"""Per-person ratings and the family rating (spec §8.2, §11; plan Task 8; Review Focus 4: a rating edit that empties or
breaks the mean). Names are made up: Avery, Blake, Casey, Drew, Emery rate."""
import pytest

import app
from conftest import MATINEE_FIXTURES  # noqa: F401  (the people fixtures are served by matinee_fixtures)


@pytest.fixture
def family(client, matinee_fixtures):
    """Five people (copied from Matinee on the way in) and two movies, one owned by Matinee (Elf, id 1) and one not."""
    matinee_fixtures.people_file = "people_five.json"
    client.post("/api/people/sync")
    with app.app.app_context():
        con = app.get_db()
        elf = con.execute("INSERT INTO movies (tmdb_id, title) VALUES (10719, 'Elf')").lastrowid
        klaus = con.execute("INSERT INTO movies (tmdb_id, title) VALUES (508439, 'Klaus')").lastrowid
        con.commit()
    return {"elf": elf, "klaus": klaus, "people": client.get("/api/people").get_json()}


def rate(client, movie, person, rating):
    return client.put(f"/api/movies/{movie}/ratings/{person}", json={"rating": rating})


def rate_all(client, fam, movie, values):
    for p, v in zip(fam["people"], values):
        assert rate(client, movie, p["id"], v).status_code == 200


def test_klaus_mean_8_6(client, family):
    rate_all(client, family, family["klaus"], [8, 9, 10, 8, 8])
    r = rate(client, family["klaus"], family["people"][0]["id"], 8)
    body = r.get_json()
    assert body["family"]["mean"] == 8.6 and body["family_rating"] == 8.6 and body["rating_source"] == "family"
    assert [(p["name"], p["rating"]) for p in body["family"]["by_person"]] == [
        ("Avery", 8), ("Blake", 9), ("Casey", 10), ("Drew", 8), ("Emery", 8)]
    assert [p["color"] for p in body["family"]["by_person"]] == ["green", "blue", "red", "pink", "purple"]
    assert app.ratings.mean_of([8.5, 9, 10, 9, 8]) == 8.9                              # the Elf scenario


def test_the_mean_is_to_one_decimal_with_ties_up(app_ctx):
    mean = app.ratings.mean_of
    assert mean([8, 8.5]) == 8.3 and mean([8, 8, 8.5]) == 8.2 and mean([7]) == 7.0 and mean([0, 0.5]) == 0.3
    assert mean([]) is None and mean([None]) is None


def test_clearing_last_rating_gives_null_mean(client, family):          # Review Focus 4
    a, b = family["people"][0]["id"], family["people"][1]["id"]
    rate(client, family["klaus"], a, 8)
    rate(client, family["klaus"], b, 9.5)
    assert rate(client, family["klaus"], a, None).get_json()["family"]["mean"] == 9.5
    body = rate(client, family["klaus"], b, None).get_json()
    assert body["family"]["mean"] is None and body["family_rating"] is None and body["rating_source"] is None
    assert [p["rating"] for p in body["family"]["by_person"]] == [None] * 5
    movie = next(m for m in client.get("/api/movies").get_json() if m["id"] == family["klaus"])
    assert movie["family_rating"] is None
    with app.app.app_context():
        assert app.get_db().execute("SELECT count(*) FROM person_ratings").fetchone()[0] == 0
    assert rate(client, family["klaus"], b, None).status_code == 200            # clearing nothing is fine


@pytest.mark.parametrize("bad", [7.3, 11, -0.5, 10.5, "abc", True, [8], {"x": 1}, float("nan")], ids=repr)
def test_off_step_is_400(client, family, bad):
    a = family["people"][0]["id"]
    rate(client, family["klaus"], a, 8)
    r = rate(client, family["klaus"], a, bad)
    assert r.status_code == 400 and "0.5 steps" in r.get_json()["error"]
    assert client.get(f"/api/movies/{family['klaus']}").get_json()["family"]["mean"] == 8      # unchanged


def test_a_body_without_a_rating_is_400(client, family):
    for body in ({}, [], None, {"score": 8}):
        assert client.put(f"/api/movies/{family['klaus']}/ratings/{family['people'][0]['id']}", json=body).status_code == 400


@pytest.mark.parametrize("ok", [0, 0.0, 0.5, 5, "7.5", 10], ids=repr)
def test_every_half_step_from_0_to_10_is_accepted(client, family, ok):
    r = rate(client, family["klaus"], family["people"][0]["id"], ok)
    assert r.status_code == 200 and r.get_json()["family"]["mean"] == float(ok)


def test_unknown_movie_or_person_is_404(client, family):
    assert rate(client, 999, family["people"][0]["id"], 8).status_code == 404
    assert rate(client, family["klaus"], 999, 8).status_code == 404


def test_changing_a_rating_replaces_it(client, family):
    a = family["people"][0]["id"]
    rate(client, family["klaus"], a, 6)
    assert rate(client, family["klaus"], a, 9).get_json()["family"]["mean"] == 9
    with app.app.app_context():
        assert app.get_db().execute("SELECT count(*) FROM person_ratings").fetchone()[0] == 1


def test_a_rating_is_per_movie(client, family):
    a = family["people"][0]["id"]
    rate(client, family["klaus"], a, 6)
    rate(client, family["elf"], a, 9)
    assert client.get(f"/api/movies/{family['klaus']}").get_json()["family"]["mean"] == 6


def test_unrated_people_are_listed_with_a_null_rating(client, family):
    rate(client, family["klaus"], family["people"][2]["id"], 7)
    by = client.get(f"/api/movies/{family['klaus']}").get_json()["family"]["by_person"]
    assert [p["rating"] for p in by] == [None, None, 7, None, None]


def test_the_list_and_the_detail_carry_the_shown_rating(client, family):
    rate_all(client, family, family["klaus"], [8, 9, 10, 8, 8])
    listed = {m["id"]: m for m in client.get("/api/movies").get_json()}
    assert listed[family["klaus"]]["family_rating"] == 8.6 and listed[family["klaus"]]["rating_source"] == "family"
    assert listed[family["elf"]]["family_rating"] is None
    assert client.get(f"/api/movies/{family['klaus']}").get_json()["family_rating"] == 8.6


def test_before_anyone_rates_here_the_poster_shows_matinees_rating(client, family):
    with app.app.app_context():
        app.movies.refresh_ownership(app.get_db(), family["elf"])       # Elf: owned, Matinee rating 9.0
    elf = client.get(f"/api/movies/{family['elf']}").get_json()
    assert (elf["family_rating"], elf["rating_source"]) == (9.0, "matinee")
    with app.app.app_context():                                         # Matinee's rating is what shows while it owns the rating
        con = app.get_db()
        con.execute("UPDATE matinee_sync SET rating_owner='wonderful' WHERE movie_id=?", (family["elf"],))
        con.commit()
    rate_all(client, family, family["elf"], [8.5, 9, 10, 9, 8])
    elf = client.get(f"/api/movies/{family['elf']}").get_json()
    assert (elf["family_rating"], elf["rating_source"]) == (8.9, "family") and elf["family"]["mean"] == 8.9


def test_a_movie_matinee_does_not_own_shows_the_family_mean_whatever_the_owner_flag(client, family):
    with app.app.app_context():
        con = app.get_db()
        con.execute("INSERT INTO matinee_sync (movie_id) VALUES (?)", (family["klaus"],))      # rating_owner defaults to 'matinee'
        con.commit()
    rate(client, family["klaus"], family["people"][0]["id"], 8)
    assert client.get(f"/api/movies/{family['klaus']}").get_json()["family_rating"] == 8


def test_every_change_tells_the_sync_hook(client, family, monkeypatch):
    seen = []
    monkeypatch.setattr(app.sync, "after_rating_change", lambda con, movie_id: seen.append(movie_id))
    a = family["people"][0]["id"]
    rate(client, family["klaus"], a, 8)
    rate(client, family["klaus"], a, None)
    rate(client, family["klaus"], a, 7.3)                      # refused: no change, no hook
    assert seen == [family["klaus"], family["klaus"]]


def test_the_rating_hook_with_nothing_rated_does_nothing(app_ctx):
    assert app.sync.after_rating_change(app.get_db(), 1) is None


def test_removing_a_movie_takes_its_ratings(client, family):
    rate(client, family["klaus"], family["people"][0]["id"], 8)
    assert client.delete(f"/api/movies/{family['klaus']}").status_code == 200
    with app.app.app_context():
        assert app.get_db().execute("SELECT count(*) FROM person_ratings").fetchone()[0] == 0


def test_ratings_work_with_matinee_down(client, family, matinee_down):
    assert rate(client, family["klaus"], family["people"][0]["id"], 8).status_code == 200      # rating never needs Matinee
