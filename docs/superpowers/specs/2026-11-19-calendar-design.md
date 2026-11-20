# Calendar tab: design

**Date:** 2026-11-19
**Repo:** `SDNick484/its-a-wonderful-app`, `main` @ `1dceb30` (schema v1)
**Size:** a small change: one read-only route, one tab, no schema change
**Status:** Approved by Nick on 2026-11-19

---

## 1. Intent

A separate tab that shows one month as a calendar, with the movie posters we watched placed on the nights we
watched them. It is for looking back over the season ("what did we watch the week before Christmas?"), and it
is only really used from late November to Christmas.

### Goals

1. A month grid with a poster on each day a movie was watched, month arrows, and the current month first.
2. A movie that took several nights appears on each night we watched it.
3. Tapping a day lists that night's movies, each linking to its page.
4. It reads only the local database, so it works while TMDB, Matinee and Home Assistant are down.

### Non-goals

- Past years, or a backfill from Matinee. The app only knows what it has recorded since it started.
- Watches logged in Matinee for movies we watched outside this app.
- Editing, moving or deleting a watch from the calendar.
- Per-person views (who watched), and planning future nights.
- A public view. Like every route in the app, it needs `@editor_required`.

### Anti-goals (fails even if it technically works)

- Showing a night that did not happen: a movie that was only picked ("tonight" with no time watched), or one we
  gave up on.
- A grid that scrolls sideways or has tap targets under 44 px at 360 or 412 px.
- Any new runtime dependency or build step.

## 2. Decisions from brainstorming (2026-11-19, Nick)

| # | Decision | Choice |
|---|---|---|
| 1 | Use | Looking back, in the lead-up to Christmas. Opens on the current month. |
| 2 | A movie over several nights | **Show every night we watched it**, falling back to the start date when we have no session data. |
| 3 | Look | **Poster month grid** (approach A below). |

## 3. Approaches considered

| | What it is | Trade-off |
|---|---|---|
| **A. Poster month grid (chosen)** | A poster in each day cell, a "+N" badge when a day has more than one movie, tap a day for a list. | Looks like the rest of the app and a poster is easy to recognise. Cells are about 52 px wide at 412 px, so titles are not readable in the grid; the day sheet covers that. |
| B. Compact grid plus a list | Dots in the cells and a dated list underneath. | Very readable, but less fun to look at, and you read the list, not the calendar. |
| C. List by date only | "Thu Dec 3: Elf". | Simplest and most readable, but it is not a calendar and a quiet month is mostly blank. |

## 4. Which nights count (my calls, checked against `viewings.py`)

A viewing contributes a set of local dates. A date is shown for that viewing when it is any of:

- the local date of a `sessions.started_at` (stored in UTC, converted with the host's `TZ` as `viewings._local`
  does). A session that starts before 4 am local counts as the evening before, the same 4 am rule the app uses for
  "tonight" (`viewings.NIGHT_ENDS`);
- `viewings.started_on`;
- `viewings.finished_on`, when the viewing is finished.

A viewing is left out entirely when its status is `abandoned`, or when it is `tonight` with no sessions (a pick
that was never watched). A `tonight` viewing that was paused earlier and picked again still shows its earlier
nights. A rewatch is a second viewing of the same movie, so the movie can appear on two unrelated dates.

**Scenario.** *Elf* has a viewing with `started_on = 2026-12-03`, sessions starting 2026-12-03 19:40 and
2026-12-05 18:55 (Los Angeles), and `finished_on = 2026-12-05`. *Home Alone* has a viewing paused with no TV data,
`started_on = 2026-12-05`. For `month=2026-12`:

- Dec 3: Elf.
- Dec 4: nothing (no session, so we do not guess).
- Dec 5: Elf (finished) and Home Alone, so the cell shows Elf's poster with a "+1" badge and a check mark.

## 5. API

`GET /api/calendar?month=YYYY-MM`, `@editor_required`, reads the database only. `month` defaults to the current
month on the host's local date; anything else is a 400 with `{"error": "month must look like 2026-12"}`. An empty
month is `days: {}`, not an error.

```json
{
  "month": "2026-12",
  "today": "2026-12-05",
  "days": {
    "2026-12-03": [
      {"movie_id": 3, "viewing_id": 12, "title": "Elf", "year": 2003,
       "poster_url": "/images/posters/elf.jpg", "finished": false}
    ],
    "2026-12-05": [
      {"movie_id": 3, "viewing_id": 12, "title": "Elf", "year": 2003,
       "poster_url": "/images/posters/elf.jpg", "finished": true},
      {"movie_id": 9, "viewing_id": 15, "title": "Home Alone", "year": 1990,
       "poster_url": "/images/posters/home-alone.jpg", "finished": false}
    ]
  }
}
```

Within a day, finished movies come first, then by the viewing's earliest session, then by `viewing_id`.
`poster_url` is built the same way `/api/continue` builds it. `finished` is true only on the `finished_on` day.

Code goes in a new route-free module (see §8 on its name); the route stays in `app.py` and the module is added to
`_SPLIT_MODULES` and to `installer/build.sh`.

## 6. UI (412 px phone first)

New tab at `#/calendar/YYYY-MM` (`#/calendar` opens the current month), so the browser Back button steps between
months. Reached from a header icon button (a calendar glyph, `aria-label="Calendar"`, styled like the settings
button) because the header already holds the brand, Worth a Month?, Settings and Add.

```
 < Calendar              (back to Our list)
 <   December 2026   >
 S    M    T    W    T    F    S
                1    2   [Elf] 4
                          3
 5    6    7    8    9   10   11
[Elf✓]
[+1]
```

- Seven columns, Sunday first. Each cell is a button only when it has a movie, so empty days are not tap targets.
  A cell is at least 44 px square and shows the day number plus the first movie's poster. A "+N" badge shows when
  a day has more than one movie, and a check mark when any movie finished that day. Today has a ring.
- Tapping a cell opens the existing sheet component with the date as its title and one row per movie: poster,
  title and year, "Finished" when it finished that day, each linking to `#/m/<movie_id>`. One movie or several, so
  the behaviour is the same.
- Month arrows are 44 px buttons and both are always enabled. An empty month says "Nothing watched in December
  yet." The tab loads from `/api/calendar` each time it opens, like Worth a Month?.
- Poster failures use the existing `watchPosters` fallback. Day numbers and badges sit on a `--raised` panel so they
  stay at 4.5:1 over every theme.
- Each cell has an `aria-label` such as "Dec 5: Elf, Home Alone. A movie finished."

## 7. Rules from CLAUDE.md this touches

- **No schema change**, no setting, nothing new in `$DATA_DIR`, so migrations, the installer settings list and
  `ops/wonderful-backup` are unchanged.
- **Auth:** the new route has `@editor_required`; `tests/test_auth.py` walks it.
- **JS:** a new `static/js/calendar.js`, listed in `JS_MODULES` in `tests/conftest.py`.
- **Theme tokens:** any new text colour is added to `TOKENS` in `tests/test_theme_ui.py`.
- **Docs:** `README.md` is updated in the same PR.

## 8. Testing

No live network, nothing recorded from TMDB. Tests build viewings and sessions directly.

- `tests/test_watched_days.py` (new): the Elf and Home Alone scenario above; a session at 2026-12-06 07:30 UTC
  lands on Dec 5 (11:30 pm Los Angeles); a session at 2026-12-06 09:00 UTC (1:00 am) also lands on Dec 5; a
  `tonight` viewing with no sessions and an `abandoned` one are absent; a paused-then-picked-again viewing keeps its
  earlier nights; a rewatch gives two entries on different days; a Nov 30 session is not in `month=2026-12`;
  `month=2026-13`, `month=Dec` and `month=` are 400; no `month` means the current month; an empty month is `{}`.
- `tests/test_auth.py` keeps passing with the new rule.
- `tests/test_ui_calendar.py` (new, Playwright): at 412 and 360 px there is no horizontal scroll; cells and arrows
  are at least 44 px; the header, with the new button, does not overflow; the arrows change the month and the hash;
  tapping a day with two movies opens a sheet listing both with working links; an empty month shows the message.

## 9. Left to the builder

- Exact cell sizing, badge style and the calendar glyph.
- If the header does not fit at 360 px with the new button, put a "Calendar" link beside the "Our Christmas
  movies" heading on the home screen instead.
- The module name. **It must not be `calendar.py`**: that would shadow the standard library's `calendar` module for
  every import in the app. Use something like `watched_days.py`.

## 10. Deferred

- Past years, once there is data worth showing.
- Showing who watched, using the people colours.
- Moving a watch to another night from the calendar.
