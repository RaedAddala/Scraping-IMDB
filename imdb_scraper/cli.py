import argparse
import time

from .config import ADVANCED_WORKERS, MAX_WORKERS, YEAR_PAUSE_SECONDS
from .metadata import write_dataset_metadata
from .pipeline import process_year, rebuild_year, repair_year, retry_failed_year


def _parse_refresh_stages(value):
    aliases = {
        "title": "title_page", "title_page": "title_page",
        "parental": "parental_guide", "parental_guide": "parental_guide",
        "credits": "full_credits", "fullcredits": "full_credits", "full_credits": "full_credits",
        "release": "release_info", "releaseinfo": "release_info", "release_info": "release_info",
    }
    stages = []
    for item in str(value).split(","):
        key = item.strip().lower().replace("-", "_")
        if key not in aliases:
            raise argparse.ArgumentTypeError(f"Unknown refresh stage: {item}")
        if aliases[key] not in stages:
            stages.append(aliases[key])
    return stages


def main():
    parser = argparse.ArgumentParser(description="Scrape IMDb movie data by year.")
    parser.add_argument("--start-year", type=int, default=1942)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--max-movies", type=int, default=1000)
    parser.add_argument("--workers", type=int, choices=range(1, MAX_WORKERS + 1), default=ADVANCED_WORKERS, help="Number of independent Edge workers for advanced extraction.")
    parser.add_argument("--preview-release-info", action="store_true", help="Keep only the release-date and AKA entries embedded in the page (faster); by default every entry is expanded.")
    refresh_group = parser.add_mutually_exclusive_group()
    refresh_group.add_argument("--refresh-advanced", action="store_true", help="Re-scrape every advanced stage even for completed links.")
    refresh_group.add_argument("--refresh-missing", action="store_true", help="Re-scrape only stages with no populated fields.")
    refresh_group.add_argument("--refresh-stages", type=_parse_refresh_stages, help="Comma-separated stages to refresh: title, parental, credits, release.")
    parser.add_argument("--listing-only", action="store_true", help="Refresh only the search listing (basic CSV) and rebuild the merged file; no advanced scraping.")
    parser.add_argument("--retry-failed", action="store_true", help="Retry only links marked failed in the advanced scrape status file.")
    parser.add_argument("--fix-quality-issues", action="store_true", help="Re-scrape only the titles (and stages) that the data-quality check flags, in the year range.")
    parser.add_argument("--rebuild-derived", action="store_true", help="Recompute the derived columns of the saved CSVs in the year range (no scraping) and refresh the metadata.")
    parser.add_argument("--write-metadata", action="store_true", help="Only (re)write Data/dataset-metadata.json (Kaggle schema) and exit.")
    args = parser.parse_args()
    if args.write_metadata:
        path, count = write_dataset_metadata()
        print(f"Wrote {path} ({count} year files)")
        return
    if args.rebuild_derived:
        for year in range(args.start_year, args.end_year + 1):
            rebuild_year(year)
        path, count = write_dataset_metadata()
        print(f"Updated {path} ({count} year files)")
        return
    if args.fix_quality_issues:
        for year in range(args.start_year, args.end_year + 1):
            repair_year(year, args.workers, not args.preview_release_info)
        path, count = write_dataset_metadata()
        print(f"Updated {path} ({count} year files)")
        return
    if args.listing_only and (args.retry_failed or args.refresh_advanced or args.refresh_missing or args.refresh_stages):
        parser.error("--listing-only cannot be combined with retry or advanced refresh options")
    if args.retry_failed and (args.refresh_advanced or args.refresh_missing or args.refresh_stages):
        parser.error("--retry-failed cannot be combined with an advanced refresh option")
    for year in range(args.start_year, args.end_year + 1):
        action = "Retrying failed links" if args.retry_failed else "Processing year"
        print(f"\n{'=' * 50}\n{action} {year}\n{'=' * 50}")
        if args.retry_failed:
            retry_failed_year(year, args.workers, not args.preview_release_info)
        else:
            process_year(
                year, args.max_movies, args.workers,
                args.refresh_advanced, args.refresh_stages, args.refresh_missing,
                not args.preview_release_info, args.listing_only,
            )
        if year < args.end_year:
            time.sleep(YEAR_PAUSE_SECONDS)
    path, count = write_dataset_metadata()
    print(f"Updated {path} ({count} year files)")
