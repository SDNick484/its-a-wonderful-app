"""Playwright at phone size: the Advent themes (spec §14.3). Today's scene by the calendar, Themes on/off, Light/Dark/System
and Preview themes in Settings; motion that stops under prefers-reduced-motion and pauses in a hidden tab; text that
clears 4.5:1 over every theme even when the drawing under the scrim is white (the scrim's floor is derived from that); no
sideways scroll and three columns at 412 and 360 px. Run by the ui-smoke job (REQUIRE_UI=1, as in test_ui_smoke.py)."""
import datetime as dt
import re
import struct
import zlib

import pytest

import app
from test_ui_grid import LIST, _lefts, _side_scroll
from test_ui_smoke import PHONE, SMALL_PHONE, browser, server  # noqa: F401  (fixtures shared with the smoke tests)

DAYS = {"fireplace": dt.date(2026, 12, 1), "toystore": dt.date(2026, 12, 8), "tree": dt.date(2026, 12, 15),
        "sleigh": dt.date(2027, 1, 3)}                      # Advent 1-3 and Santa's week, after New Year's Day
THEMES = list(DAYS)
PLAIN_DAY = dt.date(2026, 11, 3)
TOKENS = ("--ink", "--ink-2", "--ink-3", "--accent-text", "--amber-text", "--ok-text")


def set_prefs(**prefs):
    with app.app.app_context():
        con = app.get_db()
        for k, v in prefs.items():
            con.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"theme_{k}", v))
        con.commit()


@pytest.fixture
def day(monkeypatch):
    """Sets the host's date for the theme route (a test says which day it is)."""
    def set_day(d):
        monkeypatch.setattr(app, "today", lambda: d)
    return set_day


@pytest.fixture
def seeded(server, tmdb_fixtures):          # noqa: F811
    with app.app.app_context():
        for tmdb_id, tmdb_type in LIST:
            app.movies.add_movie(app.get_db(), tmdb_id, tmdb_type, "test")
    set_prefs(enabled="1", mode="system")
    return server


def open_page(browser, url, viewport=PHONE, path="/", **ctx):       # noqa: F811
    page = browser.new_page(viewport=viewport, device_scale_factor=2.625, is_mobile=True, has_touch=True, **ctx)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url + path)
    page.wait_for_function("document.getElementById('grid-empty').textContent !== 'Loading…'")
    return page, errors


def theme_of(page):
    return page.evaluate("document.documentElement.dataset.theme || null")


def wait_for_art(page, key):
    """The theme's stylesheet is in and its picture is the scene's background."""
    page.wait_for_function("(k) => getComputedStyle(document.getElementById('scene')).backgroundImage.includes('/themes/' + k + '/')",
                           arg=key)


def luminance(rgb):
    def chan(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(v) for v in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def rgb_of(css):
    return [float(n) for n in re.findall(r"[\d.]+", css)[:3]]


def pixel(page, x, y):
    """The RGB of one screen pixel, from a 1 x 1 screenshot. Whatever filter the PNG row uses, a single pixel has no
    left or upper neighbour (both count as 0), so its stored bytes are the colour as they are."""
    png = page.screenshot(clip={"x": x, "y": y, "width": 1, "height": 1}, scale="css")
    pos, idat, ctype = 8, b"", 2
    while pos < len(png):
        n, kind = struct.unpack(">I4s", png[pos:pos + 8])
        body = png[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            ctype = body[9]
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    raw = zlib.decompress(idat)
    assert ctype in (2, 6) and len(raw) in (4, 5), (ctype, len(raw))
    return list(raw[1:4])


def blend(over, under, alpha):
    return [alpha * o + (1 - alpha) * u for o, u in zip(over, under)]


# ------------------------------------------------------------------------------------------------ the calendar on the page
@pytest.mark.parametrize("key", THEMES)
def test_todays_scene_is_the_one_the_calendar_names(browser, seeded, day, key):   # noqa: F811
    day(DAYS[key])
    page, errors = open_page(browser, seeded)
    assert theme_of(page) == key
    wait_for_art(page, key)
    assert page.is_visible("#scene") and page.get_attribute("#scene", "aria-hidden") == "true"
    for name in ("background.webp", "background-wide.webp", "theme.css"):         # the layers are real, served files
        assert page.evaluate("(u) => fetch(u).then(r => r.status)", f"/static/themes/{key}/{name}") == 200
    assert errors == []


def test_a_plain_day_has_no_scene_and_stays_clear_of_theme_files(browser, seeded, day):   # noqa: F811
    day(PLAIN_DAY)
    page, errors = open_page(browser, seeded)
    assert theme_of(page) is None and not page.is_visible("#scene")
    assert page.locator("#theme-css").count() == 0 and errors == []


def test_themes_off_wins_over_the_calendar(browser, seeded, day):   # noqa: F811
    day(DAYS["tree"])
    set_prefs(enabled="0")
    page, _ = open_page(browser, seeded)
    assert theme_of(page) is None and page.locator("#theme-css").count() == 0


def test_settings_saves_themes_on_off_and_light_dark_for_the_household(browser, seeded, day):   # noqa: F811
    day(DAYS["fireplace"])
    page, errors = open_page(browser, seeded, path="/#/settings")
    page.wait_for_selector("#look-box .seg-btn")
    assert "fireplace scene, through December 5" in page.inner_text("#theme-hint")
    assert page.get_attribute("[data-enabled=true]", "aria-pressed") == "true" and theme_of(page) == "fireplace"
    page.click("[data-enabled=false]")
    page.wait_for_function("!document.documentElement.dataset.theme")
    assert page.get_attribute("[data-enabled=false]", "aria-pressed") == "true"
    assert page.evaluate("fetch('/api/theme/prefs').then(r => r.json())") == {"enabled": False, "mode": "system"}
    page.click(".seg-btn[data-mode=light]")
    page.wait_for_function("document.documentElement.dataset.scheme === 'light'")
    assert page.evaluate("fetch('/api/theme/prefs').then(r => r.json())") == {"enabled": False, "mode": "light"}
    assert page.evaluate("document.activeElement.dataset.mode") == "light"           # focus stays on what was pressed
    page.reload()                                                                     # kept in the database, not the page
    page.wait_for_selector("#look-box .seg-btn")
    assert theme_of(page) is None and page.get_attribute(".seg-btn[data-mode=light]", "aria-pressed") == "true"
    page.click("[data-enabled=true]")
    page.wait_for_function("document.documentElement.dataset.theme === 'fireplace'")
    assert errors == []


def test_settings_look_buttons_are_tappable_and_fit(browser, seeded, day):   # noqa: F811
    day(DAYS["fireplace"])
    for viewport in (PHONE, SMALL_PHONE):
        page, _ = open_page(browser, seeded, viewport, "/#/settings")
        page.wait_for_selector("#look-box .chip")
        heights = page.eval_on_selector_all("#look-box .seg-btn, #look-box .chip",
                                            "els => els.map(e => e.getBoundingClientRect().height)")
        assert len(heights) == 11 and min(heights) >= 44 and _side_scroll(page) <= 0


def test_preview_themes_is_for_this_session_only(browser, seeded, day):   # noqa: F811
    day(PLAIN_DAY)
    page, errors = open_page(browser, seeded, path="/#/settings")
    page.wait_for_selector("#look-box .chip")
    assert [t.strip() for t in page.eval_on_selector_all("#look-box .chip", "els => els.map(e => e.textContent)")] == [
        "Today's", "Fireplace", "Toy store", "Christmas tree", "Santa's sleigh", "No theme"]
    for label, key in (("Fireplace", "fireplace"), ("Toy store", "toystore"), ("Christmas tree", "tree"), ("Santa's sleigh", "sleigh")):
        page.click(f"#look-box .chip >> text={label}")
        page.wait_for_function("(k) => document.documentElement.dataset.theme === k", arg=key)
        wait_for_art(page, key)
        assert page.get_attribute(f"#look-box .chip >> text={label}", "aria-pressed") == "true"
    page.reload()                                                                     # the preview survives navigation...
    page.wait_for_selector("#look-box .chip")
    assert theme_of(page) == "sleigh"
    assert page.evaluate("fetch('/api/theme/prefs').then(r => r.json())")["enabled"] is True      # ...and saved nothing
    other, _ = open_page(browser, seeded)                                             # a new session sees today's look
    assert theme_of(other) is None
    page.click("#look-box .chip >> text=No theme")
    page.wait_for_function("!document.documentElement.dataset.theme")
    page.click("#look-box .chip >> text=Today's")
    assert theme_of(page) is None and page.evaluate("sessionStorage.getItem('wonderful-preview')") is None
    assert errors == []


def test_a_preview_shows_even_with_themes_off(browser, seeded, day):   # noqa: F811
    day(DAYS["tree"])
    set_prefs(enabled="0")
    page, _ = open_page(browser, seeded, path="/#/settings")
    page.wait_for_selector("#look-box .chip")
    page.click("#look-box .chip >> text=Toy store")
    page.wait_for_function("document.documentElement.dataset.theme === 'toystore'")


# ------------------------------------------------------------------------------------------------ motion
@pytest.mark.parametrize("key", THEMES)
def test_reduced_motion_stops_every_animation_and_the_canvas(browser, seeded, day, key):   # noqa: F811
    day(DAYS[key])
    page, errors = open_page(browser, seeded, reduced_motion="reduce")
    wait_for_art(page, key)
    page.wait_for_function("document.getElementById('fx').dataset.running === 'false'")
    page.wait_for_timeout(300)
    assert page.evaluate("document.getAnimations().length") == 0
    frames = page.evaluate("document.getElementById('fx').dataset.frames || '0'")
    page.wait_for_timeout(400)
    assert page.evaluate("document.getElementById('fx').dataset.frames || '0'") == frames          # the loop is stopped
    assert not page.evaluate("document.getElementById('fx').getContext('2d')"
                             ".getImageData(0, 0, 40, 40).data.some(v => v)")                        # and nothing is drawn
    assert errors == []


@pytest.mark.parametrize("key", THEMES)
def test_with_motion_the_scene_moves_and_the_canvas_draws(browser, seeded, day, key):   # noqa: F811
    day(DAYS[key])
    page, errors = open_page(browser, seeded, reduced_motion="no-preference")
    wait_for_art(page, key)
    page.wait_for_function("document.getElementById('fx').dataset.running === 'true'")
    assert page.evaluate("document.getAnimations().length") > 0               # flicker, twinkle, breathing
    page.wait_for_function("Number(document.getElementById('fx').dataset.frames) > 5")
    page.wait_for_timeout(1200)
    assert page.evaluate("document.getElementById('fx').getContext('2d')"
                         ".getImageData(0, 0, document.getElementById('fx').width, document.getElementById('fx').height)"
                         ".data.some((v, i) => i % 4 === 3 && v)")           # snow (all four), sparks (fireplace)
    assert errors == []


def test_a_hidden_tab_pauses_the_loop_and_coming_back_resumes_it(browser, seeded, day):   # noqa: F811
    day(DAYS["fireplace"])
    page, _ = open_page(browser, seeded, reduced_motion="no-preference")
    page.wait_for_function("document.getElementById('fx').dataset.running === 'true'")
    page.evaluate("Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });"
                  " document.dispatchEvent(new Event('visibilitychange'))")
    assert page.evaluate("document.getElementById('fx').dataset.running") == "false"
    frames = page.evaluate("document.getElementById('fx').dataset.frames")
    page.wait_for_timeout(400)
    assert page.evaluate("document.getElementById('fx').dataset.frames") == frames
    page.evaluate("Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });"
                  " document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_function("(n) => Number(document.getElementById('fx').dataset.frames) > Number(n)", arg=frames)
    assert page.evaluate("document.getElementById('fx').dataset.running") == "true"


def test_turning_themes_off_stops_the_loop(browser, seeded, day):   # noqa: F811
    day(DAYS["tree"])
    page, _ = open_page(browser, seeded, path="/#/settings", reduced_motion="no-preference")
    page.wait_for_function("document.getElementById('fx').dataset.running === 'true'")
    page.click("[data-enabled=false]")
    page.wait_for_function("document.getElementById('fx').dataset.running === 'false'")


# ------------------------------------------------------------------------------------------------ layout
@pytest.mark.parametrize("key", THEMES)
@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_three_columns_and_no_side_scroll_over_every_theme(browser, seeded, day, key, viewport):   # noqa: F811
    day(DAYS[key])
    page, errors = open_page(browser, seeded, viewport)
    wait_for_art(page, key)
    assert len(set(_lefts(page)[:3])) == 3 and _lefts(page)[3] == _lefts(page)[0] and _side_scroll(page) <= 0
    page.click(".movie-card >> text=Elf")
    page.wait_for_selector("#detail .detail-title")
    assert _side_scroll(page) <= 0 and errors == []


def test_the_scene_does_not_take_taps_or_move_with_scrolling(browser, seeded, day):   # noqa: F811
    day(DAYS["tree"])
    page, _ = open_page(browser, seeded)
    wait_for_art(page, "tree")
    assert page.evaluate("getComputedStyle(document.getElementById('scene')).pointerEvents") == "none"
    assert page.evaluate("getComputedStyle(document.getElementById('scene')).position") == "fixed"
    page.click(".movie-card >> text=Elf")                                              # a tap reaches the card
    page.wait_for_selector("#detail .detail-title")


# ------------------------------------------------------------------------------------------------ contrast over themes
def scrim_stops(page):
    """(rgb, [alphas]) of the scrim's gradient as the browser computed it."""
    css = page.evaluate("getComputedStyle(document.querySelector('.scene-scrim')).backgroundImage")
    stops = re.findall(r"rgba?\(([^)]*)\)", css)
    rgbs = [[float(n) for n in re.split(r"[ ,/]+", s.strip()) if n][:4] for s in stops]
    return rgbs[0][:3], [r[3] if len(r) > 3 else 1.0 for r in rgbs]


def needed_alpha(fg, scrim_rgb, floor=4.5):
    """The least scrim alpha that keeps `fg` at `floor`:1 when the drawing under it is white (the brightest it can be)."""
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if ratio(fg, blend(scrim_rgb, [255, 255, 255], mid)) >= floor:
            hi = mid
        else:
            lo = mid
    return hi


def token_colors(page):
    return {t: rgb_of(page.evaluate("(t) => { const e = document.createElement('i'); e.style.color = `var(${t})`;"
                                    " document.body.appendChild(e); const c = getComputedStyle(e).color; e.remove(); return c; }", t))
            for t in TOKENS}


@pytest.mark.parametrize("key", THEMES)
def test_scrim_floor_keeps_every_text_colour_at_4_5_over_a_white_drawing(browser, seeded, day, key):   # noqa: F811
    day(DAYS[key])
    page, _ = open_page(browser, seeded, reduced_motion="reduce")
    wait_for_art(page, key)
    scrim_rgb, alphas = scrim_stops(page)
    floor = min(alphas)
    assert floor == pytest.approx(float(page.evaluate("getComputedStyle(document.getElementById('scene')).getPropertyValue('--scrim-min')")), abs=0.005)
    for token, color in token_colors(page).items():
        assert floor >= needed_alpha(color, scrim_rgb), (key, token, floor)
    assert max(needed_alpha(c, scrim_rgb) for c in token_colors(page).values()) > 0.5      # the test bites: a thin scrim fails it


@pytest.mark.parametrize("key", THEMES)
def test_title_and_rating_text_clear_4_5_on_the_real_scrim_over_white(browser, seeded, day, key):   # noqa: F811
    """The pixels, not the arithmetic: paint the drawing white, set the glow at its brightest, hide the glyphs, and measure the
    page behind each piece of text against that text's own colour."""
    day(DAYS[key])
    page, errors = open_page(browser, seeded, reduced_motion="reduce")
    wait_for_art(page, key)
    page.click(".movie-card >> text=Elf")
    page.wait_for_selector("#detail-rating-head")
    selectors = [".detail-title", ".detail-meta", ".detail-label", "#detail-rating-head", ".back-link", ".detail-overview",
                 ".detail-cast", ".site-footer p"]
    colors = {sel: rgb_of(page.evaluate("(s) => getComputedStyle(document.querySelector(s)).color", sel)) for sel in selectors}
    page.add_style_tag(content="""#scene { background-image: none !important; background-color: #fff !important; }
        #scene .scene-glow { opacity: 1 !important; animation: none !important; }
        .scene-lights { display: none !important; }
        * { color: transparent !important; text-shadow: none !important; }""")
    for sel in selectors:
        centre = page.evaluate("""(s) => { const e = document.querySelector(s); e.scrollIntoView({block: 'center'});
            const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }""", sel)
        bg = pixel(page, centre[0], centre[1])
        assert ratio(colors[sel], bg) >= 4.5, (key, sel, colors[sel], bg, round(ratio(colors[sel], bg), 2))
    assert errors == []


@pytest.mark.parametrize("key", THEMES)
def test_every_text_colour_clears_4_5_across_the_screen_over_white(browser, seeded, day, key):   # noqa: F811
    """Any text colour the app uses, set anywhere on the screen (the fire's glow at its brightest included)."""
    day(DAYS[key])
    page, _ = open_page(browser, seeded, reduced_motion="reduce")
    wait_for_art(page, key)
    colors = token_colors(page)
    page.add_style_tag(content="""#scene { background-image: none !important; background-color: #fff !important; }
        #scene .scene-glow { opacity: 1 !important; animation: none !important; }
        main, .site-footer, .site-header { visibility: hidden !important; }""")   # only the scene: no chips or buttons
    page.wait_for_timeout(100)
    w, h = PHONE["width"], PHONE["height"]
    for fy in (0.02, 0.15, 0.3, 0.5, 0.65, 0.75, 0.85, 0.98):          # the fire glows at 75 %
        for fx in (0.05, 0.5, 0.95):
            x, y = fx * w, fy * h
            if (x < 18 or x > w - 18) and key in ("toystore", "tree"):
                continue
            bg = pixel(page, x, y)
            for token, color in colors.items():
                assert ratio(color, bg) >= 4.5, (key, token, (fx, fy), bg, round(ratio(color, bg), 2))


# ------------------------------------------------------------------------------------------------ light and dark
def body_bg(page):
    return rgb_of(page.evaluate("getComputedStyle(document.body).backgroundColor"))


@pytest.mark.parametrize("scheme,mode,light", [("light", "system", True), ("dark", "system", False),
                                               ("dark", "light", True), ("light", "dark", False)])
def test_light_dark_and_system_in_the_plain_period(browser, seeded, day, scheme, mode, light):   # noqa: F811
    day(PLAIN_DAY)
    set_prefs(mode=mode)
    page, errors = open_page(browser, seeded, color_scheme=scheme)
    assert (luminance(body_bg(page)) > 0.5) is light
    assert _side_scroll(page) <= 0 and errors == []


def test_a_theme_is_dark_even_when_light_is_chosen(browser, seeded, day):   # noqa: F811
    day(DAYS["tree"])
    set_prefs(mode="light")
    page, _ = open_page(browser, seeded, color_scheme="light")
    wait_for_art(page, "tree")
    assert luminance(body_bg(page)) < 0.05 and page.evaluate("getComputedStyle(document.documentElement).colorScheme") == "dark"


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_text_colours_clear_4_5_on_every_surface_in_light_and_dark(browser, seeded, day, scheme):   # noqa: F811
    day(PLAIN_DAY)
    set_prefs(mode="system")
    page, _ = open_page(browser, seeded, color_scheme=scheme)
    surfaces = {s: rgb_of(page.evaluate("(t) => { const e = document.createElement('i'); e.style.backgroundColor = `var(${t})`;"
                                        " document.body.appendChild(e); const c = getComputedStyle(e).backgroundColor; e.remove();"
                                        " return c; }", s)) for s in ("--page", "--card", "--raised")}
    colors = token_colors(page)
    for token in ("--ink", "--ink-2", "--ink-3"):
        for name, bg in surfaces.items():
            assert ratio(colors[token], bg) >= 4.5, (scheme, token, name)
    for token in ("--accent-text", "--amber-text", "--ok-text"):
        for name in ("--page", "--card"):
            assert ratio(colors[token], surfaces[name]) >= 4.5, (scheme, token, name)
    accent, ink = (rgb_of(page.evaluate("(t) => { const e = document.createElement('i'); e.style.color = `var(${t})`;"
                                        " document.body.appendChild(e); const c = getComputedStyle(e).color; e.remove(); return c; }", t))
                   for t in ("--accent", "--accent-ink"))
    assert ratio(accent, ink) >= 4.5                                                  # button text on the red


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_light_look_keeps_three_columns_and_readable_text_on_the_screens(browser, seeded, day, viewport):   # noqa: F811
    day(PLAIN_DAY)
    set_prefs(mode="light")
    page, errors = open_page(browser, seeded, viewport, color_scheme="dark")
    assert len(set(_lefts(page)[:3])) == 3 and _side_scroll(page) <= 0
    for sel in (".card-title", ".card-year", ".section-title", ".search-status", ".site-footer p"):
        fg = rgb_of(page.evaluate("(s) => getComputedStyle(document.querySelector(s)).color", sel))
        assert ratio(fg, body_bg(page)) >= 4.5, sel
    page.click(".movie-card >> text=Elf")
    page.wait_for_selector("#detail-rating-head")
    for sel in (".detail-meta", ".detail-label", "#detail-rating-head", ".back-link"):
        fg = rgb_of(page.evaluate("(s) => getComputedStyle(document.querySelector(s)).color", sel))
        assert ratio(fg, body_bg(page)) >= 4.5, sel
    assert errors == []


def test_santa_rides_the_sleigh_in_red(browser, seeded, day):   # noqa: F811
    """The gold sleigh made Santa a gold blob on a gold sleigh; he is drawn in red so he can be seen. The first sleigh
    comes 4 to 9 s after the page opens and takes 11 s to cross: some canvas pixel turns plainly red (snow, glitter and
    the sleigh are white or gold, and the drawing is CSS, not on the canvas)."""
    day(DAYS["sleigh"])
    page, errors = open_page(browser, seeded, reduced_motion="no-preference")
    wait_for_art(page, "sleigh")
    page.wait_for_function("""(() => {
        const c = document.getElementById('fx'), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
        for (let i = 0; i < d.length; i += 4) if (d[i + 3] > 200 && d[i] > 200 && d[i + 1] < 90 && d[i + 2] < 90) return true;
        return false;
    })()""", polling=250, timeout=20000)
    assert errors == []
