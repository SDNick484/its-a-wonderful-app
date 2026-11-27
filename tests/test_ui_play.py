"""Playwright at phone size (412 and 360 px): the movie's "Play on the Family Room TV" section (design 2026-11-26 §5.3, §5.4,
plan Task 4): the disc and stream boxes, the status line (Opening..., confirmed, Sent to the TV., didn't answer), a Home
Assistant that is down, one request per tap, the second visit to the page, and a stale TV event that never confirms
(Review Focus 3, the page's half). Home Assistant's play webhook is a recorder (no live network); the TV's events come in
through /hooks/tv as the real automation sends them. Run by the ui-smoke job (REQUIRE_UI=1).

One clock: every TV event is stamped from this process's UTC now (the host's clock, as the play route's `sent_at` is),
with a UTC-8 offset so the page has to compare dates, not strings; the host's date is pinned, never the browser's."""
import datetime as dt
import json
import time
import types
import urllib.error

import pytest

import app
from test_theme_ui import DAYS, pixel, ratio, rgb_of, set_prefs, wait_for_art
from test_ui_grid import _height, _side_scroll
from test_ui_smoke import PHONE, SMALL_PHONE, browser, server  # noqa: F401  (fixtures shared with the smoke tests)

URL = "http://ha.example.com:8123/api/webhook/play-secret-id"
SECRET = "tv-s3cret"
SHELF = "Family Room › Media Cabinet › Shelf 2"
SHELF_LINE = f"Blu-ray · {SHELF}"
PACIFIC_WINTER = dt.timezone(dt.timedelta(hours=-8))
VIEWPORTS = [pytest.param(PHONE, id="412px"), pytest.param(SMALL_PHONE, id="360px")]


class _Ok:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Webhook:
    """urlopen for Home Assistant's play webhook: keeps each request body, waits `delay`, answers `status`."""

    def __init__(self):
        self.calls, self.status, self.delay = [], 200, 0.0

    def __call__(self, req, timeout=None):
        assert req.full_url == URL, req.full_url
        self.calls.append(json.loads(req.data))
        time.sleep(self.delay)
        if self.status != 200:
            raise urllib.error.HTTPError(req.full_url, self.status, "Server Error", {}, None)
        return _Ok()


@pytest.fixture
def env(server, monkeypatch):          # noqa: F811
    """The app with the TV hook secret, a pinned host date and the recorder in place of Home Assistant. Play is still off."""
    import urllib.request
    hook = Webhook()
    monkeypatch.setattr(urllib.request, "urlopen", hook)
    monkeypatch.setattr(app, "HA_HOOK_SECRET", SECRET)
    monkeypatch.setattr(app, "today", lambda: dt.date(2026, 12, 12))
    return types.SimpleNamespace(url=server, hook=hook)


@pytest.fixture
def on(env, monkeypatch):
    """env with HA_PLAY_WEBHOOK_URL set: Play on TV is on."""
    monkeypatch.setattr(app, "HA_PLAY_WEBHOOK_URL", URL)
    return env


def seed(title="Home Alone", disc=False, digital=False, **tiers):
    """A movie, with where TMDB lists it (`flatrate=["disney_plus"]`, ...) and what Matinee holds. Returns its id."""
    with app.app.app_context():
        con = app.get_db()
        tmdb_id = con.execute("SELECT COALESCE(MAX(tmdb_id), 0) + 1 FROM movies").fetchone()[0]
        movie_id = con.execute("INSERT INTO movies (tmdb_id, title, runtime_min) VALUES (?, ?, 103)", (tmdb_id, title)).lastrowid
        data = {t: tiers.get(t, []) for t in ("flatrate", "free", "ads", "rent", "buy")}
        con.execute("INSERT INTO providers_cache (movie_id, data, fetched_at) VALUES (?, ?, ?)", (movie_id, json.dumps(data), app.now_iso()))
        if disc or digital:
            summary = " · ".join(x for x in ("Blu-ray" if disc else "", "Digital HD" if digital else "") if x)
            con.execute("INSERT INTO matinee_sync (movie_id, matinee_title_id, owned_summary, location_path, checked_at,"
                        " has_physical, has_digital) VALUES (?, 1, ?, ?, ?, ?, ?)",
                        (movie_id, summary, SHELF if disc else None, app.now_iso(), int(disc), int(digital)))
        con.commit()
        return movie_id


def open_page(browser, env, viewport=PHONE, wait=400, **ctx):          # noqa: F811
    """The grid, with the page's polling made short (it is 3 s and 90 s for real) before the app loads."""
    page = browser.new_page(viewport=viewport, device_scale_factor=2.625, is_mobile=True, has_touch=True, **ctx)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script(f"window.__playTimings = {{poll: 50, wait: {wait}}};")
    page.goto(env.url + "/")
    page.wait_for_function("document.querySelector('#grid .movie-card') !== null")
    return page, errors


def open_movie(page, title="Home Alone"):
    page.click(f".movie-card >> text={title}")
    page.wait_for_selector("#detail-where")


def status(page):
    return page.inner_text("#detail-play-status")


def wait_status(page, text, timeout=5000):
    page.wait_for_function("(t) => document.getElementById('detail-play-status')?.textContent === t", arg=text, timeout=timeout)


def wait_for(condition, timeout=5.0):
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.02)


def tv_event(page, env, state, source, ago=0):
    """The TV's event, as Home Assistant posts it: stamped `ago` seconds back on the host's clock, in UTC-8."""
    at = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=ago)).astimezone(PACIFIC_WINTER)
    r = page.request.post(env.url + "/hooks/tv", data={"state": state, "source": source, "at": at.isoformat()},
                          headers={"X-Hook-Secret": SECRET})
    assert r.ok, r.text()


def tonight_text(page):
    return page.inner_text("#detail-tonight-box")


# ------------------------------------------------------------------------------------------------ the section
@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_both_boxes_show(browser, on, viewport):          # noqa: F811
    seed(disc=True, flatrate=["disney_plus"])
    page, errors = open_page(browser, on, viewport)
    open_movie(page)
    headings = page.eval_on_selector_all(".detail-label", "els => els.map(e => e.textContent)")
    assert headings.index("Play on the Family Room TV") == headings.index("Where to watch") - 1
    boxes = page.locator("#detail-play-box .play-box")
    assert boxes.count() == 2
    assert SHELF_LINE in boxes.nth(0).inner_text() and boxes.nth(0).get_by_role("button", name="Start the disc").count() == 1
    assert "On Disney+" in boxes.nth(1).inner_text() and boxes.nth(1).get_by_role("button", name="Stream it", exact=True).count() == 1
    assert page.get_attribute("#detail-play-status", "aria-live") == "polite"
    for sel in ("[data-play=disc]", "[data-play=stream]"):
        assert _height(page, sel) >= 44, sel
    assert page.is_visible("#detail-tonight")           # Watch tonight stays beside it
    assert _side_scroll(page) <= 0 and errors == []


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_two_services_name_the_app(browser, on, viewport):          # noqa: F811
    seed(flatrate=["netflix", "disney_plus"])
    page, errors = open_page(browser, on, viewport)
    open_movie(page)
    names = page.eval_on_selector_all("[data-play=stream]", "els => els.map(e => [e.textContent, e.dataset.service])")
    assert names == [["Stream it on Netflix", "netflix"], ["Stream it on Disney+", "disney_plus"]]
    assert page.locator("[data-play=disc]").count() == 0
    assert all(_height(page, f"[data-service={k}]") >= 44 for k in ("netflix", "disney_plus"))
    assert _side_scroll(page) <= 0 and errors == []


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_digital_copy_box(browser, on, viewport):          # noqa: F811
    seed(digital=True)
    page, errors = open_page(browser, on, viewport)
    open_movie(page)
    assert "Our digital copy · Fandango at Home" in page.inner_text("#detail-play-box")
    assert page.get_by_role("button", name="Stream it", exact=True).count() == 1
    assert page.locator("[data-play=disc]").count() == 0
    assert _side_scroll(page) <= 0 and errors == []


def test_no_section_when_nothing_applies(browser, on):          # noqa: F811
    seed(rent=["netflix"])
    page, errors = open_page(browser, on)
    open_movie(page)
    assert "Play on the Family Room TV" not in page.inner_text("#detail")
    assert page.locator("#detail-play-box").count() == 0 and page.is_visible("#detail-tonight") and errors == []


def test_no_section_when_the_feature_is_off(browser, env):          # noqa: F811
    seed(disc=True, flatrate=["disney_plus"])           # HA_PLAY_WEBHOOK_URL is empty
    page, errors = open_page(browser, env)
    open_movie(page)
    assert "Play on the Family Room TV" not in page.inner_text("#detail")
    assert page.locator("[data-play]").count() == 0 and page.is_visible("#detail-tonight") and errors == []


# ------------------------------------------------------------------------------------------------ pressing a button
@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_stream_it_confirms(browser, on, viewport):          # noqa: F811
    seed(flatrate=["disney_plus"])
    page, errors = open_page(browser, on, viewport, wait=5000)
    tv_event(page, on, "on", "Netflix", ago=600)        # the TV has been heard from: on Netflix, ten minutes ago
    open_movie(page)
    page.click("[data-play=stream]")
    wait_status(page, "Opening Disney+ on the Family Room TV…")
    wait_for(lambda: len(on.hook.calls) == 1)
    assert on.hook.calls == [{"event": "wonderful_play", "mode": "stream", "source": "Disney+", "title": "Home Alone"}]
    page.wait_for_selector("#detail-tonight-status")
    assert page.inner_text("#detail-play-status") == "Opening Disney+ on the Family Room TV…"     # the old event confirms nothing
    tv_event(page, on, "on", "Disney+")
    wait_status(page, "Disney+ is open on the Family Room TV.")
    assert page.inner_text("#detail-tonight-status") == "On for tonight." and page.locator("#detail-tonight").count() == 0
    assert page.is_enabled("[data-play=stream]") and _side_scroll(page) <= 0 and errors == []


def test_the_tv_already_there_confirms_at_once(browser, on):          # noqa: F811
    seed(flatrate=["disney_plus"])
    page, _ = open_page(browser, on, wait=5000)
    tv_event(page, on, "playing", "disney+", ago=300)   # on Disney+ since before the tap: nothing else is coming
    open_movie(page)
    page.click("[data-play=stream]")
    wait_status(page, "Disney+ is open on the Family Room TV.")


def test_an_event_older_than_the_tap_never_confirms(browser, on):          # noqa: F811
    seed(flatrate=["disney_plus"])
    page, _ = open_page(browser, on)
    tv_event(page, on, "on", "Netflix", ago=600)
    open_movie(page)
    page.click("[data-play=stream]")
    wait_for(lambda: len(on.hook.calls) == 1)
    tv_event(page, on, "on", "Disney+", ago=60)         # a minute before the tap: older than sent_at minus 5 s
    wait_status(page, "The TV didn't answer. Try the remote.")


def test_an_event_on_another_input_never_confirms(browser, on):          # noqa: F811
    seed(flatrate=["disney_plus"])
    page, _ = open_page(browser, on)
    tv_event(page, on, "on", "Netflix", ago=600)
    open_movie(page)
    page.click("[data-play=stream]")
    wait_for(lambda: len(on.hook.calls) == 1)
    tv_event(page, on, "on", "Netflix")
    wait_status(page, "The TV didn't answer. Try the remote.")


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_start_the_disc_shows_the_shelf(browser, on, viewport):          # noqa: F811
    seed(disc=True, flatrate=["disney_plus"])
    page, errors = open_page(browser, on, viewport)
    open_movie(page)
    page.click("[data-play=disc]")
    page.wait_for_function("document.getElementById('detail-play-status').textContent.includes('go get it!')")
    assert SHELF_LINE in status(page)
    assert on.hook.calls == [{"event": "wonderful_play", "mode": "disc", "source": "AV Receiver", "title": "Home Alone"}]
    assert _side_scroll(page) <= 0 and errors == []


def test_a_disc_confirms_with_the_shelf_line(browser, on):          # noqa: F811
    seed(disc=True)
    page, _ = open_page(browser, on, wait=5000)
    tv_event(page, on, "on", "Netflix", ago=600)
    open_movie(page)
    page.click("[data-play=disc]")
    wait_for(lambda: len(on.hook.calls) == 1)
    tv_event(page, on, "on", "AV Receiver")
    wait_status(page, f"The TV is ready. {SHELF_LINE}: go get it!")


def test_tv_never_answers(browser, on):          # noqa: F811
    seed(flatrate=["disney_plus"])
    page, errors = open_page(browser, on)
    tv_event(page, on, "off", None, ago=600)            # heard from, so the page polls
    open_movie(page)
    page.click("[data-play=stream]")
    wait_status(page, "Opening Disney+ on the Family Room TV…")
    wait_status(page, "The TV didn't answer. Try the remote.")
    assert page.is_enabled("[data-play=stream]") and errors == []


def test_no_events_ever(browser, on):          # noqa: F811
    seed(flatrate=["disney_plus"])
    page, errors = open_page(browser, on)
    open_movie(page)
    page.click("[data-play=stream]")
    wait_status(page, "Sent to the TV.")
    assert len(on.hook.calls) == 1 and errors == []
    page.wait_for_timeout(600)                          # longer than the shortened wait: nothing replaces it
    assert status(page) == "Sent to the TV."


def test_home_assistant_down(browser, on):          # noqa: F811
    seed(flatrate=["disney_plus"])
    on.hook.status = 500
    page, errors = open_page(browser, on)
    open_movie(page)
    page.click("[data-play=stream]")
    wait_status(page, "Couldn't reach the TV. Home Alone is on for tonight; use the remote.")
    assert page.is_enabled("[data-play=stream]")
    page.wait_for_selector("#detail-tonight-status")    # the movie is on for tonight all the same
    assert page.locator("#detail-tonight").count() == 0 and errors == []
    on.hook.status = 200                                # and the next tap goes through
    page.click("[data-play=stream]")
    wait_status(page, "Sent to the TV.")


def test_a_movie_that_cannot_be_played_says_why(browser, on):          # noqa: F811
    seed(flatrate=["disney_plus"])
    page, _ = open_page(browser, on)
    open_movie(page)
    page.route("**/api/movies/*/play", lambda route: route.fulfill(
        status=409, content_type="application/json", body='{"error": "Home Alone isn\'t on a service we have."}'))
    page.click("[data-play=stream]")
    wait_status(page, "Home Alone isn't on a service we have.")
    assert on.hook.calls == [] and page.is_enabled("[data-play=stream]") and page.locator("#detail-tonight").count() == 1


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_double_tap_sends_once(browser, on, viewport):          # noqa: F811
    seed(disc=True, flatrate=["disney_plus"])
    on.hook.delay = 0.4
    page, _ = open_page(browser, on, viewport)
    open_movie(page)
    page.evaluate("() => { const b = document.querySelector('[data-play=stream]'); b.click(); b.click(); }")
    page.evaluate("() => document.querySelector('[data-play=disc]').click()")      # nor can the other box start a second one
    wait_status(page, "Sent to the TV.")
    page.wait_for_timeout(300)
    assert len(on.hook.calls) == 1 and status(page) == "Sent to the TV."


def test_second_visit_still_works(browser, on):          # noqa: F811
    seed(flatrate=["disney_plus"])
    seed("Elf", flatrate=["netflix"])
    page, errors = open_page(browser, on)
    open_movie(page)
    page.click("#back-link")
    page.wait_for_selector("#grid-view", state="visible")
    open_movie(page)
    assert page.inner_text("#detail-play-status") == ""     # a fresh page: the last visit's line is gone
    page.click("[data-play=stream]")
    wait_status(page, "Sent to the TV.")
    page.wait_for_timeout(200)
    assert len(on.hook.calls) == 1
    page.click("#back-link")
    page.wait_for_selector("#grid-view", state="visible")
    open_movie(page, "Elf")                              # a second movie after the first: its own page and one request
    page.click("[data-play=stream]")
    wait_status(page, "Sent to the TV.")
    page.wait_for_timeout(200)
    assert [c["title"] for c in on.hook.calls] == ["Home Alone", "Elf"] and errors == []


def test_the_answer_follows_the_person_off_the_page_in_a_toast_that_stays_until_tapped(browser, on):          # noqa: F811
    seed(disc=True)
    page, errors = open_page(browser, on, wait=8000)
    tv_event(page, on, "on", "Netflix", ago=600)
    open_movie(page)
    page.click("[data-play=disc]")
    wait_for(lambda: len(on.hook.calls) == 1)
    page.click("#back-link")                             # away from the page: its status line is no longer on screen
    page.wait_for_selector("#grid-view", state="visible")
    tv_event(page, on, "on", "AV Receiver")
    page.wait_for_function("document.getElementById('toast').textContent.includes('go get it!')")
    assert f"The TV is ready. {SHELF_LINE}: go get it!" == page.inner_text("#toast")
    page.wait_for_timeout(4400)                          # a disc's toast is not the 4-second kind
    assert page.evaluate("document.getElementById('toast').classList.contains('show')")
    assert page.evaluate("document.getElementById('toast').getBoundingClientRect().height") >= 44
    page.click("#toast")
    assert not page.evaluate("document.getElementById('toast').classList.contains('show')") and errors == []


# ------------------------------------------------------------------------------------------------ over a theme
def test_contrast_over_a_theme(browser, on, monkeypatch):          # noqa: F811
    monkeypatch.setattr(app, "today", lambda: DAYS["tree"])
    set_prefs(enabled="1", mode="system")
    seed(disc=True, flatrate=["disney_plus"])
    page, errors = open_page(browser, on, reduced_motion="reduce")
    wait_for_art(page, "tree")
    open_movie(page)
    page.click("[data-play=stream]")
    wait_status(page, "Sent to the TV.")
    selectors = ["#detail-play-box .detail-label", ".play-line", "#detail-play-status"]
    colors = {sel: rgb_of(page.evaluate("(s) => getComputedStyle(document.querySelector(s)).color", sel)) for sel in selectors}
    page.add_style_tag(content="""#scene { background-image: none !important; background-color: #fff !important; }
        #scene .scene-glow { opacity: 1 !important; animation: none !important; }
        .scene-lights { display: none !important; }
        * { color: transparent !important; text-shadow: none !important; }""")
    for sel in selectors:
        centre = page.evaluate("""(s) => { const e = document.querySelector(s); e.scrollIntoView({block: 'center'});
            const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }""", sel)
        bg = pixel(page, centre[0], centre[1])
        assert ratio(colors[sel], bg) >= 4.5, (sel, colors[sel], bg, round(ratio(colors[sel], bg), 2))
    assert errors == []


# ------------------------------------------------------------------------------------------------ the main page (Task 5)
def seed_paused(title, **kw):
    """A movie, as `seed` makes it, that is paused partway: it sits in Continue Watching. Returns its id."""
    movie_id = seed(title, **kw)
    with app.app.app_context():
        con = app.get_db()
        viewing_id = app.viewings.watch_tonight(con, movie_id)
        con.execute("UPDATE viewings SET status='paused', watched_seconds=2400 WHERE id=?", (viewing_id,))
        con.commit()
    return movie_id


def draw(page):
    """Press Surprise us and wait for the three picks."""
    page.click("#surprise-btn")
    page.wait_for_function("document.querySelectorAll('#surprise-picks .movie-card').length === 3")


def toast_text(page):
    return page.inner_text("#toast")


def wait_toast(page, text, timeout=5000):
    page.wait_for_function("(t) => document.getElementById('toast').textContent === t", arg=text, timeout=timeout)


def continue_loads(page):
    """A list that fills with every GET /api/continue the page makes from here on."""
    loads = []
    page.on("request", lambda r: loads.append(r.url) if r.method == "GET" and r.url.endswith("/api/continue") else None)
    return loads


def settle(page, loads, count):
    """Wait for `count` loads of the row, then a little longer: a stray extra one shows up in `loads`."""
    for _ in range(100):                                  # page.wait_for_timeout lets the request events in; time.sleep would not
        if len(loads) >= count:
            break
        page.wait_for_timeout(50)
    assert len(loads) >= count, "the row never reloaded"
    page.wait_for_timeout(300)


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_continue_row_play(browser, on, viewport):          # noqa: F811
    seed_paused("Elf", flatrate=["netflix"])
    on.hook.delay = 0.3                                  # long enough to see the opening line
    page, errors = open_page(browser, on, viewport)
    page.wait_for_selector("#continue-row .continue-item")
    assert page.inner_text("#continue-row .continue-status") != "Tonight"
    button = page.locator("#continue-row .continue-play")
    assert button.count() == 1 and button.inner_text() == "▶ Play"
    assert button.get_attribute("aria-label") == "Play Elf on the TV"
    page.click("#continue-row .continue-play")
    wait_toast(page, "Opening Netflix on the Family Room TV…")
    wait_for(lambda: len(on.hook.calls) == 1)
    assert on.hook.calls == [{"event": "wonderful_play", "mode": "stream", "source": "Netflix", "title": "Elf"}]
    page.wait_for_function("document.querySelector('#continue-row .continue-status').textContent === 'Tonight'")
    wait_toast(page, "Sent to the TV.")
    assert page.locator("#continue-actions").count() == 0         # the tap did not open the sheet
    assert _side_scroll(page) <= 0 and errors == []
    page.click("#continue-row .continue-item")                    # the poster still does
    page.wait_for_selector("#continue-actions")
    assert page.inner_text("#continue-actions .sheet-title") == "Elf"


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_surprise_pick_play_does_not_open_the_page(browser, on, viewport):          # noqa: F811
    for title in ("Elf", "Home Alone", "Jingle All the Way"):
        seed(title, flatrate=["netflix"])
    page, errors = open_page(browser, on, viewport)
    draw(page)
    assert page.locator("#surprise-picks .pick-play").count() == 3
    hash_before = page.evaluate("location.hash")
    first = page.locator("#surprise-picks .pick-play").first
    label = first.get_attribute("aria-label")
    assert label.startswith("Play ") and label.endswith(" on the TV")
    first.click()
    wait_toast(page, "Sent to the TV.")
    page.wait_for_timeout(300)
    assert len(on.hook.calls) == 1 and on.hook.calls[0]["mode"] == "stream"
    assert page.evaluate("location.hash") == hash_before and page.is_visible("#grid-view")
    assert label == f"Play {on.hook.calls[0]['title']} on the TV"
    assert _side_scroll(page) <= 0 and errors == []
    page.click("#surprise-picks .movie-card")                     # the poster still opens the movie's page
    page.wait_for_function("location.hash.startsWith('#/m/')")
    page.wait_for_selector("#detail .detail-title")


def test_no_play_button_when_nothing_applies(browser, on):          # noqa: F811
    seed("Elf", rent=["netflix"])
    seed("Prancer", rent=["netflix"])
    seed("Home Alone", flatrate=["netflix"])
    seed_paused("Arthur Christmas", rent=["disney_plus"])
    seed_paused("The Santa Clause", flatrate=["disney_plus"])
    page, errors = open_page(browser, on)
    page.wait_for_selector("#continue-row .continue-item")
    assert page.locator("#continue-row .continue-item").count() == 2
    assert page.eval_on_selector_all("#continue-row .continue-play", "els => els.map(e => e.getAttribute('aria-label'))") == [
        "Play The Santa Clause on the TV"]                        # the rent-only one has none
    streamable = {"Home Alone", "The Santa Clause"}
    for _ in range(30):                                       # five movies, three picks: until a streamable one is drawn
        draw(page)
        if streamable & set(page.eval_on_selector_all("#surprise-picks .card-title", "els => els.map(e => e.textContent)")):
            break
    cards = page.eval_on_selector_all("#surprise-picks .pick", """els => els.map(e => [e.querySelector('.card-title').textContent,
        e.querySelectorAll('.pick-play').length])""")
    assert any(n for _, n in cards) and any(not n for _, n in cards)       # both kinds are on screen
    assert all(bool(n) == (title in streamable) for title, n in cards), cards
    assert errors == []


def test_no_play_buttons_when_off(browser, env):          # noqa: F811
    seed_paused("Elf", flatrate=["netflix"])
    seed("Home Alone", disc=True, flatrate=["netflix"])
    seed("Prancer", flatrate=["netflix"])
    page, errors = open_page(browser, env)                 # HA_PLAY_WEBHOOK_URL is empty
    page.wait_for_selector("#continue-row .continue-item")
    draw(page)
    assert page.locator(".pick-play, .continue-play").count() == 0 and errors == []


def test_grid_has_no_play_buttons(browser, on):          # noqa: F811
    seed_paused("Elf", flatrate=["netflix"])
    seed("Home Alone", disc=True, flatrate=["netflix"])
    seed("Prancer", flatrate=["netflix"])
    page, errors = open_page(browser, on)
    page.wait_for_selector("#continue-row .continue-play")
    draw(page)
    assert page.locator("#continue-row .continue-play, #surprise-picks .pick-play").count() == 4     # the control: they are there
    assert page.locator("#grid .movie-card").count() == 3
    assert page.locator("#grid .pick-play, #grid .continue-play, #grid button").count() == 0 and errors == []


def test_disc_toast_stays(browser, on):          # noqa: F811
    for title in ("Elf", "Home Alone", "Prancer"):
        seed(title, disc=True)
    page, errors = open_page(browser, on)
    draw(page)
    page.click("#surprise-picks .pick-play")
    wait_toast(page, f"Sent to the TV. {SHELF_LINE}: go get it!")
    assert on.hook.calls[0]["mode"] == "disc" and on.hook.calls[0]["source"] == "AV Receiver"
    page.wait_for_timeout(5000)                           # not the 4-second kind
    assert page.evaluate("document.getElementById('toast').classList.contains('show')")
    assert SHELF_LINE in toast_text(page)
    page.click("#toast")
    assert not page.evaluate("document.getElementById('toast').classList.contains('show')") and errors == []


def test_a_failed_play_says_so_in_the_toast(browser, on):          # noqa: F811
    seed_paused("Elf", flatrate=["netflix"])
    on.hook.status = 500
    page, errors = open_page(browser, on)
    page.click("#continue-row .continue-play")
    wait_toast(page, "Couldn't reach the TV. Elf is on for tonight; use the remote.")
    page.wait_for_function("document.querySelector('#continue-row .continue-status').textContent === 'Tonight'")
    assert errors == []


def test_double_tap_sends_one_request(browser, on):          # noqa: F811
    for title in ("Elf", "Home Alone", "Prancer"):
        seed(title, flatrate=["netflix"])
    seed_paused("Arthur Christmas", flatrate=["netflix"])
    on.hook.delay = 0.5                                   # the first request is still in flight for the second tap
    page, errors = open_page(browser, on)
    draw(page)
    page.evaluate("() => { const b = document.querySelector('#surprise-picks .pick-play'); b.click(); b.click(); }")
    wait_toast(page, "Sent to the TV.")
    page.wait_for_timeout(400)
    assert len(on.hook.calls) == 1
    on.hook.calls.clear()                                  # nor can a second button start another while one is pending
    page.evaluate("() => { document.querySelector('#continue-row .continue-play').click();"
                  " document.querySelector('#surprise-picks .pick-play').click(); }")
    wait_toast(page, "Sent to the TV.")
    page.wait_for_timeout(400)
    assert len(on.hook.calls) == 1 and errors == []


def test_second_visit_to_the_main_page(browser, on):          # noqa: F811
    for title in ("Elf", "Home Alone", "Prancer"):
        seed(title, flatrate=["netflix"])
    seed_paused("Arthur Christmas", flatrate=["netflix"])
    page, errors = open_page(browser, on)
    loads = continue_loads(page)
    page.wait_for_selector("#continue-row .continue-play")
    draw(page)
    page.click("#surprise-picks .movie-card")             # to a movie's page and back
    page.wait_for_selector("#detail-where")
    page.click("#back-link")
    page.wait_for_selector("#grid-view", state="visible")
    draw(page)
    for sel, expected in (("#surprise-picks .pick-play", 1), ("#continue-row .continue-play", 2)):
        before = len(loads)
        page.click(sel)
        wait_for(lambda: len(on.hook.calls) == expected)
        settle(page, loads, before + 1)
        assert len(on.hook.calls) == expected, sel         # one request for the tap, not two
        assert len(loads) == before + 1, sel               # and the row reloaded once: a listener wired twice would reload twice
    assert page.locator("#surprise-picks .movie-card").count() == 3 and errors == []


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_play_buttons_fit(browser, on, viewport):          # noqa: F811
    for title in ("Elf", "Home Alone", "Prancer"):
        seed_paused(title, flatrate=["netflix"])
    seed("Arthur Christmas", flatrate=["netflix"])
    page, errors = open_page(browser, on, viewport)
    page.wait_for_selector("#continue-row .continue-play")
    draw(page)
    sizes = page.eval_on_selector_all(".pick-play, .continue-play", "els => els.map(e => { const r = e.getBoundingClientRect(); return [r.width, r.height]; })")
    assert len(sizes) >= 4 and all(w >= 44 and h >= 44 for w, h in sizes), sizes
    for sel in ("#surprise-picks .movie-card", "#continue-row .continue-item"):
        lefts = page.eval_on_selector_all(sel, "els => els.map(e => Math.round(e.getBoundingClientRect().left))")
        assert len(lefts) == 3 and len(set(lefts)) == 3, (sel, lefts)         # three columns remain
    for sel in (".pick-play", ".continue-play"):
        colors = page.evaluate("(s) => { const c = getComputedStyle(document.querySelector(s)); return [c.color, c.backgroundColor]; }", sel)
        assert ratio(rgb_of(colors[0]), rgb_of(colors[1])) >= 4.5, (sel, colors)
    inside = page.evaluate("""() => [...document.querySelectorAll('.pick-play')].every(b => {
        const r = b.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth; })""")
    assert inside and _side_scroll(page) <= 0 and errors == []
