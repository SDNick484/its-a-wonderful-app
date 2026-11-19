"""The family (spec §8.4): the app's own `people` table, so rating works when Matinee is down. It mirrors Matinee's
people by name (kind, color and order are copied; "Sync people from Matinee" and the first run do it), and a person can
also be added here (a grandparent visiting): they rate normally and are dropped from the attendee list sent to Matinee.
Route-free: a bad request aborts with common.make_err, and a Matinee failure raises matinee.Unavailable or
matinee.Rejected for app.py to answer. No Flask object here (see CLAUDE.md)."""
import sqlite3, time

from flask import abort

import matinee
from common import clean, make_err

KINDS = ("adult", "kid")
COLORS = ("green", "blue", "red", "pink", "purple")   # Matinee's palette keys; the page maps each to a --p-user colour
NAME_MAX = 40
FIRST_RUN_BACKOFF = 60                                # seconds a page load leaves Matinee alone after the first-run sync failed
_first_run_failed_at = None                           # time.monotonic() of that failure (this worker only)


def _out(row):
    return {"id": row["id"], "name": row["name"], "kind": row["kind"], "color": row["color"],
            "sort_order": row["sort_order"], "active": bool(row["active"])}


def list_people(con):
    """The active people in order: [{id, name, kind, color, sort_order, active}]."""
    return [_out(r) for r in con.execute("SELECT * FROM people WHERE active=1 ORDER BY sort_order, id")]


def get_row(con, person_id):
    """The people row, or a 404."""
    row = con.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    if row is None:
        abort(make_err(404, "That person isn't on our list."))
    return row


def add_person(con, data):
    """POST /api/people {name, kind?, color?}: a person who exists only here. `kind` defaults to 'adult' and `color` to
    the first palette colour nobody has yet (then the first one). 400 for a blank or long name, an unknown kind or
    colour; 409 when the name is taken (names are unique, ignoring case). Returns the new person."""
    if not isinstance(data, dict):
        abort(make_err(400, "Send a JSON body with a name."))
    name = clean(data.get("name") if isinstance(data.get("name"), str) else None)
    if not name:
        abort(make_err(400, "Type a name."))
    if len(name) > NAME_MAX:
        abort(make_err(400, f"That name is too long (most {NAME_MAX} characters)."))
    kind = data.get("kind") or "adult"
    if kind not in KINDS:
        abort(make_err(400, "kind must be 'adult' or 'kid'."))
    color = data.get("color")
    if color is None or color == "":
        used = {r["color"] for r in con.execute("SELECT color FROM people")}
        color = next((c for c in COLORS if c not in used), COLORS[0])
    if color not in COLORS:
        abort(make_err(400, "color must be one of " + ", ".join(COLORS) + "."))
    if con.execute("SELECT 1 FROM people WHERE name=?", (name,)).fetchone():
        abort(make_err(409, f"{name} is already on our list."))
    order = con.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM people").fetchone()[0]
    try:
        cur = con.execute("INSERT INTO people (name, kind, color, sort_order) VALUES (?,?,?,?)", (name, kind, color, order))
        con.commit()
    except sqlite3.IntegrityError:   # two people tapped Add at once
        con.rollback()
        abort(make_err(409, f"{name} is already on our list."))
    return _out(get_row(con, cur.lastrowid))


def sync_from_matinee(con, client):
    """Copy Matinee's people by name (spec §8.4): a new name is added, a known one (any case) has its kind, colour and
    order brought in line. Returns {"added": n, "updated": n}; `updated` counts only people whose row changed, so a
    second run with nothing new is {"added": 0, "updated": 0}. People who exist only here are left alone. A Matinee
    entry with no name or an unknown kind is skipped, and an unknown colour becomes the first palette colour.
    matinee.Unavailable and matinee.Rejected propagate: nothing is changed then."""
    added = updated = 0
    for p in client.people():
        name = clean(p.get("name") if isinstance(p.get("name"), str) else None)
        kind, color, order = p.get("kind"), p.get("color"), p.get("sort_order")
        if not name or len(name) > NAME_MAX or kind not in KINDS:
            continue
        if color not in COLORS:
            color = COLORS[0]
        order = order if isinstance(order, int) and not isinstance(order, bool) else 0
        row = con.execute("SELECT * FROM people WHERE name=?", (name,)).fetchone()
        if row is None:
            con.execute("INSERT INTO people (name, kind, color, sort_order) VALUES (?,?,?,?)", (name, kind, color, order))
            added += 1
        elif (row["kind"], row["color"], row["sort_order"]) != (kind, color, order):
            con.execute("UPDATE people SET kind=?, color=?, sort_order=? WHERE id=?", (kind, color, order, row["id"]))
            updated += 1
    con.commit()
    return {"added": added, "updated": updated}


def first_run_sync(con):
    """Called when the page asks for people and there are none: copy them from Matinee once, quietly. Does nothing when
    Matinee has no key, there are people already, or the last try failed under a minute ago; a failure is not an error
    (the person can add people by hand or tap the sync button later)."""
    global _first_run_failed_at
    if not matinee.configured() or con.execute("SELECT 1 FROM people LIMIT 1").fetchone():
        return
    if _first_run_failed_at is not None and time.monotonic() - _first_run_failed_at < FIRST_RUN_BACKOFF:
        return
    try:
        sync_from_matinee(con, matinee.client())
        _first_run_failed_at = None
    except (matinee.Unavailable, matinee.Rejected):
        _first_run_failed_at = time.monotonic()
