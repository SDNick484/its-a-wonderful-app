"""Playwright at phone size (412 and 360 px): the Surprise button, the chips (all off to begin with, remembered per
device, the rating cap cycling), three picks in three columns, Pick Again until the pool runs out, and a pick whose
TMDB data has holes. Run by the ui-smoke job (REQUIRE_UI=1, as in test_ui_smoke.py)."""
import pytest

import app
from test_randomizer import LIBRARY, add
from test_ui_grid import _contrast, _height, _open, _side_scroll  # noqa: F401
from test_ui_smoke import PHONE, SMALL_PHONE, browser, server  # noqa: F401  (fixtures shared with the smoke tests)

BUTTON = "🎲 Surprise us, ya filthy animals"
AGAIN = "Keep the change (pick again)"
G_TITLES = {"Tinsel Town", "Nutcracker Nights"}


@pytest.fixture
def library(server):          # noqa: F811
    with app.app.app_context():
        con = app.get_db()
        for title, cert, runtime, animated in LIBRARY:
            add(con, title, cert, runtime, animated)
    return server


def _picks(page):
    return page.eval_on_selector_all("#surprise-picks .card-title", "els => els.map(e => e.textContent)")


def _chips(page):
    return page.eval_on_selector_all("#surprise-chips .chip", "els => els.map(e => [e.textContent, e.getAttribute('aria-pressed')])")


def _draw(page, selector):
    """Tap a draw button and wait for the answer to be on screen (the buttons stay disabled until it is drawn)."""
    with page.expect_response("**/api/surprise"):
        page.click(selector)
    page.wait_for_function("!document.getElementById('surprise-btn').disabled")


def _press(page):
    _draw(page, "#surprise-btn")


def _again(page):
    _draw(page, "#surprise-again")


def _chip(page, text):
    page.click(f"#surprise-chips .chip:has-text('{text}')")


def _cap(page, taps):
    """Tap the rating-cap chip `taps` times (off -> G -> PG -> PG-13 -> off) and return its label."""
    for _ in range(taps):
        page.click("#surprise-chips [data-chip='cap']")
    return page.inner_text("#surprise-chips [data-chip='cap']")


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_button_chips_and_picks_fit_the_phone(browser, library, viewport):   # noqa: F811
    page, errors = _open(browser, library, viewport)
    assert page.inner_text("#surprise-btn") == BUTTON
    assert [name for name, _ in _chips(page)] == ["Animated", "Live action", "Any rating", "Under 90 min",
                                                  "Not watched this year", "Ready to watch"]
    assert all(pressed == "false" for _, pressed in _chips(page))                 # every chip starts off
    assert page.is_hidden("#surprise-again")
    _press(page)
    cards = page.locator("#surprise-picks .movie-card")
    assert cards.count() == 3 and len(set(_picks(page))) == 3
    lefts = page.eval_on_selector_all("#surprise-picks .movie-card", "els => els.map(e => Math.round(e.getBoundingClientRect().left))")
    assert len(set(lefts)) == 3                                                    # three columns, as on the grid
    assert page.inner_text("#surprise-again") == AGAIN and page.is_visible("#surprise-again")
    assert _side_scroll(page) <= 0 and errors == []


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_tap_targets_and_contrast(browser, library, viewport):   # noqa: F811
    page, _ = _open(browser, library, viewport)
    _press(page)
    for selector in ("#surprise-btn", "#surprise-chips .chip", "#surprise-again"):
        assert _height(page, selector) >= 44, selector
    assert _contrast(page, "#surprise-btn") >= 4.5 and _contrast(page, "#surprise-again") >= 4.5
    assert _contrast(page, "#surprise-chips .chip") >= 4.5                       # off
    _chip(page, "Under 90 min")
    assert _contrast(page, "#surprise-chips .chip[aria-pressed='true']") >= 4.5   # on
    assert _contrast(page, "#surprise-status") >= 4.5
    assert page.evaluate("getComputedStyle(document.querySelector('#surprise-btn')).fontSize") == "16px"


def test_the_rating_cap_chip_cycles_and_up_to_G_shows_only_G(browser, library):   # noqa: F811
    page, _ = _open(browser, library, PHONE)
    assert [_cap(page, 1) for _ in range(4)] == ["Up to G", "Up to PG", "Up to PG-13", "Any rating"]
    assert dict(_chips(page))["Any rating"] == "false"
    assert _cap(page, 1) == "Up to G" and dict(_chips(page))["Up to G"] == "true"
    _press(page)
    assert set(_picks(page)) == G_TITLES
    assert page.inner_text("#surprise-status") == "Only 2 match. Try turning off a filter."
    assert page.is_hidden("#surprise-again")                                       # nothing more to draw


def test_animated_and_live_action_are_exclusive(browser, library):   # noqa: F811
    page, _ = _open(browser, library, PHONE)
    _chip(page, "Animated")
    assert dict(_chips(page))["Animated"] == "true" and dict(_chips(page))["Live action"] == "false"
    _press(page)
    assert set(_picks(page)) == {"Tinsel Town", "Frosty Fridays"}
    _chip(page, "Live action")
    assert dict(_chips(page))["Animated"] == "false" and dict(_chips(page))["Live action"] == "true"
    assert page.locator("#surprise-picks .movie-card").count() == 0                # a changed chip clears the picks
    _press(page)
    assert not set(_picks(page)) & {"Tinsel Town", "Frosty Fridays"}
    _chip(page, "Live action")                                                     # both off again: both kinds
    assert dict(_chips(page))["Live action"] == "false"


def test_pick_again_shows_new_ones_until_the_list_runs_out_then_says_so(browser, library):   # noqa: F811
    page, _ = _open(browser, library, PHONE)
    _press(page)
    first = _picks(page)
    _again(page)
    second = _picks(page)
    assert len(second) == 3 and not set(first) & set(second)
    assert page.inner_text("#surprise-status") == ""
    _again(page)                                                                   # 8 on the list: two left, then a restart
    third = _picks(page)
    assert len(third) == 3 and page.inner_text("#surprise-status") == "That's all of them. Starting over."
    left = {t for t, *_ in LIBRARY} - set(first) - set(second)
    assert left <= set(third)
    _again(page)                                                                   # the round after a restart is fresh
    assert not set(_picks(page)) & set(third) and page.inner_text("#surprise-status") == ""


def test_chips_are_remembered_on_this_device(browser, library):   # noqa: F811
    page, _ = _open(browser, library, PHONE)
    _chip(page, "Under 90 min")
    assert _cap(page, 2) == "Up to PG"
    assert page.evaluate("JSON.parse(localStorage.getItem('wonderful.surprise.filters'))") == {
        "animated": None, "cap": "PG", "under_90": True, "not_watched_this_year": False, "ready": False}
    page.reload()
    page.wait_for_function("document.querySelectorAll('#grid .movie-card').length > 0")
    assert dict(_chips(page)) == {"Animated": "false", "Live action": "false", "Up to PG": "true", "Under 90 min": "true",
                                  "Not watched this year": "false", "Ready to watch": "false"}
    _press(page)
    assert set(_picks(page)) == {"Tinsel Town", "Frosty Fridays"}                  # PG or under, under 90 min


def test_broken_saved_filters_start_everything_off(browser, library):   # noqa: F811
    page, errors = _open(browser, library, PHONE)
    page.evaluate("localStorage.setItem('wonderful.surprise.filters', '{\"cap\": \"R\", \"ready\": \"yes\", \"animated\": 3}')")
    page.reload()
    page.wait_for_function("document.querySelectorAll('#grid .movie-card').length > 0")
    assert all(pressed == "false" for _, pressed in _chips(page)) and errors == []


def test_blocked_storage_still_works(browser, library):   # noqa: F811
    page = browser.new_page(viewport=PHONE, is_mobile=True, has_touch=True)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script("""const boom = () => { throw new DOMException('blocked', 'SecurityError'); };
        Object.defineProperty(window, 'localStorage', { get: boom });""")
    page.goto(library + "/")
    page.wait_for_function("document.querySelectorAll('#grid .movie-card').length > 0")
    _chip(page, "Under 90 min")
    _press(page)
    assert len(_picks(page)) == 3 and errors == []


def test_a_pick_with_no_poster_runtime_or_providers_shows_a_titled_placeholder(browser, library):   # noqa: F811
    """Review Focus 2: the holes TMDB leaves still make a usable card."""
    page, errors = _open(browser, library, PHONE)
    assert _cap(page, 2) == "Up to PG"      # takes in The Quiet Reindeer: no certification reads as NR
    for _ in range(40):
        _press(page)
        if "The Quiet Reindeer" in _picks(page):
            break
    card = page.locator("#surprise-picks .movie-card", has_text="The Quiet Reindeer")
    assert card.locator(".poster-ph").inner_text() == "The Quiet Reindeer"
    assert card.locator(".card-year").count() == 0                                 # no runtime: no runtime line
    assert card.locator(".card-where").inner_text() == "Rent or buy" and errors == []


def test_a_pick_shows_runtime_and_where_to_watch_and_opens_its_detail(browser, library):   # noqa: F811
    page, _ = _open(browser, library, PHONE)
    assert _cap(page, 1) == "Up to G"
    _chip(page, "Under 90 min")
    _press(page)
    card = page.locator("#surprise-picks .movie-card")
    assert card.count() == 1
    assert card.locator(".card-year").inner_text() == "1 h 22 min" and card.locator(".card-where").inner_text()
    card.click()
    page.wait_for_function("location.hash.startsWith('#/m/')")
    page.wait_for_selector("#detail .detail-title")
    assert page.inner_text("#detail .detail-title") == "Tinsel Town"
    page.go_back()
    assert _picks(page) == ["Tinsel Town"]                                         # the picks are still there


def test_an_empty_pool_says_so(browser, library):   # noqa: F811
    page, _ = _open(browser, library, SMALL_PHONE)
    _chip(page, "Ready to watch")      # nothing here is owned, subscribed or free
    _press(page)
    assert page.inner_text("#surprise-status") == "Nothing matches. Try turning off a filter."
    assert _picks(page) == [] and page.is_hidden("#surprise-again") and _side_scroll(page) <= 0
