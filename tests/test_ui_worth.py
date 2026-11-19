"""Worth a Month? as its own top tab (spec §13) at phone size (412 and 360 px): the header link fits, the tab lists the
services with posters, the grid and Settings no longer carry a copy, and the route keeps the grid's scroll. Run by the
ui-smoke job (REQUIRE_UI=1). TMDB is answered from recorded fixtures."""
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


def _header_fits(page):
    """The header's controls sit on one row inside the screen, with no sideways scroll."""
    return page.evaluate("""() => {
        const row = [...document.querySelectorAll('#worth-btn, #settings-btn, #add-btn')].map(e => e.getBoundingClientRect());
        return row.every(r => r.right <= window.innerWidth && Math.abs(r.top - row[0].top) < 2) && row.every(r => r.height >= 44);
    }""")


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_header_link_is_visible_fits_and_the_short_label_shows_under_400px(browser, seeded, viewport):   # noqa: F811
    page, errors = _open(browser, seeded, viewport)
    link = page.locator("#worth-btn")
    assert link.is_visible() and link.get_attribute("aria-label") == "Worth a Month?"
    assert _header_fits(page) and _side_scroll(page) <= 0 and errors == []
    expected = "Worth it?" if viewport["width"] < 400 else "Worth a Month?"
    assert link.inner_text() == expected
    assert _contrast(page, "#worth-btn") >= 4.5


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_tab_lists_the_service_with_posters_and_a_poster_opens_the_movie(browser, seeded, viewport):   # noqa: F811
    page, errors = _open(browser, seeded, viewport)
    page.click("#worth-btn")
    page.wait_for_selector("#worth-view:not([hidden]) .worth-service")
    assert page.is_hidden("#grid-view") and page.is_visible("#worth-view")
    assert page.title() == "Worth a Month? · It's a Wonderful App"
    assert page.get_attribute("#worth-btn", "aria-current") == "page"
    assert "Peacock adds 1" in page.inner_text("#worth-list")
    assert "Paramount+ adds 0" in page.inner_text("#worth-list")
    assert page.locator("#worth-list .movie-card", has_text="The Peacock Parade").count() == 1
    assert _contrast(page, "#worth-view .worth-line") >= 4.5
    assert _side_scroll(page) <= 0 and errors == []
    page.click("#worth-list .movie-card >> text=The Peacock Parade")
    page.wait_for_function("location.hash.startsWith('#/m/') && document.getElementById('detail').innerText.includes('The Peacock Parade')")
    assert page.is_hidden("#worth-view") and page.is_visible("#detail-view") and errors == []


def test_no_worth_card_on_the_grid_and_no_section_in_settings(browser, seeded):   # noqa: F811
    page, errors = _open(browser, seeded, PHONE)
    assert page.locator("#worth").count() == 0 and page.locator("#worth-box").count() == 0
    assert page.is_visible("#grid-view") and page.get_attribute("#worth-btn", "aria-current") is None
    page.goto(seeded + "/#/settings")
    page.wait_for_selector(".svc-list")
    assert "Worth a Month?" not in page.inner_text("#settings")
    assert errors == []


def test_worth_is_fetched_only_when_its_tab_opens(browser, seeded):   # noqa: F811
    page, _ = _open(browser, seeded, PHONE)
    requests = []
    page.on("request", lambda r: requests.append(r.url) if "/api/worth" in r.url else None)
    page.goto(seeded + "/#/settings")
    page.wait_for_selector(".svc-list")
    page.goto(seeded + "/#/")
    page.wait_for_selector("#grid-view:not([hidden])")
    assert requests == []
    page.click("#worth-btn")
    page.wait_for_selector("#worth-view:not([hidden]) .worth-service")
    assert len(requests) == 1


def test_going_back_to_the_grid_restores_its_scroll_position(browser, seeded):   # noqa: F811
    page, errors = _open(browser, seeded, PHONE)
    page.evaluate("document.body.style.minHeight = '3000px'; window.scrollTo(0, 400)")
    page.click("#worth-btn")
    page.wait_for_selector("#worth-view:not([hidden])")
    page.click("#worth-back")
    page.wait_for_selector("#grid-view:not([hidden])")
    assert page.evaluate("Math.round(window.scrollY)") == 400
    assert errors == []
