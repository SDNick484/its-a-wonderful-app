# Start the Movie Itself on Netflix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each task is also filed as one "Prompt:" GitHub issue and run from the issue queue.

**Goal:** **Stream it** on a Netflix movie starts that movie playing on the Family Room TV, using a Netflix title id the app looks up on Wikidata or a person pastes.

**Architecture:** A new route-free module `titles.py` keeps one title id per movie and service in a new table and fills Netflix's from a small Wikidata client, `wikidata.py`, on add and nightly. `play.py` adds the id to the Home Assistant payload when Netflix is the chosen service. The documented Home Assistant script launches Netflix on that title.

**Tech Stack:** Python 3.10 to 3.13, Flask, SQLite, vanilla ES modules, pytest, Playwright, Home Assistant YAML.

**Spec:** `docs/superpowers/specs/2026-11-26-netflix-title-design.md` (read it with this plan; § numbers refer to it). It builds on `docs/superpowers/specs/2026-11-26-play-on-tv-design.md`.

## Global Constraints

- No new runtime dependency, no frontend framework or build step. ES modules: one `export { … };` at the end, `core.js` imports nothing.
- A new Python module goes in `_SPLIT_MODULES` in `app.py` and in `installer/build.sh`'s `cp` line. It never imports `app`; routes stay in `app.py`; tests patch `app.X`.
- Schema changes go through the idempotent `db.migrate()`, which must work from v1 and v2; `SCHEMA_VERSION` becomes `"3"` (update CLAUDE.md rule 2, the README's `/api/health` example and the tests that pin the version).
- No new setting, no new route (the id is saved through the existing `PUT /api/movies/<id>`), nothing new in `$DATA_DIR`.
- No live network in tests. Wikidata answers are recorded fixtures in `tests/fixtures/wikidata/` (add that folder to CLAUDE.md rule 3's list); the client has a miss test and an HTTP-error test. `tests/conftest.py`'s `_no_network` already makes `urlopen` raise.
- A title id is 1 to 12 ASCII digits (`^[0-9]{1,12}$`) everywhere: from Wikidata, from a pasted link, in the payload.
- Exact wording: "Netflix link", "Save", "Starting {title} on Netflix…", "That doesn't look like a Netflix link.", "Found automatically", "Set by hand".
- Phone-first: tap targets at least 44 px, no horizontal scroll at 412 px and 360 px, contrast at least 4.5:1 with existing colour tokens only; a Playwright check for the UI, exercised on the second visit; wire listeners once.
- Public repo: placeholder names only outside `docs/superpowers/`. OpenRC and `vim` in docs.
- Conventional Commits, author `SDNick484 <SDNick484@users.noreply.github.com>`, one PR per task, `sh scripts/gate.sh` green before each PR. Task 2 is **(M)**: its PR description ends with a "Try it" note.

## Review Focus

1. **Wikidata not answering.** Down, slow, HTTP 500, HTML instead of JSON, JSON of another shape: adding a movie still answers 201, the nightly step reports and carries on, nothing is stored. Tests in Task 1.
2. **A hand-set id against the lookup.** The lookup never changes it; clearing it lets the lookup fill it. Tests in Task 1.
3. **Values that aren't digits.** A Wikidata value like `80183187; rm` or a 13-digit one, and pasted text like `netflix.com/title/abc`, a Disney+ address, or `80183187/../x`, are refused and never reach the payload. Tests in Tasks 1 and 2.
4. **The id used for the wrong play.** A movie with a stored id that TMDB no longer lists on Netflix, Netflix set to Considering, or a digital copy ranking first: no `direct`, no `content_id`. Tests in Task 2.
5. **Old and new sides mixed.** A payload with no `content_id` still works with the new script, and the doc's automation rejects a `content_id` outside `^[A-Za-z0-9_-]{1,64}$` (this app's own ids stay digits only). Tests in Task 2 (`tests/test_ha_doc.py`).

---

### Task 1: Keep a Netflix title id per movie (schema v3, Wikidata lookup, saved by hand)

**Files:**
- Create: `wikidata.py`, `titles.py`, `tests/test_titles.py`, `tests/fixtures/wikidata/` (`netflix_klaus.json`, `none.json`, `two_ids.json`, `bad_value.json`)
- Modify: `db.py` (`SCHEMA`, `SCHEMA_VERSION`, `migrate`), `app.py` (imports, `_SPLIT_MODULES`, `_movie_json`, `api_movie_add`), `movies.py` (`update_movie` accepts `netflix_link`), `ops/wonderful-refresh` (a third step), `installer/build.sh`, `CLAUDE.md`, `README.md`, `tests/test_schema.py`, `tests/test_auth.py` (health value)
- Test: `tests/test_titles.py`, `tests/test_schema.py`, `tests/test_installer_static.py`

**Interfaces:**
- Produces:
  - Table `service_titles (movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE, service TEXT NOT NULL, title_id TEXT, manual INTEGER NOT NULL DEFAULT 0, checked_at TEXT, PRIMARY KEY (movie_id, service))`, created by `SCHEMA` (`CREATE TABLE IF NOT EXISTS`), so v1 and v2 databases gain it on the next start.
  - `wikidata.WikidataError(Exception)` with `.message`; `wikidata.netflix_id(tmdb_id: int, tmdb_type: str) -> str | None`: one GET to `https://query.wikidata.org/sparql` with `format=json` and the query of spec §3 (`P4947` for `"movie"`, `P4983` for `"tv"`), `User-Agent: UA`, `Accept: application/sparql-results+json`, `timeout=10`. Returns the first binding's value when it matches `^[0-9]{1,12}$`, else the next that does, else `None`. Raises `WikidataError` for any exception, a non-200, or a body that isn't the expected JSON object.
  - `titles.NETFLIX = "netflix"`, `titles.STALE_DAYS = 30`.
  - `titles.on_netflix(con, movie_id) -> bool`: `"netflix"` is in the providers cache's `flatrate` tier (no TMDB call).
  - `titles.get(con, movie_id, service=NETFLIX) -> str | None`: the stored id.
  - `titles.out(con, movie_id) -> dict | None`: `{"title_id": str | None, "manual": bool}`, or `None` when the movie is not on Netflix.
  - `titles.lookup(con, movie_id) -> str | None`: does nothing and returns the stored id when the movie is not on Netflix or its id is manual; otherwise asks Wikidata and stores the answer (an id, or `NULL` for none) with `checked_at`. Lets `WikidataError` out.
  - `titles.lookup_quietly(con, movie_id) -> None`: `lookup` that logs one warning and returns on `WikidataError`.
  - `titles.due(con) -> list[int]`: ids of movies on Netflix, not manual, never checked or checked over `STALE_DAYS` ago.
  - `titles.parse_link(raw) -> str | None`: `None` for empty or whitespace; the digits from `netflix.com/title/<digits>` or `netflix.com/watch/<digits>` (any scheme, `www.` or not, an optional locale segment like `/us/` or `/en-gb/`, any query string or fragment) or from a bare 1-to-12-digit string; otherwise `abort(make_err(400, "That doesn't look like a Netflix link."))`.
  - `titles.set_manual(con, movie_id, raw) -> None`: a parsed id is stored with `manual=1`; empty deletes the manual row (so the next lookup refills it).
  - `PUT /api/movies/<id>` accepts `{"netflix_link": str}` alongside its existing fields; every movie from the API carries `"netflix": titles.out(...)`.
  - `POST /api/movies` calls `titles.lookup_quietly` after the providers are fetched.
  - `ops/wonderful-refresh` gains a step after the Matinee ones: `titles.lookup` for each id in `titles.due`, stopping at the first `WikidataError` with a line in its output and a non-zero exit like the other steps; `--dry-run` lists what it would ask.

- [ ] **Step 1: Write the failing tests** in `tests/test_titles.py`, with a `wikidata_fixtures` fixture modelled on `tmdb_fixtures` in `tests/conftest.py` (a fake `urlopen` that serves a named fixture and records each request's URL and headers). Fixtures: `netflix_klaus.json` is the real answer for TMDB 508965 (one binding, `80183187`); `none.json` has empty `bindings`; `two_ids.json` has `596974` then `70000001`; `bad_value.json` has `80183187; rm` then `1234567890123` then `60031255`.
  - `test_netflix_id_reads_the_first_binding` (`"80183187"`, and the request URL contains `P4947` and `508965`, with `User-Agent` set); `test_tv_uses_the_tv_property` (`P4983`); `test_none_found` (`None`); `test_first_of_two` (`"596974"`); `test_values_that_are_not_ids_are_skipped` (`"60031255"`).
  - `test_wikidata_errors` parametrized: `URLError`, `TimeoutError`, `HTTPError` 500, a body of `<html>`, a body of `[]`, a body of `{"results": {}}` → `WikidataError`.
  - `test_lookup_stores_the_id`, `test_lookup_stores_none_and_does_not_ask_again_for_30_days` (`due` is empty right after, and lists the movie when `checked_at` is 31 days old), `test_lookup_skips_a_movie_not_on_netflix` (no request made, `out` is `None`), `test_lookup_never_changes_a_manual_id` (no request made), `test_clearing_a_manual_id_lets_the_lookup_fill_it`.
  - `test_parse_link` parametrized: `https://www.netflix.com/title/80183187`, `http://netflix.com/watch/80183187?trackId=1`, `https://www.netflix.com/us/title/80183187`, `https://www.netflix.com/en-gb/title/80183187#x`, `80183187`, ` 80183187 ` → `"80183187"`; `""`, `"  "` → `None`. `test_parse_link_refuses` parametrized: `netflix.com/title/abc`, `https://www.disneyplus.com/browse/entity-1`, `80183187/../x`, `1234567890123`, `https://evil.example.com/?u=netflix.com/title/1`, `5` as an int → 400 with `"That doesn't look like a Netflix link."`.
  - Through the API: `test_put_saves_and_clears_the_link` (PUT `{"netflix_link": "…/title/80183187"}` → `netflix == {"title_id": "80183187", "manual": True}`; PUT `{"netflix_link": ""}` → `{"title_id": None, "manual": False}`); `test_add_looks_the_id_up` (with `tmdb_fixtures` and `wikidata_fixtures`, a movie added that is on Netflix has its id); `test_add_survives_wikidata_down` (201, `netflix.title_id` `None`, one warning in `caplog`).
  - `tests/test_schema.py`: version `"3"`; `test_v2_database_gains_service_titles` (build the v2 schema from `git show 7b7f961:db.py`, one movie row, `migrate()` twice: the table exists, the row is unchanged). Nightly: `test_refresh_asks_only_what_is_due` and `test_refresh_stops_at_the_first_wikidata_failure`, following the existing tests of `ops/wonderful-refresh`.
- [ ] **Step 2: Run and see them fail.** `.venv/bin/python -m pytest tests/test_titles.py tests/test_schema.py -q`.
- [ ] **Step 3: Implement** the interfaces. README: one paragraph under "Where to watch" on the Netflix link (what it is for, that the TMDB id goes to Wikidata, that it fills in Task 2's direct play), and the nightly-refresh paragraph gains the step.
- [ ] **Step 4: Run the gate.** `sh scripts/gate.sh` → `gate passed`.
- [ ] **Step 5: Commit.** `feat(netflix): keep a Netflix title id per movie, from Wikidata or by hand`.

---

### Task 2 (M): Start the movie on Netflix

**Files:**
- Modify: `play.py` (`_parts`/`options`, `_target`, `start`), `static/js/play.js` (the opening line), `static/js/detail.js` and `static/style.css` (the Netflix link field), `docs/home-assistant.md` (script and automation), `README.md`, `tests/test_play.py`, `tests/test_ui_play.py`, `tests/test_ha_doc.py`
- Test: those three test files

**Interfaces:**
- Consumes: `titles.get(con, movie_id) -> str | None`, `titles.out`, `titles.NETFLIX`, and `netflix` on each movie (Task 1).
- Produces:
  - Each stream option gains `"direct": bool`: true only for service `netflix` when `titles.get` returns an id. (A Netflix option exists only when the movie is `flatrate` on Netflix and Netflix is Subscribed, so an id for a movie no longer on Netflix is never used.)
  - `play.start`: when the chosen target is a direct option, the payload gains `"content_id": "<digits>"` and the answer `"direct": true`; otherwise the payload has no `content_id` key and the answer has `"direct": false`. A stored id that fails `^[0-9]{1,12}$` is treated as absent.
  - `play.js`: for a direct target the opening line is `"Starting {title} on Netflix…"`; `openingName`'s other cases are unchanged.
  - `detail.js`: under the Where to watch list, when `m.netflix` is not null, a labelled **Netflix link** input (`id="detail-netflix"`, showing the current id), a **Save** button (`id="detail-netflix-save"`) and a hint reading "Found automatically", "Set by hand", or nothing when there is no id. Save sends `PUT /api/movies/<id>` `{"netflix_link": value}`, redraws the section and the Play section, and shows the server's sentence on a 400.
  - `docs/home-assistant.md`: the script gains an optional `content_id` field. In the stream branch, after the wait and the settle delay, a `choose` with a default:
    - `content_id` non-empty and `source` is `Netflix`: action `webostv.command` on the TV entity, `command: system.launcher/launch`, payload `id: netflix`, `contentId: "m=https://www.netflix.com/watch/{{ content_id }}&source_type=4"`;
    - `content_id` non-empty and `source` is `YouTube`: the same action with payload `id: youtube.leanback.v4`, `contentId: "v={{ content_id }}"`;
    - default: `media_player.select_source` as now.
    The automation's condition also requires `trigger.json.content_id`, when defined, to match `^[A-Za-z0-9_-]{1,64}$`, and passes `content_id: "{{ trigger.json.content_id | default('') }}"`. The prose says these two apps were tried on an LG webOS TV on 2026-11-26, that Disney+ ignored the same idea, that this app sends a `content_id` for Netflix only, and that the YouTube case is for other callers of the script.

- [ ] **Step 1: Write the failing tests.**
  - `tests/test_play.py`: `test_netflix_with_an_id_is_direct` (option `direct` true; payload `content_id == "80183187"`; answer `direct` true); `test_netflix_without_an_id_is_not_direct` (no `content_id` key in the payload); `test_other_services_are_never_direct` (an id stored for the movie, play on `disney_plus`: no `content_id`); `test_a_digital_copy_ranks_first_and_is_not_direct` (`auto` goes to Fandango at Home with no `content_id`; `{"mode": "stream", "service": "netflix"}` is direct); `test_an_id_for_a_movie_no_longer_on_netflix_is_unused` (no Netflix option at all); `test_netflix_considering_is_unused`; `test_a_stored_id_that_is_not_digits_is_ignored` (write `80183187; rm` straight into the table: `direct` false, no `content_id`).
  - `tests/test_ui_play.py`: `test_direct_play_says_starting` (the status reads "Starting Klaus on Netflix…"); `test_netflix_link_field` at 412 and 360 px (the field shows the id and "Found automatically"; saving `https://www.netflix.com/title/60031255` shows the new id and "Set by hand"; saving `abc` shows "That doesn't look like a Netflix link." and keeps the old id; the input and button are at least 44 px tall; no horizontal scroll); `test_no_netflix_field_for_a_movie_not_on_netflix`; `test_netflix_field_second_visit` (open, back, open again, save once: one PUT).
  - `tests/test_ha_doc.py`: the doc contains `webostv.command`, `system.launcher/launch`, `m=https://www.netflix.com/watch/{{ content_id }}&source_type=4`, `youtube.leanback.v4`, `v={{ content_id }}`, `content_id`, and the pattern `^[A-Za-z0-9_-]{1,64}$`; the existing needles still pass.
- [ ] **Step 2: Run and see them fail.** `.venv/bin/python -m pytest tests/test_play.py tests/test_ha_doc.py -q` and `sh scripts/gate.sh ui`.
- [ ] **Step 3: Implement.** README: the Play entry says Netflix starts the movie itself when the app knows its Netflix id.
- [ ] **Step 4: Run the gate.** `sh scripts/gate.sh` → `gate passed`. Load every yaml block of `docs/home-assistant.md` with the system `python3`'s PyYAML (a stub for `!secret`) and say so in the report; do not add PyYAML to the repo.
- [ ] **Step 5: Commit.** `feat(play): start the movie itself on Netflix`. The PR's "Try it": after the Home Assistant script is updated, open a Netflix movie, tap **Stream it**, and the film should start playing.

---

## After the code (not a PR)

- [ ] Update Nick's live `script.wonderful_play_on_tv` and its webhook automation to the documented versions (Claude, through the Home Assistant tools, on Nick's go-ahead).
- [ ] At the TV: a direct play from a cold TV; with Netflix already open on another title; a Netflix movie with no id still opens the app.
