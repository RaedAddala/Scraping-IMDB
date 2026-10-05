import time

import pandas as pd

from .advanced import extract_advanced_data
from .analysis import compute_derived_columns, merge_data
from .config import ADVANCED_WORKERS, BASIC_SCHEMA, MERGED_SCHEMA, STATUS_SCHEMA
from .extractors import extract_links
from .storage import (
    read_csv_fast,
    read_csv_or_empty,
    setup_directories,
    setup_logging,
    write_csv_safely,
    year_paths,
)


def _rebuild_merged(year, data_dir, paths, error_logger, results_logger):
    merged = merge_data(year, data_dir, error_logger, results_logger)
    write_csv_safely(compute_derived_columns(merged, error_logger, results_logger), paths["merged"], MERGED_SCHEMA)


def process_year(
    year, max_movies=1000, workers=ADVANCED_WORKERS,
    refresh_advanced=False, refresh_stages=None, refresh_missing=False,
    complete_release_info=True, listing_only=False,
):
    print(f"Starting processing for year {year}")
    start = time.time()
    data_dir, _ = setup_directories(year)
    paths = year_paths(year)
    error_logger, results_logger = setup_logging(year)
    try:
        refresh_requested = bool(refresh_advanced or refresh_stages or refresh_missing) and not listing_only
        if refresh_requested and paths["basic"].exists():
            links = read_csv_fast(paths["basic"])
            if max_movies >= 0:
                links = links.head(max_movies)
            results_logger.info("Loaded %s existing basic rows for targeted refresh of %s", len(links), year)
        else:
            links = extract_links(year, error_logger, results_logger, max_movies)
        if links.empty:
            results_logger.info("No links extracted for %s; skipping advanced extraction and merge", year)
            print(f"No links extracted for year {year}; skipping advanced extraction and merge")
            return
        if not refresh_requested or not paths["basic"].exists():
            existing_rows = len(read_csv_fast(paths["basic"])) if paths["basic"].exists() else 0
            if not links.attrs.get("complete", True) and len(links) < existing_rows:
                # A partial listing must not replace a more complete saved one.
                error_logger.error("Listing for %s was incomplete (%s rows < %s saved); keeping the saved listing", year, len(links), existing_rows)
                print(f"Listing for year {year} was incomplete; keeping the saved listing")
                links = read_csv_fast(paths["basic"])
            else:
                write_csv_safely(links, paths["basic"], BASIC_SCHEMA)
        if not listing_only:
            extract_advanced_data(
                year, links, error_logger, results_logger, workers=workers,
                refresh_advanced=refresh_advanced, refresh_stages=refresh_stages,
                refresh_missing=refresh_missing, complete_release_info=complete_release_info,
            )
        _rebuild_merged(year, data_dir, paths, error_logger, results_logger)
        print(f"Processing completed for year {year} in {time.time() - start:.2f} seconds")
    except Exception as exc:
        error_logger.error("Critical error during processing for year %s: %s", year, exc)
        print(f"Error: Processing failed for year {year}: {exc}")


def retry_failed_year(year, workers=ADVANCED_WORKERS, complete_release_info=True):
    print(f"Retrying failed advanced links for year {year}")
    start = time.time()
    data_dir, _ = setup_directories(year)
    paths = year_paths(year)
    error_logger, results_logger = setup_logging(year)
    status = read_csv_or_empty(paths["status"], STATUS_SCHEMA)
    failed = status[status["status"] == "failed"] if "status" in status else pd.DataFrame(columns=list(STATUS_SCHEMA))
    if failed.empty:
        results_logger.info("No failed advanced links to retry for %s", year)
        print(f"No failed advanced links to retry for year {year}")
        return
    extract_advanced_data(
        year, failed, error_logger, results_logger,
        retry_failed_only=True, workers=workers, complete_release_info=complete_release_info,
    )
    _rebuild_merged(year, data_dir, paths, error_logger, results_logger)
    print(f"Retry completed for year {year} in {time.time() - start:.2f} seconds")
