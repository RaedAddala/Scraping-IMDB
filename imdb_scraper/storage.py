import json
import logging
import os
import time
from contextlib import contextmanager
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
        "merged": data_dir / f"merged_movies_data_{year}.csv",  # the only file in Data/; also the resume checkpoint
        "status": logs_dir / f"scrape_status_{year}.csv",
        "attempts": logs_dir / f"scrape_attempts_{year}.jsonl",
    }


@contextmanager
def year_lock(year):
    """Exclusive per-year lock so two runs can never write the same year's files at once."""
    _, logs_dir = setup_directories(year)
    handle = open(logs_dir / ".lock", "a+")
    try:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError(f"another run is already working on year {year}") from None
        yield
    finally:
        handle.close()  # closing releases the lock


def setup_directories(year):
    paths = year_paths(year)
    data_dir, logs_dir = paths["data_dir"], paths["logs_dir"]
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    return data_dir, logs_dir


def setup_logging(year):
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
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
    for attempt in range(6):
        try:
            temp_path.replace(path)
            return
        except PermissionError:
            if attempt == 5:
                raise PermissionError(f"Cannot write {path.name}: the file is open in another program (close it, e.g. Excel)")
            time.sleep(2)  # an editor or antivirus scan may hold the file briefly


# Only an empty cell is missing, and everything is read as text so values round-trip exactly (no
# 1995 -> 1995.0, no timestamp re-formatting). The default C parser is used on purpose: the pyarrow
# engine infers types first and would rewrite values such as dates before casting them to text.
_CSV_OPTIONS = {"keep_default_na": False, "na_values": [""], "dtype": str}


def read_csv_fast(path):
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


def describe_error(error, limit=160):
    """One short line for an exception or message: 'ErrorType: first line', no browser stack traces."""
    if isinstance(error, BaseException):
        text = str(error)
        name = None if type(error).__name__ == "StageExtractionError" else type(error).__name__  # message already says it
    else:
        text, name = str(error), None
    text = text.split("Stacktrace:")[0].replace("Message:", "")
    line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if len(line) > limit:
        line = line[: limit - 1] + "…"
    return f"{name}: {line}" if name and line else (name or line)


def log_timing_summary(path, results_logger):
    """One line: average seconds per stage over the logged attempts."""
    try:
        with Path(path).open(encoding="utf-8") as handle:
            events = [json.loads(line) for line in handle if line.strip()]
    except (OSError, json.JSONDecodeError):
        return
    seconds = {}
    for event in events:
        for stage, value in (event.get("seconds") or {}).items():
            seconds.setdefault(stage, []).append(value)
    if seconds:
        average = ", ".join(f"{stage} {sum(v) / len(v):.1f}s" for stage, v in seconds.items())
        results_logger.info("Average time per stage over %s attempts: %s", len(events), average)
