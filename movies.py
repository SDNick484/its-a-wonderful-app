"""The curated list (spec §7): add a movie from TMDB, read it back for the page, edit the parent note and the
certification, refresh from TMDB, remove. Route-free: a bad request aborts with common.make_err, and a TMDB failure
raises tmdb.TmdbError for app.py to answer. No Flask object here (see CLAUDE.md)."""
import datetime as dt, json, sqlite3, time

from flask import abort, current_app, has_app_context

import images
import matinee
import sync
import tmdb
from common import clean, make_err, now_iso

CERTIFICATIONS = ("G", "PG", "PG-13", "R", "NC-17", "NR", "TV-Y", "TV-Y7", "TV-G", "TV-PG", "TV-14", "TV-MA")
NOTE_MAX = 1000
OWNERSHIP_STALE_DAYS = 1      # spec §8.1: ownership is asked again when the last good answer is older than a day
MATINEE_BACKOFF = 60          # seconds a page view leaves Matinee alone after it failed to answer
_matinee_failed_at = None     # time.monotonic() of the last failed page-view lookup (this worker only)


def get_row(con, movie_id):
    """The movies row, or a 404."""
    row = con.execute("SELECT * FROM movies WHERE id=?", (movie_id,)).fetchone()
    if row is None:
        abort(make_err(404, "That movie isn't on our list."))
    return row


def parse_ref(data):
    """(tmdb_id, tmdb_type) from a request body {tmdb_id, tmdb_type}; 400 when either is wrong. A missing type
    means 'movie', like the column's default."""
    if not isinstance(data, dict):
        abort(make_err(400, "Send a JSON body with tmdb_id and tmdb_type."))
    tmdb_type = data.get("tmdb_type", "movie")
    if tmdb_type not in tmdb.TYPES:
        abort(make_err(400, "tmdb_type must be 'movie' or 'tv'."))
    tmdb_id = data.get("tmdb_id")
    if isinstance(tmdb_id, str) and tmdb_id.strip().isdigit():
        tmdb_id = int(tmdb_id)
    if isinstance(tmdb_id, bool) or not isinstance(tmdb_id, int) or tmdb_id <= 0:
        abort(make_err(400, "tmdb_id must be a positive whole number."))
    return tmdb_id, tmdb_type


def _already(existing_id):
    abort(make_err(409, "That one is already on our list.", id=existing_id))


def add_movie(con, tmdb_id, tmdb_type, added_by):
    """Fetch the details from TMDB, keep the poster and backdrop locally, add the row and return its id. 409 when
    that title is already on the list (before TMDB is asked); TmdbError when TMDB can't answer."""
    row = con.execute("SELECT id FROM movies WHERE tmdb_type=? AND tmdb_id=?", (tmdb_type, tmdb_id)).fetchone()
    if row:
        _already(row["id"])
    d = tmdb.details(tmdb_id, tmdb_type)
    poster = images.fetch(d["poster_path"], images.POSTER_SIZE, images.poster_name(tmdb_type, tmdb_id))
    backdrop = images.fetch(d["backdrop_path"], images.BACKDROP_SIZE, images.backdrop_name(tmdb_type, tmdb_id))
    try:
        cur = con.execute(
            "INSERT INTO movies (tmdb_id, tmdb_type, title, year, runtime_min, certification, overview, poster_path,"
            " backdrop_path, is_animated, collection_id, collection_name, top_cast, tmdb_vote, added_by, meta_refreshed_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tmdb_id, tmdb_type, d["title"], d["year"], d["runtime_min"], d["us_certification"], d["overview"], poster,
             backdrop, int(d["is_animated"]), d["collection_id"], d["collection_name"], json.dumps(d["top_cast"]),
             d["tmdb_vote"], added_by, now_iso()))
        con.commit()
    except sqlite3.IntegrityError:   # two people tapped Add at once
        con.rollback()
        row = con.execute("SELECT id FROM movies WHERE tmdb_type=? AND tmdb_id=?", (tmdb_type, tmdb_id)).fetchone()
        _already(row["id"] if row else None)
    return cur.lastrowid


def refresh_metadata(con, movie_id):
    """Re-read the details from TMDB. A hand-set certification (certification_override = 1) is kept; a poster that
    failed to download earlier is tried again, and one already on disk is never downloaded twice."""
    row = get_row(con, movie_id)
    d = tmdb.details(row["tmdb_id"], row["tmdb_type"])
    poster = images.fetch(d["poster_path"], images.POSTER_SIZE, images.poster_name(row["tmdb_type"], row["tmdb_id"]))
    backdrop = images.fetch(d["backdrop_path"], images.BACKDROP_SIZE, images.backdrop_name(row["tmdb_type"], row["tmdb_id"]))
    cert = row["certification"] if row["certification_override"] else d["us_certification"]
    con.execute(
        "UPDATE movies SET title=?, year=?, runtime_min=?, certification=?, overview=?, poster_path=?, backdrop_path=?,"
        " is_animated=?, collection_id=?, collection_name=?, top_cast=?, tmdb_vote=?, meta_refreshed_at=? WHERE id=?",
        (d["title"], d["year"], d["runtime_min"], cert, d["overview"], poster or row["poster_path"],
         backdrop or row["backdrop_path"], int(d["is_animated"]), d["collection_id"], d["collection_name"],
         json.dumps(d["top_cast"]), d["tmdb_vote"], now_iso(), movie_id))
    con.commit()


def update_movie(con, movie_id, data):
    """PUT /api/movies/<id>: `parent_note` (text, or null/blank to clear) and/or `certification` (one of
    CERTIFICATIONS; setting it stops refreshes changing it back; null or blank lifts the override, and the next
    refresh brings TMDB's value back). 400 for anything else."""
    get_row(con, movie_id)
    if not isinstance(data, dict) or not ({"parent_note", "certification"} & set(data)):
        abort(make_err(400, "Send parent_note and/or certification."))
    sets, args = [], []
    if "parent_note" in data:
        note = data["parent_note"]
        if note is not None and not isinstance(note, str):
            abort(make_err(400, "parent_note must be text."))
        note = clean(note)
        if note and len(note) > NOTE_MAX:
            abort(make_err(400, f"The note is too long (most {NOTE_MAX} characters)."))
        sets.append("parent_note=?"); args.append(note)
    if "certification" in data:
        cert = data["certification"]
        if cert is not None and not isinstance(cert, str):
            abort(make_err(400, "certification must be text."))
        cert = (clean(cert) or "").upper()
        if cert and cert not in CERTIFICATIONS:
            abort(make_err(400, "certification must be one of " + ", ".join(CERTIFICATIONS) + "."))
        if cert:
            sets += ["certification=?", "certification_override=1"]; args.append(cert)
        else:
            sets.append("certification_override=0")
    con.execute(f"UPDATE movies SET {', '.join(sets)} WHERE id=?", (*args, movie_id))
    con.commit()


def remove_movie(con, movie_id):
    """Delete the movie; its ratings, viewings and cached providers go with it (ON DELETE CASCADE), and so do its
    local images."""
    row = get_row(con, movie_id)
    con.execute("DELETE FROM movies WHERE id=?", (movie_id,))
    con.commit()
    images.delete(row["poster_path"], row["backdrop_path"])


# ------------------------------------------------------------------------------------------------ ownership (Matinee)
def ownership_is_stale(checked_at, max_age_days=OWNERSHIP_STALE_DAYS):
    """True when `checked_at` (a matinee_sync timestamp) is missing, unreadable or older than max_age_days."""
    try:
        when = dt.datetime.strptime(checked_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return True
    return dt.datetime.now(dt.timezone.utc) - when > dt.timedelta(days=max_age_days)


def _newest_watch(watches):
    """The newest valid watched_date (YYYY-MM-DD) in a Matinee title's watches, or None. A watch with no date, or one
    Matinee estimated from a bucket and left blank, is skipped."""
    found = []
    for w in watches if isinstance(watches, list) else []:
        day = w.get("watched_date") if isinstance(w, dict) else None
        try:
            found.append(dt.date.fromisoformat(day).isoformat())
        except (TypeError, ValueError):
            continue
    return max(found, default=None)


def _user_rating(detail):
    """Matinee's household rating from a title record (`user_rating`), or None when it has none."""
    value = detail.get("user_rating") if isinstance(detail, dict) else None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def check_ownership(con, movie_id):
    """Ask Matinee whether the movie is owned and where, and store the answer in matinee_sync (spec §8.1).
    A title Matinee doesn't have, or has with no copy, is not owned: matinee_title_id NULL and no summary or shelf.
    A TV-only entry (tmdb_type 'tv') is never asked: Matinee keys titles by movie id, so a TV id could match an
    unrelated movie (spec §8.2). Only the five Matinee-read columns and checked_at are written here; then
    sync.reconcile compares Matinee's rating with the family's (the bought-later rule, a conflict, a push still owed).
    Raises matinee.Unavailable or matinee.Rejected when Matinee gives no answer: nothing is changed then, so the last
    known answer and its checked_at stay."""
    row = get_row(con, movie_id)
    if row["tmdb_type"] != "movie":
        return
    api = matinee.client()
    before = con.execute("SELECT * FROM matinee_sync WHERE movie_id=?", (movie_id,)).fetchone()
    found = api.owned(row["tmdb_id"])
    title_id = found["title_id"] if found["summary"] else None
    summary = location = rating = last_watch = None
    if title_id is not None:
        summary, location = found["summary"], found["location_path"]
        detail = api.title(title_id)
        rating = _user_rating(detail)
        last_watch = _newest_watch(detail.get("watches"))
    con.execute(
        "INSERT INTO matinee_sync (movie_id, matinee_title_id, owned_summary, location_path, matinee_rating,"
        " matinee_last_watch, checked_at) VALUES (?,?,?,?,?,?,?)"
        " ON CONFLICT(movie_id) DO UPDATE SET matinee_title_id=excluded.matinee_title_id,"
        " owned_summary=excluded.owned_summary, location_path=excluded.location_path,"
        " matinee_rating=excluded.matinee_rating, matinee_last_watch=excluded.matinee_last_watch,"
        " checked_at=excluded.checked_at",
        (movie_id, title_id, summary, location, rating, last_watch, now_iso()))
    con.commit()
    sync.reconcile(con, movie_id, before)


def refresh_ownership(con, movie_id):
    """check_ownership that never fails: Matinee being down, slow, or refusing our key (spec Review Focus 1) is logged
    and the last known ownership stays, which where_to_watch shows as "(as of <date>)"."""
    try:
        check_ownership(con, movie_id)
    except (matinee.Unavailable, matinee.Rejected) as e:
        if has_app_context():
            current_app.logger.warning("Matinee ownership for movie %s not refreshed: %s", movie_id, e.message)


def refresh_ownership_if_stale(con, movie_id):
    """For the detail view: refresh when the last good answer is over a day old (or there is none), but after a
    failure leave Matinee alone for MATINEE_BACKOFF seconds, so a Matinee that is down doesn't add its timeout to
    every tap. TV entries and an app with no Matinee key do nothing."""
    global _matinee_failed_at
    row = get_row(con, movie_id)
    if row["tmdb_type"] != "movie" or not matinee.configured():
        return
    sync = con.execute("SELECT checked_at FROM matinee_sync WHERE movie_id=?", (movie_id,)).fetchone()
    if sync is not None and not ownership_is_stale(sync["checked_at"]):
        return
    if _matinee_failed_at is not None and time.monotonic() - _matinee_failed_at < MATINEE_BACKOFF:
        return
    try:
        check_ownership(con, movie_id)
        _matinee_failed_at = None
    except (matinee.Unavailable, matinee.Rejected) as e:
        _matinee_failed_at = time.monotonic()
        if has_app_context():
            current_app.logger.warning("Matinee ownership for movie %s not refreshed: %s", movie_id, e.message)


def ownership_due(con):
    """The ids of the movies the nightly job should ask Matinee about: movies never checked, last checked over a
    day ago, or with a family rating still owed to Matinee (asking again is what sends it, sync.reconcile). TV-only
    entries are never asked."""
    owed = set(sync.pending_ids(con))
    return [r["id"] for r in con.execute(
        "SELECT m.id, s.checked_at FROM movies m LEFT JOIN matinee_sync s ON s.movie_id = m.id"
        " WHERE m.tmdb_type = 'movie' ORDER BY m.id") if r["id"] in owed or ownership_is_stale(r["checked_at"])]


def list_rows(con):
    return con.execute("SELECT * FROM movies ORDER BY title COLLATE NOCASE, id").fetchall()


def movie_out(row):
    """One movie as the page sees it. A missing poster is poster_url None (the page shows a titled placeholder).
    family_rating is the slot the grid card reserves; ratings fill it in later."""
    try:
        cast = json.loads(row["top_cast"]) if row["top_cast"] else []
    except ValueError:
        cast = []
    return {
        "id": row["id"], "tmdb_id": row["tmdb_id"], "tmdb_type": row["tmdb_type"], "title": row["title"],
        "year": row["year"], "runtime_min": row["runtime_min"], "certification": row["certification"],
        "certification_override": bool(row["certification_override"]), "overview": row["overview"],
        "poster_url": images.image_url(row["poster_path"]), "backdrop_url": images.image_url(row["backdrop_path"]),
        "is_animated": bool(row["is_animated"]), "collection_id": row["collection_id"],
        "collection_name": row["collection_name"], "top_cast": cast, "tmdb_vote": row["tmdb_vote"],
        "parent_note": row["parent_note"], "added_by": row["added_by"], "added_at": row["added_at"],
        "family_rating": None,
    }
