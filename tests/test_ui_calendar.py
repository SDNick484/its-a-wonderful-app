"""The Calendar tab (calendar spec §6; calendar plan Task 2; Review Focus 4 and 5) at phone size (412 and 360 px): the
header button fits, the month grid draws posters on the nights we watched, a day opens a sheet, the arrows and Back
step through months, a bad hash falls back to the grid, and a missing poster or a failed fetch degrade cleanly. Run by
the ui-smoke job (REQUIRE_UI=1). Today is 2026-12-05 in Los Angeles; sessions are stored in UTC."""
import datetime as dt
import shutil
from pathlib import Path

import pytest

import app
from test_ui_grid import _contrast, _side_scroll
from test_ui_smoke import PHONE, SMALL_PHONE, browser, server  # noqa: F401  (fixtures shared with the smoke tests)
from test_ui_providers import _open

POSTER = Path(__file__).parent / "fixtures" / "tmdb" / "poster.jpg"
VIEWPORTS = pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])


@pytest.fixture
def seeded(server, tmdb_fixtures, monkeypatch):          # noqa: F811
    """Elf over Dec 3 and Dec 5 (finished on the 5th), Home Alone paused on Dec 5 with no TV data, and Klaus finished
    on Dec 12 with no sessions and no poster. Returns (url, {title: movie_id})."""
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    monkeypatch.setattr(app, "today", lambda: dt.date(2026, 12, 5))
    app.POSTER_DIR.mkdir(parents=True, exist_ok=True)
    ids = {}
    with app.app.app_context():
        con = app.get_db()
        for tmdb_id, title, year, poster in ((10719, "Elf", 2003, "movie-10719-w342.jpg"),
                                             (771, "Home Alone", 1990, "movie-771-w342.jpg"),
                                             (508439, "Klaus", 2019, None)):
            if poster:
                shutil.copy(POSTER, app.POSTER_DIR / poster)
            ids[title] = con.execute("INSERT INTO movies (tmdb_id, tmdb_type, title, year, poster_path) VALUES (?, 'movie', ?, ?, ?)",
                                     (tmdb_id, title, year, poster)).lastrowid
        elf = con.execute("INSERT INTO viewings (movie_id, started_on, status, finished_on) VALUES (?, '2026-12-03', 'finished', '2026-12-05')",
                          (ids["Elf"],)).lastrowid
        for at in ("2026-12-04T03:40:00Z", "2026-12-06T02:55:00Z"):
            con.execute("INSERT INTO sessions (viewing_id, tv_source, started_at) VALUES (?, 'Shield', ?)", (elf, at))
        con.execute("INSERT INTO viewings (movie_id, started_on, status) VALUES (?, '2026-12-05', 'paused')", (ids["Home Alone"],))
        con.execute("INSERT INTO viewings (movie_id, started_on, status, finished_on) VALUES (?, '2026-12-12', 'finished', '2026-12-12')",
                    (ids["Klaus"],))
        con.commit()
    return server, ids


def _calendar(browser, seeded, viewport, path="/"):        # noqa: F811
    url, _ = seeded
    page, errors = _open(browser, url, viewport, path)
    if path == "/":
        page.click("#calendar-btn")
    page.wait_for_selector("#calendar-view:not([hidden]) #calendar-grid .cal-day")
    return page, errors


def _day(date):
    return f'#calendar-grid button.cal-day[data-date="{date}"]'


@VIEWPORTS
def test_calendar_link_fits_beside_the_list_heading(browser, seeded, viewport):   # noqa: F811
    """§9: the header has no room for a fourth control at 360 px, so the way in is a link beside the list's heading."""
    page, errors = _open(browser, seeded[0], viewport)
    link = page.locator("#grid-view .list-head #calendar-btn")
    assert link.is_visible() and link.get_attribute("aria-label") == "Calendar" and link.inner_text() == "Calendar"
    assert page.evaluate("""() => {
        const a = document.getElementById('calendar-btn').getBoundingClientRect();
        const h = document.querySelector('.list-head .section-title').getBoundingClientRect();
        const row = [...document.querySelectorAll('#worth-btn, #settings-btn, #add-btn')].map(e => e.getBoundingClientRect());
        return a.height >= 44 && a.left >= h.right && a.right <= window.innerWidth && a.top < h.bottom && h.top < a.bottom
            && row.every(r => r.right <= window.innerWidth && Math.abs(r.top - row[0].top) < 2 && r.height >= 44);
    }""")
    assert _side_scroll(page) <= 0 and errors == []


@VIEWPORTS
def test_tab_shows_the_month(browser, seeded, viewport):   # noqa: F811
    page, errors = _calendar(browser, seeded, viewport)
    assert page.title() == "Calendar · It's a Wonderful App"
    assert page.inner_text("#calendar-title") == "December 2026"
    assert page.is_hidden("#grid-view")
    for date in ("2026-12-03", "2026-12-05", "2026-12-12"):
        assert page.locator(_day(date)).count() == 1
    assert page.locator(_day("2026-12-04")).count() == 0
    dec5 = page.locator(_day("2026-12-05"))
    assert dec5.locator(".cal-more").inner_text() == "+1"
    assert dec5.locator(".cal-done").count() == 1
    assert "cal-today" in dec5.get_attribute("class")
    assert dec5.get_attribute("aria-label") == "Dec 5: Elf, Home Alone. A movie finished."
    assert page.locator(_day("2026-12-03")).get_attribute("aria-label") == "Dec 3: Elf."
    sizes = page.eval_on_selector_all("#calendar-grid button.cal-day",
                                      "els => els.map(e => [e.getBoundingClientRect().width, e.getBoundingClientRect().height])")
    assert sizes and all(w >= 44 and h >= 44 for w, h in sizes)
    assert _contrast(page, ".cal-num") >= 4.5
    assert _side_scroll(page) <= 0 and errors == []


@VIEWPORTS
def test_tapping_a_day_opens_the_sheet(browser, seeded, viewport):   # noqa: F811
    page, errors = _calendar(browser, seeded, viewport)
    page.click(_day("2026-12-05"))
    sheet = page.locator(".sheet")
    assert sheet.locator(".sheet-title").inner_text() == "Saturday, December 5"
    rows = sheet.locator(".cal-row")
    assert rows.count() == 2
    assert "Elf (2003)" in rows.nth(0).inner_text() and "Finished" in rows.nth(0).inner_text()
    assert "Home Alone (1990)" in rows.nth(1).inner_text() and "Finished" not in rows.nth(1).inner_text()
    page.keyboard.press("Escape")
    assert page.locator(".sheet").count() == 0
    assert page.evaluate("document.activeElement.dataset.date") == "2026-12-05"
    page.click(_day("2026-12-05"))
    page.click(".sheet .cal-row >> text=Elf (2003)")
    page.wait_for_function(f"location.hash === '#/m/{seeded[1]['Elf']}' && document.getElementById('detail').innerText.includes('Elf')")
    assert page.locator(".sheet").count() == 0
    assert page.is_hidden("#calendar-view") and page.is_visible("#detail-view") and errors == []


def test_arrows_change_month_and_hash(browser, seeded):   # noqa: F811
    page, errors = _calendar(browser, seeded, PHONE)
    for arrow in ("#calendar-prev", "#calendar-next"):
        box = page.locator(arrow).bounding_box()
        assert box["width"] >= 44 and box["height"] >= 44
    page.click("#calendar-prev")
    page.wait_for_function("document.getElementById('calendar-title').textContent === 'November 2026'")
    assert page.evaluate("location.hash") == "#/calendar/2026-11"
    assert page.inner_text("#calendar-status") == "Nothing watched in November yet."
    page.go_back()
    page.wait_for_function("document.getElementById('calendar-title').textContent === 'December 2026'")
    assert page.locator(_day("2026-12-05")).count() == 1 and page.inner_text("#calendar-status") == ""
    page.click("#calendar-next")
    page.wait_for_function("document.getElementById('calendar-title').textContent === 'January 2027'")
    assert page.evaluate("location.hash") == "#/calendar/2027-01"
    assert errors == []


def test_direct_links_and_bad_hash(browser, seeded):   # noqa: F811
    page, errors = _calendar(browser, seeded, PHONE, "/#/calendar/2026-12")
    assert page.inner_text("#calendar-title") == "December 2026"
    bad, bad_errors = _open(browser, seeded[0], PHONE, "/#/calendar/2026-13")
    assert bad.is_visible("#grid-view") and bad.is_hidden("#calendar-view") and bad_errors == []
    aug, aug_errors = _open(browser, seeded[0], SMALL_PHONE, "/#/calendar/2026-08")
    aug.wait_for_function("document.getElementById('calendar-title').textContent === 'August 2026'")
    nums = aug.eval_on_selector_all("#calendar-grid .cal-num", "els => els.map(e => e.textContent)")
    assert nums == [str(d) for d in range(1, 32)]
    assert _side_scroll(aug) <= 0 and aug_errors == [] and errors == []


def test_movie_without_a_poster(browser, seeded):   # noqa: F811
    page, errors = _calendar(browser, seeded, SMALL_PHONE)
    cell = page.locator(_day("2026-12-12"))
    assert cell.locator(".poster-ph").inner_text() == "Klaus"
    assert cell.evaluate("e => e.scrollWidth <= e.clientWidth && e.scrollHeight <= e.clientHeight")
    cell.click()
    assert page.locator(".sheet .cal-row .poster-ph").inner_text() == "Klaus"
    assert _side_scroll(page) <= 0 and errors == []


def test_api_failure_shows_a_message(browser, seeded):   # noqa: F811
    page, errors = _open(browser, seeded[0], PHONE)
    page.route("**/api/calendar*", lambda route: route.fulfill(status=500, content_type="application/json",
                                                               body='{"error": "boom"}'))
    page.click("#calendar-btn")
    page.wait_for_function("document.getElementById('calendar-status').textContent === \"Couldn't load the calendar right now.\"")
    assert page.locator("#calendar-grid .cal-day").count() == 0 and errors == []


def test_calendar_is_fetched_only_when_its_tab_opens(browser, seeded):   # noqa: F811
    page, _ = _open(browser, seeded[0], PHONE)
    requests = []
    page.on("request", lambda r: requests.append(r.url) if "/api/calendar" in r.url else None)
    page.goto(seeded[0] + "/#/worth")
    page.wait_for_selector("#worth-view:not([hidden])")
    page.goto(seeded[0] + "/#/")
    page.wait_for_selector("#grid-view:not([hidden])")
    assert requests == []
    page.click("#calendar-btn")
    page.wait_for_selector("#calendar-view:not([hidden]) .cal-day")
    assert len(requests) == 1


def test_going_back_restores_the_grid_scroll(browser, seeded):   # noqa: F811
    page, errors = _open(browser, seeded[0], PHONE)
    # The link sits near the top of the list, so a click would first scroll it into view: open the tab by its hash.
    page.evaluate("document.body.style.minHeight = '3000px'; window.scrollTo(0, 400); location.hash = '#/calendar'")
    page.wait_for_selector("#calendar-view:not([hidden])")
    page.click("#calendar-back")
    page.wait_for_selector("#grid-view:not([hidden])")
    assert page.evaluate("Math.round(window.scrollY)") == 400
    assert errors == []
