"""The Matinee client and ownership (spec §8, plan Task 5): matinee.Client against responses recorded from Matinee's
/admin/api (tests/fixtures/matinee/), movies.refresh_ownership, the owned line in where_to_watch, the detail view's
refresh, and the nightly ops/wonderful-refresh. Matinee answers from the FakeMatinee in conftest; no network."""
import importlib.machinery
import importlib.util
import io
import json
import urllib.error
from pathlib import Path

import pytest

import app
from conftest import MATINEE_HOST, MATINEE_KEY

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "matinee"
ELF, KLAUS, WISHED = 10719, 508439, 777
SHELF = "Blu-ray · Family Room › Media Cabinet › Shelf 2"


def load_cli():
    """ops/wonderful-refresh has no .py suffix, so load it by path."""
    loader = importlib.machinery.SourceFileLoader("wonderful_refresh", str(ROOT / "ops" / "wonderful-refresh"))
    spec = importlib.util.spec_from_loader("wonderful_refresh", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


refresh_cli = load_cli()


@pytest.fixture
def con(app_ctx):
    return app_ctx.get_db()


def api():
    return app.matinee.Client(f"http://{MATINEE_HOST}", MATINEE_KEY)


def add_row(con, tmdb_id, title, tmdb_type="movie"):
    cur = con.execute("INSERT INTO movies (tmdb_id, tmdb_type, title) VALUES (?, ?, ?)", (tmdb_id, tmdb_type, title))
    con.commit()
    return cur.lastrowid


def sync(con, movie_id):
    return con.execute("SELECT * FROM matinee_sync WHERE movie_id=?", (movie_id,)).fetchone()


def last_known(con, movie_id, checked_at, title_id=1, summary="Blu-ray", location="Family Room › Media Cabinet › Shelf 2"):
    """A matinee_sync row as an earlier successful check left it."""
    con.execute("INSERT OR REPLACE INTO matinee_sync (movie_id, matinee_title_id, owned_summary, location_path,"
                " matinee_rating, checked_at) VALUES (?,?,?,?,9.0,?)", (movie_id, title_id, summary, location, checked_at))
    con.commit()


def age(con, movie_id, days):
    con.execute("UPDATE matinee_sync SET checked_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?) WHERE movie_id=?",
                (f"-{days} days", movie_id))
    con.commit()


def lines(con, movie_id):
    return [(w["kind"], w["label"]) for w in app.providers.where_to_watch(con, movie_id)]


def asked(fake):
    """The TMDB ids of the owned lookups the fake saw."""
    return [int(p.split("/")[4]) for m, p, _b in fake.calls if p.endswith("/owned")]


# ------------------------------------------------------------------------------------------------ the client
def test_owned_elf_reads_bluray_and_shelf(con, matinee_fixtures):
    assert api().owned(ELF) == {"title_id": 1, "summary": "Blu-ray", "location_path": "Family Room › Media Cabinet › Shelf 2",
                                "has_physical": True, "has_digital": False, "fandango_id": None}
    movie_id = add_row(con, ELF, "Elf")
    app.movies.refresh_ownership(con, movie_id)
    s = sync(con, movie_id)
    assert (s["matinee_title_id"], s["owned_summary"], s["location_path"], s["matinee_rating"]) == \
        (1, "Blu-ray", "Family Room › Media Cabinet › Shelf 2", 9.0)
    assert s["matinee_last_watch"] == "2025-12-20"        # the newest of the two recorded watches
    assert s["checked_at"]
    assert lines(con, movie_id)[0] == ("owned", SHELF)    # fresh: no "(as of …)"


@pytest.mark.parametrize("fixture, kinds", [
    ("owned_elf.json", (True, False)),
    ("owned_digital_only.json", (False, True)),
    ("owned_disc_and_digital.json", (True, True)),
    ("owned_no_copies.json", (False, False)),
])
def test_owned_reads_which_kinds_of_copy_there_are(matinee_fixtures, fixture, kinds):
    matinee_fixtures.owned_files[ELF] = fixture
    found = api().owned(ELF)
    assert (found["has_physical"], found["has_digital"]) == kinds


def test_a_copy_of_any_other_kind_counts_as_neither(matinee_fixtures, monkeypatch):
    body = {"title_id": 5, "summary": "Mystery", "copies": [{"kind": "tape", "format": "Betamax"}, {"kind": None}, "x"]}
    monkeypatch.setattr(app.matinee.Client, "_call", lambda self, method, path, b=None: body)
    found = api().owned(ELF)
    assert (found["has_physical"], found["has_digital"]) == (False, False)


# ------------------------------------------------------------------------------------------------ the Fandango at Home id
def test_a_digital_copy_with_a_fandango_id_gives_it(matinee_fixtures):
    matinee_fixtures.owned_files[ELF] = "owned_digital_fandango.json"
    found = api().owned(ELF)
    assert found["fandango_id"] == "15429" and (found["has_physical"], found["has_digital"]) == (False, True)


def test_a_disc_and_digital_title_takes_the_digital_copys_id(matinee_fixtures):
    # the recorded disc carries an id of its own, which is ignored
    matinee_fixtures.owned_files[ELF] = "owned_disc_and_digital_fandango.json"
    assert api().owned(ELF)["fandango_id"] == "15429"


@pytest.mark.parametrize("fixture", ["owned_elf.json", "owned_digital_only.json", "owned_disc_and_digital.json",
                                     "owned_no_copies.json", "not_owned.json"])
def test_a_copy_without_the_key_has_no_fandango_id(matinee_fixtures, fixture):
    matinee_fixtures.owned_files[ELF] = fixture      # an older Matinee: no copy has the key, and that is no error
    assert api().owned(ELF)["fandango_id"] is None


@pytest.mark.parametrize("value", [None, "15429; rm", "1234567890123", 15429, "", " 15429", "15429\n", "１５４２９", True, ["15429"]])
def test_a_fandango_id_that_is_not_one_to_twelve_digits_is_none(matinee_fixtures, monkeypatch, value):
    body = json.loads((FIXTURES / "owned_digital_fandango.json").read_text())
    body["copies"][0]["fandango_id"] = value
    monkeypatch.setattr(app.matinee.Client, "_call", lambda self, method, path, b=None: body)
    assert api().owned(ELF)["fandango_id"] is None


def test_a_twelve_digit_fandango_id_is_kept(matinee_fixtures, monkeypatch):
    body = json.loads((FIXTURES / "owned_digital_fandango.json").read_text())
    body["copies"][0]["fandango_id"] = "123456789012"
    monkeypatch.setattr(app.matinee.Client, "_call", lambda self, method, path, b=None: body)
    assert api().owned(ELF)["fandango_id"] == "123456789012"


def test_a_physical_copy_with_the_key_is_ignored(matinee_fixtures, monkeypatch):
    body = json.loads((FIXTURES / "owned_disc_and_digital_fandango.json").read_text())
    del body["copies"][1]                             # leave the disc, which carries "99999"
    assert body["copies"][0]["kind"] == "physical" and body["copies"][0]["fandango_id"] == "99999"
    monkeypatch.setattr(app.matinee.Client, "_call", lambda self, method, path, b=None: body)
    assert api().owned(ELF)["fandango_id"] is None


def test_the_first_digital_copy_with_a_valid_id_wins(matinee_fixtures, monkeypatch):
    body = {"title_id": 1, "summary": "Digital HD", "copies": [
        {"kind": "digital", "fandango_id": "bad id"}, {"kind": "digital", "fandango_id": "111"},
        {"kind": "digital", "fandango_id": "222"}]}
    monkeypatch.setattr(app.matinee.Client, "_call", lambda self, method, path, b=None: body)
    assert api().owned(ELF)["fandango_id"] == "111"


def test_not_owned_sets_null_title_id(con, matinee_fixtures):
    assert api().owned(KLAUS) == {"title_id": None, "summary": None, "location_path": None,
                                  "has_physical": False, "has_digital": False, "fandango_id": None}
    movie_id = add_row(con, KLAUS, "Klaus")
    app.movies.refresh_ownership(con, movie_id)
    s = sync(con, movie_id)
    assert (s["matinee_title_id"], s["owned_summary"], s["location_path"], s["matinee_rating"],
            s["matinee_last_watch"]) == (None, None, None, None, None)
    assert s["checked_at"]                                # checked: "not owned" is an answer
    assert all(kind != "owned" for kind, _ in lines(con, movie_id))
    assert [c[1] for c in matinee_fixtures.calls if "/titles/" in c[1]] == []   # no title lookup for a title not owned


def test_a_title_matinee_has_with_no_copies_is_not_owned(con, matinee_fixtures):
    matinee_fixtures.owned_files[WISHED] = "owned_no_copies.json"
    movie_id = add_row(con, WISHED, "A Wished-For Movie")
    app.movies.refresh_ownership(con, movie_id)
    assert sync(con, movie_id)["matinee_title_id"] is None
    assert all(kind != "owned" for kind, _ in lines(con, movie_id))


def test_a_movie_that_stopped_being_owned_loses_its_shelf(con, matinee_fixtures):
    movie_id = add_row(con, KLAUS, "Klaus")
    last_known(con, movie_id, "2025-12-03T18:00:00Z")
    app.movies.refresh_ownership(con, movie_id)
    assert sync(con, movie_id)["owned_summary"] is None and lines(con, movie_id)[0][0] != "owned"


def test_tv_type_skips_matinee(con, matinee_fixtures):
    movie_id = add_row(con, ELF, "A TV special that shares Elf's id", tmdb_type="tv")   # Matinee keys by movie id only
    app.movies.refresh_ownership(con, movie_id)
    assert matinee_fixtures.calls == []
    assert sync(con, movie_id) is None
    assert movie_id not in app.movies.ownership_due(con)


def test_bearer_header_sent(matinee_fixtures):
    c = api()
    c.owned(ELF)
    c.title(1)
    c.people()
    assert matinee_fixtures.headers == [f"Bearer {MATINEE_KEY}"] * 3
    assert all(m == "GET" for m, _p, _b in matinee_fixtures.calls)


def test_title_reads_the_rating_and_watches(matinee_fixtures):
    t = api().title(1)
    assert t["user_rating"] == 9.0 and [w["watched_date"] for w in t["watches"]] == ["2025-12-20", "2024-12-14"]


def test_set_rating_puts_the_value_and_a_bad_step_is_rejected(matinee_fixtures):
    c = api()
    assert c.set_rating(1, 8.5) is None
    assert matinee_fixtures.calls[-1] == ("PUT", "/admin/api/titles/1/rating", {"rating": 8.5})
    with pytest.raises(app.matinee.Rejected) as e:
        c.set_rating(1, 8.3)
    assert e.value.status == 400 and "0.5 increments" in e.value.message


def test_log_watch_returns_the_watch_id_and_never_says_live(matinee_fixtures):
    assert api().log_watch(1, "2025-12-24", ["Avery", "Blake"]) == 3
    method, path, body = matinee_fixtures.calls[-1]
    assert (method, path) == ("POST", "/admin/api/titles/1/watches")
    assert body == {"watched_date": "2025-12-24", "attendees": ["Avery", "Blake"]}     # no "live" (spec §8.3)


def test_delete_watch_deletes_it(matinee_fixtures):
    api().delete_watch(1, 3)
    assert matinee_fixtures.calls[-1] == ("DELETE", "/admin/api/titles/1/watches/3", None)


def test_people_lists_matinees_people(matinee_fixtures):
    people = api().people()
    assert [(p["name"], p["kind"], p["color"], p["sort_order"]) for p in people] == [
        ("Avery", "adult", "green", 0), ("Blake", "adult", "blue", 1), ("Casey", "kid", "red", 2), ("Drew", "kid", "pink", 3)]


CALLS = {"owned": lambda c: c.owned(ELF), "title": lambda c: c.title(1), "set_rating": lambda c: c.set_rating(1, 8.5),
         "log_watch": lambda c: c.log_watch(1, "2025-12-24", ["Avery"]), "delete_watch": lambda c: c.delete_watch(1, 3),
         "people": lambda c: c.people()}


@pytest.mark.parametrize("name", CALLS)
@pytest.mark.parametrize("error", [urllib.error.URLError(ConnectionRefusedError()), TimeoutError(), ConnectionResetError(),
                                   500, 502, 503])
def test_every_call_raises_unavailable_when_matinee_cannot_answer(name, error, matinee_down):
    matinee_down.error = error
    with pytest.raises(app.matinee.Unavailable) as e:
        CALLS[name](api())
    assert MATINEE_KEY not in e.value.message


@pytest.mark.parametrize("name", CALLS)
@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_every_call_raises_rejected_on_a_4xx(name, status, matinee_down):
    matinee_down.error = status
    with pytest.raises(app.matinee.Rejected) as e:
        CALLS[name](api())
    assert e.value.status == status and e.value.message


def test_wrong_key_is_rejected_with_matinees_words(matinee_fixtures):
    with pytest.raises(app.matinee.Rejected) as e:
        app.matinee.Client(f"http://{MATINEE_HOST}", "not-the-key").owned(ELF)
    assert (e.value.status, e.value.message) == (401, "Sign in to edit")


@pytest.mark.parametrize("body", [b"<html>Bad gateway</html>", b"", b"[1, 2]", b'{"title_id": "x", "copies": []}'])
def test_an_answer_that_is_not_matinees_json_is_unavailable(body, client, monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: io.BytesIO(body))
    with pytest.raises(app.matinee.Unavailable):
        api().owned(ELF)


def test_a_watch_answer_without_an_id_is_unavailable(client, monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: io.BytesIO(b'{"ok": true}'))
    with pytest.raises(app.matinee.Unavailable):
        api().log_watch(1, "2025-12-24", ["Avery"])


def test_no_key_means_no_request(matinee_fixtures):
    with pytest.raises(app.matinee.Unavailable):
        app.matinee.Client(f"http://{MATINEE_HOST}", "").owned(ELF)
    with pytest.raises(app.matinee.Unavailable):
        app.matinee.Client("ftp://example.com", MATINEE_KEY).owned(ELF)
    assert matinee_fixtures.calls == []


def test_the_timeout_is_five_seconds_by_default(client, monkeypatch):
    import urllib.request
    seen = []

    def spy(req, timeout=None):
        seen.append(timeout)
        return io.BytesIO(b'{"title_id": null, "copies": [], "summary": null}')

    monkeypatch.setattr(urllib.request, "urlopen", spy)
    api().owned(ELF)
    app.matinee.Client(f"http://{MATINEE_HOST}", MATINEE_KEY, timeout=2).owned(ELF)
    assert seen == [5, 2]


def test_newest_watch_skips_undated_and_junk():
    f = app.movies._newest_watch
    assert f([{"watched_date": "2024-12-14"}, {"watched_date": None}, {"watched_date": "2025-12-20"},
              {"watched_date": "someday"}, "x"]) == "2025-12-20"
    assert f([]) is None and f(None) is None and f([{"watched_date": None}]) is None


# ------------------------------------------------------------------------------------------------ Review Focus 1
@pytest.mark.parametrize("error", [urllib.error.URLError(ConnectionRefusedError()), TimeoutError(), 502, 500])
def test_matinee_down_keeps_last_known_and_marks_stale(con, matinee_down, error):
    matinee_down.error = error
    movie_id = add_row(con, ELF, "Elf")
    last_known(con, movie_id, "2025-12-03T18:00:00Z")
    before = dict(sync(con, movie_id))
    app.movies.refresh_ownership(con, movie_id)             # does not raise
    assert dict(sync(con, movie_id)) == before              # nothing changed, checked_at included
    assert matinee_down.calls >= 1
    assert lines(con, movie_id)[0] == ("owned", SHELF + " (as of Dec 3)")


def test_a_wrong_key_keeps_last_known_too(con, matinee_fixtures, monkeypatch):
    monkeypatch.setattr(app, "MATINEE_API_KEY", "not-the-key")
    movie_id = add_row(con, ELF, "Elf")
    last_known(con, movie_id, "2025-12-03T18:00:00Z")
    app.movies.refresh_ownership(con, movie_id)
    assert sync(con, movie_id)["checked_at"] == "2025-12-03T18:00:00Z"
    assert lines(con, movie_id)[0] == ("owned", SHELF + " (as of Dec 3)")


def test_the_as_of_date_is_the_host_local_date(con, monkeypatch):
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    movie_id = add_row(con, ELF, "Elf")
    last_known(con, movie_id, "2025-12-04T03:00:00Z")       # 7 pm on Dec 3 in Los Angeles
    assert lines(con, movie_id)[0][1].endswith("(as of Dec 3)")
    last_known(con, movie_id, "2025-12-31T09:00:00Z")
    assert lines(con, movie_id)[0][1].endswith("(as of Dec 31)")


def test_an_answer_under_a_day_old_has_no_as_of(con):
    movie_id = add_row(con, ELF, "Elf")
    last_known(con, movie_id, "2025-12-03T18:00:00Z")
    age(con, movie_id, 0.9)
    assert lines(con, movie_id)[0] == ("owned", SHELF)
    age(con, movie_id, 1.1)
    assert lines(con, movie_id)[0][1].startswith(SHELF + " (as of ")


def test_owned_with_no_shelf_reads_just_the_copies(con):
    movie_id = add_row(con, ELF, "Elf")
    last_known(con, movie_id, "2099-01-01T00:00:00Z", summary="Digital HD (Movies Anywhere)", location=None)
    assert lines(con, movie_id)[0] == ("owned", "Digital HD (Movies Anywhere)")


def test_owned_comes_first_and_is_ready_tonight(con):
    movie_id = add_row(con, ELF, "Elf")                     # no provider cache at all: it would read "Rent or buy"
    assert lines(con, movie_id) == [("rent_buy", "Rent or buy")] and not app.providers.ready_tonight(con, movie_id)
    last_known(con, movie_id, "2099-01-01T00:00:00Z")
    assert [k for k, _ in lines(con, movie_id)] == ["owned"]
    assert app.providers.ready_tonight(con, movie_id)


def test_a_refresh_leaves_the_rating_columns_alone(con, matinee_fixtures):
    movie_id = add_row(con, ELF, "Elf")
    con.execute("INSERT INTO matinee_sync (movie_id, pushed_rating, rating_owner, conflict_rating) VALUES (?, 8.5, 'wonderful', 7.0)",
                (movie_id,))
    con.commit()
    app.movies.refresh_ownership(con, movie_id)
    s = sync(con, movie_id)
    assert (s["pushed_rating"], s["rating_owner"], s["conflict_rating"], s["matinee_rating"]) == (8.5, "wonderful", 7.0, 9.0)


# ------------------------------------------------------------------------------------------------ the routes
def test_adding_a_movie_asks_matinee_and_the_card_shows_the_shelf(client, tmdb_fixtures, matinee_fixtures):
    r = client.post("/api/movies", json={"tmdb_id": ELF})
    assert r.status_code == 201 and r.get_json()["where_to_watch"][0] == {"kind": "owned", "label": SHELF}
    assert asked(matinee_fixtures) == [ELF]
    (card,) = client.get("/api/movies").get_json()
    assert card["where_to_watch"][0]["kind"] == "owned" and asked(matinee_fixtures) == [ELF]   # the grid never asks


def test_adding_a_movie_works_while_matinee_is_down(client, tmdb_fixtures, matinee_down):
    r = client.post("/api/movies", json={"tmdb_id": ELF})
    assert r.status_code == 201
    assert all(w["kind"] != "owned" for w in r.get_json()["where_to_watch"])
    assert client.get(f"/api/movies/{r.get_json()['id']}").status_code == 200


def test_detail_view_asks_again_only_when_the_answer_is_over_a_day_old(client, tmdb_fixtures, matinee_fixtures):
    movie_id = client.post("/api/movies", json={"tmdb_id": ELF}).get_json()["id"]
    assert len(matinee_fixtures.calls) == 2                 # owned + title, on add
    client.get(f"/api/movies/{movie_id}")
    assert len(matinee_fixtures.calls) == 2                 # fresh: not asked
    with app.app.app_context():
        age(app.get_db(), movie_id, 2)
    body = client.get(f"/api/movies/{movie_id}").get_json()
    assert len(matinee_fixtures.calls) == 4                 # asked again
    assert body["where_to_watch"][0] == {"kind": "owned", "label": SHELF}    # and fresh again: no "(as of …)"


def test_detail_view_with_matinee_down_shows_the_last_known_and_does_not_hammer(client, tmdb_fixtures, matinee_fixtures,
                                                                               monkeypatch):
    import urllib.request
    movie_id = client.post("/api/movies", json={"tmdb_id": ELF}).get_json()["id"]
    with app.app.app_context():
        con = app.get_db()
        con.execute("UPDATE matinee_sync SET checked_at='2025-12-03T18:00:00Z' WHERE movie_id=?", (movie_id,))
        con.commit()
    down = type("Down", (), {"calls": 0})()

    def refuse(req, timeout=None):
        down.calls += 1
        raise urllib.error.URLError(TimeoutError())

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    for _ in range(3):
        body = client.get(f"/api/movies/{movie_id}").get_json()
        assert body["where_to_watch"][0]["label"] == SHELF + " (as of Dec 3)"
    assert down.calls == 1                                  # one attempt, then a minute's peace


def test_the_detail_view_does_not_ask_without_a_key(client, tmdb_fixtures):
    movie_id = client.post("/api/movies", json={"tmdb_id": ELF}).get_json()["id"]
    assert client.get(f"/api/movies/{movie_id}").status_code == 200    # urlopen would raise AssertionError if asked


def test_a_tv_special_is_never_asked_on_add_or_view(client, tmdb_fixtures, matinee_fixtures):
    r = client.post("/api/movies", json={"tmdb_id": 900002, "tmdb_type": "tv"})
    assert r.status_code == 201 and client.get(f"/api/movies/{r.get_json()['id']}").status_code == 200
    assert matinee_fixtures.calls == []


# ------------------------------------------------------------------------------------------------ the nightly job
def test_refresh_job_checks_rows_older_than_a_day_only(con, matinee_fixtures):
    never = add_row(con, ELF, "Elf")
    fresh = add_row(con, KLAUS, "Klaus")
    old = add_row(con, WISHED, "A Wished-For Movie")
    tv = add_row(con, 900002, "A TV special", tmdb_type="tv")
    last_known(con, fresh, "2025-12-03T18:00:00Z", title_id=None, summary=None, location=None)
    age(con, fresh, 0.5)
    last_known(con, old, "2025-12-03T18:00:00Z", title_id=None, summary=None, location=None)
    age(con, old, 2)
    assert app.movies.ownership_due(con) == [never, old] and tv not in app.movies.ownership_due(con)
    assert refresh_cli.refresh_ownership(con, say=lambda m: None) == (2, 0, 0)
    assert sorted(asked(matinee_fixtures)) == sorted([ELF, WISHED])    # Klaus (fresh) and the TV special were not asked
    assert app.movies.ownership_due(con) == []
    assert refresh_cli.refresh_ownership(con, say=lambda m: None) == (0, 0, 0)    # nothing is due now
    assert len(asked(matinee_fixtures)) == 2


def test_refresh_job_stops_at_the_first_failure(con, matinee_down):
    for n in range(3):
        add_row(con, 1000 + n, f"Movie {n}")
    said = []
    assert refresh_cli.refresh_ownership(con, say=said.append) == (0, 1, 2)
    assert matinee_down.calls == 1                          # not one timeout per movie
    assert len(said) == 1 and "2 more left for tomorrow" in said[0] and MATINEE_KEY not in said[0]


def test_refresh_job_with_no_key_asks_nothing(con, client):
    add_row(con, ELF, "Elf")
    said = []
    assert refresh_cli.refresh_ownership(con, say=said.append) == (0, 0, 1)    # urlopen would raise if asked
    assert "MATINEE_API_KEY" in said[0]


def test_refresh_job_dry_run_asks_and_writes_nothing(con, matinee_fixtures):
    add_row(con, ELF, "Elf")
    assert refresh_cli.refresh_ownership(con, dry_run=True, say=lambda m: None) == (1, 0, 0)
    assert matinee_fixtures.calls == [] and con.execute("SELECT COUNT(*) FROM matinee_sync").fetchone()[0] == 0


def test_refresh_job_renews_stale_provider_caches_only(con, tmdb_fixtures):
    stale, fresh = add_row(con, ELF, "Elf"), add_row(con, KLAUS, "Klaus")
    app.providers.refresh(con, fresh)
    tmdb_fixtures.api.clear()
    assert refresh_cli.refresh_providers(con, say=lambda m: None) == (1, 0)
    assert tmdb_fixtures.api == [f"https://api.themoviedb.org/3/movie/{ELF}/watch/providers"]
    assert app.providers.cached(con, stale)[3] is False
    assert refresh_cli.refresh_providers(con, say=lambda m: None) == (0, 0)


def test_refresh_job_provider_failures_are_counted_not_fatal(con, tmdb_down):
    add_row(con, ELF, "Elf")
    add_row(con, KLAUS, "Klaus")
    said = []
    assert refresh_cli.refresh_providers(con, say=said.append) == (0, 2)
    assert len(said) == 2


def test_refresh_job_main_runs_both_and_exits_clean(client, tmdb_fixtures, matinee_fixtures, capsys):
    with app.app.app_context():
        add_row(app.get_db(), ELF, "Elf")
    assert refresh_cli.main([]) == 0
    out = capsys.readouterr().out
    assert "providers for 1 (0 failed)" in out and "ownership checked for 1 (0 failed, 0 left for tomorrow)" in out
    with app.app.app_context():
        assert lines(app.get_db(), 1)[0] == ("owned", SHELF)


def test_refresh_job_main_exits_1_when_matinee_is_down(client, tmdb_fixtures, matinee_fixtures, capsys, monkeypatch):
    monkeypatch.setattr(app, "MATINEE_API_KEY", "not-the-key")
    with app.app.app_context():
        add_row(app.get_db(), ELF, "Elf")
    assert refresh_cli.main([]) == 1
    assert "1 failed" in capsys.readouterr().out
