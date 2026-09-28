import argparse
import time

from .config import ADVANCED_WORKERS, YEAR_PAUSE_SECONDS
from .pipeline import process_year, retry_failed_year


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
    parser.add_argument("--workers", type=int, choices=(1, 2), default=ADVANCED_WORKERS, help="Number of independent Edge workers for advanced extraction.")
    parser.add_argument("--complete-release-info", action="store_true", help="Expand and collect every release-date and AKA entry (slower).")
    refresh_group = parser.add_mutually_exclusive_group()
    refresh_group.add_argument("--refresh-advanced", action="store_true", help="Re-scrape every advanced stage even for completed links.")
    refresh_group.add_argument("--refresh-missing", action="store_true", help="Re-scrape only stages with no populated fields.")
    refresh_group.add_argument("--refresh-stages", type=_parse_refresh_stages, help="Comma-separated stages to refresh: title, parental, credits, release.")
    parser.add_argument("--retry-failed", action="store_true", help="Retry only links marked failed in the advanced scrape status file.")
    args = parser.parse_args()
    if args.retry_failed and (args.refresh_advanced or args.refresh_missing or args.refresh_stages):
        parser.error("--retry-failed cannot be combined with an advanced refresh option")
    for year in range(args.start_year, args.end_year + 1):
        action = "Retrying failed links" if args.retry_failed else "Processing year"
        print(f"\n{'=' * 50}\n{action} {year}\n{'=' * 50}")
        if args.retry_failed:
            retry_failed_year(year, args.workers, args.complete_release_info)
        else:
            process_year(
                year, args.max_movies, args.workers,
                args.refresh_advanced, args.refresh_stages, args.refresh_missing,
                args.complete_release_info,
            )
        if year < args.end_year:
            time.sleep(YEAR_PAUSE_SECONDS)
