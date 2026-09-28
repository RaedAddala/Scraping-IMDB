import ast
import re

import pandas as pd

from .config import ADVANCED_COLUMNS
from .storage import read_csv_fast, read_csv_or_empty, year_paths


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
