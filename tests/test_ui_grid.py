"""Playwright at phone size (412 and 360 px): the grid of real movies, the detail view and the add sheet. Run by the
ui-smoke job (REQUIRE_UI=1 turns a missing browser into a failure, as in test_ui_smoke.py). TMDB is answered from
recorded fixtures; the browser only ever talks to the app."""
import pytest

import app
from test_ui_smoke import PHONE, SMALL_PHONE, browser, server  # noqa: F401  (fixtures shared with the smoke tests)

LIST = [(10719, "movie"), (14181, "movie"), (900001, "movie"), (900002, "tv")]   # Elf, Prancer, no poster, a TV special


@pytest.fixture
def seeded(server, tmdb_fixtures):          # noqa: F811
    with app.app.app_context():
        for tmdb_id, tmdb_type in LIST:
            app.movies.add_movie(app.get_db(), tmdb_id, tmdb_type, "test")
    return server


def _open(browser, url, viewport):       # noqa: F811
    page = browser.new_page(viewport=viewport, device_scale_factor=2.625, is_mobile=True, has_touch=True)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url + "/")
    page.wait_for_function("document.getElementById('grid-empty').textContent !== 'Loading…'")
    return page, errors


def _side_scroll(page):
    return page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")


def _lefts(page):
    return page.evaluate("[...document.querySelectorAll('#grid .movie-card')].map(c => Math.round(c.getBoundingClientRect().left))")


def _height(page, selector):
    return page.evaluate("(s) => document.querySelector(s).getBoundingClientRect().height", selector)


def _luminance(rgb):
    def chan(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(page, selector):
    """WCAG contrast of an element's text colour on its own (solid) background colour."""
    fg, bg = page.evaluate("""(s) => { const st = getComputedStyle(document.querySelector(s));
        const n = c => c.match(/[\\d.]+/g).slice(0, 3).map(Number); return [n(st.color), n(st.backgroundColor)]; }""", selector)
    hi, lo = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_grid_of_real_movies_has_three_columns_and_no_side_scroll(browser, seeded, viewport):   # noqa: F811
    page, errors = _open(browser, seeded, viewport)
    assert len(_lefts(page)) == 4
    assert len(set(_lefts(page)[:3])) == 3 and _lefts(page)[3] == _lefts(page)[0]     # three columns, the fourth wraps
    assert _side_scroll(page) <= 0 and errors == []
    titles = page.eval_on_selector_all("#grid .card-title", "els => els.map(e => e.textContent)")
    assert titles == ["Elf", "Prancer", "The Quiet Reindeer", "The Tinsel Express"]


def test_posters_load_and_a_missing_one_is_a_titled_placeholder(browser, seeded):   # noqa: F811
    page, _ = _open(browser, seeded, PHONE)
    page.wait_for_function("[...document.querySelectorAll('.poster-img')].every(i => i.complete)")
    assert page.evaluate("[...document.querySelectorAll('.poster-img')].map(i => i.naturalWidth > 0)") == [True, True, True]
    quiet = page.locator(".movie-card", has_text="The Quiet Reindeer")
    assert quiet.locator(".poster-img").count() == 0 and quiet.locator(".poster-ph").inner_text() == "The Quiet Reindeer"


def test_a_poster_that_fails_to_load_becomes_the_placeholder(browser, seeded):   # noqa: F811
    (app.POSTER_DIR / "movie-10719-w342.jpg").unlink()          # the row still points at it
    page, _ = _open(browser, seeded, PHONE)
    page.wait_for_function("document.querySelector('.movie-card .poster-ph')")
    assert page.locator(".movie-card", has_text="Elf").locator(".poster-ph").inner_text() == "Elf"


def test_detail_view_shows_the_movie_and_goes_back(browser, seeded):   # noqa: F811
    page, errors = _open(browser, seeded, PHONE)
    page.click(".movie-card >> text=Elf")
    page.wait_for_selector("#detail .detail-title")
    assert page.inner_text("#detail .detail-title") == "Elf" and not page.is_visible("#grid")
    assert page.inner_text(".detail-meta") == "2003 · PG · 1 h 37 min"
    assert "Will Ferrell" in page.inner_text(".detail-cast") and "Kyle Gass" not in page.inner_text(".detail-cast")
    assert page.is_visible(".detail-backdrop img") and page.inner_text(".detail-overview")
    assert _side_scroll(page) <= 0 and page.url.endswith("#/m/1")
    page.click("#back-link")
    page.wait_for_selector("#grid .movie-card")
    assert page.is_visible("#grid") and not page.is_visible("#detail") and errors == []


def test_detail_with_holes(browser, seeded):   # noqa: F811
    page, _ = _open(browser, seeded, SMALL_PHONE)
    page.click(".movie-card >> text=The Quiet Reindeer")
    page.wait_for_selector("#detail .detail-title")
    assert page.inner_text(".detail-meta") == "NR"                       # no year, no runtime
    assert page.inner_text(".detail-collection") == "Part of The Quiet Reindeer Collection"
    assert page.locator(".detail-cast").count() == 0 and page.locator(".detail-backdrop").count() == 0
    assert page.locator(".detail-poster .poster-ph").inner_text() == "The Quiet Reindeer"
    assert _side_scroll(page) <= 0


def test_parent_note_and_certification_are_editable(browser, seeded):   # noqa: F811
    page, _ = _open(browser, seeded, PHONE)
    page.click(".movie-card >> text=Elf")
    page.fill("#detail-note", "Some fake snow")
    page.click("#detail-save")
    page.wait_for_function("document.getElementById('toast').textContent.includes('Note saved')")
    page.select_option("#detail-cert", "PG-13")
    page.wait_for_function("document.getElementById('toast').textContent.includes('PG-13')")
    page.reload()
    page.wait_for_selector("#detail .detail-title")
    assert page.input_value("#detail-note") == "Some fake snow" and page.input_value("#detail-cert") == "PG-13"
    assert page.inner_text(".detail-meta") == "2003 · PG-13 · 1 h 37 min"
    for sel in ("#detail-save", "#detail-remove", "#detail-cert", "#detail-note", "#back-link"):
        assert _height(page, sel) >= 44, sel


def test_remove_asks_first_and_takes_the_card_away(browser, seeded):   # noqa: F811
    page, _ = _open(browser, seeded, PHONE)
    page.click(".movie-card >> text=Elf")
    page.once("dialog", lambda d: d.dismiss())
    page.click("#detail-remove")
    assert page.is_visible("#detail .detail-title")                  # cancelled: still there
    page.once("dialog", lambda d: d.accept())
    page.click("#detail-remove")
    page.wait_for_selector("#grid .movie-card")
    assert page.locator("#grid .movie-card").count() == 3 and page.locator(".movie-card", has_text="Elf").count() == 0


def test_add_prancer_from_the_plus_button(browser, server, tmdb_fixtures):   # noqa: F811
    page, errors = _open(browser, server, PHONE)
    assert page.is_visible("#grid-empty")
    assert _height(page, "#add-btn") >= 44 and page.evaluate("document.querySelector('#add-btn').getBoundingClientRect().width") >= 44
    page.click("#add-btn")
    page.wait_for_selector(".sheet-panel")
    assert _height(page, "#add-q") >= 44 and "not endorsed or certified by TMDB" in page.inner_text(".sheet-panel")
    page.fill("#add-q", "Prancer")
    page.wait_for_selector(".add-row")
    assert page.locator(".add-row").count() == 3 and "Prancer" in page.inner_text(".add-row")
    assert _height(page, ".add-row .btn") >= 44 and _side_scroll(page) <= 0
    page.click(".add-row >> nth=0 >> text=Add to our list")
    page.wait_for_selector("#grid .movie-card")
    assert not page.is_visible(".sheet-panel")
    assert page.inner_text("#grid .card-title") == "Prancer" and page.inner_text("#grid .card-year") == "1989"
    page.wait_for_function("document.querySelector('#grid .poster-img')?.complete")
    assert page.evaluate("document.querySelector('#grid .poster-img').naturalWidth") > 0
    assert page.is_hidden("#grid-empty") and errors == []
    # searching again shows it is on the list, not addable twice
    page.click("#add-btn")
    page.fill("#add-q", "Prancer")
    page.wait_for_selector(".add-row")
    assert page.locator(".add-row >> text=On our list").count() == 1 and page.locator(".add-row .btn >> text=Add to our list").count() == 2


def test_search_with_no_match_says_so_and_a_tmdb_failure_is_explained(browser, server, tmdb_fixtures, monkeypatch):   # noqa: F811
    page, _ = _open(browser, server, PHONE)
    page.click("#add-btn")
    page.fill("#add-q", "zzzz")
    page.wait_for_selector(".add-note")
    assert page.inner_text(".add-note") == 'TMDB has nothing called "zzzz".'
    monkeypatch.setattr(app, "TMDB_READ_TOKEN", "")
    page.fill("#add-q", "elf")
    page.wait_for_function("document.querySelector('.add-note')?.textContent.includes('TMDB_READ_TOKEN')")
    page.keyboard.press("Escape")
    assert not page.is_visible(".sheet-panel")


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_add_sheet_fits_the_phone(browser, server, tmdb_fixtures, viewport):   # noqa: F811
    page, _ = _open(browser, server, viewport)
    page.click("#add-btn")
    page.fill("#add-q", "Prancer")
    page.wait_for_selector(".add-row")
    assert _side_scroll(page) <= 0
    assert page.evaluate("document.querySelector('.sheet-panel').scrollWidth <= document.querySelector('.sheet-panel').clientWidth")


def test_button_text_has_aa_contrast(browser, seeded):   # noqa: F811
    page, _ = _open(browser, seeded, PHONE)
    assert _contrast(page, "#add-btn") >= 4.5
    page.click(".movie-card >> text=Elf")
    page.wait_for_selector("#detail-save")
    for sel in ("#detail-save", "#detail-remove", ".detail-meta", ".back-link"):
        page.evaluate("(s) => { const e = document.querySelector(s);"
                      " if (!getComputedStyle(e).backgroundColor.match(/[1-9]/)) e.style.backgroundColor = '#0b0b0e'; }", sel)
        assert _contrast(page, sel) >= 4.5, sel
