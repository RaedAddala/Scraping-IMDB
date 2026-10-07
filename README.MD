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
| --- | --- |
| `--max-movies N` | Movies per year (default 1000). |
| `--workers 1-4` | Independent Edge sessions (default 4). |
| `--refresh-stages title,parental,credits,release` | Re-scrape only those stages, reusing the saved listing. |
| `--refresh-advanced` | Re-scrape every stage. |
| `--refresh-missing` | Re-scrape stages that have no populated field. |
| `--retry-failed` | Retry only titles marked failed in the status file. |
| `--listing-only` | Refresh only the search listing and rebuild the merged file. |
| `--write-metadata` | Only rewrite `Data/dataset-metadata.json` (and validate it against the CSVs) and exit. |
| `--fix-quality-issues` | Re-scrape only the titles (and only the stages) the data-quality check flags in the year range. Nothing else is touched. |
| `--rebuild-derived` | Recompute the derived columns of the saved CSVs in the year range, without scraping. Use it after a change to the derived-column logic. |
| `--preview-release-info` | Keep only the first release/AKA rows embedded in the page (saves 2-6 requests per title). By default every row is fetched. |

Runs are resumable: finished titles are skipped, failed stages are retried once automatically, and a failed stage never erases values from stages that succeeded. A per-year lock stops two runs from writing the same year. Ctrl+C saves the titles finished so far. If 25 titles in a row fail (IMDb may be blocking), the year stops early, the remaining titles stay pending and the next run resumes them. If the merged CSV is open in Excel when a save happens, the scraper retries for about 10 seconds and then fails with a clear message, so keep the files closed while it runs.

## Request footprint

A title costs about 7 requests (versus 200+ when pages were loaded like a normal browser visit): one HTML document each for the title, parental-guide and full-credits pages, plus a few paginated GraphQL calls for the remaining release dates and alternative titles, and for the rest of any credit group the page lists only partly (the page shows 10 people, IMDb's data holds all of them). Everything is read from the server-rendered `__NEXT_DATA__` JSON, so page scripts are blocked (and with them the ~70 background GraphQL, anti-bot and analytics calls they would make); images, fonts, styles, media and tracking hosts are blocked too. That is what makes four workers lighter on IMDb than two used to be. IMDb's anti-bot token comes from a script-run page load: the first load of a browser session, or any load that is refused, runs with scripts once to renew it. The paginated queries are verified row for row against the page's own expansion; if IMDb changes them, the scraper falls back to expanding the lists in the page, which works but is slower and heavier.

## Output files

**`Data/`** holds only the dataset: `Data/<year>/merged_movies_data_<year>.csv` (listing + details + derived columns, one row per title) and `Data/dataset-metadata.json` (typed, documented schema for Kaggle, rewritten after every run or with `--write-metadata`). The merged CSV is also the resume checkpoint; no other data files exist.

**`Logs/<year>/`** holds everything about the scraping itself:

| File | Content |
| --- | --- |
| `errors.txt` | One short line per failed attempt (`tt0114709 [initial #1] full_credits: PageContentError: ...`), no stack traces. |
| `results.txt` | A few summary lines per run: listing size, stage timings, sparse fields, a data-quality check, titles scraped/failed. |
| `scrape_status_<year>.csv` | Per-title and per-stage status (`completed`/`failed`/`pending`, attempts, last error). |
| `scrape_attempts_<year>.jsonl` | One compact event per attempt (stages, seconds per stage, error). |

## Data conventions

- **Key:** `imdb_id` (`tt0114709`) in every file. The year/listing position is never part of identity.
- **Names:** `snake_case`; amounts are paired with their currency (`budget_amount`, `budget_currency`).
- **Types:** `int`, `float`, `bool` (`True`/`False`), text, and `json` columns holding a JSON array or object. Integers have no `.0`. Missing is an empty cell; an empty list is also an empty cell (the status file says whether the stage succeeded).
- **Read it with pandas:** `pd.read_csv(path, keep_default_na=False, na_values=[""])` and `json.loads` on the json columns, so values such as `none` are never mistaken for missing.
- **Encoding:** UTF-8.

## Column dictionary

**Listing** (`imdb_id`, `search_year`, `listing_rank`, `listing_title`): the discovery order for the searched year.

**Title page**: `title`, `original_title`, `title_type`, `release_year`, `is_adult`, `production_status`, `plot`, `poster_url`, `certificate`, `runtime_seconds`; `release_date` (ISO, may be `YYYY` or `YYYY-MM`), `release_date_precision` (`year`/`month`/`day`) and `release_date_country` (IMDb's displayed release, which is a regional release, not necessarily the first); `imdb_rating`, `imdb_votes`, `metascore`, `top_rated_rank` (the site shows only ranks up to 250, the data can hold lower ones), `rating_histogram` (votes for 1..10), `user_reviews_count`, `critic_reviews_count`; `budget_*`, `gross_us_canada_*`, `gross_worldwide_*`, `opening_weekend_us_canada_*` (amount + currency, no conversion) and `opening_weekend_end_date`; `award_wins`, `award_nominations` (nominations that did not win; 0 when IMDb lists none), `prestigious_award_name/wins/nominations`; json lists `genres`, `interests` (themes and franchises, never mixed into genres), `keywords` (the first few) with `keywords_total`, `countries_of_origin`, `languages`, `production_companies`, `filming_locations` with `filming_locations_total`, `similar_movie_ids`, `similar_movie_titles`; `similar_movies_status` (`found`/`empty`).

**Parental guide**: `sex_nudity_severity`, `violence_gore_severity`, `profanity_severity`, `alcohol_drugs_smoking_severity`, `frightening_intense_scenes_severity` (`none`/`mild`/`moderate`/`severe`, lowercase) and `certificates_by_country` (json `[{country, rating, notes}]`, IMDb lists only the first ~50 ratings) and `certificates_total` (countries with a certificate).

**Credits** (full-credits page): for `directors`, `writers`, `cast`, `producers`, `composers`, `cinematographers`, `editors`, `casting_directors`, `production_designers`, `costume_designers` there is a json list of names and a parallel `<group>_ids` list of IMDb person IDs. Also `cast_characters` (list of role lists parallel to `cast`), `cast_total`, and `credits_incomplete` (groups the page lists only partly).

**Release info**: `release_dates` (json `[{country, date, note}]`), `akas` (json `[{country, title, note}]`, the original-language title has no country), `release_dates_total`, `akas_total`, and `release_info_complete` (`complete`, `preview` or `empty`, checked against the source totals).

**Housekeeping**: `scraped_at` (UTC time of the latest stage run).

**Derived (merged file only)**: `runtime_minutes`, `first_release_date` (earliest full date in `release_dates`), `release_decade`, `release_month` and `release_weekday` (only when the date precision allows), `gross_minus_budget` / `gross_to_budget_ratio` / `gross_comparison_currency` (worldwide gross vs budget, only when both are in the same currency; not profit), `genre_count`, `country_count`, `language_count`, `cast_count` (empty, not 0, when unknown).

## How data quality is protected

- After every run `results.txt` gets a quality line from `quality.py` (ID formats, rating ranges, money/currency pairs, parallel-list alignment, histogram vs votes, release-info completeness, valid dates, JSON validity). Offending IDs are listed.

- Every stage reads IMDb's structured page data and checks it belongs to the requested title; invalid or partial pages fail the stage instead of saving empties.
- Extractor errors propagate; a failed stage records its error, keeps previous values, and is retried.
- Values are validated (rating 1-10, non-negative votes and amounts, amounts always have a currency).
- Credit groups are matched by IMDb's stable category IDs, so singular/plural naming differences ("Editor"/"Editors") cannot drop data.
- A partial or failed listing never replaces a more complete saved one.

Not collected: the full keyword list (only the first few and the total), departments beyond the main credit groups, and per-country certificate dates.

## Code layout

`scrapping.py` is the entry point; the implementation is under `imdb_scraper/`: `config.py` (typed schemas and credit-group IDs), `metadata.py` (Kaggle schema and column descriptions), `browser.py`, `storage.py` (paths, typed CSV read/write, logging), `extractors.py`, `advanced.py` (workers, checkpoints, retries, stage status), `analysis.py` (merge and derived columns), `pipeline.py`, `cli.py`, `parsing.py`.

## Publishing to Kaggle

Kaggle imports this repository from GitHub, so `Data/dataset-metadata.json` is generated and committed together with the CSVs; no Kaggle CLI or API is used. The CSV files are plain CSVs (header row, no comments). The metadata follows Kaggle's resource format (`resources[].path`, `description`, `schema.fields[].name/description/type`) with fields in exactly the CSV column order. The column list comes from the schema that writes the CSVs, the types and descriptions are defined once in `imdb_scraper/metadata.py` and reused for every year's file, and `--write-metadata` (also run after every scrape) validates it against the real CSV headers: same columns in the same order, non-empty descriptions, supported types, and every file documented.

1. Run the scraper, then `uv run python .\scrapping.py --write-metadata` (also done automatically after every run).
2. The metadata `id` is `raedaddala/imdb-movies-from-1960-to-2023` (the Kaggle dataset this repository feeds). Review title, description and license (IMDb's terms of use apply to the data).
3. `kaggle datasets create -p Data` (or `version` for updates). The metadata carries the type of every column; `json` columns are strings holding JSON.

Load a year with the right dtypes:

```python
import json, pandas as pd
df = pd.read_csv("1995/merged_movies_data_1995.csv", keep_default_na=False, na_values=[""],
                 dtype={"imdb_id": "string"}).convert_dtypes()
df["genres"] = df["genres"].map(lambda v: json.loads(v) if isinstance(v, str) else [])
```

`imdb_id` is unique within a year file; a title can in rare cases appear in two neighbouring years.

Good to know when analysing: each file holds up to 1,000 titles in IMDb's US box-office order, and titles without a recorded gross follow in no meaningful order, so early years contain many obscure titles with few fields (in 1920-1925 about two thirds have no rating). IMDb lists the language "None" for many silent films; it is kept as IMDb gives it and is not counted in `language_count`.

## Tests

```powershell
uv run python -m unittest discover tests
```

Offline tests only (no browser or network).

`tests/live_verify_columns.py` re-checks every column of a merged CSV against what IMDb's rendered pages show (DOM, JSON-LD, format and cross-column rules) and prints PASS/FAIL per column. It opens Edge and needs network access.

## License

See [LICENSE](LICENSE).
