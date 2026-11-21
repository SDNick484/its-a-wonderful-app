"""Playwright at phone size (412 and 360 px): the rating sheet (a 0-10 slider per person in half steps, as in Matinee),
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


def _row(page, person):
    return page.locator(f".rate-row:has-text('{person}')")


def _slide(page, person, value):
    """Move a person's slider to `value` (what a drag does: the value changes and the input event fires)."""
    _row(page, person).locator(".rate-slider").fill(str(value))


def _clear(page, person):
    _row(page, person).locator(".rate-clear").click()


def _val(page, person):
    return _row(page, person).locator(".rate-val").inner_text()


def _toast(page, text):
    page.wait_for_function("(t) => document.getElementById('toast').textContent.includes(t)", arg=text)


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_rating_sheet_has_a_big_slider_per_person(browser, seeded, viewport):   # noqa: F811
    page, errors = _open(browser, seeded, viewport)
    _rate_sheet(page)
    assert page.locator(".rate-row").count() == 5
    for row in range(5):
        slider = page.locator(".rate-row").nth(row).locator(".rate-slider")
        box = slider.bounding_box()
        assert box["height"] >= 44 and box["x"] + box["width"] <= viewport["width"], box
        assert [slider.get_attribute(a) for a in ("min", "max", "step")] == ["0", "10", "0.5"]
    assert page.locator(".rate-row-unset").count() == 5                          # nobody rated: all dimmed, "–"
    assert _val(page, "Avery") == "–" and page.locator(".rate-clear:visible").count() == 0
    assert _side_scroll(page) <= 0 and _height(page, "#rate-done") >= 44 and errors == []
    assert page.evaluate("document.querySelector('.sheet-panel').scrollWidth <= document.querySelector('.sheet-panel').clientWidth")
    _slide(page, "Avery", 8)
    shown = ".rate-clear:not([hidden])"
    assert page.locator(shown).count() == 1 and _height(page, shown) >= 44
    for sel in (".rate-hint", ".rate-name", ".rate-val", shown):
        page.evaluate("(s) => { const e = document.querySelector(s);"
                      " if (!getComputedStyle(e).backgroundColor.match(/[1-9]/)) e.style.backgroundColor = '#16161c'; }", sel)
        assert _contrast(page, sel) >= 4.5, sel
    for color in ("green", "blue", "red", "pink", "purple"):                     # the initial on each family colour
        assert _contrast(page, f".dot[data-color={color}]") >= 4.5, color


def test_a_tap_on_the_slider_rates(browser, seeded):   # noqa: F811
    page, _ = _open(browser, seeded, PHONE)
    _rate_sheet(page)
    slider = _row(page, "Avery").locator(".rate-slider")
    slider.click()                                                                # the middle of the strip is 5
    assert _val(page, "Avery") == "5" and page.locator(".rate-row-unset").count() == 4
    blake = _row(page, "Blake").locator(".rate-slider")
    box = blake.bounding_box()
    blake.click(position={"x": box["width"] * 0.7, "y": box["height"] / 2})     # where an unrated thumb rests
    assert _val(page, "Blake") == "7"
    page.keyboard.press("ArrowRight")                                             # half steps from the keyboard too
    assert _val(page, "Blake") == "7.5"


def test_rate_a_movie_for_everyone(browser, seeded):   # noqa: F811
    page, errors = _open(browser, seeded, PHONE)
    assert page.locator(".movie-card .star").count() == 0                       # nothing to show yet
    _rate_sheet(page)
    for person, n in zip(("Avery", "Blake", "Casey", "Drew", "Emery"), (8, 9, 10, 8, 8)):
        _slide(page, person, n)
    assert _val(page, "Avery") == "8" and page.locator(".rate-row-unset").count() == 0
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
    _slide(page, "Avery", 8.5)
    assert _val(page, "Avery") == "8.5"
    _slide(page, "Blake", 0.5)
    assert _val(page, "Blake") == "0.5"
    _clear(page, "Blake")                                                         # Clear: unrated again
    assert _val(page, "Blake") == "–" and _row(page, "Blake").get_attribute("class").endswith("rate-row-unset")
    _slide(page, "Casey", 10)
    assert _val(page, "Casey") == "10"
    page.click("#rate-done")
    _toast(page, "Ratings saved")
    assert page.inner_text("#detail-rating-head") == "★ 9.3 family"                # (8.5 + 10) / 2 = 9.25, ties up
    page.click("#detail-rate")
    page.wait_for_selector(".rate-row")
    assert _val(page, "Avery") == "8.5" and _row(page, "Avery").locator(".rate-slider").input_value() == "8.5"
    _clear(page, "Avery")
    _clear(page, "Casey")
    page.click("#rate-done")
    page.wait_for_function("document.getElementById('detail-rating-head').textContent === 'Nobody has rated it yet.'")


def test_clearing_every_rating_leaves_no_star(browser, seeded):   # noqa: F811
    with app.app.app_context():
        con = app.get_db()
        app.ratings.set(con, 1, 1, 8)
    page, _ = _open(browser, seeded, PHONE)
    assert page.locator(".movie-card", has_text="Elf").locator(".star").inner_text() == "★ 8.0"
    _rate_sheet(page)
    assert _val(page, "Avery") == "8"
    _clear(page, "Avery")
    page.click("#rate-done")
    _toast(page, "Ratings saved")
    assert page.inner_text("#detail-rating-head") == "Nobody has rated it yet." and page.inner_text("#detail-rate") == "Rate it"
    page.click("#back-link")
    assert page.locator(".movie-card .star").count() == 0


def test_the_sheet_closes_without_saving(browser, seeded):   # noqa: F811
    page, _ = _open(browser, seeded, PHONE)
    _rate_sheet(page)
    _slide(page, "Avery", 7)
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


def _conflict(matinee_rating=7.0, conflict=True):
    """Elf rated 8.5, 9, 10, 9, 8 here (8.9; no Matinee key, so nothing was sent), and Matinee title 1 saying 7.0: an
    open notice, or with conflict=False a rating still owed to Matinee."""
    with app.app.app_context():
        con = app.get_db()
        for person, value in zip(range(1, 6), (8.5, 9, 10, 9, 8)):
            app.ratings.set(con, 1, person, value)
        con.execute("UPDATE matinee_sync SET matinee_title_id=1, owned_summary='Blu-ray', matinee_rating=?,"
                    " conflict_rating=? WHERE movie_id=1", (matinee_rating, matinee_rating if conflict else None))
        con.commit()


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_the_conflict_notice_offers_three_answers(browser, seeded, viewport):   # noqa: F811
    _conflict()
    page, errors = _open(browser, seeded, viewport)
    page.click(".movie-card >> text=Elf")
    page.wait_for_selector("#rating-conflict")
    assert page.inner_text(".sync-text") == "Matinee says 7, we say 8.9"
    assert page.eval_on_selector_all("#rating-conflict button", "els => els.map(e => e.textContent)") == [
        "Use ours", "Use Matinee's", "Dismiss"]
    for choice in ("ours", "matinee", "dismiss"):
        assert _height(page, f"#rating-conflict [data-choice={choice}]") >= 44, choice
    for sel in (".sync-text", "#rating-conflict .btn", "#rating-conflict .btn-quiet"):
        assert _contrast(page, sel) >= 4.5, sel
    assert _side_scroll(page) <= 0
    page.click("text=Use Matinee's")
    _toast(page, "Using Matinee's rating")
    assert page.inner_text("#detail-rating-head") == "★ 7.0 family rating from Matinee"
    assert page.locator("#rating-conflict").count() == 0
    page.click("#back-link")
    assert page.locator(".movie-card", has_text="Elf").locator(".star").inner_text() == "★ 7.0"
    assert errors == []


def test_dismiss_closes_the_notice_and_keeps_ours(browser, seeded):   # noqa: F811
    _conflict()
    page, errors = _open(browser, seeded, PHONE)
    page.click(".movie-card >> text=Elf")
    page.click("text=Dismiss")
    _toast(page, "Left as it is")
    assert page.locator("#rating-conflict").count() == 0 and page.inner_text("#detail-rating-head") == "★ 8.9 family"
    page.reload()
    page.wait_for_selector("#detail-rating-head")
    assert page.locator("#rating-conflict").count() == 0 and errors == []


def test_a_rating_matinee_has_not_heard_says_so(browser, seeded):   # noqa: F811
    _conflict(conflict=False)
    page, errors = _open(browser, seeded, PHONE)
    page.click(".movie-card >> text=Elf")
    page.wait_for_selector("#rating-pending")
    assert page.inner_text("#rating-pending") == "Not sent to Matinee yet. It tries again tonight."
    assert _contrast(page, "#rating-pending") >= 4.5 and errors == []
