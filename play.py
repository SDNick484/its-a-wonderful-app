"""Play on the Family Room TV (design 2026-11-26, §5.1, §5.2): what can play a movie, and starting it. Route-free: a bad
request aborts with common.make_err, and no Flask object lives here (see CLAUDE.md).

options() is the one rule the movie page, the main page and the play route all use. It reads the providers cache, the
services table and Matinee's stored copy kinds only: no TMDB or Matinee call. start() works out the target from the same
rule, marks the movie for tonight (viewings.watch_tonight), asks Home Assistant to start it (ha.post_play) and says
whether the TV is already there. HA_PLAY_WEBHOOK_URL is a secret and is never logged or returned (ha.py's rule)."""
import datetime as dt

from flask import abort

import ha
import movies
import providers
import viewings
from common import clean, make_err
from settings import HA_PLAY_WEBHOOK_URL

MODES = ("auto", "stream", "disc")


def enabled():
    """True when HA_PLAY_WEBHOOK_URL is set; empty means Play on TV is off everywhere."""
    return bool(HA_PLAY_WEBHOOK_URL)


# ------------------------------------------------------------------------------------------------ the rule (§5.1)
def _stream_options(con, movie_id, digital):
    """The services the TV can open the movie on, best first, each {"service", "name", "owned", "tv_source"}: our
    digital copy (Fandango at Home, whatever its status), then subscribed `flatrate` services, then known `free` or
    `ads` services not set to Ignore, the last two in Subscriptions order. A service needs a tv_source and appears once."""
    tiers = providers.cached(con, movie_id)[0]
    services = [r for r in con.execute("SELECT key, name, status, tv_source FROM services ORDER BY rowid")
                if clean(r["tv_source"])]
    found = []

    def add(row, owned=False):
        if all(f["service"] != row["key"] for f in found):
            found.append({"service": row["key"], "name": row["name"], "owned": owned,
                          "tv_source": clean(row["tv_source"])})

    if digital:
        for r in services:
            if r["key"] == ha.FANDANGO:
                add(r, owned=True)
    for r in services:
        if r["key"] in tiers["flatrate"] and r["status"] == "subscribed":
            add(r)
    for r in services:
        if (r["key"] in tiers["free"] or r["key"] in tiers["ads"]) and r["status"] != "ignore":
            add(r)
    return found


def _disc(con, movie_id, physical):
    """{"label": the where-to-watch line of the owned copy} when Matinee holds a disc, else None."""
    if not physical:
        return None
    line = providers._owned_line(con, movie_id)
    return {"label": line["label"] if line else "On disc"}


def _parts(con, movie_id):
    physical, digital = movies.copy_kinds(con, movie_id)
    return _stream_options(con, movie_id, digital), _disc(con, movie_id, physical)


def options(con, movie_id):
    """None when Play on TV is off. Otherwise {"stream": [{"service", "name", "owned"}], "disc": {"label"} | None,
    "auto": "stream" | "disc" | None}: what can play the movie, and what the main page's Play would start."""
    if not enabled():
        return None
    stream, disc = _parts(con, movie_id)
    return {"stream": [{k: s[k] for k in ("service", "name", "owned")} for s in stream], "disc": disc,
            "auto": "stream" if stream else "disc" if disc else None}


# ------------------------------------------------------------------------------------------------ pressing Play (§5.2)
def _body(data):
    """(mode, service or None) from the request body, or a 400."""
    if not isinstance(data, dict):
        abort(make_err(400, 'Send a JSON body like {"mode": "auto"}.'))
    mode, service = data.get("mode"), data.get("service")
    if mode not in MODES:
        abort(make_err(400, "mode must be one of " + ", ".join(MODES) + "."))
    if service is not None and (mode != "stream" or not isinstance(service, str) or not service):
        abort(make_err(400, "service is a service key, and only goes with mode stream."))
    return mode, service


def _target(con, movie_id, title, mode, service):
    """(mode, source, name, label) for what to start, or a 409 naming what the movie can't do."""
    stream, disc = _parts(con, movie_id)
    if mode == "auto":
        mode = "stream" if stream or disc is None else "disc"   # with nothing at all, the stream sentence
    if mode == "disc":
        if disc is None:
            abort(make_err(409, f"We don't own {title} on disc."))
        return "disc", ha.RECEIVER, None, disc["label"]
    if service is not None:
        stream = [s for s in stream if s["service"] == service]
        if not stream:
            abort(make_err(409, f"{title} can't be played on that service."))
    if not stream:
        abort(make_err(409, f"{title} isn't on a service we have."))
    return "stream", stream[0]["tv_source"], stream[0]["name"], None


def _confirm(con, viewing_id, source, started_at):
    """True when the TV's remembered state is on and on `source` (case ignored): then no TV event is coming to open the
    night's session, so one is opened here unless one is open already. The write lock is taken first, as viewings does,
    so two taps at once can't open two sessions."""
    if not con.in_transaction:
        con.execute("BEGIN IMMEDIATE")
    try:
        tv = ha.tv_state(con)
        there = ha.tv_is_on(tv["state"]) and tv["source"] is not None and tv["source"].casefold() == source.casefold()
        if there and con.execute("SELECT 1 FROM sessions WHERE viewing_id=? AND ended_at IS NULL",
                                 (viewing_id,)).fetchone() is None:
            viewings.open_session(con, viewing_id, source, started_at)
        con.commit()
    except BaseException:
        con.rollback()
        raise
    return there


def start(con, movie_id, data, now=None):
    """Play the movie on the Family Room TV. `data` is the request body {"mode": "auto" | "stream" | "disc", "service"?}.
    The movie is marked for tonight first (and stays marked if Home Assistant can't be reached), then Home Assistant is
    asked and waited for. Returns {"ok", "mode", "source", "name", "label", "viewing", "tv", "sent_at", "confirmed"}:
    `sent_at` is the ISO time taken before the request (the page ignores TV events older than it), `confirmed` that the
    TV was already on that input. 503 when Play is off, 404 for an unknown movie, 400 for a bad body, 409 for something
    the movie can't do, 502 when Home Assistant doesn't take the request."""
    if not enabled():
        abort(make_err(503, "Play on TV isn't set up."))
    title = movies.get_row(con, movie_id)["title"]
    mode, service = _body(data)
    mode, source, name, label = _target(con, movie_id, title, mode, service)
    viewing_id = viewings.watch_tonight(con, movie_id)
    now = now or dt.datetime.now(dt.timezone.utc)
    sent_at = now.isoformat(timespec="milliseconds")
    try:
        ha.post_play({"event": "wonderful_play", "mode": mode, "source": source, "title": title})
    except ha.PlayFailed:
        abort(make_err(502, f"Couldn't reach the TV. {title} is on for tonight; use the remote."))
    confirmed = _confirm(con, viewing_id, source, now)
    return {"ok": True, "mode": mode, "source": source, "name": name, "label": label,
            "viewing": viewings.out(con, viewing_id), "tv": ha.tv_state(con), "sent_at": sent_at, "confirmed": confirmed}
