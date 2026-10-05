"""Kaggle dataset metadata (dataset-metadata.json) with a typed, documented schema for the merged CSVs."""
import json

from .config import CREDIT_GROUPS, MERGED_SCHEMA, PARENTAL_GUIDE_CATEGORIES, SCRIPT_DIR

# Frictionless/Kaggle field types. JSON columns are strings holding a JSON array/object.
KAGGLE_TYPES = {"str": "string", "int": "integer", "float": "number", "bool": "boolean", "json": "string"}

_BASE = {
    "imdb_id": "IMDb title ID (primary key within a year file), e.g. tt0114709.",
    "search_year": "Release year used for the IMDb search that found the title.",
    "listing_rank": "Position in IMDb's search results for that year (sorted by US box office, descending).",
    "listing_title": "Title as shown in the search results.",
    "title": "Display title on the title page.",
    "original_title": "Title in the original language.",
    "title_type": "IMDb title type id (movie, tvMovie, video, ...).",
    "release_year": "Year of release according to the title page.",
    "is_adult": "True when IMDb flags the title as adult content.",
    "production_status": "IMDb production stage id (released, ...).",
    "plot": "Plot outline.",
    "poster_url": "URL of the main poster image.",
    "certificate": "Primary content certificate shown on the title page (e.g. PG-13).",
    "runtime_seconds": "Runtime in seconds.",
    "release_date": "Release date IMDb displays (ISO; may be YYYY or YYYY-MM), in release_date_country; a regional release, not necessarily the first.",
    "release_date_precision": "Precision of release_date: year, month or day.",
    "release_date_country": "Country of the displayed release_date.",
    "imdb_rating": "IMDb average user rating, 1-10.",
    "imdb_votes": "Number of IMDb user ratings.",
    "metascore": "Metacritic Metascore, 0-100.",
    "top_rated_rank": "Position in IMDb's Top Rated ranking (the site displays only the top 250, the data can hold lower ranks).",
    "rating_histogram": "JSON array of 10 integers: number of votes for ratings 1 to 10.",
    "user_reviews_count": "Number of user reviews.",
    "critic_reviews_count": "Number of critic reviews.",
    "budget_amount": "Production budget (see budget_currency); empty when unknown.",
    "budget_currency": "ISO currency code of budget_amount.",
    "gross_us_canada_amount": "Gross in the US and Canada.",
    "gross_us_canada_currency": "ISO currency code of gross_us_canada_amount.",
    "gross_worldwide_amount": "Worldwide gross.",
    "gross_worldwide_currency": "ISO currency code of gross_worldwide_amount.",
    "opening_weekend_us_canada_amount": "Opening-weekend gross in the US and Canada.",
    "opening_weekend_us_canada_currency": "ISO currency code of the opening-weekend gross.",
    "opening_weekend_end_date": "End date (ISO) of the opening weekend.",
    "award_wins": "Total award wins (0 when IMDb lists none).",
    "award_nominations": "Award nominations that did not win (0 when IMDb lists none).",
    "prestigious_award_name": "Name of the prestigious award IMDb summarises (e.g. Oscar).",
    "prestigious_award_wins": "Wins in that prestigious award.",
    "prestigious_award_nominations": "Nominations in that prestigious award.",
    "genres": "JSON array of IMDb genres.",
    "interests": "JSON array of IMDb interests (themes, sub-genres, franchises).",
    "keywords": "JSON array of the first plot keywords shown on the title page.",
    "keywords_total": "Total number of plot keywords IMDb has for the title.",
    "countries_of_origin": "JSON array of countries of origin.",
    "languages": "JSON array of spoken languages.",
    "production_companies": "JSON array of production companies.",
    "filming_locations": "JSON array of the first filming locations shown.",
    "filming_locations_total": "Total number of filming locations IMDb has.",
    "similar_movie_ids": "JSON array of IMDb IDs of the 'More like this' titles.",
    "similar_movie_titles": "JSON array of titles parallel to similar_movie_ids.",
    "similar_movies_status": "found or empty (no recommendations on the page).",
    "certificates_by_country": "JSON array of {country, rating, notes} certificates from the parental guide (IMDb lists only the first ~50 ratings; see certificates_total).",
    "certificates_total": "Number of countries with a certificate according to IMDb.",
    "cast_characters": "JSON array parallel to cast: each item is the list of characters the person plays.",
    "cast_total": "Total number of cast members listed on the full-credits page.",
    "credits_incomplete": "JSON array of credit groups the page lists only partly; empty when all are complete.",
    "release_dates": "JSON array of {country, date, note}: every release date IMDb lists.",
    "release_dates_total": "Number of release-date rows IMDb reports.",
    "akas": "JSON array of {country, title, note}: alternative titles; the original title has country null.",
    "akas_total": "Number of alternative-title rows IMDb reports.",
    "release_info_complete": "complete, preview or empty: whether release_dates/akas hold every row IMDb reports.",
    "scraped_at": "UTC time of the latest scrape of this title.",
    "runtime_minutes": "Derived: runtime_seconds / 60.",
    "first_release_date": "Derived: earliest full date in release_dates (ISO).",
    "release_decade": "Derived: decade of release_year.",
    "release_month": "Derived: month (1-12) of release_date; empty when precision is year.",
    "release_weekday": "Derived: weekday of release_date; only when precision is day.",
    "gross_minus_budget": "Derived: worldwide gross minus budget, only when both share a currency. Not profit.",
    "gross_to_budget_ratio": "Derived: (gross - budget) / budget, same condition.",
    "gross_comparison_currency": "Currency used for gross_minus_budget and gross_to_budget_ratio.",
    "genre_count": "Derived: number of genres; empty when none are listed.",
    "country_count": "Derived: number of countries of origin.",
    "language_count": "Derived: number of spoken languages.",
    "cast_count": "Derived: number of people in cast.",
}


def column_description(column):
    if column in _BASE:
        return _BASE[column]
    if column in PARENTAL_GUIDE_CATEGORIES:
        return f"Parental-guide severity for '{PARENTAL_GUIDE_CATEGORIES[column]}': none, mild, moderate or severe."
    for group in CREDIT_GROUPS:
        label = group.replace("_", " ")
        if column == group:
            return f"JSON array of {label} names (full-credits page), in credit order."
        if column == f"{group}_ids":
            return f"JSON array of IMDb person IDs (nm...) parallel to {group}."
    raise KeyError(column)


def schema_fields():
    return [
        {"name": column, "description": column_description(column), "type": KAGGLE_TYPES[kind]}
        for column, kind in MERGED_SCHEMA.items()
    ]


def build_metadata(data_dir=None):
    data_dir = data_dir or SCRIPT_DIR / "Data"
    fields = schema_fields()
    resources = [
        {
            "path": path.relative_to(data_dir).as_posix(),
            "description": f"Top-grossing IMDb feature films released in {path.parent.name}.",
            "schema": {"fields": fields},
        }
        for path in sorted(data_dir.glob("*/merged_movies_data_*.csv"))
    ]
    return {
        "id": "your-kaggle-username/imdb-movies-by-year",
        "title": "IMDb Movies by Year",
        "subtitle": "Top-grossing IMDb feature films per year with ratings, money, awards, credits and release data",
        "description": (
            "One CSV per release year (`<year>/merged_movies_data_<year>.csv`), keyed by `imdb_id`. "
            "Columns are typed (see schema); `json` columns hold JSON arrays/objects. Missing values are empty cells. "
            "Read with `pd.read_csv(path, keep_default_na=False, na_values=[''])` so values such as `none` stay text. "
            "Data comes from IMDb's public pages; check IMDb's terms of use before redistributing."
        ),
        "licenses": [{"name": "other"}],
        "keywords": ["movies", "film", "imdb", "box office", "cinema"],
        "resources": resources,
    }


def write_dataset_metadata(data_dir=None):
    data_dir = data_dir or SCRIPT_DIR / "Data"
    metadata = build_metadata(data_dir)
    path = data_dir / "dataset-metadata.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path, len(metadata["resources"])
