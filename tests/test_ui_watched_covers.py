"""Playwright at phone size (412 and 360 px): on the grid, the cover of a movie watched this year is greyed out and the
card still opens the movie; the words on the card (title, year, the star, a placeholder's title) stay readable; and a
night logged, finished or deleted on the detail view shows on the card behind it. Run by the ui-smoke job
(REQUIRE_UI=1). TMDB answers from fixtures. The host says it is 2026-12-05, whatever the browser's clock says."""
import datetime as dt

import pytest

import app
from test_continue_ui import _finished, _open, _solid
from test_rating_ui import _toast
from test_ui_grid import _contrast, _side_scroll, seeded  # noqa: F401  (Elf, Prancer, The Quiet Reindeer with no poster, a TV special)
from test_ui_smoke import PHONE, SMALL_PHONE, browser, server  # noqa: F401  (fixtures shared with the smoke tests)

ELF, PRANCER, QUIET = 1, 2, 3


@pytest.fixture(autouse=True)
def host_day(monkeypatch):
    monkeypatch.setattr(app, "today", lambda: dt.date(2026, 12, 5))


def _card(title):
    return f"#grid .movie-card[aria-label^='{title}']"


def _greyed(page):
    return page.eval_on_selector_all("#grid .movie-card.watched .card-title", "els => els.map(e => e.textContent)")


def _drawn(page, sel):
    """[opacity, filtered]: the opacity an element is drawn with (its own times its ancestors') and whether it or an
    ancestor has a filter on it."""
    return page.evaluate("""(s) => { let o = 1, f = false;
        for (let e = document.querySelector(s); e; e = e.parentElement) {
          const st = getComputedStyle(e); o *= parseFloat(st.opacity); f = f || st.filter !== 'none'; }
        return [o, f]; }""", sel)


def _color(page, sel):
    return page.evaluate("(s) => getComputedStyle(document.querySelector(s)).color", sel)


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_a_movie_watched_this_year_has_a_greyed_cover_and_still_opens(browser, seeded, viewport):   # noqa: F811
    with app.app.app_context():
        con = app.get_db()
        app.people.add_person(con, {"name": "Avery", "kind": "adult", "color": "green"})
        con.execute("INSERT INTO person_ratings (person_id, movie_id, rating) VALUES (1, ?, 9)", (ELF,))
        con.commit()
    page, errors, _ = _open(browser, seeded, viewport)
    assert _greyed(page) == []                                                     # nothing watched yet: no grey covers
    plain = _color(page, _card("The Quiet Reindeer") + " .poster-ph")
    _finished(ELF, "2026-12-04", [])                                               # last night
    _finished(QUIET, "2026-01-01", [])                                             # New Year's Day: still this year
    _finished(PRANCER, "2025-12-31", [])                                           # last year: not greyed
    page.reload()
    page.wait_for_function("document.getElementById('grid-empty').textContent !== 'Loading…'")
    page.wait_for_function("[...document.querySelectorAll('.poster-img')].every(i => i.complete)")
    assert _greyed(page) == ["Elf", "The Quiet Reindeer"]
    opacity, filtered = _drawn(page, _card("Elf") + " .poster-img")
    assert opacity <= 0.6 and filtered                                             # the cover: dimmed, and drained of colour
    assert _drawn(page, _card("Prancer") + " .poster-img") == [1, False]
    assert page.get_attribute(_card("Elf"), "aria-label") == "Elf (2003), watched this year"
    assert page.get_attribute(_card("Prancer"), "aria-label") == "Prancer (1989)"
    for part in (" .card-title", " .card-year", " .star"):                         # the words are not greyed with it
        assert _drawn(page, _card("Elf") + part) == [1, False], part
    for part in (" .card-title", " .card-year"):
        _solid(page, _card("Elf") + part)
        assert _contrast(page, _card("Elf") + part) >= 4.5, part
    ph = _card("The Quiet Reindeer") + " .poster-ph"                               # no poster: its title is the cover
    assert _color(page, ph) != plain and _drawn(page, ph) == [1, False]
    page.evaluate("(s) => { document.querySelector(s).style.background = 'var(--ph-from)'; }", ph)   # the lighter end
    assert _contrast(page, ph) >= 4.5
    assert _side_scroll(page) <= 0
    page.click(_card("Elf"))                                                       # greyed, not disabled
    page.wait_for_selector(".detail-title")
    assert page.inner_text(".detail-title") == "Elf" and errors == []


def test_logging_then_deleting_a_night_greys_then_clears_the_card_behind(browser, seeded):   # noqa: F811
    page, errors, _ = _open(browser, seeded, PHONE)
    page.click(_card("Prancer"))
    page.wait_for_selector("#detail-log")
    page.fill("#detail-log-date", "2026-12-04")
    page.click("#detail-log")
    _toast(page, "Logged")
    page.wait_for_selector(".sheet")                                               # the rating sheet: close it
    page.keyboard.press("Escape")
    page.wait_for_selector(".sheet", state="detached")
    page.click("#back-link")
    page.wait_for_selector(_card("Prancer") + ".watched")
    assert _greyed(page) == ["Prancer"]
    page.click(_card("Prancer"))
    page.click(".watched-delete")
    page.click("#watched-delete [data-act=delete]")
    _toast(page, "Viewing deleted")
    page.click("#back-link")
    page.wait_for_selector(_card("Prancer"))
    assert _greyed(page) == [] and errors == []


def test_we_finished_greys_the_card_behind(browser, seeded):   # noqa: F811
    page, errors, _ = _open(browser, seeded, PHONE)
    page.click(_card("Elf"))
    page.click("#detail-tonight")
    page.click("#detail-finish")
    page.wait_for_selector(".sheet")
    page.keyboard.press("Escape")
    page.wait_for_selector(".watched-row")
    page.click("#back-link")
    page.wait_for_selector(_card("Elf") + ".watched")
    assert _greyed(page) == ["Elf"] and errors == []
