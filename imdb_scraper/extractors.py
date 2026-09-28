import json
import re
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

import pandas as pd
from bs4 import BeautifulSoup
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .browser import (
    PageContentError,
    _wait_for_page_ready,
    clean_text,
    create_edge_driver,
)
from .config import (
    ADVANCED_COLUMNS,
    ADVANCED_STAGES,
    BASIC_COLUMNS,
    FULL_CREDITS_DEPARTMENTS,
    IMDB_BASE_URL,
    LOAD_MORE_BUTTON_TIMEOUT_SECONDS,
    LOAD_MORE_RESULT_TIMEOUT_SECONDS,
    LOAD_MORE_RETRY_PAUSE_SECONDS,
    PAGE_LOAD_TIMEOUT_SECONDS,
    PARENTAL_GUIDE_CATEGORIES,
    REQUIRED_CONTENT_TIMEOUT_SECONDS,
    SCRAPE_VERSION,
    STAGE_FIELDS,
)


class StageExtractionError(RuntimeError):
    def __init__(self, stage, partial_row, remaining_stages, cause):
        super().__init__(f"{stage} failed: {type(cause).__name__}: {cause}")
        self.stage = stage
        self.partial_row = partial_row
        self.remaining_stages = list(remaining_stages)
        self.cause = cause


def extract_listing_metadata(film):
    values = [clean_text(item) for item in film.select(".dli-title-metadata li.ipc-inline-list__item")]
    return tuple(values[i] if i < len(values) else None for i in range(3))


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
        try:
            driver.get(url)
        except TimeoutException:
            driver.execute_script("window.stop()")
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


def _next_data(soup):
    tag = soup.select_one("script#__NEXT_DATA__")
    if not tag:
        return None
    try:
        return json.loads(tag.string or tag.get_text())
    except (TypeError, json.JSONDecodeError):
        return None


def _next_content_data(soup):
    data = _next_data(soup) or {}
    content = data.get("props", {}).get("pageProps", {}).get("contentData")
    return content if isinstance(content, dict) else None


def _content_title_id(content):
    if not isinstance(content, dict):
        return None
    return content.get("entityMetadata", {}).get("id") or content.get("data", {}).get("title", {}).get("id")


def _soup_title_id(soup):
    content = _next_content_data(soup) or {}
    entity_id = content.get("entityMetadata", {}).get("id")
    if entity_id:
        return entity_id
    data_id = content.get("data", {}).get("title", {}).get("id")
    if data_id:
        return data_id
    for tag in soup.select("script[type='application/ld+json']"):
        match = re.search(r"\btt\d+\b", tag.string or tag.get_text())
        if match:
            return match.group(0)
    return None


def _expected_title_id(url):
    match = re.search(r"/title/(tt\d+)", str(url))
    return match.group(1) if match else None


def _is_expected_imdb_page(soup, url, stage):
    page_title = clean_text(soup.title) or ""
    if "privacy error" in page_title.lower() or "preventing microsoft edge" in soup.get_text(" ", strip=True).lower():
        return False
    expected_id = _expected_title_id(url)
    actual_id = _soup_title_id(soup)
    if expected_id and actual_id != expected_id:
        return False
    if stage == "title_page":
        return bool(actual_id and (soup.select_one("script[type='application/ld+json']") or _next_data(soup)))
    return bool(actual_id and _next_content_data(soup))


def _page_soup(driver, url, timings=None, stage=None):
    started_at = time.perf_counter()
    navigation_timed_out = False
    try:
        try:
            driver.get(url)
        except TimeoutException:
            navigation_timed_out = True
            try:
                driver.execute_script("window.stop()")
            except WebDriverException:
                pass

        selector = "script[type='application/ld+json'], script#__NEXT_DATA__" if stage == "title_page" else "script#__NEXT_DATA__"
        try:
            WebDriverWait(driver, REQUIRED_CONTENT_TIMEOUT_SECONDS).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
        except TimeoutException:
            pass
        soup = BeautifulSoup(driver.page_source, "lxml")
        content_ready = _is_expected_imdb_page(soup, url, stage)
        if timings is not None and stage:
            timings[f"{stage}_content_ready"] = content_ready
            timings[f"{stage}_navigation_timed_out"] = navigation_timed_out
        if not content_ready:
            raise PageContentError(f"IMDb returned an invalid or incomplete {stage} page for {url}")
        return soup
    finally:
        if timings is not None and stage:
            timings[f"{stage}_seconds"] = round(time.perf_counter() - started_at, 3)


def _page_content_data(driver, url, timings=None, stage=None):
    started_at = time.perf_counter()
    navigation_timed_out = False
    try:
        try:
            driver.get(url)
        except TimeoutException:
            navigation_timed_out = True
            try:
                driver.execute_script("window.stop()")
            except WebDriverException:
                pass
        try:
            WebDriverWait(driver, REQUIRED_CONTENT_TIMEOUT_SECONDS).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "script#__NEXT_DATA__"))
            )
        except TimeoutException:
            pass
        raw = driver.execute_script(
            "return document.querySelector('script#__NEXT_DATA__')?.textContent || null"
        )
        try:
            data = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            data = None
        content = (data or {}).get("props", {}).get("pageProps", {}).get("contentData")
        expected_id = _expected_title_id(url)
        actual_id = _content_title_id(content)
        page_title = driver.title or ""
        content_ready = bool(
            isinstance(content, dict)
            and actual_id
            and (not expected_id or actual_id == expected_id)
            and "privacy error" not in page_title.lower()
        )
        if timings is not None and stage:
            timings[f"{stage}_content_ready"] = content_ready
            timings[f"{stage}_navigation_timed_out"] = navigation_timed_out
        if not content_ready:
            raise PageContentError(f"IMDb returned an invalid or incomplete {stage} page for {url}")
        return content
    finally:
        if timings is not None and stage:
            timings[f"{stage}_seconds"] = round(time.perf_counter() - started_at, 3)


def extract_parental_guide(driver, base_url, error_logger, timings=None):
    result = {key: None for key in PARENTAL_GUIDE_CATEGORIES}
    try:
        content = _page_content_data(driver, base_url + "parentalguide/", timings=timings, stage="parental_guide")
        summaries = content.get("contentRatingData", {}).get("categorySummaries") or []
        by_title = {
            str(item.get("title", "")).casefold(): item.get("severitySummaryText")
            for item in summaries if isinstance(item, dict)
        }
        for key, label in PARENTAL_GUIDE_CATEGORIES.items():
            result[key] = by_title.get(label.casefold())
        if not any(result.values()):
            soup = BeautifulSoup(driver.page_source, "lxml")
            text = soup.get_text(" ", strip=True)
            for key, label in PARENTAL_GUIDE_CATEGORIES.items():
                flexible_label = re.escape(label).replace(r"\ ", r"\s+")
                match = re.search(flexible_label + r"\s*:?\s*(None|Mild|Moderate|Severe)", text, re.I)
                if match:
                    result[key] = match.group(1)
    except (PageContentError, WebDriverException):
        raise
    except Exception as exc:
        error_logger.error("Error extracting parental guide for %s: %s", base_url, exc)
    return result


def extract_full_credits(driver, base_url, error_logger, timings=None):
    result = {key: None for key in FULL_CREDITS_DEPARTMENTS}
    try:
        content = _page_content_data(driver, base_url + "fullcredits/", timings=timings, stage="full_credits")
        categories = {
            str(category.get("name", "")).casefold(): category
            for category in content.get("categories", []) if isinstance(category, dict)
        }
        fallback_soup = None
        for key, heading_text in FULL_CREDITS_DEPARTMENTS.items():
            category = categories.get(heading_text.casefold()) or {}
            items = category.get("section", {}).get("items") or []
            names = [item.get("rowTitle") for item in items if isinstance(item, dict) and item.get("rowTitle")]
            if not names:
                if fallback_soup is None:
                    fallback_soup = BeautifulSoup(driver.page_source, "lxml")
                heading = fallback_soup.find(
                    ["h2", "h3", "h4"],
                    string=lambda value: value and value.strip().casefold() == heading_text.casefold(),
                )
                section = heading.find_parent("section") if heading else None
                names = [clean_text(a) for a in section.select("a[href^='/name/nm']")] if section else []
            result[key] = list(dict.fromkeys(name for name in names if name)) or None
    except (PageContentError, WebDriverException):
        raise
    except Exception as exc:
        error_logger.error("Error extracting full credits for %s: %s", base_url, exc)
    return result


def _expand_release_info(driver):
    result = {"release_dates_by_country": None, "aka_titles": None}
    for section_id, key in (("releases", "release_dates_by_country"), ("akas", "aka_titles")):
        for _ in range(10):
            try:
                section = driver.find_element(By.XPATH, f"//span[@id='{section_id}']/ancestor::section[1]")
            except WebDriverException:
                break
            buttons = section.find_elements(By.XPATH, ".//button[contains(translate(normalize-space(.), 'MORE', 'more'), 'more')]")
            button = next((item for item in buttons if re.fullmatch(r"\d+\s+more", item.text.strip(), re.I)), None)
            if not button:
                break
            before = len(section.text)
            try:
                driver.execute_script("arguments[0].click()", button)
                WebDriverWait(driver, REQUIRED_CONTENT_TIMEOUT_SECONDS + 2).until(
                    lambda d: len(d.find_element(By.XPATH, f"//span[@id='{section_id}']/ancestor::section[1]").text) > before
                )
            except WebDriverException:
                break
        try:
            section = driver.find_element(By.XPATH, f"//span[@id='{section_id}']/ancestor::section[1]")
        except WebDriverException:
            continue
        pairs = []
        for item in section.find_elements(By.CSS_SELECTOR, "li.ipc-metadata-list__item"):
            lines = [line.strip() for line in item.text.splitlines() if line.strip()]
            if len(lines) >= 2:
                value = re.sub(r"(?<=\w)\(", " (", " ".join(lines[1:]))
                pairs.append(f"{lines[0]}: {value}")
        result[key] = list(dict.fromkeys(pairs)) or None
    return result


def extract_release_info(driver, base_url, error_logger, timings=None, complete=False):
    result = {"release_dates_by_country": None, "aka_titles": None}
    try:
        content = _page_content_data(driver, base_url + "releaseinfo/", timings=timings, stage="release_info")
        categories = {
            str(category.get("id", "")).casefold(): category
            for category in content.get("categories", []) if isinstance(category, dict)
        }

        def structured_pairs(category_id):
            category = categories.get(category_id) or {}
            pairs = []
            for item in category.get("section", {}).get("items") or []:
                if not isinstance(item, dict) or not item.get("rowTitle"):
                    continue
                values = []
                for value in item.get("listContent") or []:
                    if not isinstance(value, dict) or not value.get("text"):
                        continue
                    text = value["text"]
                    if value.get("subText"):
                        text = f"{text} {value['subText']}"
                    values.append(text)
                if values:
                    pairs.append(f"{item['rowTitle']}: {'; '.join(values)}")
            return pairs or None

        result["release_dates_by_country"] = structured_pairs("releases")
        result["aka_titles"] = structured_pairs("akas")
        if complete:
            expansion_started = time.perf_counter()
            expanded = _expand_release_info(driver)
            result.update({key: value or result[key] for key, value in expanded.items()})
            if timings is not None:
                expansion_seconds = round(time.perf_counter() - expansion_started, 3)
                timings["release_info_expansion_seconds"] = expansion_seconds
                timings["release_info_seconds"] = round(timings.get("release_info_seconds", 0) + expansion_seconds, 3)
    except (PageContentError, WebDriverException):
        raise
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


def _is_missing_value(value):
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _advanced_row_template(url, existing_row=None):
    row = {column: None for column in ADVANCED_COLUMNS}
    row.update({"link": url, "genres": [], "Languages": []})
    if existing_row:
        for column in ADVANCED_COLUMNS:
            value = existing_row.get(column)
            if not _is_missing_value(value):
                row[column] = value
    row["link"] = url
    return row


def _extract_advanced_row(driver, url, error_logger, timings=None, stages=None, existing_row=None, complete_release_info=False):
    stages = tuple(stages or ADVANCED_STAGES)
    row = _advanced_row_template(url, existing_row)
    for stage in stages:
        for field in STAGE_FIELDS[stage]:
            row[field] = [] if field in ("genres", "Languages") else None

    if "title_page" in stages:
        soup = _page_soup(driver, url, timings=timings, stage="title_page")
        if not soup.find(lambda tag: tag.name in ("section", "div") and "more like this" in (tag.get("aria-label") or "").lower()):
            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                scrolled_soup = BeautifulSoup(driver.page_source, "lxml")
                if _is_expected_imdb_page(scrolled_soup, url, "title_page"):
                    soup = scrolled_soup
            except WebDriverException:
                pass
        row.update({"budget": _text_in(soup, "title-boxoffice-budget"), "opening_weekend_Gross": _text_in(soup, "title-boxoffice-openingweekenddomestic"), "grossWorldWWide": _text_in(soup, "title-boxoffice-cumulativeworldwidegross"), "gross_US_Canada": _text_in(soup, "title-boxoffice-grossdomestic")})
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
    if "parental_guide" in stages:
        row.update(extract_parental_guide(driver, base, error_logger, timings))
    if "full_credits" in stages:
        row.update(extract_full_credits(driver, base, error_logger, timings))
    if "release_info" in stages:
        row.update(extract_release_info(driver, base, error_logger, timings, complete=complete_release_info))
    row["scrape_version"] = SCRAPE_VERSION
    return row


def _extract_advanced_stages(driver, record, error_logger, timings):
    stages = tuple(record.get("_stages") or ADVANCED_STAGES)
    row = _advanced_row_template(record["link"], record.get("_existing_row"))
    for index, stage in enumerate(stages):
        try:
            row = _extract_advanced_row(
                driver, record["link"], error_logger, timings,
                stages=(stage,), existing_row=row,
                complete_release_info=record.get("_complete_release_info", False),
            )
        except Exception as exc:
            raise StageExtractionError(stage, row, stages[index:], exc) from exc
    return row
