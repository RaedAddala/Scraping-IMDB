# IMDb Movie Data Scraper

Scrape IMDb feature-film data by release year into typed, analysis-ready CSV files: one listing file, one details file, one status file and one merged file per year.

The scraper takes the top-grossing feature films for each year (IMDb search, sorted by US box office), then enriches every title from IMDb's embedded structured page data (no fragile HTML scraping) across four stages: title page, parental guide, full credits and release info.

## Requirements and setup

- Python 3.13+, [uv](https://docs.astral.sh/uv/), Microsoft Edge and a matching `edgedriver.exe` in the project root.

```powershell
uv sync
```

## Usage

```powershell
uv run python .\scrapping.py --start-year 1920 --end-year 2007      # everything, resumable
uv run python .\scrapping.py --start-year 2024 --end-year 2024 --max-movies 100
uv run python .\scrapping.py --start-year 2024 --end-year 2024 --workers 1
```

| Option | Meaning |
|---|---|
| `--max-movies N` | Movies per year (default 1000). |
| `--workers 1\|2` | Independent Edge sessions (default 2). |
| `--refresh-stages title,parental,credits,release` | Re-scrape only those stages, reusing the saved listing. |
| `--refresh-advanced` | Re-scrape every stage. |
| `--refresh-missing` | Re-scrape stages that have no populated field. |
| `--retry-failed` | Retry only titles marked failed in the status file. |
| `--listing-only` | Refresh only the search listing and rebuild the merged file. |
| `--preview-release-info` | Keep only the release/AKA entries embedded in the page (faster). By default every entry is expanded. |

Runs are resumable: finished titles are skipped, failed stages are retried once automatically, and a failed stage never erases values from stages that succeeded. Wait for a running scrape to finish before starting another on the same year.

## Output files

For each year: `Data/<year>/imdb_movies_<year>.csv` (listing), `advanced_movies_details_<year>.csv` (details), `advanced_scrape_status_<year>.csv` (per-title and per-stage state), `merged_movies_data_<year>.csv` (listing + details + derived columns), plus `Logs/<year>/errors.txt`, `results.txt` and `advanced_scrape_attempts_<year>.jsonl`.

## Data conventions

- **Key:** `imdb_id` (`tt0114709`) in every file. The year/listing position is never part of identity.
- **Names:** `snake_case`; amounts are paired with their currency (`budget_amount`, `budget_currency`).
- **Types:** `int`, `float`, `bool` (`True`/`False`), text, and `json` columns holding a JSON array or object. Integers have no `.0`. Missing is an empty cell; an empty list is also an empty cell (the status file says whether the stage succeeded).
- **Read it with pandas:** `pd.read_csv(path, keep_default_na=False, na_values=[""])` and `json.loads` on the json columns, so values such as `none` are never mistaken for missing.
- **Encoding:** UTF-8.

## Column dictionary

**Listing** (`imdb_id`, `search_year`, `listing_rank`, `listing_title`): the discovery order for the searched year.

**Title page**: `title`, `original_title`, `title_type`, `release_year`, `is_adult`, `production_status`, `plot`, `poster_url`, `certificate`, `runtime_seconds`; `release_date` (ISO, may be `YYYY` or `YYYY-MM`), `release_date_precision` (`year`/`month`/`day`) and `release_date_country` (IMDb's displayed release, which is a regional release, not necessarily the first); `imdb_rating`, `imdb_votes`, `metascore`, `top_rated_rank`, `rating_histogram` (votes for 1..10), `user_reviews_count`, `critic_reviews_count`; `budget_*`, `gross_us_canada_*`, `gross_worldwide_*`, `opening_weekend_us_canada_*` (amount + currency, no conversion) and `opening_weekend_end_date`; `award_wins`, `award_nominations` (nominations that did not win; 0 when IMDb lists none), `prestigious_award_name/wins/nominations`; json lists `genres`, `interests` (themes and franchises, never mixed into genres), `keywords` (the first few) with `keywords_total`, `countries_of_origin`, `languages`, `production_companies`, `filming_locations` with `filming_locations_total`, `similar_movie_ids`, `similar_movie_titles`; `similar_movies_status` (`found`/`empty`).

**Parental guide**: `sex_nudity_severity`, `violence_gore_severity`, `profanity_severity`, `alcohol_drugs_smoking_severity`, `frightening_intense_scenes_severity` (`none`/`mild`/`moderate`/`severe`, lowercase) and `certificates_by_country` (json `[{country, rating, notes}]`).

**Credits** (full-credits page): for `directors`, `writers`, `cast`, `producers`, `composers`, `cinematographers`, `editors`, `casting_directors`, `production_designers`, `costume_designers` there is a json list of names and a parallel `<group>_ids` list of IMDb person IDs. Also `cast_characters` (list of role lists parallel to `cast`), `cast_total`, and `credits_incomplete` (groups the page lists only partly).

**Release info**: `release_dates` (json `[{country, date, note}]`), `akas` (json `[{country, title, note}]`, the original-language title has no country), `release_dates_total`, `akas_total`, and `release_info_complete` (`complete`, `preview` or `empty`, checked against the source totals).

**Housekeeping**: `scraped_at` (UTC time of the latest stage run).

**Derived (merged file only)**: `runtime_minutes`, `first_release_date` (earliest full date in `release_dates`), `release_decade`, `release_month` and `release_weekday` (only when the date precision allows), `gross_minus_budget` / `gross_to_budget_ratio` / `gross_comparison_currency` (worldwide gross vs budget, only when both are in the same currency; not profit), `genre_count`, `country_count`, `language_count`, `cast_count` (empty, not 0, when unknown).

## How data quality is protected

- Every stage reads IMDb's structured page data and checks it belongs to the requested title; invalid or partial pages fail the stage instead of saving empties.
- Extractor errors propagate; a failed stage records its error, keeps previous values, and is retried.
- Values are validated (rating 1-10, non-negative votes and amounts, amounts always have a currency).
- Credit groups are matched by IMDb's stable category IDs, so singular/plural naming differences ("Editor"/"Editors") cannot drop data.
- A partial or failed listing never replaces a more complete saved one.

Not collected: the full keyword list (only the first few and the total), departments beyond the main credit groups, and per-country certificate dates.

## Code layout

`scrapping.py` is the entry point; the implementation is under `imdb_scraper/`: `config.py` (typed schemas and credit-group IDs), `browser.py`, `storage.py` (paths, typed CSV read/write, logging), `extractors.py`, `advanced.py` (workers, checkpoints, retries, stage status), `analysis.py` (merge and derived columns), `pipeline.py`, `cli.py`, `parsing.py`.

## Tests

```powershell
uv run python -m unittest discover tests
```

Offline tests only (no browser or network).

## License

See [LICENSE](LICENSE).
