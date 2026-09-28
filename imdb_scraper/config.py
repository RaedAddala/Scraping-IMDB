from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent.parent
IMDB_BASE_URL = "https://www.imdb.com/"
BASIC_COLUMNS = [
    "Title", "Year", "Duration", "MPA", "Rating", "Votes", "meta_score",
    "description", "Movie Link",
]
ADVANCED_COLUMNS = [
    "link", "scrape_version", "writers", "directors", "stars", "characters", "budget",
    "opening_weekend_Gross", "grossWorldWWide", "gross_US_Canada",
    "release_date", "countries_origin", "filming_locations",
    "production_company", "awards_content", "awards_wins_nominations_total",
    "critic_reviews_count", "user_reviews_count", "genres", "Languages",
    "similar_movies", "similar_movies_links", "json_ld_rating",
    "json_ld_vote_count", "json_ld_content_rating", "json_ld_keywords",
    "json_ld_poster_url", "json_ld_directors", "json_ld_writers",
    "json_ld_actors", "json_ld_runtime_minutes", "sex_nudity_severity",
    "violence_gore_severity", "profanity_severity",
    "alcohol_drugs_smoking_severity", "frightening_intense_scenes_severity",
    "producers", "composer", "cinematographer", "editor", "casting_director",
    "production_designer", "costume_designer", "release_dates_by_country",
    "aka_titles",
]
STATUS_COLUMNS = [
    "link", "title", "status", "attempt_count", "last_error",
    "last_attempted_at", "completed_at", "scrape_version",
]
SCRAPE_VERSION = 2
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
    "*.woff*", "*.woff2*", "*.ttf*", "*.otf*", "*.mp4*", "*.webm*",
]

PARENTAL_GUIDE_CATEGORIES = {
    "sex_nudity_severity": "Sex & Nudity",
    "violence_gore_severity": "Violence & Gore",
    "profanity_severity": "Profanity",
    "alcohol_drugs_smoking_severity": "Alcohol, Drugs & Smoking",
    "frightening_intense_scenes_severity": "Frightening & Intense Scenes",
}
FULL_CREDITS_DEPARTMENTS = {
    "producers": "Producers",
    "composer": "Composer",
    "cinematographer": "Cinematographer",
    "editor": "Editor",
    "casting_director": "Casting Director",
    "production_designer": "Production Designer",
    "costume_designer": "Costume Designer",
}
ADVANCED_STAGES = ("title_page", "parental_guide", "full_credits", "release_info")
STAGE_FIELDS = {
    "title_page": [
        column for column in ADVANCED_COLUMNS
        if column not in {
            "link", "scrape_version", *PARENTAL_GUIDE_CATEGORIES,
            *FULL_CREDITS_DEPARTMENTS, "release_dates_by_country", "aka_titles",
        }
    ],
    "parental_guide": list(PARENTAL_GUIDE_CATEGORIES),
    "full_credits": list(FULL_CREDITS_DEPARTMENTS),
    "release_info": ["release_dates_by_country", "aka_titles"],
}
