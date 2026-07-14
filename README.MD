# IMDb Movie Data Scraper

Scrape IMDb feature-film data by release year, save basic and detailed CSV files, and merge them into one analysis-ready dataset per year.

The scraper focuses on top-grossing feature films for each selected year. It collects listing data, enriches each movie with detailed metadata, and stores the results in a consistent `Data/<year>` and `Logs/<year>` structure.

## Dataset

Historical outputs and related notebooks are available on Kaggle:

- [IMDb movies from 1960 to 2023](https://www.kaggle.com/datasets/raedaddala/imdb-movies-from-1960-to-2023)
- [Top 500-600 movies of each year from 1960 to 2024](https://www.kaggle.com/datasets/raedaddala/top-500-600-movies-of-each-year-from-1960-to-2024)

Local dataset notebooks, when present, can be used for extraction guidance, cleaning, and normalization:

- `Dataset/guide-to-extracting-data-from-this-dataset.ipynb`
- `Dataset/cleaning-and-normalizing-data.ipynb`
- `Dataset/cleaned_data_from_1920_to_2025.csv`

## Features

- Collects feature films by release year, sorted by US box office gross on IMDb.
- Loads up to 600 movies per year by default, with a configurable limit.
- Extracts basic listing fields such as title, year, duration, MPA rating, IMDb rating, votes, Metascore, description, and IMDb link.
- Extracts detailed fields such as writers, directors, stars, budget, opening weekend gross, worldwide gross, US/Canada gross, release date, countries of origin, filming locations, production companies, awards, genres, and languages.
- Creates separate basic, advanced, and merged CSV files for every processed year.
- Writes per-year logs for errors and processing results.

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- Microsoft Edge
- `edgedriver.exe` in the project root
- Stable internet connection

The Edge driver version should match your installed Microsoft Edge version.

## Setup

Install dependencies with uv:

```powershell
uv sync
```

This installs the dependencies declared in `pyproject.toml`, including Selenium, BeautifulSoup, pandas, and lxml.

## Usage

Run the scraper for the default range, 2024 through 2025:

```powershell
uv run python .\scrapping.py
```

Run it for a specific year range:

```powershell
uv run python .\scrapping.py --start-year 1920 --end-year 1920
```

Limit how many movies are loaded per year:

```powershell
uv run python .\scrapping.py --start-year 2024 --end-year 2025 --max-movies 100
```

The default movie limit is 600 per year.

## Outputs

For each processed year, the scraper creates:

- `Data/<year>/imdb_movies_<year>.csv`
- `Data/<year>/advanced_movies_details_<year>.csv`
- `Data/<year>/merged_movies_data_<year>.csv`
- `Logs/<year>/errors.txt`
- `Logs/<year>/results.txt`

## CSV Structure

### `imdb_movies_<year>.csv`

Basic listing data:

```text
Title, Year, Duration, MPA, Rating, Votes, meta_score, description, Movie Link
```

Field notes:

- `Title`: Movie title.
- `Year`: Release year shown in the IMDb listing.
- `Duration`: Runtime.
- `MPA`: Motion Picture Association rating, when available.
- `Rating`: IMDb user rating.
- `Votes`: Number of IMDb user votes.
- `meta_score`: Metascore, when available.
- `description`: Short movie synopsis.
- `Movie Link`: IMDb movie URL.

### `advanced_movies_details_<year>.csv`

Detailed movie metadata:

```text
link, writers, directors, stars, budget, opening_weekend_Gross, grossWorldWWide, gross_US_Canada, release_date, countries_origin, filming_locations, production_company, awards_content, genres, Languages
```

Field notes:

- `link`: IMDb movie URL.
- `writers`: Listed writers.
- `directors`: Listed directors.
- `stars`: Main cast members.
- `budget`: Production budget, when available.
- `opening_weekend_Gross`: Opening weekend revenue.
- `grossWorldWWide`: Worldwide box office revenue.
- `gross_US_Canada`: US and Canada box office revenue.
- `release_date`: Listed release date.
- `countries_origin`: Countries of origin.
- `filming_locations`: Listed filming locations.
- `production_company`: Production companies.
- `awards_content`: Awards summary or detailed awards text.
- `genres`: Movie genres.
- `Languages`: Listed languages.

### `merged_movies_data_<year>.csv`

Combined dataset produced by joining the basic and advanced files on the IMDb movie link.

```text
Title, Year, Duration, MPA, Rating, Votes, meta_score, description, Movie Link, writers, directors, stars, budget, opening_weekend_Gross, grossWorldWWide, gross_US_Canada, release_date, countries_origin, filming_locations, production_company, awards_content, genres, Languages
```

## Logging

Each year gets its own log directory:

- `Logs/<year>/errors.txt`: extraction and merge errors.
- `Logs/<year>/results.txt`: progress, row counts, timing, and completion details.

## Applications

The generated data can be used for:

- Movie-industry trend analysis over time.
- Box office, ratings, or awards modeling.
- Recommendation-system experiments.
- Data cleaning, normalization, and visualization notebooks.

## Troubleshooting

### WebDriver Errors

- Make sure `edgedriver.exe` is in the project root.
- Make sure the Edge WebDriver version matches your installed Microsoft Edge version.
- If you use another browser, update `create_edge_driver()` in `scrapping.py`.

### Empty or Incomplete Data

IMDb page markup changes over time. If fields suddenly become empty, inspect the current IMDb HTML and update the Selenium or BeautifulSoup selectors in `scrapping.py`.

Some older movies may not have complete financial, awards, language, or filming-location data.

### Rate Limiting or Slow Runs

- Reduce `--max-movies` while testing.
- Process smaller year ranges.
- Increase waits between years or requests if IMDb starts blocking or failing loads.

## Contributing

Contributions are welcome. Useful improvements include selector updates, better retry handling, browser configuration options, tests, data cleaning notebooks, and performance improvements.

Suggested workflow:

```powershell
git checkout -b feature-name
git commit -m "Add feature"
```

Then open a pull request with a clear description of the change.

## License

This project is licensed under the MIT License. See `LICENSE` for details.
