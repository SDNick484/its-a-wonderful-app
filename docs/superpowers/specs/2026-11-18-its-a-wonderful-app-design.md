# It's a Wonderful App — design

**Date:** 2026-11-18
**Repo:** `SDNick484/its-a-wonderful-app` (new, empty, public)
**Sibling:** Matinee (`SDNick484/matinee`, `main` @ `78296c4`, schema v12), read for this spec
**Status:** Approved by Nick on 2026-11-18

---

## 1. Intent

A Christmas movie picker that Nick is building with his oldest daughter Margaret ("Midge"). It's her first
time building something with AI. The family opens it on a phone on a December evening, finds or is handed a
movie, picks it, watches it (often over two nights), and rates it. It feels like Matinee, with posters,
ratings and a dark cinema look, but it's dressed for Christmas and its scene changes each week of Advent.

It is a **separate app** from Matinee. Matinee stays limited to movies the family owns (discs, plus permanent
licenses on Movies Anywhere or Fandango at Home). This app holds a curated Christmas list, most of which is
streaming. The two apps share ratings and watches for the movies they have in common.

Margaret's own description of the core loop: *"I open the app, there's a search at the top, I describe what
I want ('a movie related to Jesus', 'a musical') or just say 'Elf', or I tap a randomizer. I select it. Ideally
it starts on the TV; if not, it at least marks that it's tonight's movie."*

### Success

- In December 2026 the family uses it to pick most of their Christmas movies.
- Margaret can explain how a feature she asked for got built, and ran some of the build herself.
- Ratings and watches agree between this app and Matinee without anyone re-entering them.

### Goals

1. A curated, growing list of Christmas movies with posters, ratings, runtime and certification.
2. "Where to watch" for every movie: the shelf or digital locker if owned (from Matinee), otherwise current
   streaming services (TMDB watch providers, JustWatch data).
3. Search by title, by description ("a musical"), by actor or by series, with AI for descriptions.
4. A randomizer that shows three picks at once, with filters and Pick Again.
5. Continue Watching: a movie can take more than one night. The app guesses "not finished" from the Family
   Room TV through Home Assistant, and asks to confirm.
6. Per-person ratings (0 to 10 in 0.5 steps) whose average is shown and becomes Matinee's household rating.
7. Four themes that rotate on the Sundays of Advent through January 6, drawn by Margaret, with motion on top.
8. "Worth a Month?": which streaming service the family doesn't have would add the most unwatched movies.

### Non-goals

- Playing video. The app hands off to the TV and streaming apps.
- Movies beyond Christmas (Halloween etc.). The schema shouldn't block it, but nothing is designed for it.
- A public view. Nothing here is meant for people outside the family.
- Logins for the kids. They have no devices or emails of their own.
- Moving owned-movie data out of Matinee. Matinee stays the source of truth for what is owned and where.

### Anti-goals (fails even if it technically works)

- Margaret can't follow how it's built, because the issues are too big or too abstract for her to run.
- The randomizer lands on a rental at 8 pm, or on a PG-13 movie on a night the twins are picking.
- "Watched" or a rating disagrees between this app and Matinee by New Year's.
- The scene behind the posters makes titles or ratings hard to read.
- The app quietly adds movies to the list. Only a person adds a movie.

## 2. Decisions from brainstorming (2026-11-18)

| # | Topic | Decision | Who |
|---|---|---|---|
| 1 | Separate app or a Matinee mode | Separate app, sibling to Matinee in look and stack | Nick |
| 2 | Matinee scope | Matinee only holds owned movies (physical, or permanent digital on Movies Anywhere / Fandango at Home) | Nick |
| 3 | How the apps connect | LAN API calls; this app reads ownership and ratings from Matinee and writes ratings and watches back (§8) | Nick, approach A |
| 4 | Which movies | A curated list, starting from Nick's list (§17), grown over time | Margaret |
| 5 | New movies from search | Search may suggest movies not on the list, with an "Add to our list" button. Never added automatically | Margaret |
| 6 | Unfinished movies | A Continue Watching row, like Disney+ | Margaret |
| 7 | Detecting "not finished" | Guess from the TV's on/off and input changes vs. the movie's runtime, then ask "Did you finish?" with the guess preselected | Margaret (accepted proposal) |
| 8 | After a movie | Ask "Want to rate it?" | Margaret |
| 9 | Rating scale | Same as Matinee: 0 to 10 in 0.5 steps | Nick, Margaret |
| 10 | Who rates | Each person rates individually; the average is the family rating and is what Matinee receives | Margaret, Nick agreed |
| 11 | Rating conflicts | Before anyone rates here, show Matinee's rating. After, this app owns the rating; a later Matinee edit raises a notice, never a silent overwrite | Proposed, not objected to |
| 12 | Randomizer pool | All movies on the list, narrowed by filter chips | Margaret |
| 13 | Randomizer filters | Animated, Live action, rating cap (up to G / PG / PG-13), Under 90 min, Not watched this year, Ready to watch | Margaret, Nick |
| 14 | Randomizer output | Three picks at once; Pick Again replaces all three | Margaret |
| 15 | Subscriptions | Netflix, Disney+, Hulu, Prime Video, Fandango at Home, YouTube TV. Unsure / would add for a month: HBO Max, Peacock, Paramount+, Apple TV | Nick |
| 16 | Worth a Month? | Yes | Nick, Margaret |
| 17 | Themes | Fireplace, toy store, Christmas tree, Santa's sleigh at night; one per Advent week from the first Sunday of Advent, Santa through January 6; plain (light or dark) the rest of the year | Margaret |
| 18 | Theme art | Margaret draws the scenes; AI may clean them up; motion (flames, snow, lights, sleigh) is code on top | Margaret |
| 19 | Name | **It's a Wonderful App** (Lauren). The randomizer button reads "🎲 Surprise us, ya filthy animals" (Margaret) | Family |
| 20 | Free-with-ads services | Count as "ready to watch" | Proposed, not objected to |
| 21 | How the family streams | The LG's built-in apps, so the TV's `source` names the service | Nick |
| 22 | Deployments | Nick deploys and manages releases with Margaret; each merged PR goes to the live app, with no staging copy | Nick |
| 23 | HA movie log | Finishing a movie here adds it to the Family Room dashboard's movie log (§8.5) | Nick |

## 3. Approaches considered

| | Approach | Trade-off | Verdict |
|---|---|---|---|
| A | Own repo and database, Matinee's stack; talks to Matinee's `/admin/api` with a key over the LAN | One more client of Matinee's API to keep compatible, as the MCP server's REST mode already is | **Chosen** (Nick: "cleaner") |
| B | Same stack, in Matinee's container, reads `matinee.db` directly; writes through the API | Faster start; every Matinee migration can break it | Rejected |
| C | A "Christmas mode" inside Matinee | Contradicts decision 2: the list is mostly streaming | Ruled out |
| D | Browser-only page (Matinee API + TMDB from the client) | Per-person ratings, the HA webhook and the sync need a server | Ruled out |

## 4. Constraints

- **Stack parity with Matinee** (its `CLAUDE.md` rules apply here unless this spec says otherwise): Flask +
  gunicorn, SQLite in `$DATA_DIR`, vanilla JS as native ES modules in `static/js/` with no framework, bundler or
  npm build; runtime deps only as Alpine `py3-*` packages; Alpine LXC, OpenRC service `wonderful`; config in
  `/etc/conf.d/wonderful`; self-extracting installer `dist/setup-wonderful.sh` that preserves data and config;
  `ops/wonderful-backup`.
- **Tests:** pytest, no live network, recorded fixtures for TMDB, Matinee, Home Assistant and Anthropic responses.
  Every external call has a miss test and an HTTP-error test.
- **CI:** Python 3.10–3.13 on Ubuntu, an Alpine container job, ruff, `node --check` on every `static/js/*.js`,
  and a Playwright UI smoke job at 412 px.
- **Phone-first:** Android Chrome at 412 px is the primary screen. At least 3 poster columns, no horizontal
  scroll, tap targets ≥ 44 px. WCAG AA (≥ 4.5:1) for all text, including over themes.
- **Hygiene:** the repo is public. No personal hostnames, LAN addresses or container IDs in code or docs; use
  `wonderful.example.com`, `movies.example.com`, `ha.example.com`, `192.168.1.100`. No people are seeded in
  code; names live only in the database (as in Matinee).
- **Commits:** Conventional Commits, one logical change each, feature branches merged by PR, author
  `SDNick484 <SDNick484@users.noreply.github.com>`. Superpowers flow (specs, plans, `.superpowers/sdd/`).
- **TMDB attribution** (logo + notice) and **JustWatch attribution** wherever watch providers appear.

## 5. Architecture

```
 Phone (Android Chrome)                      Home Assistant
   │  https://wonderful.example.com             │  automation on the Family Room TV
   ▼                                            │  (media_player.<family_room_tv>)
 It's a Wonderful App (Flask, SQLite)  ◄────────┘  POST /hooks/tv  (shared secret)
   │            │             │
   │            │             └──► Anthropic API (AI search only)
   │            └──► TMDB (metadata, posters, watch providers, credits, collections)
   └──► Matinee /admin/api (LAN, MATINEE_API_KEY)
          reads: owned copies + location, household rating, people
          writes: household rating, watch (+ attendees)
```

- **Hosting (builder's call, my suggestion):** the same Alpine container as Matinee and Wish Lists, its own
  OpenRC service and port, exposed through the existing Cloudflare Tunnel as its own hostname.
- **Access:** the whole app (pages and API) requires either a direct LAN request (`LAN_EDIT`-style: addressed by
  IP, localhost or a `LAN_HOSTS` name, not via Cloudflare) or a verified Cloudflare Access JWT for an
  `ADMIN_EMAILS` user. There is no anonymous public view. `/hooks/tv` instead requires the `HA_HOOK_SECRET`
  header. Reuse Matinee's auth code shape (`editor_required`, `lan_host()`, JWT check) rather than inventing one.
  *Caveat to verify in the build:* Matinee's notes say it's always opened by hostname even on the LAN, which
  routes through Cloudflare. If the same is true here, the kids' phone would need either an Access session or
  a `LAN_HOSTS` local DNS name. The first infra task settles which, on real hardware.

## 6. Data model (schema v1)

```sql
CREATE TABLE movies (                  -- the curated list
  id INTEGER PRIMARY KEY,
  tmdb_id INTEGER NOT NULL,
  tmdb_type TEXT NOT NULL DEFAULT 'movie' CHECK (tmdb_type IN ('movie','tv')),   -- a few specials may be TV-only
  title TEXT NOT NULL, year INTEGER, runtime_min INTEGER,
  certification TEXT,                  -- US: G, PG, PG-13, NR (or NULL). Editable by hand
  certification_override INTEGER NOT NULL DEFAULT 0,
  overview TEXT, poster_path TEXT, backdrop_path TEXT,   -- local copies, as Matinee
  is_animated INTEGER NOT NULL DEFAULT 0,               -- TMDB genre 16
  collection_id INTEGER, collection_name TEXT,          -- "The Santa Clause Collection"
  top_cast TEXT,                       -- JSON array, first 8 billed names
  tmdb_vote REAL,
  parent_note TEXT,                    -- e.g. the Wimpy Kid Santa warning; shown only on the detail view
  added_by TEXT, added_at TEXT DEFAULT CURRENT_TIMESTAMP,
  meta_refreshed_at TEXT,
  UNIQUE (tmdb_type, tmdb_id)
);

CREATE TABLE providers_cache (         -- TMDB watch providers, US region, refreshed (§7.2)
  movie_id INTEGER PRIMARY KEY REFERENCES movies(id) ON DELETE CASCADE,
  data TEXT NOT NULL,                  -- {"flatrate":[...], "free":[...], "ads":[...], "rent":[...], "buy":[...]}
  link TEXT, fetched_at TEXT NOT NULL
);

CREATE TABLE services (                -- streaming services the family knows about
  key TEXT PRIMARY KEY,                -- 'netflix', 'disney_plus', 'hbo_max', ...
  name TEXT NOT NULL,                  -- display name
  tmdb_provider_ids TEXT NOT NULL,     -- JSON array; one service can map to several TMDB provider ids
  status TEXT NOT NULL CHECK (status IN ('subscribed','considering','ignore')),
  tv_source TEXT                       -- the TV's input name, e.g. 'Disney+' (for §10 and the later TV launch)
);

CREATE TABLE people (                  -- mirrors Matinee's people by name (§8.4)
  id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
  kind TEXT NOT NULL CHECK (kind IN ('adult','kid')),
  color TEXT NOT NULL,                 -- green | blue | red | pink | purple (Matinee's palette keys)
  sort_order INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE person_ratings (
  person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
  rating REAL NOT NULL CHECK (rating >= 0 AND rating <= 10),   -- 0.5 steps, validated in code
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (person_id, movie_id)
);

CREATE TABLE viewings (                -- one attempt at watching a movie, possibly over several nights
  id INTEGER PRIMARY KEY,
  movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
  started_on TEXT NOT NULL,            -- local date of the first night
  status TEXT NOT NULL CHECK (status IN ('tonight','watching','paused','finished','abandoned')),
  watched_seconds INTEGER NOT NULL DEFAULT 0,   -- summed across sessions
  guess TEXT CHECK (guess IN ('finished','not_finished')),   -- set when a session ends; drives the prompt
  finished_on TEXT,
  matinee_watch_id INTEGER,            -- set once the watch is posted to Matinee
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE viewing_people (viewing_id INTEGER REFERENCES viewings(id) ON DELETE CASCADE,
                             person_id INTEGER REFERENCES people(id), PRIMARY KEY (viewing_id, person_id));

CREATE TABLE sessions (                -- one evening's TV time for a viewing
  id INTEGER PRIMARY KEY,
  viewing_id INTEGER NOT NULL REFERENCES viewings(id) ON DELETE CASCADE,
  tv_source TEXT,                      -- input when it started, e.g. 'Disney+' or 'AV Receiver'
  started_at TEXT NOT NULL, ended_at TEXT,
  end_reason TEXT                      -- 'tv_off', 'source_changed', 'manual', 'timeout'
);

CREATE TABLE matinee_sync (            -- what we last told / heard from Matinee, per movie
  movie_id INTEGER PRIMARY KEY REFERENCES movies(id) ON DELETE CASCADE,
  matinee_title_id INTEGER,            -- NULL = not owned / not in Matinee
  owned_summary TEXT,                  -- "Blu-ray · Movies Anywhere"
  location_path TEXT,                  -- "Family Room › Media Cabinet › Shelf 2"
  matinee_rating REAL,                 -- last seen
  pushed_rating REAL,                  -- last value we wrote
  rating_owner TEXT NOT NULL DEFAULT 'matinee' CHECK (rating_owner IN ('matinee','wonderful')),
  conflict_rating REAL,                -- Matinee changed after we took over; shown as a notice
  checked_at TEXT
);

CREATE TABLE ai_cache (q_norm TEXT PRIMARY KEY, list_hash TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT);
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);   -- schema version, settings that live in the DB
```

- `migrate()` from day one, idempotent, `SCHEMA_VERSION = "1"`, the Matinee pattern.
- **Seed data:** the 41 starting movies are added from a checked-in file `data/seed-movies.json` of TMDB ids,
  certifications and parent notes, through the same code path as "Add to our list". Services are seeded from a
  checked-in list with statuses set as in decision 15. People are not seeded (§8.4).

## 7. The list

### 7.1 Adding a movie

An editor (anyone allowed in, §5) searches TMDB by title and taps a result. The app fetches details (runtime,
genres, US certification from release dates, collection, credits for the top 8 cast), downloads the poster
locally, fetches watch providers, asks Matinee about ownership, and adds the row. The parent note is an
optional text field on the detail view. Removing a movie from the list is allowed and asks for confirmation;
its ratings and viewings go with it.

**Scenario: add Prancer.** Search "Prancer" → *Prancer* (1989), G, 103 min. Tap **Add to our list**. The grid
gains its poster. Its card reads "Not owned · Rent or buy" until providers say otherwise.

### 7.2 Where to watch

Shown on every card and detail view, in this order:

1. **Owned** (from Matinee): `owned_summary` and `location_path`, e.g. "Blu-ray · Family Room › Media
   Cabinet › Shelf 2" or "Movies Anywhere".
2. **On a subscribed service** (flatrate on a `subscribed` service).
3. **Free** (TMDB `free` or `ads`): "Free with ads on The Roku Channel".
4. **On a service you're considering**: "On Peacock (you don't have it)".
5. **Rent or buy** only.

Provider data is TMDB `/movie/{id}/watch/providers`, region US, with JustWatch attribution. It's refreshed when
older than 7 days, and on demand from the detail view. The Duet list's text in §17 is reference only, never
stored as availability.

### 7.3 Certification

From TMDB US release dates. If none, `NR`. An editor can override it (`certification_override = 1` stops the
refresh from changing it back). For the rating-cap filter, `NR` counts as **PG**: it passes "up to PG" and
"up to PG-13" but not "up to G". *White Christmas* and *A Loud House Christmas Movie* are the current NR titles.

## 8. Matinee sync

All calls use Matinee's existing editor API with `MATINEE_API_KEY` as `Authorization: Bearer`. Matinee needs
**no code change** for this design: every route below already exists at `78296c4`.

| Need | Matinee route |
|---|---|
| Is it owned, and where | `GET /admin/api/tmdb/<tmdb_id>/owned` → `{title_id, copies[{label, location_path…}], summary}` |
| Household rating | `GET /admin/api/titles/<title_id>` → `user_rating` |
| Set household rating | `PUT /admin/api/titles/<title_id>/rating` `{"rating": 8.5}` (0.5 steps, else 400) |
| Log a watch | `POST /admin/api/titles/<title_id>/watches` `{"watched_date": "2026-12-12", "attendees": ["Nick","Lauren","Midge","Alice","Paige"]}` |
| People | `GET /admin/api/people` |

### 8.1 Ownership refresh

On add, on the detail view if `checked_at` is older than a day, and in a nightly `ops/wonderful-refresh` run
(with provider refresh). A title Matinee doesn't have (`title_id: null`), or has with no copies, is "not owned".
A Matinee outage never blocks the app: it shows the last known value with "(as of Dec 3)".

### 8.2 Ratings

- **Before anyone rates here** (`rating_owner = 'matinee'`): the poster shows Matinee's `user_rating`, labeled
  "family rating from Matinee" on the detail view.
- **The first person rating** flips `rating_owner` to `wonderful`. From then on the shown family rating is
  the mean of `person_ratings` to one decimal (8.6), and Matinee receives that mean **rounded to the nearest
  0.5** (8.5) because Matinee only accepts 0.5 steps. Ties round up (8.25 → 8.5, 8.75 → 9.0).
- The app pushes on every change to `person_ratings` for an owned movie, and records `pushed_rating`.
- **Conflict:** when a refresh sees `matinee_rating ≠ pushed_rating` on a `wonderful`-owned movie, it stores
  `conflict_rating` and the detail view shows "Matinee says 9, we say 8.6 · Use ours / Use Matinee's / Dismiss".
  "Use Matinee's" can't be split across people, so it reverts `rating_owner` to `matinee` (person ratings stay
  but stop driving Matinee until someone rates again).
- Movies Matinee doesn't own: ratings live here only.
- **Bought later** (Claude's call): when a refresh finds a movie newly owned that already has person ratings
  here, the app sets `rating_owner = 'wonderful'`. If Matinee has no rating, it pushes the rounded mean. If
  Matinee already has a different rating, it doesn't push. It raises the conflict notice instead.
- **TV-only entries** (`tmdb_type = 'tv'`) skip the Matinee lookup entirely. Matinee keys titles by movie
  TMDB id only, so a TV id could match an unrelated movie. When TMDB has both a movie and a TV entry, the seed
  prefers the movie.
- Matinee's own seasonal lists (v12 has a Christmas list) are unrelated to this app's list and aren't read.

**Scenario: rating Klaus.** *Klaus* isn't owned. After the credits, the family rates N 8, L 9, M 10, A 8, P 8.
The poster shows ★ 8.6. Nothing goes to Matinee.

**Scenario: rating Elf.** *Elf* is owned on Blu-ray with Matinee rating 9.0. Before tonight the poster shows
★ 9.0. Tonight N 8.5, L 9, M 10, A 9, P 8 → mean 8.9, shown ★ 8.9; Matinee gets `{"rating": 9.0}`.

### 8.3 Watches

When a viewing becomes `finished` and the movie is owned, the app posts one watch to Matinee dated
`finished_on`, with `attendees` = the viewing's people, mapped by name to Matinee's people and dropping names
Matinee doesn't know. It never sends `"live": true`. This app tells Home Assistant itself (§8.5), so sending it would
log the movie twice. It stores the returned `matinee_watch_id`. If the post fails, the viewing keeps a "not synced"
flag and the nightly job retries.

Watches for movies Matinee doesn't own live only here. "Not watched this year" uses this app's viewings plus
Matinee's watches this calendar year for owned movies.

### 8.4 People

The app keeps its own `people` table so rating works when Matinee is down. On first run, and from a "Sync
people from Matinee" button in settings, it copies name, kind, color and order from `GET /admin/api/people`.
People can also be added here (e.g. a grandparent visiting); such a person rates normally, and is dropped from
the attendee list sent to Matinee.

### 8.5 Home Assistant movie log

Every finished viewing, owned or not, posts to `HA_WEBHOOK_URL`. Use the same webhook URL as Matinee, so the
existing automation that keeps the Family Room dashboard's movie log picks it up unchanged. The payload copies
Matinee's `ha_payload()` shape and event name, plus a `source` key:

```json
{"event": "matinee_watch_logged", "source": "wonderful", "title": "Home Alone", "year": 1990,
 "runtime": 103, "certification": "PG", "formats": ["Blu-ray"],
 "location": "Family Room › Media Cabinet › Shelf 2", "watched_date": "2026-12-13", "title_id": null}
```

For a movie that isn't owned, `formats` is `[]` and `location` is `null`. `title_id` is always `null`
(Matinee's id would be misleading here). The post is fire-and-forget on a daemon thread, logged as a
host-only warning on failure, exactly like Matinee's `post_ha_event()`. It runs once per viewing, when the
viewing becomes `finished`.

## 9. Search

One box at the top. As you type, it filters the list locally by title, year, cast and collection, with no
network. On **Enter** (or the search button):

1. **Exact or near-exact title match** on the list (normalized, ignoring punctuation and "The"): show it, done.
   No AI call. "elf" → *Elf*.
2. Otherwise **AI search** (`ANTHROPIC_API_KEY` set): one Messages API call. The prompt holds the whole list
   as compact JSON (id, title, year, certification, runtime, animated, collection, top cast, overview, parent
   note) and the query. The model returns JSON: `{"matches": [{"id": 12, "why": "the Nativity story"}],
   "suggestions": [{"title": "The Nativity Story", "year": 2006, "why": "..."}]}` with up to 8 matches and up to
   3 suggestions not on the list. The app checks every id exists, resolves each suggestion through TMDB search
   (dropping ones it can't find or that are already on the list), caches the result by normalized query and a
   hash of the list (`ai_cache`), and shows:
   - matches as posters with their one-line "why";
   - a **Not on our list yet** section with the suggestions and an **Add to our list** button each.
3. **No API key, or the call fails:** fall back to the local filter of step 0 and say "Smart search is off
   right now."

Model, key, timeout and a daily call cap live in settings. The query text and the list (titles, cast, and
parent notes) go to Anthropic; nothing about people or ratings does.

**Scenario.** "a movie about Jesus" → matches *The Star* ("the Nativity story, told by the animals"); suggestions
include *The Nativity Story* (2006, PG). Tapping Add runs §7.1 for it.

## 10. Picking a movie, Continue Watching, and the TV

### 10.1 Picking

Tapping **Watch tonight** on a movie creates a viewing (`status = 'tonight'`, people = all active people, which
can be edited with the same colored dots as rating) or reuses an open one for that movie. It appears first in
**Continue Watching**.

*Builder's-check calls (Claude):*

- Tapping a `paused` movie in Continue Watching shows **Keep watching tonight**, which puts it back to
  `tonight`. That's how night two gets TV events again.
- Picking a second movie while one is `tonight` moves the first back to `paused`, or deletes it if it has no
  watched time. Only one viewing is ever `tonight`.
- A `tonight` viewing with no session by 4 am local the next day reverts the same way, so a movie that was
  picked and never watched can't block detection.

### 10.2 The TV webhook

A Home Assistant automation on the Family Room TV's `media_player` (on/off and `source` changes) posts to
`POST /hooks/tv` with header `X-Hook-Secret`:

```json
{"state": "on", "source": "Disney+", "at": "2026-12-12T19:31:04-08:00"}
```

The current TV (LG 77G1) reports `state` and `source` (e.g. "Disney+", "Netflix", "HBO Max", "Peacock", "AV
Receiver") but not the title or playback position. The family streams through the LG's built-in apps
(decision 21), so `source` names the service. Discs come in through the receiver ("AV Receiver"). The app documents the automation YAML in
`docs/home-assistant.md`; it doesn't configure HA itself.

Rules, applied only when exactly one viewing is `tonight` or `watching`:

| Event | Effect |
|---|---|
| TV on, or source changes to a source that can play this movie (its provider's `tv_source`, or the receiver input for an owned disc) | Open a session; viewing → `watching` |
| Source changes to anything else (YouTube, Live TV) | Close the session, `end_reason = 'source_changed'` |
| TV off | Close the session, `end_reason = 'tv_off'` |
| A session open longer than runtime + 60 min | Close it at runtime + 60, `end_reason = 'timeout'` |

Closing a session adds its length to `watched_seconds` and sets `guess`: **finished** if
`watched_seconds ≥ 0.85 × runtime`, else **not_finished**; viewing → `paused`. With two or more open viewings,
events are ignored (the app can't tell which), and the prompt has no preselected answer.

### 10.3 "Did you finish?"

The next time anyone opens the app after a session closes, a sheet asks **Did you finish *Home Alone*?** with
**Yes** and **Not yet**, the guess preselected (highlighted, still needs a tap), plus "We gave up on it" in small
text (`abandoned`, drops off the row). "We finished" is also a button on the movie in Continue Watching, for
nights without the webhook.

- **Not yet:** stays in Continue Watching with "About halfway" / "Just started" / "Almost done" from
  `watched_seconds / runtime` (< 25 %, 25–75 %, > 75 %).
- **Yes:** `finished`, `finished_on` = date of the last session (or today), then "Want to rate it?" (§11), then
  the Matinee watch (§8.3).

**Scenario: Home Alone over two nights.** Dec 12, 7:30 pm: Margaret taps Watch tonight on *Home Alone* (103 min).
7:31 the TV switches to Disney+ → session opens. 8:21 TV off → 50 min, guess not finished. Dec 13 she opens the
app: "Did you finish *Home Alone*?" with Not yet highlighted. She taps it. Continue Watching shows *Home Alone*,
"About halfway". She taps it, then **Keep watching tonight**, and switches the TV to Disney+ with the remote
(Disney+ remembers the spot). At 8:50 the TV turns off at
50 + 55 = 105 min → guess finished. Next open: Yes, then rating.

## 11. Ratings UI

After **Yes**: "Want to rate it?" with **Rate** and **Skip**. Rate shows one row per person (the viewing's
people first, then the rest dimmed): a colored dot with their initial and a row of number buttons **1–10** plus
**½**, at least 44 px each, wrapping onto two lines at 412 px. Anyone can be left unrated. Done saves. A rating
can be changed later on the detail view, which shows the family rating and each person's:

```
Klaus · ★ 8.6 family
● N 8   ● L 9   ● M 10   ● A 8   ● P 8
```

## 12. The randomizer

```
 [ 🎲 Surprise us, ya filthy animals ]
 [Animated] [Live action] [Up to G|PG|PG-13] [Under 90 min] [Not watched this year] [Ready to watch]

 ┌───────┐ ┌───────┐ ┌───────┐
 │ Klaus │ │ Elf   │ │Prancer│      each: poster, runtime, where to watch
 └───────┘ └───────┘ └───────┘
          [ Keep the change (pick again) ]
```

- Draws 3 distinct movies uniformly at random from the list after filters. Fewer than 3 left: show what's
  there and say "Only 2 match. Try turning off a filter."
- **Pick Again** draws 3 new ones, excluding everything shown since the filters last changed, until the pool
  runs out; then it starts over and says so.
- **Animated / Live action** are mutually exclusive (both off = both). **Rating cap** is one chip that cycles
  off → G → PG → PG-13. **Under 90 min** uses `runtime_min < 90`. **Not watched this year** excludes any movie
  with a finished viewing (or a Matinee watch, if owned) in the current calendar year; a December 30 → January 6
  watch counts for the year it happened in. **Ready to watch** keeps owned movies, movies on a subscribed
  service, and free ones.
- Filter state is remembered per device in `localStorage` (guarded, as Matinee does). Every chip starts
  off, so the default pool is the whole list (decision 12).
- Tapping a pick opens its detail view, which has **Watch tonight**.

## 13. Worth a Month?

A card on the home screen in November and December, and always in settings. For each `considering` service:
the count and posters of list movies that are (a) not owned, (b) not on a subscribed or free service, (c) on
this service's flatrate, and (d) not watched this year. Sorted by count; a service adding 0 says so.

```
Peacock adds 3: How the Grinch Stole Christmas! (1966) · How the Grinch Stole Christmas (2000) · The Grinch (2018)
HBO Max adds 2: The Polar Express · 8-Bit Christmas
Apple TV adds 1: A Charlie Brown Christmas
Paramount+ adds 0: everything it has is already on Prime, Hulu or free
```

(Illustrative only; real numbers come from TMDB and Matinee.) Statuses are edited in settings: Subscribed,
Considering, Ignore.

## 14. Look and themes

### 14.1 Base look

Matinee's palette, type and grid: surfaces `#0b0b0e` / `#16161c` / `#202029`, ivory ink `#f3ead8` / `#b8b0a1`,
cinema red `#c8272d`, amber `#f2b544`, Figtree (bundled), family colors `--p-user1…5`. A light mode exists for
the plain (non-theme) period, chosen in settings and defaulting to the system setting. Poster grid of ≥ 3
columns at 412 px with the family rating on each poster.

### 14.2 Theme calendar

`theme_for(date)`: first Sunday of Advent = the fourth Sunday before December 25.

| Window | Theme |
|---|---|
| Advent 1 Sunday → Saturday | Fireplace |
| Advent 2 Sunday → Saturday | Toy store |
| Advent 3 Sunday → Saturday | Christmas tree |
| Advent 4 Sunday → January 6 | Santa's sleigh in the night sky |
| Otherwise | Plain (light or dark) |

2026: Nov 29, Dec 6, Dec 13, Dec 20 → Jan 6, 2027. Tests cover 2026, 2027 (Dec 25 on a Saturday, so
Advent 4 is Dec 19) and a year where Dec 25 is a Sunday (2022: Advent 4 is Dec 18; Dec 25 itself is not
Advent 4). Settings has **Preview themes** (a session-only override) and **Themes on/off**.

### 14.3 Layers

Each theme is a folder `static/themes/<key>/` with:

1. `background.webp`: Margaret's drawing, scanned or photographed, cleaned up (by hand or with AI image tools,
   outside this app), cropped to a portrait phone (1080 × 2340 master, served sized), plus a landscape crop
   for desktop.
2. Motion in CSS/canvas, no library: fireplace flames flicker and sparks rise; toy-store window lights twinkle;
   tree lights twinkle and drift through colors; Santa's sleigh crosses the moon every 45–90 s. Gentle snow in
   all four.
3. A scrim (dark gradient) between the scene and the content so every text and chip pair still meets 4.5:1;
   a test checks the scrim's minimum opacity.

Motion stops under `prefers-reduced-motion`, and pauses on `visibilitychange` when hidden. Until Margaret's
drawings exist, each theme ships with a simple placeholder background in the theme's colors, so the motion
work doesn't wait on the art.

### 14.4 Margaret's art pipeline

`docs/themes.md` explains, for Margaret: draw on paper (portrait), photograph in daylight, and either drop the
photo in `art/originals/` and run `ops/prepare-theme <key> <photo>` (crop, resize, convert to WebP with Pillow,
which is `py3-pillow` on Alpine) or ask Claude to help clean it up first. Originals are kept in the repo.

## 15. Later (designed, not in v1): start it on the TV

A **Play on TV** button on a picked movie:

- Streaming: switch the Family Room TV to the service's `tv_source` through Home Assistant
  (`media_player.select_source`), and where a deep link is known, open the movie directly.
- Owned disc: switch to the receiver input and show the shelf ("Blu-ray · Family Room › Media Cabinet › Shelf
  2: go get it!").

This needs an HA long-lived token and a per-service deep-link table, and will be its own spec. v1 only stores
`services.tv_source` so it has what it needs.

## 16. Settings (`/etc/conf.d/wonderful`, documented in `.env.example`)

`PORT`, `DATA_DIR`, `TMDB_READ_TOKEN`, `MATINEE_URL`, `MATINEE_API_KEY`, `HA_HOOK_SECRET`, `HA_WEBHOOK_URL`, `ANTHROPIC_API_KEY`,
`AI_MODEL`, `AI_DAILY_CAP`, `CF_TEAM_DOMAIN`, `CF_AUD`, `ADMIN_EMAILS`, `LAN_EDIT`, `LAN_HOSTS`, `TZ` (dates are
local, America/Los_Angeles on the host). Subscriptions, theme on/off and light/dark live in the database.

## 17. Starting list (41)

From Nick's Duet list plus his additions. Certifications as given; availability is not stored (§7.2).

**Animated and TV specials:** Rudolph the Red-Nosed Reindeer (1964) · A Charlie Brown Christmas (1965) · How
the Grinch Stole Christmas! (1966) · Frosty the Snowman (1969) · Mickey's Christmas Carol (1983) · The Nightmare
Before Christmas (1993) · The Polar Express (2004) · Shrek the Halls (2007) · Prep & Landing (2009) · Disney's A
Christmas Carol (2009) · Arthur Christmas (2011) · The Star (2017) · Olaf's Frozen Adventure (2017) · The Grinch
(2018) · Klaus (2019) · Diary of a Wimpy Kid Christmas: Cabin Fever (2023, parent note: Greg finds his hidden
presents and then gets the same gifts "from Santa").

**Live-action family classics:** It's a Wonderful Life (1946) · Miracle on 34th Street (1947) · White Christmas
(1954) · A Christmas Story (1983) · Home Alone (1990) · Home Alone 2: Lost in New York (1992) · The Muppet
Christmas Carol (1992) · The Santa Clause (1994) · Miracle on 34th Street (1994) · Jingle All the Way (1996) ·
How the Grinch Stole Christmas (2000) · The Santa Clause 2 (2002) · Elf (2003) · The Christmas Chronicles (2018) ·
Noelle (2019) · Jingle Jangle: A Christmas Journey (2020) · The Christmas Chronicles: Part Two (2020).

**Newer:** Scrooge: A Christmas Carol (2022) · That Christmas (2024) · The Best Christmas Pageant Ever (2024) · A
Loud House Christmas Movie: Naughty or Nice (2025).

**Nick's additions:** Prancer (1989) · 8-Bit Christmas (2021) · Four Christmases (2008, PG-13) · Christmas with
the Kranks (2004).

The seed task resolves each to a TMDB id and type; any that resolve only as TV (the specials are the likely
ones) get `tmdb_type = 'tv'`, and the task reports which.

## 18. Build order (for the issue queue)

Each step is shippable and becomes one or more small "Prompt:" issues. Issues marked **(M)** are ones Margaret
can run herself: a visible change she can check on her phone.

1. Skeleton: Flask app, schema v1 + `migrate()`, auth (§5), CI, installer, OpenRC service, deploy, smoke test.
2. The list: TMDB add flow, posters, grid, detail view, seed of 41, parent note. **(M: the grid with posters)**
3. Where to watch: providers, services table and settings, Matinee ownership. **(M: subscriptions screen)**
4. Search: local filter, exact-title shortcut. **(M)**
5. Randomizer with filters, three picks and Pick Again, and the button text. **(M)**
6. People (sync from Matinee) and per-person ratings, family average. **(M: the rating screen)**
7. Matinee sync: rating push and conflict notice. Watch push. HA movie log (§8.5).
8. Viewings and Continue Watching with manual "We finished". **(M)**
9. HA webhook and the finish guess; `docs/home-assistant.md`.
10. AI search with suggestions and Add to our list. **(M: try her own searches)**
11. Themes: calendar, placeholders, motion, scrim, preview. **(M: motion tuning)**
12. Margaret's art: pipeline and her four drawings. **(M)**
13. Worth a Month?
14. (Later, own spec) Play on TV.

Target: steps 1–8 live before Advent 2 (Dec 6, 2026), the rest during December.

Nick runs the deploys with Margaret (decision 22). Each **(M)** issue ends with a short "Try it" note for her:
what to open on the phone after the deploy, and what she should see.

## 19. Testing

No live network. Fixtures: TMDB details, release dates, credits, watch providers and search for at least *Elf*
(10719), *Klaus*, *Home Alone*, *The Star*, *White Christmas* (NR) and one TV-only special; Matinee responses
for owned (*Elf*, Blu-ray with a location), not owned, rating 400, people; Anthropic responses for a match, a
suggestion, malformed JSON and HTTP 529. Unit tests for `theme_for`, the rounding rule, the finish guess, each
randomizer filter, and the conflict states. Playwright at 412 px: grid columns, no horizontal scroll, rating
buttons ≥ 44 px, scrim contrast, reduced motion stops animation.

## 20. Left to the builder

- Port number, hostname and whether it shares Matinee's container.
- Module split inside the Flask app (follow Matinee's `app.py` + route-free siblings).
- Exact provider-id → service mapping (TMDB names such as "Max" vs "HBO Max" change; keep it data-driven).
- The AI prompt wording and model default (a current Haiku-class model is plenty).
- Placeholder theme art and the exact motion timings.

## 21. Deferred

- Play on TV (§15).
- Other holidays.
- Per-person "who has seen it" filters in the randomizer (Matinee has `unseen_by`; could follow).
- An MCP server for this app.
- Kid logins.
