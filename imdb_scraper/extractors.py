import json
import re
import time
import pandas as pd
from bs4 import BeautifulSoup
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
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
    CREDIT_GROUPS,
    LOAD_MORE_BUTTON_TIMEOUT_SECONDS,
    LOAD_MORE_RESULT_TIMEOUT_SECONDS,
    LOAD_MORE_RETRY_PAUSE_SECONDS,
    PAGE_LOAD_TIMEOUT_SECONDS,
    PARENTAL_GUIDE_CATEGORIES,
    REQUIRED_CONTENT_TIMEOUT_SECONDS,
    STAGE_FIELDS,
)
from .parsing import split_listing_rank, title_id, title_url
from .storage import describe_error, now_iso


class StageExtractionError(RuntimeError):
    def __init__(self, stage, partial_row, remaining_stages, cause):
        super().__init__(f"{stage}: {describe_error(cause)}")
        self.stage = stage
        self.partial_row = partial_row
        self.remaining_stages = list(remaining_stages)
        self.cause = cause


# --- Search listing ----------------------------------------------------------------------------
def _listing_ids(driver):
    hrefs = driver.execute_script(
        "return Array.from(document.querySelectorAll('li.ipc-metadata-list-summary-item a.ipc-lockup-overlay[href]'))"
        ".map(a => a.getAttribute('href'));"
    ) or []
    return {title_id(href) for href in hrefs if title_id(href)}


def extract_links(year, error_logger, results_logger, max_movies=600):
    """The year's search listing: one row per unique IMDb title, in listing order."""
    if max_movies < 0:
        raise ValueError("max_movies must be non-negative")
    start = time.time()
    url = f"https://www.imdb.com/search/title/?title_type=feature&release_date={year}-01-01,{year}-12-31&count=50&sort=boxoffice_gross_us,desc"
    films_data, loaded_data, failures = [], 0, 0
    complete = True  # False when pagination or item extraction failed, i.e. the listing may be partial
    driver = None
    try:
        driver = create_edge_driver()
        try:
            driver.get(url)
        except TimeoutException:
            driver.execute_script("window.stop()")
        _wait_for_page_ready(driver)
        WebDriverWait(driver, PAGE_LOAD_TIMEOUT_SECONDS).until(EC.presence_of_element_located((By.CSS_SELECTOR, "ul.ipc-metadata-list")))
        loaded_data = len(_listing_ids(driver))
        while loaded_data < max_movies and failures < 3:
            try:
                button = WebDriverWait(driver, LOAD_MORE_BUTTON_TIMEOUT_SECONDS).until(EC.presence_of_element_located((By.XPATH, "//button[contains(@class, 'ipc-btn') and .//span[contains(text(), '50 more')]]")))
            except TimeoutException:
                break  # no "50 more" button: the end of the results
            try:
                driver.execute_script("arguments[0].scrollIntoView(true);", button)
                driver.execute_script("arguments[0].click();", button)
                old_count = loaded_data
                WebDriverWait(driver, LOAD_MORE_RESULT_TIMEOUT_SECONDS).until(lambda d: len(_listing_ids(d)) > old_count)
                _wait_for_page_ready(driver)
                loaded_data = len(_listing_ids(driver))
                failures = 0
            except Exception as exc:
                failures += 1
                complete = failures < 3
                error_logger.error("Listing %s: load-more attempt %s failed after %s titles: %s", year, failures, loaded_data, describe_error(exc))
                time.sleep(LOAD_MORE_RETRY_PAUSE_SECONDS)
        soup = BeautifulSoup(driver.page_source, "lxml")
        container = soup.select_one("ul.ipc-metadata-list")
        seen_ids = set()
        for position, film in enumerate(container.find_all("li", class_="ipc-metadata-list-summary-item") if container else [], start=1):
            if len(films_data) >= max_movies:
                break
            try:
                link_tag = film.select_one("a.ipc-lockup-overlay[href]")
                imdb_id = title_id(link_tag.get("href", "")) if link_tag else None
                if not imdb_id:
                    raise ValueError("listing item has no title link")
                if imdb_id in seen_ids:
                    continue
                seen_ids.add(imdb_id)
                rank, listing_title = split_listing_rank(clean_text(film.select_one("a.ipc-title-link-wrapper")))
                films_data.append({
                    "imdb_id": imdb_id, "search_year": year,
                    "listing_rank": rank or position, "listing_title": listing_title,
                })
            except Exception as exc:
                complete = False
                error_logger.error("Listing %s: item skipped: %s", year, describe_error(exc))
        results_logger.info("Listing: %s titles in %.0fs%s", len(films_data), time.time() - start, "" if complete else " (INCOMPLETE)")
    except Exception as exc:
        complete = False
        error_logger.error("Listing %s failed: %s", year, describe_error(exc))
    finally:
        if driver is not None:
            driver.quit()
    listing = pd.DataFrame(films_data, columns=BASIC_COLUMNS)
    listing.attrs["complete"] = complete
    return listing


# --- Page data ---------------------------------------------------------------------------------
def _get(data, *path):
    """Safe nested lookup: None as soon as any step is missing or not a mapping."""
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _stop_page_loading(driver):
    try:
        driver.execute_script("window.stop()")
    except WebDriverException:
        pass


def _page_props(driver, url, timings=None, stage=None):
    """Navigate and return the page's __NEXT_DATA__ pageProps, verified to belong to the requested title."""
    started_at = time.perf_counter()
    navigation_timed_out = False
    try:
        try:
            driver.get(url)
        except TimeoutException:
            navigation_timed_out = True
            _stop_page_loading(driver)
        try:
            WebDriverWait(driver, REQUIRED_CONTENT_TIMEOUT_SECONDS).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "script#__NEXT_DATA__"))
            )
        except TimeoutException:
            pass
        _stop_page_loading(driver)
        raw = driver.execute_script("return document.querySelector('script#__NEXT_DATA__')?.textContent || null")
        try:
            props = (json.loads(raw) if raw else {}).get("props", {}).get("pageProps")
        except json.JSONDecodeError:
            props = None
        props = props if isinstance(props, dict) else {}
        expected_id = title_id(url)
        actual_id = props.get("tconst") or _get(props, "contentData", "entityMetadata", "id") or _get(props, "contentData", "data", "title", "id")
        if stage == "title_page":
            has_content = isinstance(props.get("aboveTheFoldData"), dict) and isinstance(props.get("mainColumnData"), dict)
        else:
            has_content = isinstance(props.get("contentData"), dict)
        ready = bool(has_content and actual_id == expected_id and "privacy error" not in (driver.title or "").lower())
        if timings is not None and stage:
            timings[f"{stage}_content_ready"] = ready
            timings[f"{stage}_navigation_timed_out"] = navigation_timed_out
        if not ready:
            raise PageContentError(f"invalid or incomplete {stage} page")
        return props
    finally:
        if timings is not None and stage:
            timings[f"{stage}_seconds"] = round(time.perf_counter() - started_at, 3)


def _page_content_data(driver, url, timings=None, stage=None):
    return _page_props(driver, url, timings=timings, stage=stage)["contentData"]


def _section_items(category):
    section = (category or {}).get("section") or {}
    items = [item for item in section.get("items") or [] if isinstance(item, dict)]
    return items, section.get("total")


# --- Title page --------------------------------------------------------------------------------
def _release_date(release):
    """({day, month, year}) -> ('1995-11-22' | '1995-11' | '1995', precision)."""
    year, month, day = (release or {}).get("year"), (release or {}).get("month"), (release or {}).get("day")
    if not year:
        return None, None
    if month and day:
        return f"{year:04d}-{month:02d}-{day:02d}", "day"
    if month:
        return f"{year:04d}-{month:02d}", "month"
    return f"{year:04d}", "year"


def _money(node):
    return (node or {}).get("amount"), (node or {}).get("currency")


def _names(edges, *path):
    values = [_get(edge.get("node") if isinstance(edge, dict) else None, *path) for edge in edges or []]
    return [value for value in dict.fromkeys(values) if value]


def _texts(items):
    return [item["text"] for item in items or [] if isinstance(item, dict) and item.get("text")]


def _histogram(breakdown):
    values = _get(breakdown, "histogram", "histogramValues") or []
    by_rating = {item.get("rating"): item.get("voteCount") for item in values if isinstance(item, dict)}
    if set(by_rating) != set(range(1, 11)):
        return None
    return [by_rating[rating] for rating in range(1, 11)]


def _similar_titles(more_like_this):
    ids, titles = [], []
    for edge in more_like_this.get("edges") or []:
        node = edge.get("node") if isinstance(edge, dict) else None
        name = _get(node, "titleText", "text")
        if isinstance(node, dict) and node.get("id") and name:
            ids.append(node["id"])
            titles.append(name)
    return ids, titles


def _validate_title_row(row):
    rating, votes = row["imdb_rating"], row["imdb_votes"]
    if rating is not None and not 1 <= rating <= 10:
        raise ValueError(f"imdb_rating out of range: {rating}")
    if votes is not None and votes < 0:
        raise ValueError(f"imdb_votes negative: {votes}")
    if row["runtime_seconds"] is not None and row["runtime_seconds"] <= 0:
        raise ValueError(f"runtime_seconds not positive: {row['runtime_seconds']}")
    for field in ("budget", "gross_us_canada", "gross_worldwide", "opening_weekend_us_canada"):
        amount = row[f"{field}_amount"]
        if amount is not None and (amount < 0 or not row[f"{field}_currency"]):
            raise ValueError(f"{field} amount without a valid currency: {amount}")


def extract_title_page(driver, imdb_id, timings=None):
    props = _page_props(driver, title_url(imdb_id), timings=timings, stage="title_page")
    above, main = props["aboveTheFoldData"], props["mainColumnData"]
    title = _get(above, "titleText", "text")
    if not title:
        raise PageContentError(f"Title page for {imdb_id} has no title text")
    more_like_this = main.get("moreLikeThisTitles")
    if not isinstance(more_like_this, dict):
        # Real pages always carry the recommendations section (possibly empty); its absence means a partial page.
        raise PageContentError(f"Recommendations section missing from the title page for {imdb_id}")
    similar_ids, similar_titles = _similar_titles(more_like_this)

    release = main.get("releaseDate") or above.get("releaseDate")
    release_date, precision = _release_date(release)
    budget, budget_currency = _money(_get(main, "productionBudget", "budget"))
    domestic, domestic_currency = _money(_get(main, "lifetimeGross", "total"))
    worldwide, worldwide_currency = _money(_get(main, "worldwideGross", "total"))
    opening, opening_currency = _money(_get(main, "openingWeekendGross", "gross", "total"))
    prestigious = main.get("prestigiousAwardSummary") or {}
    row = {
        "title": title,
        "original_title": _get(above, "originalTitleText", "text"),
        "title_type": _get(above, "titleType", "id"),
        "release_year": _get(above, "releaseYear", "year"),
        "is_adult": above.get("isAdult"),
        "production_status": _get(above, "productionStatus", "currentProductionStage", "id"),
        "plot": _get(above, "plot", "plotText", "plainText"),
        "poster_url": _get(above, "primaryImage", "url"),
        "certificate": _get(above, "certificate", "rating"),
        "runtime_seconds": _get(above, "runtime", "seconds"),
        "release_date": release_date,
        "release_date_precision": precision,
        "release_date_country": _get(release, "country", "text"),
        "imdb_rating": _get(above, "ratingsSummary", "aggregateRating"),
        "imdb_votes": _get(above, "ratingsSummary", "voteCount"),
        "metascore": _get(above, "metacritic", "metascore", "score"),
        "top_rated_rank": _get(main, "ratingsSummary", "topRanking", "rank"),
        "rating_histogram": _histogram(main.get("aggregateRatingsBreakdown")),
        "user_reviews_count": _get(main, "reviews", "total"),
        "critic_reviews_count": _get(above, "criticReviewsTotal", "total"),
        "budget_amount": budget, "budget_currency": budget_currency,
        "gross_us_canada_amount": domestic, "gross_us_canada_currency": domestic_currency,
        "gross_worldwide_amount": worldwide, "gross_worldwide_currency": worldwide_currency,
        "opening_weekend_us_canada_amount": opening, "opening_weekend_us_canada_currency": opening_currency,
        "opening_weekend_end_date": _get(main, "openingWeekendGross", "weekendEndDate"),
        # IMDb reports no awards as null, so a loaded page with no counts means zero.
        "award_wins": _get(main, "wins", "total") or 0,
        "award_nominations": _get(main, "nominationsExcludeWins", "total") or 0,
        "prestigious_award_name": _get(prestigious, "award", "text"),
        "prestigious_award_wins": prestigious.get("wins"),
        "prestigious_award_nominations": prestigious.get("nominations"),
        "genres": _texts(_get(above, "genres", "genres")),
        "interests": _names(_get(above, "interests", "edges"), "primaryText", "text"),
        "keywords": _names(_get(above, "keywords", "edges"), "text"),
        "keywords_total": _get(above, "keywords", "total"),
        "countries_of_origin": _texts(_get(main, "countriesDetails", "countries")),
        "languages": _texts(_get(main, "spokenLanguages", "spokenLanguages")),
        "production_companies": _names(_get(main, "production", "edges"), "company", "companyText", "text"),
        "filming_locations": _names(_get(main, "filmingLocations", "edges"), "location"),
        "filming_locations_total": _get(main, "filmingLocations", "total"),
        "similar_movie_ids": similar_ids,
        "similar_movie_titles": similar_titles,
        "similar_movies_status": "found" if similar_ids else "empty",
    }
    _validate_title_row(row)
    return row


# --- Parental guide ----------------------------------------------------------------------------
def extract_parental_guide(driver, imdb_id, timings=None):
    """Severity per category (lowercase: none/mild/moderate/severe) and the certificates of every country.
    Parser errors propagate: a failed parse must fail the stage, not look like an empty section."""
    result = {key: None for key in PARENTAL_GUIDE_CATEGORIES}
    result["certificates_by_country"] = result["certificates_total"] = None
    content = _page_content_data(driver, title_url(imdb_id) + "parentalguide/", timings=timings, stage="parental_guide")
    rating_data = content.get("contentRatingData")
    if not isinstance(rating_data, dict):
        raise PageContentError(f"Parental guide data missing for {imdb_id}")
    by_title = {
        str(item.get("title", "")).casefold(): item.get("severitySummaryText")
        for item in rating_data.get("categorySummaries") or [] if isinstance(item, dict)
    }
    for key, label in PARENTAL_GUIDE_CATEGORIES.items():
        severity = by_title.get(label.casefold())
        result[key] = severity.strip().lower() if isinstance(severity, str) and severity.strip() else None
    certificates = []
    for entry in content.get("certificates") or []:
        for rating in (entry or {}).get("ratings") or []:
            if entry.get("country") and rating.get("rating"):
                notes = rating.get("extraInformation") or []
                certificates.append({"country": entry["country"], "rating": rating["rating"], "notes": "; ".join(notes) or None})
    result["certificates_by_country"] = certificates or None
    total = content.get("totalCertificates")  # IMDb lists only the first ~50 ratings of titles with many certificates
    result["certificates_total"] = total if isinstance(total, int) else None
    return result


# --- Full credits ------------------------------------------------------------------------------
def _credit_group(categories, group):
    spec = CREDIT_GROUPS[group]
    for category in categories:
        if str(category.get("id", "")).endswith(spec["id"]):
            return category
    for category in categories:
        if str(category.get("name", "")).casefold() in spec["names"]:
            return category
    return None


def extract_full_credits(driver, imdb_id, timings=None):
    result = {}
    for group in CREDIT_GROUPS:
        result[group] = result[f"{group}_ids"] = None
    result.update(cast_characters=None, cast_total=None, credits_incomplete=None)
    content = _page_content_data(driver, title_url(imdb_id) + "fullcredits/", timings=timings, stage="full_credits")
    categories = [category for category in content.get("categories", []) if isinstance(category, dict)]
    incomplete = []
    for group in CREDIT_GROUPS:
        items, total = _section_items(_credit_group(categories, group))
        people = list({item["id"]: item for item in items if item.get("id") and item.get("rowTitle")}.values())
        result[group] = [item["rowTitle"] for item in people] or None
        result[f"{group}_ids"] = [item["id"] for item in people] or None
        if isinstance(total, int) and len(items) < total:
            incomplete.append(group)  # the page lists only part of this group
        if group == "cast":
            result["cast_characters"] = [item.get("characters") or [] for item in people] or None
            result["cast_total"] = total if isinstance(total, int) else (len(people) or None)
    result["credits_incomplete"] = incomplete or None
    return result


# --- Release info ------------------------------------------------------------------------------
MAX_RELEASE_EXPANSIONS = 60


_MONTHS = {name: number for number, name in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"), start=1)}
_DATE_TEXT = re.compile(r"(?:(?P<month>[A-Za-z]+)\s+)?(?:(?P<day>\d{1,2}),\s*)?(?P<year>\d{4})")


def _iso_date(text):
    """'November 22, 1995' -> '1995-11-22', 'May 1995' -> '1995-05', '1995' -> '1995'; unparsed text is returned as is.
    Month names are matched here, not with strptime, so the result does not depend on the machine's locale."""
    match = _DATE_TEXT.fullmatch(text.strip())
    if match:
        month = _MONTHS.get((match["month"] or "").lower())
        year = int(match["year"])
        if not match["month"]:
            return f"{year:04d}"
        if month and match["day"]:
            return f"{year:04d}-{month:02d}-{int(match['day']):02d}"
        if month and not match["day"]:
            return f"{year:04d}-{month:02d}"
    return text.strip()


def _note(text):
    text = (text or "").strip()
    return text[1:-1].strip() if text.startswith("(") and text.endswith(")") else (text or None)


def _release_entries(items, kind):
    entries = []
    for item in items:
        for value in item.get("listContent") or []:
            country = item.get("rowTitle")
            if not country or not isinstance(value, dict) or not value.get("text"):
                continue
            note = _note(value.get("subText"))
            if country == "(original title)":  # not a country: the title in its original language
                country, note = None, "original title"
            if kind == "release":
                entries.append({"country": country, "date": _iso_date(value["text"]), "note": note})
            else:
                entries.append({"country": country, "title": value["text"].strip(), "note": note})
    return entries


_SECTION_JS = """
const section = document.evaluate("//span[@id='%s']/ancestor::section[1]", document, null, 9, null).singleNodeValue;
if (!section) return null;
return Array.from(section.querySelectorAll('li.ipc-metadata-list__item')).map(li => {
  const label = li.querySelector('.ipc-metadata-list-item__label');
  const values = Array.from(li.querySelectorAll('ul li')).map(v => ({
    text: (v.querySelector('a, span') || {}).textContent || '',
    sub: (v.querySelector('span.ipc-metadata-list-item__list-content-item--subText') || {}).textContent || ''
  }));
  return {country: label ? label.textContent : '', values: values};
});
"""


def _release_section(driver, section_id):
    return driver.find_element(By.XPATH, f"//span[@id='{section_id}']/ancestor::section[1]")


def _more_button(section):
    buttons = section.find_elements(By.XPATH, ".//button[contains(translate(normalize-space(.), 'MORE', 'more'), 'more')]")
    return next((item for item in buttons if re.fullmatch(r"\d+\s+more", item.text.strip(), re.I)), None)


def _expand_release_info(driver):
    """Expand every 'N more' control and read the full lists as {"releases": [...], "akas": [...]} items in the
    same shape as the page data. Browser errors and non-exhaustion raise, so a partial list is never reported complete."""
    expanded = {}
    for section_id in ("releases", "akas"):
        try:
            _release_section(driver, section_id)
        except NoSuchElementException:
            continue  # section genuinely absent on this page
        for _ in range(MAX_RELEASE_EXPANSIONS):
            section = _release_section(driver, section_id)
            button = _more_button(section)
            if not button:
                break
            before = len(section.text)
            driver.execute_script("arguments[0].click()", button)
            WebDriverWait(driver, REQUIRED_CONTENT_TIMEOUT_SECONDS + 2).until(
                lambda d: len(_release_section(d, section_id).text) > before
            )
        else:
            if _more_button(_release_section(driver, section_id)):
                raise PageContentError(f"{section_id} list was not exhausted after {MAX_RELEASE_EXPANSIONS} expansions")
        rows = driver.execute_script(_SECTION_JS % section_id) or []
        expanded[section_id] = [
            {"rowTitle": row["country"].strip(), "listContent": [{"text": v["text"], "subText": v["sub"]} for v in row["values"] if v["text"].strip()]}
            for row in rows if row["country"].strip()
        ]
    return expanded


def extract_release_info(driver, imdb_id, timings=None, complete=True):
    """Release dates and AKA titles as lists of objects. Source totals are recorded so a preview is never
    mistaken for a complete list: release_info_complete is 'complete', 'preview' or 'empty'."""
    content = _page_content_data(driver, title_url(imdb_id) + "releaseinfo/", timings=timings, stage="release_info")
    categories = {
        str(category.get("id", "")).casefold(): category
        for category in content.get("categories", []) if isinstance(category, dict)
    }
    release_items, release_total = _section_items(categories.get("releases"))
    aka_items, aka_total = _section_items(categories.get("akas"))
    if complete:
        expansion_started = time.perf_counter()
        expanded = _expand_release_info(driver)
        release_items = expanded.get("releases", release_items)
        aka_items = expanded.get("akas", aka_items)
        if timings is not None:
            expansion_seconds = round(time.perf_counter() - expansion_started, 3)
            timings["release_info_expansion_seconds"] = expansion_seconds
            timings["release_info_seconds"] = round(timings.get("release_info_seconds", 0) + expansion_seconds, 3)
    # Totals count source rows (one per country), the same unit as the item lists.
    if not release_items and not aka_items and not release_total and not aka_total:
        status = "empty"
    elif all(isinstance(total, int) and len(items) >= total for items, total in ((release_items, release_total), (aka_items, aka_total)) if total):
        status = "complete"
    else:
        status = "preview"
    return {
        "release_dates": _release_entries(release_items, "release") or None, "release_dates_total": release_total,
        "akas": _release_entries(aka_items, "aka") or None, "akas_total": aka_total, "release_info_complete": status,
    }


# --- Row assembly ------------------------------------------------------------------------------
def _advanced_row_template(imdb_id, existing_row=None):
    row = {column: None for column in ADVANCED_COLUMNS}
    if existing_row:
        for column in ADVANCED_COLUMNS:
            value = existing_row.get(column)
            if value is not None and not (isinstance(value, float) and pd.isna(value)):
                row[column] = value
    row["imdb_id"] = imdb_id
    return row


def _extract_advanced_row(driver, imdb_id, timings=None, stages=None, existing_row=None, complete_release_info=True):
    stages = tuple(stages or ADVANCED_STAGES)
    row = _advanced_row_template(imdb_id, existing_row)
    for stage in stages:
        for field in STAGE_FIELDS[stage]:
            row[field] = None
    if "title_page" in stages:
        row.update(extract_title_page(driver, imdb_id, timings))
    if "parental_guide" in stages:
        row.update(extract_parental_guide(driver, imdb_id, timings))
    if "full_credits" in stages:
        row.update(extract_full_credits(driver, imdb_id, timings))
    if "release_info" in stages:
        row.update(extract_release_info(driver, imdb_id, timings, complete=complete_release_info))
    row["scraped_at"] = now_iso()
    return row


def _extract_advanced_stages(driver, record, timings):
    stages = tuple(record.get("_stages") or ADVANCED_STAGES)
    row = _advanced_row_template(record["imdb_id"], record.get("_existing_row"))
    for index, stage in enumerate(stages):
        try:
            row = _extract_advanced_row(
                driver, record["imdb_id"], timings,
                stages=(stage,), existing_row=row,
                complete_release_info=record.get("_complete_release_info", True),
            )
        except Exception as exc:
            raise StageExtractionError(stage, row, stages[index:], exc) from exc
    return row
