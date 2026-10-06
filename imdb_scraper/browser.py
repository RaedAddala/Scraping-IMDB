from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .config import (
    BLOCKED_RESOURCE_URLS,
    SCRIPTLESS_EXTRA_URLS,
    PAGE_LOAD_TIMEOUT_SECONDS,
    SCRIPT_DIR,
    SCRIPT_TIMEOUT_SECONDS,
)


class PageContentError(RuntimeError):
    pass


def clean_text(element):
    return element.get_text(" ", strip=True) if element else None


def create_edge_driver(log_network=False):
    options = webdriver.EdgeOptions()
    if log_network:  # diagnostics only: lets a script count requests and bytes
        options.set_capability("ms:loggingPrefs", {"performance": "ALL"})
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    options.page_load_strategy = "eager"
    options.add_argument("--lang=en-US")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_experimental_option("prefs", {
        "profile.managed_default_content_settings.images": 2,
        "profile.default_content_setting_values.notifications": 2,
        "net.network_prediction_options": 2,
    })
    for argument in (
        "--log-level=3",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-infobars",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-domain-reliability",
        "--disable-sync",
        "--disable-translate",
        "--metrics-recording-only",
        "--mute-audio",
    ):
        options.add_argument(argument)
    driver_path = SCRIPT_DIR / "edgedriver.exe"
    try:
        driver = webdriver.Edge(service=Service(executable_path=str(driver_path)), options=options)
    except SessionNotCreatedException:
        driver = webdriver.Edge(options=options)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SECONDS)
    driver.set_script_timeout(SCRIPT_TIMEOUT_SECONDS)
    try:
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": BLOCKED_RESOURCE_URLS})
    except WebDriverException:
        pass
    try:
        driver.maximize_window()
    except WebDriverException:
        driver.set_window_size(1920, 1080)
    return driver


def set_script_mode(driver, scripts_allowed):
    """Allow or block the page's scripts (and the background requests they make) for the next navigations."""
    urls = BLOCKED_RESOURCE_URLS if scripts_allowed else BLOCKED_RESOURCE_URLS + SCRIPTLESS_EXTRA_URLS
    try:
        driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": urls})
    except WebDriverException:
        pass


def _wait_for_page_ready(driver, timeout=PAGE_LOAD_TIMEOUT_SECONDS):
    WebDriverWait(driver, timeout).until(lambda d: d.execute_script("return document.readyState") in ("interactive", "complete"))
    WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
