import argparse
import ast
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.edge.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


SCRIPT_DIR = Path(__file__).resolve().parent
IMDB_BASE_URL = "https://www.imdb.com/"
BASIC_COLUMNS = [
    "Title", "Year", "Duration", "MPA", "Rating", "Votes", "meta_score",
    "description", "Movie Link",
]
ADVANCED_COLUMNS = [
    "link", "writers", "directors", "stars", "characters", "budget",
    "opening_weekend_Gross", "grossWorldWWide", "gross_US_Canada",
    "release_date", "countries_origin", "filming_locations",
    "production_company", "awards_content", "awards_wins_nominations_total",
    "critic_reviews_count", "user_reviews_count", "genres", "Languages",
    "similar_movies", "similar_movies_links", "json_ld_rating",
    "json_ld_vote_count", "json_ld_content_rating", "json_ld_keywords",
    "json_ld_poster_url", "json_ld_directors", "json_ld_writers",
    "json_ld_actors", "json_ld_runtime_minutes", "sex_nudity_severity",
    "violence_gore_severity", "profanity_severity",
    "alcohol_drugs_smoking_severity", "frightening_intense_scenes_severity",
    "producers", "composer", "cinematographer", "editor", "casting_director",
    "production_designer", "costume_designer", "release_dates_by_country",
    "aka_titles",
]
STATUS_COLUMNS = [
    "link", "title", "status", "attempt_count", "last_error",
    "last_attempted_at", "completed_at",
]
PAGE_LOAD_TIMEOUT_SECONDS = 10
CONTENT_WAIT_TIMEOUT_SECONDS = 4
PAGE_SETTLE_SECONDS = 0.3
SCROLLED_PAGE_SETTLE_SECONDS = 0.5
LOAD_MORE_BUTTON_TIMEOUT_SECONDS = 6
LOAD_MORE_RESULT_TIMEOUT_SECONDS = 10
LOAD_MORE_RETRY_PAUSE_SECONDS = 1.0
YEAR_PAUSE_SECONDS = 2.0


def clean_text(element):
    return element.get_text(" ", strip=True) if element else None


def create_edge_driver():
    options = webdriver.EdgeOptions()
    options.page_load_strategy = "eager"
    options.add_argument("--lang=en-US")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    for argument in ("--log-level=3", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage", "--disable-extensions", "--disable-infobars"):
        options.add_argument(argument)
    driver_path = SCRIPT_DIR / "edgedriver.exe"
    driver = webdriver.Edge(service=Service(executable_path=str(driver_path)), options=options)
    try:
        driver.maximize_window()
    except Exception:
        driver.set_window_size(1920, 1080)
    return driver


def _wait_for_page_ready(driver, timeout=PAGE_LOAD_TIMEOUT_SECONDS, min_pause=PAGE_SETTLE_SECONDS):
    WebDriverWait(driver, timeout).until(lambda d: d.execute_script("return document.readyState") in ("interactive", "complete"))
    WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    if min_pause:
        time.sleep(min_pause)


def _wait_for_page_text(driver, text, timeout=CONTENT_WAIT_TIMEOUT_SECONDS):
    try:
        WebDriverWait(driver, timeout).until(lambda d: text.lower() in d.find_element(By.TAG_NAME, "body").text.lower())
    except Exception:
        pass


def _wait_for_page_element(driver, locator, timeout=CONTENT_WAIT_TIMEOUT_SECONDS):
    try:
        WebDriverWait(driver, timeout).until(EC.presence_of_element_located(locator))
    except Exception:
        pass


def extract_listing_metadata(film):
    values = [clean_text(item) for item in film.select(".dli-title-metadata li.ipc-inline-list__item")]
    return tuple(values[i] if i < len(values) else None for i in range(3))


def year_paths(year):
    data_dir = SCRIPT_DIR / "Data" / str(year)
    logs_dir = SCRIPT_DIR / "Logs" / str(year)
    return {
        "data_dir": data_dir,
        "logs_dir": logs_dir,
        "basic": data_dir / f"imdb_movies_{year}.csv",
        "advanced": data_dir / f"advanced_movies_details_{year}.csv",
        "merged": data_dir / f"merged_movies_data_{year}.csv",
        "status": data_dir / f"advanced_scrape_status_{year}.csv",
        "attempts": logs_dir / f"advanced_scrape_attempts_{year}.jsonl",
    }


def setup_directories(year):
    paths = year_paths(year)
    data_dir, logs_dir = paths["data_dir"], paths["logs_dir"]
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    return data_dir, logs_dir


def setup_logging(year):
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    error_logger = logging.getLogger(f"error_logger_{year}")
    results_logger = logging.getLogger(f"results_logger_{year}")
    error_logger.setLevel(logging.ERROR)
    results_logger.setLevel(logging.INFO)
    _, logs_dir = setup_directories(year)
    for logger, filename, level in ((error_logger, "errors.txt", logging.ERROR), (results_logger, "results.txt", logging.INFO)):
        logger.propagate = False
        path = os.path.abspath(logs_dir / filename)
        if not any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == path for h in logger.handlers):
            handler = logging.FileHandler(path)
            handler.setLevel(level)
            handler.setFormatter(formatter)
            logger.addHandler(handler)
    return error_logger, results_logger


def write_csv_safely(df, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    df.to_csv(temp_path, index=False)
    temp_path.replace(path)


def read_csv_fast(path):
    try:
        return pd.read_csv(path, engine="pyarrow")
    except Exception:
        return pd.read_csv(path)


def read_csv_or_empty(path, columns):
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=columns)
    df = read_csv_fast(path)
    for column in columns:
        if column not in df.columns:
            df[column] = None
    return df


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append_attempt_log(path, event):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def _normalize_votes(element):
    value = clean_text(element)
    if value and value.startswith("(") and value.endswith(")"):
        return value[1:-1].strip()
    return value


def _normalize_imdb_url(value, keep_query=True):
    if not value:
        return None
    absolute = urljoin(IMDB_BASE_URL, value)
    parts = urlsplit(absolute)
    if not parts.path.startswith("/title/tt"):
        return absolute
    if keep_query:
        return urlunsplit(parts)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", "")) + "/"


def extract_links(year, error_logger, results_logger, max_movies=600):
    if max_movies < 0:
        raise ValueError("max_movies must be non-negative")
    start = time.time()
    url = f"https://www.imdb.com/search/title/?title_type=feature&release_date={year}-01-01,{year}-12-31&count=50&sort=boxoffice_gross_us,desc"
    films_data, loaded_data, failures = [], 0, 0
    driver = None
    try:
        driver = create_edge_driver()
        driver.get(url)
        _wait_for_page_ready(driver)
        WebDriverWait(driver, PAGE_LOAD_TIMEOUT_SECONDS).until(EC.presence_of_element_located((By.CSS_SELECTOR, "ul.ipc-metadata-list")))
        loaded_data = len(driver.find_elements(By.CSS_SELECTOR, "li.ipc-metadata-list-summary-item"))
        while loaded_data < max_movies and failures < 3:
            try:
                button = WebDriverWait(driver, LOAD_MORE_BUTTON_TIMEOUT_SECONDS).until(EC.presence_of_element_located((By.XPATH, "//button[contains(@class, 'ipc-btn') and .//span[contains(text(), '50 more')]]")))
                driver.execute_script("arguments[0].scrollIntoView(true);", button)
                driver.execute_script("arguments[0].click();", button)
                old_count = loaded_data
                WebDriverWait(driver, LOAD_MORE_RESULT_TIMEOUT_SECONDS).until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "li.ipc-metadata-list-summary-item")) > old_count)
                _wait_for_page_ready(driver)
                loaded_data = len(driver.find_elements(By.CSS_SELECTOR, "li.ipc-metadata-list-summary-item"))
                failures = 0
            except Exception as exc:
                failures += 1
                error_logger.error("Load more attempt %s failed after %s items: %s", failures, loaded_data, exc)
                time.sleep(LOAD_MORE_RETRY_PAUSE_SECONDS)
        soup = BeautifulSoup(driver.page_source, "lxml")
        container = soup.select_one("ul.ipc-metadata-list")
        for film in (container.find_all("li", class_="ipc-metadata-list-summary-item") if container else [])[:max_movies]:
            try:
                title_tag = film.select_one("a.ipc-title-link-wrapper")
                link_tag = film.select_one("a.ipc-lockup-overlay[href]")
                href = link_tag.get("href", "") if link_tag else ""
                listed_year, duration, mpa = extract_listing_metadata(film)
                films_data.append({
                    "Title": clean_text(title_tag),
                    "Year": listed_year,
                    "Duration": duration,
                    "MPA": mpa,
                    "Rating": clean_text(film.find("span", class_="ipc-rating-star--rating")),
                    "Votes": _normalize_votes(film.find("span", class_="ipc-rating-star--voteCount")),
                    "meta_score": clean_text(film.find("span", class_="metacritic-score-box")),
                    "description": clean_text(film.find("div", class_="ipc-html-content-inner-div")),
                    "Movie Link": _normalize_imdb_url(href),
                })
            except Exception as exc:
                error_logger.error("Error extracting listing item: %s", exc)
        results_logger.info("Loaded %s items; extracted %s movies in %.2f seconds", loaded_data, len(films_data), time.time() - start)
    except Exception as exc:
        error_logger.error("Error during link extraction: %s", exc)
    finally:
        if driver is not None:
            driver.quit()
    return pd.DataFrame(films_data, columns=BASIC_COLUMNS)


def _as_list(value):
    return [] if value is None else value if isinstance(value, list) else [value]


def _persons(value):
    return [person["name"] for person in _as_list(value) if isinstance(person, dict) and person.get("name")]


def _iso8601_to_minutes(duration):
    if not duration:
        return None
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", str(duration))
    if not match:
        return None
    return (int(match.group(1) or 0) * 60) + int(match.group(2) or 0)


def _title_base_url(url):
    match = re.search(r"https?://[^/]+/title/tt\d+", str(url))
    if match:
        return match.group(0) + "/"
    return _normalize_imdb_url(str(url), keep_query=False) or ""


PARENTAL_GUIDE_CATEGORIES = {
    "sex_nudity_severity": "Sex & Nudity",
    "violence_gore_severity": "Violence & Gore",
    "profanity_severity": "Profanity",
    "alcohol_drugs_smoking_severity": "Alcohol, Drugs & Smoking",
    "frightening_intense_scenes_severity": "Frightening & Intense Scenes",
}
FULL_CREDITS_DEPARTMENTS = {
    "producers": "Produced by", "composer": "Music by", "cinematographer": "Cinematography by",
    "editor": "Film Editing by", "casting_director": "Casting By", "production_designer": "Production Design by", "costume_designer": "Costume Design by",
}


def _page_soup(driver, url, wait_for_text=None):
    driver.get(url)
    _wait_for_page_ready(driver)
    if wait_for_text:
        _wait_for_page_text(driver, wait_for_text)
    return BeautifulSoup(driver.page_source, "lxml")


def extract_parental_guide(driver, base_url, error_logger):
    result = {key: None for key in PARENTAL_GUIDE_CATEGORIES}
    try:
        text = _page_soup(driver, base_url + "parentalguide/", wait_for_text="Frightening & Intense Scenes").get_text(" ", strip=True)
        for key, label in PARENTAL_GUIDE_CATEGORIES.items():
            flexible_label = re.escape(label).replace(r"\ ", r"\s+")
            match = re.search(flexible_label + r"\s*:?\s*(None|Mild|Moderate|Severe)", text, re.I)
            if match:
                result[key] = match.group(1)
    except Exception as exc:
        error_logger.error("Error extracting parental guide for %s: %s", base_url, exc)
    return result


def extract_full_credits(driver, base_url, error_logger):
    result = {key: None for key in FULL_CREDITS_DEPARTMENTS}
    try:
        soup = _page_soup(driver, base_url + "fullcredits/", wait_for_text="Costume Design by")
        for key, heading_text in FULL_CREDITS_DEPARTMENTS.items():
            heading = soup.find(string=lambda value: value and heading_text.lower() in value.lower())
            if not heading:
                continue
            parent = heading.find_parent()
            container = parent.find_next(["table", "ul"]) if parent else None
            names = [clean_text(a) for a in container.find_all("a", href=re.compile(r"^/name/nm"))] if container else []
            result[key] = list(dict.fromkeys(name for name in names if name)) or None
    except Exception as exc:
        error_logger.error("Error extracting full credits for %s: %s", base_url, exc)
    return result


def extract_release_info(driver, base_url, error_logger):
    result = {"release_dates_by_country": None, "aka_titles": None}
    try:
        soup = _page_soup(driver, base_url + "releaseinfo/", wait_for_text="Also known as")
        def pairs_after(label):
            heading = soup.find(string=lambda value: value and label.lower() in value.lower())
            container = heading.find_parent().find_next(["table", "ul"]) if heading else None
            pairs = []
            rows = container.find_all("tr") if container and container.find_all("tr") else container.find_all("li") if container else []
            for row in rows:
                cells = [clean_text(cell) for cell in row.find_all("td", recursive=False) if clean_text(cell)]
                if not cells:
                    cells = [clean_text(cell) for cell in row.find_all(["a", "span"], recursive=False) if clean_text(cell)]
                if len(cells) >= 2:
                    pairs.append(f"{cells[0]}: {cells[1]}")
            return pairs or None
        result["release_dates_by_country"] = pairs_after("Release date")
        result["aka_titles"] = pairs_after("Also known as")
    except Exception as exc:
        error_logger.error("Error extracting release info for %s: %s", base_url, exc)
    return result


def _text_in(soup, testid):
    item = soup.find(["li", "div"], {"data-testid": testid})
    value = item.find(class_="ipc-metadata-list-item__list-content-item") if item else None
    return clean_text(value)


def _extract_principal_credits(soup):
    result = {"writers": None, "directors": None}
    for item in soup.find_all("li", class_="ipc-metadata-list__item"):
        label = clean_text(item.find(["a", "span"], class_="ipc-metadata-list-item__label"))
        if not label:
            continue
        values = [clean_text(a) for a in item.find_all("a", class_="ipc-metadata-list-item__list-content-item")]
        if "director" in label.lower() and values:
            result["directors"] = values
        elif "writer" in label.lower() and values:
            result["writers"] = values
    return result


def _extract_cast(soup):
    stars, characters = [], []
    for item in soup.find_all("div", {"data-testid": "title-cast-item"}):
        actor = item.find("a", {"data-testid": "title-cast-item__actor"})
        if not actor:
            continue
        character = item.find(["a", "span"], {"data-testid": "cast-item-characters-link"})
        stars.append(clean_text(actor))
        characters.append(clean_text(character))
    return (stars or None), (characters or None)


def _extract_json_ld(soup):
    result = {"json_ld_rating": None, "json_ld_vote_count": None, "json_ld_content_rating": None, "json_ld_keywords": None, "json_ld_poster_url": None, "json_ld_directors": None, "json_ld_writers": None, "json_ld_actors": None, "json_ld_runtime_minutes": None}
    data = None
    for tag in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            parsed = json.loads(tag.string or tag.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        candidates = parsed if isinstance(parsed, list) else [parsed]
        graph = [item for item in candidates if isinstance(item, dict) and isinstance(item.get("@graph"), list)]
        candidates.extend(item for item in graph for item in item["@graph"])
        def is_movie(item):
            if not isinstance(item, dict):
                return False
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            return bool(item.get("aggregateRating") or "Movie" in types)

        data = next((item for item in candidates if is_movie(item)), None)
        if data:
            break
    if not data:
        return result
    aggregate = data.get("aggregateRating") or {}
    result.update(json_ld_rating=aggregate.get("ratingValue"), json_ld_vote_count=aggregate.get("ratingCount"), json_ld_content_rating=data.get("contentRating"), json_ld_keywords=data.get("keywords"), json_ld_poster_url=data.get("image"), json_ld_directors=_persons(data.get("director")), json_ld_writers=_persons(data.get("creator")), json_ld_actors=_persons(data.get("actor")), json_ld_runtime_minutes=_iso8601_to_minutes(data.get("duration")))
    return result


def _extract_advanced_row(driver, url, error_logger):
    driver.get(url)
    _wait_for_page_ready(driver)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    _wait_for_page_ready(driver, min_pause=SCROLLED_PAGE_SETTLE_SECONDS)
    _wait_for_page_element(driver, (By.XPATH, "//*[self::section or self::div][contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'more like this')]"))
    soup = BeautifulSoup(driver.page_source, "lxml")
    row = {"link": url, "writers": None, "directors": None, "stars": None, "characters": None, "budget": _text_in(soup, "title-boxoffice-budget"), "opening_weekend_Gross": _text_in(soup, "title-boxoffice-openingweekenddomestic"), "grossWorldWWide": _text_in(soup, "title-boxoffice-cumulativeworldwidegross"), "gross_US_Canada": _text_in(soup, "title-boxoffice-grossdomestic"), "release_date": None, "countries_origin": None, "filming_locations": None, "production_company": None, "awards_content": None, "awards_wins_nominations_total": None, "critic_reviews_count": None, "user_reviews_count": None, "genres": [], "Languages": [], "similar_movies": None, "similar_movies_links": None}
    row.update(_extract_json_ld(soup))
    row.update(_extract_principal_credits(soup))
    row["stars"], row["characters"] = _extract_cast(soup)
    for key, testid in (("release_date", "title-details-releasedate"), ("production_company", "title-details-companies")):
        item = soup.find("li", {"data-testid": testid})
        if item:
            values = [clean_text(a) for a in item.find_all("a", class_="ipc-metadata-list-item__list-content-item")]
            row[key] = values[0].split(" (")[0] if key == "release_date" and values else values or None
    origin = soup.find("li", {"data-testid": "title-details-origin"})
    row["countries_origin"] = [clean_text(a) for a in origin.find_all("a", class_="ipc-metadata-list-item__list-content-item")] if origin else None
    filming = soup.find("li", {"data-testid": "title-details-filminglocations"})
    if filming:
        locations = []
        for item in filming.select("li.ipc-inline-list__item"):
            link_text = clean_text(item.find("a"))
            extra_text = clean_text(item.find("span"))
            value = " ".join(part for part in (link_text, extra_text) if part) or clean_text(item)
            if value:
                locations.append(value)
        row["filming_locations"] = locations or None
    interests = soup.find("div", {"data-testid": "interests"})
    row["genres"] = [clean_text(x) for x in interests.find_all("span", class_="ipc-chip__text")] if interests else []
    language = soup.find("li", {"data-testid": "title-details-languages"})
    row["Languages"] = [clean_text(a) for a in language.find_all("a", class_="ipc-metadata-list-item__list-content-item")] if language else []
    awards = soup.find("div", {"data-testid": "awards"})
    if awards:
        row["awards_content"] = clean_text(awards)
        match = re.search(r"[\d,]+\s+wins?\s*&\s*[\d,]+\s+nominations?(?:\s+total)?", clean_text(awards) or "", re.I)
        row["awards_wins_nominations_total"] = match.group(0) if match else None
    for anchor in soup.find_all("a", href=True):
        href, text = anchor["href"].split("?")[0].rstrip("/"), clean_text(anchor)
        if href.endswith("/reviews") and "external" not in href:
            row["user_reviews_count"] = text
        elif href.endswith("/externalreviews"):
            row["critic_reviews_count"] = text
    section = soup.find(lambda tag: tag.name in ("section", "div") and "more like this" in (tag.get("aria-label") or "").lower())
    if section:
        pairs = [(clean_text(a), _normalize_imdb_url(a["href"], keep_query=False)) for a in section.find_all("a", href=True) if "/title/tt" in a["href"] and clean_text(a)]
        pairs = list(dict.fromkeys(pairs))
        row["similar_movies"], row["similar_movies_links"] = ([p[0] for p in pairs] or None), ([p[1] for p in pairs] or None)
    base = _title_base_url(url)
    row.update(extract_parental_guide(driver, base, error_logger))
    row.update(extract_full_credits(driver, base, error_logger))
    row.update(extract_release_info(driver, base, error_logger))
    return row


def _string_or_none(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return str(value)


def _links_from_df(links_df):
    link_column = "Movie Link" if "Movie Link" in links_df.columns else "link" if "link" in links_df.columns else None
    if not link_column:
        return []
    title_column = "Title" if "Title" in links_df.columns else "title" if "title" in links_df.columns else None
    records = []
    for _, item in links_df.iterrows():
        link = _string_or_none(item.get(link_column))
        if not link:
            continue
        records.append({"link": link, "title": _string_or_none(item.get(title_column)) if title_column else None})
    return list({record["link"]: record for record in records}.values())


def _status_records(status_df):
    records = {}
    for _, item in status_df.iterrows():
        link = _string_or_none(item.get("link"))
        if not link:
            continue
        records[link] = {column: _string_or_none(item.get(column)) for column in STATUS_COLUMNS}
        try:
            records[link]["attempt_count"] = int(float(records[link].get("attempt_count") or 0))
        except ValueError:
            records[link]["attempt_count"] = 0
    return records


def _write_status(path, records):
    rows = []
    for record in records.values():
        rows.append({column: record.get(column) for column in STATUS_COLUMNS})
    write_csv_safely(pd.DataFrame(rows, columns=STATUS_COLUMNS), path)


def _combine_advanced(existing_df, new_rows):
    new_df = pd.DataFrame(new_rows, columns=ADVANCED_COLUMNS)
    combined = pd.concat([existing_df, new_df], ignore_index=True)
    if "link" in combined.columns:
        combined = combined.dropna(subset=["link"]).drop_duplicates(subset=["link"], keep="last")
    for column in ADVANCED_COLUMNS:
        if column not in combined.columns:
            combined[column] = None
    return combined[ADVANCED_COLUMNS]


def _attempt_advanced_links(driver, link_records, status_records, attempt_log_path, error_logger, phase):
    rows, failures = [], []
    for record in link_records:
        link, title = record["link"], record.get("title")
        status = status_records.setdefault(link, {
            "link": link, "title": title, "status": "pending", "attempt_count": 0,
            "last_error": None, "last_attempted_at": None, "completed_at": None,
        })
        if title and not status.get("title"):
            status["title"] = title
        status["attempt_count"] = int(status.get("attempt_count") or 0) + 1
        status["last_attempted_at"] = now_iso()
        try:
            row = _extract_advanced_row(driver, link, error_logger)
            rows.append(row)
            status.update(status="completed", last_error=None, completed_at=now_iso())
            append_attempt_log(attempt_log_path, {"timestamp": now_iso(), "phase": phase, "link": link, "title": status.get("title"), "status": "completed", "attempt_count": status["attempt_count"]})
        except Exception as exc:
            message = str(exc)
            status.update(status="failed", last_error=message, completed_at=None)
            failures.append(record)
            append_attempt_log(attempt_log_path, {"timestamp": now_iso(), "phase": phase, "link": link, "title": status.get("title"), "status": "failed", "attempt_count": status["attempt_count"], "error": message})
            error_logger.error("Error processing URL %s: %s", link, exc)
    return rows, failures


def extract_advanced_data(year, links_df, error_logger, results_logger, retry_failed_only=False):
    start = time.time()
    paths = year_paths(year)
    link_records = _links_from_df(links_df)
    if not link_records:
        error_logger.error("Advanced extraction requires a 'Movie Link' or 'link' column with at least one URL")
        return read_csv_or_empty(paths["advanced"], ADVANCED_COLUMNS)

    existing_advanced = read_csv_or_empty(paths["advanced"], ADVANCED_COLUMNS)
    completed_links = set(existing_advanced["link"].dropna().astype(str)) if "link" in existing_advanced else set()
    status_records = _status_records(read_csv_or_empty(paths["status"], STATUS_COLUMNS))
    for record in link_records:
        status = status_records.setdefault(record["link"], {
            "link": record["link"], "title": record.get("title"), "status": "pending",
            "attempt_count": 0, "last_error": None, "last_attempted_at": None, "completed_at": None,
        })
        if record.get("title") and not status.get("title"):
            status["title"] = record["title"]
        if record["link"] in completed_links and status.get("status") != "completed":
            status.update(status="completed", last_error=None, completed_at=status.get("completed_at") or now_iso())

    if retry_failed_only:
        candidates = [record for record in link_records if status_records.get(record["link"], {}).get("status") == "failed"]
    else:
        candidates = [record for record in link_records if status_records.get(record["link"], {}).get("status") != "completed"]

    rows, failures = [], []
    driver = None
    try:
        if candidates:
            driver = create_edge_driver()
            first_rows, failures = _attempt_advanced_links(driver, candidates, status_records, paths["attempts"], error_logger, "retry" if retry_failed_only else "initial")
            rows.extend(first_rows)
            if failures and not retry_failed_only:
                results_logger.info("Retrying %s failed advanced links for %s once", len(failures), year)
                retry_rows, failures = _attempt_advanced_links(driver, failures, status_records, paths["attempts"], error_logger, "auto_retry")
                rows.extend(retry_rows)
    finally:
        if driver is not None:
            driver.quit()

    advanced = _combine_advanced(existing_advanced, rows)
    _write_status(paths["status"], status_records)
    write_csv_safely(advanced, paths["advanced"])
    results_logger.info(
        "Advanced extraction completed for %s: %s new rows, %s total rows, %s unresolved failures, %.2f seconds",
        year, len(rows), len(advanced), len(failures), time.time() - start,
    )
    return advanced


def merge_data(year, data_dir, error_logger, results_logger):
    try:
        paths = year_paths(year)
        basic = read_csv_fast(paths["basic"])
        advanced = read_csv_or_empty(paths["advanced"], ADVANCED_COLUMNS)
        if "Movie Link" not in basic.columns or "link" not in advanced.columns:
            raise ValueError("Input CSVs are missing the movie-link join column")
        advanced = advanced.rename(columns={"link": "Movie Link"})
        merged = pd.merge(basic, advanced, how="left", on="Movie Link")
        results_logger.info("Merged %s basic rows with %s advanced rows into %s rows for %s", len(basic), len(advanced), len(merged), year)
        return merged
    except Exception as exc:
        error_logger.error("Error merging data for year %s: %s", year, exc)
        return None


def _safe_list_len(value):
    if isinstance(value, (list, tuple)):
        return len(value)
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0
    try:
        parsed = ast.literal_eval(str(value))
        return len(parsed) if isinstance(parsed, (list, tuple)) else 0
    except (ValueError, SyntaxError):
        return 0


def _parse_money(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    match = re.search(r"([\d][\d,]*(?:\.\d+)?)\s*(billion|million|bn|m|b|k)?", str(value), re.I)
    if not match:
        return None
    number = float(match.group(1).replace(",", ""))
    multiplier = {"k": 1_000, "m": 1_000_000, "million": 1_000_000, "b": 1_000_000_000, "bn": 1_000_000_000, "billion": 1_000_000_000}
    return number * multiplier.get((match.group(2) or "").lower(), 1)


def _currency_symbol(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    match = re.search(r"[$\u20ac\u00a3\u00a5\u20b9]|(?:USD|EUR|GBP|JPY|INR)\b", str(value), re.I)
    return match.group(0).upper() if match else None


def _same_or_unknown_currency(left, right):
    left_currency, right_currency = _currency_symbol(left), _currency_symbol(right)
    return left_currency is None or right_currency is None or left_currency == right_currency


def _parse_runtime_to_minutes(value):
    if pd.isna(value):
        return None
    text = str(value)
    hours, minutes = re.search(r"(\d+)\s*h", text, re.I), re.search(r"(\d+)\s*m", text, re.I)
    if hours or minutes:
        return (int(hours.group(1)) * 60 if hours else 0) + (int(minutes.group(1)) if minutes else 0)
    match = re.fullmatch(r"\s*(\d+)\s*", text)
    return int(match.group(1)) if match else None


def _parse_release_dates(series):
    try:
        return pd.to_datetime(series, errors="coerce", format="mixed")
    except ValueError:
        return series.apply(lambda value: pd.to_datetime(value, errors="coerce"))


def _release_date_has_day(value):
    return bool(re.search(r"\b\d{1,2},\s+\d{4}\b|\b\d{4}-\d{1,2}-\d{1,2}\b", str(value)))


def compute_derived_columns(df, error_logger, results_logger):
    try:
        for source, target in (("budget", "budget_numeric"), ("grossWorldWWide", "grossWorldWWide_numeric"), ("gross_US_Canada", "gross_US_Canada_numeric"), ("opening_weekend_Gross", "opening_weekend_numeric")):
            df[target] = df[source].apply(_parse_money) if source in df else float("nan")
        if "budget" in df and "grossWorldWWide" in df:
            comparable_currency = df.apply(lambda row: _same_or_unknown_currency(row["budget"], row["grossWorldWWide"]), axis=1)
        else:
            comparable_currency = pd.Series(False, index=df.index)
        df["profit"] = (df["grossWorldWWide_numeric"] - df["budget_numeric"]).where(comparable_currency)
        df["roi"] = df["profit"].div(df["budget_numeric"].replace(0, float("nan")))
        awards = df["awards_wins_nominations_total"].astype(str) if "awards_wins_nominations_total" in df else pd.Series(index=df.index, dtype="string")
        extracted = awards.str.extract(r"([\d,]+)\s+wins?\s*&\s*([\d,]+)\s+nominations?", expand=True)
        df["total_wins"] = pd.to_numeric(extracted[0].str.replace(",", "", regex=False), errors="coerce")
        df["total_nominations"] = pd.to_numeric(extracted[1].str.replace(",", "", regex=False), errors="coerce")
        df["runtime_minutes"] = df["Duration"].apply(_parse_runtime_to_minutes) if "Duration" in df else float("nan")
        dates = _parse_release_dates(df["release_date"]) if "release_date" in df else pd.Series(pd.NaT, index=df.index)
        has_release_day = df["release_date"].apply(_release_date_has_day) if "release_date" in df else pd.Series(False, index=df.index)
        df["release_month"], df["release_decade"] = dates.dt.month, dates.dt.year // 10 * 10
        df["release_weekday"] = dates.dt.day_name().where(has_release_day)
        for source, target in (("stars", "cast_size"), ("genres", "genre_count"), ("countries_origin", "country_count")):
            df[target] = df[source].apply(_safe_list_len) if source in df else 0
        if "Rating" in df and "json_ld_rating" in df:
            left = pd.to_numeric(df["Rating"], errors="coerce")
            right = pd.to_numeric(df["json_ld_rating"], errors="coerce")
            df["rating_mismatch"] = ((left - right).abs() > 0.15).where(left.notna() & right.notna())
        else:
            df["rating_mismatch"] = pd.Series(pd.NA, index=df.index, dtype="boolean")
        results_logger.info("Computed derived columns for %s merged rows", len(df))
    except Exception as exc:
        error_logger.error("Error computing derived columns: %s", exc)
    return df


def process_year(year, max_movies=1000):
    print(f"Starting processing for year {year}")
    start = time.time()
    data_dir, _ = setup_directories(year)
    paths = year_paths(year)
    error_logger, results_logger = setup_logging(year)
    try:
        links = extract_links(year, error_logger, results_logger, max_movies)
        write_csv_safely(links, paths["basic"])
        extract_advanced_data(year, links, error_logger, results_logger)
        merged = merge_data(year, data_dir, error_logger, results_logger)
        if merged is not None:
            write_csv_safely(compute_derived_columns(merged, error_logger, results_logger), paths["merged"])
        print(f"Processing completed for year {year} in {time.time() - start:.2f} seconds")
    except Exception as exc:
        error_logger.error("Critical error during processing for year %s: %s", year, exc)
        print(f"Error: Processing failed for year {year}: {exc}")


def retry_failed_year(year):
    print(f"Retrying failed advanced links for year {year}")
    start = time.time()
    data_dir, _ = setup_directories(year)
    paths = year_paths(year)
    error_logger, results_logger = setup_logging(year)
    status = read_csv_or_empty(paths["status"], STATUS_COLUMNS)
    failed = status[status["status"] == "failed"] if "status" in status else pd.DataFrame(columns=STATUS_COLUMNS)
    if failed.empty:
        results_logger.info("No failed advanced links to retry for %s", year)
        print(f"No failed advanced links to retry for year {year}")
        return
    retry_links = failed.rename(columns={"link": "Movie Link", "title": "Title"})
    extract_advanced_data(year, retry_links, error_logger, results_logger, retry_failed_only=True)
    merged = merge_data(year, data_dir, error_logger, results_logger)
    if merged is not None:
        write_csv_safely(compute_derived_columns(merged, error_logger, results_logger), paths["merged"])
    print(f"Retry completed for year {year} in {time.time() - start:.2f} seconds")


def main():
    parser = argparse.ArgumentParser(description="Scrape IMDb movie data by year.")
    parser.add_argument("--start-year", type=int, default=1941)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--max-movies", type=int, default=1000)
    parser.add_argument("--retry-failed", action="store_true", help="Retry only links marked failed in the advanced scrape status file.")
    args = parser.parse_args()
    for year in range(args.start_year, args.end_year + 1):
        action = "Retrying failed links" if args.retry_failed else "Processing year"
        print(f"\n{'=' * 50}\n{action} {year}\n{'=' * 50}")
        if args.retry_failed:
            retry_failed_year(year)
        else:
            process_year(year, args.max_movies)
        if year < args.end_year:
            time.sleep(YEAR_PAUSE_SECONDS)


if __name__ == "__main__":
    main()
