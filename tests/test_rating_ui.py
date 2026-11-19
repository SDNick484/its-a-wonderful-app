"""Playwright at phone size (412 and 360 px): the rating sheet (number buttons 1-10 and ½, 44 px or more, two rows),
rating a movie for everyone, the star on the poster and the dot row on the detail view, and Settings -> People. Run by the
ui-smoke job (REQUIRE_UI=1). TMDB is answered from recorded fixtures; the people have made-up names."""
import pytest

import app
from test_ui_grid import _contrast, _height, _side_scroll
from test_ui_smoke import PHONE, SMALL_PHONE, browser, server  # noqa: F401  (fixtures shared with the smoke tests)

FAMILY = [("Avery", "adult", "green"), ("Blake", "adult", "blue"), ("Casey", "kid", "red"), ("Drew", "kid", "pink"),
          ("Emery", "adult", "purple")]


@pytest.fixture
def seeded(server, tmdb_fixtures):          # noqa: F811
    """Elf and Prancer on the list, and five people."""
    with app.app.app_context():
        con = app.get_db()
        for tmdb_id in (10719, 14181):
            app.movies.add_movie(con, tmdb_id, "movie", "test")
        for name, kind, color in FAMILY:
            app.people.add_person(con, {"name": name, "kind": kind, "color": color})
    return server


def _open(browser, url, viewport, path="/"):       # noqa: F811
    page = browser.new_page(viewport=viewport, device_scale_factor=2.625, is_mobile=True, has_touch=True)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url + path)
    page.wait_for_function("document.getElementById('grid-empty').textContent !== 'Loading…'")
    return page, errors


def _rate_sheet(page):
    page.click(".movie-card >> text=Elf")
    page.click("#detail-rate")
    page.wait_for_selector(".rate-row")


def _tap(page, person, label):
    """Tap the number (or ½) button in a person's row."""
    page.locator(f".rate-row:has-text('{person}') .rate-btn", has_text=label).first.click()


def _toast(page, text):
    page.wait_for_function("(t) => document.getElementById('toast').textContent.includes(t)", arg=text)


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_rating_sheet_buttons_are_big_and_wrap_to_two_rows(browser, seeded, viewport):   # noqa: F811
    page, errors = _open(browser, seeded, viewport)
    _rate_sheet(page)
    assert page.locator(".rate-row").count() == 5
    for row in range(5):
        boxes = page.locator(".rate-row").nth(row).locator(".rate-btn").evaluate_all(
            "els => els.map(e => { const r = e.getBoundingClientRect(); return [r.top, r.width, r.height, r.right]; })")
        assert len(boxes) == 11
        assert all(w >= 44 and h >= 44 for _top, w, h, _r in boxes), boxes
        assert len({round(top) for top, *_ in boxes}) == 2                       # 1-10 and ½ wrap onto two lines
        assert max(b[3] for b in boxes) <= viewport["width"]
    labels = page.locator(".rate-row").first.locator(".rate-btn").evaluate_all("els => els.map(e => e.textContent)")
    assert labels == [str(n) for n in range(1, 11)] + ["½"]
    assert _side_scroll(page) <= 0 and _height(page, "#rate-done") >= 44 and errors == []
    assert page.evaluate("document.querySelector('.sheet-panel').scrollWidth <= document.querySelector('.sheet-panel').clientWidth")
    _tap(page, "Avery", "8")
    for sel in (".rate-btn", ".rate-btn[aria-pressed=true]", ".rate-hint", ".rate-name", ".rate-val"):
        page.evaluate("(s) => { const e = document.querySelector(s);"
                      " if (!getComputedStyle(e).backgroundColor.match(/[1-9]/)) e.style.backgroundColor = '#16161c'; }", sel)
        assert _contrast(page, sel) >= 4.5, sel
    for color in ("green", "blue", "red", "pink", "purple"):                     # the initial on each family colour
        assert _contrast(page, f".dot[data-color={color}]") >= 4.5, color


def test_rate_a_movie_for_everyone(browser, seeded):   # noqa: F811
    page, errors = _open(browser, seeded, PHONE)
    assert page.locator(".movie-card .star").count() == 0                       # nothing to show yet
    _rate_sheet(page)
    for person, n in zip(("Avery", "Blake", "Casey", "Drew", "Emery"), (8, 9, 10, 8, 8)):
        _tap(page, person, str(n))
    assert page.locator(".rate-row:has-text('Avery') .rate-val").inner_text() == "8"
    assert page.locator(".rate-row:has-text('Avery') .rate-btn[aria-pressed=true]").inner_text() == "8"
    page.click("#rate-done")
    _toast(page, "Ratings saved")
    assert not page.is_visible(".sheet-panel")
    assert page.inner_text("#detail-rating-head") == "★ 8.6 family"
    assert [t.strip() for t in page.eval_on_selector_all(".rating-dot", "els => els.map(e => e.textContent)")] == [
        "A8", "B9", "C10", "D8", "E8"]
    assert page.get_attribute(".rating-dot >> nth=0", "aria-label") == "Avery rated it 8"
    assert page.inner_text("#detail-rate") == "Change ratings"
    for sel in (".rating-head", ".dot", ".dot-val"):
        assert _contrast(page, sel) >= 4.5, sel
    page.click("#back-link")
    assert page.locator(".movie-card", has_text="Elf").locator(".star").inner_text() == "★ 8.6"
    assert _contrast(page, ".star") >= 4.5 and _side_scroll(page) <= 0
    page.reload()                                                                # it was saved, not just drawn
    page.wait_for_selector(".movie-card .star")
    assert page.locator(".movie-card", has_text="Elf").locator(".star").inner_text() == "★ 8.6"
    assert page.locator(".movie-card", has_text="Prancer").locator(".star").count() == 0
    assert errors == []


def test_half_steps_and_clearing(browser, seeded):   # noqa: F811
    page, _ = _open(browser, seeded, PHONE)
    _rate_sheet(page)
    _tap(page, "Avery", "8")
    _tap(page, "Avery", "½")
    assert page.locator(".rate-row:has-text('Avery') .rate-val").inner_text() == "8.5"
    assert page.locator(".rate-row:has-text('Avery') .rate-btn[aria-pressed=true]").count() == 2     # the 8 and the ½
    _tap(page, "Blake", "½")                                                                          # ½ alone is 0.5
    assert page.locator(".rate-row:has-text('Blake') .rate-val").inner_text() == "0.5"
    _tap(page, "Blake", "½")                                                                          # and off again: unrated
    assert page.locator(".rate-row:has-text('Blake') .rate-val").inner_text() == "–"
    _tap(page, "Casey", "10")
    _tap(page, "Casey", "½")                                                                          # nothing above 10
    assert page.locator(".rate-row:has-text('Casey') .rate-val").inner_text() == "10"
    page.click("#rate-done")
    _toast(page, "Ratings saved")
    assert page.inner_text("#detail-rating-head") == "★ 9.3 family"                                    # (8.5 + 10) / 2 = 9.25, ties up
    page.click("#detail-rate")                                                                         # tapping the same value clears it
    _tap(page, "Avery", "8")                                                                           # 8 with the half on is 8.5: the same
    _tap(page, "Casey", "10")
    assert page.locator(".rate-row:has-text('Avery') .rate-val").inner_text() == "–"
    assert page.locator(".rate-row:has-text('Casey') .rate-val").inner_text() == "–"
    page.click("#rate-done")
    page.wait_for_function("document.getElementById('detail-rating-head').textContent === 'Nobody has rated it yet.'")


def test_clearing_every_rating_leaves_no_star(browser, seeded):   # noqa: F811
    with app.app.app_context():
        con = app.get_db()
        app.ratings.set(con, 1, 1, 8)
    page, _ = _open(browser, seeded, PHONE)
    assert page.locator(".movie-card", has_text="Elf").locator(".star").inner_text() == "★ 8.0"
    _rate_sheet(page)
    _tap(page, "Avery", "8")                                         # the same value again clears it
    page.click("#rate-done")
    _toast(page, "Ratings saved")
    assert page.inner_text("#detail-rating-head") == "Nobody has rated it yet." and page.inner_text("#detail-rate") == "Rate it"
    page.click("#back-link")
    assert page.locator(".movie-card .star").count() == 0


def test_the_sheet_closes_without_saving(browser, seeded):   # noqa: F811
    page, _ = _open(browser, seeded, PHONE)
    _rate_sheet(page)
    _tap(page, "Avery", "7")
    page.keyboard.press("Escape")
    assert not page.is_visible(".sheet-panel")
    assert page.inner_text("#detail-rating-head") == "Nobody has rated it yet."
    page.click("#detail-rate")
    page.click("[data-close] >> nth=1")
    assert not page.is_visible(".sheet-panel")
    with app.app.app_context():
        assert app.ratings.family(app.get_db(), 1)["mean"] is None


def test_matinees_rating_shows_until_someone_rates_here(browser, seeded):   # noqa: F811
    with app.app.app_context():
        con = app.get_db()
        con.execute("INSERT INTO matinee_sync (movie_id, matinee_title_id, matinee_rating) VALUES (1, 1, 9.0)")
        con.commit()
    page, _ = _open(browser, seeded, PHONE)
    assert page.locator(".movie-card", has_text="Elf").locator(".star").inner_text() == "★ 9.0"
    page.click(".movie-card >> text=Elf")
    page.wait_for_selector("#detail-rating-head")
    assert page.inner_text("#detail-rating-head") == "★ 9.0 family rating from Matinee"


def test_with_nobody_in_the_family_the_sheet_says_where_to_add_them(browser, server, tmdb_fixtures):   # noqa: F811
    with app.app.app_context():
        app.movies.add_movie(app.get_db(), 10719, "movie", "test")
    page, _ = _open(browser, server, PHONE)
    page.click(".movie-card >> text=Elf")
    page.click("#detail-rate")
    page.wait_for_selector(".rate-hint")
    assert "Add the family in Settings" in page.inner_text(".sheet-panel") and page.locator(".rate-row").count() == 0
    page.click(".sheet-panel a")
    page.wait_for_selector("#people-box .detail-label")
    assert not page.is_visible(".sheet-panel")


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_settings_people_lists_adds_and_syncs(browser, seeded, viewport):   # noqa: F811
    page, errors = _open(browser, seeded, viewport)
    page.click("#settings-btn")
    page.wait_for_selector(".person")
    assert page.eval_on_selector_all(".person-name", "els => els.map(e => e.textContent)") == [n for n, _, _ in FAMILY]
    assert page.locator(".person >> nth=2").inner_text().split() == ["C", "Casey", "Kid"]
    for sel in ("#people-sync", "#person-name", "#person-kind", "#person-form .btn", ".person"):
        assert _height(page, sel) >= 44, sel
    page.fill("#person-name", "Grandpa Visiting")
    page.select_option("#person-kind", "adult")
    page.click("#person-form .btn")
    page.wait_for_function("document.querySelectorAll('.person').length === 6")
    assert page.inner_text(".person >> nth=5").split()[1:3] == ["Grandpa", "Visiting"] and page.input_value("#person-name") == ""
    page.click("#people-sync")                                                  # Matinee is not set up in this app
    _toast(page, "Couldn't sync")
    assert page.locator(".person").count() == 6 and _side_scroll(page) <= 0 and errors == []
    page.click("#person-form .btn")                                             # a blank name is not sent
    _toast(page, "Type a name")
    for sel in (".person-kind", ".settings-hint"):
        assert _contrast(page, sel) >= 4.5, sel
    page.click("#settings-back")
    page.click(".movie-card >> text=Elf")
    page.click("#detail-rate")
    page.wait_for_selector(".rate-row")
    assert page.locator(".rate-row").count() == 6                                # the visitor can rate too


def test_the_first_detail_view_copies_the_family_from_matinee(browser, server, tmdb_fixtures, matinee_fixtures):   # noqa: F811
    with app.app.app_context():
        app.movies.add_movie(app.get_db(), 10719, "movie", "test")
    page, errors = _open(browser, server, PHONE)
    page.click(".movie-card >> text=Elf")
    page.click("#detail-rate")
    page.wait_for_selector(".rate-row")
    assert page.eval_on_selector_all(".rate-name", "els => els.map(e => e.textContent)") == ["Avery", "Blake", "Casey", "Drew"]
    assert [c for c in matinee_fixtures.calls if c[1] == "/admin/api/people"] == [("GET", "/admin/api/people", None)]
    assert errors == []
