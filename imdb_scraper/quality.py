"""Row-level data-quality rules for the merged data. Each rule lists the IMDb IDs that violate it."""
import re
from datetime import datetime

import pandas as pd

from .config import CREDIT_GROUPS, MERGED_SCHEMA
from .storage import parse_json_cell

_TT = re.compile(r"tt\d{7,}")
_NM = re.compile(r"nm\d{7,}")
_CURRENCY = re.compile(r"[A-Z]{3}")
MONEY_FIELDS = ("budget", "gross_us_canada", "gross_worldwide", "opening_weekend_us_canada")


def _num(value):
    return pd.to_numeric(value, errors="coerce")


def _list(value):
    parsed = parse_json_cell(value)
    return parsed if isinstance(parsed, list) else []


def _valid_date(value):
    for fmt, length in (("%Y-%m-%d", 10), ("%Y-%m", 7), ("%Y", 4)):
        if len(value) == length:
            try:
                datetime.strptime(value, fmt)
                return True
            except ValueError:
                return False
    return False


def row_issues(row):
    """Names of the rules this row breaks."""
    issues = []
    if not _TT.fullmatch(str(row["imdb_id"])):
        issues.append("imdb_id_format")
    for column, kind in MERGED_SCHEMA.items():
        if kind == "json" and isinstance(row.get(column), str):
            parsed = parse_json_cell(row[column])
            if not isinstance(parsed, (list, dict)):
                issues.append("invalid_json")
                break
    rating, votes, meta = _num(row.get("imdb_rating")), _num(row.get("imdb_votes")), _num(row.get("metascore"))
    if (pd.notna(rating) and not 1 <= rating <= 10) or (pd.notna(votes) and votes < 0) or (pd.notna(meta) and not 0 <= meta <= 100):
        issues.append("rating_out_of_range")
    for field in MONEY_FIELDS:
        amount, currency = row.get(f"{field}_amount"), row.get(f"{field}_currency")
        if pd.isna(amount) != pd.isna(currency) or (isinstance(currency, str) and not _CURRENCY.fullmatch(currency)):
            issues.append("money_without_currency")
            break
    for group in CREDIT_GROUPS:
        names, ids = _list(row.get(group)), _list(row.get(f"{group}_ids"))
        if len(names) != len(ids) or not all(_NM.fullmatch(str(x)) for x in ids):
            issues.append("credit_ids_misaligned")
            break
    cast = _list(row.get("cast"))
    if len(_list(row.get("cast_characters"))) != len(cast) or (pd.notna(_num(row.get("cast_total"))) and _num(row["cast_total"]) < len(cast)):
        issues.append("cast_inconsistent")
    similar = _list(row.get("similar_movie_ids"))
    if len(similar) != len(_list(row.get("similar_movie_titles"))) or not all(_TT.fullmatch(str(x)) for x in similar) or row["imdb_id"] in similar:
        issues.append("similar_movies_inconsistent")
    histogram = _list(row.get("rating_histogram"))
    if histogram and (len(histogram) != 10 or (pd.notna(votes) and abs(sum(histogram) - votes) > 0.02 * votes + 5)):
        issues.append("histogram_vs_votes")
    if row.get("release_info_complete") == "complete":
        if len(_list(row.get("release_dates"))) < (_num(row.get("release_dates_total")) or 0) or len(_list(row.get("akas"))) < (_num(row.get("akas_total")) or 0):
            issues.append("release_info_marked_complete_but_short")
    for column in ("release_date", "first_release_date", "opening_weekend_end_date"):
        if isinstance(row.get(column), str) and not _valid_date(row[column]):
            issues.append("invalid_date")
            break
    return issues


def check_quality(merged):
    """{rule: [imdb_id, ...]} for the scraped rows of a merged frame (rows without details are skipped)."""
    found = {}
    scraped = merged[merged["title"].notna()] if "title" in merged else merged.iloc[0:0]
    for row in scraped.to_dict("records"):
        for rule in dict.fromkeys(row_issues(row)):
            found.setdefault(rule, []).append(row["imdb_id"])
    return found


def log_quality(merged, results_logger):
    issues = check_quality(merged)
    scraped = int(merged["title"].notna().sum()) if "title" in merged else 0
    if not issues:
        results_logger.info("Quality check: %s titles, all rules pass", scraped)
        return
    summary = "; ".join(f"{rule} x{len(ids)} ({', '.join(ids[:3])}{'...' if len(ids) > 3 else ''})" for rule, ids in issues.items())
    results_logger.info("Quality check: %s titles, issues: %s", scraped, summary)
