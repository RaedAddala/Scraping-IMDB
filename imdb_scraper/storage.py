import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import SCRIPT_DIR


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
            handler = logging.FileHandler(path, encoding="utf-8")
            handler.setLevel(level)
            handler.setFormatter(formatter)
            logger.addHandler(handler)
    return error_logger, results_logger


def is_missing(value):
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False  # lists and other containers


def _json_cell(value):
    if isinstance(value, str) or is_missing(value):
        return None if is_missing(value) else value
    if isinstance(value, (list, tuple, dict)) and not value:
        return None
    return json.dumps(value, ensure_ascii=False)


def _bool_cell(value):
    if is_missing(value):
        return None
    return str(value).strip().lower() in {"true", "1"}


def format_frame(df, schema):
    """Return df with exactly the schema's columns, in order, cast to the schema's types."""
    out = pd.DataFrame(index=df.index)
    for column, kind in schema.items():
        series = df[column] if column in df else pd.Series(None, index=df.index, dtype=object)
        if kind == "int":
            out[column] = pd.to_numeric(series, errors="coerce").round().astype("Int64")
        elif kind == "float":
            out[column] = pd.to_numeric(series, errors="coerce").astype("Float64")
        elif kind == "bool":
            out[column] = series.map(_bool_cell).astype("boolean")
        elif kind == "json":
            out[column] = series.map(_json_cell).astype(object)
        else:
            out[column] = series.map(lambda value: None if is_missing(value) else str(value)).astype(object)
    return out.reset_index(drop=True)


def write_csv_safely(df, path, schema=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if schema is not None:
        df = format_frame(df, schema)
    temp_path = path.with_name(f"{path.name}.tmp")
    df.to_csv(temp_path, index=False, encoding="utf-8")
    temp_path.replace(path)


# Only an empty cell is missing, and everything is read as text so values round-trip exactly
# (no 1995 -> 1995.0). Callers cast with format_frame / pd.to_numeric where they need numbers.
_CSV_OPTIONS = {"keep_default_na": False, "na_values": [""], "dtype": str}


def read_csv_fast(path):
    try:
        return pd.read_csv(path, engine="pyarrow", **_CSV_OPTIONS)
    except Exception:
        return pd.read_csv(path, **_CSV_OPTIONS)


def read_csv_or_empty(path, schema):
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=list(schema))
    df = read_csv_fast(path)
    for column in schema:
        if column not in df.columns:
            df[column] = None
    if "imdb_id" in df.columns:
        df = df.dropna(subset=["imdb_id"]).drop_duplicates(subset=["imdb_id"], keep="last")
    return df.reset_index(drop=True)


def parse_json_cell(value):
    """Parse a JSON column cell; missing or malformed text gives None."""
    if is_missing(value):
        return None
    try:
        return json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        return None


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append_attempt_log(path, event):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def log_advanced_timing_summary(path, results_logger):
    try:
        with Path(path).open(encoding="utf-8") as handle:
            events = [json.loads(line) for line in handle if line.strip()]
        timed_events = [event for event in events if isinstance(event.get("total_seconds"), (int, float))]
        if not timed_events:
            return
        stages = ("title_page", "parental_guide", "full_credits", "release_info")
        summary = {}
        for stage in stages:
            durations = [event.get("timings", {}).get(f"{stage}_seconds") for event in timed_events]
            durations = [duration for duration in durations if isinstance(duration, (int, float))]
            ready_values = [event.get("timings", {}).get(f"{stage}_content_ready") for event in timed_events]
            navigation_timeouts = [event.get("timings", {}).get(f"{stage}_navigation_timed_out") for event in timed_events]
            summary[stage] = {
                "average_seconds": round(sum(durations) / len(durations), 2) if durations else None,
                "content_not_ready": sum(value is False for value in ready_values),
                "navigation_timed_out": sum(value is True for value in navigation_timeouts),
            }
        results_logger.info(
            "Advanced timing summary for %s attempts: average total %.2fs; stages=%s",
            len(timed_events),
            sum(event["total_seconds"] for event in timed_events) / len(timed_events),
            json.dumps(summary, sort_keys=True),
        )
    except (OSError, json.JSONDecodeError) as exc:
        results_logger.warning("Could not summarize advanced timings: %s", exc)
