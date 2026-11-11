# IMDb Movies by Year (1920-2026)

**107,000 feature films** from IMDb: the top 1,000 per release year from 1920 to 2026, ranked by US box office. Each film has ratings, money figures, awards, parental-guide severities, full credits with person IDs, release dates and alternative titles. That makes **98 typed columns** per film.

## Files

```text
README.md                     this file
data_dictionary.csv           type and description of every column
merged_movies_data_1920.csv   one file per release year
merged_movies_data_1921.csv
...
merged_movies_data_2026.csv   107 files in all
```

The files sit side by side here. In the [GitHub repository](https://github.com/RaedAddala/Scraping-IMDB) each one is in its year folder (`Data/1920/merged_movies_data_1920.csv`).

- Every CSV has the **same 98 columns in the same order**, so you can concatenate them directly.
- Each file has **1,000 rows**, one per film, keyed by `imdb_id` (`tt0114709`). Files range from about 2 to 10 MB, 642 MB in total.
- Files are UTF-8, with a header row and comma separators. Fields that contain commas or newlines are quoted.
- Rows follow IMDb's search order for that year: US box-office gross, highest first. Films with no recorded gross come after the grossing ones, in no meaningful order.

## Columns

`data_dictionary.csv` gives the type and full description of every column, one row per column, in file order. By group:

| Group | Columns |
| --- | --- |
| **Listing** | `imdb_id`, `search_year`, `listing_rank`, `listing_title` |
| **Title** | `title`, `original_title`, `title_type`, `release_year`, `is_adult`, `production_status`, `plot`, `poster_url`, `certificate`, `runtime_seconds`, `release_date`, `release_date_precision` (`year`/`month`/`day`), `release_date_country` |
| **Ratings & reviews** | `imdb_rating` (1-10), `imdb_votes`, `metascore` (0-100), `top_rated_rank`, `rating_histogram` (votes for 1..10), `user_reviews_count`, `critic_reviews_count` |
| **Money** | Amount/currency pairs for `budget_*`, `gross_us_canada_*`, `gross_worldwide_*` and `opening_weekend_us_canada_*`, plus `opening_weekend_end_date`. Amounts are in their original currency and are not converted. |
| **Awards** | `award_wins`, `award_nominations` (nominations that did not win), `prestigious_award_name` / `_wins` / `_nominations` (for example Oscar) |
| **Tags & places** | `genres`, `interests` (themes, sub-genres, franchises), `keywords` + `keywords_total`, `countries_of_origin`, `languages`, `production_companies`, `filming_locations` + `filming_locations_total` |
| **Similar titles** | `similar_movie_ids`, `similar_movie_titles`, `similar_movies_status` |
| **Parental guide** | `sex_nudity_severity`, `violence_gore_severity`, `profanity_severity`, `alcohol_drugs_smoking_severity`, `frightening_intense_scenes_severity` (`none`/`mild`/`moderate`/`severe`), `certificates_by_country` (`[{country, rating, notes}]`), `certificates_total` |
| **Credits** | Names plus a parallel `<group>_ids` list of IMDb person IDs (`nm...`) for `directors`, `writers`, `cast`, `producers`, `composers`, `cinematographers`, `editors`, `casting_directors`, `production_designers` and `costume_designers`. Also `cast_characters` (parallel to `cast`), `cast_total` and `credits_incomplete`. |
| **Release info** | `release_dates` (`[{country, date, note}]`), `release_dates_total`, `akas` (`[{country, title, note}]`), `akas_total`, `release_info_complete` (`complete`/`preview`/`empty`) |
| **Derived** | `runtime_minutes`, `first_release_date`, `release_decade`, `release_month`, `release_weekday`, `gross_minus_budget` and `gross_to_budget_ratio` (worldwide gross vs budget, only when both use the same currency; this is not profit), `gross_comparison_currency`, `genre_count`, `country_count`, `language_count`, `cast_count` |
| **Housekeeping** | `scraped_at` (UTC time of the latest scrape) |

**Value conventions:**

- **List columns hold JSON.** Genres, credits, keywords, release dates, akas and the other list or record columns are JSON arrays or objects stored as text. Parse them with `json.loads`.
- **Missing values are empty cells.** An empty list is also an empty cell. Integers have no `.0`, and booleans are `True`/`False`.
- **Dates are ISO and can be partial.** `release_date` can be `YYYY` or `YYYY-MM`; see `release_date_precision`.

## Loading

```python
import glob, json, pandas as pd

files = sorted(glob.glob("/kaggle/input/**/merged_movies_data_*.csv", recursive=True))
df = pd.concat(
    (pd.read_csv(f, keep_default_na=False, na_values=[""], low_memory=False) for f in files),
    ignore_index=True,
)
df["genres"] = df["genres"].map(lambda v: json.loads(v) if isinstance(v, str) else [])
```

Use `keep_default_na=False, na_values=[""]`. Without it, pandas would turn real values such as the severity `none` into NaN.

## Coverage

How complete the data is depends mostly on the era:

| Decade | 1920s | 1930s | 1940s | 1950s | 1960s | 1970s | 1980s | 1990s | 2000s | 2010s | 2020s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Has `imdb_rating` | 39% | 81% | 84% | 91% | 96% | 98% | 98% | 99% | 100% | 100% | 98% |
| Has worldwide gross | 1% | 1% | 2% | 4% | 5% | 7% | 21% | 31% | 71% | 82% | 65% |

Across the whole dataset, 99% of films have directors, 99% have cast, 90% have a plot and 96% have release dates. Budget is known for 19%, Metascore for 17% and parental-guide severities for 35%.

## Caveats

- **Early years are mostly obscure titles.** Few early films have a recorded gross, so most of the 1,000 rows for those years are films that do not have one.
- **2026 is a partial year.** The data was scraped between 2026-10-06 and 2026-11-11, so 2026 grosses and ratings were still changing.
- **One film appears in two year files.** `imdb_id` is unique within each year; `tt0061876` is in both 1967 and 1987. Deduplicate on `imdb_id` if you combine the years.
- **Years can differ between columns.** `search_year` is the year the film was found under. `release_year` comes from the title page. `release_date` is a regional release that IMDb displays, not necessarily the first; use `first_release_date` for the earliest.
- **Some lists are capped.** `keywords`, `filming_locations` and `certificates_by_country` hold only the first entries; their `_total` columns give the full counts.
- **The language "None" is IMDb's own value.** It marks many silent films and is kept as is, but it is not counted in `language_count`.

## Source & license

The data was collected from IMDb's public title, parental-guide, full-credits and release-info pages with the open-source scraper at <https://github.com/RaedAddala/Scraping-IMDB>. IMDb's [conditions of use](https://www.imdb.com/conditions) apply to the data. Use it for research and non-commercial analysis, and credit IMDb as the source.
