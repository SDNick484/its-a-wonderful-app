"""Playwright at phone size (412 and 360 px): the search box filters the grid as you type, Enter shows an exact
title, and the box is a usable tap target. Run by the ui-smoke job (REQUIRE_UI=1, as in test_ui_smoke.py)."""
import pytest

import app
from test_search_local import LIBRARY, load
from test_ui_grid import _contrast, _height, _open, _side_scroll  # noqa: F401
from test_ui_smoke import PHONE, SMALL_PHONE, browser, server  # noqa: F401  (fixtures shared with the smoke tests)

TIM_ALLEN = ["The Santa Clause", "The Santa Clause 2", "Christmas with the Kranks"]


@pytest.fixture
def library(server):          # noqa: F811
    with app.app.app_context():
        load(app.get_db())
    return server


def _titles(page):
    return page.eval_on_selector_all("#grid .card-title", "els => els.map(e => e.textContent)")


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_typing_filters_the_grid_by_actor(browser, library, viewport):   # noqa: F811
    page, errors = _open(browser, library, viewport)
    assert len(_titles(page)) == len(LIBRARY)
    page.fill("#search-input", "tim allen")
    assert sorted(_titles(page)) == sorted(TIM_ALLEN)
    assert page.inner_text("#search-status") == '3 movies match "tim allen"'
    assert _side_scroll(page) <= 0 and errors == []


def test_enter_on_an_exact_title_shows_that_movie(browser, library):   # noqa: F811
    page, _ = _open(browser, library, PHONE)
    page.fill("#search-input", "the santa clause")
    page.press("#search-input", "Enter")
    page.wait_for_function("document.querySelectorAll('#grid .movie-card').length === 1")
    assert _titles(page) == ["The Santa Clause"]
    assert page.inner_text("#search-status") == 'Exact title match for "the santa clause"'


def test_clearing_the_box_shows_the_whole_list_again(browser, library):   # noqa: F811
    page, _ = _open(browser, library, PHONE)
    page.fill("#search-input", "elf")
    assert _titles(page) == ["Elf"]
    page.fill("#search-input", "")
    assert len(_titles(page)) == len(LIBRARY) and page.inner_text("#search-status") == ""


def test_no_match_says_so(browser, library):   # noqa: F811
    page, _ = _open(browser, library, SMALL_PHONE)
    page.fill("#search-input", "zzz nothing")
    assert _titles(page) == []
    assert page.inner_text("#grid-empty") == "Nothing on our list matches that."
    assert _side_scroll(page) <= 0


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_search_box_is_a_tap_target_and_readable(browser, library, viewport):   # noqa: F811
    page, _ = _open(browser, library, viewport)
    assert _height(page, "#search-input") >= 44
    assert page.evaluate("getComputedStyle(document.querySelector('#search-input')).fontSize") == "16px"
    page.fill("#search-input", "tim allen")
    assert _contrast(page, "#search-status") >= 4.5
