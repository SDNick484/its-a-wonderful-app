"""The family (spec §8.4): people copied from Matinee by name, people added here, and what happens when Matinee can't
answer. Matinee's answers come from tests/fixtures/matinee/ (people.json has four, people_five.json five); the names
are made up."""
import pytest

import app

FIVE = ["Avery", "Blake", "Casey", "Drew", "Emery"]


def names(client):
    return [p["name"] for p in client.get("/api/people").get_json()]


def test_sync_people_adds_five_and_is_idempotent(client, matinee_fixtures):
    matinee_fixtures.people_file = "people_five.json"
    r = client.post("/api/people/sync")
    assert r.status_code == 200
    body = r.get_json()
    assert (body["added"], body["updated"]) == (5, 0)
    assert [(p["name"], p["kind"], p["color"], p["sort_order"]) for p in body["people"]] == [
        ("Avery", "adult", "green", 0), ("Blake", "adult", "blue", 1), ("Casey", "kid", "red", 2),
        ("Drew", "kid", "pink", 3), ("Emery", "adult", "purple", 4)]
    again = client.post("/api/people/sync").get_json()
    assert (again["added"], again["updated"]) == (0, 0) and names(client) == FIVE


def test_sync_updates_by_name_ignoring_case_and_keeps_local_people(app_ctx, matinee_fixtures):
    con = app.get_db()
    con.execute("INSERT INTO people (name, kind, color, sort_order) VALUES ('AVERY', 'kid', 'purple', 9)")
    con.execute("INSERT INTO people (name, kind, color, sort_order) VALUES ('Grandma Visiting', 'adult', 'red', 10)")
    con.commit()
    assert app.people.sync_from_matinee(con, app.matinee.client()) == {"added": 3, "updated": 1}
    rows = {r["name"]: (r["kind"], r["color"], r["sort_order"]) for r in con.execute("SELECT * FROM people")}
    assert rows["AVERY"] == ("adult", "green", 0) and "Avery" not in rows       # one row, kept under its first spelling
    assert rows["Grandma Visiting"] == ("adult", "red", 10)                     # only here: never touched
    assert con.execute("SELECT count(*) FROM people").fetchone()[0] == 5


def test_sync_skips_entries_it_cannot_use(app_ctx):
    class Odd:
        def people(self):
            return [{"name": "Real", "kind": "kid", "color": "chartreuse", "sort_order": 2},
                    {"name": "", "kind": "adult", "color": "red", "sort_order": 0},
                    {"name": "Robot", "kind": "robot", "color": "red", "sort_order": 1},
                    {"kind": "adult", "color": "red"}]
    con = app.get_db()
    assert app.people.sync_from_matinee(con, Odd()) == {"added": 1, "updated": 0}
    assert [tuple(r) for r in con.execute("SELECT name, kind, color, sort_order FROM people")] == [("Real", "kid", "green", 2)]


@pytest.mark.parametrize("error", [None, 503, 401], ids=["refused", "5xx", "wrong key"])
def test_sync_when_matinee_cannot_answer_is_a_502_and_changes_nothing(client, matinee_down, error):
    if error:
        matinee_down.error = error
    r = client.post("/api/people/sync")
    assert r.status_code == 502 and r.get_json()["error"]
    assert names(client) == []


def test_sync_with_no_matinee_key_says_so(client):
    r = client.post("/api/people/sync")
    assert r.status_code == 502 and "MATINEE_API_KEY" in r.get_json()["error"]


def test_first_run_copies_people_from_matinee(client, matinee_fixtures):
    assert names(client) == ["Avery", "Blake", "Casey", "Drew"]
    n = len(matinee_fixtures.calls)
    assert names(client) == ["Avery", "Blake", "Casey", "Drew"] and len(matinee_fixtures.calls) == n   # only when empty


def test_first_run_with_matinee_down_is_an_empty_list_and_leaves_matinee_alone_for_a_minute(client, matinee_down):
    assert client.get("/api/people").get_json() == []
    assert client.get("/api/people").get_json() == [] and matinee_down.calls == 1


def test_first_run_with_no_key_makes_no_call(client):
    assert client.get("/api/people").get_json() == []       # the no-network fixture would fail the test on any call


def test_local_only_person_allowed(client, matinee_fixtures):
    r = client.post("/api/people", json={"name": "  Grandpa Visiting ", "kind": "adult"})
    assert r.status_code == 201
    person = r.get_json()
    assert person["name"] == "Grandpa Visiting" and person["kind"] == "adult" and person["color"] in app.people.COLORS
    assert names(client) == ["Grandpa Visiting"]                 # a non-empty list: no first-run copy from Matinee
    matinee_fixtures.people_file = "people_five.json"
    body = client.post("/api/people/sync").get_json()
    assert body["added"] == 5 and sorted(names(client)) == sorted(FIVE + ["Grandpa Visiting"])   # sync keeps him


def test_a_new_person_takes_the_next_colour_and_place(client):
    a = client.post("/api/people", json={"name": "One"}).get_json()
    b = client.post("/api/people", json={"name": "Two", "kind": "kid"}).get_json()
    assert (a["color"], b["color"]) == ("green", "blue") and b["sort_order"] == a["sort_order"] + 1 and b["kind"] == "kid"


@pytest.mark.parametrize("body, status", [
    ({"name": ""}, 400), ({"name": "   "}, 400), ({}, 400), ({"name": 5}, 400), ({"name": "x" * 41}, 400),
    ({"name": "Ok", "kind": "robot"}, 400), ({"name": "Ok", "color": "chartreuse"}, 400), ([], 400),
], ids=str)
def test_bad_person_is_400(client, body, status):
    assert client.post("/api/people", json=body).status_code == status
    assert names(client) == []


def test_duplicate_name_is_409_ignoring_case(client):
    assert client.post("/api/people", json={"name": "Nana"}).status_code == 201
    assert client.post("/api/people", json={"name": "nana"}).status_code == 409
    assert names(client) == ["Nana"]
