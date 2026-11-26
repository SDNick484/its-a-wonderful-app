"""Home Assistant (spec §8.5, §10.2). Outbound: the Family Room movie log. Every finished viewing, owned or not, is
posted to HA_WEBHOOK_URL (the same webhook Matinee uses) with Matinee's ha_payload() shape and event name plus
`"source": "wonderful"`, so the automation that keeps the dashboard's movie log takes it unchanged. Inbound: the Family
Room TV's events on /hooks/tv (handle_tv_event; docs/home-assistant.md has the automation). Route-free; no Flask object
here (see CLAUDE.md).

The webhook id in HA_WEBHOOK_URL is its only credential, so the URL is never logged: a failure is one warning naming the
host and the kind of failure (an HTTP status or an exception class), never the URL or str(exc), which can echo it."""
import datetime as dt, json, logging, threading, urllib.error, urllib.parse, urllib.request

from flask import abort, current_app, has_app_context

import movies
import providers
import viewings
from common import clean, host_tz, make_err
from settings import HA_WEBHOOK_URL, UA

TIMEOUT = 5
EVENT = "matinee_watch_logged"   # Matinee's event name: the HA automation listens for this one


def _host(url):
    """The webhook URL's host, for log lines: the rest of the URL is the credential."""
    try:
        return urllib.parse.urlsplit(url).hostname or "?"
    except ValueError:
        return "?"


def _logger():
    """The Flask app's logger when there is an app context (the thread has none, so it is taken before it starts)."""
    return current_app.logger if has_app_context() else logging.getLogger("wonderful")


def _post(url, payload, log):
    """POST `payload` as JSON. Runs on a daemon thread and never raises; a failure is one host-only warning."""
    host = _host(url)
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            status = getattr(resp, "status", 200)
        if not 200 <= status < 300:
            log.warning("Home Assistant webhook (host %s) answered HTTP %s", host, status)
    except urllib.error.HTTPError as e:
        log.warning("Home Assistant webhook (host %s) answered HTTP %s", host, e.code)
        try:
            e.close()
        except Exception:  # noqa: BLE001 — nothing to read; the warning is already out
            pass
    except Exception as e:  # noqa: BLE001 — fire and forget: whatever goes wrong is a warning, never the caller's problem
        log.warning("Home Assistant webhook (host %s) failed: %s", host, type(e).__name__)


def post_watch_logged(payload):
    """Tell Home Assistant a movie was watched: fire and forget on a daemon thread named "ha-webhook". Does nothing
    when HA_WEBHOOK_URL is empty. `payload` is built by the caller (viewings.ha_payload) on its own connection."""
    url = HA_WEBHOOK_URL
    if not url:
        return
    log = _logger()
    try:
        threading.Thread(target=_post, args=(url, dict(payload), log), daemon=True, name="ha-webhook").start()
    except Exception as e:  # noqa: BLE001 — e.g. no thread to be had: still never the caller's problem
        log.warning("Home Assistant webhook (host %s) not sent: %s", _host(url), type(e).__name__)


# ------------------------------------------------------------------------------------------------ inbound: the TV (§10.2)
RECEIVER = "AV Receiver"          # the TV input a disc comes in on (through the receiver): counts for owned discs only
FANDANGO = "fandango_at_home"     # the service key (data/services.json) where our digital copies play
ON_STATES = ("on", "playing", "paused", "idle", "buffering")   # media_player states that mean the TV is on
OFF_STATES = ("off", "standby")
NO_SOURCE = ("", "none", "unknown", "unavailable")   # a template renders a missing attribute as "None"
LAST_AT = "tv_last_event_at"      # meta key: the `at` of the newest TV event taken, so an older one is ignored


def _parse_at(value):
    """An aware datetime from the event's `at` (ISO 8601; no offset = the host's TZ); None when it can't be read."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        when = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        tz = host_tz()
        when = when.replace(tzinfo=tz) if tz else when.astimezone()
    return when


def parse_tv_event(data):
    """The /hooks/tv body {"state", "source", "at"} -> (state, source or None, at). `state` is required (a string);
    `source` may be missing or null, and "None"/"unknown"/"unavailable" read as no source; `at` defaults to now. 400 for
    a body that isn't an object, a missing state, or an `at` that isn't an ISO time."""
    if not isinstance(data, dict):
        abort(make_err(400, 'Send a JSON body like {"state": "on", "source": "Disney+", "at": "2026-12-12T19:31:04-08:00"}.'))
    state = data.get("state")
    if not isinstance(state, str) or not state.strip():
        abort(make_err(400, "state is required (the TV's media_player state, e.g. on or off)."))
    source = data.get("source")
    if source is not None and not isinstance(source, str):
        abort(make_err(400, "source must be the TV's input name or null."))
    source = clean(source)
    if source is not None and source.casefold() in NO_SOURCE:
        source = None
    raw_at = data.get("at")
    if raw_at is None or raw_at == "":
        at = dt.datetime.now(dt.timezone.utc)
    else:
        at = _parse_at(raw_at)
        if at is None:
            abort(make_err(400, "at must be an ISO time like 2026-12-12T19:31:04-08:00."))
    return state.strip().lower(), source, at


def sources_for(con, movie_id):
    """The TV inputs that can play the movie, casefolded: the tv_source of every service TMDB lists it on (any tier, any
    status: the cache, no TMDB call), plus the receiver input when Matinee holds a disc, plus Fandango at Home's input
    when it holds a digital copy (which plays there whatever the service's status)."""
    physical, digital = movies.copy_kinds(con, movie_id)
    tiers = providers.cached(con, movie_id)[0]
    keys = {k for names in tiers.values() for k in names}
    if digital:
        keys.add(FANDANGO)
    found = set()
    if keys:
        marks = ",".join("?" * len(keys))
        for r in con.execute(f"SELECT tv_source FROM services WHERE key IN ({marks})", sorted(keys)):
            if clean(r["tv_source"]):
                found.add(clean(r["tv_source"]).casefold())
    if physical:
        found.add(RECEIVER.casefold())
    return found


def _decide(con, state, source, at):
    """The rules of spec §10.2 for one event that is in order. Writes, no commit."""
    viewings.close_overdue(con, at)
    live = con.execute("SELECT id, movie_id FROM viewings WHERE status IN ('tonight','watching')").fetchall()
    if not live:
        return {"action": "ignored", "reason": "no viewing tonight"}
    if len(live) > 1:
        return {"action": "ignored", "reason": "more than one viewing tonight"}
    viewing = live[0]
    session = con.execute("SELECT id FROM sessions WHERE viewing_id=? AND ended_at IS NULL ORDER BY id DESC LIMIT 1",
                          (viewing["id"],)).fetchone()
    if state in OFF_STATES:
        if session is None:
            return {"action": "ignored", "reason": "TV off with no session open"}
        viewings.close_session(con, session["id"], at, "tv_off")
        return {"action": "closed", "reason": "tv_off"}
    if state not in ON_STATES:
        return {"action": "ignored", "reason": f"state {state!r} says nothing"}
    if source is None:
        return {"action": "ignored", "reason": "no source"}
    if source.casefold() in sources_for(con, viewing["movie_id"]):
        if session is not None:
            return {"action": "ignored", "reason": "session already open"}
        viewings.open_session(con, viewing["id"], source, at)
        return {"action": "opened", "reason": f"on {source}"}
    if session is None:
        return {"action": "ignored", "reason": f"{source} can't play it"}
    viewings.close_session(con, session["id"], at, "source_changed")
    return {"action": "closed", "reason": "source_changed"}


def handle_tv_event(con, state, source, at):
    """One Family Room TV event from Home Assistant (spec §10.2) -> {"action": "opened" | "closed" | "ignored",
    "reason"}. Applied only when exactly one viewing is `tonight` or `watching`:
      on (or playing, idle...) on an input that can play it (sources_for)   open a session; the viewing is `watching`
      on, on any other input (YouTube, Live TV) with a session open          close it, `source_changed`
      off (or standby) with a session open                                   close it, `tv_off`
    A session open past runtime + 60 min is closed at that limit first (`timeout`). Everything else is an idempotent
    no-op (Review Focus 3): an event no newer than the last one taken (a duplicate, or out of order by `at`), "on" with
    a session already open, "off" with none, no source, a state such as unavailable. Closing asks Did you finish?
    with the guess (viewings.close_session)."""
    if not con.in_transaction:
        con.execute("BEGIN IMMEDIATE")   # two events at once: the second waits and then sees the first
    try:
        row = con.execute("SELECT v FROM meta WHERE k=?", (LAST_AT,)).fetchone()
        last = _parse_at(row["v"]) if row else None
        if last is not None and at <= last:
            result = {"action": "ignored", "reason": "duplicate" if at == last else "out of order"}
        else:
            con.execute("INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                        (LAST_AT, at.isoformat()))
            result = _decide(con, state, source, at)
        con.commit()
    except BaseException:
        con.rollback()
        raise
    return result
