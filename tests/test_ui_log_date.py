"""Playwright at phone size (412 and 360 px): Log date on a movie's detail view, for a night nobody logged at the time
(as in Matinee). The Who watched row has everyone on until someone is tapped off, the date field takes today or
earlier, and Log date adds the night to the Watched list and opens the rating sheet with those people first. Run by
the ui-smoke job (REQUIRE_UI=1). TMDB answers from fixtures, Matinee is off, and the people have made-up names.

The host says it is 2026-12-05, which is never the browser's own date: "today", "yesterday" and the newest date the
field offers must all come from the host (TZ), not from the phone's clock."""
import datetime as dt

import pytest

import app
from test_continue_ui import _open, _solid, _status, seeded  # noqa: F401  (the fixture: Elf, Prancer and five people)
from test_rating_ui import _toast
from test_ui_grid import _contrast, _height, _side_scroll
from test_ui_smoke import PHONE, SMALL_PHONE, browser, server  # noqa: F401  (fixtures shared with the smoke tests)

NAMES = ["Avery", "Blake", "Casey", "Drew", "Emery"]
TODAY, LAST_NIGHT = "2026-12-05", "2026-12-04"


@pytest.fixture(autouse=True)
def host_day(monkeypatch):
    monkeypatch.setattr(app, "today", lambda: dt.date(2026, 12, 5))


def _who(name):
    return f"#detail-who .who-btn[aria-label='{name}']"


def _pressed(page):
    return page.eval_on_selector_all("#detail-who .who-btn[aria-pressed=true]", "els => els.map(e => e.getAttribute('aria-label'))")


def _elf(page):
    page.click(".movie-card >> text=Elf")
    page.wait_for_selector("#detail-log")


def _viewings():
    """[(status, finished_on, [person ids])] for Elf, oldest first."""
    with app.app.app_context():
        con = app.get_db()
        return [(v["status"], v["finished_on"], [r["person_id"] for r in con.execute(
            "SELECT person_id FROM viewing_people WHERE viewing_id=? ORDER BY person_id", (v["id"],))])
            for v in con.execute("SELECT id, status, finished_on FROM viewings WHERE movie_id=1 ORDER BY id").fetchall()]


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_log_last_night_for_the_ones_who_watched(browser, seeded, viewport):   # noqa: F811
    page, errors, calls = _open(browser, seeded, viewport)
    _elf(page)
    assert page.inner_text("#detail-who .who-label") == "Who watched"
    assert _pressed(page) == NAMES                                                 # everyone, until someone is tapped off
    assert page.get_attribute("#detail-log-date", "max") == TODAY                  # not a night that hasn't happened
    assert page.input_value("#detail-log-date") == "" and page.inner_text("#detail-log") == "Log date"
    for sel in (_who("Avery"), "#detail-log-date", "#detail-log"):
        assert _height(page, sel) >= 44, sel
    assert page.evaluate("(s) => document.querySelector(s).getBoundingClientRect().width", _who("Avery")) >= 44
    assert _side_scroll(page) <= 0
    page.click(_who("Avery"))
    page.click(_who("Emery"))
    assert _pressed(page) == ["Blake", "Casey", "Drew"]
    for name in NAMES:                                                             # on (the person's colour) and off
        _solid(page, _who(name))
        assert _contrast(page, _who(name)) >= 4.5, name
    for sel in ("#detail-who .who-label", "#detail-log-date", "#detail-log"):
        _solid(page, sel)
        assert _contrast(page, sel) >= 4.5, sel
    page.fill("#detail-log-date", LAST_NIGHT)
    page.click("#detail-log")
    page.wait_for_selector(".rate-row")                                            # the rating sheet, straight away
    names = page.eval_on_selector_all(".rate-row .rate-name", "els => els.map(e => e.textContent)")
    assert names == ["Blake", "Casey", "Drew", "Avery", "Emery"]                   # the ones who watched first
    page.keyboard.press("Escape")
    page.wait_for_selector(".sheet", state="detached")
    assert page.locator(".watched-row").count() == 1 and page.inner_text(".watched-ago") == "(yesterday)"
    assert page.get_attribute(".watched-who", "aria-label") == "Watched by Blake, Casey, Drew"
    assert ("POST", "api/movies/1/watched") in calls
    assert _viewings() == [("finished", LAST_NIGHT, [2, 3, 4])]
    assert page.input_value("#detail-log-date") == "" and _pressed(page) == NAMES  # ready for another night
    assert _side_scroll(page) <= 0 and errors == []


def test_log_date_needs_a_date_and_somebody(browser, seeded):   # noqa: F811
    page, errors, calls = _open(browser, seeded, PHONE)
    _elf(page)
    page.click("#detail-log")                                                      # no date chosen
    _toast(page, "Choose a date")
    for name in NAMES:
        page.click(_who(name))
    assert _pressed(page) == [] and page.is_disabled("#detail-log")                # nobody watched: nothing to log
    page.click(_who("Blake"))
    assert page.is_enabled("#detail-log")
    assert not any(path.endswith("/watched") for _m, path in calls) and _viewings() == []
    assert errors == []


def test_log_date_finishes_the_movie_waiting_in_continue_watching(browser, seeded):   # noqa: F811
    with app.app.app_context():
        con = app.get_db()
        viewing_id = app.viewings.watch_tonight(con, 1)
        con.execute("UPDATE viewings SET status='paused', started_on=?, watched_seconds=600 WHERE id=?", (LAST_NIGHT, viewing_id))
        con.commit()
    page, errors, _ = _open(browser, seeded, PHONE)
    _elf(page)
    assert page.is_visible("#detail-tonight-status")                               # In Continue Watching: Just started.
    page.fill("#detail-log-date", LAST_NIGHT)
    page.click("#detail-log")
    page.wait_for_selector(".rate-row")
    page.keyboard.press("Escape")
    page.wait_for_selector("#detail-tonight")                                      # Watch tonight is back
    assert page.locator("#detail-tonight-status").count() == 0 and page.locator(".watched-row").count() == 1
    assert _status(viewing_id) == ("finished", None) and len(_viewings()) == 1     # that viewing, not a second one
    page.click("#back-link")
    page.wait_for_function("document.getElementById('continue').hidden")           # and it is off the row
    assert errors == []


def test_log_date_with_no_family_yet_has_no_who_watched_row(browser, server, tmdb_fixtures):   # noqa: F811
    with app.app.app_context():
        app.movies.add_movie(app.get_db(), 10719, "movie", "test")
    page, errors, _ = _open(browser, server, PHONE)
    _elf(page)
    assert page.locator("#detail-who").count() == 0
    page.fill("#detail-log-date", TODAY)
    page.click("#detail-log")
    _toast(page, "Logged")
    page.wait_for_selector(".watched-row")
    assert page.inner_text(".watched-ago") == "(today)" and _viewings() == [("finished", TODAY, [])]
    assert errors == []


# ------------------------------------------------------------------------------------------------ one page, one movie
# The detail view once added a click handler on every visit and never took the old ones away, so the second movie's
# page still answered for the first: each initial toggled twice (nothing seemed to happen) and Log date logged both.
def _all_viewings():
    """[(title, status, finished_on, [person ids])] for every viewing, oldest first."""
    with app.app.app_context():
        con = app.get_db()
        return [(v["title"], v["status"], v["finished_on"], [r["person_id"] for r in con.execute(
            "SELECT person_id FROM viewing_people WHERE viewing_id=? ORDER BY person_id", (v["id"],))])
            for v in con.execute("SELECT v.id, m.title, v.status, v.finished_on FROM viewings v JOIN movies m ON m.id = v.movie_id"
                                 " ORDER BY v.id").fetchall()]


def _prancer_after_elf(page):
    _elf(page)
    page.click("#back-link")
    page.click(".movie-card >> text=Prancer")
    page.wait_for_function("document.querySelector('.detail-title')?.textContent === 'Prancer'")
    page.wait_for_selector("#detail-log")


def test_the_second_movie_opened_toggles_once_and_logs_only_itself(browser, seeded):   # noqa: F811
    page, errors, calls = _open(browser, seeded, PHONE)
    _prancer_after_elf(page)
    page.click(_who("Casey"))
    assert _pressed(page) == ["Avery", "Blake", "Drew", "Emery"]                   # one tap takes Casey off
    del calls[:]
    page.fill("#detail-log-date", LAST_NIGHT)
    page.click("#detail-log")
    page.wait_for_selector(".rate-row")
    assert page.inner_text("#rate-title") == "Rate Prancer"
    page.keyboard.press("Escape")
    page.wait_for_selector(".sheet", state="detached")
    assert [c for c in calls if c[0] == "POST"] == [("POST", "api/movies/2/watched")]
    assert _all_viewings() == [("Prancer", "finished", LAST_NIGHT, [1, 2, 4, 5])]  # Elf's page logged nothing
    assert errors == []


def test_we_finished_on_one_movie_leaves_the_one_opened_before_it_alone(browser, seeded):   # noqa: F811
    with app.app.app_context():
        con = app.get_db()
        elf = app.viewings.watch_tonight(con, 1)
        con.execute("UPDATE viewings SET status='paused', started_on=?, watched_seconds=600 WHERE id=?", (LAST_NIGHT, elf))
        con.commit()
    page, errors, _ = _open(browser, seeded, PHONE)
    _prancer_after_elf(page)
    page.click("#detail-tonight")
    page.wait_for_selector("#detail-finish")
    page.click("#detail-finish")
    page.wait_for_selector(".rate-row")
    assert page.inner_text("#rate-title") == "Rate Prancer"
    page.keyboard.press("Escape")
    page.wait_for_selector(".sheet", state="detached")
    assert _status(elf) == ("paused", None)                                        # Elf is still in Continue Watching
    assert [(t, s) for t, s, _d, _p in _all_viewings()] == [("Elf", "paused"), ("Prancer", "finished")]
    assert errors == []
