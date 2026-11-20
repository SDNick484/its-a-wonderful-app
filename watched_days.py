"""The Calendar tab's data (calendar spec §4, §5): the movies watched on each day of a month. A viewing shows on the
local evening of each TV session (a start before 4 am counts as the evening before, viewings.NIGHT_ENDS), on its
started_on, and on its finished_on when finished. Abandoned viewings and tonight picks with no TV time are left out.
Route-free; GET /api/calendar is in app.py. Named so it never shadows the standard library's `calendar`."""
import datetime as dt, re

from flask import abort

import images
from common import make_err, today
from viewings import NIGHT_ENDS, _local, _stamp

MONTH_RE = re.compile(r"(\d{4})-(\d{2})", re.ASCII)
MONTH_ERROR = "month must look like 2026-12"


def parse_month(raw):
    """(year, month) from "YYYY-MM"; None means this month on the host's date. Anything else aborts with a 400."""
    if raw is None:
        now = today()
        return now.year, now.month
    m = MONTH_RE.fullmatch(raw)
    if not m or int(m[1]) < 1 or not 1 <= int(m[2]) <= 12:
        abort(make_err(400, MONTH_ERROR))
    return int(m[1]), int(m[2])


def night_of(started_at):
    """The local evening a session that started at `started_at` belongs to, or None when the stamp can't be read."""
    when = _stamp(started_at)
    if when is None:
        return None
    return (_local(when) - dt.timedelta(hours=NIGHT_ENDS)).date()


def _day(text):
    try:
        return dt.date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def month_view(con, raw):
    """{"month", "today", "days": {"YYYY-MM-DD": [{movie_id, viewing_id, title, year, poster_url, finished}]}} for
    the month `raw` names. Within a day: finished first, then the viewing's earliest session, then viewing_id. A
    family's viewings are a few hundred rows at most, so the month filter is done here, not in SQL."""
    year, month = parse_month(raw)
    starts = {}
    for s in con.execute("SELECT viewing_id, started_at FROM sessions"):
        starts.setdefault(s["viewing_id"], []).append(s["started_at"])
    rows = con.execute("SELECT v.id, v.movie_id, v.status, v.started_on, v.finished_on, m.title, m.year, m.poster_path"
                       " FROM viewings v JOIN movies m ON m.id = v.movie_id WHERE v.status != 'abandoned'").fetchall()
    days = {}
    for r in rows:
        stamps = starts.get(r["id"], [])
        if r["status"] == "tonight" and not stamps:
            continue
        whens = [w for w in map(_stamp, stamps) if w]
        # started_on and finished_on are calendar dates (today(), the last session's date), so a watch after midnight
        # would also show on the next day: that date folds into the session's night, a night that did happen.
        fold = {}
        for w in whens:
            local = _local(w)
            if local.hour < NIGHT_ENDS:
                fold[local.date()] = local.date() - dt.timedelta(days=1)
        started_on, finished_on = _day(r["started_on"]), _day(r["finished_on"]) if r["status"] == "finished" else None
        started_on, finished_on = fold.get(started_on, started_on), fold.get(finished_on, finished_on)
        nights = {night_of(s) for s in stamps} | {started_on, finished_on}
        first = min(whens).astimezone(dt.timezone.utc).isoformat() if whens else ""
        for night in nights:
            if night is None or (night.year, night.month) != (year, month):
                continue
            done = night == finished_on
            entry = {"movie_id": r["movie_id"], "viewing_id": r["id"], "title": r["title"], "year": r["year"],
                     "poster_url": images.image_url(r["poster_path"]), "finished": done}
            days.setdefault(night.isoformat(), []).append(((not done, first, r["id"]), entry))
    return {"month": f"{year:04d}-{month:02d}", "today": today().isoformat(),
            "days": {day: [e for _, e in sorted(days[day], key=lambda p: p[0])] for day in sorted(days)}}
