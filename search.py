"""Search over our list (spec §9): an exact-title shortcut, a local filter by title, year, cast and collection (no
network), and smart search, one Anthropic call for a description like "a musical" (ai.py) that also suggests titles
that are not on the list yet. Smart search never adds anything: a suggestion is only data until someone taps Add.
Route-free: app.py's GET /api/search calls these with a connection. No Flask object here (see CLAUDE.md)."""
import hashlib
import json
import re

from flask import current_app, has_app_context

import ai as ai_client   # search.ai() below is the smart search itself
import movies
import tmdb
from common import now_iso, today
from settings import AI_DAILY_CAP

AI_NOTICE = "Smart search is off right now."
SUGGESTIONS_NOTICE = "Ideas for titles to add aren't available right now."
MAX_MATCHES = 8
MAX_SUGGESTIONS = 3
QUERY_MAX = 200   # characters of the query sent to the model
_CALLS_KEY = "ai_calls:"   # meta key prefix: "ai_calls:<local date>" holds that day's count

_APOSTROPHES = re.compile(r"['’]")
_PUNCTUATION = re.compile(r"[^\w\s]|_")


def normalize(s):
    """Casefolded text with apostrophes dropped, other punctuation a space, runs of spaces collapsed, and a leading
    "the " dropped: "The Santa Clause!" and "santa clause" both become "santa clause". The page's search.js mirrors
    this exactly; change both together."""
    s = _APOSTROPHES.sub("", str(s or "").casefold())
    s = " ".join(_PUNCTUATION.sub(" ", s).split())
    return s[4:] if s.startswith("the ") else s


def _cast(row):
    try:
        names = json.loads(row["top_cast"]) if row["top_cast"] else []
    except ValueError:
        names = []
    return [n for n in names if isinstance(n, str)]


def exact(con, q):
    """The id of the one movie whose normalized title is the normalized query, or None. Two titles with the same
    normalized name (a remake, a TV special) are not exact: the local filter shows both."""
    qn = normalize(q)
    if not qn:
        return None
    hits = [r["id"] for r in movies.list_rows(con) if normalize(r["title"]) == qn]
    return hits[0] if len(hits) == 1 else None


def local_matches(con, q):
    """[{"id", "why"}] for every movie on the list that matches the query in its title, year, one of its cast names
    or its collection name, in list order. `why` names the first field that matched ("title", "year", "cast: <name>",
    "collection: <name>"). An empty query returns the whole list with `why` None."""
    qn = normalize(q)
    out = []
    for r in movies.list_rows(con):
        if not qn:
            out.append({"id": r["id"], "why": None})
            continue
        why = None
        if qn in normalize(r["title"]):
            why = "title"
        elif r["year"] is not None and qn in str(r["year"]):
            why = "year"
        else:
            name = next((n for n in _cast(r) if qn in normalize(n)), None)
            if name is not None:
                why = f"cast: {name}"
            elif r["collection_name"] and qn in normalize(r["collection_name"]):
                why = f"collection: {r['collection_name']}"
        if why is not None:
            out.append({"id": r["id"], "why": why})
    return out


def local(con, q):
    """The ids from local_matches, in list order."""
    return [m["id"] for m in local_matches(con, q)]


# ---------------------------------------------------------------------------------------------------- smart search
def _log(msg, *args):
    if has_app_context():
        current_app.logger.warning(msg, *args)


def _fallback(con, q):
    """The local filter, with the notice that smart search is off (spec §9 step 3)."""
    return {"mode": "local", "matches": local_matches(con, q), "suggestions": [], "notice": AI_NOTICE}


def _claim_call(con):
    """Count one smart search against today's AI_DAILY_CAP (the host's local date, like every date here) and say
    whether it may go ahead. The count is in `meta`, claimed in one statement so two workers can't both take the last
    call, and it counts every call made, answered or not: the cap is about spend. Cached answers never come here."""
    day = f"{_CALLS_KEY}{today().isoformat()}"
    con.execute("DELETE FROM meta WHERE k LIKE ? AND k <> ?", (_CALLS_KEY + "%", day))
    con.execute("INSERT OR IGNORE INTO meta (k, v) VALUES (?, '0')", (day,))
    cur = con.execute("UPDATE meta SET v = CAST(v AS INTEGER) + 1 WHERE k = ? AND CAST(v AS INTEGER) < ?",
                      (day, AI_DAILY_CAP))
    con.commit()
    return cur.rowcount == 1


def _cached(con, qn, list_hash):
    row = con.execute("SELECT result FROM ai_cache WHERE q_norm = ? AND list_hash = ?", (qn, list_hash)).fetchone()
    if row is None:
        return None
    try:
        result = json.loads(row["result"])
    except ValueError:
        return None
    ok = isinstance(result, dict) and isinstance(result.get("matches"), list) and isinstance(result.get("suggestions"), list)
    return result if ok else None


def _checked_matches(raw, ids):
    """At most MAX_MATCHES of the model's matches, best first: only ids that are on the list, each once."""
    out, seen = [], set()
    for m in raw:
        if m["id"] in ids and m["id"] not in seen:
            seen.add(m["id"])
            out.append({"id": m["id"], "why": m["why"]})
    return out[:MAX_MATCHES]


def _pick(found, title, year):
    """The TMDB result for a suggested title: the same normalized title, and when the model gave a year, within a
    year of it (the closest first). None when TMDB has no such thing."""
    want = normalize(title)
    same = [f for f in found if normalize(f["title"]) == want]
    if year is None:
        return same[0] if same else None
    near = sorted((f for f in same if f["year"] is not None and abs(f["year"] - year) <= 1), key=lambda f: abs(f["year"] - year))
    return near[0] if near else None


def _resolved_suggestions(con, raw):
    """([{title, year, why, tmdb_id, tmdb_type}], complete): up to MAX_SUGGESTIONS of the model's suggestions looked
    up in TMDB, minus the ones TMDB can't find and the ones already on the list. `complete` is False when TMDB
    failed part-way (what was found is kept, but the caller must not cache it)."""
    have = {(r["tmdb_type"], r["tmdb_id"]) for r in con.execute("SELECT tmdb_type, tmdb_id FROM movies")}
    titles = {(normalize(r["title"]), r["year"]) for r in movies.list_rows(con)}
    out = []
    for s in raw[:MAX_SUGGESTIONS]:
        try:
            hit = _pick(tmdb.search(s["title"]), s["title"], s["year"])
        except tmdb.TmdbError as e:
            _log("smart search: TMDB could not check the suggestion %r: %s", s["title"], e.message)
            return out, False
        if hit is None or (hit["tmdb_type"], hit["tmdb_id"]) in have or (normalize(hit["title"]), hit["year"]) in titles:
            continue
        if any(o["tmdb_id"] == hit["tmdb_id"] and o["tmdb_type"] == hit["tmdb_type"] for o in out):
            continue
        out.append({"title": hit["title"], "year": hit["year"], "why": s["why"],
                    "tmdb_id": hit["tmdb_id"], "tmdb_type": hit["tmdb_type"]})
    return out, True


def ai(con, q):
    """Smart search for `q`: {"mode": "ai", "matches": [{"id", "why"}], "suggestions": [{"title", "year", "why",
    "tmdb_id", "tmdb_type"}], "notice": None}. Matches are ids that are on the list (at most 8); suggestions are what
    TMDB found for the model's ideas that are not on the list yet (at most 3). Nothing is added to the list. The answer
    is cached by the normalized query and a hash of the list, so asking again costs nothing until the list changes.
    With no key, a spent AI_DAILY_CAP, or any failure of the model, this is the local filter with the notice instead
    ({"mode": "local", ...}); the cap and a failed call both count as spend, a cache hit does not."""
    q = (q or "").strip()[:QUERY_MAX]
    qn = normalize(q)
    if not qn:
        return {"mode": "local", "matches": local_matches(con, q), "suggestions": [], "notice": None}
    if not ai_client.configured():
        return _fallback(con, q)
    rows = movies.list_rows(con)
    list_json = ai_client.build_list_json(rows)
    list_hash = hashlib.sha256(list_json.encode("utf-8")).hexdigest()
    hit = _cached(con, qn, list_hash)
    if hit is not None:
        return {"mode": "ai", "matches": hit["matches"], "suggestions": hit["suggestions"], "notice": None}
    if not _claim_call(con):
        _log("smart search: today's AI_DAILY_CAP of %s is spent", AI_DAILY_CAP)
        return _fallback(con, q)
    try:
        answer = ai_client.ask(list_json, q)
    except ai_client.AiError as e:
        _log("smart search failed (%s): %s", e.reason, e.message)
        return _fallback(con, q)
    result = {"matches": _checked_matches(answer["matches"], {r["id"] for r in rows})}
    result["suggestions"], complete = _resolved_suggestions(con, answer["suggestions"])
    if complete:
        con.execute("INSERT OR REPLACE INTO ai_cache (q_norm, list_hash, result, created_at) VALUES (?,?,?,?)",
                    (qn, list_hash, json.dumps(result), now_iso()))
        con.commit()
    return {"mode": "ai", **result, "notice": None if complete else SUGGESTIONS_NOTICE}
