"""Keeping Matinee's household rating in step with the family's (spec §8.2). Route-free; no Flask object (see CLAUDE.md).

Who owns a movie's rating is matinee_sync.rating_owner. While it is 'matinee' the poster shows Matinee's rating. The
first person rating here flips it to 'wonderful': from then on the family mean shows, and an owned movie sends Matinee
that mean rounded to the nearest 0.5, half up (common.round_half_up). Matinee never gets null: with nobody rated there
is nothing to send. A movie Matinee doesn't own keeps its ratings here only.

The matinee_sync columns this module keeps:
  matinee_rating   the rating Matinee held when we last looked (a refresh, a read before a push), or what we wrote
  pushed_rating    the rating Matinee was last told, or settled at (it already agreed, or the family dismissed the
                   notice). A family rating whose rounded mean differs from it is owed to Matinee ("pending")
  conflict_rating  Matinee's rating when it changed behind our back: shown as a notice until the family chooses

A wrong push would overwrite what someone set in Matinee, so a rating is never written over a change we haven't seen:
a push after a rating change reads Matinee first, and a refresh compares Matinee's rating with the one it saw last
time. Either way, a change there is a conflict, never an overwrite. The one deliberate overwrite is taking over: the
first rating here replaces Matinee's (the spec's Elf scenario), as does the family's "Use ours".

Matinee down, slow or refusing the key never fails a rating (Review Focus 1): the push stays owed, the page says so,
the next tries wait out movies.MATINEE_BACKOFF, and the nightly ops/wonderful-refresh (movies.ownership_due lists every
movie with a push owed) reads Matinee again and sends it."""
import time

from flask import abort, current_app, has_app_context

import matinee
import movies
import ratings
from common import make_err, round_half_up

CHOICES = ("ours", "matinee", "dismiss")


def _row(con, movie_id):
    return con.execute("SELECT * FROM matinee_sync WHERE movie_id=?", (movie_id,)).fetchone()


def _log(msg, *args):
    if has_app_context():
        current_app.logger.warning(msg, *args)


def _owed(row, mean):
    """The rating owed to Matinee (the rounded mean), or None when nothing is: nobody has rated, Matinee owns the
    rating, the movie isn't owned, a conflict waits for the family, or Matinee was already told this value."""
    if row is None or mean is None or row["rating_owner"] != "wonderful" or row["matinee_title_id"] is None:
        return None
    if row["conflict_rating"] is not None:
        return None
    value = round_half_up(mean)
    return None if value == row["pushed_rating"] else value


def _backing_off():
    failed = movies._matinee_failed_at
    return failed is not None and time.monotonic() - failed < movies.MATINEE_BACKOFF


def _set(con, movie_id, **cols):
    con.execute(f"UPDATE matinee_sync SET {', '.join(f'{k}=?' for k in cols)} WHERE movie_id=?", (*cols.values(), movie_id))
    con.commit()


def _settle(con, movie_id, value):
    """Matinee holds `value`, which is ours: in step, nothing to send."""
    _set(con, movie_id, matinee_rating=value, pushed_rating=value, conflict_rating=None)


def _push(con, movie_id, value, last_seen=None, read_first=False):
    """Send `value` to Matinee. With read_first, Matinee is read first: when its rating is no longer `last_seen` (the
    one we saw last), someone changed it there, and that becomes the conflict notice (or settles, when it already is
    `value`) instead of being overwritten; when Matinee has no rating there is nothing to overwrite. A failure is logged
    and leaves the push owed. True when Matinee holds `value` afterwards."""
    title_id = _row(con, movie_id)["matinee_title_id"]
    api = matinee.client()
    try:
        if read_first:
            now = movies._user_rating(api.title(title_id))
            if now == value:
                _settle(con, movie_id, value)
                return True
            if now is not None and now != last_seen:
                _set(con, movie_id, matinee_rating=now, conflict_rating=now)
                return False
        api.set_rating(title_id, value)
    except (matinee.Unavailable, matinee.Rejected) as e:
        movies._matinee_failed_at = time.monotonic()
        _log("Rating %s for movie %s not sent to Matinee (sent again tonight): %s", value, movie_id, e.message)
        return False
    movies._matinee_failed_at = None
    _settle(con, movie_id, value)
    return True


def after_rating_change(con, movie_id):
    """Called after any change to a movie's person ratings (ratings.set). The first rating takes the movie's rating
    over from Matinee; an owned movie then sends Matinee the rounded mean (reading Matinee first, except when taking
    over). Never raises for Matinee: a failed push stays owed. Cleared ratings send nothing (never null)."""
    mean = ratings.family(con, movie_id)["mean"]
    if mean is None:
        return None
    row = _row(con, movie_id)
    taking_over = row is None or row["rating_owner"] != "wonderful"
    if taking_over:
        con.execute("INSERT INTO matinee_sync (movie_id, rating_owner) VALUES (?, 'wonderful') ON CONFLICT(movie_id)"
                    " DO UPDATE SET rating_owner='wonderful', conflict_rating=NULL", (movie_id,))
        con.commit()
        row = _row(con, movie_id)
    value = _owed(row, mean)
    if value is None or not matinee.configured() or _backing_off():
        return None
    _push(con, movie_id, value, last_seen=row["matinee_rating"], read_first=not taking_over)
    return None


def reconcile(con, movie_id, before=None):
    """After an ownership refresh wrote Matinee's answer (movies.check_ownership calls this). `before` is the
    matinee_sync row as it stood before that refresh (None when there was none). For a movie the family's rating owns:
      - newly owned (bought later, spec §8.2): Matinee unrated -> send ours; the same -> settle; different -> notice;
      - Matinee unchanged since we last looked -> send a push still owed (the nightly retry);
      - Matinee changed -> the notice (or settle when it now agrees; send ours when it was cleared there);
      - a notice already open follows Matinee's newest rating, and ends when Matinee comes round to ours.
    Matinee-owned, not owned or unrated movies are left alone."""
    row = _row(con, movie_id)
    if row is None or row["matinee_title_id"] is None or row["rating_owner"] != "wonderful":
        return None
    mean = ratings.family(con, movie_id)["mean"]
    if mean is None:
        return None
    value, now = round_half_up(mean), row["matinee_rating"]
    if row["conflict_rating"] is None and before is not None and before["matinee_title_id"] == row["matinee_title_id"] \
            and now == before["matinee_rating"]:
        if _owed(row, mean) is not None:
            _push(con, movie_id, value)
        return None
    if now is None:
        _set(con, movie_id, conflict_rating=None)
        _push(con, movie_id, value)
    elif now == value:
        _settle(con, movie_id, value)
    else:
        _set(con, movie_id, conflict_rating=now)
    return None


def resolve_conflict(con, movie_id, choice):
    """The family's answer to "Matinee says 7, we say 8.9" (spec §8.2): 'ours' sends the rounded mean over Matinee's;
    'matinee' hands the rating back to Matinee (rating_owner 'matinee': person ratings stay but stop driving Matinee
    until someone rates again); 'dismiss' closes the notice and leaves both as they are (the next family change is sent
    as usual). 400 for another choice, 404 for an unknown movie; with no notice open it does nothing."""
    if choice not in CHOICES:
        abort(make_err(400, 'Send {"choice": "ours"}, "matinee" or "dismiss".'))
    movies.get_row(con, movie_id)
    row = _row(con, movie_id)
    if row is None or row["conflict_rating"] is None:
        return None
    mean = ratings.family(con, movie_id)["mean"]
    if choice == "matinee":
        _set(con, movie_id, rating_owner="matinee", conflict_rating=None, pushed_rating=None)   # it holds its own
    elif choice == "dismiss":
        _set(con, movie_id, conflict_rating=None,
             pushed_rating=round_half_up(mean) if mean is not None else row["pushed_rating"])
    else:
        _set(con, movie_id, conflict_rating=None, pushed_rating=None)   # Matinee no longer holds what we sent
        value = _owed(_row(con, movie_id), mean)
        if value is not None and matinee.configured():
            _push(con, movie_id, value)
    return None


def pending(con, movie_id, mean=None):
    """True when a rating is owed to Matinee (a push failed or hasn't happened yet). `mean` saves reading it again."""
    if mean is None:
        mean = ratings.family(con, movie_id)["mean"]
    return _owed(_row(con, movie_id), mean) is not None


def pending_ids(con):
    """The ids of the movies with a rating owed to Matinee, for the nightly retry."""
    return [r["movie_id"] for r in con.execute(
        "SELECT movie_id FROM matinee_sync WHERE rating_owner='wonderful' AND matinee_title_id IS NOT NULL"
        " AND conflict_rating IS NULL ORDER BY movie_id") if pending(con, r["movie_id"])]


def status(con, movie_id, mean):
    """{"rating_conflict": {"matinee": 7.0, "ours": 8.9} | None, "rating_pending": bool} for the page."""
    row = _row(con, movie_id)
    conflict = None
    if row is not None and row["conflict_rating"] is not None and row["rating_owner"] == "wonderful":
        conflict = {"matinee": row["conflict_rating"], "ours": mean}
    return {"rating_conflict": conflict, "rating_pending": _owed(row, mean) is not None}


def display_rating(con, movie_id):
    """The rating the poster shows (spec §8.2): Matinee's while it owns the rating of a movie it holds, else the family
    mean; None when there is neither."""
    return ratings.shown(con, movie_id)[0]
