import pandas as pd

from .config import ADVANCED_SCHEMA
from .storage import parse_json_cell, read_csv_fast, read_csv_or_empty, year_paths


def merge_data(year, data_dir, error_logger, results_logger):
    """Listing rows joined with their scraped details by IMDb ID. Raises on any problem."""
    try:
        paths = year_paths(year)
        basic = read_csv_fast(paths["basic"])
        if "imdb_id" not in basic.columns:
            raise ValueError("Listing CSV has no imdb_id column")
        advanced = read_csv_or_empty(paths["advanced"], ADVANCED_SCHEMA)
        merged = pd.merge(basic, advanced, how="left", on="imdb_id", validate="one_to_one")
        results_logger.info("Merged %s listing rows with %s detail rows into %s rows for %s", len(basic), len(advanced), len(merged), year)
        return merged
    except Exception as exc:
        error_logger.error("Error merging data for year %s: %s", year, exc)
        raise


def _list_len(value):
    """Length of a JSON list cell; <NA> when the cell is blank (not a fabricated zero)."""
    parsed = parse_json_cell(value)
    return len(parsed) if isinstance(parsed, list) else pd.NA


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

        precision = text("release_date_precision")
        dates = pd.to_datetime(text("release_date").where(precision == "day"), format="%Y-%m-%d", errors="coerce")
        months = pd.to_numeric(text("release_date").str.slice(5, 7), errors="coerce").where(precision.isin(["month", "day"]))
        df["first_release_date"] = df["release_dates"].map(_first_release_date) if "release_dates" in df else None
        df["release_decade"] = number("release_year") // 10 * 10
        df["release_month"] = months
        df["release_weekday"] = dates.dt.day_name()

        # Gross minus budget only when both amounts are in the same stated currency; no conversion is attempted.
        budget, gross = number("budget_amount"), number("gross_worldwide_amount")
        budget_currency, gross_currency = text("budget_currency"), text("gross_worldwide_currency")
        comparable = budget.notna() & gross.notna() & budget_currency.notna() & (budget_currency == gross_currency)
        df["gross_minus_budget"] = (gross - budget).where(comparable)
        df["gross_to_budget_ratio"] = ((gross - budget) / budget.where(budget > 0)).where(comparable).round(4)
        df["gross_comparison_currency"] = budget_currency.where(comparable)

        for source, target in (("genres", "genre_count"), ("countries_of_origin", "country_count"),
                               ("languages", "language_count"), ("cast", "cast_count")):
            df[target] = df[source].map(_list_len) if source in df else pd.NA
        results_logger.info("Computed derived columns for %s merged rows", len(df))
    except Exception as exc:
        error_logger.error("Error computing derived columns: %s", exc)
        raise
    return df
