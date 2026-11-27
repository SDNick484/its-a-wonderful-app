# Start the movie itself on Netflix: design

**Date:** 2026-11-26
**Repo:** `SDNick484/its-a-wonderful-app`, `main` @ `7b7f961` (schema v2)
**Size:** a small change: one table, one outside lookup, one optional field in the play request, a script change in Home Assistant
**Status:** Approved by Nick on 2026-11-26 (in chat: "That works")
**Builds on:** `2026-11-26-play-on-tv-design.md` (its §9 "Later: open the exact movie")

---

## 1. Intent

**Stream it** opens the streaming app and leaves the family to find the movie with the remote. On Netflix the TV can
do better: tried on the Family Room TV on 2026-11-26, a launch that names the title started *Klaus* playing by itself,
with no profile picker and no extra button. Disney+ ignored five formats of the same idea, so this is Netflix only.

### Goals

1. **Stream it** (and the main page's ▶) on a Netflix movie starts that movie playing.
2. The app finds the Netflix id by itself for most movies, and a person can paste one for the rest.
3. A movie with no id, and every other service, behaves exactly as today.

### Non-goals

- Any service but Netflix. Nothing here should make a second one harder, but none is designed.
- Resuming at a position; Netflix does that itself.
- A confirm step before playback starts (decision 2).

### Anti-goals

- A lookup that is down, slow or wrong breaks adding a movie, the nightly refresh, or Play.
- A pasted id is overwritten by the lookup.
- Anything but digits reaches the TV's launch command.

## 2. Decisions (2026-11-26)

| # | Decision | Choice | Whose |
|---|---|---|---|
| 1 | Which services | Netflix only | Nick (tested on the TV: Netflix worked, Disney+ did not) |
| 2 | Confirm before it starts | No. A tap starts the film, on the movie's page and on the main page | Claude's call, played back, Nick: "That works" |
| 3 | Where the id comes from | Wikidata, looked up by TMDB id when a movie is added and nightly; plus a "Netflix link" field on the movie's page that wins over the lookup | Claude's call, played back, Nick: "That works" |
| 4 | What the page says | "Starting *Klaus* on Netflix…" in place of "Opening Netflix…" | Claude's call |
| 5 | Storage | A small table keyed by movie and service, not a Netflix column, so a second service needs no schema change | Claude's call |

## 3. What was learned on the TV and from Wikidata

- Home Assistant action `webostv.command`, command `system.launcher/launch`, payload
  `{"id": "netflix", "contentId": "m=https://www.netflix.com/watch/<id>&source_type=4"}` starts the title. Tested with
  the Netflix app not in the foreground. Not yet tested: Netflix already open on another title; a cold TV.
- Wikidata's query service answers `SELECT ?netflix WHERE { ?item wdt:P4947 "<tmdb movie id>" ; wdt:P1874 ?netflix . }`
  (`P4947` TMDB movie id, `P4983` TMDB TV series id, `P1874` Netflix id) with JSON at
  `https://query.wikidata.org/sparql?format=json&query=…`. Checked: 508965 → `80183187` (*Klaus*, the id that worked
  on the TV), 771 → `596974`, 10719 → `60031255`, 527435 → `80199682`, an unknown id → no rows. Wikidata holds an id
  even when the film is not on Netflix in the US, so the id is used only when TMDB says the movie is on Netflix.

## 4. Behaviour

### 4.1 The id

- Stored per movie and service: the title id, whether a person set it, and when the lookup last ran.
- **Lookup.** For a movie whose providers cache has Netflix in `flatrate`, the app asks Wikidata (10 s timeout) when
  the movie is added and in the nightly refresh when it has never been asked or was last asked over 30 days ago. A
  found id is stored; "none found" is stored too, so the question isn't repeated every night. More than one id: the
  first. Only a value of 1 to 12 digits is accepted. A failure (down, slow, HTTP error, unreadable answer) changes
  nothing, is one warning in the log, and waits for the next night. A TV-only special uses `P4983`.
- **By hand.** The movie's page shows, under Where to watch and only when the movie is on Netflix, a **Netflix link**
  field with **Save**. It takes a Netflix address (`https://www.netflix.com/title/80183187`, `…/watch/80183187`, with
  or without a query string or locale segment) or the bare number; anything else is a 400 with a sentence. Saving it
  empty clears a hand-set value and lets the lookup fill it again. A hand-set id is never changed by the lookup. The
  field shows the current id and says whether it was found automatically or set by hand.
- The movie in the API gains `"netflix": {"title_id": "80183187" | null, "manual": false}`; `null` object when the
  movie is not on Netflix. It is saved with the existing `PUT /api/movies/<id>` as `{"netflix_link": "…"}`.
- What leaves the house: the movie's TMDB id, to Wikidata. Nothing about people, ratings or viewing.

### 4.2 Play

- A stream option for Netflix with a known id carries `"direct": true` (others `false`).
- `POST /api/movies/<id>/play` for that option adds `"content_id": "<digits>"` to the Home Assistant payload and
  `"direct": true` to its answer. Everything else in the earlier design's §5.2 and §5.3 is unchanged, including
  confirmation: the TV reports the `Netflix` input either way.
- The page and the toast say "Starting *Klaus* on Netflix…" for a direct play. The confirmed and failure sentences
  stay as they are.

### 4.3 Home Assistant

- The automation's condition also requires `content_id`, when present, to be digits only, and passes it to the
  script (empty when absent).
- The script's stream branch, after Watch TV and the wait: when `content_id` is non-empty and `source` is `Netflix`,
  it sends the launch command of §3; otherwise it selects the source as today. An older app that sends no
  `content_id` keeps working, and a newer app talking to the older automation just opens the app.
- `docs/home-assistant.md` shows the new script and automation. Nick's live ones are updated by Claude after the code
  is merged, on his go-ahead.

## 5. Failure cases reviewers check first

1. Wikidata down, slow, HTTP 500, or answering something that isn't the expected JSON: the add still succeeds, the
   nightly refresh carries on to its other steps, nothing is stored, one warning.
2. A hand-set id survives the lookup; clearing it lets the lookup fill it.
3. An id that isn't digits, from Wikidata or a pasted link, is never stored and never sent.
4. A movie with an id that is no longer on Netflix (per the providers cache): no `direct`, no `content_id`; and when
   Netflix is not the chosen service (a digital copy ranks first), no `content_id` either.
5. A v2 database migrates; `migrate()` twice changes nothing.
6. With `HA_PLAY_WEBHOOK_URL` empty the field still works and nothing else shows.

## 6. Left to the builder

Module and table names, the lookup's User-Agent (the existing `UA`), CSS, where exactly the field sits, and how the
nightly script reports the step. The hardware pass after deploy: a direct play from a cold TV, and with Netflix
already open on another title.
