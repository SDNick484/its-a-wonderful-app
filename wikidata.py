"""The Wikidata client (netflix-title design §3): the Netflix title id of a movie or TV special, looked up by its TMDB
id, over urllib. Route-free: a failure raises WikidataError and the caller decides what it costs (titles.py logs it).
Only the TMDB id leaves the house. No Flask object here (see CLAUDE.md)."""
import json, re, urllib.error, urllib.parse, urllib.request

from settings import UA

SPARQL_URL = "https://query.wikidata.org/sparql"
TIMEOUT = 10
MAX_BYTES = 1024 * 1024
TMDB_PROPERTY = {"movie": "P4947", "tv": "P4983"}     # Wikidata's "TMDB movie ID" and "TMDB TV series ID"
NETFLIX_PROPERTY = "P1874"                              # "Netflix ID"
TITLE_ID = re.compile(r"[0-9]{1,12}")


class WikidataError(Exception):
    """Wikidata could not answer, or answered something we can't read. `message` is for the log."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def netflix_id(tmdb_id, tmdb_type="movie"):
    """The first Netflix title id Wikidata holds for the TMDB id, or None when it holds none. A value that is not 1 to
    12 digits is skipped (the next one is tried). WikidataError for a failed request, a non-200 answer, or a body
    that is not Wikidata's result JSON; one GET, no retries."""
    if tmdb_type not in TMDB_PROPERTY:
        raise ValueError(f"tmdb_type must be one of {tuple(TMDB_PROPERTY)}")
    query = f'SELECT ?netflix WHERE {{ ?item wdt:{TMDB_PROPERTY[tmdb_type]} "{int(tmdb_id)}" ; wdt:{NETFLIX_PROPERTY} ?netflix . }}'
    url = f"{SPARQL_URL}?" + urllib.parse.urlencode({"format": "json", "query": query})
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            status = getattr(r, "status", 200)
            if status != 200:
                raise WikidataError(f"Wikidata answered HTTP {status}.")
            data = json.loads(r.read(MAX_BYTES))
    except WikidataError:
        raise
    except urllib.error.HTTPError as e:
        raise WikidataError(f"Wikidata had a problem (HTTP {e.code}).") from None
    except Exception:  # noqa: BLE001 — down, slow, refused, cut off, not JSON: all the same to the caller
        raise WikidataError("Wikidata didn't answer.") from None
    results = data.get("results") if isinstance(data, dict) else None
    bindings = results.get("bindings") if isinstance(results, dict) else None
    if not isinstance(bindings, list):
        raise WikidataError("Wikidata sent something we couldn't read.")
    for b in bindings:
        cell = b.get("netflix") if isinstance(b, dict) else None
        value = cell.get("value") if isinstance(cell, dict) else None
        if isinstance(value, str) and TITLE_ID.fullmatch(value):
            return value
    return None

