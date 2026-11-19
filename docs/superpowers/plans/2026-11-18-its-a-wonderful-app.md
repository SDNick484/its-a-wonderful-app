# It's a Wonderful App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each task is also filed as one "Prompt:" GitHub issue and run from the issue queue.

**Goal:** A phone-first Christmas movie picker for the family: a curated list with posters, where to watch, search, a three-pick randomizer, Continue Watching driven by the Family Room TV, per-person ratings synced to Matinee, and four Advent themes.

**Architecture:** A Flask + SQLite app built the same way as Matinee (`SDNick484/matinee`): `app.py` holds the Flask object, auth and every route; route-free sibling modules hold the logic; the SPA is vanilla ES modules in `static/js/`. It talks to Matinee's `/admin/api` with a key, to TMDB for metadata and watch providers, to Anthropic for AI search, and receives Home Assistant TV events on `/hooks/tv`.

**Tech Stack:** Python 3.10–3.13, Flask, gunicorn, SQLite, Pillow (`py3-pillow`), vanilla JS, pytest, Playwright, ruff, Alpine LXC + OpenRC.

**Spec:** `docs/superpowers/specs/2026-11-18-its-a-wonderful-app-design.md` (read it with this plan; § numbers below refer to it).

## Global Constraints

- Runtime deps only as Alpine `py3-*` packages; no frontend framework, bundler or npm build. ES modules: `import { x } from "./x.js";`, one `export { … };` at the end, `core.js` imports nothing.
- Schema changes only through an idempotent `migrate()`; `SCHEMA_VERSION` starts at `"1"`.
- pytest with recorded fixtures in `tests/fixtures/{tmdb,matinee,anthropic}/`; no live network. Every external call has a miss test and an HTTP-error test.
- CI: Python 3.10, 3.11, 3.12, 3.13 on Ubuntu; an Alpine container job; ruff; shellcheck; `node --check static/js/*.js` with `static/js/package.json` = `{"type": "module"}`; Playwright UI smoke at 412 × 915.
- Phone-first: ≥ 3 poster columns and no horizontal scroll at 412 px and 360 px; tap targets ≥ 44 px; text contrast ≥ 4.5:1 including over themes.
- Every route requires `editor_required` (LAN host, Cloudflare Access JWT for `ADMIN_EMAILS`, or a key), except `/hooks/tv` (`X-Hook-Secret` = `HA_HOOK_SECRET`) and static files. No anonymous view.
- Public repo hygiene: no personal hostnames, LAN IPs, container IDs or family names in code, fixtures or docs outside `docs/superpowers/`. Use `wonderful.example.com`, `movies.example.com`, `ha.example.com`, `192.168.1.100`. A `tests/test_hygiene.py` enforces it.
- Ratings: 0.0–10.0 in 0.5 steps. Matinee receives the per-person mean rounded to the nearest 0.5, half up (8.25 → 8.5, 8.75 → 9.0).
- TMDB attribution (logo + notice) on the about screen; JustWatch attribution wherever providers show.
- Conventional Commits, author `SDNick484 <SDNick484@users.noreply.github.com>`, one logical change per commit, one PR per task. OpenRC (`rc-service wonderful restart`), `vim`.
- Every task tagged **(M)** ends its PR description with a "Try it, Midge" note: what to open on the phone after Nick deploys, and what she should see.

## Review Focus

1. **Matinee unreachable or slow** (timeout, 502, wrong key) during add, rating or finish: the app still answers, shows the last known ownership "(as of <date>)", queues the push, and the nightly refresh retries. Tests in Tasks 5, 9 and 10.
2. **TMDB data with holes:** no US certification, `runtime: null`, no poster, no providers for US. Certification becomes `NR`, a null runtime fails "Under 90 min" and gives no finish guess (prompt has nothing preselected), a missing poster shows a titled placeholder. Tests in Tasks 2, 7 and 11.
3. **Home Assistant events that don't fit:** duplicates, TV off with no open session, "on" arriving twice, events out of order by `at`. All are idempotent no-ops or close the open session once. Tests in Task 11.
4. **Rating edits that empty or break the mean:** clearing the last person's rating makes the family rating `null` and pushes nothing (it never sends `null` to Matinee); 7.3 or 11 is a 400. Tests in Task 8 and 9.
5. **Dates around the year boundary:** January 1–6 shows Santa from the previous Advent; a viewing finished January 2 counts for the new year in "Not watched this year"; all dates use the host's `TZ`, not UTC. Tests in Tasks 7 and 13.

---

### Task 1: Skeleton, auth, CI, installer (Nick deploys)

**Files:**
- Create: `app.py`, `settings.py`, `common.py`, `db.py`, `auth.py`, `static/index.html`, `static/style.css`, `static/js/{core.js,main.js,package.json}`, `static/fonts/` (Figtree, copied from Matinee), `installer/{setup-head.sh,build.sh}`, `ops/wonderful-backup`, `.env.example`, `requirements-dev.txt`, `ruff.toml`, `pytest.ini`, `.github/workflows/ci.yml`, `CLAUDE.md`, `README.md`
- Test: `tests/conftest.py`, `tests/test_schema.py`, `tests/test_auth.py`, `tests/test_hygiene.py`, `tests/test_installer_static.py`, `tests/test_js_modules.py`

**Interfaces:**
- Produces: `db.connect(path) -> sqlite3.Connection` (row factory, `PRAGMA foreign_keys=ON`); `db.migrate(con) -> None`; `db.SCHEMA_VERSION = "1"`; `common.make_err(status, msg)`, `common.clean(s)`, `common.validate_rating(v) -> float | None` (400 unless 0–10 in 0.5 steps), `common.round_half_up(x: float) -> float`, `common.today() -> date` (host `TZ`); `auth.editor_required`, `auth.hook_required`; fixture `client` (LAN identity) and `anon_client` in `conftest.py`. CSS custom properties copied from Matinee: surfaces, ink, `--red #c8272d`, `--amber #f2b544`, `--p-user1…5`.

Port Matinee's shape, not its features: the auth code (`access_identity`, `lan_host`, JWT check, `cross_site`, `editor_required`) from Matinee `app.py:93–208`, the installer and OpenRC init from `installer/`, the CI jobs from `.github/workflows/ci.yml`. The whole §6 schema goes in now so later tasks never migrate.

- [ ] **Step 1: Write the failing tests**

```python
def test_migrate_creates_every_table_and_is_idempotent(tmp_path):
    con = db.connect(tmp_path / "w.db"); db.migrate(con); db.migrate(con)
    names = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    assert {"movies","providers_cache","services","people","person_ratings","viewings",
            "viewing_people","sessions","matinee_sync","ai_cache","meta"} <= names
    assert con.execute("select v from meta where k='schema'").fetchone()[0] == "1"

def test_round_half_up():
    assert [common.round_half_up(x) for x in (8.6, 8.25, 8.75, 8.9, 10.0)] == [8.5, 8.5, 9.0, 9.0, 10.0]

def test_validate_rating_rejects_off_steps(app_ctx):
    for bad in (7.3, 11, -1, True, "x"):
        with pytest.raises(HTTPException): common.validate_rating(bad)

def test_anonymous_via_cloudflare_is_401(anon_client):
    assert anon_client.get("/api/health", headers={"Cf-Connecting-Ip": "1.2.3.4"}).status_code == 401

def test_lan_ip_host_is_allowed(client):
    assert client.get("/api/health", base_url="http://192.168.1.100:8772").status_code == 200

def test_hook_requires_secret(client, monkeypatch):
    monkeypatch.setattr(app, "HA_HOOK_SECRET", "s3cret")
    assert client.post("/hooks/tv", json={}).status_code == 403
```

- [ ] **Step 2: Run** `python -m pytest -q` → FAIL (no modules).
- [ ] **Step 3: Implement** the files above. `GET /api/health` → `{"ok": true, "schema": "1"}`. `/` serves `index.html` with an empty grid and the app title "It's a Wonderful App". `.env.example` lists every §16 setting, each with a comment line. The installer creates `/var/lib/wonderful`, writes missing keys to `/etc/conf.d/wonderful` without overwriting, installs `apk add python3 py3-flask py3-gunicorn py3-pillow`, and adds OpenRC service `wonderful`. `ops/wonderful-backup` does an atomic `sqlite3 .backup` plus `posters/` and `art/`. `CLAUDE.md` copies Matinee's rules, renamed.
- [ ] **Step 4: Run** `python -m pytest -q && ruff check && for f in static/js/*.js; do node --check "$f"; done && sh installer/build.sh && sh -n dist/setup-wonderful.sh` → all pass.
- [ ] **Step 5: Commit** `feat: app skeleton, schema v1, auth, CI and installer`. After merge, Nick deploys and confirms `curl http://<lan-ip>:<port>/api/health` and loading the page on the phone, and records in `README.md` how the phone reaches it on the LAN (spec §5 caveat).

### Task 2: TMDB client, add a movie, grid and detail view (M)

**Files:**
- Create: `tmdb.py`, `movies.py`, `images.py`, `static/js/{grid.js,detail.js,add.js}`, `static/tmdb.svg`
- Modify: `app.py` (routes), `static/js/main.js`
- Test: `tests/test_tmdb.py`, `tests/test_movies_api.py`, `tests/test_grid_ui.py`, fixtures `tests/fixtures/tmdb/movie_10719.json` (Elf, with `release_dates`, `credits`, `belongs_to_collection` appended), `search_prancer.json`, one TV-only special, one with no US certification and `runtime: null`

**Interfaces:**
- Consumes: Task 1 `db`, `common`, `auth`.
- Produces: `tmdb.search(q: str) -> list[dict]` (`tmdb_id, tmdb_type, title, year, poster_path`); `tmdb.details(tmdb_id, tmdb_type) -> dict` (runtime, genres, `us_certification`, collection, `top_cast` ≤ 8, vote, overview, poster/backdrop); `movies.add_movie(con, tmdb_id, tmdb_type, added_by) -> int` (409 if present); `movies.movie_out(row) -> dict`; routes `GET /api/tmdb/search?q=`, `POST /api/movies` `{tmdb_id, tmdb_type}`, `GET /api/movies`, `GET /api/movies/<id>`, `PUT /api/movies/<id>` (`parent_note`, `certification`), `DELETE /api/movies/<id>`.

- [ ] **Step 1: Write the failing tests**

```python
def test_add_elf_fills_metadata(client, tmdb_fixtures):
    r = client.post("/api/movies", json={"tmdb_id": 10719, "tmdb_type": "movie"}).get_json()
    m = client.get(f"/api/movies/{r['id']}").get_json()
    assert (m["title"], m["year"], m["certification"], m["is_animated"]) == ("Elf", 2003, "PG", False)
    assert m["runtime_min"] == 97 and len(m["top_cast"]) <= 8 and m["poster_url"].startswith("/posters/")

def test_add_twice_is_409(client, tmdb_fixtures): ...
def test_missing_us_cert_becomes_NR_and_null_runtime_kept(client, tmdb_fixtures): ...   # Review Focus 2
def test_certification_override_survives_refresh(client, tmdb_fixtures): ...
def test_tmdb_http_error_is_502_with_message(client, tmdb_down): ...
def test_tmdb_search_miss_returns_empty_with_message(client, tmdb_fixtures): ...
# Playwright, 412 and 360 px: 3 poster columns, no horizontal scroll, missing poster shows titled placeholder
```

- [ ] **Step 2: Run** `pytest tests/test_movies_api.py -q` → FAIL.
- [ ] **Step 3: Implement.** Posters download once to `$DATA_DIR/posters/<tmdb_type>-<id>-w342.jpg`. US certification = first non-empty `certification` in the `US` release-date set, else `NR`. Grid card: poster, title, year, family rating slot (empty for now). Detail: backdrop, overview, runtime, cert, cast, collection, parent note (editable), Remove (confirm). Add sheet: search box → results → **Add to our list**.
- [ ] **Step 4: Run** the full suite → PASS.
- [ ] **Step 5: Commit** `feat(movies): add movies from TMDB with grid and detail view`. *Try it, Midge:* add *Prancer* from the + button and watch its poster appear.

### Task 3: Seed the starting list of 41

**Files:**
- Create: `data/seed-movies.json`, `ops/seed-movies` (Python CLI)
- Test: `tests/test_seed.py`

**Interfaces:**
- Consumes: `movies.add_movie`, `tmdb.search`, `tmdb.details`.
- Produces: `seed-movies.json` entries `{"tmdb_id": int, "tmdb_type": "movie"|"tv", "title": str, "year": int, "certification": str|null, "parent_note": str|null}`; `ops/seed-movies [--dry-run]` adds missing ones and prints `added N, skipped M`.

- [ ] **Step 1: Resolve all 41 titles in spec §17** to TMDB ids with `tmdb.search` (run once by hand with a real token, outside tests), preferring `movie` over `tv`. Write `seed-movies.json`. The *Wimpy Kid* entry carries its parent note; *Four Christmases* is `PG-13`; *White Christmas* and *A Loud House Christmas Movie* are `NR`. List the `tv` ones in the PR description.
- [ ] **Step 2: Failing test** `test_seed_file_has_41_unique_entries_and_valid_certs` (unique `(tmdb_type, tmdb_id)`, certs in `{G, PG, PG-13, NR}`, every entry has title and year) and `test_seed_is_idempotent` (running twice against fixtures adds 0 the second time).
- [ ] **Step 3: Implement** `ops/seed-movies`; the installer runs it once on a fresh install only.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(seed): starting list of 41 Christmas movies`.

### Task 4: Services and where to watch (M)

**Files:**
- Create: `providers.py`, `data/services.json`, `static/js/settings.js`
- Modify: `app.py`, `static/js/{grid.js,detail.js}`
- Test: `tests/test_providers.py`, fixtures `tmdb/providers_10719.json`, `providers_klaus.json`, `providers_empty.json`

**Interfaces:**
- Consumes: Task 2 `movies`.
- Produces: `providers.get(con, movie_id, max_age_days=7) -> dict` (`flatrate, free, ads, rent, buy` as lists of service keys or raw names; refreshes when stale); `providers.where_to_watch(con, movie_id) -> list[{"kind": "owned"|"subscribed"|"free"|"considering"|"rent_buy", "label": str}]` (ordered per §7.2; `owned` filled in Task 5); `providers.ready_tonight(con, movie_id) -> bool`; routes `GET/PUT /api/services` (`status` in `subscribed|considering|ignore`), `POST /api/movies/<id>/providers/refresh`.

- [ ] **Step 1: Failing tests:** `test_klaus_on_netflix_is_subscribed_first`; `test_free_with_ads_counts_as_ready` (decision 20); `test_peacock_only_title_reads_on_peacock_you_dont_have_it`; `test_no_us_providers_reads_rent_or_buy`; `test_stale_cache_refreshes_and_fresh_cache_does_not` (7 days); `test_unknown_tmdb_provider_name_shown_raw`; `test_services_seeded_with_decision_15_statuses`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** `services.json` maps each family service to TMDB provider ids and the LG `tv_source` names seen on the TV ("Disney+", "Netflix", "HBO Max", "Hulu", "Peacock", "Paramount+", "Prime Video", "Fandango at Home", "YouTube TV"; Apple TV has none). Subscribed: Netflix, Disney+, Hulu, Prime Video, Fandango at Home, YouTube TV. Considering: HBO Max, Peacock, Paramount+, Apple TV. Settings screen lists services with three-way toggles. Card line shows the first `where_to_watch` entry; detail shows all plus "Data from JustWatch".
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(providers): where to watch and subscriptions`. *Try it, Midge:* open Settings → Subscriptions and see your services.

### Task 5: Matinee client and ownership

**Files:**
- Create: `matinee.py`, `ops/wonderful-refresh`
- Modify: `providers.py` (owned entry), `app.py`, installer (cron line, as Matinee's `matinee-refresh`)
- Test: `tests/test_matinee_client.py`, fixtures `tests/fixtures/matinee/{owned_elf.json,not_owned.json,title_detail_elf.json,people.json}`

**Interfaces:**
- Consumes: `MATINEE_URL`, `MATINEE_API_KEY`.
- Produces: `matinee.Client(url, key, timeout=5)` with `owned(tmdb_id) -> {"title_id": int|None, "summary": str|None, "location_path": str|None}`, `title(title_id) -> dict`, `set_rating(title_id, rating: float) -> None`, `log_watch(title_id, watched_date: str, attendees: list[str]) -> int` (watch id), `people() -> list[dict]`; raises `matinee.Unavailable` on timeout/5xx/connection error and `matinee.Rejected(status, message)` on 4xx. `movies.refresh_ownership(con, movie_id) -> None` writes `matinee_sync` (`matinee_title_id, owned_summary, location_path, matinee_rating, matinee_last_watch, checked_at`); `matinee_last_watch` is the newest `watched_date` in the title detail's `watches`.

- [ ] **Step 1: Failing tests:** `test_owned_elf_reads_bluray_and_shelf` (summary "Blu-ray", location "Family Room › Media Cabinet › Shelf 2", rating 9.0); `test_not_owned_sets_null_title_id`; `test_tv_type_skips_matinee` (no request made); `test_matinee_down_keeps_last_known_and_marks_stale` (Review Focus 1: where-to-watch shows "(as of Dec 3)"); `test_bearer_header_sent`; `test_refresh_job_checks_rows_older_than_a_day_only`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** with `urllib` (no new dependency), `Authorization: Bearer`. Ownership refreshes on add, on detail view when `checked_at` > 1 day, and nightly in `ops/wonderful-refresh` together with providers.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(matinee): read ownership and shelf from Matinee`.

### Task 6: Search: local filter and exact title (M)

**Files:**
- Create: `search.py`, `static/js/search.js`
- Modify: `app.py`, `static/js/main.js`
- Test: `tests/test_search_local.py`

**Interfaces:**
- Produces: `search.normalize(s) -> str` (casefold, strip punctuation, drop leading "the "); `search.local(con, q) -> list[int]` (title, year, cast, collection substring); `search.exact(con, q) -> int | None`; route `GET /api/search?q=` → `{"mode": "exact"|"local"|"ai", "matches": [{"id", "why"}], "suggestions": []}` (AI arrives in Task 12).

- [ ] **Step 1: Failing tests:** `test_elf_exact` (`"elf"` → mode exact, Elf only); `test_the_santa_clause_matches_without_the`; `test_actor_search_tim_allen` (both Santa Clause films, Christmas with the Kranks, Jingle All the Way); `test_collection_search_christmas_chronicles`; `test_empty_query_returns_whole_list`.
- [ ] **Step 2–4:** Implement; the search box filters the grid as you type, Enter calls `/api/search`. Run → PASS.
- [ ] **Step 5: Commit** `feat(search): local and exact-title search`. *Try it, Midge:* type "Tim Allen".

### Task 7: The randomizer (M)

**Files:**
- Create: `randomizer.py`, `static/js/surprise.js`
- Modify: `app.py`
- Test: `tests/test_randomizer.py`, `tests/test_surprise_ui.py`

**Interfaces:**
- Consumes: `providers.ready_tonight`; `viewings` rows (empty until Task 10) and `matinee_sync.matinee_last_watch` (Task 5).
- Produces: `randomizer.watched_this_year(con, movie_id, year: int) -> bool` (a `finished` viewing with `finished_on` in `year`, or `matinee_last_watch` in `year`); `randomizer.pool(con, filters: dict) -> list[int]`; `randomizer.pick(pool, exclude: set[int], k=3, rng) -> list[int]`; route `POST /api/surprise` `{"filters": {...}, "exclude": [ids]}` → `{"picks": [ids], "pool_size": int, "restarted": bool}`. Filter keys: `animated: true|false|null`, `cap: null|"G"|"PG"|"PG-13"`, `under_90: bool`, `not_watched_this_year: bool`, `ready: bool`.

- [ ] **Step 1: Failing tests:** `test_cap_G_excludes_NR_and_cap_PG_includes_NR` (§7.3); `test_four_christmases_only_at_PG13`; `test_under_90_excludes_null_runtime` (Review Focus 2); `test_three_distinct_picks`; `test_pick_again_excludes_shown_until_exhausted_then_restarts`; `test_fewer_than_three_returns_what_matches`; `test_watched_jan_2_counts_for_new_year` (Review Focus 5); `test_all_chips_off_is_whole_list`.
- [ ] **Step 2–4:** Implement. The button text is exactly **🎲 Surprise us, ya filthy animals**; Pick Again reads **Keep the change (pick again)**. Chips per spec §12 (rating cap cycles off → G → PG → PG-13), remembered in `localStorage` key `wonderful.surprise.filters`, all off by default; reads guarded with try/catch. "Only 2 match. Try turning off a filter." when short. Run → PASS.
- [ ] **Step 5: Commit** `feat(surprise): three-pick randomizer with filters`. *Try it, Midge:* press the button with "Up to G" on.

### Task 8: People and per-person ratings (M)

**Files:**
- Create: `people.py`, `ratings.py`, `static/js/rating.js`
- Modify: `app.py`, `static/js/{grid.js,detail.js,settings.js}`
- Test: `tests/test_people.py`, `tests/test_ratings.py`, `tests/test_rating_ui.py`

**Interfaces:**
- Consumes: `matinee.Client.people()`.
- Produces: `people.sync_from_matinee(con, client) -> {"added": int, "updated": int}` (by name; copies kind, color, order); `ratings.set(con, movie_id, person_id, rating: float | None) -> None`; `ratings.family(con, movie_id) -> {"mean": float | None, "by_person": [{"person_id", "name", "color", "rating"}]}` (mean to 1 decimal); routes `GET/POST /api/people`, `POST /api/people/sync`, `PUT /api/movies/<id>/ratings/<person_id>` `{"rating": 8.5|null}`. After any change, calls `sync.after_rating_change(con, movie_id)` (a no-op until Task 9).

- [ ] **Step 1: Failing tests:** `test_klaus_mean_8_6` (8, 9, 10, 8, 8 → 8.6); `test_clearing_last_rating_gives_null_mean` (Review Focus 4); `test_off_step_is_400`; `test_sync_people_adds_five_and_is_idempotent`; `test_local_only_person_allowed`; UI at 412 px: number buttons 1–10 and ½ each ≥ 44 px, wrap to two rows, no horizontal scroll.
- [ ] **Step 2–4:** Implement. Grid poster shows ★ mean (or Matinee's rating while `rating_owner = 'matinee'`, Task 9). Detail shows the dot row `● N 8  ● L 9 …` with family colors. Rating sheet per spec §11. Run → PASS.
- [ ] **Step 5: Commit** `feat(ratings): per-person ratings and family average`. *Try it, Midge:* rate a movie for everyone.

### Task 9: Rating sync with Matinee

**Files:**
- Create: `sync.py`
- Modify: `movies.refresh_ownership` (bought-later rule), `static/js/detail.js` (conflict notice)
- Test: `tests/test_rating_sync.py`

**Interfaces:**
- Consumes: `ratings.family`, `matinee.Client.set_rating`, `matinee_sync` row.
- Produces: `sync.after_rating_change(con, movie_id) -> None`; `sync.reconcile(con, movie_id) -> None` (called from ownership refresh); `sync.resolve_conflict(con, movie_id, choice: "ours"|"matinee"|"dismiss") -> None`; route `POST /api/movies/<id>/rating-conflict` `{"choice": ...}`. Shown rating rule: `display_rating(con, movie_id) -> float | None`.

- [ ] **Step 1: Failing tests** (spec §8.2 scenarios):
  - `test_before_anyone_rates_shows_matinee_9` (Elf).
  - `test_first_rating_takes_ownership_and_pushes_rounded_mean` (8.5, 9, 10, 9, 8 → shows 8.9, PUT `{"rating": 9.0}`).
  - `test_not_owned_never_pushes` (Klaus).
  - `test_matinee_changed_after_push_sets_conflict_and_does_not_overwrite`.
  - `test_use_matinee_reverts_owner`.
  - `test_bought_later_pushes_when_matinee_unrated_else_conflict`.
  - `test_null_mean_never_pushed` (Review Focus 4).
  - `test_push_failure_marks_pending_and_refresh_retries` (Review Focus 1).
- [ ] **Step 2–4:** Implement. Run → PASS.
- [ ] **Step 5: Commit** `feat(sync): keep the family rating in step with Matinee`.

### Task 10: Viewings, Continue Watching, finishing (M)

**Files:**
- Create: `viewings.py`, `ha.py` (outbound part), `static/js/continue.js`
- Modify: `app.py`, `static/js/{detail.js,main.js}`
- Test: `tests/test_viewings.py`, `tests/test_ha_log.py`, `tests/test_continue_ui.py`

**Interfaces:**
- Consumes: `matinee.Client.log_watch`, `people`, `HA_WEBHOOK_URL`.
- Produces: `viewings.watch_tonight(con, movie_id, person_ids: list[int] | None) -> int` (enforces one `tonight`; previous one → `paused`, or deleted if `watched_seconds == 0`); `viewings.keep_watching(con, viewing_id) -> None`; `viewings.finish(con, viewing_id, finished_on: date | None) -> None` (posts Matinee watch if owned, then HA log); `viewings.abandon(con, viewing_id)`; `viewings.expire_stale(con, now) -> int` (4 am rule); `viewings.progress_label(watched_seconds, runtime_min) -> str | None` ("Just started" < 25 %, "About halfway" 25–75 %, "Almost done" > 75 %, None if runtime unknown); `viewings.pending_prompt(con) -> dict | None` (`{"viewing_id", "title", "guess"}`); `ha.post_watch_logged(payload: dict) -> None` (daemon thread, host-only warnings). Routes `POST /api/movies/<id>/tonight`, `POST /api/viewings/<id>/{keep,finish,abandon}`, `GET /api/continue`, `GET /api/prompt`.

- [ ] **Step 1: Failing tests:**
  - `test_one_tonight_at_a_time`.
  - `test_stale_tonight_reverts_at_4am_local`.
  - `test_finish_owned_posts_matinee_watch_with_known_names_only_and_no_live_flag`.
  - `test_finish_posts_ha_payload` (event `matinee_watch_logged`, `source: "wonderful"`, `title_id: null`, `formats: []` and `location: null` for Klaus, `watched_date` = `finished_on`).
  - `test_finish_happens_once` (a second finish is 409, no second HA post).
  - `test_matinee_down_on_finish_keeps_viewing_finished_and_flags_unsynced` (Review Focus 1).
  - `test_progress_labels`.
  - UI: the Continue Watching row appears above the grid only when non-empty; the "Did you finish?" sheet has Yes, Not yet, and "We gave up on it"; a guess is highlighted but not auto-submitted.
- [ ] **Step 2–4:** Implement. Yes → "Want to rate it?" → Task 8 rating sheet. Run → PASS.
- [ ] **Step 5: Commit** `feat(viewings): Continue Watching, finishing, Matinee watch and HA movie log`. *Try it, Midge:* pick *Elf* for tonight, then tap "We finished".

### Task 11: TV webhook and the finish guess

**Files:**
- Modify: `ha.py` (inbound), `viewings.py`, `app.py`
- Create: `docs/home-assistant.md`
- Test: `tests/test_tv_hook.py`

**Interfaces:**
- Consumes: `viewings` (Task 10), `services.tv_source`, `matinee_sync` (owned → receiver input `"AV Receiver"`).
- Produces: `ha.handle_tv_event(con, state: str, source: str | None, at: datetime) -> dict` (`{"action": "opened"|"closed"|"ignored", "reason": str}`); `viewings.close_session(con, session_id, ended_at, reason)` sets `guess` = `finished` if `watched_seconds ≥ 0.85 × runtime × 60`, else `not_finished`, and `None` if runtime is unknown. Route `POST /hooks/tv` `{"state", "source", "at"}`.

- [ ] **Step 1: Failing tests:** `test_home_alone_two_nights` (spec §10.3 scenario end to end: 50 min → not_finished, Keep watching, +55 min → finished); `test_source_youtube_closes_session`; `test_disc_counts_on_av_receiver_only_when_owned`; `test_timeout_closes_at_runtime_plus_60`; `test_event_with_no_tonight_viewing_is_ignored`; `test_duplicate_on_and_off_with_no_session_are_noops` (Review Focus 3); `test_out_of_order_at_is_ignored`; `test_null_runtime_gives_no_guess` (Review Focus 2).
- [ ] **Step 2–4:** Implement. `docs/home-assistant.md` gives the automation YAML: triggers on the TV `media_player` state and `source` attribute, `rest_command` posting `{"state": "{{ states(tv) }}", "source": "{{ state_attr(tv, 'source') }}", "at": "{{ now().isoformat() }}"}` with `X-Hook-Secret`, entity written as `media_player.family_room_tv` (placeholder). Run → PASS.
- [ ] **Step 5: Commit** `feat(tv): guess unfinished movies from the Family Room TV`.

### Task 12: AI search with suggestions (M)

**Files:**
- Create: `ai.py`
- Modify: `search.py`, `static/js/search.js`
- Test: `tests/test_ai_search.py`, fixtures `tests/fixtures/anthropic/{jesus.json,musical.json,malformed.json,overloaded_529.json}`

**Interfaces:**
- Consumes: `search.exact`, `search.local`, `tmdb.search`, `movies.add_movie`.
- Produces: `ai.ask(list_json: str, query: str) -> {"matches": [{"id", "why"}], "suggestions": [{"title", "year", "why"}]}` (Messages API via `urllib`; `AI_MODEL`, `AI_TIMEOUT`); `search.ai(con, q) -> dict` (validates ids, ≤ 8 matches, resolves ≤ 3 suggestions via TMDB and drops ones already listed or not found, caches by `normalize(q)` + list hash, enforces `AI_DAILY_CAP`).

- [ ] **Step 1: Failing tests:**
  - `test_jesus_returns_the_star_and_suggests_nativity_story`.
  - `test_unknown_ids_from_model_dropped`.
  - `test_suggestion_already_on_list_dropped`.
  - `test_cache_hit_makes_no_call`.
  - `test_list_change_busts_cache`.
  - `test_malformed_json_falls_back_to_local_with_notice` ("Smart search is off right now.").
  - `test_529_falls_back`.
  - `test_no_key_falls_back`.
  - `test_daily_cap_falls_back`.
  - `test_suggestions_never_added_without_tap` (no `movies` row after a search).
  - `test_prompt_contains_no_people_or_ratings`.
- [ ] **Step 2–4:** Implement. "Not on our list yet" section with **Add to our list** per suggestion. Run → PASS.
- [ ] **Step 5: Commit** `feat(search): AI search with suggestions to add`. *Try it, Midge:* search "a movie about Jesus" and "a musical".

### Task 13: Themes: calendar, motion, scrim (M)

**Files:**
- Create: `themes.py`, `static/js/theme.js`, `static/themes/{fireplace,toystore,tree,sleigh}/{background.webp,background-wide.webp,theme.css}` (placeholders), `tests/test_themes.py`, `tests/test_theme_ui.py`
- Modify: `app.py` (`GET /api/theme`), `static/style.css` (light mode, scrim), `static/js/settings.js` (Preview themes, Themes on/off, Light/Dark/System)

**Interfaces:**
- Produces: `themes.advent_sunday(year: int, n: int) -> date` (n = 1..4); `themes.theme_for(d: date) -> "fireplace"|"toystore"|"tree"|"sleigh"|None`; `GET /api/theme` → `{"theme": ..., "until": "YYYY-MM-DD"}`.

- [ ] **Step 1: Failing tests:**

```python
@pytest.mark.parametrize("d,want", [
    ("2026-11-28", None), ("2026-11-29", "fireplace"), ("2026-12-05", "fireplace"),
    ("2026-12-06", "toystore"), ("2026-12-13", "tree"), ("2026-12-20", "sleigh"),
    ("2027-01-06", "sleigh"), ("2027-01-07", None),            # Review Focus 5
    ("2027-12-19", "sleigh"), ("2027-12-18", "tree"),          # Dec 25, 2027 is a Saturday
    ("2022-12-18", "sleigh"), ("2022-12-11", "tree"),          # Dec 25, 2022 is a Sunday
])
def test_theme_for(d, want): assert themes.theme_for(date.fromisoformat(d)) == want
```

  Plus UI tests: `prefers-reduced-motion` → no running animations (`document.getAnimations().length == 0` and canvas loop stopped); hidden tab pauses the loop; title and rating text over every theme ≥ 4.5:1 against the scrim's darkest-allowed background (assert the scrim's computed alpha ≥ the value the test derives); no horizontal scroll at 412 px.
- [ ] **Step 2–4:** Implement. Motion in CSS and one `<canvas>` for snow and sparks: flicker and rising sparks (fireplace), twinkling window lights (toy store), twinkling and color-drifting lights (tree), sleigh across the moon every 45–90 s (sleigh), gentle snow in all four. Placeholders are flat color scenes in each theme's palette. Run → PASS.
- [ ] **Step 5: Commit** `feat(themes): Advent themes with motion`. *Try it, Midge:* Settings → Preview themes, then tell us if the flames flicker too fast.

### Task 14: Margaret's drawings (M)

**Files:**
- Create: `ops/prepare-theme`, `docs/themes.md`, `art/originals/` (her photos)
- Modify: `static/themes/*/background*.webp`
- Test: `tests/test_prepare_theme.py`

**Interfaces:**
- Produces: `ops/prepare-theme <key> <photo>` → writes `background.webp` (1080 × 2340, center-cropped portrait) and `background-wide.webp` (2340 × 1080) with Pillow, quality 82, EXIF orientation applied and stripped.

- [ ] **Step 1: Failing test** `test_prepare_theme_crops_and_strips_exif` (a rotated 3000 × 4000 JPEG fixture with GPS EXIF → outputs exact sizes, no EXIF).
- [ ] **Step 2–4:** Implement; `docs/themes.md` is written for Margaret (short steps: draw portrait, daylight photo, put it in `art/originals/`, run the command with Dad, or ask Claude to help clean it up first). Run → PASS.
- [ ] **Step 5: Commit** `feat(themes): art pipeline`, then one commit per drawing: `feat(themes): Midge's fireplace` and so on. *Try it, Midge:* your drawing behind the posters.

### Task 15: Worth a Month?

**Files:**
- Create: `worth.py`, `static/js/worth.js`
- Modify: `app.py`, `static/js/{main.js,settings.js}`
- Test: `tests/test_worth.py`

**Interfaces:**
- Consumes: `providers.get`, `matinee_sync`, `randomizer.watched_this_year`.
- Produces: `worth.compute(con, year: int) -> list[{"service": key, "name": str, "movies": [ids], "count": int}]` sorted by count desc then name; `GET /api/worth`.

- [ ] **Step 1: Failing tests:** `test_peacock_counts_the_three_grinches`; `test_owned_movie_not_counted` (owning *The Polar Express* drops HBO Max by one); `test_free_or_subscribed_elsewhere_not_counted`; `test_watched_this_year_not_counted`; `test_zero_service_listed_with_reason`.
- [ ] **Step 2–4:** Implement. The card shows on home November 1 to December 31, and always in Settings. Run → PASS.
- [ ] **Step 5: Commit** `feat(worth): which service is worth a month`.

---

**Order and dependencies:** 1 → 2 → 3; 4 and 5 after 2; 6 after 2; 7 after 4 (and reads Task 10 data once it exists); 8 after 5; 9 after 8; 10 after 8; 11 after 10; 12 after 6; 13 after 1; 14 after 13; 15 after 5. Target: Tasks 1–10 live before Sunday, December 6, 2026.
