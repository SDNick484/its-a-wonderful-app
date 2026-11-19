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
  Enter shows an exact title on its own (`elf` → *Elf*; "The" and punctuation don't count). Anything else is **smart
  search** when `ANTHROPIC_API_KEY` is set: one call to the model asks which movies on our list fit ("a movie about
  Jesus", "a musical") and shows them with a one-line reason, then a **Not on our list yet** section of up to three
  titles the list doesn't have, each with **Add to our list**. Nothing is added until someone taps that button.
  The query and the list (titles, cast, overviews and parent notes) go to Anthropic; nothing about people or
  ratings does. Answers are cached until the list changes, and `AI_DAILY_CAP` limits calls a day. With no key, a
  spent cap or a failed call, Enter shows the plain list filter and says "Smart search is off right now."
  API: `GET /api/search?q=` → `{"mode": "exact" | "ai" | "local", "matches": [{"id", "why"}], "suggestions":
  [{"title", "year", "why", "tmdb_id", "tmdb_type"}], "notice"}`; a suggestion is added with `POST /api/movies`.
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
  the poster shows Matinee's rating ("family rating from Matinee"). Rating never needs Matinee.
- **The family rating in Matinee.** The first rating here takes a movie's rating over from Matinee. From then on, for
  a movie Matinee owns, every change sends Matinee the family mean rounded to the nearest half, ties up (8.9 → **9.0**,
  8.6 → **8.5**, 8.75 → **9.0**); Matinee never gets an empty rating, so clearing every rating sends nothing. A movie
  Matinee doesn't own keeps its ratings here; if it is bought later, the next ownership check sends the rating when
  Matinee has none. The app never writes over a rating someone changed in Matinee: before sending it reads Matinee,
  and each ownership check compares, and when they differ the detail view shows **Matinee says 9, we say 8.6** with
  **Use ours** (send ours), **Use Matinee's** (Matinee's rating shows and leads again until someone rates here) and
  **Dismiss** (leave both; the next change here is sent). If Matinee is down, slow or refuses the key, the rating still
  saves, the detail view says **Not sent to Matinee yet**, and the nightly refresh sends it.
  API: `GET`/`POST /api/people` (`{"name", "kind": "adult" | "kid", "color"}`), `POST /api/people/sync`,
  `PUT /api/movies/<id>/ratings/<person_id>` (`{"rating": 8.5}` or `null` to clear),
  `POST /api/movies/<id>/rating-conflict` (`{"choice": "ours" | "matinee" | "dismiss"}`).
- **Continue Watching.** **Watch tonight** on a movie's detail view puts it in the **Continue Watching** row above the
  grid (the row only shows when something is in it), with everyone in the family as its audience. Only one movie is
  ever on for tonight: picking another moves the first back to the row, or drops it if nobody watched any of it, and
  so does 4 am local the next morning. Tap a movie in the row for **Keep watching tonight** (when it is paused), **We
  finished**, its details, or **We gave up on it** (off the row, nothing sent anywhere). A paused movie says how far
  along it is: **Just started** (under 25 %), **About halfway** (25 to 75 %) or **Almost done**. When the TV stopped
  a movie, the next open asks **Did you finish *Home Alone*?** with **Yes**, **Not yet** and
  "We gave up on it": the app's guess is highlighted but still needs a tap. After **We finished** or **Yes**: "Want to
  rate it?" (**Rate** opens the rating sheet with the people who watched first; **Skip**).
- **Finishing tells Matinee and Home Assistant.** A finished movie Matinee owns is logged there once as a watch, dated
  the day it finished (the last TV night, or today), with the people who watched and whom Matinee knows (a visitor is
  left out); the app never asks Matinee to tell Home Assistant. Every finished movie, owned or not, is posted once to
  `HA_WEBHOOK_URL`, Matinee's Family Room movie log webhook, in Matinee's own shape (`"event":
  "matinee_watch_logged"`) plus `"source": "wonderful"`, with `formats` and `location` from Matinee for an owned movie
  (`[]` and `null` otherwise) and `title_id` always `null`. Home Assistant failing is a warning in the log (naming the
  host only, never the webhook URL). If Matinee is down, slow or refuses the key, the movie is finished all the same,
  the watch is owed, and the nightly refresh sends it (Home Assistant is not told twice). A finished movie counts for
  **Not watched this year**.
  API: `POST /api/movies/<id>/tonight` (`{"people": [ids]}` optional), `GET /api/continue`, `GET /api/prompt`,
  `POST /api/viewings/<id>/keep`, `…/not-yet`, `…/finish` (`{"finished_on": "2026-12-12"}` optional; a second finish
  is a 409), `…/abandon`.
- **Settings → Subscriptions** (the gear in the header). Each streaming service is **Subscribed**, **Considering** or
  **Ignore**, and every card follows at once. Starting statuses: Netflix, Disney+, Hulu, Prime Video, Fandango at
  Home and YouTube TV subscribed; HBO Max, Peacock, Paramount+ and Apple TV considering. The list, each service's
  TMDB provider ids and the TV input name it uses (`tv_source`, for the Family Room TV) live in
  `data/services.json`; the database keeps your statuses, and a restart picks up edits to the rest.
  API: `GET`/`PUT /api/services` (`{"key": "peacock", "status": "subscribed"}`),
  `POST /api/movies/<id>/providers/refresh`.
- **Worth a Month?** For each service you're considering, the movies on our list it would add: not owned in Matinee,
  not on a service you have (or free anywhere), and not watched this year. It is the **Worth a Month?** tab, opened
  from the header link at any time of year, most movies first; a service adding nothing says why. It only reads
  the cache, so it works while TMDB or Matinee is down. API: `GET /api/worth`
  (`{"year", "season", "services": [{"service", "name", "movies", "count", "reason"}]}`).
- **Advent themes.** The app wears a scene for each week of Advent, by the host's local date (`TZ`, never UTC): the
  fireplace from the first Sunday of Advent, the toy store the Sunday after, the Christmas tree the Sunday after that,
  and Santa's sleigh from the fourth Sunday through January 6 (2026: Nov 29, Dec 6, Dec 13, Dec 20 to Jan 6). The
  rest of the year is plain, light or dark. Each scene is a picture behind a dark scrim, so text stays readable
  (at least 4.5:1) even over a pale drawing, plus motion on top: flames that flicker and rising sparks, twinkling window
  lights, tree lights that twinkle and drift through colours, a sleigh that crosses the moon every 45 to 90 seconds, and
  gentle snow in all four. Motion stops under the phone's reduced-motion setting and pauses while the tab is hidden.
  **Settings → Advent themes** turns themes on or off, **Light or dark** picks the plain look (Light, Dark, or System,
  which follows the phone; a theme is always dark), and **Preview themes** shows any scene on that phone until the app
  is closed. Themes on/off and light/dark are saved in the database for the whole household. A theme is a folder,
  `static/themes/<key>/` (`fireplace`, `toystore`, `tree`, `sleigh`), holding `background.webp` (portrait, 1080 × 2340),
  `background-wide.webp` (landscape, 2340 × 1080) and `theme.css` (the tuning, e.g. `--flicker` and `--twinkle`); the
  pictures are flat placeholders until the drawings arrive. To make them from a photo of a drawing, see
  [docs/themes.md](docs/themes.md): `ops/prepare-theme <key> <photo>` writes both files with Pillow.
  API: `GET /api/theme` (`{"theme": "fireplace" | "toystore" | "tree" | "sleigh" | null, "until": "2027-01-06"}`),
  `GET`/`PUT /api/theme/prefs` (`{"enabled": true, "mode": "system"}`).
- **The starting list.** `data/seed-movies.json` holds the 41 titles from spec §17, with their parent notes and
  certifications but no TMDB ids yet. `ops/seed-movies` adds the ones that have an id and skips the rest; see
  [The starting list](#the-starting-list).
- **The Family Room TV.** A Home Assistant automation posts the TV's on/off and input changes to `POST /hooks/tv`
  (`{"state", "source", "at"}` with `X-Hook-Secret: <HA_HOOK_SECRET>`; the YAML is in
  [docs/home-assistant.md](docs/home-assistant.md)). While one movie is on for tonight, the TV turning on to an input
  that can play it (a service TMDB lists it on, by that service's `tv_source`, or `AV Receiver` for a disc Matinee
  says we own) starts counting; the TV turning off, switching to anything else, or running past the runtime + 60
  minutes stops it. Then the movie is paused with a guess: finished at 85 % of the runtime, otherwise not, and no
  guess when the runtime is unknown (the question is still asked, with nothing highlighted). Duplicate, late or
  out-of-order events, "on" twice and "off" with nothing counting change nothing.
- Sign-in rules (below), the Home Assistant TV hook's secret check, the installer, the OpenRC service and the nightly
  backup.

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
cache is over 7 days old, and asks Matinee about every movie never checked or last checked over a day ago, or with a
family rating Matinee hasn't received yet (asking again is what sends it, unless Matinee changed meanwhile). Then it
sends Matinee the watches of movies finished while it was down. If TMDB has no token, or Matinee is down or refuses
the key, that part stops at the first failure and the rest wait for tomorrow. Run it by hand with `/opt/wonderful/ops/wonderful-refresh` (`--dry-run` says what it would ask).

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
| `ANTHROPIC_API_KEY`, `AI_MODEL`, `AI_DAILY_CAP`, `AI_TIMEOUT` | Smart search: the key, the model, searches per day, seconds to wait |

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
