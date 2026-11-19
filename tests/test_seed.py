"""The starting list (spec §17, plan Task 3): data/seed-movies.json holds the 41 titles, and ops/seed-movies adds the
ones with a tmdb_id, idempotently. TMDB answers from the recorded fixtures; no network."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path

import app

ROOT = Path(__file__).resolve().parent.parent
SEED_FILE = ROOT / "data" / "seed-movies.json"
CERTS = {"G", "PG", "PG-13", "NR"}


def load_cli():
    """ops/seed-movies has no .py suffix, so load it by path."""
    loader = importlib.machinery.SourceFileLoader("seed_movies", str(ROOT / "ops" / "seed-movies"))
    spec = importlib.util.spec_from_loader("seed_movies", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


seed = load_cli()

ELF = {"tmdb_id": 10719, "tmdb_type": "movie", "title": "Elf", "year": 2003, "certification": "PG",
       "parent_note": None}
QUIET = {"tmdb_id": 900001, "tmdb_type": "movie", "title": "The Quiet Reindeer", "year": 1999,
         "certification": "NR", "parent_note": None}              # no US certification and runtime null in TMDB
TINSEL = {"tmdb_id": 900002, "tmdb_type": "tv", "title": "The Tinsel Express", "year": 2011, "certification": "G",
          "parent_note": None}                                      # a TV-only special
PRANCER = {"tmdb_id": None, "tmdb_type": None, "title": "Prancer", "year": 1989, "certification": "G",
           "parent_note": None}
UNRESOLVED = {"tmdb_id": None, "tmdb_type": None, "title": "Nonexistent Holiday Film", "year": 2001,
              "certification": "NR", "parent_note": None}


def write_seed(tmp_path, entries):
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def count_movies():
    with app.app.app_context():
        return app.get_db().execute("SELECT COUNT(*) FROM movies").fetchone()[0]


def test_seed_file_has_41_unique_entries_and_valid_certs():
    entries = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    assert len(entries) == 41
    assert len({(e["title"], e["year"]) for e in entries}) == 41
    ids = [(e["tmdb_type"], e["tmdb_id"]) for e in entries if e["tmdb_id"] is not None]
    assert len(ids) == len(set(ids))
    for e in entries:
        assert e["title"] and isinstance(e["year"], int), e
        assert (e["tmdb_id"] is None) == (e["tmdb_type"] is None), e      # an id always comes with its type
        assert e["tmdb_type"] in (None, "movie", "tv"), e
        assert e["certification"] in CERTS, e
    by_title = {e["title"]: e for e in entries}
    assert by_title["Four Christmases"]["certification"] == "PG-13"
    assert by_title["White Christmas"]["certification"] == "NR"
    assert by_title["A Loud House Christmas Movie: Naughty or Nice"]["certification"] == "NR"
    assert "Greg" in by_title["Diary of a Wimpy Kid Christmas: Cabin Fever"]["parent_note"]


def test_seed_is_idempotent(client, tmdb_fixtures, tmp_path, capsys):
    path = write_seed(tmp_path, [ELF, QUIET, TINSEL, UNRESOLVED])
    assert seed.main(["--file", str(path)]) == 0
    out = capsys.readouterr().out
    assert "added 3, skipped 1" in out and "1 still have no tmdb_id" in out
    assert count_movies() == 3
    assert seed.main(["--file", str(path)]) == 0           # running it again adds nothing
    assert "added 0, skipped 4" in capsys.readouterr().out
    assert count_movies() == 3


def test_resolve_finds_the_id_and_writes_it_back(client, tmdb_fixtures, tmp_path, capsys):
    path = write_seed(tmp_path, [PRANCER])
    assert seed.main(["--resolve", "--file", str(path)]) == 0
    assert "resolved Prancer (1989) to movie 14181" in capsys.readouterr().out
    saved = json.loads(path.read_text(encoding="utf-8"))[0]
    assert (saved["tmdb_id"], saved["tmdb_type"]) == (14181, "movie")
    assert count_movies() == 1


def test_resolve_miss_leaves_the_entry_unresolved(client, tmdb_fixtures, tmp_path, capsys):
    path = write_seed(tmp_path, [UNRESOLVED])
    assert seed.main(["--resolve", "--file", str(path)]) == 0
    assert "no TMDB match for Nonexistent Holiday Film" in capsys.readouterr().out
    assert json.loads(path.read_text(encoding="utf-8"))[0]["tmdb_id"] is None
    assert count_movies() == 0


def test_tmdb_error_is_reported_and_exits_1(client, tmdb_down, tmp_path, capsys):
    path = write_seed(tmp_path, [ELF, PRANCER])
    assert seed.main(["--resolve", "--file", str(path)]) == 1
    out = capsys.readouterr().out
    assert "could not add Elf" in out and "could not look up Prancer" in out
    assert "added 0" in out
    assert count_movies() == 0


def test_missing_token_is_reported_and_exits_1(client, tmp_path, capsys):
    path = write_seed(tmp_path, [ELF])
    assert seed.main(["--file", str(path)]) == 1
    assert "TMDB is not set up yet" in capsys.readouterr().out
    assert count_movies() == 0


def test_dry_run_writes_nothing_and_asks_nothing(client, tmdb_fixtures, tmp_path, capsys):
    path = write_seed(tmp_path, [ELF, TINSEL, UNRESOLVED])
    assert seed.main(["--dry-run", "--file", str(path)]) == 0
    assert "would add 2, skipped 1" in capsys.readouterr().out
    assert count_movies() == 0
    assert tmdb_fixtures.api == []


def test_parent_note_is_kept_and_a_certification_difference_is_named(client, tmdb_fixtures, tmp_path, capsys):
    note = {**ELF, "parent_note": "Buddy is a human raised by elves.", "certification": "G"}   # TMDB says PG
    path = write_seed(tmp_path, [note])
    assert seed.main(["--file", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Elf is PG on TMDB, the file says G; TMDB's is kept" in out
    with app.app.app_context():
        row = app.movies.get_row(app.get_db(), 1)
    assert row["parent_note"] == "Buddy is a human raised by elves." and row["certification"] == "PG"
