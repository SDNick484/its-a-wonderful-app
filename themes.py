"""The Advent themes (spec §14.2): which scene the app wears today, and the household's theme settings.

Route-free (see CLAUDE.md): app.py holds `GET /api/theme` and `GET`/`PUT /api/theme/prefs` and asks this module. The
calendar is pure date math, so it is tested without a database; the caller passes the host's local date
(`common.today()`, TZ), never UTC, so on January 1 the family still gets Santa from the previous Advent.

The first Sunday of Advent is the fourth Sunday before December 25, so the fourth is the last Sunday before
Christmas Day (December 25 itself is not Advent 4 when it falls on a Sunday)."""
import datetime as dt

from flask import abort

from common import make_err

THEME_KEYS = ("fireplace", "toystore", "tree", "sleigh")   # Advent 1, 2, 3, 4 (the folders in static/themes/)
LAST_DAY = (1, 6)                                          # Advent 4's window runs to January 6
MODES = ("system", "light", "dark")                        # for the plain period; a theme is always dark
ENABLED_KEY = "theme_enabled"                              # meta keys: the household's choice, in the database
MODE_KEY = "theme_mode"


def advent_sunday(year, n):
    """The Sunday that starts Advent week `n` (1..4) before Christmas of `year`. 2026: Nov 29, Dec 6, 13, 20."""
    if n not in (1, 2, 3, 4):
        raise ValueError("n must be 1, 2, 3 or 4")
    christmas = dt.date(year, 12, 25)
    fourth = christmas - dt.timedelta(days=(christmas.weekday() + 1) % 7 or 7)   # the Sunday strictly before it
    return fourth - dt.timedelta(weeks=4 - n)


def _windows(year):
    """[(theme, first day, last day)] for the Advent that starts in `year`; the fourth ends on January 6 after."""
    sundays = [advent_sunday(year, n) for n in (1, 2, 3, 4)]
    ends = [s - dt.timedelta(days=1) for s in sundays[1:]] + [dt.date(year + 1, *LAST_DAY)]
    return list(zip(THEME_KEYS, sundays, ends))


def theme_window(d):
    """(theme or None, last day it holds): the theme on date `d` and the last date that same answer is still true.
    Plain days end the day before the next Advent begins."""
    for year in (d.year, d.year - 1):          # January 1-6 belongs to the Advent that began the year before
        for key, first, last in _windows(year):
            if first <= d <= last:
                return key, last
    start = advent_sunday(d.year, 1)
    if d > start:                              # after January 6: plain until next year's Advent
        start = advent_sunday(d.year + 1, 1)
    return None, start - dt.timedelta(days=1)


def theme_for(d):
    """"fireplace" | "toystore" | "tree" | "sleigh" on date `d`, or None for the plain look."""
    return theme_window(d)[0]


def current(d):
    """The body of GET /api/theme: {"theme": key or None, "until": "YYYY-MM-DD"}."""
    key, until = theme_window(d)
    return {"theme": key, "until": until.isoformat()}


# ------------------------------------------------------------------------------------------------ the household's settings
def get_prefs(con):
    """{"enabled": bool, "mode": "system" | "light" | "dark"}: themes on (the default) and the plain period's look."""
    rows = dict(con.execute("SELECT k, v FROM meta WHERE k IN (?, ?)", (ENABLED_KEY, MODE_KEY)).fetchall())
    mode = rows.get(MODE_KEY)
    return {"enabled": rows.get(ENABLED_KEY) != "0", "mode": mode if mode in MODES else "system"}


def set_prefs(con, data):
    """PUT /api/theme/prefs {"enabled"?: bool, "mode"?: "system"|"light"|"dark"}: what is sent changes, the rest stays.
    400 for a body that is not an object, says nothing to change, or has a wrong type or value."""
    if not isinstance(data, dict) or not ({"enabled", "mode"} & data.keys()):
        abort(make_err(400, "Send enabled (true or false) and/or mode (system, light or dark)."))
    if "enabled" in data and not isinstance(data["enabled"], bool):
        abort(make_err(400, "enabled must be true or false."))
    if "mode" in data and data["mode"] not in MODES:
        abort(make_err(400, "mode must be one of " + ", ".join(MODES) + "."))
    if "enabled" in data:
        con.execute("INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                    (ENABLED_KEY, "1" if data["enabled"] else "0"))
    if "mode" in data:
        con.execute("INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                    (MODE_KEY, data["mode"]))
    con.commit()
    return get_prefs(con)
