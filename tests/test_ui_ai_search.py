"""Playwright at phone size (412 and 360 px) for smart search (spec §9, plan Task 12): Enter on a description shows the
matches with their reasons and a "Not on our list yet" section, a suggestion is added only by tapping its button, and a
search with smart search off says so. Anthropic and TMDB answer from the recorded fixtures (the server runs in this
process, so the patched urlopen is the one it uses). Run by the ui-smoke job (REQUIRE_UI=1, as in test_ui_smoke.py)."""
import urllib.request

import pytest

import app
from conftest import ANTHROPIC_KEY, TMDB_TOKEN, FakeAnthropic, FakeTmdb
from test_ai_search import LIBRARY, load
from test_ui_grid import _contrast, _height, _open, _side_scroll  # noqa: F401
from test_ui_smoke import PHONE, SMALL_PHONE, browser, server  # noqa: F401  (fixtures shared with the smoke tests)

JESUS = "a movie about Jesus"


@pytest.fixture
def smart(server, monkeypatch):   # noqa: F811
    monkeypatch.setattr(app, "TMDB_READ_TOKEN", TMDB_TOKEN)
    monkeypatch.setattr(app, "ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    fake = FakeAnthropic(FakeTmdb())
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    with app.app.app_context():
        load(app.get_db())
    return server, fake


def _titles(page):
    return page.eval_on_selector_all("#grid .card-title", "els => els.map(e => e.textContent)")


def _search(page, q):
    page.fill("#search-input", q)
    page.press("#search-input", "Enter")


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_smart_search_shows_matches_with_reasons_and_suggestions_to_add(browser, smart, viewport):   # noqa: F811
    page, errors = _open(browser, smart[0], viewport)
    _search(page, JESUS)
    page.wait_for_selector("#suggest:not([hidden])")
    assert _titles(page) == ["The Star"]
    assert page.inner_text("#grid .card-why") == "the Nativity story, told by the animals"
    assert page.inner_text("#search-status") == f'1 movie on our list fit "{JESUS}"'
    assert page.inner_text("#suggest-title") == "Not on our list yet"
    assert page.inner_text("#suggest-list .add-name") == "The Nativity Story"
    assert page.inner_text("#suggest-list .add-kind") == "2006 · Movie"
    assert page.inner_text("#suggest-list .add-why") == "Mary and Joseph's journey to Bethlehem, played straight"
    assert _height(page, "#suggest-list .btn") >= 44 and page.inner_text("#suggest-list .btn") == "Add to our list"
    assert _contrast(page, ".card-why") >= 4.5 and _contrast(page, "#suggest-list .add-why") >= 4.5
    assert _side_scroll(page) <= 0 and errors == []
    assert len(smart[1].calls) == 1


def test_nothing_is_added_until_the_button_is_tapped(browser, smart):   # noqa: F811
    page, _ = _open(browser, smart[0], PHONE)
    _search(page, JESUS)
    page.wait_for_selector("#suggest:not([hidden])")
    with app.app.app_context():
        assert app.get_db().execute("SELECT COUNT(*) FROM movies").fetchone()[0] == len(LIBRARY)
    page.click("#suggest-list .btn")
    page.wait_for_selector("#suggest[hidden]", state="attached")
    assert sorted(_titles(page)) == ["The Nativity Story", "The Star"]
    assert "Added The Nativity Story." in page.inner_text("#toast")
    with app.app.app_context():
        assert app.get_db().execute("SELECT COUNT(*) FROM movies").fetchone()[0] == len(LIBRARY) + 1


def test_typing_again_clears_the_reasons_and_the_suggestions(browser, smart):   # noqa: F811
    page, _ = _open(browser, smart[0], PHONE)
    _search(page, JESUS)
    page.wait_for_selector("#suggest:not([hidden])")
    page.fill("#search-input", "")
    assert page.is_hidden("#suggest") and page.locator(".card-why").count() == 0 and len(_titles(page)) == len(LIBRARY)


def test_with_no_key_enter_shows_the_list_filter_and_says_smart_search_is_off(browser, smart, monkeypatch):   # noqa: F811
    monkeypatch.setattr(app, "ANTHROPIC_API_KEY", "")
    page, _ = _open(browser, smart[0], SMALL_PHONE)
    _search(page, "christmas")
    page.wait_for_function("document.getElementById('search-status').textContent.includes('Smart search is off')")
    assert page.inner_text("#search-status") == '2 movies match "christmas". Smart search is off right now.'
    assert sorted(_titles(page)) == ["The Muppet Christmas Carol", "White Christmas"]
    assert page.is_hidden("#suggest") and smart[1].calls == []
