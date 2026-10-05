import json
import time
from collections import deque
from queue import Empty, Queue
from threading import Event, Lock, Thread

import pandas as pd
from selenium.common.exceptions import WebDriverException

from .browser import create_edge_driver
from .config import (
    ADVANCED_COLUMNS,
    ADVANCED_STAGES,
    ADVANCED_WORKERS,
    CHECKPOINT_INTERVAL,
    NETWORK_BACKOFF_SECONDS,
    NETWORK_ERROR_THRESHOLD,
    ADVANCED_SCHEMA,
    STATUS_COLUMNS,
    STATUS_SCHEMA,
    STAGE_FIELDS,
    WORKER_RESULT_TIMEOUT_SECONDS,
)
from .extractors import (
    StageExtractionError,
    _extract_advanced_stages,
)
from .storage import (
    is_missing,
    append_attempt_log,
    log_advanced_timing_summary,
    now_iso,
    read_csv_or_empty,
    write_csv_safely,
    year_paths,
)


def _string_or_none(value):
    if is_missing(value):
        return None
    return str(value)


def _records_from_df(listing_df):
    """Unique titles (by IMDb ID) from a listing or status frame, in order."""
    if "imdb_id" not in listing_df.columns:
        return []
    title_column = "listing_title" if "listing_title" in listing_df.columns else "title" if "title" in listing_df.columns else None
    records = {}
    for _, item in listing_df.iterrows():
        imdb_id = _string_or_none(item.get("imdb_id"))
        if imdb_id and imdb_id not in records:
            records[imdb_id] = {"imdb_id": imdb_id, "title": _string_or_none(item.get(title_column)) if title_column else None}
    return list(records.values())


def _status_records(status_df):
    records = {}
    for _, item in status_df.iterrows():
        link = _string_or_none(item.get("imdb_id"))
        if not link:
            continue
        records[link] = {column: _string_or_none(item.get(column)) for column in STATUS_COLUMNS}
        records[link]["imdb_id"] = link
        try:
            records[link]["attempt_count"] = int(float(records[link].get("attempt_count") or 0))
        except ValueError:
            records[link]["attempt_count"] = 0
    return records


def _write_status(path, records):
    rows = []
    for record in records.values():
        rows.append({column: record.get(column) for column in STATUS_COLUMNS})
    write_csv_safely(pd.DataFrame(rows, columns=STATUS_COLUMNS), path, STATUS_SCHEMA)


def _combine_advanced(existing_df, new_rows):
    new_df = pd.DataFrame(new_rows, columns=ADVANCED_COLUMNS)
    combined = pd.concat([existing_df, new_df], ignore_index=True)
    if "imdb_id" in combined.columns:
        combined = combined.dropna(subset=["imdb_id"]).drop_duplicates(subset=["imdb_id"], keep="last")
    for column in ADVANCED_COLUMNS:
        if column not in combined.columns:
            combined[column] = None
    return combined[ADVANCED_COLUMNS]


def _has_data(value):
    if is_missing(value):
        return False
    return str(value).strip().lower() not in {"", "[]", "{}", "nan", "null", "<na>"}


def _missing_stages(row):
    missing = []
    for stage, fields in STAGE_FIELDS.items():
        if not any(_has_data(row.get(field)) for field in fields):
            missing.append(stage)
    return missing


def _load_stage_status(record):
    try:
        loaded = json.loads(record.get("stage_status") or "{}")
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _record_stage_outcomes(status, completed_stages, failed_stage=None, error=None):
    """Keep per-stage state so a row's existence is never taken as proof of stage success."""
    stages = _load_stage_status(status)
    for stage in completed_stages:
        stages[stage] = {"status": "completed", "error": None}
    if failed_stage:
        stages[failed_stage] = {"status": "failed", "error": error}
    status["stage_status"] = json.dumps(stages, sort_keys=True)


def _reconcile_with_history(status_records, attempts_path, results_logger=None):
    """A link whose latest logged attempt failed cannot be 'completed', whatever the status file says."""
    try:
        with open(attempts_path, encoding="utf-8") as handle:
            events = [json.loads(line) for line in handle if line.strip()]
    except (OSError, ValueError):
        return 0
    latest = {}
    for event in events:
        link = event.get("imdb_id")
        if link:
            latest[link] = event
    fixed = 0
    for link, event in latest.items():
        status = status_records.get(link)
        if status and status.get("status") == "completed" and event.get("status") == "failed":
            status.update(status="failed", last_error=event.get("error") or "Latest logged attempt failed", completed_at=None)
            fixed += 1
    if fixed and results_logger:
        results_logger.info("Reconciled %s links marked completed whose latest attempt failed", fixed)
    return fixed


def log_field_completeness(df, results_logger):
    if df.empty:
        return
    counts = {
        column: int(df[column].map(_has_data).sum()) if column in df else 0
        for column in ADVANCED_COLUMNS if column != "imdb_id"
    }
    results_logger.info(
        "Advanced field completeness for %s rows: %s",
        len(df),
        json.dumps({column: round(count / len(df) * 100, 1) for column, count in counts.items()}, sort_keys=True),
    )


def _close_driver(driver):
    if driver is not None:
        try:
            driver.quit()
        except WebDriverException:
            pass


def _is_network_error(message):
    lowered = str(message).lower()
    return any(token in lowered for token in (
        "err_name_not_resolved", "err_connection_reset", "err_internet_disconnected",
        "err_connection_timed_out", "err_network_changed", "privacy error", "pagecontenterror",
    ))


def _is_session_error(message):
    lowered = str(message).lower()
    return any(token in lowered for token in (
        "invalid session id", "disconnected", "tab crashed", "no such window",
    ))


def _advanced_worker(worker_id, work_items, work_lock, result_queue, cancel_event, pop_left):
    driver = None
    consecutive_network_errors = 0
    try:
        driver = create_edge_driver()
        while not cancel_event.is_set():
            with work_lock:
                if not work_items:
                    break
                record = work_items.popleft() if pop_left else work_items.pop()
            timings = {}
            started_at = time.perf_counter()
            try:
                row = _extract_advanced_stages(driver, record, timings)
                result_queue.put({
                    "worker_id": worker_id,
                    "record": record,
                    "row": row,
                    "error": None,
                    "total_seconds": round(time.perf_counter() - started_at, 3),
                    "timings": timings,
                })
                consecutive_network_errors = 0
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                failed_record = dict(record)
                failed_record["_attempted_stages"] = list(record.get("_stages") or ADVANCED_STAGES)
                partial_row = None
                if isinstance(exc, StageExtractionError):
                    partial_row = exc.partial_row
                    failed_record["_existing_row"] = partial_row
                    failed_record["_stages"] = exc.remaining_stages
                    failed_record["_failed_stage"] = exc.stage
                if _is_session_error(message):
                    _close_driver(driver)
                    driver = None
                    try:
                        driver = create_edge_driver()
                        retry_timings = {}
                        row = _extract_advanced_stages(driver, failed_record, retry_timings)
                        timings.update({f"recovery_{key}": value for key, value in retry_timings.items()})
                        result_queue.put({
                            "worker_id": worker_id, "record": record, "row": row, "error": None,
                            "total_seconds": round(time.perf_counter() - started_at, 3), "timings": timings,
                        })
                        consecutive_network_errors = 0
                        continue
                    except Exception as retry_exc:
                        message = f"{type(retry_exc).__name__}: {retry_exc}"
                        if isinstance(retry_exc, StageExtractionError):
                            partial_row = retry_exc.partial_row
                            failed_record["_existing_row"] = partial_row
                            failed_record["_stages"] = retry_exc.remaining_stages
                            failed_record["_failed_stage"] = retry_exc.stage
                consecutive_network_errors = consecutive_network_errors + 1 if _is_network_error(message) else 0
                result_queue.put({
                    "worker_id": worker_id,
                    "record": failed_record,
                    "row": partial_row,
                    "error": message,
                    "total_seconds": round(time.perf_counter() - started_at, 3),
                    "timings": timings,
                })
                if consecutive_network_errors >= NETWORK_ERROR_THRESHOLD and not cancel_event.is_set():
                    time.sleep(NETWORK_BACKOFF_SECONDS)
                    _close_driver(driver)
                    driver = create_edge_driver()
                    consecutive_network_errors = 0
    except Exception as exc:
        result_queue.put({"worker_done": True, "worker_id": worker_id, "worker_error": f"{type(exc).__name__}: {exc}"})
        return
    finally:
        _close_driver(driver)
    result_queue.put({"worker_done": True, "worker_id": worker_id, "worker_error": None})


def _attempt_advanced_links(link_records, status_records, attempt_log_path, error_logger, phase, workers=ADVANCED_WORKERS, checkpoint=None):
    if not link_records:
        return [], []
    scheduled = []
    for order, original in enumerate(link_records):
        record = dict(original)
        record["_order"] = order
        link, title = record["imdb_id"], record.get("title")
        status = status_records.setdefault(link, {
            "imdb_id": link, "title": title, "status": "pending", "attempt_count": 0,
            "last_error": None, "last_attempted_at": None, "completed_at": None,
            "stage_status": None,
        })
        if title and not status.get("title"):
            status["title"] = title
        status["attempt_count"] = int(status.get("attempt_count") or 0) + 1
        status["last_attempted_at"] = now_iso()
        record["_attempt_count"] = status["attempt_count"]
        scheduled.append(record)

    worker_count = max(1, min(int(workers), 2, len(scheduled)))
    work_items = deque(scheduled)
    work_lock = Lock()
    result_queue = Queue()
    cancel_event = Event()
    threads = []
    for worker_id in range(1, worker_count + 1):
        thread = Thread(
            target=_advanced_worker,
            args=(worker_id, work_items, work_lock, result_queue, cancel_event, worker_id == 1),
            name=f"imdb-worker-{worker_id}",
        )
        thread.start()
        threads.append(thread)

    completed_rows, failures, processed_orders = [], [], set()
    completed_count = 0
    finished_workers = 0
    try:
        while completed_count < len(scheduled) and finished_workers < len(threads):
            try:
                outcome = result_queue.get(timeout=WORKER_RESULT_TIMEOUT_SECONDS)
            except Empty:
                if not any(thread.is_alive() for thread in threads):
                    break
                continue
            if outcome.get("worker_done"):
                finished_workers += 1
                if outcome.get("worker_error"):
                    error_logger.error("Worker %s stopped: %s", outcome["worker_id"], outcome["worker_error"])
                continue
            completed_count += 1
            record = outcome["record"]
            processed_orders.add(record["_order"])
            link = record["imdb_id"]
            status = status_records[link]
            event = {
                "timestamp": now_iso(), "phase": phase, "imdb_id": link,
                "title": status.get("title"), "attempt_count": record["_attempt_count"],
                "total_seconds": outcome["total_seconds"], "timings": outcome["timings"],
                "worker_id": outcome["worker_id"], "stages": record.get("_stages") or list(ADVANCED_STAGES),
            }
            attempted = list(record.get("_attempted_stages") or record.get("_stages") or ADVANCED_STAGES)
            if outcome["error"] is None:
                _record_stage_outcomes(status, attempted)
                all_done = all(
                    _load_stage_status(status).get(stage, {}).get("status") == "completed"
                    for stage in ADVANCED_STAGES
                )
                if all_done:
                    status.update(status="completed", last_error=None, completed_at=now_iso())
                else:
                    # A partial refresh of a link never fully scraped must not look fully scraped.
                    status.update(last_error=None)
                completed_rows.append((record["_order"], outcome["row"]))
                event["status"] = "completed"
            else:
                message = outcome["error"]
                failed_stage = record.get("_failed_stage")
                remaining = set(record.get("_stages") or []) if failed_stage else set(attempted)
                _record_stage_outcomes(
                    status, [stage for stage in attempted if stage not in remaining],
                    failed_stage=failed_stage, error=message,
                )
                status.update(status="failed", last_error=message, completed_at=None)
                if outcome.get("row") is not None:
                    completed_rows.append((record["_order"], outcome["row"]))
                retry_record = {
                    key: value for key, value in record.items()
                    if key not in {"_order", "_attempt_count", "_attempted_stages", "_failed_stage"}
                }
                failures.append((record["_order"], retry_record))
                event.update(status="failed", error=message)
                error_logger.error("Error processing URL %s: %s", link, message)
            append_attempt_log(attempt_log_path, event)
            if checkpoint and completed_count % CHECKPOINT_INTERVAL == 0:
                checkpoint([row for _, row in sorted(completed_rows)])
    finally:
        cancel_event.set()
        for thread in threads:
            thread.join()
    for record in scheduled:
        if record["_order"] in processed_orders:
            continue
        message = "Worker stopped before reporting this record"
        status = status_records[record["imdb_id"]]
        status.update(status="failed", last_error=message, completed_at=None)
        retry_record = {key: value for key, value in record.items() if key not in {"_order", "_attempt_count"}}
        failures.append((record["_order"], retry_record))
        append_attempt_log(attempt_log_path, {
            "timestamp": now_iso(), "phase": phase, "imdb_id": record["imdb_id"],
            "title": status.get("title"), "status": "failed", "attempt_count": record["_attempt_count"],
            "error": message, "total_seconds": 0.0, "timings": {}, "worker_id": None,
            "stages": record.get("_stages") or list(ADVANCED_STAGES),
        })
    return (
        [row for _, row in sorted(completed_rows)],
        [record for _, record in sorted(failures)],
    )


def extract_advanced_data(
    year, links_df, error_logger, results_logger, retry_failed_only=False,
    workers=ADVANCED_WORKERS, refresh_advanced=False, refresh_stages=None,
    refresh_missing=False, complete_release_info=True,
):
    start = time.time()
    paths = year_paths(year)
    link_records = _records_from_df(links_df)
    if not link_records:
        error_logger.error("Advanced extraction requires a 'Movie Link' or 'link' column with at least one URL")
        return read_csv_or_empty(paths["advanced"], ADVANCED_SCHEMA)

    existing_advanced = read_csv_or_empty(paths["advanced"], ADVANCED_SCHEMA)
    existing_by_link = {
        str(row["imdb_id"]): row
        for row in existing_advanced.to_dict("records") if _has_data(row.get("imdb_id"))
    }
    status_records = _status_records(read_csv_or_empty(paths["status"], STATUS_SCHEMA))
    _reconcile_with_history(status_records, paths["attempts"], results_logger)
    for record in link_records:
        status = status_records.setdefault(record["imdb_id"], {
            "imdb_id": record["imdb_id"], "title": record.get("title"), "status": "pending",
            "attempt_count": 0, "last_error": None, "last_attempted_at": None, "completed_at": None,
            "stage_status": None,
        })
        if record.get("title") and not status.get("title"):
            status["title"] = record["title"]
        # Existing advanced data only stands in for a missing status when every stage has values;
        # a partial row is never promoted to completed.
        existing_row = existing_by_link.get(record["imdb_id"])
        if (
            existing_row is not None and status.get("status") not in {"completed", "failed"}
            and not _missing_stages(existing_row)
        ):
            status.update(status="completed", last_error=None, completed_at=status.get("completed_at") or now_iso())

    candidates = []
    requested_stages = tuple(refresh_stages or ADVANCED_STAGES)
    for source_record in link_records:
        record = dict(source_record)
        existing_row = existing_by_link.get(record["imdb_id"])
        status_value = status_records.get(record["imdb_id"], {}).get("status")
        stages = None
        if retry_failed_only:
            stages = ADVANCED_STAGES if status_value == "failed" else None
        elif refresh_advanced:
            stages = ADVANCED_STAGES
        elif refresh_stages:
            stages = requested_stages
        elif refresh_missing:
            stages = tuple(_missing_stages(existing_row or {}))
        elif status_value != "completed":
            stages = ADVANCED_STAGES
        if not stages:
            continue
        record["_stages"] = list(stages)
        record["_complete_release_info"] = complete_release_info
        if existing_row:
            record["_existing_row"] = existing_row
        candidates.append(record)

    rows, failures = [], []

    def checkpoint(phase_rows):
        checkpoint_rows = rows + phase_rows
        _write_status(paths["status"], status_records)
        write_csv_safely(_combine_advanced(existing_advanced, checkpoint_rows), paths["advanced"], ADVANCED_SCHEMA)

    if candidates:
        first_rows, failures = _attempt_advanced_links(
            candidates, status_records, paths["attempts"], error_logger,
            "retry" if retry_failed_only else "initial", workers=workers, checkpoint=checkpoint,
        )
        rows.extend(first_rows)
        if failures and not retry_failed_only:
            results_logger.info("Retrying %s failed advanced links for %s once", len(failures), year)
            retry_rows, failures = _attempt_advanced_links(
                failures, status_records, paths["attempts"], error_logger,
                "auto_retry", workers=workers, checkpoint=checkpoint,
            )
            rows.extend(retry_rows)

    advanced = _combine_advanced(existing_advanced, rows)
    _write_status(paths["status"], status_records)
    write_csv_safely(advanced, paths["advanced"], ADVANCED_SCHEMA)
    log_advanced_timing_summary(paths["attempts"], results_logger)
    log_field_completeness(advanced, results_logger)
    results_logger.info(
        "Advanced extraction completed for %s: %s new rows, %s total rows, %s unresolved failures, %.2f seconds",
        year, len(rows), len(advanced), len(failures), time.time() - start,
    )
    return advanced
