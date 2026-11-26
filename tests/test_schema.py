"""The schema (spec §6, v2 adds the copy kinds), migrate(), and the shared helpers in common.py."""
import datetime as dt
import sqlite3

import pytest
from werkzeug.exceptions import HTTPException

import common
import db

TABLES = {"movies", "providers_cache", "services", "people", "person_ratings", "viewings", "viewing_people",
          "sessions", "matinee_sync", "ai_cache", "meta"}


def columns(con, table):
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def test_migrate_creates_every_table_and_is_idempotent(tmp_path):
    con = db.connect(tmp_path / "w.db"); db.migrate(con); db.migrate(con)
    names = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    assert {"movies","providers_cache","services","people","person_ratings","viewings",
            "viewing_people","sessions","matinee_sync","ai_cache","meta"} <= names
    assert con.execute("select v from meta where k='schema'").fetchone()[0] == "2"


def test_schema_version_is_two():
    assert db.SCHEMA_VERSION == "2"


V1_MATINEE_SYNC = """
CREATE TABLE matinee_sync (
  movie_id INTEGER PRIMARY KEY REFERENCES movies(id) ON DELETE CASCADE,
  matinee_title_id INTEGER,            -- NULL = not owned / not in Matinee
  owned_summary TEXT,
  location_path TEXT,
  matinee_rating REAL,
  matinee_last_watch TEXT,             -- newest watched_date Matinee has (for "Not watched this year")
  pushed_rating REAL,
  rating_owner TEXT NOT NULL DEFAULT 'matinee' CHECK (rating_owner IN ('matinee','wonderful')),
  conflict_rating REAL,
  checked_at TEXT
);
"""


def test_v1_database_gains_the_copy_columns(tmp_path):
    con = db.connect(tmp_path / "w.db")
    con.executescript(db.SCHEMA.split("CREATE TABLE IF NOT EXISTS matinee_sync")[0])   # v1 tables up to matinee_sync
    con.executescript(V1_MATINEE_SYNC)
    con.execute("INSERT INTO meta (k, v) VALUES ('schema', '1')")
    movie = con.execute("INSERT INTO movies (tmdb_id, title) VALUES (10719, 'Elf')").lastrowid
    con.execute("INSERT INTO matinee_sync (movie_id, matinee_title_id, owned_summary, location_path, matinee_rating,"
                " checked_at) VALUES (?, 1, 'Blu-ray', 'Family Room › Media Cabinet › Shelf 2', 9.0, '2026-11-19T07:26:02Z')",
                (movie,))
    con.commit()
    assert "has_physical" not in columns(con, "matinee_sync")
    before = tuple(con.execute("SELECT movie_id, matinee_title_id, owned_summary, location_path, matinee_rating,"
                               " checked_at FROM matinee_sync").fetchone())
    db.migrate(con); db.migrate(con)
    assert columns(con, "matinee_sync")[-2:] == ["has_physical", "has_digital"]
    row = con.execute("SELECT * FROM matinee_sync").fetchone()
    assert (row["has_physical"], row["has_digital"]) == (None, None)
    assert tuple(row[k] for k in ("movie_id", "matinee_title_id", "owned_summary", "location_path", "matinee_rating",
                                  "checked_at")) == before
    assert con.execute("SELECT count(*) FROM matinee_sync").fetchone()[0] == 1
    assert con.execute("SELECT v FROM meta WHERE k='schema'").fetchone()[0] == "2"


def test_the_whole_spec_schema_is_there_now(tmp_path):
    # Every column of spec §6 exists from v1; v2 adds only the two copy-kind columns on matinee_sync.
    con = db.connect(tmp_path / "w.db"); db.migrate(con)
    assert columns(con, "movies") == [
        "id", "tmdb_id", "tmdb_type", "title", "year", "runtime_min", "certification", "certification_override",
        "overview", "poster_path", "backdrop_path", "is_animated", "collection_id", "collection_name", "top_cast",
        "tmdb_vote", "parent_note", "added_by", "added_at", "meta_refreshed_at"]
    assert columns(con, "providers_cache") == ["movie_id", "data", "link", "fetched_at"]
    assert columns(con, "services") == ["key", "name", "tmdb_provider_ids", "status", "tv_source"]
    assert columns(con, "people") == ["id", "name", "kind", "color", "sort_order", "active"]
    assert columns(con, "person_ratings") == ["person_id", "movie_id", "rating", "updated_at"]
    assert columns(con, "viewings") == ["id", "movie_id", "started_on", "status", "watched_seconds", "guess",
                                        "finished_on", "matinee_watch_id", "updated_at"]
    assert columns(con, "viewing_people") == ["viewing_id", "person_id"]
    assert columns(con, "sessions") == ["id", "viewing_id", "tv_source", "started_at", "ended_at", "end_reason"]
    assert columns(con, "matinee_sync") == [
        "movie_id", "matinee_title_id", "owned_summary", "location_path", "matinee_rating", "matinee_last_watch",
        "pushed_rating", "rating_owner", "conflict_rating", "checked_at", "has_physical", "has_digital"]
    assert columns(con, "ai_cache") == ["q_norm", "list_hash", "result", "created_at"]
    assert set(r[0] for r in con.execute("select name from sqlite_master where type='table'")) == TABLES


def test_migrate_keeps_existing_rows(tmp_path):
    con = db.connect(tmp_path / "w.db"); db.migrate(con)
    con.execute("INSERT INTO movies (tmdb_id, title, year) VALUES (10719, 'Elf', 2003)")
    con.commit()
    db.migrate(con)
    assert con.execute("SELECT title FROM movies").fetchone()["title"] == "Elf"


def test_connect_has_rows_and_foreign_keys(tmp_path):
    con = db.connect(tmp_path / "w.db"); db.migrate(con)
    assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert isinstance(con.execute("SELECT 1 AS one").fetchone(), sqlite3.Row)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO person_ratings (person_id, movie_id, rating) VALUES (99, 99, 8)")


def test_schema_checks(tmp_path):
    con = db.connect(tmp_path / "w.db"); db.migrate(con)
    movie = con.execute("INSERT INTO movies (tmdb_id, title) VALUES (10719, 'Elf')").lastrowid
    with pytest.raises(sqlite3.IntegrityError):   # same TMDB entry twice
        con.execute("INSERT INTO movies (tmdb_id, title) VALUES (10719, 'Elf')")
    con.execute("INSERT INTO movies (tmdb_id, tmdb_type, title) VALUES (10719, 'tv', 'A TV special')")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO viewings (movie_id, started_on, status) VALUES (?, '2026-12-12', 'later')", (movie,))
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO matinee_sync (movie_id, rating_owner) VALUES (?, 'nobody')", (movie,))
    con.execute("INSERT INTO matinee_sync (movie_id) VALUES (?)", (movie,))
    assert con.execute("SELECT rating_owner FROM matinee_sync").fetchone()[0] == "matinee"
    # removing a movie takes its rows with it (spec §7.1)
    con.execute("DELETE FROM movies WHERE id=?", (movie,))
    assert con.execute("SELECT count(*) FROM matinee_sync").fetchone()[0] == 0


def test_init_db_makes_the_data_folders(app_ctx, tmp_path):
    assert (tmp_path / "wonderful.db").is_file()
    assert (tmp_path / "posters").is_dir() and (tmp_path / "art").is_dir()


# ------------------------------------------------------------------------------------------------- common.py
def test_round_half_up():
    assert [common.round_half_up(x) for x in (8.6, 8.25, 8.75, 8.9, 10.0)] == [8.5, 8.5, 9.0, 9.0, 10.0]


def test_round_half_up_on_real_means():
    # Spec §8.2: the Elf scenario (8.5, 9, 10, 9, 8 -> 8.9 -> 9.0) and means that land on a tie
    assert common.round_half_up(sum([8.5, 9, 10, 9, 8]) / 5) == 9.0
    assert common.round_half_up(sum([8, 8.5]) / 2) == 8.5          # 8.25
    assert common.round_half_up(sum([8.5, 9, 9, 8.5]) / 4) == 9.0   # 8.75
    assert common.round_half_up(0.0) == 0.0 and common.round_half_up(0.24) == 0.0


def test_validate_rating_rejects_off_steps(app_ctx):
    for bad in (7.3, 11, -1, True, "x"):
        with pytest.raises(HTTPException): common.validate_rating(bad)


def test_validate_rating_errors_are_400(app_ctx):
    for bad in (7.3, 10.5, float("nan"), float("inf"), [8]):
        with pytest.raises(HTTPException) as e:
            common.validate_rating(bad)
        assert e.value.response.status_code == 400
        assert e.value.response.get_json()["error"] == common.RATING_ERROR


def test_validate_rating_accepts_half_steps(app_ctx):
    assert [common.validate_rating(v) for v in (0, 0.5, "8.5", 10, 9.0)] == [0.0, 0.5, 8.5, 10.0, 9.0]
    assert common.validate_rating(None) is None and common.validate_rating("") is None


def test_clean():
    assert common.clean("  Elf ") == "Elf"
    assert common.clean("   ") is None and common.clean(None) is None
    assert common.clean(2003) == "2003"


def test_make_err_outside_a_request():
    r = common.make_err(404, "No such movie", reason="gone")
    assert r.status_code == 404 and r.get_json() == {"error": "No such movie", "reason": "gone"}


def test_today_uses_the_host_tz_not_utc(monkeypatch):
    zoneinfo = pytest.importorskip("zoneinfo")
    # UTC+14 and UTC-11 are a day apart for most of every day, so at least one differs from the UTC date.
    for zone in ("Pacific/Kiritimati", "Pacific/Pago_Pago"):
        try:
            tz = zoneinfo.ZoneInfo(zone)
        except zoneinfo.ZoneInfoNotFoundError:
            pytest.fail("no tzdata: install the tzdata package (the installer and CI do)")
        monkeypatch.setenv("TZ", zone)
        assert common.today() == dt.datetime.now(tz).date()


def test_today_with_an_unknown_zone_falls_back_to_local(monkeypatch):
    monkeypatch.setenv("TZ", "Nowhere/Atlantis")
    assert common.today() == dt.date.today()
