"""The SQLite schema (spec §6), migrate(), connections (one per request, or one standalone connection outside a
request) and init_db(). No Flask object and no routes here (see CLAUDE.md).

Schema rule: every change goes through migrate(), which must work from every earlier version, and bumps
SCHEMA_VERSION. Tables are created with IF NOT EXISTS; a later column is added with ALTER TABLE in migrate()."""
import sqlite3

from flask import g, has_app_context

import providers
from settings import DATA_DIR, DB_PATH, POSTER_DIR, ART_DIR

SCHEMA_VERSION = "3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);   -- schema version, settings that live in the DB

CREATE TABLE IF NOT EXISTS movies (                  -- the curated list
  id INTEGER PRIMARY KEY,
  tmdb_id INTEGER NOT NULL,
  tmdb_type TEXT NOT NULL DEFAULT 'movie' CHECK (tmdb_type IN ('movie','tv')),
  title TEXT NOT NULL, year INTEGER, runtime_min INTEGER,
  certification TEXT,                  -- US: G, PG, PG-13, NR (or NULL). Editable by hand
  certification_override INTEGER NOT NULL DEFAULT 0,
  overview TEXT, poster_path TEXT, backdrop_path TEXT,
  is_animated INTEGER NOT NULL DEFAULT 0,
  collection_id INTEGER, collection_name TEXT,
  top_cast TEXT,                       -- JSON array, first 8 billed names
  tmdb_vote REAL,
  parent_note TEXT,
  added_by TEXT, added_at TEXT DEFAULT CURRENT_TIMESTAMP,
  meta_refreshed_at TEXT,
  UNIQUE (tmdb_type, tmdb_id)
);

CREATE TABLE IF NOT EXISTS providers_cache (         -- TMDB watch providers, US region
  movie_id INTEGER PRIMARY KEY REFERENCES movies(id) ON DELETE CASCADE,
  data TEXT NOT NULL,                  -- {"flatrate":[...], "free":[...], "ads":[...], "rent":[...], "buy":[...]}
  link TEXT, fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS services (                -- streaming services the family knows about
  key TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  tmdb_provider_ids TEXT NOT NULL,     -- JSON array
  status TEXT NOT NULL CHECK (status IN ('subscribed','considering','ignore')),
  tv_source TEXT
);

CREATE TABLE IF NOT EXISTS people (                  -- mirrors Matinee's people by name
  id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
  kind TEXT NOT NULL CHECK (kind IN ('adult','kid')),
  color TEXT NOT NULL,                 -- green | blue | red | pink | purple
  sort_order INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS person_ratings (
  person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
  rating REAL NOT NULL CHECK (rating >= 0 AND rating <= 10),   -- 0.5 steps, validated in code
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (person_id, movie_id)
);
CREATE INDEX IF NOT EXISTS person_ratings_movie ON person_ratings(movie_id);

CREATE TABLE IF NOT EXISTS viewings (                -- one attempt at watching a movie, possibly over several nights
  id INTEGER PRIMARY KEY,
  movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
  started_on TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('tonight','watching','paused','finished','abandoned')),
  watched_seconds INTEGER NOT NULL DEFAULT 0,
  guess TEXT CHECK (guess IN ('finished','not_finished')),
  finished_on TEXT,
  matinee_watch_id INTEGER,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS viewings_movie ON viewings(movie_id);
CREATE TABLE IF NOT EXISTS viewing_people (viewing_id INTEGER REFERENCES viewings(id) ON DELETE CASCADE,
                                           person_id INTEGER REFERENCES people(id),
                                           PRIMARY KEY (viewing_id, person_id));

CREATE TABLE IF NOT EXISTS sessions (                -- one evening's TV time for a viewing
  id INTEGER PRIMARY KEY,
  viewing_id INTEGER NOT NULL REFERENCES viewings(id) ON DELETE CASCADE,
  tv_source TEXT,
  started_at TEXT NOT NULL, ended_at TEXT,
  end_reason TEXT                      -- 'tv_off', 'source_changed', 'manual', 'timeout'
);
CREATE INDEX IF NOT EXISTS sessions_viewing ON sessions(viewing_id);

CREATE TABLE IF NOT EXISTS matinee_sync (            -- what we last told / heard from Matinee, per movie
  movie_id INTEGER PRIMARY KEY REFERENCES movies(id) ON DELETE CASCADE,
  matinee_title_id INTEGER,            -- NULL = not owned / not in Matinee
  owned_summary TEXT,
  location_path TEXT,
  matinee_rating REAL,
  matinee_last_watch TEXT,             -- newest watched_date Matinee has (for "Not watched this year")
  pushed_rating REAL,
  rating_owner TEXT NOT NULL DEFAULT 'matinee' CHECK (rating_owner IN ('matinee','wonderful')),
  conflict_rating REAL,
  checked_at TEXT,
  has_physical INTEGER,                -- v2: 1 when Matinee holds a disc, 0 when not; NULL = not checked since the upgrade
  has_digital INTEGER                  -- v2: the same for a digital copy
);

CREATE TABLE IF NOT EXISTS service_titles (         -- v3: a streaming service's own id for a movie (Netflix: the title id)
  movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
  service TEXT NOT NULL,               -- a services.key, today only 'netflix'
  title_id TEXT,                       -- 1 to 12 digits; NULL = the lookup found none
  manual INTEGER NOT NULL DEFAULT 0,   -- 1 = somebody pasted it: the lookup never changes it
  checked_at TEXT,                     -- when the lookup last asked (UTC)
  PRIMARY KEY (movie_id, service)
);

CREATE TABLE IF NOT EXISTS ai_cache (q_norm TEXT PRIMARY KEY, list_hash TEXT NOT NULL, result TEXT NOT NULL,
                                     created_at TEXT);
"""


def connect(path=None):
    """A connection to `path` (default DB_PATH) with Row rows, foreign keys on and WAL."""
    con = sqlite3.connect(path or DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    return con


_standalone_db = None


def get_db():
    """The request's connection (closed by app.py's teardown), or one shared standalone connection outside a
    request (ops scripts)."""
    if has_app_context():
        if "db" not in g:
            g.db = connect()
        return g.db
    global _standalone_db
    if _standalone_db is None:
        _standalone_db = connect()
    return _standalone_db


def migrate(con):
    """Bring any earlier database (or an empty file) to SCHEMA_VERSION. Idempotent: safe on every start.
    v1 is the first version, so it only creates what is missing; later versions add their steps below (each checks
    PRAGMA table_info first, so a step is a no-op the second time). The streaming services (data/services.json) are
    seeded here, so a service added to the file appears on the next start.
    v2: matinee_sync.has_physical and has_digital, NULL on an old row until its next ownership check.
    v3: the service_titles table, which SCHEMA creates (CREATE TABLE IF NOT EXISTS), so v1 and v2 databases gain it here."""
    con.executescript(SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(matinee_sync)")}
    for column in ("has_physical", "has_digital"):
        if column not in have:
            con.execute(f"ALTER TABLE matinee_sync ADD COLUMN {column} INTEGER")
    providers.seed_services(con)
    con.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('schema', ?)", (SCHEMA_VERSION,))
    con.commit()


def init_db():
    """Create the data folders and bring the database to SCHEMA_VERSION (runs at app import)."""
    for d in (DATA_DIR, POSTER_DIR, ART_DIR):
        d.mkdir(parents=True, exist_ok=True)
    con = connect()
    try:
        migrate(con)
    finally:
        con.close()
