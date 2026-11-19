"""Search over our list (spec §9, steps 0 and 1): normalize, the exact-title shortcut, the local filter by title, year,
cast and collection, and GET /api/search. No network: the rows are written straight into the database, with the cast
and collection a TMDB details call would have stored (the cast lists are hand-entered test data, not recorded TMDB)."""
import json

import pytest

import search

# (tmdb_id, tmdb_type, title, year, collection name, top cast)
LIBRARY = [
    (1001, "movie", "The Santa Clause", 1994, None, ["Tim Allen", "Judge Reinhold", "Wendy Crewson"]),
    (1002, "movie", "The Santa Clause 2", 2002, "The Santa Clause Collection", ["Tim Allen", "Elizabeth Mitchell"]),
    (1003, "movie", "Christmas with the Kranks", 2004, None, ["Tim Allen", "Cheryl Hines"]),
    (1004, "movie", "Jingle All the Way", 1996, None, ["Arnold Schwarzenegger", "Sinbad"]),
    (1005, "movie", "The Christmas Chronicles", 2018, "The Christmas Chronicles Collection", ["Kurt Russell"]),
    (1006, "movie", "Elf", 2003, None, ["Will Ferrell", "James Caan"]),
]


def load(con, rows=LIBRARY):
    """Write the rows into the open database and return {title: id}."""
    ids = {}
    for tmdb_id, tmdb_type, title, year, collection, cast in rows:
        cur = con.execute(
            "INSERT INTO movies (tmdb_id, tmdb_type, title, year, collection_name, top_cast, added_by)"
            " VALUES (?,?,?,?,?,?,?)", (tmdb_id, tmdb_type, title, year, collection, json.dumps(cast), "test"))
        ids[title] = cur.lastrowid
    con.commit()
    return ids


@pytest.fixture
def library(app_ctx):
    """The app's own database, with LIBRARY on it, inside an application context."""
    from app import get_db
    return load(get_db())


@pytest.fixture
def library_client(client):
    import app as core
    with core.app.app_context():
        ids = load(core.get_db())
    return client, ids


def test_normalize_drops_punctuation_apostrophes_and_a_leading_the():
    assert search.normalize("The Santa Clause!") == "santa clause"
    assert search.normalize("It's a Wonderful Life") == "its a wonderful life"
    assert search.normalize("  the   Elf ") == "elf"
    assert search.normalize("Tim-Allen") == "tim allen"
    assert search.normalize("Theater") == "theater"      # only "the " at the start, as a word
    assert search.normalize("the") == "the"
    assert search.normalize(None) == ""


def test_elf_exact(library):
    from app import get_db
    assert search.exact(get_db(), "elf") == library["Elf"]
    assert search.exact(get_db(), "Elf") == library["Elf"]


def test_the_santa_clause_matches_without_the(library):
    from app import get_db
    assert search.exact(get_db(), "santa clause") == library["The Santa Clause"]
    assert search.exact(get_db(), "The Santa Clause") == library["The Santa Clause"]
    assert search.exact(get_db(), "Santa") is None           # a part of a title is not exact


def test_exact_is_none_when_two_titles_share_the_name(library):
    from app import get_db
    con = get_db()
    con.execute("INSERT INTO movies (tmdb_id, tmdb_type, title, year, added_by) VALUES (2001, 'tv', 'The Elf', 2010, 't')")
    con.commit()
    assert search.exact(con, "elf") is None                   # the local filter shows both


def test_actor_search_tim_allen(library):
    from app import get_db
    want = {library["The Santa Clause"], library["The Santa Clause 2"], library["Christmas with the Kranks"]}
    assert set(search.local(get_db(), "Tim Allen")) == want
    assert set(search.local(get_db(), "tim allen")) == want
    assert library["Jingle All the Way"] not in search.local(get_db(), "Tim Allen")


def test_collection_search_christmas_chronicles(library):
    from app import get_db
    want = [library["The Christmas Chronicles"]]
    assert search.local(get_db(), "Chronicles Collection") == want
    assert search.local(get_db(), "christmas chronicles") == want
    matches = search.local_matches(get_db(), "Chronicles Collection")
    assert matches == [{"id": want[0], "why": "collection: The Christmas Chronicles Collection"}]


def test_year_and_title_matches(library):
    from app import get_db
    assert search.local(get_db(), "2003") == [library["Elf"]]
    assert search.local_matches(get_db(), "christmas")[0] == {
        "id": library["Christmas with the Kranks"], "why": "title"}


def test_empty_query_returns_whole_list(library):
    from app import get_db
    con = get_db()
    assert search.local(con, "") == [m["id"] for m in search.local_matches(con, "")]
    assert len(search.local(con, "   ")) == len(LIBRARY)
    assert all(m["why"] is None for m in search.local_matches(con, ""))


def test_no_match_is_an_empty_list(library):
    from app import get_db
    assert search.local(get_db(), "zzz nothing like this") == []


def test_api_exact_title(library_client):
    client, ids = library_client
    r = client.get("/api/search?q=elf")
    assert r.status_code == 200
    assert r.get_json() == {"mode": "exact", "matches": [{"id": ids["Elf"], "why": "exact title"}], "suggestions": []}


def test_api_actor_is_local_with_a_reason(library_client):
    client, ids = library_client
    body = client.get("/api/search?q=Tim%20Allen").get_json()
    assert body["mode"] == "local" and body["suggestions"] == []
    assert {m["id"] for m in body["matches"]} == {ids["The Santa Clause"], ids["The Santa Clause 2"],
                                                  ids["Christmas with the Kranks"]}
    assert {m["why"] for m in body["matches"]} == {"cast: Tim Allen"}


def test_api_empty_query_is_the_whole_list_in_list_order(library_client):
    client, ids = library_client
    body = client.get("/api/search?q=").get_json()
    assert body["mode"] == "local"
    assert [m["id"] for m in body["matches"]] == [ids[t] for t in sorted(ids, key=str.casefold)]
    assert client.get("/api/search").get_json()["matches"] == body["matches"]


def test_api_no_match_is_200_and_empty(library_client):
    client, _ = library_client
    r = client.get("/api/search?q=zzz")
    assert r.status_code == 200 and r.get_json() == {"mode": "local", "matches": [], "suggestions": []}

