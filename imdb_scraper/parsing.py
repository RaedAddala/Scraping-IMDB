"""Pure helpers shared by the scraper, merge and analysis steps."""
import re

from .config import IMDB_BASE_URL

_TITLE_ID_RE = re.compile(r"\btt\d{7,}\b")
_RANK_PREFIX_RE = re.compile(r"^\s*(\d+)\.\s+")


def title_id(value):
    """IMDb title ID (ttNNNNNNN) found in a URL or bare ID, or None."""
    if value is None:
        return None
    match = _TITLE_ID_RE.search(str(value))
    return match.group(0) if match else None


def title_url(imdb_id):
    return f"{IMDB_BASE_URL}title/{imdb_id}/"


def split_listing_rank(title):
    """'12. Foo' -> (12, 'Foo'); titles without a rank prefix are returned unchanged."""
    if not title:
        return None, title
    match = _RANK_PREFIX_RE.match(title)
    if not match:
        return None, title
    return int(match.group(1)), title[match.end():].strip()
