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
    SCRAPE_VERSION,
    STATUS_COLUMNS,
    STAGE_FIELDS,
    WORKER_RESULT_TIMEOUT_SECONDS,
)
from .extractors import (
    StageExtractionError,
    _advanced_row_template,
    _extract_advanced_stages,
    _is_missing_value,
)
from .storage import (
    append_attempt_log,
    log_advanced_timing_summary,
    now_iso,
    read_csv_or_empty,
    write_csv_safely,
    year_paths,
)


def _string_or_none(value):
    if _is_missing_value(value):
        return None
    return str(value)


def _links_from_df(links_df):
    link_column = "Movie Link" if "Movie Link" in links_df.columns else "link" if "link" in links_df.columns else None
    if not link_column:
        return []
    title_column = "Title" if "Title" in links_df.columns else "title" if "title" in links_df.columns else None
    records = []
    for _, item in links_df.iterrows():
        link = _string_or_none(item.get(link_column))
        if not link:
            continue
        records.append({"link": link, "title": _string_or_none(item.get(title_column)) if title_column else None})
    return list({record["link"]: record for record in records}.values())


def _status_records(status_df):
    records = {}
    for _, item in status_df.iterrows():
        link = _string_or_none(item.get("link"))
        if not link:
            continue
        records[link] = {column: _string_or_none(item.get(column)) for column in STATUS_COLUMNS}
        try:
            records[link]["attempt_count"] = int(float(records[link].get("attempt_count") or 0))
        except ValueError:
            records[link]["attempt_count"] = 0
    return records


def _write_status(path, records):
    rows = []
    for record in records.values():
        rows.append({column: record.get(column) for column in STATUS_COLUMNS})
    write_csv_safely(pd.DataFrame(rows, columns=STATUS_COLUMNS), path)


def _combine_advanced(existing_df, new_rows):
    new_df = pd.DataFrame(new_rows, columns=ADVANCED_COLUMNS)
    combined = pd.concat([existing_df, new_df], ignore_index=True)
    if "link" in combined.columns:
        combined = combined.dropna(subset=["link"]).drop_duplicates(subset=["link"], keep="last")
    for column in ADVANCED_COLUMNS:
        if column not in combined.columns:
            combined[column] = None
    return combined[ADVANCED_COLUMNS]


def _has_data(value):
    if _is_missing_value(value):
        return False
    return str(value).strip().lower() not in {"", "[]", "none", "nan", "null", "<na>"}


def _missing_stages(row):
    missing = []
    for stage, fields in STAGE_FIELDS.items():
        if not any(_has_data(row.get(field)) for field in fields):
            missing.append(stage)
    return missing


def log_field_completeness(df, results_logger):
    if df.empty:
        return
    counts = {
        column: int(df[column].map(_has_data).sum()) if column in df else 0
        for column in ADVANCED_COLUMNS if column not in {"link", "scrape_version"}
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


def _advanced_worker(worker_id, work_items, work_lock, result_queue, error_logger, cancel_event, pop_left):
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
                row = _extract_advanced_stages(driver, record, error_logger, timings)
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
                partial_row = None
                if isinstance(exc, StageExtractionError):
                    partial_row = exc.partial_row
                    failed_record["_existing_row"] = partial_row
                    failed_record["_stages"] = exc.remaining_stages
                if _is_session_error(message):
                    _close_driver(driver)
                    driver = None
                    try:
                        driver = create_edge_driver()
                        retry_timings = {}
                        row = _extract_advanced_stages(driver, failed_record, error_logger, retry_timings)
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
        link, title = record["link"], record.get("title")
        status = status_records.setdefault(link, {
            "link": link, "title": title, "status": "pending", "attempt_count": 0,
            "last_error": None, "last_attempted_at": None, "completed_at": None,
            "scrape_version": None,
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
            args=(worker_id, work_items, work_lock, result_queue, error_logger, cancel_event, worker_id == 1),
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
            link = record["link"]
            status = status_records[link]
            event = {
                "timestamp": now_iso(), "phase": phase, "link": link,
                "title": status.get("title"), "attempt_count": record["_attempt_count"],
                "total_seconds": outcome["total_seconds"], "timings": outcome["timings"],
                "worker_id": outcome["worker_id"], "stages": record.get("_stages") or list(ADVANCED_STAGES),
            }
            if outcome["error"] is None:
                status.update(status="completed", last_error=None, completed_at=now_iso(), scrape_version=SCRAPE_VERSION)
                completed_rows.append((record["_order"], outcome["row"]))
                event["status"] = "completed"
            else:
                message = outcome["error"]
                status.update(status="failed", last_error=message, completed_at=None)
                if outcome.get("row") is not None:
                    completed_rows.append((record["_order"], outcome["row"]))
                retry_record = {
                    key: value for key, value in record.items()
                    if key not in {"_order", "_attempt_count"}
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
        status = status_records[record["link"]]
        status.update(status="failed", last_error=message, completed_at=None)
        retry_record = {key: value for key, value in record.items() if key not in {"_order", "_attempt_count"}}
        failures.append((record["_order"], retry_record))
        append_attempt_log(attempt_log_path, {
            "timestamp": now_iso(), "phase": phase, "link": record["link"],
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
    refresh_missing=False, complete_release_info=False,
):
    start = time.time()
    paths = year_paths(year)
    link_records = _links_from_df(links_df)
    if not link_records:
        error_logger.error("Advanced extraction requires a 'Movie Link' or 'link' column with at least one URL")
        return read_csv_or_empty(paths["advanced"], ADVANCED_COLUMNS)

    existing_advanced = read_csv_or_empty(paths["advanced"], ADVANCED_COLUMNS)
    existing_by_link = {
        str(row["link"]): row
        for row in existing_advanced.to_dict("records") if _has_data(row.get("link"))
    }
    completed_links = set(existing_advanced["link"].dropna().astype(str)) if "link" in existing_advanced else set()
    status_records = _status_records(read_csv_or_empty(paths["status"], STATUS_COLUMNS))
    for record in link_records:
        status = status_records.setdefault(record["link"], {
            "link": record["link"], "title": record.get("title"), "status": "pending",
            "attempt_count": 0, "last_error": None, "last_attempted_at": None, "completed_at": None,
            "scrape_version": None,
        })
        if record.get("title") and not status.get("title"):
            status["title"] = record["title"]
        if record["link"] in completed_links and status.get("status") != "completed":
            status.update(status="completed", last_error=None, completed_at=status.get("completed_at") or now_iso())

    candidates = []
    requested_stages = tuple(refresh_stages or ADVANCED_STAGES)
    for source_record in link_records:
        record = dict(source_record)
        existing_row = existing_by_link.get(record["link"])
        status_value = status_records.get(record["link"], {}).get("status")
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
        write_csv_safely(_combine_advanced(existing_advanced, checkpoint_rows), paths["advanced"])

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
    write_csv_safely(advanced, paths["advanced"])
    log_advanced_timing_summary(paths["attempts"], results_logger)
    log_field_completeness(advanced, results_logger)
    results_logger.info(
        "Advanced extraction completed for %s: %s new rows, %s total rows, %s unresolved failures, %.2f seconds",
        year, len(rows), len(advanced), len(failures), time.time() - start,
    )
    return advanced
