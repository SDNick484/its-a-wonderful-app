"""Worth a Month? (spec §13, decision 16): for each service the family is considering, how many movies on our list
it would add. A movie counts when (a) Matinee doesn't own it, (b) it is not on a subscribed or free service, (c) it is
on this service's flatrate, and (d) it was not watched this year. Sorted by count, then name; a service adding nothing
is listed with the reason. Route-free (see CLAUDE.md). Reads only the database: the providers cache and matinee_sync,
never TMDB or Matinee, so the card works while either is down."""
import providers
import movies
import randomizer
from common import today

SEASON_MONTHS = (11, 12)     # the home-screen card shows in November and December (spec §13)


def season(day=None):
    """True in November and December on the host's date (TZ), when the home screen shows the card."""
    return (day or today()).month in SEASON_MONTHS


def _owned(con, movie_id):
    row = con.execute("SELECT matinee_title_id FROM matinee_sync WHERE movie_id=?", (movie_id,)).fetchone()
    return row is not None and row["matinee_title_id"] is not None


def compute(con, year):
    """[{service, name, movies: [ids], count, reason}] for every service set to considering, most movies first, then by
    name. `reason` is None when the service adds something; a service adding 0 gets a sentence saying why."""
    considering = con.execute("SELECT key, name FROM services WHERE status='considering' ORDER BY rowid").fetchall()
    found = {s["key"]: {"service": s["key"], "name": s["name"], "movies": [], "on_list": 0} for s in considering}
    if not found:
        return []
    have = {r["key"] for r in con.execute("SELECT key FROM services WHERE status='subscribed'")}
    for m in movies.list_rows(con):
        movie_id = m["id"]
        data = providers.cached(con, movie_id)[0]
        here = set(data["flatrate"]) & set(found)       # considering services that stream it (c)
        if not here:
            continue
        on_have = bool(data["free"] or data["ads"]) or bool(set(data["flatrate"]) & have)   # (b)
        counted = not (_owned(con, movie_id) or on_have or randomizer.watched_this_year(con, movie_id, year))   # (a), (d)
        for key in here:
            found[key]["on_list"] += 1
            if counted:
                found[key]["movies"].append(movie_id)
    out = []
    for entry in found.values():
        count = len(entry["movies"])
        reason = None
        if count == 0:
            reason = ("None of our movies is on it." if entry["on_list"] == 0 else
                      f"All {entry['on_list']} of its movies here are owned, already on a service you have, "
                      "free, or watched this year.")
        out.append({"service": entry["service"], "name": entry["name"], "movies": entry["movies"], "count": count,
                    "reason": reason})
    out.sort(key=lambda e: (-e["count"], e["name"]))
    return out


def worth(con, day=None):
    """GET /api/worth: the year, whether the home card shows (season), and compute() for this year."""
    day = day or today()
    return {"year": day.year, "season": season(day), "services": compute(con, day.year)}

