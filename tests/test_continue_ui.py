"""Playwright at phone size (412 and 360 px): Watch tonight on the detail view, the Continue Watching row above the grid
(only when something is in it), its actions sheet, We finished -> the rating sheet (straight away) with the
viewing's people first, and the "Did you finish?" sheet (Yes, Not yet, "We gave up on it"; the guess highlighted, never
answered for you). Run by the ui-smoke job (REQUIRE_UI=1). TMDB answers from fixtures; the people have made-up names."""
import pytest

import app
from test_rating_ui import FAMILY, _toast
from test_ui_grid import _contrast, _height, _side_scroll
from test_ui_smoke import PHONE, SMALL_PHONE, browser, server  # noqa: F401  (fixtures shared with the smoke tests)


@pytest.fixture
def seeded(server, tmdb_fixtures):          # noqa: F811
    """Elf and Prancer on the list, five people. Matinee is off (no key), so a finish sends nothing to it."""
    with app.app.app_context():
        con = app.get_db()
        for tmdb_id in (10719, 14181):
            app.movies.add_movie(con, tmdb_id, "movie", "test")
        for name, kind, color in FAMILY:
            app.people.add_person(con, {"name": name, "kind": kind, "color": color})
    return server


def _open(browser, url, viewport):       # noqa: F811
    page = browser.new_page(viewport=viewport, device_scale_factor=2.625, is_mobile=True, has_touch=True)
    errors, calls = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: calls.append((r.method, r.url.split("/", 3)[-1])) if "/api/" in r.url else None)
    page.goto(url + "/")
    page.wait_for_function("document.getElementById('grid-empty').textContent !== 'Loading…'")
    return page, errors, calls


def _paused_with_guess(guess, seconds=3000):
    """Elf paused after a TV session that ended with `guess` (what the TV webhook task will do)."""
    with app.app.app_context():
        con = app.get_db()
        viewing_id = app.viewings.watch_tonight(con, 1)
        con.execute("UPDATE viewings SET status='paused', watched_seconds=?, guess=? WHERE id=?", (seconds, guess, viewing_id))
        con.commit()
    return viewing_id


def _status(viewing_id):
    with app.app.app_context():
        return tuple(app.get_db().execute("SELECT status, guess FROM viewings WHERE id=?", (viewing_id,)).fetchone())


def _solid(page, sel):
    """Give a transparent element the panel colour it sits on, so its contrast can be measured."""
    page.evaluate("(s) => { const e = document.querySelector(s);"
                  " if (!getComputedStyle(e).backgroundColor.match(/[1-9]/)) e.style.backgroundColor = '#16161c'; }", sel)


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_watch_tonight_puts_it_on_the_row_above_the_grid(browser, seeded, viewport):   # noqa: F811
    page, errors, _ = _open(browser, seeded, viewport)
    assert not page.is_visible("#continue")                                        # nothing in it: no row
    page.click(".movie-card >> text=Elf")
    page.click("#detail-tonight")
    _toast(page, "Elf is on for tonight")
    page.wait_for_selector("#detail-tonight-status")
    assert page.inner_text("#detail-tonight-status") == "On for tonight." and page.is_visible("#detail-finish")
    page.click("#back-link")
    page.wait_for_selector("#continue-row .continue-item")
    assert page.is_visible("#continue") and page.inner_text("#continue-title") == "Continue Watching"
    assert page.inner_text("#continue-row .continue-status") == "Tonight"
    above = page.evaluate("document.getElementById('continue').getBoundingClientRect().bottom"
                          " <= document.getElementById('grid').getBoundingClientRect().top")
    assert above and _side_scroll(page) <= 0 and errors == []
    assert _height(page, ".continue-item") >= 44
    _solid(page, ".continue-status")
    assert _contrast(page, ".continue-status") >= 4.5


def test_we_finished_then_rate_with_the_viewings_people_first(browser, seeded):   # noqa: F811
    with app.app.app_context():
        con = app.get_db()
        app.viewings.watch_tonight(con, 1, [2, 4])                                 # Blake and Drew watched
    page, errors, calls = _open(browser, seeded, PHONE)
    page.click("#continue-row .continue-item")
    page.wait_for_selector("#continue-actions [data-act=finish]")
    for sel in ("#continue-actions [data-act=finish]", "#continue-actions [data-act=abandon]", "#continue-actions a.btn"):
        assert _height(page, sel) >= 44, sel
    page.click("#continue-actions [data-act=finish]")
    page.wait_for_selector(".rate-row")                                            # no "Want to rate it?" first
    assert page.locator("#rate-ask").count() == 0 and page.inner_text("#rate-title") == "Rate Elf"
    assert ("POST", "api/viewings/1/finish") in calls
    assert not page.is_visible("#continue")                                        # finished: off the row
    names = page.eval_on_selector_all(".rate-row .rate-name", "els => els.map(e => e.textContent)")
    assert names == ["Blake", "Drew", "Avery", "Casey", "Emery"]                   # the viewing's people first
    assert page.locator(".rate-row-dim").count() == 3
    _solid(page, ".rate-row-dim .rate-name")
    assert _contrast(page, ".rate-row-dim .rate-name") >= 4.5
    page.locator(".rate-row:has-text('Blake') .rate-slider").fill("9")
    page.click("#rate-done")
    _toast(page, "Ratings saved")
    page.wait_for_selector(".movie-card .star")
    assert page.locator(".movie-card", has_text="Elf").locator(".star").inner_text() == "★ 9.0"
    assert _status(1) == ("finished", None) and errors == []


def test_did_you_finish_highlights_the_guess_without_answering(browser, seeded):   # noqa: F811
    viewing_id = _paused_with_guess("not_finished")
    page, errors, calls = _open(browser, seeded, PHONE)
    page.wait_for_selector("#finish-prompt")
    assert page.inner_text("#finish-prompt-title") == "Did you finish Elf?"
    assert page.get_attribute("[data-ans=not-yet]", "data-guess") == "true"        # the guess is highlighted
    assert page.get_attribute("[data-ans=yes]", "data-guess") is None
    assert page.is_visible("[data-ans=abandon]") and page.inner_text("[data-ans=abandon]") == "We gave up on it"
    for sel in ("[data-ans=yes]", "[data-ans=not-yet]", "[data-ans=abandon]"):
        assert _height(page, sel) >= 44, sel
    for sel in ("[data-ans=yes]", "[data-ans=not-yet]"):
        assert _contrast(page, sel) >= 4.5, sel
    _solid(page, "[data-ans=abandon]")
    assert _contrast(page, "[data-ans=abandon]") >= 4.5
    page.wait_for_timeout(300)
    assert not any(path.startswith("api/viewings/") for _m, path in calls)         # not answered for you
    assert _status(viewing_id) == ("paused", "not_finished")
    assert _side_scroll(page) <= 0
    page.click("[data-ans=not-yet]")
    page.wait_for_selector("#finish-prompt", state="detached")
    assert _status(viewing_id) == ("paused", None)
    page.wait_for_function("document.querySelector('#continue-row .continue-status')?.textContent === 'About halfway'")
    page.reload()                                                                  # answered: not asked again
    page.wait_for_selector("#continue-row .continue-item")
    page.wait_for_timeout(300)
    assert not page.is_visible("#finish-prompt") and errors == []


def test_did_you_finish_yes_then_close_the_rating_sheet(browser, seeded):   # noqa: F811
    viewing_id = _paused_with_guess("finished", seconds=5700)
    page, errors, _ = _open(browser, seeded, PHONE)
    page.wait_for_selector("#finish-prompt")
    assert page.get_attribute("[data-ans=yes]", "data-guess") == "true"
    page.click("[data-ans=yes]")
    page.wait_for_selector(".rate-row")
    assert page.locator("#finish-prompt").count() == 0
    page.keyboard.press("Escape")                                                  # closing it rates nobody
    page.wait_for_selector(".sheet", state="detached")
    with app.app.app_context():
        assert app.ratings.family(app.get_db(), 1)["mean"] is None
    assert _status(viewing_id) == ("finished", None) and not page.is_visible("#continue") and errors == []


def test_we_gave_up_on_it(browser, seeded):   # noqa: F811
    viewing_id = _paused_with_guess("not_finished")
    page, errors, _ = _open(browser, seeded, SMALL_PHONE)
    page.wait_for_selector("#finish-prompt")
    page.click("[data-ans=abandon]")
    page.wait_for_selector("#finish-prompt", state="detached")
    assert _status(viewing_id) == ("abandoned", None)
    page.wait_for_function("document.getElementById('continue').hidden")
    assert errors == []


def test_keep_watching_tonight_from_the_row(browser, seeded):   # noqa: F811
    with app.app.app_context():
        con = app.get_db()
        viewing_id = app.viewings.watch_tonight(con, 1)
        con.execute("UPDATE viewings SET status='paused', watched_seconds=600 WHERE id=?", (viewing_id,))
        con.commit()
    page, errors, _ = _open(browser, seeded, PHONE)
    page.wait_for_selector("#continue-row .continue-item")
    assert page.inner_text("#continue-row .continue-status") == "Just started"
    page.click("#continue-row .continue-item")
    page.click("#continue-actions [data-act=keep]")
    page.wait_for_function("document.querySelector('#continue-row .continue-status')?.textContent === 'Tonight'")
    assert _status(viewing_id)[0] == "tonight" and errors == []


def _finished(movie_id, day, people):
    with app.app.app_context():
        con = app.get_db()
        viewing_id = con.execute("INSERT INTO viewings (movie_id, started_on, status, finished_on) VALUES (?, ?, 'finished', ?)",
                                 (movie_id, day, day)).lastrowid
        con.executemany("INSERT INTO viewing_people (viewing_id, person_id) VALUES (?, ?)", [(viewing_id, p) for p in people])
        con.commit()
    return viewing_id


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_the_watched_list_and_deleting_a_mistake(browser, seeded, viewport):   # noqa: F811
    day = app.today().isoformat()
    _finished(1, "2025-12-20", [1, 2])
    mistake = _finished(1, day, [1, 2, 3, 4, 5])
    _finished(1, day, [1, 2, 3, 4, 5])                                             # the same night twice: one is a mistake
    page, errors, calls = _open(browser, seeded, viewport)
    page.click(".movie-card >> text=Elf")
    page.wait_for_selector(".watched-row")
    assert page.locator(".watched-row").count() == 3
    assert page.inner_text(".watched-row >> nth=0 >> .watched-ago") == "(today)"
    assert "Dec 20, 2025" in page.inner_text(".watched-row >> nth=2 >> .watched-date")
    assert page.locator(".watched-row >> nth=2 >> .dot").count() == 2              # who watched
    assert page.get_attribute(".watched-row >> nth=2 >> .watched-who", "aria-label") == "Watched by Avery, Blake"
    assert _height(page, ".watched-delete") >= 44 and _side_scroll(page) <= 0
    for sel in (".watched-date", ".watched-ago", ".watched-delete"):
        _solid(page, sel)
        assert _contrast(page, sel) >= 4.5, sel
    page.click(f".watched-delete[data-viewing='{mistake}']")
    page.wait_for_selector("#watched-delete [data-act=delete]")
    assert "deleted in Matinee too" in page.inner_text("#watched-delete")
    page.click("#watched-delete [data-act=cancel]")                                # Cancel keeps it
    page.wait_for_selector("#watched-delete", state="detached")
    assert page.locator(".watched-row").count() == 3
    page.click(f".watched-delete[data-viewing='{mistake}']")
    page.click("#watched-delete [data-act=delete]")
    _toast(page, "Viewing deleted")
    assert page.locator(".watched-row").count() == 2 and ("DELETE", f"api/viewings/{mistake}") in calls
    with app.app.app_context():
        assert app.get_db().execute("SELECT COUNT(*) FROM viewings WHERE id=?", (mistake,)).fetchone()[0] == 0
    assert errors == []


def test_we_finished_on_the_detail_view_adds_to_the_watched_list(browser, seeded):   # noqa: F811
    with app.app.app_context():
        app.viewings.watch_tonight(app.get_db(), 1)
    page, errors, _ = _open(browser, seeded, PHONE)
    page.click(".movie-card >> text=Elf")
    page.wait_for_selector(".watched-none")
    assert page.inner_text("#detail-watched") == "Not watched yet."
    page.click("#detail-finish")
    page.wait_for_selector(".rate-row")                                            # the rating sheet, straight away
    page.keyboard.press("Escape")
    page.wait_for_selector(".watched-row")
    assert page.inner_text(".watched-ago") == "(today)" and errors == []
