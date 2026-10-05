import time

from .advanced import extract_advanced_data
from .analysis import load_merged, save_merged
from .config import ADVANCED_WORKERS
from .extractors import extract_links
from .storage import setup_logging, year_lock


def _choose_listing(new, existing, max_movies, error_logger, results_logger):
    """Never let a partial or limit-truncated listing shrink what is already saved."""
    if existing is None or existing.empty:
        return new
    if len(new) < len(existing) and (not new.attrs.get("complete", True) or len(new) >= max_movies):
        reason = "incomplete" if not new.attrs.get("complete", True) else f"limited by --max-movies {max_movies}"
        results_logger.info("New listing (%s titles) is %s; keeping the saved listing (%s titles)", len(new), reason, len(existing))
        return existing
    return new


def _run_year(year, max_movies, workers, refresh_advanced, refresh_stages, refresh_missing, complete_release_info, listing_only,
              error_logger, results_logger):
    existing_listing, existing_details = load_merged(year)
    refresh_requested = bool(refresh_advanced or refresh_stages or refresh_missing) and not listing_only
    if refresh_requested and existing_listing is not None:
        listing = existing_listing
    else:
        new_listing = extract_links(year, error_logger, results_logger, max_movies)
        if new_listing.empty:
            results_logger.info("No titles found; nothing saved")
            print(f"Year {year}: no titles found, nothing saved")
            return
        listing = _choose_listing(new_listing, existing_listing, max_movies, error_logger, results_logger)
        save_merged(year, listing, existing_details, error_logger, results_logger)
    if not listing_only:
        extract_advanced_data(
            year, listing, error_logger, results_logger, workers=workers,
            refresh_advanced=refresh_advanced, refresh_stages=refresh_stages,
            refresh_missing=refresh_missing, complete_release_info=complete_release_info,
            max_movies=max_movies,
        )


def process_year(
    year, max_movies=1000, workers=ADVANCED_WORKERS,
    refresh_advanced=False, refresh_stages=None, refresh_missing=False,
    complete_release_info=True, listing_only=False,
):
    print(f"Year {year}: starting")
    start = time.time()
    error_logger, results_logger = setup_logging(year)
    try:
        with year_lock(year):
            _run_year(year, max_movies, workers, refresh_advanced, refresh_stages, refresh_missing,
                      complete_release_info, listing_only, error_logger, results_logger)
        print(f"Year {year}: done in {time.time() - start:.0f}s")
    except Exception as exc:
        error_logger.error("Year %s aborted: %s", year, exc)
        print(f"Year {year}: failed ({exc}); see Logs/{year}/errors.txt")


def retry_failed_year(year, workers=ADVANCED_WORKERS, complete_release_info=True):
    print(f"Year {year}: retrying failed titles")
    start = time.time()
    error_logger, results_logger = setup_logging(year)
    try:
        with year_lock(year):
            listing, _ = load_merged(year)
            if listing is None:
                print(f"Year {year}: no saved data to retry")
                return
            extract_advanced_data(
                year, listing, error_logger, results_logger,
                retry_failed_only=True, workers=workers, complete_release_info=complete_release_info,
            )
        print(f"Year {year}: retry done in {time.time() - start:.0f}s")
    except Exception as exc:
        error_logger.error("Year %s retry aborted: %s", year, exc)
        print(f"Year {year}: failed ({exc}); see Logs/{year}/errors.txt")
