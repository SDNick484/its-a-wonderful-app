"""Playwright UI smoke at phone size (412 x 915, Android Chrome; and 360 px): the page loads, the grid has at least
three poster columns, nothing scrolls sideways, tap targets are at least 44 px.

Skipped when Playwright or Chromium is missing, except with REQUIRE_UI=1 (scripts/gate.sh and the CI "ui-smoke"
job set it), where a missing browser is a failure: a skipped smoke test is not a pass.
"""
import glob
import os
import threading

import pytest

REQUIRED = os.environ.get("REQUIRE_UI") == "1"
if REQUIRED:
    from playwright import sync_api
else:
    sync_api = pytest.importorskip("playwright.sync_api")

from conftest import _isolate

PHONE = {"width": 412, "height": 915}
SMALL_PHONE = {"width": 360, "height": 780}
CARD = ('<a class="movie-card" href="#/m/{i}"><div class="poster-wrap"><div class="poster-ph">Movie {i}</div></div>'
        '<div class="card-title">Movie {i}</div></a>')


def _chromium_path():
    roots = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "", "/opt/pw-browsers"]
    for root in filter(None, roots):
        for pat in ("chromium-*/chrome-linux64/chrome", "chromium-*/chrome-linux/chrome"):
            hits = sorted(glob.glob(os.path.join(root, pat)))
            if hits:
                return hits[-1]
    return None  # let playwright use its own default


@pytest.fixture
def server(tmp_path, monkeypatch):
    from werkzeug.serving import make_server
    core = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(core, "LAN_EDIT", True)
    # These tests were written against the plain dark look: pin that in the database (what the settings screen does),
    # so a run in December does not put a theme behind them and a light phone does not turn them light. The theme
    # tests (test_theme_ui.py) set it back themselves.
    with core.app.app_context():
        con = core.get_db()
        con.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('theme_enabled', '0'), ('theme_mode', 'dark')")
        con.commit()
    srv = make_server("127.0.0.1", 0, core.app, threaded=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    t.join(timeout=5)


@pytest.fixture
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(executable_path=_chromium_path())
        except Exception as e:  # noqa: BLE001 — no usable Chromium here
            if REQUIRED:
                pytest.fail(f"Chromium won't launch and REQUIRE_UI=1: {e}")
            pytest.skip(f"Chromium won't launch: {e}")
        yield b
        b.close()


def _open(browser, server, viewport):
    page = browser.new_page(viewport=viewport, device_scale_factor=2.625, is_mobile=True, has_touch=True)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(server + "/")
    page.wait_for_function("document.getElementById('grid-empty').textContent.includes('No movies')")
    return page, errors


def _columns(page, n=9):
    page.evaluate("(html) => { document.getElementById('grid').innerHTML = html; }",
                  "".join(CARD.format(i=i) for i in range(n)))
    return page.evaluate("new Set([...document.querySelectorAll('#grid .movie-card')]"
                         ".map(c => Math.round(c.getBoundingClientRect().left))).size")


def _side_scroll(page):
    return page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")


def test_page_loads_at_412(browser, server):
    page, errors = _open(browser, server, PHONE)
    assert page.title() == "It's a Wonderful App"
    assert page.inner_text("h1") == "It's a Wonderful App"
    assert page.is_visible("#grid-empty") and "No movies on our list yet." in page.inner_text("#grid-empty")
    assert errors == []
    assert _side_scroll(page) <= 0
    assert page.evaluate("document.querySelector('.brand').getBoundingClientRect().height") >= 44


@pytest.mark.parametrize("viewport", [PHONE, SMALL_PHONE], ids=["412px", "360px"])
def test_grid_has_three_columns_and_no_side_scroll(browser, server, viewport):
    page, _ = _open(browser, server, viewport)
    assert _columns(page) >= 3
    assert _side_scroll(page) <= 0
