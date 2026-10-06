import pandas as pd

from .config import ADVANCED_SCHEMA, BASIC_SCHEMA, MERGED_SCHEMA
from .storage import describe_error, format_frame, parse_json_cell, read_csv_or_empty, write_csv_safely, year_paths


def load_merged(year):
    """(listing, details) frames from the year's merged CSV, or (None, empty details) when it does not exist."""
    path = year_paths(year)["merged"]
    if not path.exists():
        return None, pd.DataFrame(columns=list(ADVANCED_SCHEMA))
    merged = read_csv_or_empty(path, MERGED_SCHEMA)
    return merged[list(BASIC_SCHEMA)].reset_index(drop=True), merged[list(ADVANCED_SCHEMA)].reset_index(drop=True)


def save_merged(year, listing, details, error_logger, results_logger):
    """Join listing and details by IMDb ID, add the derived columns and write the year's only data file."""
    try:
        if "imdb_id" not in details:
            details = pd.DataFrame(columns=["imdb_id"])
        merged = pd.merge(listing, details, how="left", on="imdb_id", validate="one_to_one")
        # Type the values first, so rows scraped in this run (Python lists) and rows reloaded from the CSV
        # (JSON text) go through identical derivations.
        merged = format_frame(merged, {**BASIC_SCHEMA, **ADVANCED_SCHEMA})
        merged = compute_derived_columns(merged, error_logger, results_logger)
        write_csv_safely(merged, year_paths(year)["merged"], MERGED_SCHEMA)
        return merged
    except Exception as exc:
        error_logger.error("Could not save merged data for %s: %s", year, describe_error(exc))
        raise


def _list_len(value):
    """Length of a JSON list cell; <NA> when the cell is blank (not a fabricated zero)."""
    parsed = parse_json_cell(value)
    return len(parsed) if isinstance(parsed, list) else pd.NA


def _language_len(value):
    """Number of languages; IMDb's 'None' placeholder (no spoken language listed) is not a language."""
    parsed = parse_json_cell(value)
    return len([language for language in parsed if language != "None"]) if isinstance(parsed, list) else pd.NA


def _first_release_date(value):
    """Earliest full (day-precision) date among a title's release dates; None when there is none."""
    dates = [item.get("date") for item in parse_json_cell(value) or [] if isinstance(item, dict)]
    full = [d for d in dates if isinstance(d, str) and len(d) == 10 and d[4] == "-" and d[7] == "-"]
    return min(full) if full else None


def compute_derived_columns(df, error_logger, results_logger):
    """Columns computed from the scraped values. Every one is empty when its inputs are unknown."""
    try:
        number = lambda column: pd.to_numeric(df[column], errors="coerce") if column in df else pd.Series(float("nan"), index=df.index)
        text = lambda column: df[column] if column in df else pd.Series(None, index=df.index, dtype=object)

        df["runtime_minutes"] = (number("runtime_seconds") / 60).round(1)

        df["first_release_date"] = df["release_dates"].map(_first_release_date) if "release_dates" in df else None
        # Month and weekday describe the release in release_year: the earliest full release date when it falls in that
        # year, else IMDb's displayed (regional) release_date when it does. A later local release (a re-release years
        # after the film came out) is never used, so those cells stay empty instead of describing the wrong year.
        release_date, first = text("release_date"), df["first_release_date"]
        in_year = lambda dates: pd.to_numeric(dates.str.slice(0, 4), errors="coerce") == number("release_year")
        basis = first.where(in_year(first)).where(lambda s: s.notna(), release_date.where(in_year(release_date)))
        dates = pd.to_datetime(basis.where(basis.str.len() == 10), format="%Y-%m-%d", errors="coerce")
        df["release_decade"] = number("release_year") // 10 * 10
        df["release_month"] = pd.to_numeric(basis.str.slice(5, 7), errors="coerce")
        df["release_weekday"] = dates.dt.day_name()

        # Gross minus budget only when both amounts are in the same stated currency; no conversion is attempted.
        budget, gross = number("budget_amount"), number("gross_worldwide_amount")
        budget_currency, gross_currency = text("budget_currency"), text("gross_worldwide_currency")
        comparable = budget.notna() & gross.notna() & budget_currency.notna() & (budget_currency == gross_currency)
        df["gross_minus_budget"] = (gross - budget).where(comparable)
        df["gross_to_budget_ratio"] = ((gross - budget) / budget.where(budget > 0)).where(comparable).round(4)
        df["gross_comparison_currency"] = budget_currency.where(comparable)

        # Title-page lists: a blank list on a scraped title means IMDb lists none (0); no title page yet means unknown.
        title_scraped = text("title").notna()
        for source, target in (("genres", "genre_count"), ("countries_of_origin", "country_count"), ("languages", "language_count")):
            counts = df[source].map(_language_len if source == "languages" else _list_len) if source in df else pd.Series(pd.NA, index=df.index)
            df[target] = counts.where(counts.notna(), pd.Series(0, index=df.index).where(title_scraped, pd.NA))
        df["cast_count"] = df["cast"].map(_list_len) if "cast" in df else pd.NA
    except Exception as exc:
        error_logger.error("Could not compute derived columns: %s", describe_error(exc))
        raise
    return df
