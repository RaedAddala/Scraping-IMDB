"""Kaggle dataset metadata (``Data/dataset-metadata.json``) for the merged CSVs.

The column set and order come from ``config.MERGED_SCHEMA``, the same schema that writes the CSVs, so the
metadata cannot silently diverge from them; ``validate_metadata`` also checks it against the real CSV headers.
The Kaggle type and the description of every column are defined once, here, and reused for every year's file.
"""
import csv
import json
import os
import shutil
from pathlib import Path

from .config import CREDIT_GROUPS, MERGED_SCHEMA, PARENTAL_GUIDE_CATEGORIES, SCRIPT_DIR

KAGGLE_TYPES = {
    "string", "boolean", "numeric", "datetime", "id", "uuid", "latitude", "longitude", "coordinates",
    "country", "province", "postalcode", "address", "email", "url", "integer", "decimal", "city",
}
# Which Kaggle types may describe a column the scraper writes as each internal kind (see config.py).
_ALLOWED_BY_KIND = {
    "str": {"string", "id", "url", "country", "datetime"},
    "json": {"string"},
    "int": {"integer", "numeric"},
    "float": {"decimal", "numeric"},
    "bool": {"boolean"},
}

_MONEY = {  # money field prefix -> what the amount measures (taken from the IMDb box-office / budget entries)
    "budget": "Production budget",
    "gross_us_canada": "Lifetime gross in the US and Canada",
    "gross_worldwide": "Lifetime worldwide gross",
    "opening_weekend_us_canada": "Opening-weekend gross in the US and Canada",
}

_COLUMNS = {  # column -> (Kaggle type, description)
    "imdb_id": ("id", "IMDb title ID (tt followed by digits); the unique key of a row within a year's file."),
    "search_year": ("integer", "Release year of the IMDb search (title_type=feature) that returned this title."),
    "listing_rank": ("integer", "Position of the title in IMDb's search results for that year, which IMDb sorts by US box-office gross (descending). Titles without a recorded gross follow in no meaningful order."),
    "listing_title": ("string", "Title as shown in the search results."),
    "title": ("string", "Title shown on the title page."),
    "original_title": ("string", "Title in its original language."),
    "title_type": ("string", "IMDb title type id, e.g. movie."),
    "release_year": ("integer", "Release year according to the title page; can differ from search_year."),
    "is_adult": ("boolean", "True when IMDb flags the title as adult."),
    "production_status": ("string", "IMDb production stage id, e.g. released."),
    "plot": ("string", "Plot outline from the title page."),
    "poster_url": ("url", "URL of the title's main image on IMDb."),
    "certificate": ("string", "Content certificate IMDb shows on the title page (the page does not state the country; see certificates_by_country for all countries)."),
    "runtime_seconds": ("integer", "Runtime in seconds."),
    "release_date": ("string", "Release date IMDb displays on the title page for release_date_country, in ISO format and possibly partial (YYYY or YYYY-MM). A regional release: it can fall in a different year than release_year."),
    "release_date_precision": ("string", "Precision of release_date: year, month or day."),
    "release_date_country": ("country", "Country the displayed release_date belongs to."),
    "imdb_rating": ("decimal", "IMDb weighted average user rating on a 1-10 scale; empty when the title has no rating."),
    "imdb_votes": ("integer", "Number of user ratings behind imdb_rating (0 when unrated)."),
    "metascore": ("integer", "Metacritic Metascore (0-100) shown by IMDb."),
    "top_rated_rank": ("integer", "Position in IMDb's Top Rated ranking. The site displays only ranks up to 250, the data can hold lower ranks."),
    "rating_histogram": ("string", "JSON array of 10 integers: user votes for ratings 1 to 10, in that order."),
    "user_reviews_count": ("integer", "Number of user reviews."),
    "critic_reviews_count": ("integer", "Number of critic reviews."),
    "opening_weekend_end_date": ("datetime", "End date (ISO, YYYY-MM-DD) of the opening weekend."),
    "award_wins": ("integer", "Total award wins; 0 when IMDb lists none."),
    "award_nominations": ("integer", "Award nominations that did not result in a win (IMDb's 'nominations' count); 0 when none."),
    "prestigious_award_name": ("string", "Name of the award IMDb singles out for the title (e.g. Oscar); empty when it shows none."),
    "prestigious_award_wins": ("integer", "Wins in that award."),
    "prestigious_award_nominations": ("integer", "Nominations in that award."),
    "genres": ("string", "JSON array of IMDb genres."),
    "interests": ("string", "JSON array of IMDb interests: themes, sub-genres and franchises."),
    "keywords": ("string", "JSON array of the first plot keywords shown on the title page (see keywords_total)."),
    "keywords_total": ("integer", "Number of plot keywords IMDb holds for the title."),
    "countries_of_origin": ("string", "JSON array of countries of origin."),
    "languages": ("string", "JSON array of languages listed by IMDb. IMDb's own value 'None' (no spoken language listed, as for many silent films) is kept as is."),
    "production_companies": ("string", "JSON array of production companies listed on the title page."),
    "filming_locations": ("string", "JSON array of the first filming locations shown on the title page (see filming_locations_total)."),
    "filming_locations_total": ("integer", "Number of filming locations IMDb holds for the title."),
    "similar_movie_ids": ("string", "JSON array of IMDb title IDs of the 'More like this' titles as served to an anonymous visitor, in IMDb's order; the recommendations shown in a browser after the page loads can differ."),
    "similar_movie_titles": ("string", "JSON array of titles parallel to similar_movie_ids."),
    "similar_movies_status": ("string", "found, or empty when the title page has no 'More like this' titles."),
    "certificates_by_country": ("string", "JSON array of {country, rating, notes} certificates from the parental guide. IMDb exposes only the first ~50 ratings (see certificates_total)."),
    "certificates_total": ("integer", "Number of countries with a certificate according to IMDb."),
    "cast_characters": ("string", "JSON array parallel to cast: for each person the list of characters played."),
    "cast_total": ("integer", "Number of cast entries on the full-credits page."),
    "credits_incomplete": ("string", "JSON array naming the credit groups whose list on the page is shorter than IMDb's reported total; empty when all are complete."),
    "release_dates": ("string", "JSON array of {country, date, note}: every release date on IMDb's release-info page (date in ISO format, possibly partial)."),
    "release_dates_total": ("integer", "Number of release-date rows IMDb reports."),
    "akas": ("string", "JSON array of {country, title, note}: alternative titles from the release-info page. The original title has country null and note 'original title'."),
    "akas_total": ("integer", "Number of alternative-title rows IMDb reports."),
    "release_info_complete": ("string", "complete when release_dates and akas hold at least the rows IMDb reports, preview when they hold fewer, empty when there are none."),
    "scraped_at": ("datetime", "UTC time (ISO 8601) the title was last scraped."),
    "runtime_minutes": ("decimal", "Derived: runtime_seconds / 60, rounded to 0.1."),
    "first_release_date": ("datetime", "Derived: earliest full date (YYYY-MM-DD) in release_dates; can be a festival or premiere."),
    "release_decade": ("integer", "Derived: decade of release_year, e.g. 1920."),
    "release_month": ("integer", "Derived: month (1-12) of the release within release_year: first_release_date when it falls in that year, else release_date when it does; empty when only a year is known or no date falls in release_year."),
    "release_weekday": ("string", "Derived: English weekday of the same release date; empty unless that date is a full date."),
    "gross_minus_budget": ("integer", "Derived: gross_worldwide_amount minus budget_amount, only when both are in the same currency (no conversion). Not profit."),
    "gross_to_budget_ratio": ("decimal", "Derived: (worldwide gross - budget) / budget under the same condition."),
    "gross_comparison_currency": ("string", "Currency code used for gross_minus_budget and gross_to_budget_ratio."),
    "genre_count": ("integer", "Derived: number of genres; 0 when the scraped title page lists none."),
    "country_count": ("integer", "Derived: number of countries of origin."),
    "language_count": ("integer", "Derived: number of languages, not counting IMDb's 'None' placeholder."),
    "cast_count": ("integer", "Derived: number of people in cast."),
}


def _generated_columns():
    """Columns that follow a pattern share one definition per pattern instead of one copy each."""
    columns = {}
    for prefix, label in _MONEY.items():
        columns[f"{prefix}_amount"] = ("integer", f"{label}, in the currency given in {prefix}_currency; empty when IMDb has no figure.")
        columns[f"{prefix}_currency"] = ("string", f"ISO 4217 code of the currency of {prefix}_amount (e.g. USD; historical codes such as DEM occur).")
    for column, label in PARENTAL_GUIDE_CATEGORIES.items():
        columns[column] = ("string", f"Severity of '{label}' in IMDb's parental guide: none, mild, moderate or severe; empty when the guide has no entry.")
    for group in CREDIT_GROUPS:
        label = group.replace("_", " ")
        columns[group] = ("string", f"JSON array of {label} names from IMDb's full-credits page, in the order listed there.")
        columns[f"{group}_ids"] = ("string", f"JSON array of IMDb person IDs (nm...) parallel to {group}.")
    return columns


COLUMN_METADATA = {**_COLUMNS, **_generated_columns()}


def schema_fields():
    """schema.fields in CSV column order (the order of the schema that writes the CSV)."""
    return [
        {"name": column, "description": COLUMN_METADATA[column][1], "type": COLUMN_METADATA[column][0]}
        for column in MERGED_SCHEMA
    ]


def build_metadata(data_dir=None):
    data_dir = data_dir or SCRIPT_DIR / "Data"
    fields = schema_fields()
    resources = [
        {
            "path": path.relative_to(data_dir).as_posix(),
            "description": (
                f"IMDb feature films released in {path.parent.name}: up to 1,000 titles in IMDb's US box-office order, "
                "one row per title, with ratings, money, awards, credits, release dates and alternative titles. "
                "The first row holds the column names."
            ),
            "schema": {"fields": fields},
        }
        for path in sorted(data_dir.glob("*/merged_movies_data_*.csv"))
    ]
    # Kaggle shows the description as the dataset's "About" page; Data/README.md is the single source of it.
    readme = data_dir / "README.md"
    return {
        "id": "raedaddala/imdb-movies-by-year-1920-2026",
        "title": "IMDb Movies by Year (1920-2026)",
        "subtitle": "Top 1,000 IMDb films per year with ratings, box office, awards and credits",
        "description": readme.read_text(encoding="utf-8") if readme.is_file() else "",
        "licenses": [{"name": "other"}],
        "keywords": ["movies and tv shows", "arts and entertainment"],  # must be existing Kaggle tags; others are dropped
        "resources": resources,
    }


def validate_metadata(metadata, data_dir=None):
    """Raise ValueError listing every way the metadata and the CSV files disagree."""
    data_dir = data_dir or SCRIPT_DIR / "Data"
    problems = []
    if not 6 <= len(metadata.get("title", "")) <= 50:
        problems.append("title must be 6-50 characters (Kaggle limit)")
    if not 20 <= len(metadata.get("subtitle", "")) <= 80:
        problems.append("subtitle must be 20-80 characters (Kaggle limit)")
    if not metadata.get("description", "").strip():
        problems.append("empty description (Data/README.md is missing or empty)")
    documented = set()
    for resource in metadata.get("resources", []):
        path = resource.get("path", "")
        documented.add(path)
        if not resource.get("description", "").strip():
            problems.append(f"{path}: empty resource description")
        csv_path = data_dir / path
        if not csv_path.is_file():
            problems.append(f"{path}: no such dataset file")
            continue
        with csv_path.open(encoding="utf-8", newline="") as handle:
            header = next(csv.reader(handle), [])
        fields = resource.get("schema", {}).get("fields", [])
        names = [field.get("name") for field in fields]
        if names != header:
            missing = [name for name in header if name not in names]
            extra = [name for name in names if name not in header]
            detail = f"missing {missing}, extra {extra}" if missing or extra else "same columns, different order"
            problems.append(f"{path}: schema.fields does not match the CSV header ({detail})")
        for field in fields:
            name, kind = field.get("name"), MERGED_SCHEMA.get(field.get("name"))
            if not str(field.get("description", "")).strip():
                problems.append(f"{path}: field {name} has no description")
            if field.get("type") not in KAGGLE_TYPES:
                problems.append(f"{path}: field {name} has unsupported type {field.get('type')!r}")
            elif kind and field["type"] not in _ALLOWED_BY_KIND[kind]:
                problems.append(f"{path}: field {name} type {field['type']} does not fit the CSV kind {kind}")
    for csv_path in sorted(data_dir.glob("*/merged_movies_data_*.csv")):
        if csv_path.relative_to(data_dir).as_posix() not in documented:
            problems.append(f"{csv_path.relative_to(data_dir).as_posix()}: dataset file is not documented")
    undocumented = [column for column in MERGED_SCHEMA if column not in COLUMN_METADATA]
    unknown = [column for column in COLUMN_METADATA if column not in MERGED_SCHEMA]
    if undocumented:
        problems.append(f"schema columns without metadata: {undocumented}")
    if unknown:
        problems.append(f"metadata for columns not in the schema: {unknown}")
    if problems:
        raise ValueError("dataset-metadata.json is inconsistent:\n  " + "\n  ".join(problems))


def write_dataset_metadata(data_dir=None):
    """Regenerate Data/dataset-metadata.json deterministically and validate it against the CSV files."""
    data_dir = data_dir or SCRIPT_DIR / "Data"
    metadata = build_metadata(data_dir)
    validate_metadata(metadata, data_dir)
    path = data_dir / "dataset-metadata.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path, len(metadata["resources"])


def build_kaggle_folder(out_dir, data_dir=None):
    """Lay the dataset out flat in out_dir for `kaggle datasets create -p out_dir`.

    The Kaggle CLI skips sub-folders by default, and how it unpacks zipped ones is undocumented, so every year's CSV
    goes to the top level (the year is already in the file name) and the metadata paths are rewritten to match.
    CSVs are hard-linked when out_dir is on the same drive, so the folder costs no extra disk space.
    """
    data_dir = Path(data_dir or SCRIPT_DIR / "Data")
    out_dir = Path(out_dir)
    if out_dir.resolve() == data_dir.resolve() or data_dir.resolve() in out_dir.resolve().parents:
        raise ValueError("the Kaggle folder must be outside the data folder")
    metadata = build_metadata(data_dir)
    validate_metadata(metadata, data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("merged_movies_data_*.csv"):
        stale.unlink()
    for resource in metadata["resources"]:
        source = data_dir / resource["path"]
        target = out_dir / source.name
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
        resource["path"] = source.name
    shutil.copy2(data_dir / "README.md", out_dir / "README.md")
    # Kaggle drops column descriptions sent through its API (github.com/Kaggle/kaggle-cli/issues/1207),
    # so they also ship as a plain file.
    with (out_dir / "data_dictionary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["column", "type", "description"])
        writer.writerows([field["name"], field["type"], field["description"]] for field in schema_fields())
    validate_metadata(metadata, out_dir)
    (out_dir / "dataset-metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out_dir, len(metadata["resources"])
