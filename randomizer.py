"""The randomizer (spec §12): three distinct movies drawn uniformly from the list after the filter chips, and Pick Again
that skips what was already shown until the pool runs out. Route-free: a bad request aborts with common.make_err, and
app.py's POST /api/surprise calls surprise(). No Flask object here (see CLAUDE.md).

Reads only: the movies row, viewings, matinee_sync and the providers cache. No TMDB or Matinee call, so the button works
while either is down."""
import random

from flask import abort

import movies
import providers
from common import make_err, today

PICKS = 3
CAPS = ("G", "PG", "PG-13")
FILTER_KEYS = ("animated", "cap", "under_90", "not_watched_this_year", "ready")
UNDER_MINUTES = 90

# Certification -> its place on the cap ladder (0 = G, 1 = PG, 2 = PG-13). A cap keeps a movie at or below its rung.
# NR counts as PG (spec §7.3); so does a missing certification, which is how a TMDB title with no US rating is stored
# anyway. R, NC-17, TV-MA and anything unknown are on no rung: a cap excludes them.
_RUNG = {"G": 0, "TV-Y": 0, "TV-G": 0, "PG": 1, "TV-Y7": 1, "TV-PG": 1, "NR": 1, "PG-13": 2, "TV-14": 2}


def _rung(certification):
    return _RUNG.get((certification or "NR").strip().upper())


def passes_cap(certification, cap):
    """True when the movie is allowed under the cap (None = no cap): NR and no certification count as PG."""
    if cap is None:
        return True
    rung = _rung(certification)
    return rung is not None and rung <= CAPS.index(cap)


def watched_this_year(con, movie_id, year):
    """True when the movie was watched in the calendar `year`: a `finished` viewing whose finished_on (a local date)
    falls in it, or Matinee's newest watch (matinee_last_watch, for an owned movie) does. A watch on January 2 counts
    for the new year; one on December 30 for the old. A viewing that is only started, paused or abandoned does not count."""
    prefix = f"{int(year):04d}-"
    row = con.execute("SELECT 1 FROM viewings WHERE movie_id=? AND status='finished' AND finished_on LIKE ? LIMIT 1",
                      (movie_id, prefix + "%")).fetchone()
    if row is not None:
        return True
    sync = con.execute("SELECT matinee_last_watch FROM matinee_sync WHERE movie_id=?", (movie_id,)).fetchone()
    return sync is not None and (sync["matinee_last_watch"] or "").startswith(prefix)


def clean_filters(raw):
    """The filter dict with every key present: animated True/False/None, cap None or one of CAPS, the rest booleans.
    A missing key is off; a wrong type, an unknown cap or an unknown key is a 400."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        abort(make_err(400, "filters must be an object."))
    unknown = sorted(set(raw) - set(FILTER_KEYS))
    if unknown:
        abort(make_err(400, "Unknown filter: " + ", ".join(map(str, unknown)) + "."))
    out = {"animated": raw.get("animated"), "cap": raw.get("cap")}
    if out["animated"] not in (True, False, None):
        abort(make_err(400, "animated must be true, false or null."))
    if out["cap"] not in (None, *CAPS):
        abort(make_err(400, "cap must be null, " + ", ".join(CAPS) + "."))
    for key in ("under_90", "not_watched_this_year", "ready"):
        value = raw.get(key, False)
        if not isinstance(value, bool):
            abort(make_err(400, f"{key} must be true or false."))
        out[key] = value
    return out


def pool(con, filters, year=None):
    """The ids of the movies that pass every filter that is on, in list order. All off is the whole list. `year` is the
    calendar year "Not watched this year" means (default: this year on the host's TZ)."""
    f = clean_filters(filters)
    year = today().year if year is None else year
    out = []
    for row in movies.list_rows(con):
        if f["animated"] is not None and bool(row["is_animated"]) != f["animated"]:
            continue
        if not passes_cap(row["certification"], f["cap"]):
            continue
        if f["under_90"] and not (row["runtime_min"] is not None and row["runtime_min"] < UNDER_MINUTES):
            continue      # no runtime is unknown, not short: it fails "Under 90 min"
        if f["not_watched_this_year"] and watched_this_year(con, row["id"], year):
            continue
        if f["ready"] and not providers.ready_tonight(con, row["id"]):
            continue
        out.append(row["id"])
    return out


def pick(pool, exclude, k=PICKS, rng=None):
    """Up to k distinct ids from the pool that are not in `exclude`, uniformly at random (fewer when fewer are left).
    `rng` is a random.Random (a test passes a seeded one)."""
    rng = rng or random
    fresh = [i for i in pool if i not in exclude]
    return rng.sample(fresh, min(k, len(fresh)))


def clean_exclude(raw):
    if raw is None:
        return set()
    if not isinstance(raw, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in raw):
        abort(make_err(400, "exclude must be a list of movie ids."))
    return set(raw)


def surprise(con, data, rng=None):
    """POST /api/surprise {"filters": {...}, "exclude": [ids]} -> {"picks": [ids], "pool_size": n, "restarted": bool}.
    Pick Again sends what was shown since the filters last changed. When fewer than three unseen movies are left, the
    ones left are shown and the rest drawn from the whole pool, and `restarted` is true: the page says it started over.
    A pool smaller than three just returns what matches."""
    if not isinstance(data, dict):
        abort(make_err(400, "Send a JSON body with filters and exclude."))
    ids = pool(con, data.get("filters"))
    exclude = clean_exclude(data.get("exclude")) & set(ids)
    picks = pick(ids, exclude, PICKS, rng)
    restarted = False
    if len(picks) < PICKS and len(picks) < len(ids):
        restarted = True
        picks += pick(ids, set(picks), PICKS - len(picks), rng)
    return {"picks": picks, "pool_size": len(ids), "restarted": restarted}
