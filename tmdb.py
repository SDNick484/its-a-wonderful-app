"""The TMDB client (spec §7.1): search, and details for one movie or TV special, over urllib. Route-free: a failure
raises TmdbError and app.py turns it into a JSON error. No Flask object here (see CLAUDE.md)."""
import json, urllib.error, urllib.parse, urllib.request

from common import clean
from settings import TMDB_API, TMDB_READ_TOKEN, UA

TIMEOUT = 8
MAX_CAST = 8
ANIMATION_GENRE = 16
TYPES = ("movie", "tv")


class TmdbError(Exception):
    """TMDB could not answer. `reason` is machine-readable, `message` is for a person, `status` is the HTTP status
    our own route answers with."""
    STATUS = {"not_configured": 503, "not_found": 404, "rate_limited": 503, "unavailable": 502}

    def __init__(self, reason, message):
        super().__init__(message)
        self.reason, self.message, self.status = reason, message, self.STATUS[reason]


def _get(path, **params):
    """One TMDB v3 GET with the read token. No retries: someone is waiting, so a failure is shown straight away."""
    if not TMDB_READ_TOKEN:
        raise TmdbError("not_configured", "TMDB is not set up yet: add TMDB_READ_TOKEN to /etc/conf.d/wonderful.")
    url = f"{TMDB_API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json",
                                               "Authorization": f"Bearer {TMDB_READ_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read(2 * 1024 * 1024))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise TmdbError("not_found", "TMDB has no such title.") from None
        if e.code == 401:
            raise TmdbError("unavailable", "TMDB refused our token (HTTP 401). Check TMDB_READ_TOKEN.") from None
        if e.code == 429:
            wait = clean(e.headers.get("Retry-After")) if e.headers else None
            msg = "TMDB is busy. Try again in a minute."
            raise TmdbError("rate_limited", msg + (f" (TMDB asked us to wait {wait} s.)" if wait else "")) from None
        raise TmdbError("unavailable", f"TMDB had a problem (HTTP {e.code}). Try again later.") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise TmdbError("unavailable", "TMDB didn't answer. Try again later.") from None
    if not isinstance(data, dict):
        raise TmdbError("unavailable", "TMDB sent something we couldn't read. Try again later.")
    return data


def _year(date):
    """'2003-11-07' -> 2003; '', None or junk -> None."""
    date = clean(date)
    try:
        return int(date[:4]) if date else None
    except ValueError:
        return None


def search(q):
    """Up to 20 movies and TV titles matching `q`, best first: [{tmdb_id, tmdb_type, title, year, poster_path}].
    People in TMDB's multi-search are dropped. An empty list means TMDB has nothing by that name."""
    q = clean(q)
    if not q:
        return []
    data = _get("/search/multi", query=q, include_adult="false", language="en-US", page=1)
    out = []
    for r in (data.get("results") or []):
        if not isinstance(r, dict) or r.get("media_type") not in TYPES or not isinstance(r.get("id"), int):
            continue
        movie = r["media_type"] == "movie"
        title = clean(r.get("title") if movie else r.get("name")) or clean(r.get("original_title") or r.get("original_name"))
        if not title:
            continue
        out.append({"tmdb_id": r["id"], "tmdb_type": r["media_type"], "title": title,
                    "year": _year(r.get("release_date") if movie else r.get("first_air_date")),
                    "poster_path": clean(r.get("poster_path"))})
    return out[:20]


def us_certification(d, tmdb_type="movie"):
    """The US certification: the first non-empty `certification` in the US release-date set (a movie), or the US
    content rating (TV); NR when TMDB has none."""
    if tmdb_type == "tv":
        for r in (d.get("content_ratings") or {}).get("results") or []:
            if r.get("iso_3166_1") == "US" and clean(r.get("rating")):
                return clean(r["rating"])
        return "NR"
    for country in (d.get("release_dates") or {}).get("results") or []:
        if country.get("iso_3166_1") == "US":
            for rel in country.get("release_dates") or []:
                if clean(rel.get("certification")):
                    return clean(rel["certification"])
    return "NR"


def _runtime(d, tmdb_type):
    """Minutes, or None. A TV special has episode_run_time: [minutes]. TMDB sends 0 or null for unknown."""
    if tmdb_type == "tv":
        runs = [m for m in (d.get("episode_run_time") or []) if isinstance(m, int) and m > 0]
        return runs[0] if runs else None
    runtime = d.get("runtime")
    return runtime if isinstance(runtime, int) and runtime > 0 else None


def details(tmdb_id, tmdb_type="movie"):
    """Everything the list keeps about one title:
    {tmdb_id, tmdb_type, title, year, runtime_min, genres, is_animated, us_certification, collection_id,
     collection_name, top_cast (<= 8 names), tmdb_vote, overview, poster_path, backdrop_path}.
    poster_path and backdrop_path are TMDB's own paths (/abc.jpg); images.py turns them into local files."""
    if tmdb_type not in TYPES:
        raise ValueError(f"tmdb_type must be one of {TYPES}")
    tmdb_id = int(tmdb_id)
    if tmdb_type == "tv":
        d = _get(f"/tv/{tmdb_id}", append_to_response="content_ratings,credits", language="en-US")
        title, date = d.get("name") or d.get("original_name"), d.get("first_air_date")
    else:
        d = _get(f"/movie/{tmdb_id}", append_to_response="release_dates,credits", language="en-US")
        title, date = d.get("title") or d.get("original_title"), d.get("release_date")
    genres = [x for x in (d.get("genres") or []) if isinstance(x, dict)]
    coll = d.get("belongs_to_collection") or {}
    cast = sorted((c for c in (d.get("credits") or {}).get("cast") or [] if clean(c.get("name"))),
                  key=lambda c: c.get("order") if isinstance(c.get("order"), int) else 999)
    return {
        "tmdb_id": tmdb_id, "tmdb_type": tmdb_type, "title": clean(title) or f"TMDB {tmdb_id}", "year": _year(date),
        "runtime_min": _runtime(d, tmdb_type), "genres": [x["name"] for x in genres if x.get("name")],
        "is_animated": any(x.get("id") == ANIMATION_GENRE for x in genres),
        "us_certification": us_certification(d, tmdb_type),
        "collection_id": coll.get("id"), "collection_name": clean(coll.get("name")),
        "top_cast": [clean(c["name"]) for c in cast[:MAX_CAST]],
        "tmdb_vote": d.get("vote_average") if d.get("vote_count") else None,
        "overview": clean(d.get("overview")), "poster_path": clean(d.get("poster_path")),
        "backdrop_path": clean(d.get("backdrop_path")),
    }
