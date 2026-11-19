"""Helpers every part of the app shares: text cleaning, the JSON error response, rating validation and rounding,
and the host's local date. No Flask object and no routes here (see CLAUDE.md)."""
import datetime as dt, json, math, os

from flask import abort, has_app_context, jsonify
from werkzeug.wrappers import Response as WerkzeugResponse

RATING_ERROR = "Rating must be a number between 0.0 and 10.0 in 0.5 steps."


def clean(s):
    """Stripped text, or None for None, blank or whitespace-only input."""
    if s is None:
        return None
    s = str(s).strip()
    return s or None


def make_err(status, msg, **extra):
    """A JSON error response {"error": msg, ...}: pass it to abort() or return it from a route."""
    if has_app_context():
        r = jsonify(error=msg, **extra)
        r.status_code = status
        return r
    return WerkzeugResponse(json.dumps({"error": msg, **extra}), status=status, mimetype="application/json")


def validate_rating(v):
    """None or "" -> None (no rating). Otherwise a float 0.0-10.0 in 0.5 steps, or abort with a 400."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        abort(make_err(400, RATING_ERROR))
    try:
        r = float(v)
    except (TypeError, ValueError):
        abort(make_err(400, RATING_ERROR))
    if not math.isfinite(r) or not (0.0 <= r <= 10.0) or (r * 2) % 1 != 0:
        abort(make_err(400, RATING_ERROR))
    return round(r, 1)


def round_half_up(x):
    """To the nearest 0.5, ties up: 8.6 -> 8.5, 8.25 -> 8.5, 8.75 -> 9.0 (what Matinee receives, spec §8.2).
    round(…, 9) first, so a mean like 8.7499999999 that is really 8.75 still rounds up."""
    return math.floor(round(x * 2, 9) + 0.5) / 2


def today():
    """Today's date on the host's TZ (spec §16), not UTC. TZ is read on every call, so a test can set it; an
    unknown zone falls back to the process's local time."""
    tz = os.environ.get("TZ", "").strip().lstrip(":")
    if tz:
        try:
            from zoneinfo import ZoneInfo
            return dt.datetime.now(ZoneInfo(tz)).date()
        except Exception:  # noqa: BLE001 — no tzdata or a bad name: use local time
            pass
    return dt.date.today()


def now_iso():
    """UTC timestamp for *_at columns: 2026-12-12T03:31:04Z."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
