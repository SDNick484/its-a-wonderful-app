"""Adding, listing, editing and removing movies over the API, with TMDB answered from recorded fixtures."""
import sqlite3

import pytest

import app

ELF = {"tmdb_id": 10719, "tmdb_type": "movie"}
PRANCER = {"tmdb_id": 14181, "tmdb_type": "movie"}
QUIET = {"tmdb_id": 900001, "tmdb_type": "movie"}      # no US certification, runtime null, no poster
TINSEL = {"tmdb_id": 900002, "tmdb_type": "tv"}        # a TV-only special


def add(client, body):
    r = client.post("/api/movies", json=body)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def test_add_elf_fills_metadata(client, tmdb_fixtures):
    r = client.post("/api/movies", json=ELF).get_json()
    m = client.get(f"/api/movies/{r['id']}").get_json()
    assert (m["title"], m["year"], m["certification"], m["is_animated"]) == ("Elf", 2003, "PG", False)
    assert m["runtime_min"] == 97 and len(m["top_cast"]) <= 8 and m["poster_url"].startswith("/posters/")
    assert m["tmdb_type"] == "movie" and m["added_by"] == "lan" and m["certification_override"] is False
    assert m["backdrop_url"].startswith("/posters/") and m["parent_note"] is None and m["family_rating"] is None


def test_add_returns_the_movie_with_201(client, tmdb_fixtures):
    r = client.post("/api/movies", json=PRANCER)
    assert r.status_code == 201
    assert r.get_json()["title"] == "Prancer" and r.get_json()["certification"] == "G" and r.get_json()["runtime_min"] == 103


def test_poster_is_downloaded_once_into_the_data_folder(client, tmdb_fixtures):
    m = add(client, ELF)
    assert (app.POSTER_DIR / "movie-10719-w342.jpg").is_file() and (app.POSTER_DIR / "movie-10719-backdrop-w780.jpg").is_file()
    assert len(tmdb_fixtures.images) == 2
    img = client.get(m["poster_url"])
    assert img.status_code == 200 and img.mimetype == "image/jpeg" and img.data.startswith(b"\xff\xd8\xff")
    # a refresh finds both files on disk and downloads nothing more
    with app.app.app_context():
        app.movies.refresh_metadata(app.get_db(), m["id"])
    assert len(tmdb_fixtures.images) == 2


def test_add_twice_is_409(client, tmdb_fixtures):
    first = add(client, ELF)
    calls = len(tmdb_fixtures.api)
    r = client.post("/api/movies", json=ELF)
    assert r.status_code == 409 and r.get_json()["id"] == first["id"] and "already" in r.get_json()["error"]
    assert len(tmdb_fixtures.api) == calls      # answered from the list, TMDB wasn't asked
    assert len(client.get("/api/movies").get_json()) == 1


def test_a_movie_and_a_tv_special_may_share_a_tmdb_id(client, tmdb_fixtures):
    # UNIQUE is (tmdb_type, tmdb_id), not tmdb_id alone
    add(client, ELF)
    con = sqlite3.connect(app.DB_PATH)
    con.execute("INSERT INTO movies (tmdb_id, tmdb_type, title) VALUES (10719, 'tv', 'Same id, a show')")
    con.commit()
    con.close()
    assert len(client.get("/api/movies").get_json()) == 2


def test_missing_us_cert_becomes_NR_and_null_runtime_kept(client, tmdb_fixtures):       # Review Focus 2
    m = add(client, QUIET)
    got = client.get(f"/api/movies/{m['id']}").get_json()
    assert got["certification"] == "NR" and got["runtime_min"] is None
    assert got["poster_url"] is None and got["backdrop_url"] is None and got["year"] is None
    assert got["collection_name"] == "The Quiet Reindeer Collection" and got["top_cast"] == []
    assert tmdb_fixtures.images == []            # TMDB has no art, so nothing was downloaded


def test_tv_special_is_added_as_tv(client, tmdb_fixtures):
    m = add(client, TINSEL)
    assert (m["title"], m["tmdb_type"], m["runtime_min"], m["certification"], m["is_animated"]) == ("The Tinsel Express", "tv", 24, "TV-Y7", True)
    assert (app.POSTER_DIR / "tv-900002-w342.jpg").is_file()


def test_a_failed_poster_download_still_adds_the_movie(client, tmdb_fixtures, monkeypatch):
    import urllib.request
    real = urllib.request.urlopen

    def flaky(req, timeout=None):
        if "image.tmdb.org" in req.full_url:
            raise OSError("image host down")
        return real(req, timeout=timeout)

    monkeypatch.setattr(urllib.request, "urlopen", flaky)
    m = add(client, ELF)
    assert m["poster_url"] is None and m["title"] == "Elf"
    assert not list(app.POSTER_DIR.glob("*"))     # no half-written file left behind


def test_a_download_that_is_not_a_jpeg_is_not_kept(client, tmdb_fixtures, monkeypatch):
    import io
    import urllib.request
    real = urllib.request.urlopen
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: io.BytesIO(b"<html>captive portal</html>")
                        if "image.tmdb.org" in req.full_url else real(req, timeout=timeout))
    assert add(client, ELF)["poster_url"] is None and not list(app.POSTER_DIR.glob("*"))


def test_certification_override_survives_refresh(client, tmdb_fixtures):
    m = add(client, ELF)
    r = client.put(f"/api/movies/{m['id']}", json={"certification": "pg-13"})
    assert r.status_code == 200 and r.get_json()["certification"] == "PG-13" and r.get_json()["certification_override"] is True
    with app.app.app_context():
        app.movies.refresh_metadata(app.get_db(), m["id"])
    got = client.get(f"/api/movies/{m['id']}").get_json()
    assert got["certification"] == "PG-13" and got["certification_override"] is True
    # lifting the override lets the next refresh bring TMDB's value back
    assert client.put(f"/api/movies/{m['id']}", json={"certification": None}).get_json()["certification_override"] is False
    with app.app.app_context():
        app.movies.refresh_metadata(app.get_db(), m["id"])
    assert client.get(f"/api/movies/{m['id']}").get_json()["certification"] == "PG"


def test_refresh_updates_metadata_and_keeps_the_note(client, tmdb_fixtures):
    m = add(client, ELF)
    client.put(f"/api/movies/{m['id']}", json={"parent_note": "Some fake snow"})
    con = sqlite3.connect(app.DB_PATH)
    con.execute("UPDATE movies SET title='Elfs', runtime_min=1, top_cast='[]' WHERE id=?", (m["id"],))
    con.commit()
    con.close()
    with app.app.app_context():
        app.movies.refresh_metadata(app.get_db(), m["id"])
    got = client.get(f"/api/movies/{m['id']}").get_json()
    assert (got["title"], got["runtime_min"], len(got["top_cast"]), got["parent_note"]) == ("Elf", 97, 8, "Some fake snow")


def test_parent_note_edit_and_clear(client, tmdb_fixtures):
    m = add(client, ELF)
    assert client.put(f"/api/movies/{m['id']}", json={"parent_note": "  Skip the spaghetti scene  "}).get_json()["parent_note"] == "Skip the spaghetti scene"
    assert client.put(f"/api/movies/{m['id']}", json={"parent_note": ""}).get_json()["parent_note"] is None


@pytest.mark.parametrize("body", [{}, {"title": "x"}, {"parent_note": 5}, {"parent_note": "x" * 1001}, {"certification": "XXX"},
                                  {"certification": 13}, [], "text"])
def test_bad_updates_are_400(client, tmdb_fixtures, body):
    m = add(client, ELF)
    assert client.put(f"/api/movies/{m['id']}", json=body).status_code == 400


def test_update_or_get_unknown_movie_is_404(client):
    assert client.get("/api/movies/99").status_code == 404
    assert client.put("/api/movies/99", json={"parent_note": "x"}).status_code == 404
    assert client.delete("/api/movies/99").status_code == 404


@pytest.mark.parametrize("body", [{}, {"tmdb_id": "abc"}, {"tmdb_id": -1}, {"tmdb_id": 0}, {"tmdb_id": True}, {"tmdb_id": 1.5},
                                  {"tmdb_id": 1, "tmdb_type": "person"}, [], "text"])
def test_bad_add_bodies_are_400(client, tmdb_fixtures, body):
    r = client.post("/api/movies", json=body)
    assert r.status_code == 400 and r.get_json()["error"]
    assert tmdb_fixtures.api == []


def test_add_defaults_to_movie_and_takes_a_numeric_string(client, tmdb_fixtures):
    assert client.post("/api/movies", json={"tmdb_id": "10719"}).get_json()["tmdb_type"] == "movie"


def test_list_is_sorted_by_title(client, tmdb_fixtures):
    for body in (PRANCER, ELF, TINSEL, QUIET):
        add(client, body)
    assert [m["title"] for m in client.get("/api/movies").get_json()] == ["Elf", "Prancer", "The Quiet Reindeer", "The Tinsel Express"]


def test_remove_deletes_the_row_its_ratings_and_its_images(client, tmdb_fixtures):
    m = add(client, ELF)
    con = sqlite3.connect(app.DB_PATH)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("INSERT INTO people (id, name, kind, color) VALUES (1, 'Pat', 'adult', 'green')")
    con.execute("INSERT INTO person_ratings (person_id, movie_id, rating) VALUES (1, ?, 8.5)", (m["id"],))
    con.commit()
    con.close()
    assert client.delete(f"/api/movies/{m['id']}").get_json() == {"ok": True}
    assert client.get(f"/api/movies/{m['id']}").status_code == 404 and client.get("/api/movies").get_json() == []
    assert not list(app.POSTER_DIR.glob("*"))
    con = sqlite3.connect(app.DB_PATH)
    assert con.execute("SELECT count(*) FROM person_ratings").fetchone()[0] == 0
    con.close()
    # and it can be added again
    assert client.post("/api/movies", json=ELF).status_code == 201


# ---------------------------------------------------------------------------------------------- search route
def test_search_route(client, tmdb_fixtures):
    add(client, PRANCER)
    body = client.get("/api/tmdb/search?q=Prancer").get_json()
    assert body["message"] is None and [r["title"] for r in body["results"]] == ["Prancer", "Prancer Pals", "Prancer Untitled"]
    assert body["results"][0]["on_list"] == 1 and body["results"][1]["on_list"] is None


def test_tmdb_search_miss_returns_empty_with_message(client, tmdb_fixtures):
    r = client.get("/api/tmdb/search?q=zzzz")
    assert r.status_code == 200
    assert r.get_json() == {"results": [], "message": 'TMDB has nothing called "zzzz".'}


@pytest.mark.parametrize("url", ["/api/tmdb/search", "/api/tmdb/search?q=", "/api/tmdb/search?q=%20%20"])
def test_search_needs_a_query(client, tmdb_fixtures, url):
    r = client.get(url)
    assert r.status_code == 400 and r.get_json()["error"] and tmdb_fixtures.api == []


# ---------------------------------------------------------------------------------------------- TMDB failures
def test_tmdb_http_error_is_502_with_message(client, tmdb_down):
    r = client.post("/api/movies", json=ELF)
    assert r.status_code == 502 and "HTTP 500" in r.get_json()["error"] and r.get_json()["reason"] == "unavailable"
    r = client.get("/api/tmdb/search?q=elf")
    assert r.status_code == 502 and r.get_json()["error"]
    assert client.get("/api/movies").get_json() == []             # nothing half-added


def test_unknown_tmdb_id_is_404(client, tmdb_fixtures):
    r = client.post("/api/movies", json={"tmdb_id": 1})
    assert r.status_code == 404 and r.get_json()["reason"] == "not_found"


def test_no_token_is_503_with_the_fix(client):
    r = client.get("/api/tmdb/search?q=elf")
    assert r.status_code == 503 and "TMDB_READ_TOKEN" in r.get_json()["error"]
    assert client.post("/api/movies", json=ELF).status_code == 503


def test_the_list_works_when_tmdb_is_down(client, tmdb_fixtures, monkeypatch):
    m = add(client, ELF)
    import urllib.request

    def boom(req, timeout=None):
        raise OSError("down")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert client.get("/api/movies").status_code == 200 and client.get(f"/api/movies/{m['id']}").status_code == 200
    assert client.get(m["poster_url"]).status_code == 200            # posters are served from the local copy


# ---------------------------------------------------------------------------------------------- posters route
@pytest.mark.parametrize("name", ["../wonderful.db", "movie-1.jpg", "movie-1-w342.png", "x-1-w342.jpg", ".hidden", "movie-1-w342.jpg"])
def test_posters_route_serves_only_names_images_writes(client, name):
    assert client.get(f"/posters/{name}").status_code == 404


def test_new_routes_need_an_editor(anon_client):
    for method, url in (("GET", "/api/tmdb/search?q=elf"), ("GET", "/api/movies"), ("POST", "/api/movies"),
                        ("GET", "/api/movies/1"), ("PUT", "/api/movies/1"), ("DELETE", "/api/movies/1"),
                        ("GET", "/posters/movie-1-w342.jpg")):
        assert anon_client.open(url, method=method, json={}).status_code == 401, (method, url)
