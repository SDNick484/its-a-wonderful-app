# Play on the Family Room TV: design

**Date:** 2026-11-26
**Repo:** `SDNick484/its-a-wonderful-app`, `main` @ `e4742cf` (schema v1)
**Size:** a project: one new setting, two new routes (and a change to `/hooks/tv`), UI on two screens, a Home Assistant script, and schema v2 (two columns)
**Status:** Approved by Nick on 2026-11-26
**Replaces:** the sketch in the first design's §15 ("Later: start it on the TV")

---

## 1. Intent

Picking a movie on the phone should also get the Family Room TV (LG 77G1) ready for it: the TV on, on the right
streaming app, or set up for the disc with the shelf shown. Today the family picks in the app and then does the
same thing again with the remote.

### Goals

1. On a movie's page, show each way we can play it: **Start the disc** with where the disc is (from Matinee), and
   **Stream it** with the service. Each button starts that on the TV.
2. On the main page, a **Play** button on Continue Watching and on the three Surprise picks that starts the movie
   with no further choice, streaming first.
3. The phone says what happened: the TV got there, or it didn't answer.
4. A tap also puts the movie on for tonight, so the TV's on/off events count toward "Did you finish?" (first
   design §10) with nothing else to tap.

### Non-goals

- Opening the exact movie inside a streaming app (a deep link). Phase 1 opens the app; the family picks the movie
  with the remote. See §9.
- Any TV but the Family Room one.
- Volume, pause, or any playback control.
- Playing video in the app.
- The app configuring Home Assistant by itself. The Home Assistant side is set up once, by hand or by Claude with
  Nick's go-ahead (§7).

### Anti-goals (fails even if it technically works)

- The TV turns on from a stray thumb while scrolling the grid.
- Play starts something we'd have to pay for, or a service we don't have.
- A tap that does nothing visible: no message, no TV.
- The Home Assistant webhook URL shows up in a log, an API answer or the page.
- A Home Assistant outage breaks anything that works today (the list, ratings, Watch tonight).

## 2. Decisions from brainstorming (2026-11-26)

"Nick" means he said it. "Claude's call" means Claude proposed it and Nick did not object when it was played back;
these are the ones to check while reading.

| # | Decision | Choice | Whose |
|---|---|---|---|
| 1 | Movie page | Both options when both apply: **Start the disc** (with Matinee's copy and shelf) and **Stream it** | Nick |
| 2 | Main page | Play starts straight away, no choice shown | Nick |
| 3 | Main page, movie both owned and streamable | Stream it | Nick |
| 4 | Disc activity | The Sofabaton's "Watch a Bluray" (`switch.watch_a_bluray`) | Nick |
| 4a | Streaming and the Sofabaton | Streaming always puts the Sofabaton in "Watch TV" (`switch.watch_tv`) before the app opens, so the physical remote works too. Selecting the app on the TV alone is not enough | Nick |
| 4b | Owned only as a digital copy | It gets a Play button that opens Fandango at Home | Nick |
| 5 | Where main-page Play sits | Continue Watching and the Surprise picks only; the big grid stays tap-to-open (mockup A) | Claude's call (Nick: "looks great") |
| 6 | A tap also marks **Watch tonight** | Yes | Claude's call |
| 7 | Two subscribed services have it | The first in the Subscriptions order (`services` rowid order) | Claude's call |
| 8 | Main page, disc only | Play starts the disc and shows the shelf | Claude's call |
| 9 | Main page, rent or buy only | No Play button | Claude's call |
| 10 | Feedback | "Opening Disney+ on the Family Room TV…", then confirmed from the TV's own events, or "The TV didn't answer" after 90 seconds | Claude's call |
| 11 | How the app reaches Home Assistant | A second Home Assistant webhook (like `HA_WEBHOOK_URL`), not a long-lived token: the app can do this one thing in Home Assistant and nothing else | Claude's call |
| 12 | Who may press Play | Any signed-in editor, on the LAN or through Cloudflare. No extra confirm | Claude's call |
| 13 | Free services | A free or free-with-ads service counts for streaming only when it is in `data/services.json` with a `tv_source` and not set to Ignore, and only after subscribed ones | Claude's call |
| 14 | Movie page, several services | One stream row per launchable service, subscribed first, each with its own button | Claude's call |
| 15 | Order for main-page Play | Our digital copy, then subscribed services, then free (with ads) services, then the disc | Nick |
| 16 | Which discs get **Start the disc** | Any physical copy, whatever its format | Nick |

## 3. What Home Assistant has (looked up 2026-11-26)

- The TV is `media_player.77g1` (the webOS integration). Its `source_list` holds every `tv_source` in
  `data/services.json` spelled the same way (Netflix, Disney+, Hulu, Prime Video, Fandango at Home, YouTube TV, HBO
  Max, Peacock, Paramount+) and `AV Receiver`. The same TV also has a Cast entity and a Music Assistant entity;
  those report other sources and must not be used.
- The Sofabaton activities are switches: `switch.watch_tv` and `switch.watch_a_bluray`.
- `script.family_room_youtube_tv` already does the streaming sequence for one app: turn on `switch.watch_tv` if it
  is off, wait up to 60 s for `media_player.77g1` to be `on`, wait 5 s more for webOS, then
  `media_player.select_source`.
- No automation posts the TV's events to `/hooks/tv` yet (first design §10.2, `docs/home-assistant.md`). Feedback
  (decision 10) and "Did you finish?" both need it, so setting it up is part of this project (§7).

## 4. Constraints

Everything in `CLAUDE.md` applies. The ones that shape this:

- **Settings** (rule 7): the new setting goes in `.env.example`, `settings.py`, the installer's `add_setting` list
  and the init script's `export` line.
- **Tests** (rule 3): no live network; the Home Assistant call gets a miss test and an HTTP-error test.
- **Auth** (rule 5): the new routes are `@editor_required`.
- **Phone-first** (rule 6): Play buttons are at least 44 px, nothing scrolls sideways at 412 or 360 px, and each UI
  change gets a Playwright check. Mind the two memories of earlier bugs: wire a view's listeners once, and test a
  view on its second visit.
- **Hygiene** (rule 10): `docs/home-assistant.md` and tests use placeholder names (`media_player.family_room_tv`,
  `ha.example.com`). The real entity names above stay in this exempt folder.
- **Schema** (rule 2): v2, through `db.migrate()` from v1. `matinee_sync` gains two columns saying whether Matinee
  holds a physical copy and whether it holds a digital copy (§5.1). The TV's last state goes in `meta`.

## 5. Behaviour

### 5.1 What can play (one rule, used everywhere)

For a movie, from the cache only (no TMDB or Matinee call):

- **Stream options**, in order (decision 15): our digital copy (below); then every service that has the movie in
  TMDB's `flatrate` tier, is **Subscribed**, and has a `tv_source`, in Subscriptions order; then every known service with the movie in `free` or `ads`, not set
  to Ignore, with a `tv_source`. A service appears once. A provider the app doesn't know, a service with no
  `tv_source` (Apple TV today), and anything rent-or-buy are never stream options.
- **Our digital copy** (decision 4b): when Matinee holds a digital copy, Fandango at Home is a stream option,
  marked `"owned": true`, whatever its Subscriptions status and whether or not TMDB lists the movie there. It
  is the first stream option (decision 15). If Fandango at Home is already a
  stream option for the movie it appears once, as the owned one. The service is the one with key
  `fandango_at_home`; Matinee's own `service` text for the copy is not consulted.
- **Disc option**: when Matinee holds any physical copy (decision 16), with the "owned" where-to-watch line's label ("Blu-ray · Family Room › Media Cabinet › Shelf
  2", and "(as of Dec 3)" when stale). A digital-only movie has no disc option.
- **Auto** (main-page Play): the first stream option; else the disc; else nothing.

Matinee's `owned` answer lists `copies`, each with a `kind` (`physical` or `digital`) and a `format`. Today the app
keeps only the summary text and the first shelf. It now also keeps the two facts above in `matinee_sync`, written
at every ownership check. A row checked before the upgrade has them empty until its next check (the nightly
refresh, within a day); until then they are read from the summary text, whose parts are Matinee's format names
(a part starting "Digital" is a digital copy). The TV hook's `sources_for` follows the same facts: `AV Receiver`
counts only with a physical copy, and `Fandango at Home` counts with a digital copy.

When `HA_PLAY_WEBHOOK_URL` is empty the feature is off: no options, no buttons, and the play route answers 503
with a plain sentence.

Each movie in the API (`GET /api/movies`, `GET /api/movies/<id>`) gains:

```json
"play": {"stream": [{"service": "disney_plus", "name": "Disney+", "owned": false}],
         "disc": {"label": "Blu-ray · Family Room › Media Cabinet › Shelf 2"},
         "auto": "stream"}
```

`stream` is `[]`, `disc` is `null` and `auto` is `null` when they don't apply; `play` is `null` when the feature
is off.

### 5.2 Pressing a button

`POST /api/movies/<id>/play` with `{"mode": "auto" | "stream" | "disc", "service": "disney_plus"}` (`service` only
with `stream`, optional: the first stream option when left out).

1. Work out the target from §5.1. A mode the movie can't do is a 409 with a sentence ("*Scrooged* isn't on a
   service we have."); a bad body is a 400; an unknown movie a 404.
2. Mark the movie for tonight exactly as **Watch tonight** / **Keep watching tonight** does (`viewings`), so the
   one-movie-tonight rules of the first design §10.1 hold.
3. Post to Home Assistant and wait for its answer (5 s timeout). This is not fire-and-forget like the movie log:
   the phone needs to know.
4. If the TV is already on the target input (§5.3's remembered state: on, same source, case ignored), open the
   night's session now, because no TV event will come to open it.
5. Answer `{"ok": true, "mode": "stream", "source": "Disney+", "name": "Disney+", "label": null, "viewing": {…},
   "tv": {…}}`. For a disc, `source` is `AV Receiver`, `name` is `null` and `label` is the shelf line.

If Home Assistant can't be reached, is slow, or answers an error: 502 with "Couldn't reach the TV. *Home Alone* is
on for tonight; use the remote." Step 2 stays done (the family is still watching it), nothing else changes, and the
log gets one warning that names the host and the kind of failure, never the URL (the rule `ha.py` already follows
for `HA_WEBHOOK_URL`).

The payload to Home Assistant:

```json
{"event": "wonderful_play", "mode": "stream", "source": "Disney+", "title": "Home Alone"}
```

`mode` is `stream` or `disc`; `source` is the `tv_source`, or `AV Receiver` for a disc.

### 5.3 Knowing where the TV is

`/hooks/tv` today remembers only the time of the last event. It now also remembers the last event's `state` and
`source` in `meta`, for every in-order event, whether or not a movie is on for tonight.

`GET /api/tv` → `{"state": "on", "source": "Disney+", "at": "2026-12-12T19:31:04-08:00"}`, or all `null` when no
event has ever arrived.

After a successful play the page polls `GET /api/tv` every 3 seconds, for up to 90 seconds:

- **Confirmed** when an event at or after the tap shows the TV on and on the target source, or straight away when
  step 4 above found it already there: "Disney+ is open on the Family Room TV." For a disc: "The TV is ready.
  Blu-ray · Family Room › Media Cabinet › Shelf 2: go get it!"
- **Not confirmed** after 90 seconds: "The TV didn't answer. Try the remote."
- **Never heard from the TV** (`at` is `null`, so the events automation isn't set up): skip the polling and say
  "Sent to the TV." so the feature still works without it.

The shelf line for a disc shows as soon as the play call answers; it doesn't wait for the TV.

### 5.4 The movie's page

A **Play on the Family Room TV** section above "Where to watch", shown when the movie has any option:

- A disc box when owned: the shelf line and **Start the disc**.
- A stream box per stream option: "On Disney+" and **Stream it**. With more than one, the button reads
  **Stream it on Disney+**. Our digital copy's box reads "Our digital copy · Fandango at Home".

The existing **Watch tonight** button stays, for nights the TV is already going or the movie has no option.
A button is disabled from the tap until the answer, so a double tap sends once. The status line of §5.3 shows
under the section.

### 5.5 The main page

- **Continue Watching:** each movie in the row with an `auto` option gets a **▶ Play** button. On a paused movie it
  is also **Keep watching tonight**.
- **Surprise picks:** each of the three picks with an `auto` option gets a ▶ button on its card (44 px, with an
  accessible name like "Play Home Alone on the TV"). Tapping the rest of the card still opens the movie's page.
- **The big grid:** no Play. Posters open the movie's page, as now.

Main-page Play sends `mode: "auto"`. Its messages show as a toast: "Opening Disney+ on the Family Room TV…", then
§5.3's result. For a disc the toast carries the shelf line and stays until dismissed, since someone has to read it
and walk to the shelf.

## 6. Settings

| Setting | What it does |
|---|---|
| `HA_PLAY_WEBHOOK_URL` | Home Assistant webhook that starts something on the Family Room TV, e.g. `http://ha.example.com:8123/api/webhook/<id>`. A secret: the id is the only credential. Empty = Play on TV is off |

It is treated like `HA_WEBHOOK_URL`: never logged, never returned by a route, never in a payload.

## 7. The Home Assistant side

Documented in `docs/home-assistant.md` with placeholder names, and set up once on Nick's Home Assistant.

1. **A script, "Play on the Family Room TV"**, with two fields, `mode` and `source`:
   - `stream`: the sequence of `script.family_room_youtube_tv` with `source` in place of "YouTube TV". The first
     step is required, not an optimisation (decision 4a): unless `switch.watch_tv` is already on, turn it on,
     including when the TV is already on under another activity (Watch a Bluray) or was turned on some other way.
     Only then select the source.
   - `disc`: turn on `switch.watch_a_bluray` if it is off. The activity is trusted to put the TV on `AV Receiver`;
     the hardware pass checks it (§10).
   - `mode: restart`, so a second pick replaces the first instead of queueing behind a 60-second wait.
2. **An automation** triggered by a webhook (`local_only: true`, `POST` only, a long random id) that checks
   `event == "wonderful_play"` and runs the script with `trigger.json.mode` and `trigger.json.source`. `source` is
   only ever passed to `media_player.select_source` on the one TV, so the worst a leaked id can do is change that
   TV's app.
3. **The TV events automation and `rest_command`** already written up in `docs/home-assistant.md`, pointed at the
   webOS entity. The doc gains a line saying to pick the webOS entity when the TV has several.

Claude can create the script and the two automations through the Home Assistant tools once Nick approves this
design, and will not touch Home Assistant before then. The `rest_command` and its secret go in
`configuration.yaml` and `secrets.yaml`, which Nick edits (`vim /config/configuration.yaml`) and then restarts
Home Assistant.

## 8. Failure cases reviewers check first

1. Home Assistant down, slow (over 5 s), answering 404 or 500: the play route is a 502 with the sentence above,
   the viewing is still on for tonight, and the URL is not in the log. (Believed, not checked: Home Assistant
   answers 200 to a webhook id it doesn't know, so a mistyped URL looks like success and ends in "The TV didn't
   answer". The setup doc says to check the first play in the automation's Traces.)
2. `HA_PLAY_WEBHOOK_URL` empty: `play` is `null` on every movie, no buttons render, the route is a 503, and every
   existing test still passes untouched. `tests/conftest.py` blanks the new setting as it does `HA_WEBHOOK_URL`,
   so a developer's `.env` can't turn the feature on in tests.
3. A movie that is `flatrate` only on a service set to **Considering** or **Ignore**, on an unknown provider, or
   rent-only: no stream option, and `mode: "stream"` is a 409. (Free or free-with-ads on a known service that is
   not Ignore is a stream option whatever its status, §5.1: free costs nothing.)
4. Owned and streamable: `auto` is `stream` (decision 3). Owned only as a digital copy: one stream option,
   Fandango at Home, no disc option, and the TV hook opens a session on `Fandango at Home`, not `AV Receiver`.
   Digital copy and also on Netflix: `auto` opens Fandango at Home. A v1 database migrates and gives the same answers before and
   after its first ownership check.
5. The TV is already on the target app when Play is tapped: confirmed at once and a session opens.
6. A TV event older than the tap (the TV was on Netflix all evening, Play asks for Disney+): not a confirmation.
7. Two taps: one request while the first is pending; a second play of another movie follows the
   one-movie-tonight rules.
8. The Play button on a Surprise card doesn't also open the movie's page, and still works on the second visit to
   the main page.

## 9. Later

- **Open the exact movie.** Needs a per-movie, per-service id (TMDB doesn't supply one) and a launch format per
  webOS app. Worth a spike on the TV, Netflix first, before any design.
- A small "TV: on Disney+" line on the main page from `GET /api/tv`, so a broken automation is visible.
- Limiting Play to the LAN, if turning the TV on from away from home turns out to be a nuisance.

## 10. Left to the builder

- How to split this into plan tasks. A natural order: remember the TV's state and `GET /api/tv`; the play rule,
  setting and route; the movie page; the main page; the Home Assistant doc and setup. The UI tasks are **(M)**
  and end with a "Try it" note.
- Module layout (the outbound call belongs with `ha.py`; the option rule near `providers.py`), names of meta keys,
  CSS, exact wording of error sentences not quoted here.
- Whether the page polls with a timer or backs off; 3 s and 90 s are the intent, not a contract.
- The hardware pass after deploy: each of the nine services with a `tv_source` opens from a cold TV and from a TV already on (YouTube TV has no
  TMDB provider ids, so it is tried by posting to the webhook by hand); the
  disc activity leaves the TV on `AV Receiver`; a play while the other activity is running switches cleanly; and
  after every stream the Sofabaton is in Watch TV and the physical remote drives the app.
- `README.md` gains a "Play on the Family Room TV" entry and the new setting (rule 12).
