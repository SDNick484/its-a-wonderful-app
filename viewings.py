"""Viewings and Continue Watching (spec §10.1, §10.3), and what finishing a movie tells Matinee (§8.3) and Home
Assistant (§8.5). Route-free: a bad request aborts with common.make_err. No Flask object here (see CLAUDE.md).

A viewing is one attempt at watching a movie, possibly over several nights:

  tonight    picked with Watch tonight (or Keep watching tonight). Only one viewing is ever `tonight` (or `watching`):
             picking another moves the old one back to `paused`, or deletes it when it has no watched time. One still
             `tonight` at 4 am local the morning after it was picked reverts the same way (expire_stale)
  watching   the TV is on it: a session is open (ha.handle_tv_event opens and closes sessions, spec §10.2)
  paused     in Continue Watching, waiting for another night. A TV session that ended leaves it here with a guess
             (close_session) and a "Did you finish?" question (pending_prompt) until someone answers
  finished   done: finished_on is set, Matinee gets one watch (owned movies only), Home Assistant one movie-log event
  abandoned  "We gave up on it": off the row, nothing sent anywhere

Finishing is the one step with outside effects, and they must happen once: the move to `finished` is a single UPDATE
guarded by the status, so of two taps (or a tap and a retry) only one wins and the other is a 409. The winner posts
the Matinee watch (never "live": this app tells Home Assistant itself), then hands the movie-log event to ha.py.

Matinee down, slow or refusing the key never fails a finish (Review Focus 1): the viewing is finished all the same and
keeps a "not synced" mark, a `meta` row `matinee_watch_owed:<viewing id>` (schema v1 has no column for it, and the
schema stays at v1), which the nightly ops/wonderful-refresh clears by sending the watch (retry_watches). Home
Assistant is told at the finish itself, never again on a retry.

A session is one evening's TV time. Home Assistant's events open and close it (ha.handle_tv_event); one left open is
closed at runtime + 60 min (close_overdue, `timeout`), and Watch tonight, We finished or We gave up close one that is
still open (`manual`), never counting past that same limit. A session that ends on a TV event or the timeout adds its
length to watched_seconds and sets the guess (finished at 85 % of the runtime; none when the runtime is unknown) and a
`meta` row `finish_ask:<viewing id>`, so the question is asked even with no guess (Review Focus 2). Answering it in
any way (Not yet, Keep watching tonight, Yes, We gave up) clears both."""
import datetime as dt

from flask import abort, current_app, has_app_context

import ha
import images
import matinee
import movies
from common import clean, host_tz, make_err, now_iso, today

OPEN = ("tonight", "watching", "paused")
NIGHT_ENDS = 4                    # a night's picks expire at 4 am local the next morning (spec §10.1)
OWED = "matinee_watch_owed:"      # meta key prefix: a finished viewing whose Matinee watch is not sent yet
ASK = "finish_ask:"               # meta key prefix: a TV session ended, "Did you finish?" not answered yet
FINISHED_SHARE = 0.85             # watched this much of the runtime: the guess is "finished" (spec §10.2)
OVERTIME = dt.timedelta(minutes=60)          # a session open longer than runtime + this is closed (spec §10.2)
UNKNOWN_RUNTIME = dt.timedelta(minutes=180)  # ... and with no runtime, open longer than this + OVERTIME (4 hours)
SOURCE = "wonderful"              # the `source` key of the movie-log event, so HA can tell it from Matinee's own


# ------------------------------------------------------------------------------------------------ helpers
def _log(msg, *args):
    if has_app_context():
        current_app.logger.warning(msg, *args)


def _stamp(value):
    """An aware datetime from a stored timestamp: now_iso()'s "…Z", SQLite's "YYYY-MM-DD HH:MM:SS" (UTC) or an ISO
    time with an offset (what Home Assistant sends). None when it can't be read."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace(" ", "T", 1)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        when = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def _local(when):
    """`when` (aware) on the host's clock (TZ)."""
    tz = host_tz()
    return when.astimezone(tz) if tz else when.astimezone()


def get_row(con, viewing_id):
    """The viewings row, or a 404."""
    row = con.execute("SELECT * FROM viewings WHERE id=?", (viewing_id,)).fetchone()
    if row is None:
        abort(make_err(404, "There's no such viewing."))
    return row


def _person_ids(con, person_ids):
    """None -> every active person (in order). Otherwise a list of known person ids (duplicates dropped), or a 400."""
    if person_ids is None:
        return [r["id"] for r in con.execute("SELECT id FROM people WHERE active=1 ORDER BY sort_order, id")]
    if not isinstance(person_ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in person_ids):
        abort(make_err(400, "people must be a list of person ids."))
    ids = list(dict.fromkeys(person_ids))
    known = {r["id"] for r in con.execute(f"SELECT id FROM people WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else set()
    if set(ids) - known:
        abort(make_err(400, "That person isn't on our list."))
    return ids


def _utc_iso(when):
    """An aware datetime as a *_at column value, like now_iso(): 2026-12-13T03:31:04Z."""
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _deadline(began, runtime_min):
    """When a session that began at `began` is closed by the timeout: runtime + 60 min (4 hours with no runtime)."""
    length = dt.timedelta(minutes=runtime_min) if runtime_min and runtime_min > 0 else UNKNOWN_RUNTIME
    return began + length + OVERTIME


def _runtime(con, viewing_id):
    row = con.execute("SELECT m.runtime_min FROM viewings v JOIN movies m ON m.id = v.movie_id WHERE v.id=?",
                      (viewing_id,)).fetchone()
    return row["runtime_min"] if row else None


def _close(con, session, viewing_id, ended_at, reason):
    """End one session at `ended_at` (aware) and add its length (never negative) to watched_seconds. No commit."""
    began = _stamp(session["started_at"])
    seconds = max(0, int((ended_at - began).total_seconds())) if began else 0
    con.execute("UPDATE sessions SET ended_at=?, end_reason=? WHERE id=?", (_utc_iso(ended_at), reason, session["id"]))
    con.execute("UPDATE viewings SET watched_seconds = watched_seconds + ? WHERE id=?", (seconds, viewing_id))


def _end_sessions(con, viewing_id, reason):
    """Close the viewing's open sessions now (end_reason `reason`), adding their length to watched_seconds; one already
    past its timeout ends at that limit instead (`timeout`), so a TV that never said "off" can't count all night. No
    guess: the caller is deciding what happens to the viewing. No commit."""
    now = dt.datetime.now(dt.timezone.utc)
    runtime = _runtime(con, viewing_id)
    for s in con.execute("SELECT id, started_at FROM sessions WHERE viewing_id=? AND ended_at IS NULL", (viewing_id,)).fetchall():
        began = _stamp(s["started_at"])
        limit = _deadline(began, runtime) if began else None
        if limit is not None and now >= limit:
            _close(con, s, viewing_id, limit, "timeout")
        else:
            _close(con, s, viewing_id, now, reason)


def _answered(con, viewing_id):
    """The Did you finish? question for this viewing is settled (or moot): drop the guess and the ask. No commit."""
    con.execute("UPDATE viewings SET guess=NULL WHERE id=?", (viewing_id,))
    con.execute("DELETE FROM meta WHERE k=?", (f"{ASK}{viewing_id}",))


def guess_for(watched_seconds, runtime_min):
    """"finished" when watched_seconds >= 85 % of the runtime, else "not_finished"; None when the runtime is unknown
    (spec §10.2, Review Focus 2: the prompt then has nothing preselected)."""
    if not runtime_min or runtime_min <= 0:
        return None
    return "finished" if (watched_seconds or 0) >= FINISHED_SHARE * runtime_min * 60 else "not_finished"


def close_session(con, session_id, ended_at, reason):
    """End a TV session at `ended_at` (an aware datetime) with end_reason `reason` ('tv_off', 'source_changed',
    'timeout'): its length goes into the viewing's watched_seconds, the viewing goes back to `paused` with a guess
    (guess_for) and the Did you finish? question is asked (pending_prompt). A session that already ended is left
    alone. No commit: the caller holds the transaction (ha.handle_tv_event, close_overdue's callers)."""
    s = con.execute("SELECT id, viewing_id, started_at, ended_at FROM sessions WHERE id=?", (session_id,)).fetchone()
    if s is None or s["ended_at"] is not None:
        return
    viewing_id = s["viewing_id"]
    _close(con, s, viewing_id, ended_at, reason)
    seconds = con.execute("SELECT watched_seconds FROM viewings WHERE id=?", (viewing_id,)).fetchone()[0]
    con.execute("UPDATE viewings SET guess=?, status=CASE WHEN status IN ('tonight','watching') THEN 'paused' ELSE status END,"
                " updated_at=? WHERE id=?", (guess_for(seconds, _runtime(con, viewing_id)), now_iso(), viewing_id))
    con.execute("INSERT OR IGNORE INTO meta (k, v) VALUES (?, ?)", (f"{ASK}{viewing_id}", now_iso()))


def close_overdue(con, now):
    """Close every session open longer than its movie's runtime + 60 min (4 hours with no runtime) at that limit,
    `timeout` (spec §10.2). `now` is an aware datetime: a TV event's `at`, or the clock. Returns how many. No commit."""
    done = 0
    for s in con.execute("SELECT s.id, s.viewing_id, s.started_at, m.runtime_min FROM sessions s"
                         " JOIN viewings v ON v.id = s.viewing_id JOIN movies m ON m.id = v.movie_id"
                         " WHERE s.ended_at IS NULL").fetchall():
        began = _stamp(s["started_at"])
        if began is None:
            continue
        limit = _deadline(began, s["runtime_min"])
        if now >= limit:
            close_session(con, s["id"], limit, "timeout")
            done += 1
    return done


def open_session(con, viewing_id, tv_source, started_at):
    """Start a TV session for the viewing at `started_at` (aware) on input `tv_source`; the viewing is `watching`.
    Returns the session id. No commit."""
    session_id = con.execute("INSERT INTO sessions (viewing_id, tv_source, started_at) VALUES (?,?,?)",
                             (viewing_id, tv_source, _utc_iso(started_at))).lastrowid
    con.execute("UPDATE viewings SET status='watching', updated_at=? WHERE id=?", (now_iso(), viewing_id))
    return session_id


def _set_aside(con, viewing_id):
    """Move a viewing out of tonight: back to `paused`, or deleted when it has no watched time. No commit."""
    _end_sessions(con, viewing_id, "manual")
    seconds = con.execute("SELECT watched_seconds FROM viewings WHERE id=?", (viewing_id,)).fetchone()[0]
    if seconds:
        con.execute("UPDATE viewings SET status='paused', updated_at=? WHERE id=?", (now_iso(), viewing_id))
    else:
        _answered(con, viewing_id)
        con.execute("DELETE FROM viewings WHERE id=?", (viewing_id,))


def _only_tonight(con, viewing_id):
    """Every other `tonight` or `watching` viewing is set aside: only one is ever tonight. No commit."""
    for r in con.execute("SELECT id FROM viewings WHERE status IN ('tonight','watching') AND id<>?", (viewing_id,)).fetchall():
        _set_aside(con, r["id"])


def _begin(con):
    """Take the write lock before reading what we are about to change, so two taps at once can't both win."""
    if not con.in_transaction:
        con.execute("BEGIN IMMEDIATE")


# ------------------------------------------------------------------------------------------------ the row (spec §10.1)
def watch_tonight(con, movie_id, person_ids=None):
    """Watch tonight: the movie's open viewing (tonight, watching or paused) becomes tonight again, or a new one is
    made with `person_ids` (None: every active person). Any other viewing that was tonight is set aside. Returns the
    viewing's id. 404 for an unknown movie, 400 for a bad people list."""
    movies.get_row(con, movie_id)
    ids = _person_ids(con, person_ids)
    _begin(con)
    try:
        row = con.execute("SELECT id, status FROM viewings WHERE movie_id=? AND status IN ('tonight','watching','paused')"
                          " ORDER BY id DESC LIMIT 1", (movie_id,)).fetchone()
        if row is None:
            viewing_id = con.execute("INSERT INTO viewings (movie_id, started_on, status, updated_at) VALUES (?,?,?,?)",
                                     (movie_id, today().isoformat(), "tonight", now_iso())).lastrowid
            con.executemany("INSERT INTO viewing_people (viewing_id, person_id) VALUES (?,?)", [(viewing_id, p) for p in ids])
        else:
            viewing_id = row["id"]
            if row["status"] == "paused":
                con.execute("UPDATE viewings SET status='tonight', updated_at=? WHERE id=?", (now_iso(), viewing_id))
                _answered(con, viewing_id)
            if person_ids is not None:
                con.execute("DELETE FROM viewing_people WHERE viewing_id=?", (viewing_id,))
                con.executemany("INSERT INTO viewing_people (viewing_id, person_id) VALUES (?,?)", [(viewing_id, p) for p in ids])
        _only_tonight(con, viewing_id)
        con.commit()
    except BaseException:
        con.rollback()
        raise
    return viewing_id


def _must_be_open(row):
    if row["status"] == "finished":
        abort(make_err(409, "That one is already finished."))
    if row["status"] == "abandoned":
        abort(make_err(409, "We gave up on that one."))


def keep_watching(con, viewing_id):
    """Keep watching tonight: a paused viewing becomes tonight again (any other tonight is set aside), so the TV's
    events count for it. Tonight or watching already: nothing changes. 409 when it is finished or abandoned."""
    _must_be_open(get_row(con, viewing_id))
    _begin(con)
    try:
        if con.execute("UPDATE viewings SET status='tonight', updated_at=? WHERE id=? AND status='paused'",
                       (now_iso(), viewing_id)).rowcount:
            _answered(con, viewing_id)
        _only_tonight(con, viewing_id)
        con.commit()
    except BaseException:
        con.rollback()
        raise


def not_yet(con, viewing_id):
    """"Not yet" in the Did you finish? sheet: the guess is answered, the viewing stays in Continue Watching as it is.
    409 when it is finished or abandoned."""
    _must_be_open(get_row(con, viewing_id))
    _answered(con, viewing_id)
    con.commit()


def abandon(con, viewing_id):
    """"We gave up on it": the viewing is `abandoned` and leaves the row; nothing is sent anywhere. Doing it twice is
    fine; 409 when it was finished."""
    row = get_row(con, viewing_id)
    if row["status"] == "finished":
        abort(make_err(409, "That one is already finished."))
    if row["status"] == "abandoned":
        return
    _end_sessions(con, viewing_id, "manual")
    con.execute("UPDATE viewings SET status='abandoned', updated_at=? WHERE id=?", (now_iso(), viewing_id))
    _answered(con, viewing_id)
    con.commit()


def _night_deadline(picked):
    """4 am local on the morning after the night `picked` (aware) belongs to; a pick at 1 am belongs to the night before."""
    local = _local(picked)
    night = (local - dt.timedelta(hours=NIGHT_ENDS)).date()
    morning = dt.datetime.combine(night + dt.timedelta(days=1), dt.time(NIGHT_ENDS))
    return morning.replace(tzinfo=local.tzinfo) if host_tz() else morning.astimezone()


def expire_stale(con, now=None):
    """A viewing still `tonight` (picked, the TV never on it) at 4 am local the next morning is set aside like a second
    pick would (paused, or deleted with no watched time), so it can't block the TV detection. A TV session open past
    runtime + 60 min is closed at that limit first (close_overdue), which asks Did you finish?. `now` is an aware
    datetime (default: now). Returns how many viewings were set aside."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=host_tz()) if host_tz() else now.astimezone()
    closed = close_overdue(con, now)
    done = 0
    for r in con.execute("SELECT id, updated_at FROM viewings WHERE status='tonight'").fetchall():
        picked = _stamp(r["updated_at"])
        if picked is not None and now >= _night_deadline(picked):
            _set_aside(con, r["id"])
            done += 1
    if done or closed:
        con.commit()
    return done


def progress_label(watched_seconds, runtime_min):
    """"Just started" (< 25 %), "About halfway" (25-75 %) or "Almost done" (> 75 %) of the runtime; None when the
    runtime is unknown (spec §10.3)."""
    if not runtime_min or runtime_min <= 0:
        return None
    part = (watched_seconds or 0) / (runtime_min * 60)
    if part < 0.25:
        return "Just started"
    return "About halfway" if part <= 0.75 else "Almost done"


# ------------------------------------------------------------------------------------------------ finishing (§10.3, §8.3, §8.5)
def _last_session_day(con, viewing_id):
    row = con.execute("SELECT started_at FROM sessions WHERE viewing_id=? ORDER BY started_at DESC, id DESC LIMIT 1",
                      (viewing_id,)).fetchone()
    when = _stamp(row["started_at"]) if row else None
    return _local(when).date() if when else None


def parse_finished_on(value):
    """A finish date from a request: None or "" -> None (the last session's date, or today); "YYYY-MM-DD" -> a date,
    not in the future. 400 otherwise."""
    if value is None or value == "":
        return None
    try:
        day = dt.date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        day = None
    if day is None:
        abort(make_err(400, "finished_on must be a date like 2026-12-12."))
    if day > today():
        abort(make_err(400, "finished_on can't be in the future."))
    return day


def finish(con, viewing_id, finished_on=None):
    """We finished: the viewing becomes `finished` on `finished_on` (default: the date of its last session, or today),
    then an owned movie's watch goes to Matinee and the movie-log event to Home Assistant, once each. 409 when it is
    already finished (a second tap sends nothing) or was abandoned. Matinee failing leaves the viewing finished with
    the watch owed (watch_pending)."""
    row = get_row(con, viewing_id)
    _must_be_open(row)
    day = finished_on or _last_session_day(con, viewing_id) or today()
    _end_sessions(con, viewing_id, "manual")
    cur = con.execute("UPDATE viewings SET status='finished', finished_on=?, guess=NULL, updated_at=?"
                      " WHERE id=? AND status IN ('tonight','watching','paused')", (day.isoformat(), now_iso(), viewing_id))
    if cur.rowcount != 1:   # someone else finished (or gave up on) it in the meantime: they did the sending
        con.rollback()
        _must_be_open(get_row(con, viewing_id))
        abort(make_err(409, "That one is already finished."))
    _answered(con, viewing_id)
    con.commit()
    send_watch(con, viewing_id)
    ha.post_watch_logged(ha_payload(con, viewing_id))


def _owed(con, viewing_id, on):
    if on:
        con.execute("INSERT OR IGNORE INTO meta (k, v) VALUES (?, ?)", (f"{OWED}{viewing_id}", now_iso()))
    else:
        con.execute("DELETE FROM meta WHERE k=?", (f"{OWED}{viewing_id}",))
    con.commit()


def watch_pending(con, viewing_id):
    """True when the viewing's Matinee watch is owed (Matinee couldn't take it yet): the "not synced" flag."""
    return con.execute("SELECT 1 FROM meta WHERE k=?", (f"{OWED}{viewing_id}",)).fetchone() is not None


def _attendees(con, viewing_id, api):
    """The viewing's people as Matinee spells them, in our order; names Matinee doesn't know (a visitor added here) are
    dropped (spec §8.3)."""
    known = {}
    for p in api.people():
        name = clean(p.get("name") if isinstance(p.get("name"), str) else None)
        if name:
            known.setdefault(name.casefold(), name)
    ours = [r["name"] for r in con.execute(
        "SELECT p.name FROM viewing_people vp JOIN people p ON p.id = vp.person_id WHERE vp.viewing_id=?"
        " ORDER BY p.sort_order, p.id", (viewing_id,))]
    return [known[n.casefold()] for n in ours if n.casefold() in known]


def send_watch(con, viewing_id):
    """Post the finished viewing's watch to Matinee when the movie is owned: dated finished_on, attendees by name, no
    "live" flag; the returned id goes in matinee_watch_id. Ownership is the last known answer (asked first when it was
    never asked). Returns True when Matinee has it or nothing is owed (not owned, a TV special, sync off); False when
    Matinee couldn't take it, and the watch stays owed for the nightly retry. Never raises for Matinee."""
    v = con.execute("SELECT * FROM viewings WHERE id=?", (viewing_id,)).fetchone()
    if v is None or v["status"] != "finished" or v["matinee_watch_id"] is not None:
        _owed(con, viewing_id, False)    # nothing to send (any more)
        return True
    if not matinee.configured():
        return True                      # sync off: nothing is owed, and a key added later doesn't send old watches
    movie = movies.get_row(con, v["movie_id"])
    if movie["tmdb_type"] != "movie":
        _owed(con, viewing_id, False)
        return True
    try:
        s = con.execute("SELECT * FROM matinee_sync WHERE movie_id=?", (v["movie_id"],)).fetchone()
        if s is None or s["checked_at"] is None:
            movies.check_ownership(con, v["movie_id"])
            s = con.execute("SELECT * FROM matinee_sync WHERE movie_id=?", (v["movie_id"],)).fetchone()
        if s is None or s["matinee_title_id"] is None:
            _owed(con, viewing_id, False)
            return True
        api = matinee.client()
        watch_id = api.log_watch(s["matinee_title_id"], v["finished_on"], _attendees(con, viewing_id, api))
    except (matinee.Unavailable, matinee.Rejected) as e:
        _owed(con, viewing_id, True)
        _log("Watch of %s on %s not sent to Matinee (sent again tonight): %s", movie["title"], v["finished_on"], e.message)
        return False
    con.execute("UPDATE viewings SET matinee_watch_id=? WHERE id=?", (watch_id, viewing_id))
    con.execute("DELETE FROM meta WHERE k=?", (f"{OWED}{viewing_id}",))
    con.commit()
    return True


def owed_ids(con):
    """The finished viewings whose Matinee watch is still owed, oldest first."""
    ids = []
    for r in con.execute("SELECT k FROM meta WHERE k LIKE ?", (OWED + "%",)):
        try:
            ids.append(int(r["k"][len(OWED):]))
        except ValueError:
            continue
    return sorted(ids)


def retry_watches(con):
    """The nightly retry: send every owed watch. Stops at the first failure (Matinee is down or refuses the key, so the
    rest would only wait out the timeout). Returns (sent, failed, left). Home Assistant is not told again."""
    ids = owed_ids(con)
    sent = 0
    for n, viewing_id in enumerate(ids):
        if not send_watch(con, viewing_id):
            return sent, 1, len(ids) - n - 1
        sent += 1
    return sent, 0, 0


def _formats(summary):
    """Matinee's copy summary "Blu-ray · Digital HD (Movies Anywhere)" -> ["Blu-ray", "Digital HD (Movies Anywhere)"]."""
    return [part.strip() for part in (summary or "").split("·") if part.strip()]


def ha_payload(con, viewing_id):
    """The movie-log event (spec §8.5): Matinee's ha_payload() shape and event name plus "source": "wonderful".
    `formats` and `location` come from the last known Matinee answer ([] and None for a movie that isn't owned);
    `title_id` is always None (Matinee's id would be misleading here). No people, nothing editor-only."""
    v = get_row(con, viewing_id)
    m = movies.get_row(con, v["movie_id"])
    s = con.execute("SELECT matinee_title_id, owned_summary, location_path FROM matinee_sync WHERE movie_id=?",
                    (v["movie_id"],)).fetchone()
    owned = s is not None and s["matinee_title_id"] is not None
    return {"event": ha.EVENT, "source": SOURCE, "title": m["title"], "year": m["year"], "runtime": m["runtime_min"],
            "certification": m["certification"], "formats": _formats(s["owned_summary"]) if owned else [],
            "location": s["location_path"] if owned else None, "watched_date": v["finished_on"], "title_id": None}


# ------------------------------------------------------------------------------------------------ what the page reads
def _people_of(con, viewing_id):
    return [r["person_id"] for r in con.execute(
        "SELECT vp.person_id FROM viewing_people vp JOIN people p ON p.id = vp.person_id WHERE vp.viewing_id=?"
        " ORDER BY p.sort_order, p.id", (viewing_id,))]


def out(con, viewing_id):
    """One viewing for the page: {viewing_id, movie_id, title, status, started_on, finished_on, watched_seconds,
    progress, people: [person ids], watch_pending}."""
    v = get_row(con, viewing_id)
    m = movies.get_row(con, v["movie_id"])
    return {"viewing_id": v["id"], "movie_id": m["id"], "title": m["title"], "status": v["status"],
            "started_on": v["started_on"], "finished_on": v["finished_on"], "watched_seconds": v["watched_seconds"],
            "progress": progress_label(v["watched_seconds"], m["runtime_min"]), "people": _people_of(con, v["id"]),
            "watch_pending": watch_pending(con, v["id"])}


def open_for_movie(con, movie_id):
    """The movie's open viewing (out()), or None: what the detail view's Watch tonight button needs."""
    row = con.execute("SELECT id FROM viewings WHERE movie_id=? AND status IN ('tonight','watching','paused')"
                      " ORDER BY id DESC LIMIT 1", (movie_id,)).fetchone()
    return out(con, row["id"]) if row else None


def continue_watching(con):
    """The Continue Watching row: open viewings, tonight's first, then the most recently touched. Each is out() plus
    the movie's year, runtime_min and poster_url."""
    rows = con.execute(
        "SELECT v.id, m.year, m.runtime_min, m.poster_path FROM viewings v JOIN movies m ON m.id = v.movie_id"
        " WHERE v.status IN ('tonight','watching','paused')"
        " ORDER BY CASE WHEN v.status='paused' THEN 1 ELSE 0 END, v.updated_at DESC, v.id DESC").fetchall()
    return [{**out(con, r["id"]), "year": r["year"], "runtime_min": r["runtime_min"],
             "poster_url": images.image_url(r["poster_path"])} for r in rows]


def pending_prompt(con):
    """{"viewing_id", "title", "guess", "movie_id", "people"} for the Did you finish? sheet: the most recent paused
    viewing whose TV session ended and nobody has answered yet; None when there is none. `guess` is "finished",
    "not_finished", or None when the runtime is unknown (nothing preselected)."""
    row = con.execute("SELECT v.id, v.guess, v.movie_id, m.title FROM viewings v JOIN movies m ON m.id = v.movie_id"
                      " WHERE v.status='paused' AND (v.guess IS NOT NULL OR EXISTS (SELECT 1 FROM meta WHERE k = ? || v.id))"
                      " ORDER BY v.updated_at DESC, v.id DESC LIMIT 1", (ASK,)).fetchone()
    if row is None:
        return None
    return {"viewing_id": row["id"], "title": row["title"], "guess": row["guess"], "movie_id": row["movie_id"],
            "people": _people_of(con, row["id"])}
