"""The Netflix title id of a movie (netflix-title design §4.1): looked up from Wikidata by TMDB id, or saved by hand
from a pasted link, and kept per movie and service in service_titles so a second service needs no schema change. The
id is only offered for a movie TMDB lists on Netflix (the providers cache), and a hand-set id is never touched by the
lookup. Route-free: a bad link aborts with common.make_err, and a Wikidata failure raises wikidata.WikidataError for
the caller. No Flask object here (see CLAUDE.md)."""
import re

from flask import abort, current_app, has_app_context

import movies
import providers
import wikidata
from common import make_err, now_iso

NETFLIX = "netflix"
STALE_DAYS = 30            # a found id, or "none found", is asked again after this long
ID_RE = re.compile(r"[0-9]{1,12}")
# netflix.com/title/<id> or /watch/<id>: any scheme, www. or not, an optional locale segment (/us/, /en-gb/), then
# nothing, a slash, a query string or a fragment. Anything else after the id, or any other host, is refused.
LINK_RE = re.compile(r"(?:[a-z][a-z0-9+.-]*://)?(?:www\.)?netflix\.com/(?:[a-z]{2}(?:-[a-z]{2})?/)?(?:title|watch)/"
                     r"([0-9]{1,12})/?(?:[?#].*)?", re.IGNORECASE)
LINK_ERROR = "That doesn't look like a Netflix link."


def on_netflix(con, movie_id):
    """True when the providers cache lists Netflix among the flatrate services. No TMDB call."""
    return NETFLIX in providers.cached(con, movie_id)[0]["flatrate"]


def _row(con, movie_id, service):
    return con.execute("SELECT * FROM service_titles WHERE movie_id=? AND service=?", (movie_id, service)).fetchone()


def get(con, movie_id, service=NETFLIX):
    """The stored title id, or None (nothing stored, or the lookup found none)."""
    row = _row(con, movie_id, service)
    return row["title_id"] if row else None


def out(con, movie_id):
    """What the API shows: {"title_id": str | None, "manual": bool}, or None when the movie is not on Netflix."""
    if not on_netflix(con, movie_id):
        return None
    row = _row(con, movie_id, NETFLIX)
    return {"title_id": row["title_id"] if row else None, "manual": bool(row and row["manual"])}


def lookup(con, movie_id):
    """Ask Wikidata for the movie's Netflix id and store the answer (an id, or NULL for none) with the time asked.
    Does nothing, and returns the stored id, when the movie is not on Netflix or its id was set by hand. WikidataError
    goes to the caller, and then nothing is stored (the last answer stays)."""
    row = _row(con, movie_id, NETFLIX)
    if not on_netflix(con, movie_id) or (row and row["manual"]):
        return row["title_id"] if row else None
    movie = movies.get_row(con, movie_id)
    found = wikidata.netflix_id(movie["tmdb_id"], movie["tmdb_type"])
    # `WHERE manual = 0`: an id somebody saved while Wikidata was thinking wins over the answer.
    con.execute("INSERT INTO service_titles (movie_id, service, title_id, manual, checked_at) VALUES (?,?,?,0,?)"
                " ON CONFLICT(movie_id, service) DO UPDATE SET title_id=excluded.title_id, checked_at=excluded.checked_at"
                " WHERE service_titles.manual = 0", (movie_id, NETFLIX, found, now_iso()))
    con.commit()
    return get(con, movie_id)


def lookup_quietly(con, movie_id):
    """lookup() that never fails: Wikidata being down, slow or unreadable is one warning in the log, and the nightly
    job asks again."""
    try:
        lookup(con, movie_id)
    except wikidata.WikidataError as e:
        if has_app_context():
            current_app.logger.warning("Netflix title id for movie %s not looked up: %s", movie_id, e.message)


def due(con):
    """The ids of the movies the nightly job should ask Wikidata about: on Netflix, not set by hand, and never asked
    or last asked over STALE_DAYS ago."""
    asked = {r["movie_id"]: r for r in con.execute("SELECT * FROM service_titles WHERE service=?", (NETFLIX,))}
    ids = []
    for r in con.execute("SELECT id FROM movies ORDER BY id"):
        row = asked.get(r["id"])
        if on_netflix(con, r["id"]) and not (row and row["manual"]) \
                and movies.ownership_is_stale(row["checked_at"] if row else None, STALE_DAYS):
            ids.append(r["id"])
    return ids


def parse_link(raw):
    """The title id in what somebody pasted: None for empty (or null), the digits of a netflix.com/title/<id> or
    /watch/<id> address, or a bare 1-to-12-digit number. Anything else is a 400, so nothing but digits is stored."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        abort(make_err(400, LINK_ERROR))
    text = raw.strip()
    if not text:
        return None
    if ID_RE.fullmatch(text):
        return text
    m = LINK_RE.fullmatch(text)
    if not m:
        abort(make_err(400, LINK_ERROR))
    return m.group(1)


def set_manual(con, movie_id, raw):
    """Save a pasted link as the movie's Netflix id, marked as set by hand (the lookup never changes it). Empty clears
    a hand-set id, so the next lookup fills it again; a found id is left alone. 400 for a link that isn't Netflix's."""
    title_id = parse_link(raw)
    if title_id is None:
        con.execute("DELETE FROM service_titles WHERE movie_id=? AND service=? AND manual=1", (movie_id, NETFLIX))
    else:
        con.execute("INSERT INTO service_titles (movie_id, service, title_id, manual, checked_at) VALUES (?,?,?,1,?)"
                    " ON CONFLICT(movie_id, service) DO UPDATE SET title_id=excluded.title_id, manual=1,"
                    " checked_at=excluded.checked_at", (movie_id, NETFLIX, title_id, now_iso()))
    con.commit()
