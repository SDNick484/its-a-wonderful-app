"""Search over our list (spec §9, steps 0 and 1): an exact-title shortcut, then a local filter by title, year, cast
and collection. No network here and no AI (Task 12 adds that). Route-free: app.py's GET /api/search calls these with
a connection. No Flask object here (see CLAUDE.md)."""
import json
import re

import movies

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
