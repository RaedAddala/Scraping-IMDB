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
    MAX_CONSECUTIVE_FAILURES,
    NETWORK_BACKOFF_SECONDS,
    NETWORK_ERROR_THRESHOLD,
    STATUS_COLUMNS,
    STATUS_SCHEMA,
    STAGE_FIELDS,
    WORKER_RESULT_TIMEOUT_SECONDS,
)
from .extractors import (
    StageExtractionError,
    _extract_advanced_stages,
)
from .analysis import load_merged, save_merged
from .quality import log_quality
from .storage import (
    describe_error,
    is_missing,
    append_attempt_log,
    log_timing_summary,
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
    """One line naming the fields that are mostly empty (a quick data-quality signal)."""
    if df.empty:
        return
    sparse = {}
    for column in ADVANCED_COLUMNS:
        if column in {"imdb_id", "credits_incomplete", "top_rated_rank"} or column not in df:  # empty by design
            continue
        filled = df[column].map(_has_data).mean()
        if filled < 0.5:
            sparse[column] = round(filled * 100)
    if sparse:
        worst = sorted(sparse.items(), key=lambda item: item[1])[:12]
        results_logger.info("Fields under 50%% filled (%s titles): %s", len(df), ", ".join(f"{k} {v}%" for k, v in worst))
    else:
        results_logger.info("All fields at least 50%% filled (%s titles)", len(df))


def _stage_seconds(timings):
    """{'title_page': 3.2, ...} from the extractors' timing keys."""
    return {
        key[: -len("_seconds")]: value for key, value in timings.items()
        if key.endswith("_seconds") and key[: -len("_seconds")] in ADVANCED_STAGES
    }


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
                message = describe_error(exc)
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
                        message = describe_error(retry_exc)
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
        result_queue.put({"worker_done": True, "worker_id": worker_id, "worker_error": describe_error(exc)})
        return
    finally:
        _close_driver(driver)
    result_queue.put({"worker_done": True, "worker_id": worker_id, "worker_error": None})


def _attempt_advanced_links(link_records, status_records, attempt_log_path, error_logger, phase, workers=ADVANCED_WORKERS, checkpoint=None, run_state=None):
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
    consecutive_failures = 0
    interrupted = False
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
                "timestamp": now_iso(), "phase": phase, "imdb_id": link, "attempt": record["_attempt_count"],
                "stages": record.get("_stages") or list(ADVANCED_STAGES),
                "seconds": _stage_seconds(outcome["timings"]),
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
                error_logger.error("%s [%s #%s] %s", link, phase, record["_attempt_count"], message)
            append_attempt_log(attempt_log_path, event)
            consecutive_failures = consecutive_failures + 1 if outcome["error"] is not None else 0
            if checkpoint and completed_count % CHECKPOINT_INTERVAL == 0:
                checkpoint([row for _, row in sorted(completed_rows)])
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                if run_state is not None:
                    run_state["stopped_early"] = f"{consecutive_failures} titles in a row failed"
                break
    except BaseException:
        interrupted = True  # e.g. Ctrl+C: keep what was scraped so far
        raise
    finally:
        cancel_event.set()
        for thread in threads:
            thread.join()
        if interrupted and checkpoint:
            checkpoint([row for _, row in sorted(completed_rows)])
    deliberately_stopped = bool(run_state and run_state.get("stopped_early"))
    for record in scheduled:
        if record["_order"] in processed_orders:
            continue
        if deliberately_stopped:
            # Never attempted because the run stopped early: leave the title as it was, not as a failure.
            status_records[record["imdb_id"]]["attempt_count"] -= 1
            continue
        message = "Worker stopped before reporting this record"
        status = status_records[record["imdb_id"]]
        status.update(status="failed", last_error=message, completed_at=None)
        retry_record = {key: value for key, value in record.items() if key not in {"_order", "_attempt_count"}}
        failures.append((record["_order"], retry_record))
        error_logger.error("%s [%s #%s] %s", record["imdb_id"], phase, record["_attempt_count"], message)
        append_attempt_log(attempt_log_path, {
            "timestamp": now_iso(), "phase": phase, "imdb_id": record["imdb_id"], "attempt": record["_attempt_count"],
            "stages": record.get("_stages") or list(ADVANCED_STAGES), "status": "failed", "error": message,
        })
    return (
        [row for _, row in sorted(completed_rows)],
        [record for _, record in sorted(failures)],
    )


def extract_advanced_data(
    year, listing_df, error_logger, results_logger, retry_failed_only=False,
    workers=ADVANCED_WORKERS, refresh_advanced=False, refresh_stages=None,
    refresh_missing=False, complete_release_info=True, max_movies=None,
):
    """Scrape the details of the listing's titles and save the merged file (the resume checkpoint) as it goes.
    max_movies only limits how many titles are scraped; the merged file always covers the whole listing."""
    start = time.time()
    paths = year_paths(year)
    link_records = _records_from_df(listing_df)
    if not link_records:
        error_logger.error("No titles to scrape for %s", year)
        return load_merged(year)[1]
    scrape_records = link_records if max_movies is None or max_movies < 0 else link_records[:max_movies]

    _, existing_advanced = load_merged(year)
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
        # Saved details only stand in for a missing status when every stage has values;
        # a partial row is never promoted to completed.
        existing_row = existing_by_link.get(record["imdb_id"])
        if (
            existing_row is not None and status.get("status") not in {"completed", "failed"}
            and not _missing_stages(existing_row)
        ):
            status.update(status="completed", last_error=None, completed_at=status.get("completed_at") or now_iso())

    candidates = []
    requested_stages = tuple(refresh_stages or ADVANCED_STAGES)
    for source_record in scrape_records:
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
    run_state = {}

    def save(new_rows):
        _write_status(paths["status"], status_records)
        details = _combine_advanced(existing_advanced, new_rows)
        merged = save_merged(year, listing_df, details, error_logger, results_logger)
        return details, merged

    if candidates:
        first_rows, failures = _attempt_advanced_links(
            candidates, status_records, paths["attempts"], error_logger,
            "retry" if retry_failed_only else "initial", workers=workers,
            checkpoint=lambda phase_rows: save(rows + phase_rows)[0], run_state=run_state,
        )
        rows.extend(first_rows)
        if failures and not retry_failed_only and not run_state:
            results_logger.info("Retrying %s failed titles once", len(failures))
            retry_rows, failures = _attempt_advanced_links(
                failures, status_records, paths["attempts"], error_logger,
                "auto_retry", workers=workers, checkpoint=lambda phase_rows: save(rows + phase_rows)[0],
            )
            rows.extend(retry_rows)

    details, merged = save(rows)
    log_quality(merged, results_logger)
    log_timing_summary(paths["attempts"], results_logger)
    log_field_completeness(details, results_logger)
    results_logger.info(
        "Details: %s titles scraped, %s still failed, %.0fs",
        len(candidates), len(failures), time.time() - start,
    )
    if run_state:
        message = f"stopped early: {run_state['stopped_early']} (IMDb may be blocking requests); resume later or use --retry-failed"
        error_logger.error("Year %s %s", year, message)
        raise RuntimeError(message)
    return details
