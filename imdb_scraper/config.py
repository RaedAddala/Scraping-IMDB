from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent.parent
IMDB_BASE_URL = "https://www.imdb.com/"

# --- Output schema -----------------------------------------------------------------------------
# Every column has an explicit type. "json" columns hold JSON text (lists/objects); "int"/"float"
# columns are numeric; "bool" columns are True/False; everything else is text. Missing is an empty cell.
BASIC_SCHEMA = {
    "imdb_id": "str",
    "search_year": "int",
    "listing_rank": "int",
    "listing_title": "str",
}

TITLE_SCHEMA = {
    "title": "str", "original_title": "str", "title_type": "str", "release_year": "int",
    "is_adult": "bool", "production_status": "str", "plot": "str", "poster_url": "str",
    "certificate": "str", "runtime_seconds": "int",
    "release_date": "str", "release_date_precision": "str", "release_date_country": "str",
    "imdb_rating": "float", "imdb_votes": "int", "metascore": "int", "top_rated_rank": "int",
    "rating_histogram": "json", "user_reviews_count": "int", "critic_reviews_count": "int",
    "budget_amount": "int", "budget_currency": "str",
    "gross_us_canada_amount": "int", "gross_us_canada_currency": "str",
    "gross_worldwide_amount": "int", "gross_worldwide_currency": "str",
    "opening_weekend_us_canada_amount": "int", "opening_weekend_us_canada_currency": "str",
    "opening_weekend_end_date": "str",
    "award_wins": "int", "award_nominations": "int",
    "prestigious_award_name": "str", "prestigious_award_wins": "int", "prestigious_award_nominations": "int",
    "genres": "json", "interests": "json", "keywords": "json", "keywords_total": "int",
    "countries_of_origin": "json", "languages": "json", "production_companies": "json",
    "filming_locations": "json", "filming_locations_total": "int",
    "similar_movie_ids": "json", "similar_movie_titles": "json", "similar_movies_status": "str",
}

PARENTAL_GUIDE_CATEGORIES = {
    "sex_nudity_severity": "Sex & Nudity",
    "violence_gore_severity": "Violence & Gore",
    "profanity_severity": "Profanity",
    "alcohol_drugs_smoking_severity": "Alcohol, Drugs & Smoking",
    "frightening_intense_scenes_severity": "Frightening & Intense Scenes",
}
PARENTAL_SCHEMA = {**{key: "str" for key in PARENTAL_GUIDE_CATEGORIES}, "certificates_by_country": "json"}

# Credit groups on the full-credits page. IMDb names the same category in the singular or the plural
# depending on the title ("Editor"/"Editors"), so groups are matched by their stable category id first.
CREDIT_GROUPS = {
    "directors": {"id": "ace5cb4c-8708-4238-9542-04641e7c8171", "names": ("director", "directors")},
    "writers": {"id": "c84ecaff-add5-4f2e-81db-102a41881fe3", "names": ("writer", "writers")},
    "cast": {"id": "7caf7d16-5db9-4f4f-8864-d4c6e711c686", "names": ("cast",)},
    "producers": {"id": "0af123ce-1605-4a51-93cf-7ad477b11832", "names": ("producer", "producers")},
    "composers": {"id": "00f5faa0-5f76-4eb5-87a1-ec8d484d1779", "names": ("composer", "composers")},
    "cinematographers": {"id": "e2bf7217-c947-461b-aa58-47e27da1c78e", "names": ("cinematographer", "cinematographers")},
    "editors": {"id": "63b1f9c6-9d3b-4be6-88fc-6321c9fa5ae2", "names": ("editor", "editors")},
    "casting_directors": {"id": "67b6990c-f7de-4882-916b-dad87ec4406a", "names": ("casting", "casting director", "casting directors")},
    "production_designers": {"id": "ce558628-5755-438c-92d7-757518864a00", "names": ("production designer", "production designers")},
    "costume_designers": {"id": "a2d21716-45de-40e2-9f7d-9de01fc34a71", "names": ("costume designer", "costume designers")},
}
CREDITS_SCHEMA = {}
for _group in CREDIT_GROUPS:
    CREDITS_SCHEMA[_group] = "json"
    CREDITS_SCHEMA[f"{_group}_ids"] = "json"
CREDITS_SCHEMA["cast_characters"] = "json"
CREDITS_SCHEMA["cast_total"] = "int"
CREDITS_SCHEMA["credits_incomplete"] = "json"

RELEASE_SCHEMA = {
    "release_dates": "json", "release_dates_total": "int",
    "akas": "json", "akas_total": "int", "release_info_complete": "str",
}

STAGE_SCHEMAS = {
    "title_page": TITLE_SCHEMA,
    "parental_guide": PARENTAL_SCHEMA,
    "full_credits": CREDITS_SCHEMA,
    "release_info": RELEASE_SCHEMA,
}
ADVANCED_STAGES = tuple(STAGE_SCHEMAS)
STAGE_FIELDS = {stage: list(schema) for stage, schema in STAGE_SCHEMAS.items()}

ADVANCED_SCHEMA = {"imdb_id": "str"}
for _schema in STAGE_SCHEMAS.values():
    ADVANCED_SCHEMA.update(_schema)
ADVANCED_SCHEMA["scraped_at"] = "str"
BASIC_COLUMNS = list(BASIC_SCHEMA)
ADVANCED_COLUMNS = list(ADVANCED_SCHEMA)

STATUS_SCHEMA = {
    "imdb_id": "str", "title": "str", "status": "str", "attempt_count": "int", "last_error": "str",
    "last_attempted_at": "str", "completed_at": "str", "stage_status": "json",
}
STATUS_COLUMNS = list(STATUS_SCHEMA)

DERIVED_SCHEMA = {
    "runtime_minutes": "float", "first_release_date": "str", "release_decade": "int", "release_month": "int", "release_weekday": "str",
    "gross_minus_budget": "int", "gross_to_budget_ratio": "float", "gross_comparison_currency": "str",
    "genre_count": "int", "country_count": "int", "language_count": "int", "cast_count": "int",
}
MERGED_SCHEMA = {**BASIC_SCHEMA, **{k: v for k, v in ADVANCED_SCHEMA.items() if k != "imdb_id"}, **DERIVED_SCHEMA}

PAGE_LOAD_TIMEOUT_SECONDS = 12
SCRIPT_TIMEOUT_SECONDS = 5
REQUIRED_CONTENT_TIMEOUT_SECONDS = 3
LOAD_MORE_BUTTON_TIMEOUT_SECONDS = 6
LOAD_MORE_RESULT_TIMEOUT_SECONDS = 10
LOAD_MORE_RETRY_PAUSE_SECONDS = 1.0
YEAR_PAUSE_SECONDS = 2.0
ADVANCED_WORKERS = 2
CHECKPOINT_INTERVAL = 50
WORKER_RESULT_TIMEOUT_SECONDS = 90
NETWORK_ERROR_THRESHOLD = 3
NETWORK_BACKOFF_SECONDS = 10
BLOCKED_RESOURCE_URLS = [
    "*.jpg*", "*.jpeg*", "*.png*", "*.webp*", "*.gif*", "*.avif*",
    "*.svg*", "*.ico*", "*.bmp*",
    "*.woff*", "*.woff2*", "*.ttf*", "*.otf*", "*.eot*",
    "*.css*",
    "*.mp4*", "*.webm*", "*.mov*", "*.avi*", "*.m3u8*", "*.ts*",
    "*.mp3*", "*.m4a*", "*.wav*", "*.ogg*",
    "*doubleclick.net/*", "*googletagmanager.com/*",
    "*google-analytics.com/*", "*amazon-adsystem.com/*",
    "*scorecardresearch.com/*",
    "*m.media-amazon.com/images/*",
]
