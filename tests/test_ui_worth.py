"""Worth a Month? at phone size (412 and 360 px): the home card in November and December only, the Settings list
always, and the no-horizontal-scroll rule. The date is pinned with app.today (the server runs in this process). Run by the
ui-smoke job (REQUIRE_UI=1). TMDB is answered from recorded fixtures."""
import datetime as dt

import pytest

import app
from test_ui_grid import _contrast, _side_scroll
from test_ui_smoke import PHONE, SMALL_PHONE, browser, server  # noqa: F401  (fixtures shared with the smoke tests)
from test_ui_providers import _open

PEACOCK_PARADE = 990001        # providers_peacock.json: on Peacock (flatrate), which the family is considering


@pytest.fixture
def seeded(server, tmdb_fixtures):          # noqa: F811
    with app.app.app_context():
        con = app.get_db()
        movie_id = con.execute("INSERT INTO movies (tmdb_id, tmdb_type, title) VALUES (?, 'movie', 'The Peacock Parade')",
                               (PEACOCK_PARADE,)).lastrowid
        con.commit()
        app.providers.get(con, movie_id)
    return server


def _pin_date(monkeypatch, day):
    monkeypatch.setattr(app, "today", lambda: day)


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_home_card_in_november_lists_the_posters_and_the_grid_still_fits(browser, seeded, monkeypatch, viewport):   # noqa: F811
    _pin_date(monkeypatch, dt.date(2026, 12, 1))
    page, errors = _open(browser, seeded, viewport)
    page.wait_for_function("!document.getElementById('worth').hidden")
    card = page.locator("#worth")
    assert "Peacock adds 1" in card.inner_text()
    assert page.locator("#worth .movie-card", has_text="The Peacock Parade").count() == 1
    assert _side_scroll(page) <= 0 and errors == []
    assert _contrast(page, "#worth .worth-line") >= 4.5


def test_home_card_is_hidden_outside_november_and_december_but_settings_still_lists(browser, seeded, monkeypatch):   # noqa: F811
    _pin_date(monkeypatch, dt.date(2027, 1, 15))
    page, errors = _open(browser, seeded, PHONE)
    page.wait_for_function("document.getElementById('worth-list') !== null")
    assert page.locator("#worth").is_hidden()
    page.goto(seeded + "/#/settings")
    page.wait_for_selector("#worth-box .worth-line")
    assert "Peacock adds 1" in page.inner_text("#worth-box")
    assert "Paramount+ adds 0" in page.inner_text("#worth-box")
    assert _side_scroll(page) <= 0 and errors == []
