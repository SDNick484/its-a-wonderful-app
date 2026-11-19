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
default; `WONDERFUL_PORT=<port> sh setup-wonderful.sh` for another) and installs the nightly backup.

```sh
rc-service wonderful restart          # after editing /etc/conf.d/wonderful (vim /etc/conf.d/wonderful)
tail -f /var/log/wonderful.log
sh setup-wonderful.sh --uninstall     # removes the app and service; keeps data, config and backups
```

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
