from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .config import (
    BLOCKED_RESOURCE_URLS,
    PAGE_LOAD_TIMEOUT_SECONDS,
    SCRIPT_DIR,
    SCRIPT_TIMEOUT_SECONDS,
)


class PageContentError(RuntimeError):
    pass


def clean_text(element):
    return element.get_text(" ", strip=True) if element else None


def create_edge_driver():
    options = webdriver.EdgeOptions()
    options.page_load_strategy = "eager"
    options.add_argument("--lang=en-US")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_experimental_option("prefs", {
        "profile.managed_default_content_settings.images": 2,
        "profile.default_content_setting_values.notifications": 2,
    })
    for argument in ("--log-level=3", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage", "--disable-extensions", "--disable-infobars"):
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


def _wait_for_page_ready(driver, timeout=PAGE_LOAD_TIMEOUT_SECONDS):
    WebDriverWait(driver, timeout).until(lambda d: d.execute_script("return document.readyState") in ("interactive", "complete"))
    WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
