"""Playwright at phone size (412 and 360 px): the where-to-watch line on each card, the detail view's lines, and the
Settings -> Subscriptions screen. Run by the ui-smoke job (REQUIRE_UI=1). TMDB is answered from recorded fixtures."""
import pytest

import app
from test_ui_grid import _contrast, _height, _side_scroll
from test_ui_smoke import PHONE, SMALL_PHONE, browser, server  # noqa: F401  (fixtures shared with the smoke tests)

LIST = [(10719, "movie"), (14181, "movie"), (900001, "movie")]      # Elf: free with ads; Prancer: no providers fixture; Quiet Reindeer: none for US


@pytest.fixture
def seeded(server, tmdb_fixtures):          # noqa: F811
    with app.app.app_context():
        con = app.get_db()
        for tmdb_id, tmdb_type in LIST:
            movie_id = app.movies.add_movie(con, tmdb_id, tmdb_type, "test")
            try:
                app.providers.get(con, movie_id)
            except app.TmdbError:
                pass                         # Prancer has no providers fixture: it stays "Rent or buy"
        peacock = con.execute("INSERT INTO movies (tmdb_id, tmdb_type, title) VALUES (990001, 'movie', 'The Peacock Parade')").lastrowid
        con.commit()
        app.providers.get(con, peacock)
    return server


def _open(browser, url, viewport, path="/"):       # noqa: F811
    page = browser.new_page(viewport=viewport, device_scale_factor=2.625, is_mobile=True, has_touch=True)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url + path)
    page.wait_for_function("document.getElementById('grid-empty').textContent !== 'Loading…'")
    return page, errors


def _where(page, title):
    return page.locator(".movie-card", has_text=title).locator(".card-where").inner_text()


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_cards_show_where_to_watch_and_the_grid_still_fits(browser, seeded, viewport):   # noqa: F811
    page, errors = _open(browser, seeded, viewport)
    assert _where(page, "Elf") == "Free with ads on The Roku Channel"
    assert _where(page, "The Peacock Parade") == "On Peacock (you don't have it)"
    assert _where(page, "Prancer") == "Rent or buy"
    lefts = page.evaluate("[...document.querySelectorAll('#grid .movie-card')].slice(0, 3).map(c => Math.round(c.getBoundingClientRect().left))")
    assert len(set(lefts)) == 3 and _side_scroll(page) <= 0 and errors == []
    assert page.evaluate("[...document.querySelectorAll('.card-where')].every(e => e.scrollWidth <= e.clientWidth + 1)")
    for sel in (".card-where[data-kind=free]", ".card-where[data-kind=considering]", ".card-where[data-kind=rent_buy]"):
        assert _contrast(page, sel) >= 4.5, sel


def test_detail_lists_every_place_and_credits_justwatch(browser, seeded):   # noqa: F811
    page, errors = _open(browser, seeded, PHONE)
    page.click(".movie-card >> text=Elf")
    page.wait_for_selector(".where-line")
    assert page.eval_on_selector_all(".where-line", "els => els.map(e => e.textContent)") == [
        "Free with ads on The Roku Channel", "On HBO Max (you don't have it)", "Rent or buy"]
    assert "Data from JustWatch" in page.inner_text(".where-credit")
    assert page.get_attribute(".where-credit a", "href").startswith("https://www.themoviedb.org/")
    assert _height(page, "#detail-refresh") >= 44 and _height(page, ".where-credit a") >= 44
    assert _side_scroll(page) <= 0 and errors == []


def test_check_again_asks_tmdb_and_updates_the_line_and_the_card(browser, seeded, tmdb_fixtures):   # noqa: F811
    page, _ = _open(browser, seeded, PHONE)
    page.click(".movie-card >> text=Elf")
    page.wait_for_selector(".where-line")
    tmdb_fixtures.provider_files[10719] = "providers_klaus.json"
    page.click("#detail-refresh")
    page.wait_for_function("document.querySelector('.where-line')?.textContent === 'On Netflix'")
    page.click("#back-link")
    assert _where(page, "Elf") == "On Netflix"


def test_a_stale_answer_is_refreshed_when_the_detail_opens(browser, seeded, tmdb_fixtures):   # noqa: F811
    with app.app.app_context():
        con = app.get_db()
        con.execute("UPDATE providers_cache SET fetched_at='2020-01-01T00:00:00Z'")
        con.commit()
    tmdb_fixtures.provider_files[10719] = "providers_klaus.json"
    page, _ = _open(browser, seeded, PHONE)
    page.click(".movie-card >> text=Elf")
    page.wait_for_function("document.querySelector('.where-line')?.textContent === 'On Netflix'")


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_settings_lists_services_with_three_way_toggles(browser, seeded, viewport):   # noqa: F811
    page, errors = _open(browser, seeded, viewport)
    assert _height(page, "#settings-btn") >= 44 and page.evaluate("document.querySelector('#settings-btn').getBoundingClientRect().width") >= 44
    page.click("#settings-btn")
    page.wait_for_selector(".svc")
    assert page.url.endswith("#/settings") and page.is_hidden("#grid-view")
    assert page.inner_text("#settings .section-title") == "Settings" and "Subscriptions" in page.inner_text("#settings")
    names = page.eval_on_selector_all(".svc-name", "els => els.map(e => e.textContent)")
    assert names == ["Netflix", "Disney+", "Hulu", "Prime Video", "Fandango at Home", "YouTube TV",
                     "HBO Max", "Peacock", "Paramount+", "Apple TV"]
    pressed = page.eval_on_selector_all(".svc", "els => els.map(e => e.querySelector('[aria-pressed=true]').textContent)")
    assert pressed == ["Subscribed"] * 6 + ["Considering"] * 4
    assert page.locator(".svc").first.locator(".seg-btn").count() == 3
    for sel in (".seg-btn", "#settings-back"):
        assert page.evaluate("(s) => [...document.querySelectorAll(s)].every(e => e.getBoundingClientRect().height >= 44)", sel), sel
    assert _side_scroll(page) <= 0 and errors == []
    assert page.evaluate("[...document.querySelectorAll('.header-inner > *')].every(e => e.getBoundingClientRect().right <= innerWidth)")
    for sel in (".seg-btn[aria-pressed=true]", ".seg-btn[aria-pressed=false]", ".settings-hint"):
        page.evaluate("(s) => { const e = document.querySelector(s);"
                      " if (!getComputedStyle(e).backgroundColor.match(/[1-9]/)) e.style.backgroundColor = '#0b0b0e'; }", sel)
        assert _contrast(page, sel) >= 4.5, sel


def test_subscribing_changes_the_card_and_survives_a_reload(browser, seeded):   # noqa: F811
    page, _ = _open(browser, seeded, PHONE)
    page.click("#settings-btn")
    page.wait_for_selector(".svc")
    peacock = page.locator(".svc", has_text="Peacock")
    peacock.get_by_role("button", name="Subscribed").click()
    page.wait_for_function("document.querySelector('.movie-card:nth-child(3) .card-where')?.textContent === 'On Peacock'")
    page.click("#settings-back")
    page.wait_for_selector("#grid-view", state="visible")
    assert _where(page, "The Peacock Parade") == "On Peacock"
    assert page.locator(".movie-card", has_text="The Peacock Parade").locator(".card-where").get_attribute("data-kind") == "subscribed"
    page.reload()
    page.wait_for_selector(".card-where")
    assert _where(page, "The Peacock Parade") == "On Peacock"
    page.goto(seeded + "/#/settings")
    page.reload()
    page.wait_for_selector(".svc")
    assert peacock.get_by_role("button", name="Subscribed").get_attribute("aria-pressed") == "true"


def test_ignore_hides_a_service_and_a_failed_save_puts_the_button_back(browser, seeded, monkeypatch):   # noqa: F811
    page, _ = _open(browser, seeded, PHONE)
    page.click("#settings-btn")
    page.wait_for_selector(".svc")
    page.locator(".svc", has_text="Peacock").get_by_role("button", name="Ignore").click()
    page.wait_for_function("document.querySelector('.movie-card:nth-child(3) .card-where')?.textContent === 'Rent or buy'")
    page.route("**/api/services", lambda route: route.fulfill(status=500, content_type="application/json", body='{"error": "disk full"}')
               if route.request.method == "PUT" else route.continue_())
    page.locator(".svc", has_text="Hulu").get_by_role("button", name="Considering").click()
    page.wait_for_function("document.getElementById('toast').textContent.includes('disk full')")
    assert page.locator(".svc", has_text="Hulu").get_by_role("button", name="Subscribed").get_attribute("aria-pressed") == "true"
