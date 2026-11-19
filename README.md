# It's a Wonderful App

A phone-first Christmas movie picker for one family: a curated list with posters, where to watch, search, a
three-pick randomizer ("🎲 Surprise us, ya filthy animals"), Continue Watching driven by the living-room TV,
per-person ratings shared with [Matinee](https://github.com/SDNick484/matinee), and four Advent themes.

It is built the same way as Matinee: Flask + SQLite, a vanilla-JS single-page app of native ES modules, and a
self-extracting installer for an Alpine Linux container with OpenRC. The design is
[`docs/superpowers/specs/2026-11-18-its-a-wonderful-app-design.md`](docs/superpowers/specs/2026-11-18-its-a-wonderful-app-design.md)
and the build plan is [`docs/superpowers/plans/2026-11-18-its-a-wonderful-app.md`](docs/superpowers/plans/2026-11-18-its-a-wonderful-app.md).

## What works today

- The app skeleton: the page, `GET /api/health` → `{"ok": true, "schema": "1"}`, and the whole database
  schema (v1).
- **The list.** The **+** button opens a sheet: search TMDB by title, tap **Add to our list**, and the grid gains
  the poster (3 columns on every phone). A movie or a TV-only special adds the same way; one already on the list
  says "On our list". Tap a poster for the detail view: backdrop, overview, runtime, certification (US, `NR` when
  TMDB has none; change it by hand and refreshes keep your choice), top cast, collection, an editable note for
  parents, and **Remove from our list** (asks first; its ratings and viewings go with it). Posters are downloaded
  once to `$DATA_DIR/posters/`; a missing poster shows a titled placeholder. Adding needs `TMDB_READ_TOKEN`.
  API: `GET /api/tmdb/search?q=`, `GET`/`POST /api/movies`, `GET`/`PUT`/`DELETE /api/movies/<id>`.
- **Search.** The box above the grid filters the list as you type, by title, year, actor or collection (no network).
  Enter shows an exact title on its own (`elf` → *Elf*; "The" and punctuation don't count), otherwise the matches.
  API: `GET /api/search?q=` → `{"mode", "matches": [{"id", "why"}], "suggestions"}`.
- **Surprise us.** **🎲 Surprise us, ya filthy animals**, above the grid, draws three different movies from the list
  with a poster, runtime and where to watch on each; tap one for its detail view. **Keep the change (pick again)**
  draws three more, skipping what was shown, until the list runs out and then says it is starting over. Six chips
  narrow the draw, all off to begin with (the whole list) and remembered on that phone: **Animated** / **Live
  action** (one or the other), a rating cap that cycles **Up to G**, **Up to PG**, **Up to PG-13** (a title with no US
  rating, `NR`, counts as PG, so *Up to G* leaves it out), **Under 90 min** (a title with no runtime fails it),
  **Not watched this year** (a finished viewing or a Matinee watch in the calendar year on the host's `TZ`; a
  January 2 watch counts for the new year) and **Ready to watch** (owned, on a service you subscribe to, or free).
  With fewer than three matches it says "Only 2 match. Try turning off a filter."
  API: `POST /api/surprise` `{"filters": {...}, "exclude": [ids]}` → `{"picks": [ids], "pool_size", "restarted"}`.
- **Where to watch.** Every card carries one line (green when it is ready to watch tonight) and the detail view lists
  them all, best first: on a service you subscribe to ("On Netflix"), free ("Free with ads on The Roku Channel"; free
  counts as ready), on a service you are only considering ("On Peacock (you don't have it)"), then "Rent or buy".
  The data is TMDB's US watch providers (JustWatch), saved when a movie is added and refreshed when older than 7
  days or with **Check again** on the detail view. A provider the app has never heard of shows under its own name.
  A title with no US providers reads "Rent or buy". The seed script also fetches them.
- **Owned, and where it sits.** The app asks [Matinee](https://github.com/SDNick484/matinee) (`MATINEE_URL` and
  `MATINEE_API_KEY`) whether each movie is in the collection. An owned movie leads its where-to-watch lines with the
  copies and the shelf: "Blu-ray · Family Room › Media Cabinet › Shelf 2" (a title Matinee lacks, or holds with no
  copy, is not owned). Matinee is asked when a movie is added, when you open its detail view and the last answer is
  over a day old, and every night. If Matinee is down, slow or refuses the key, nothing else breaks: the last known
  answer stays and reads "(as of Dec 3)", and the nightly refresh tries again. TV-only specials are never asked
  (Matinee knows movies only). With no `MATINEE_API_KEY` the whole sync is off.
- **People and ratings.** **Settings → People** lists the family: they are copied from Matinee by name (kind, colour
  and order too) the first time the app needs them, and again with **Sync people from Matinee**; **Add someone** adds
  a person who lives only here (a visitor), who rates like everyone else and is not sent to Matinee. On a movie's
  detail view, **Rate it** opens a sheet with one row per person: number buttons **1** to **10** and a **½** (8, then
  ½, is 8.5; tap the same value again to clear it; anyone can be left unrated), then **Done**. Ratings are 0 to 10 in
  half steps (7.3 or 11 is refused). The family rating is the mean to one decimal (8, 9, 10, 8, 8 is **8.6**); it shows
  as **★ 8.6** on the poster and as a row of coloured dots with each person's rating on the detail view. Clear the last
  rating and the family rating goes away. While Matinee holds the rating of a movie it owns and nobody has rated here,
  the poster shows Matinee's rating ("family rating from Matinee"). Rating never needs Matinee. Sending the rating to
  Matinee arrives with the rating-sync task.
  API: `GET`/`POST /api/people` (`{"name", "kind": "adult" | "kid", "color"}`), `POST /api/people/sync`,
  `PUT /api/movies/<id>/ratings/<person_id>` (`{"rating": 8.5}` or `null` to clear).
- **Settings → Subscriptions** (the gear in the header). Each streaming service is **Subscribed**, **Considering** or
  **Ignore**, and every card follows at once. Starting statuses: Netflix, Disney+, Hulu, Prime Video, Fandango at
  Home and YouTube TV subscribed; HBO Max, Peacock, Paramount+ and Apple TV considering. The list, each service's
  TMDB provider ids and the TV input name it uses (`tv_source`, for the Family Room TV) live in
  `data/services.json`; the database keeps your statuses, and a restart picks up edits to the rest.
  API: `GET`/`PUT /api/services` (`{"key": "peacock", "status": "subscribed"}`),
  `POST /api/movies/<id>/providers/refresh`.
- **The starting list.** `data/seed-movies.json` holds the 41 titles from spec §17, with their parent notes and
  certifications but no TMDB ids yet. `ops/seed-movies` adds the ones that have an id and skips the rest; see
  [The starting list](#the-starting-list).
- Sign-in rules (below), the Home Assistant TV hook's secret check (`POST /hooks/tv`; the hook changes nothing
  yet), the installer, the OpenRC service and the nightly backup.

## Who can open it

There is no public view. Every page and API call needs one of:

- **A direct LAN request** (`LAN_EDIT=1`): the browser addresses the app by IP address
  (`http://192.168.1.100:8772/`), `localhost`, or a name listed in `LAN_HOSTS`, and the request does not come
  through Cloudflare. Any other host name is refused, so a DNS-rebinding page can't borrow the LAN.
- **Cloudflare Access**: through the tunnel (`https://wonderful.example.com`), a valid Access token for the app's
  `CF_AUD`, from an email in `ADMIN_EMAILS` (empty = anyone the Access policy lets in).
- **A key** for scripts: `Authorization: Bearer <WONDERFUL_API_KEY>` (or `X-API-Key`).

A browser request from another site (`Origin` or `Sec-Fetch-Site: cross-site`) is refused even on the LAN.
`POST /hooks/tv` needs the `X-Hook-Secret: <HA_HOOK_SECRET>` header instead; with no secret set it answers 403.
Static files (CSS, scripts, fonts) need no sign-in; they hold no data.

**How the family's phones reach it on the LAN:** to be recorded after the first deploy (spec §5 caveat: opened by
hostname, the phone may go through Cloudflare and need an Access session or a `LAN_HOSTS` name).

## Install (Alpine LXC)

```sh
sh installer/build.sh                 # on a dev machine: makes dist/setup-wonderful.sh
scp dist/setup-wonderful.sh root@192.168.1.100:
sh setup-wonderful.sh                 # on the container, as root; re-run it to upgrade
```

The installer adds `python3 py3-flask py3-gunicorn py3-pillow py3-jwt py3-cryptography sqlite tzdata` with `apk`,
creates the `wonderful` user, unpacks the app to `/opt/wonderful`, keeps data in `/var/lib/wonderful`
(`wonderful.db`, `posters/`, `art/`), writes any missing setting to `/etc/conf.d/wonderful` without touching the
ones already there, generates `HA_HOOK_SECRET`, adds the OpenRC service `wonderful` (gunicorn on port 8772 by
default; `WONDERFUL_PORT=<port> sh setup-wonderful.sh` for another) and installs the nightly backup and refresh.

```sh
rc-service wonderful restart          # after editing /etc/conf.d/wonderful (vim /etc/conf.d/wonderful)
tail -f /var/log/wonderful.log
sh setup-wonderful.sh --uninstall     # removes the app, service and nightly jobs; keeps data, config and backups
```

### Nightly refresh

`/etc/periodic/daily/wonderful-refresh` (a two-line wrapper the installer writes around `ops/wonderful-refresh`) runs
every night as root and appends to `/var/log/ops.log`. It re-reads TMDB's watch providers for every movie whose
cache is over 7 days old, and asks Matinee about every movie never checked or last checked over a day ago. If TMDB
has no token, or Matinee is down or refuses the key, that part stops at the first failure and the rest wait for
tomorrow. Run it by hand with `/opt/wonderful/ops/wonderful-refresh` (`--dry-run` says what it would ask).

### Backups

`/etc/periodic/daily/wonderful-backup` (from `ops/wonderful-backup`) writes
`/var/backups/wonderful/<date>/wonderful.db.gz` with `sqlite3 .backup` (safe while the app runs), plus
`wonderful-posters.tar.gz` and `wonderful-art.tar.gz`, each written under a temporary name and renamed when
complete. It keeps 14 days. If `/etc/conf.d/ops` sets `BACKUP_TARGET`, it also copies the day's files there.
To restore: `rc-service wonderful stop`, `gunzip -c wonderful.db.gz > /var/lib/wonderful/wonderful.db`, untar
the folders into `/var/lib/wonderful`, `chown -R wonderful:wonderful /var/lib/wonderful`, `rc-service wonderful start`.

## The starting list

The installer runs `ops/seed-movies` once on a fresh install. It adds nothing until `TMDB_READ_TOKEN` is set,
so after setting the token, run it once as root:

```sh
/opt/wonderful/ops/seed-movies --resolve      # look up each title (same title and year, movies before TV), write the ids back, add
/opt/wonderful/ops/seed-movies                # later: add any entry with an id that is not on the list yet (idempotent)
/opt/wonderful/ops/seed-movies --dry-run      # say what would be added; no TMDB call, no write
```

It prints `added N, skipped M`. `--resolve` writes the ids back into the seed file it read: on the host that is the
installed copy under `/opt/wonderful/data/`, so copy the result back to the repo's `data/seed-movies.json` and commit it. The certifications in the file are a hint: TMDB's value is kept,
and a difference is printed. The script hands the data folder back to the service user, so the service keeps
working after a root run.

## Settings

All in `/etc/conf.d/wonderful` on the host; every one is documented in [`.env.example`](.env.example).

| Setting | What it does |
|---|---|
| `PORT` | Port the app listens on (default 8772; Matinee uses 8771) |
| `DATA_DIR` | Where `wonderful.db`, `posters/` and `art/` live |
| `TZ` | Time zone for local dates (Advent themes, "this year"); never UTC on the host |
| `CF_TEAM_DOMAIN`, `CF_AUD` | Cloudflare Access team domain and the app's AUD tag |
| `ADMIN_EMAILS` | Access emails allowed in; empty = anyone Access admits |
| `LAN_EDIT`, `LAN_HOSTS` | Direct LAN access on/off, and extra LAN host names |
| `WONDERFUL_API_KEY` | Optional key for scripts |
| `HA_HOOK_SECRET` | Secret Home Assistant sends to `/hooks/tv` |
| `HA_WEBHOOK_URL` | Home Assistant webhook for the movie log (a secret) |
| `TMDB_READ_TOKEN` | TMDB read token: posters, details, where to watch |
| `MATINEE_URL`, `MATINEE_API_KEY` | Matinee's address and key: ownership, ratings and watches |
| `ANTHROPIC_API_KEY`, `AI_MODEL`, `AI_DAILY_CAP` | Smart search |

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium     # for the UI smoke test
cp .env.example .env                                # then set DATA_DIR=./data and whatever keys you have
.venv/bin/python app.py                             # http://localhost:8772/
sh scripts/gate.sh                                  # everything CI checks
```

Runtime dependencies are Alpine `py3-*` packages only; `requirements-dev.txt` is for tests and lint. Rules for
contributors and agents are in [`CLAUDE.md`](CLAUDE.md).

## Credits

This product uses the TMDB API but is not endorsed or certified by TMDB. Where-to-watch data comes from
JustWatch through TMDB. Figtree is under the SIL Open Font License (`static/fonts/OFL-Figtree.txt`).
