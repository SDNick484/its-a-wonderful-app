"""Which kinds of copy Matinee holds for a movie (plan Task 1; Review Focus 4): movies.copy_kinds from the stored
columns, or, for a row stored before the upgrade, from the summary text; and check_ownership filling the columns."""
import pytest

import app

ELF = 10719
DISC_AND_DIGITAL = "Blu-ray · Digital HD (Movies Anywhere)"


@pytest.fixture
def con(app_ctx):
    return app_ctx.get_db()


def add_movie(con, tmdb_id=ELF, title="Elf"):
    cur = con.execute("INSERT INTO movies (tmdb_id, title) VALUES (?, ?)", (tmdb_id, title))
    con.commit()
    return cur.lastrowid


def store(con, movie_id, title_id, summary, physical=None, digital=None):
    con.execute("INSERT OR REPLACE INTO matinee_sync (movie_id, matinee_title_id, owned_summary, has_physical,"
                " has_digital) VALUES (?,?,?,?,?)", (movie_id, title_id, summary, physical, digital))
    con.commit()


@pytest.mark.parametrize("title_id, summary, physical, digital, expected", [
    (1, "Blu-ray", 1, 0, (True, False)),
    (1, "Digital HD (Movies Anywhere)", 0, 1, (False, True)),
    (1, "Blu-ray", 0, 1, (False, True)),                           # the columns win over the summary
    (1, "Blu-ray", 0, 0, (False, False)),
    (1, DISC_AND_DIGITAL, None, None, (True, True)),
    (1, "Digital HD (Movies Anywhere)", None, None, (False, True)),
    (1, "digital 4K", None, None, (False, True)),                  # case ignored
    (1, "VHS", None, None, (True, False)),
    (1, "4K UHD · DVD · Digital 4K", None, None, (True, True)),
    (1, None, None, None, (False, False)),
    (1, "", None, None, (False, False)),
    (None, "Blu-ray", None, None, (False, False)),                 # Matinee doesn't own it: the text is stale
    (None, None, 1, 1, (False, False)),
])
def test_copy_kinds_of_a_stored_row(con, title_id, summary, physical, digital, expected):
    movie = add_movie(con)
    store(con, movie, title_id, summary, physical, digital)
    assert app.movies.copy_kinds(con, movie) == expected


def test_no_row_is_no_copies(con):
    assert app.movies.copy_kinds(con, add_movie(con)) == (False, False)


def test_check_ownership_stores_the_kinds(con, matinee_fixtures):
    movie = add_movie(con)
    matinee_fixtures.owned_files[ELF] = "owned_disc_and_digital.json"
    app.movies.check_ownership(con, movie)
    row = con.execute("SELECT has_physical, has_digital FROM matinee_sync WHERE movie_id=?", (movie,)).fetchone()
    assert (row["has_physical"], row["has_digital"]) == (1, 1)
    matinee_fixtures.owned_files[ELF] = "owned_digital_only.json"
    app.movies.check_ownership(con, movie)
    row = con.execute("SELECT has_physical, has_digital FROM matinee_sync WHERE movie_id=?", (movie,)).fetchone()
    assert (row["has_physical"], row["has_digital"]) == (0, 1)


def test_not_owned_stores_zero_not_null(con, matinee_fixtures):
    movie = add_movie(con, 508439, "Klaus")
    app.movies.check_ownership(con, movie)
    row = con.execute("SELECT has_physical, has_digital FROM matinee_sync WHERE movie_id=?", (movie,)).fetchone()
    assert (row["has_physical"], row["has_digital"]) == (0, 0)
    assert app.movies.copy_kinds(con, movie) == (False, False)


def test_same_answer_before_and_after_the_check(con, matinee_fixtures):
    movie = add_movie(con)
    matinee_fixtures.owned_files[ELF] = "owned_disc_and_digital.json"
    store(con, movie, 1, DISC_AND_DIGITAL)                          # a v1 row: summary only, columns NULL
    assert app.movies.copy_kinds(con, movie) == (True, True)
    app.movies.check_ownership(con, movie)
    assert con.execute("SELECT has_physical FROM matinee_sync WHERE movie_id=?", (movie,)).fetchone()[0] == 1
    assert app.movies.copy_kinds(con, movie) == (True, True)


# ------------------------------------------------------------------------------------------------ the Fandango at Home id
FANDANGO = "fandango_at_home"


def stored(con, movie_id, service=FANDANGO):
    """The service_titles row for the movie and service, or None."""
    return con.execute("SELECT * FROM service_titles WHERE movie_id=? AND service=?", (movie_id, service)).fetchone()


def test_the_fandango_id_is_the_same_key_the_play_rule_uses():
    assert app.movies.FANDANGO == app.ha.FANDANGO == FANDANGO


def test_check_ownership_stores_the_fandango_id(con, matinee_fixtures):
    movie = add_movie(con)
    matinee_fixtures.owned_files[ELF] = "owned_digital_fandango.json"
    app.movies.check_ownership(con, movie)
    row = stored(con, movie)
    assert (row["title_id"], row["manual"]) == ("15429", 0) and row["checked_at"]
    assert app.titles.get(con, movie, FANDANGO) == "15429"


def test_a_later_check_that_reports_none_clears_it(con, matinee_fixtures):
    movie = add_movie(con)
    matinee_fixtures.owned_files[ELF] = "owned_digital_fandango.json"
    app.movies.check_ownership(con, movie)
    matinee_fixtures.owned_files[ELF] = "owned_digital_only.json"      # still owned digitally, no id any more
    app.movies.check_ownership(con, movie)
    assert app.titles.get(con, movie, FANDANGO) is None
    matinee_fixtures.owned_files[ELF] = "owned_digital_fandango.json"
    app.movies.check_ownership(con, movie)
    assert app.titles.get(con, movie, FANDANGO) == "15429"
    matinee_fixtures.owned_files[ELF] = "not_owned.json"               # and no longer owned at all
    app.movies.check_ownership(con, movie)
    assert app.titles.get(con, movie, FANDANGO) is None


def test_a_disc_alone_stores_no_fandango_id(con, matinee_fixtures):
    movie = add_movie(con)
    app.movies.check_ownership(con, movie)                              # owned_elf.json: a Blu-ray
    assert app.titles.get(con, movie, FANDANGO) is None


@pytest.mark.parametrize("error", [None, 502, 401])
def test_matinee_down_keeps_the_fandango_id(con, matinee_down, error):
    movie = add_movie(con)
    con.execute("INSERT INTO service_titles (movie_id, service, title_id, manual, checked_at) VALUES (?, ?, '15429', 0,"
                " '2026-11-01T00:00:00Z')", (movie, FANDANGO))
    con.commit()
    before = dict(stored(con, movie))
    if error:
        matinee_down.error = error
    app.movies.refresh_ownership(con, movie)
    assert matinee_down.calls == 1                                       # it was asked, and could not answer
    assert dict(stored(con, movie)) == before


def test_a_tv_entry_is_never_asked_and_gets_no_fandango_row(con, matinee_fixtures):
    cur = con.execute("INSERT INTO movies (tmdb_id, tmdb_type, title) VALUES (?, 'tv', 'A special')", (ELF,))
    con.commit()
    matinee_fixtures.owned_files[ELF] = "owned_digital_fandango.json"
    app.movies.check_ownership(con, cur.lastrowid)
    assert matinee_fixtures.calls == [] and stored(con, cur.lastrowid) is None


def test_the_netflix_row_is_left_alone(con, matinee_fixtures):
    movie = add_movie(con)
    con.execute("INSERT INTO service_titles (movie_id, service, title_id, manual, checked_at) VALUES (?, 'netflix', '80183187', 1, ?)",
                (movie, app.now_iso()))
    con.commit()
    matinee_fixtures.owned_files[ELF] = "owned_digital_fandango.json"
    app.movies.check_ownership(con, movie)
    assert (stored(con, movie, "netflix")["title_id"], stored(con, movie, "netflix")["manual"]) == ("80183187", 1)
    assert app.titles.get(con, movie) == "80183187" and app.titles.get(con, movie, FANDANGO) == "15429"
