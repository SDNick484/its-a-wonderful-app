"""Keeping the family rating in step with Matinee (spec §8.2, plan Task 9; Review Focus 1: Matinee down during a rating;
Review Focus 4: a rating edit that empties the mean never sends null). Matinee answers from the FakeMatinee in conftest,
which keeps a rating it is sent; a test changes `user_rating[1]` to stand for someone editing the rating in Matinee.
Elf is owned (Matinee title 1, rated 9.0); Klaus is not. The five people have made-up names."""
import urllib.error
import urllib.request

import pytest

import app
from test_matinee_client import refresh_cli

ELF, KLAUS = 10719, 508439


@pytest.fixture
def fam(client, matinee_fixtures):
    """Five people copied from Matinee, Elf (owned, Matinee says 9.0, ownership just refreshed) and Klaus (not owned,
    refreshed too). Returns ids and the FakeMatinee; the people sync's own calls are cleared."""
    matinee_fixtures.people_file = "people_five.json"
    client.post("/api/people/sync")
    with app.app.app_context():
        con = app.get_db()
        elf = con.execute("INSERT INTO movies (tmdb_id, title) VALUES (?, 'Elf')", (ELF,)).lastrowid
        klaus = con.execute("INSERT INTO movies (tmdb_id, title) VALUES (?, 'Klaus')", (KLAUS,)).lastrowid
        con.commit()
        app.movies.refresh_ownership(con, elf)
        app.movies.refresh_ownership(con, klaus)
    matinee_fixtures.calls.clear()
    people = [p["id"] for p in client.get("/api/people").get_json()]
    return {"elf": elf, "klaus": klaus, "people": people, "matinee": matinee_fixtures}


def rate(client, fam, movie, values):
    """Rate a movie for the first len(values) people (None clears); the last answer."""
    for person, value in zip(fam["people"], values):
        r = client.put(f"/api/movies/{movie}/ratings/{person}", json={"rating": value})
        assert r.status_code == 200, r.get_json()
    return r.get_json()


def puts(fam):
    """The ratings sent to Matinee, in order."""
    return [body["rating"] for method, _path, body in fam["matinee"].calls if method == "PUT"]


def row(movie_id):
    with app.app.app_context():
        return dict(app.get_db().execute("SELECT * FROM matinee_sync WHERE movie_id=?", (movie_id,)).fetchone())


def refresh(movie_id):
    """What the detail view, an add or the nightly job does: ask Matinee about ownership again."""
    with app.app.app_context():
        app.movies.refresh_ownership(app.get_db(), movie_id)


def detail(client, movie_id):
    return client.get(f"/api/movies/{movie_id}").get_json()


def shown(movie_id):
    with app.app.app_context():
        return app.sync.display_rating(app.get_db(), movie_id)


def choose(client, movie_id, choice):
    return client.post(f"/api/movies/{movie_id}/rating-conflict", json={"choice": choice})


def matinee_goes_down(monkeypatch, fam, error=None):
    """From now on every Matinee call fails with `error` (a refused connection by default); returns a list that counts
    the attempts. matinee_comes_back() undoes it."""
    tried = []

    def down(req, timeout=None):
        tried.append(req.get_method())
        raise error or urllib.error.URLError(ConnectionRefusedError())

    monkeypatch.setattr(urllib.request, "urlopen", down)
    return tried


def matinee_comes_back(monkeypatch, fam):
    monkeypatch.setattr(urllib.request, "urlopen", fam["matinee"])
    monkeypatch.setattr(app, "_matinee_failed_at", None)     # as if the backoff had run out


def conflict_on_elf(client, fam):
    """Elf rated 8.5, 9, 10, 9, 8 (8.9, Matinee told 9.0), then someone sets 7.0 in Matinee and a refresh sees it."""
    rate(client, fam, fam["elf"], [8.5, 9, 10, 9, 8])
    fam["matinee"].user_rating[1] = 7.0
    refresh(fam["elf"])
    assert row(fam["elf"])["conflict_rating"] == 7.0
    fam["matinee"].calls.clear()


# ------------------------------------------------------------------------------------------------ spec §8.2 scenarios
def test_before_anyone_rates_shows_matinee_9(client, fam):
    assert shown(fam["elf"]) == 9.0
    elf = detail(client, fam["elf"])
    assert (elf["family_rating"], elf["rating_source"], elf["family"]["mean"]) == (9.0, "matinee", None)
    assert elf["rating_conflict"] is None and elf["rating_pending"] is False
    assert row(fam["elf"])["rating_owner"] == "matinee" and puts(fam) == []


def test_first_rating_takes_ownership_and_pushes_rounded_mean(client, fam):
    body = rate(client, fam, fam["elf"], [8.5, 9, 10, 9, 8])
    assert (body["family_rating"], body["rating_source"]) == (8.9, "family")
    assert shown(fam["elf"]) == 8.9
    assert puts(fam)[-1] == 9.0                                   # 8.9 to the nearest 0.5
    assert fam["matinee"].calls[-1] == ("PUT", "/admin/api/titles/1/rating", {"rating": 9.0})
    assert all((v * 2) % 1 == 0 for v in puts(fam))               # Matinee only ever gets 0.5 steps
    s = row(fam["elf"])
    assert (s["rating_owner"], s["pushed_rating"], s["matinee_rating"], s["conflict_rating"]) == ("wonderful", 9.0, 9.0, None)
    assert body["rating_pending"] is False
    n = len(puts(fam))
    rate(client, fam, fam["elf"], [8.5])                           # the same rating again: nothing new to tell Matinee
    assert len(puts(fam)) == n


def test_the_first_rating_pushes_without_asking_and_later_ones_read_matinee_first(client, fam):
    rate(client, fam, fam["elf"], [8])
    assert [(m, p) for m, p, _b in fam["matinee"].calls] == [("PUT", "/admin/api/titles/1/rating")]   # taking over
    fam["matinee"].calls.clear()
    rate(client, fam, fam["elf"], [9])
    assert [(m, p) for m, p, _b in fam["matinee"].calls] == [("GET", "/admin/api/titles/1"),
                                                             ("PUT", "/admin/api/titles/1/rating")]


def test_not_owned_never_pushes(client, fam):
    body = rate(client, fam, fam["klaus"], [8, 9, 10, 8, 8])
    assert body["family_rating"] == 8.6 and shown(fam["klaus"]) == 8.6
    assert fam["matinee"].calls == []
    assert row(fam["klaus"])["rating_owner"] == "wonderful" and row(fam["klaus"])["pushed_rating"] is None
    refresh(fam["klaus"])                                          # still not owned: still nothing
    assert puts(fam) == [] and body["rating_pending"] is False


def test_a_movie_never_checked_with_matinee_is_not_pushed(client, fam):
    with app.app.app_context():
        con = app.get_db()
        movie = con.execute("INSERT INTO movies (tmdb_id, title) VALUES (999, 'Unchecked')").lastrowid
        con.commit()
    assert rate(client, fam, movie, [7])["family_rating"] == 7 and fam["matinee"].calls == []


def test_a_tv_special_is_never_pushed(client, fam):
    with app.app.app_context():
        con = app.get_db()
        movie = con.execute("INSERT INTO movies (tmdb_id, tmdb_type, title) VALUES (?, 'tv', 'Special')", (ELF,)).lastrowid
        con.commit()
        app.movies.refresh_ownership(con, movie)
    rate(client, fam, movie, [7])
    assert fam["matinee"].calls == []


def test_matinee_changed_after_push_sets_conflict_and_does_not_overwrite(client, fam):
    rate(client, fam, fam["elf"], [8.5, 9, 10, 9, 8])
    fam["matinee"].user_rating[1] = 7.0                            # someone rates it 7 in Matinee
    fam["matinee"].calls.clear()
    refresh(fam["elf"])
    assert puts(fam) == []                                         # Matinee's 7 is left alone
    s = row(fam["elf"])
    assert (s["conflict_rating"], s["matinee_rating"], s["pushed_rating"], s["rating_owner"]) == (7.0, 7.0, 9.0, "wonderful")
    elf = detail(client, fam["elf"])
    assert elf["rating_conflict"] == {"matinee": 7.0, "ours": 8.9}
    assert (elf["family_rating"], elf["rating_source"]) == (8.9, "family")    # ours shows until the family chooses
    rate(client, fam, fam["elf"], [10])                            # a new rating while the notice is open: still no push
    assert puts(fam) == [] and detail(client, fam["elf"])["rating_conflict"] == {"matinee": 7.0, "ours": 9.2}
    refresh(fam["elf"])                                            # the next refresh keeps the notice, pushes nothing
    assert puts(fam) == [] and row(fam["elf"])["conflict_rating"] == 7.0
    fam["matinee"].user_rating[1] = 6.5                            # Matinee moves again: the notice follows it
    refresh(fam["elf"])
    assert row(fam["elf"])["conflict_rating"] == 6.5 and puts(fam) == []


def test_a_rating_change_reads_matinee_first_and_never_overwrites_a_change(client, fam):
    rate(client, fam, fam["elf"], [8])
    fam["matinee"].user_rating[1] = 6.0                            # changed in Matinee since our last look
    fam["matinee"].calls.clear()
    rate(client, fam, fam["elf"], [9])
    assert puts(fam) == [] and row(fam["elf"])["conflict_rating"] == 6.0
    assert detail(client, fam["elf"])["rating_conflict"] == {"matinee": 6.0, "ours": 9.0}


def test_matinee_coming_round_to_our_rating_ends_the_conflict(client, fam):
    conflict_on_elf(client, fam)
    fam["matinee"].user_rating[1] = 9.0
    refresh(fam["elf"])
    s = row(fam["elf"])
    assert (s["conflict_rating"], s["pushed_rating"]) == (None, 9.0) and puts(fam) == []


def test_matinee_agreeing_by_itself_is_not_a_conflict(client, fam):
    rate(client, fam, fam["elf"], [8])
    fam["matinee"].user_rating[1] = 9.0
    fam["matinee"].calls.clear()
    rate(client, fam, fam["elf"], [9])                             # Matinee already says 9: nothing to write
    s = row(fam["elf"])
    assert (s["conflict_rating"], s["pushed_rating"]) == (None, 9.0) and puts(fam) == []


def test_use_matinee_reverts_owner(client, fam):
    conflict_on_elf(client, fam)
    r = choose(client, fam["elf"], "matinee")
    assert r.status_code == 200
    body = r.get_json()
    assert (body["family_rating"], body["rating_source"], body["rating_conflict"]) == (7.0, "matinee", None)
    assert body["family"]["mean"] == 8.9                           # the person ratings stay
    s = row(fam["elf"])
    assert (s["rating_owner"], s["conflict_rating"]) == ("matinee", None) and puts(fam) == []
    refresh(fam["elf"])                                            # Matinee owns it again: a refresh changes nothing
    assert puts(fam) == [] and row(fam["elf"])["conflict_rating"] is None
    rate(client, fam, fam["elf"], [10])                            # until someone rates again: the family takes over
    assert row(fam["elf"])["rating_owner"] == "wonderful" and puts(fam) == [9.0]   # mean 9.2


def test_use_ours_pushes_ours(client, fam):
    conflict_on_elf(client, fam)
    body = choose(client, fam["elf"], "ours").get_json()
    assert body["rating_conflict"] is None and body["rating_pending"] is False
    assert puts(fam) == [9.0]
    s = row(fam["elf"])
    assert (s["rating_owner"], s["pushed_rating"], s["matinee_rating"], s["conflict_rating"]) == ("wonderful", 9.0, 9.0, None)


def test_dismiss_leaves_both_alone_until_the_next_change(client, fam):
    conflict_on_elf(client, fam)
    body = choose(client, fam["elf"], "dismiss").get_json()
    assert body["rating_conflict"] is None and body["rating_pending"] is False and body["family_rating"] == 8.9
    refresh(fam["elf"])                                            # Matinee still says 7: no notice again, no push
    assert row(fam["elf"])["conflict_rating"] is None and puts(fam) == []
    with app.app.app_context():
        assert fam["elf"] not in app.movies.ownership_due(app.get_db())
    fam["matinee"].user_rating[1] = 6.0                            # but a new change in Matinee is a new conflict
    refresh(fam["elf"])
    assert row(fam["elf"])["conflict_rating"] == 6.0 and puts(fam) == []
    choose(client, fam["elf"], "dismiss")
    rate(client, fam, fam["elf"], [10, 10])                        # and a new family rating (9.4) is the family's again
    assert puts(fam) == [9.5]


def test_settling_with_no_conflict_open_does_nothing(client, fam):
    rate(client, fam, fam["elf"], [8])
    before = row(fam["elf"])
    fam["matinee"].calls.clear()
    for choice in ("ours", "matinee", "dismiss"):
        assert choose(client, fam["elf"], choice).status_code == 200
    assert row(fam["elf"]) == before and fam["matinee"].calls == []


@pytest.mark.parametrize("body", [{"choice": "both"}, {}, None, {"choice": None}, ["ours"]], ids=repr)
def test_a_bad_choice_is_400(client, fam, body):
    conflict_on_elf(client, fam)
    r = client.post(f"/api/movies/{fam['elf']}/rating-conflict", json=body)
    assert r.status_code == 400 and r.get_json()["error"]
    assert row(fam["elf"])["conflict_rating"] == 7.0


def test_settling_an_unknown_movie_is_404(client, fam):
    assert choose(client, 999, "ours").status_code == 404


def test_bought_later_pushes_when_matinee_unrated_else_conflict(client, fam):
    rate(client, fam, fam["klaus"], [8, 9, 10, 8, 8])              # 8.6, rated while not owned: nothing sent
    assert fam["matinee"].calls == []
    fam["matinee"].owned_files[KLAUS] = "owned_elf.json"           # bought on Blu-ray: Matinee title 1 now
    fam["matinee"].user_rating[1] = None                           # and Matinee has no rating for it
    refresh(fam["klaus"])
    assert puts(fam) == [8.5]                                      # 8.6 to the nearest 0.5
    s = row(fam["klaus"])
    assert (s["rating_owner"], s["pushed_rating"], s["conflict_rating"]) == ("wonderful", 8.5, None)


def test_bought_later_with_a_different_matinee_rating_raises_the_notice(client, fam):
    rate(client, fam, fam["klaus"], [8, 9, 10, 8, 8])
    fam["matinee"].owned_files[KLAUS] = "owned_elf.json"           # Matinee already rates it 9.0
    refresh(fam["klaus"])
    assert puts(fam) == []
    s = row(fam["klaus"])
    assert (s["rating_owner"], s["conflict_rating"], s["pushed_rating"]) == ("wonderful", 9.0, None)
    assert detail(client, fam["klaus"])["rating_conflict"] == {"matinee": 9.0, "ours": 8.6}
    assert shown(fam["klaus"]) == 8.6


def test_bought_later_with_the_same_rating_just_settles(client, fam):
    rate(client, fam, fam["klaus"], [9])
    fam["matinee"].owned_files[KLAUS] = "owned_elf.json"           # 9.0 both sides
    refresh(fam["klaus"])
    s = row(fam["klaus"])
    assert puts(fam) == [] and (s["conflict_rating"], s["pushed_rating"]) == (None, 9.0)


def test_bought_later_with_no_ratings_leaves_matinee_in_charge(client, fam):
    fam["matinee"].owned_files[KLAUS] = "owned_elf.json"
    refresh(fam["klaus"])
    assert puts(fam) == [] and shown(fam["klaus"]) == 9.0 and row(fam["klaus"])["rating_owner"] == "matinee"


# ------------------------------------------------------------------------------------------------ Review Focus 4
def test_null_mean_never_pushed(client, fam):
    rate(client, fam, fam["elf"], [8])
    sent = puts(fam)
    assert sent == [8.0]
    body = rate(client, fam, fam["elf"], [None])                   # clear the only rating
    assert body["family"]["mean"] is None and body["family_rating"] is None and body["rating_pending"] is False
    assert puts(fam) == sent and None not in puts(fam)
    refresh(fam["elf"])
    assert puts(fam) == sent
    assert all(b is None or b.get("rating") is not None for _m, _p, b in fam["matinee"].calls)


def test_an_owed_push_is_dropped_when_the_ratings_are_cleared(client, fam, monkeypatch):
    rate(client, fam, fam["elf"], [8])
    matinee_goes_down(monkeypatch, fam)
    rate(client, fam, fam["elf"], [10])                            # owed: 10
    rate(client, fam, fam["elf"], [None])                          # and then nobody has a rating
    matinee_comes_back(monkeypatch, fam)
    fam["matinee"].calls.clear()
    with app.app.app_context():
        assert fam["elf"] not in app.movies.ownership_due(app.get_db())
    refresh(fam["elf"])
    assert puts(fam) == []


@pytest.mark.parametrize("bad", [7.3, 11], ids=repr)
def test_a_refused_rating_pushes_nothing(client, fam, bad):
    r = client.put(f"/api/movies/{fam['elf']}/ratings/{fam['people'][0]}", json={"rating": bad})
    assert r.status_code == 400 and fam["matinee"].calls == [] and row(fam["elf"])["rating_owner"] == "matinee"


# ------------------------------------------------------------------------------------------------ Review Focus 1
@pytest.mark.parametrize("error", [urllib.error.URLError(ConnectionRefusedError()), TimeoutError(),
                                   urllib.error.HTTPError("http://movies.example.com", 502, "Bad Gateway", {}, None)],
                         ids=["refused", "timeout", "502"])
def test_push_failure_marks_pending_and_refresh_retries(client, fam, monkeypatch, error):
    tried = matinee_goes_down(monkeypatch, fam, error)
    body = rate(client, fam, fam["elf"], [8.5, 9, 10, 9, 8])      # the app still answers
    assert body["family_rating"] == 8.9 and body["rating_pending"] is True
    assert tried == ["PUT"]                                        # one try; then it leaves Matinee alone for a while
    s = row(fam["elf"])
    assert (s["rating_owner"], s["pushed_rating"], s["conflict_rating"]) == ("wonderful", None, None)
    assert detail(client, fam["elf"])["rating_pending"] is True
    with app.app.app_context():
        assert fam["elf"] in app.movies.ownership_due(app.get_db())    # checked today, but a push is owed
    matinee_comes_back(monkeypatch, fam)
    with app.app.app_context():
        assert refresh_cli.refresh_ownership(app.get_db(), say=lambda m: None) == (1, 0, 0)
    assert puts(fam) == [9.0]
    s = row(fam["elf"])
    assert (s["pushed_rating"], s["matinee_rating"], s["conflict_rating"]) == (9.0, 9.0, None)
    assert detail(client, fam["elf"])["rating_pending"] is False
    with app.app.app_context():
        assert fam["elf"] not in app.movies.ownership_due(app.get_db())


def test_a_wrong_key_on_a_push_marks_pending_too(client, fam, monkeypatch):
    monkeypatch.setattr(app, "MATINEE_API_KEY", "not-the-key")
    assert rate(client, fam, fam["elf"], [8])["rating_pending"] is True
    assert row(fam["elf"])["pushed_rating"] is None


def test_a_failed_retry_after_matinee_changed_raises_the_notice_instead(client, fam, monkeypatch):
    rate(client, fam, fam["elf"], [8])                             # Matinee told 8.0
    matinee_goes_down(monkeypatch, fam)
    rate(client, fam, fam["elf"], [10])                            # owed: 10, not sent
    matinee_comes_back(monkeypatch, fam)
    fam["matinee"].user_rating[1] = 6.0                            # meanwhile someone set 6 in Matinee
    fam["matinee"].calls.clear()
    refresh(fam["elf"])
    assert puts(fam) == [] and row(fam["elf"])["conflict_rating"] == 6.0


def test_a_failed_takeover_is_retried_over_matinees_old_rating(client, fam, monkeypatch):
    matinee_goes_down(monkeypatch, fam)
    rate(client, fam, fam["elf"], [7])                             # taking over from Matinee's 9.0 failed
    matinee_comes_back(monkeypatch, fam)
    refresh(fam["elf"])                                            # Matinee still says 9.0, as when we took over
    assert puts(fam) == [7.0] and row(fam["elf"])["conflict_rating"] is None


def test_use_ours_with_matinee_down_stays_owed(client, fam, monkeypatch):
    conflict_on_elf(client, fam)
    matinee_goes_down(monkeypatch, fam)
    body = choose(client, fam["elf"], "ours").get_json()
    assert body["rating_conflict"] is None and body["rating_pending"] is True
    matinee_comes_back(monkeypatch, fam)
    refresh(fam["elf"])                                            # Matinee still says the 7 the family overruled
    assert puts(fam) == [9.0] and row(fam["elf"])["conflict_rating"] is None


def test_with_no_matinee_key_rating_still_works_and_sends_nothing(client, fam, monkeypatch):
    monkeypatch.setattr(app, "MATINEE_API_KEY", "")
    assert rate(client, fam, fam["elf"], [8])["family_rating"] == 8 and fam["matinee"].calls == []
