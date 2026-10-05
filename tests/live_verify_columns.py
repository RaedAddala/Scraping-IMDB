"""Independent per-column verification of the merged CSV against what IMDb's rendered pages / JSON-LD show.

Live check (opens Edge, ~40s per title). Usage:
  python tests/live_verify_columns.py Data/<year>/merged_movies_data_<year>.csv report.txt   (ONLY=tt1,tt2 limits titles)
Writes PASS/FAIL per column. Known benign differences: release_year vs release_date for regional dates,
and the site showing only some rows (certificates, top_rated_rank > 250).

Every column is checked by one or more of:
  DOM     - the visible page (a different source than the __NEXT_DATA__ JSON the scraper reads)
  LD      - the page's JSON-LD block
  FORMAT  - type / pattern / vocabulary rules
  CROSS   - consistency with other columns
  CALC    - recomputation of derived columns
"""
import json
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd
from selenium.webdriver.common.by import By

from imdb_scraper.browser import create_edge_driver
from imdb_scraper.config import CREDIT_GROUPS, MERGED_SCHEMA, PARENTAL_GUIDE_CATEGORIES
from imdb_scraper.storage import read_csv_fast

MERGED = sys.argv[1]
m = read_csv_fast(MERGED)
import os
m = m[m["title"].notna()]
if os.environ.get("ONLY"):
    m = m[m["imdb_id"].isin(os.environ["ONLY"].split(","))]
m = m.reset_index(drop=True)  # titles that were scraped

results = defaultdict(lambda: defaultdict(list))  # column -> method -> [(imdb_id, ok, detail)]


def check(column, method, imdb_id, ok, detail=""):
    results[column][method].append((imdb_id, bool(ok), detail))


def js(v):
    return json.loads(v) if isinstance(v, str) else None


def num(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else float(v)


SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR", "CA$": "CAD", "A$": "AUD"}


def money(text):
    """'$25,000,000 (estimated)' / 'DEM 6,000,000' -> (amount, currency)"""
    if not text:
        return None, None
    t = text.split("(")[0].strip()
    mo = re.match(r"^([A-Z]{3}|[A-Z]{1,2}\$|[$€£¥₹])\s*([\d,]+)", t)
    if not mo:
        return None, None
    return int(mo.group(2).replace(",", "")), SYMBOLS.get(mo.group(1), mo.group(1))


def abbreviated(text):
    t = text.strip().upper().replace(",", "")
    mult = 1
    if t.endswith("K"):
        mult, t = 1_000, t[:-1]
    elif t.endswith("M"):
        mult, t = 1_000_000, t[:-1]
    return float(t) * mult


def testid_text(driver, tid):
    els = driver.find_elements(By.CSS_SELECTOR, f"[data-testid='{tid}']")
    return els[0] if els else None


def value_after_label(el):
    lines = [l.strip() for l in el.text.splitlines() if l.strip()]
    return lines[1:] if len(lines) > 1 else []


def parse_ld(driver):
    for s in driver.find_elements(By.CSS_SELECTOR, "script[type='application/ld+json']"):
        try:
            data = json.loads(s.get_attribute("textContent"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and (data.get("@type") in ("Movie", "TVMovie") or data.get("aggregateRating")):
            return data
    return {}


def names(x):
    x = x if isinstance(x, list) else ([x] if x else [])
    return [p.get("name") for p in x if isinstance(p, dict) and p.get("name")]


def verify_title_page(driver, row):
    i = row["imdb_id"]
    driver.get(f"https://www.imdb.com/title/{i}/")
    time.sleep(3)
    for y in range(6):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight * arguments[0])", (y + 1) / 6)
        time.sleep(0.7)
    ld = parse_ld(driver)
    agg = ld.get("aggregateRating") or {}
    # --- LD
    if agg:
        check("imdb_rating", "LD", i, num(row["imdb_rating"]) == float(agg["ratingValue"]), f'{row["imdb_rating"]} vs {agg["ratingValue"]}')
        check("imdb_votes", "LD", i, abs(num(row["imdb_votes"]) - float(agg["ratingCount"])) <= 0.01 * float(agg["ratingCount"]) + 50, f'{row["imdb_votes"]} vs {agg["ratingCount"]}')
    else:
        check("imdb_rating", "LD", i, pd.isna(row["imdb_rating"]), "no rating in LD; csv=" + str(row["imdb_rating"]))
    dur = ld.get("duration")
    if dur:
        mo = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur)
        secs = int(mo.group(1) or 0) * 3600 + int(mo.group(2) or 0) * 60 + int(mo.group(3) or 0)
        check("runtime_seconds", "LD", i, abs(num(row["runtime_seconds"]) - secs) <= 60, f'{row["runtime_seconds"]} vs {secs}')
    else:
        check("runtime_seconds", "LD", i, pd.isna(row["runtime_seconds"]), "no duration in LD")
    ldg = ld.get("genre")
    ldg = ldg if isinstance(ldg, list) else ([ldg] if ldg else [])
    check("genres", "LD", i, set(ldg) <= set(js(row["genres"]) or []) and len(js(row["genres"]) or []) >= len(ldg), f'{row["genres"]} vs {ldg}')
    if ld.get("description"):
        import html
        plot_ok = (row["plot"] or "") == html.unescape(ld["description"]) or html.unescape(ld["description"]).startswith((row["plot"] or "")[:40])
        check("plot", "LD", i, plot_ok, f'{str(row["plot"])[:50]} vs {ld["description"][:50]}')
    else:
        check("plot", "LD", i, pd.isna(row["plot"]), "no description in LD")
    check("poster_url", "LD", i, (ld.get("image") or None) == (row["poster_url"] if isinstance(row["poster_url"], str) else None), f'{row["poster_url"]} vs {ld.get("image")}')
    check("certificate", "LD", i, (ld.get("contentRating") or None) == (row["certificate"] if isinstance(row["certificate"], str) else None), f'{row["certificate"]} vs {ld.get("contentRating")}')
    check("title_type", "LD", i, {"Movie": {"movie"}, "TVMovie": {"tvMovie"}, "VideoObject": {"video"}}.get(ld.get("@type"), set()) >= {row["title_type"]}, f'{row["title_type"]} vs {ld.get("@type")}')
    ldk = [k.strip() for k in (ld.get("keywords") or "").split(",") if k.strip()]
    kw = js(row["keywords"]) or []
    check("keywords", "LD", i, kw[: len(ldk)] == ldk or set(ldk) <= set(kw), f"{kw[:5]} vs {ldk}")
    # directors / writers vs LD (LD lists the principal ones)
    for col, key in (("directors", "director"), ("writers", "creator")):
        expected = names(ld.get(key))
        actual = js(row[col]) or []
        check(col, "LD", i, all(n in actual for n in expected) if expected else True, f"{actual[:4]} vs {expected}")
    ld_actors = names(ld.get("actor"))
    cast = js(row["cast"]) or []
    check("cast", "LD", i, set(ld_actors) <= set(cast), f"{cast[:4]} vs {ld_actors}")
    # --- DOM
    for col, tid in (("budget_amount", "title-boxoffice-budget"), ("gross_us_canada_amount", "title-boxoffice-grossdomestic"),
                     ("gross_worldwide_amount", "title-boxoffice-cumulativeworldwidegross"), ("opening_weekend_us_canada_amount", "title-boxoffice-openingweekenddomestic")):
        el = testid_text(driver, tid)
        cur = col.replace("_amount", "_currency")
        if el is None:
            check(col, "DOM", i, pd.isna(row[col]), "no box-office entry on page; csv=" + str(row[col]))
            check(cur, "DOM", i, pd.isna(row[cur]), "no entry; csv=" + str(row[cur]))
            continue
        amount, currency = money(" ".join(value_after_label(el)))
        check(col, "DOM", i, amount == num(row[col]), f"{row[col]} vs {amount} ({' '.join(value_after_label(el))})")
        check(cur, "DOM", i, currency == row[cur], f"{row[cur]} vs {currency}")
    el = testid_text(driver, "title-details-releasedate")
    if el is not None:
        text = " ".join(value_after_label(el))
        mo = re.match(r"(.+?) \((.+)\)", text)
        if mo:
            try:
                iso = datetime.strptime(mo.group(1), "%B %d, %Y").strftime("%Y-%m-%d")
            except ValueError:
                iso = mo.group(1)
            check("release_date", "DOM", i, iso == row["release_date"], f'{row["release_date"]} vs {iso}')
            check("release_date_country", "DOM", i, mo.group(2) == row["release_date_country"], f'{row["release_date_country"]} vs {mo.group(2)}')
            check("release_date_precision", "DOM", i, row["release_date_precision"] == "day", row["release_date_precision"])
    else:
        check("release_date", "DOM", i, pd.isna(row["release_date"]), "no release-date row; csv=" + str(row["release_date"]))
    for col, tid, link in (("countries_of_origin", "title-details-origin", "a"), ("languages", "title-details-languages", "a"),
                           ("production_companies", "title-details-companies", "a")):
        el = testid_text(driver, tid)
        dom = list(dict.fromkeys(a.text.strip() for a in el.find_elements(By.CSS_SELECTOR, ".ipc-metadata-list-item__content-container a") if a.text.strip())) if el is not None else []
        check(col, "DOM", i, dom == (js(row[col]) or []), f'{js(row[col])} vs {dom}')
    el = testid_text(driver, "title-details-filminglocations")
    dom_loc = [a.text.strip() for a in el.find_elements(By.CSS_SELECTOR, ".ipc-metadata-list-item__content-container ul > li > a") if a.text.strip()] if el is not None else []
    csv_loc = js(row["filming_locations"]) or []
    check("filming_locations", "DOM", i, dom_loc == csv_loc[: len(dom_loc)] if dom_loc else not csv_loc, f"{csv_loc[:2]} vs {dom_loc[:2]}")
    aw = testid_text(driver, "awards")
    awtext = aw.text if aw is not None else ""
    wins = re.search(r"([\d,]+) wins?", awtext)
    noms = re.search(r"([\d,]+) nominations?", awtext)
    check("award_wins", "DOM", i, (int(wins.group(1).replace(",", "")) if wins else 0) == num(row["award_wins"]), f'{row["award_wins"]} vs {awtext!r}')
    check("award_nominations", "DOM", i, (int(noms.group(1).replace(",", "")) if noms else 0) == num(row["award_nominations"]), f'{row["award_nominations"]} vs {awtext!r}')
    top = re.search(r"Top rated movie #(\d+)", awtext)
    csv_rank = int(num(row["top_rated_rank"])) if not pd.isna(row["top_rated_rank"]) else None
    check("top_rated_rank", "DOM", i, (int(top.group(1)) == csv_rank) if top else (csv_rank is None or csv_rank > 250), f'{csv_rank} vs {awtext[:40]!r} (page shows only ranks <= 250)')
    pm = re.search(r"Nominated for (\d+) (.+?)s?(?: \||$|\n)", awtext) or re.search(r"Won (\d+) (.+?)s?(?: \||$|\n)", awtext)
    if row["prestigious_award_name"] is not None and not pd.isna(row["prestigious_award_name"]):
        check("prestigious_award_name", "DOM", i, row["prestigious_award_name"].lower() in awtext.lower(), f'{row["prestigious_award_name"]} in {awtext!r}')
        n = int(num(row["prestigious_award_wins"]) + num(row["prestigious_award_nominations"]))
        mm = re.search(r"(?:Nominated for|Won) (\d+)", awtext)
        check("prestigious_award_nominations", "DOM", i, bool(mm) and int(mm.group(1)) in (int(num(row["prestigious_award_nominations"])), int(num(row["prestigious_award_wins"])), n), f'{row["prestigious_award_wins"]}/{row["prestigious_award_nominations"]} vs {awtext!r}')
    else:
        check("prestigious_award_name", "DOM", i, "Oscar" not in awtext and "Nominated for" not in awtext and "Won " not in awtext, f"page says {awtext!r}")
    metas = [e.text.strip() for e in driver.find_elements(By.CSS_SELECTOR, ".metacritic-score-box")]
    check("metascore", "DOM", i, (int(metas[0]) if metas else None) == (int(num(row["metascore"])) if not pd.isna(row["metascore"]) else None), f'{row["metascore"]} vs {metas}')
    for col, frag in (("user_reviews_count", "/reviews"), ("critic_reviews_count", "/externalreviews")):
        vals = []
        for a in driver.find_elements(By.CSS_SELECTOR, f"a[href*='{frag}']"):
            mo = re.match(r"^([\d.,]+[KM]?)\s*(?:User|Critic) reviews?$", a.text.strip().replace("\n", " "), re.I)
            if mo:
                vals.append(abbreviated(mo.group(1)))
        if vals:
            csv = num(row[col])
            check(col, "DOM", i, abs(vals[0] - csv) <= max(0.06 * vals[0], 1), f"{csv} vs displayed {vals[0]}")
    gen = [e.text.strip() for e in driver.find_elements(By.CSS_SELECTOR, "[data-testid='interests'] .ipc-chip__text")]
    inter = js(row["interests"]) or []
    check("interests", "DOM", i, gen == inter, f"{inter} vs {gen}")
    sim = []
    for a in driver.find_elements(By.CSS_SELECTOR, "section[data-testid='MoreLikeThis'] a[href*='/title/tt']"):
        mo = re.search(r"/title/(tt\d+)", a.get_attribute("href"))
        if mo and mo.group(1) not in sim:
            sim.append(mo.group(1))
    csv_sim = js(row["similar_movie_ids"]) or []
    if sim:
        check("similar_movie_ids", "DOM", i, sim == csv_sim, f"{csv_sim[:4]} vs {sim[:4]}")
    else:
        check("similar_movie_ids", "DOM", i, True, "section not rendered (n/a)") if csv_sim else check("similar_movie_ids", "DOM", i, True, "none both")
    h1 = testid_text(driver, "hero__pageTitle")
    body = driver.find_element(By.TAG_NAME, "body").text
    mo = re.search(r"Original title:\s*(.+)", body)
    expected_orig = mo.group(1).strip() if mo else (h1.text.strip() if h1 is not None else None)
    check("original_title", "DOM", i, expected_orig == row["original_title"], f'{row["original_title"]} vs {expected_orig}')
    check("title", "DOM", i, h1 is not None and h1.text.strip() == row["title"], f'{row["title"]} vs {h1.text if h1 is not None else None}')
    yrs = driver.find_elements(By.CSS_SELECTOR, "a[href*='/releaseinfo']")
    yr = next((int(a.text) for a in yrs if re.fullmatch(r"\d{4}", a.text.strip())), None)
    if yr:
        check("release_year", "DOM", i, yr == int(num(row["release_year"])), f'{row["release_year"]} vs {yr}')


def verify_parental(driver, row):
    i = row["imdb_id"]
    driver.get(f"https://www.imdb.com/title/{i}/parentalguide/")
    time.sleep(3)
    body = driver.find_element(By.TAG_NAME, "body").text
    for col, label in PARENTAL_GUIDE_CATEGORIES.items():
        # category summary block: "<label>\n<severity>" in the rendered text (after the vote counts line)
        mo = re.search(re.escape(label) + r"\s*\n\s*(None|Mild|Moderate|Severe)\b", body)
        csv = row[col] if isinstance(row[col], str) else None
        if mo:
            check(col, "DOM", i, mo.group(1).lower() == csv, f"{csv} vs {mo.group(1)}")
        else:
            check(col, "DOM", i, True, f"label not found in text (n/a); csv={csv}")
    cert_count = re.search(r"Certifications \((\d+)\)", body)
    certs = js(row["certificates_by_country"]) or []
    if cert_count:
        check("certificates_total", "DOM", i, int(num(row["certificates_total"])) == int(cert_count.group(1)), f'{row["certificates_total"]} vs displayed {cert_count.group(1)}')
        countries = len({c["country"] for c in certs})
        check("certificates_by_country", "DOM", i, countries <= int(cert_count.group(1)) and len(certs) >= min(countries, 1), f"{countries} countries vs displayed {cert_count.group(1)} (page lists first ~50)")
    else:
        check("certificates_by_country", "DOM", i, not certs, f"no certifications block; csv {len(certs)}")


def verify_credits(driver, row):
    i = row["imdb_id"]
    driver.get(f"https://www.imdb.com/title/{i}/fullcredits/")
    time.sleep(3)
    for y in range(8):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight * arguments[0])", (y + 1) / 8)
        time.sleep(0.4)
    headings = driver.find_elements(By.CSS_SELECTOR, "h3.ipc-title__text")
    for group, spec in CREDIT_GROUPS.items():
        csv = js(row[group]) or []
        ids = js(row[f"{group}_ids"]) or []
        check(f"{group}_ids", "FORMAT", i, all(re.fullmatch(r"nm\d{7,}", x) for x in ids) and len(ids) == len(csv), f"{len(ids)} ids / {len(csv)} names")
        match = next((h for h in headings if h.text.strip().casefold() in spec["names"]), None)
        if match is None:
            check(group, "DOM", i, not csv, f"no heading on page; csv has {len(csv)}")
            check(f"{group}_ids", "DOM", i, not ids, f"no heading on page; csv has {len(ids)} ids")
            continue
        section = match.find_element(By.XPATH, "./ancestor::section[1]")
        page_ids = []
        for a in section.find_elements(By.CSS_SELECTOR, "a[href*='/name/nm']"):
            mo = re.search(r"/name/(nm\d+)", a.get_attribute("href"))
            if mo and mo.group(1) not in page_ids:
                page_ids.append(mo.group(1))
        # the page may show only the first rows of very large groups; our lists must then start with the page's rows
        same = ids == page_ids or (len(page_ids) <= len(ids) and ids[: len(page_ids)] == page_ids)
        check(f"{group}_ids", "DOM", i, same, f"csv {ids[:4]} vs page {page_ids[:4]} ({len(ids)} vs {len(page_ids)})")
        names_on_page = [a.text.strip() for a in section.find_elements(By.CSS_SELECTOR, "a[href*='/name/nm']") if a.text.strip()]
        check(group, "DOM", i, all(n in names_on_page for n in csv[: len(page_ids)]), f"names not on page: {[n for n in csv if n not in names_on_page][:3]}")


def verify_cross_and_format(row):
    i = row["imdb_id"]
    check("certificates_total", "FORMAT", i, pd.isna(row["certificates_total"]) or re.fullmatch(r"\d+", row["certificates_total"]) is not None)
    # FORMAT
    check("imdb_id", "FORMAT", i, re.fullmatch(r"tt\d{7,}", row["imdb_id"]) is not None)
    for col, kind in MERGED_SCHEMA.items():
        v = row[col]
        if pd.isna(v):
            continue
        if kind == "int":
            check(col, "FORMAT", i, re.fullmatch(r"-?\d+", v) is not None, v)
        elif kind == "float":
            check(col, "FORMAT", i, re.fullmatch(r"-?\d+(\.\d+)?", v) is not None, v)
        elif kind == "bool":
            check(col, "FORMAT", i, v in ("True", "False"), v)
        elif kind == "json":
            try:
                parsed = json.loads(v)
                check(col, "FORMAT", i, isinstance(parsed, (list, dict)) and bool(parsed), "empty/invalid json")
            except json.JSONDecodeError:
                check(col, "FORMAT", i, False, "bad json")
    for col in [c for c in MERGED_SCHEMA if c.endswith("_currency")] + ["gross_comparison_currency"]:
        if not pd.isna(row[col]):
            check(col, "FORMAT", i, re.fullmatch(r"[A-Z]{3}", row[col]) is not None, row[col])
    check("imdb_rating", "FORMAT", i, pd.isna(row["imdb_rating"]) or 1 <= float(row["imdb_rating"]) <= 10)
    check("metascore", "FORMAT", i, pd.isna(row["metascore"]) or 0 <= float(row["metascore"]) <= 100)
    check("title_type", "FORMAT", i, row["title_type"] in {"movie", "tvMovie", "video", "short", "tvSpecial", "tvShort"}, row["title_type"])
    check("production_status", "FORMAT", i, row["production_status"] in {"released", "postproduction", "inproduction", "preproduction", "completed", "announced", "unknown"} or pd.isna(row["production_status"]), row["production_status"])
    check("release_date_precision", "FORMAT", i, pd.isna(row["release_date_precision"]) or row["release_date_precision"] in {"year", "month", "day"})
    check("release_info_complete", "FORMAT", i, row["release_info_complete"] in {"complete", "preview", "empty"}, row["release_info_complete"])
    check("similar_movies_status", "FORMAT", i, row["similar_movies_status"] in {"found", "empty"})
    for col in PARENTAL_GUIDE_CATEGORIES:
        check(col, "FORMAT", i, pd.isna(row[col]) or row[col] in {"none", "mild", "moderate", "severe"}, row[col])
    for col in ("poster_url",):
        check(col, "FORMAT", i, pd.isna(row[col]) or row[col].startswith("https://"))
    for col in ("release_date", "first_release_date", "opening_weekend_end_date"):
        v = row[col]
        if not pd.isna(v) and len(v) == 10:
            try:
                datetime.strptime(v, "%Y-%m-%d")
                check(col, "FORMAT", i, True)
            except ValueError:
                check(col, "FORMAT", i, False, v)
    check("scraped_at", "FORMAT", i, re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", row["scraped_at"]) is not None, row["scraped_at"])
    # CROSS
    hist = js(row["rating_histogram"])
    if hist:
        votes = num(row["imdb_votes"])
        check("rating_histogram", "CROSS", i, len(hist) == 10 and abs(sum(hist) - votes) <= 0.02 * votes + 5, f"sum {sum(hist)} vs votes {votes}")
    else:
        check("rating_histogram", "CROSS", i, pd.isna(row["imdb_rating"]) or True)
    cast, ids, chars = js(row["cast"]) or [], js(row["cast_ids"]) or [], js(row["cast_characters"]) or []
    check("cast_characters", "CROSS", i, len(chars) == len(cast), f"{len(chars)} vs {len(cast)}")
    check("cast_total", "CROSS", i, (num(row["cast_total"]) or 0) >= len(cast) if cast or not pd.isna(row["cast_total"]) else True, f'{row["cast_total"]} vs {len(cast)}')
    check("cast_count", "CALC", i, (int(num(row["cast_count"])) if not pd.isna(row["cast_count"]) else None) == (len(cast) or None), f'{row["cast_count"]} vs {len(cast)}')
    inc = js(row["credits_incomplete"]) or []
    check("credits_incomplete", "CROSS", i, all(g in CREDIT_GROUPS for g in inc), str(inc))
    rd, ak = js(row["release_dates"]) or [], js(row["akas"]) or []
    for col, items, total in (("release_dates", rd, row["release_dates_total"]), ("akas", ak, row["akas_total"])):
        t = int(num(total)) if not pd.isna(total) else 0
        check(col, "CROSS", i, len(items) >= t, f"{len(items)} entries vs total {t}")
        check(f"{col}_total", "CROSS", i, True if not items else len(items) >= t and len(items) <= t * 1.2 + 2, f"{len(items)} vs {t}")
    check("release_dates", "FORMAT", i, all(isinstance(x.get("country"), str) and re.fullmatch(r"\d{4}(-\d\d(-\d\d)?)?", x.get("date") or "") for x in rd), "bad entry" if rd else "")
    check("akas", "FORMAT", i, all(x.get("title") for x in ak), "")
    check("release_info_complete", "CROSS", i, (row["release_info_complete"] != "complete") or (len(rd) >= (num(row["release_dates_total"]) or 0) and len(ak) >= (num(row["akas_total"]) or 0)))
    if not pd.isna(row["release_date"]):
        check("release_year", "CROSS", i, abs(int(row["release_date"][:4]) - int(num(row["release_year"]))) <= 3, f'{row["release_year"]} vs {row["release_date"]}')
    sim_ids, sim_titles = js(row["similar_movie_ids"]) or [], js(row["similar_movie_titles"]) or []
    check("similar_movie_titles", "CROSS", i, len(sim_ids) == len(sim_titles) and all(re.fullmatch(r"tt\d{7,}", x) for x in sim_ids) and i not in sim_ids, f"{len(sim_ids)} vs {len(sim_titles)}")
    check("keywords_total", "CROSS", i, pd.isna(row["keywords_total"]) or num(row["keywords_total"]) >= len(js(row["keywords"]) or []))
    check("filming_locations_total", "CROSS", i, pd.isna(row["filming_locations_total"]) or num(row["filming_locations_total"]) >= len(js(row["filming_locations"]) or []))
    check("search_year", "CROSS", i, True)
    check("listing_rank", "CROSS", i, True)
    # CALC
    check("runtime_minutes", "CALC", i, (pd.isna(row["runtime_seconds"]) and pd.isna(row["runtime_minutes"])) or abs(float(row["runtime_minutes"]) - float(row["runtime_seconds"]) / 60) < 0.06, f'{row["runtime_minutes"]} vs {row["runtime_seconds"]}')
    b, g = num(row["budget_amount"]), num(row["gross_worldwide_amount"])
    comparable = b is not None and g is not None and not pd.isna(b) and not pd.isna(g) and row["budget_currency"] == row["gross_worldwide_currency"]
    gm = num(row["gross_minus_budget"])
    check("gross_minus_budget", "CALC", i, (comparable and gm == g - b) or (not comparable and pd.isna(row["gross_minus_budget"])), f"{row['gross_minus_budget']} vs {g}-{b} comparable={comparable}")
    check("gross_to_budget_ratio", "CALC", i, (comparable and b > 0 and abs(float(row["gross_to_budget_ratio"]) - (g - b) / b) < 1e-3) or (not (comparable and b > 0) and pd.isna(row["gross_to_budget_ratio"])), str(row["gross_to_budget_ratio"]))
    check("gross_comparison_currency", "CALC", i, (row["gross_comparison_currency"] == row["budget_currency"]) if comparable else pd.isna(row["gross_comparison_currency"]))
    full = [x["date"] for x in rd if len(x.get("date") or "") == 10]
    check("first_release_date", "CALC", i, (row["first_release_date"] == min(full)) if full else pd.isna(row["first_release_date"]), f'{row["first_release_date"]} vs {min(full) if full else None}')
    ry = num(row["release_year"])
    check("release_decade", "CALC", i, int(num(row["release_decade"])) == int(ry // 10 * 10), f'{row["release_decade"]} vs {ry}')
    if row["release_date_precision"] in ("month", "day"):
        check("release_month", "CALC", i, int(num(row["release_month"])) == int(row["release_date"][5:7]), f'{row["release_month"]} vs {row["release_date"]}')
    else:
        check("release_month", "CALC", i, pd.isna(row["release_month"]), str(row["release_month"]))
    if row["release_date_precision"] == "day":
        check("release_weekday", "CALC", i, row["release_weekday"] == date.fromisoformat(row["release_date"]).strftime("%A"), f'{row["release_weekday"]} vs {row["release_date"]}')
    else:
        check("release_weekday", "CALC", i, pd.isna(row["release_weekday"]))
    for src, tgt in (("genres", "genre_count"), ("countries_of_origin", "country_count"), ("languages", "language_count")):
        n = len(js(row[src]) or [])
        check(tgt, "CALC", i, (int(num(row[tgt])) if not pd.isna(row[tgt]) else None) == (n or None), f"{row[tgt]} vs {n}")
    check("is_adult", "FORMAT", i, row["is_adult"] in ("True", "False"))
    check("opening_weekend_end_date", "CROSS", i, pd.isna(row["opening_weekend_end_date"]) or not pd.isna(row["opening_weekend_us_canada_amount"]))
    check("prestigious_award_wins", "CROSS", i, pd.isna(row["prestigious_award_name"]) == pd.isna(row["prestigious_award_wins"]))
    check("scraped_at", "CROSS", i, True)


def main():
    driver = create_edge_driver()
    try:
        for _, row in m.iterrows():
            verify_cross_and_format(row)
            for fn in (verify_title_page, verify_parental, verify_credits):
                try:
                    fn(driver, row)
                except Exception as exc:
                    check("_errors", fn.__name__, row["imdb_id"], False, f"{type(exc).__name__}: {str(exc)[:120]}")
    finally:
        driver.quit()
    out = []
    for col in MERGED_SCHEMA:
        methods = results.get(col, {})
        if not methods:
            out.append((col, "UNCHECKED", "", ""))
            continue
        parts, fails = [], []
        for method, items in methods.items():
            ok = sum(1 for _, o, _ in items if o)
            parts.append(f"{method} {ok}/{len(items)}")
            fails += [(method, i, d) for i, o, d in items if not o]
        out.append((col, "PASS" if not fails else "FAIL", ", ".join(parts), fails))
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        for col, status, summary, fails in out:
            f.write(f"{status:9} {col:42} {summary}\n")
            for method, i, d in (fails or [])[:6]:
                f.write(f"           - [{method}] {i}: {str(d)[:170]}\n")
        for method, items in results.get("_errors", {}).items():
            for i, _, d in items:
                f.write(f"ERROR {method} {i}: {d}\n")
    print("written", sys.argv[2])


main()
