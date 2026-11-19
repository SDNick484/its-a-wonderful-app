"""The Home Assistant movie log, outbound (spec §8.5, decision 23; plan Task 10): ha.post_watch_logged posts the payload
on a daemon thread, does nothing without HA_WEBHOOK_URL, and a failure is one warning naming the host only (the webhook
id in the URL is its credential). The payload's shape is tested with a finish in tests/test_viewings.py."""
import json
import logging
import threading
import urllib.error
import urllib.request

import pytest

import app
from test_viewings import HA_URL, join_ha

PAYLOAD = {"event": "matinee_watch_logged", "source": "wonderful", "title": "Klaus", "year": 2019, "runtime": 96,
           "certification": "PG", "formats": [], "location": None, "watched_date": "2025-12-13", "title_id": None}


@pytest.fixture
def hooked(app_ctx, monkeypatch):
    monkeypatch.setattr(app, "HA_WEBHOOK_URL", HA_URL)
    return app_ctx


def _answer(monkeypatch, outcome):
    """urlopen that records each request, then raises `outcome` (an exception) or answers with that HTTP status."""
    seen = []

    class Resp:
        status = outcome

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake(req, timeout=None):
        seen.append(req)
        if isinstance(outcome, BaseException):
            raise outcome
        return Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return seen


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def test_posts_the_payload_on_a_daemon_thread(hooked, monkeypatch, caplog):
    seen = _answer(monkeypatch, 200)
    started = []
    real = threading.Thread

    def spy(*a, **kw):
        t = real(*a, **kw)
        started.append(t)
        return t

    monkeypatch.setattr(threading, "Thread", spy)
    app.ha.post_watch_logged(PAYLOAD)
    join_ha()
    assert [t.daemon for t in started] == [True] and started[0].name == "ha-webhook"
    assert len(seen) == 1 and seen[0].full_url == HA_URL and seen[0].get_method() == "POST"
    assert json.loads(seen[0].data) == PAYLOAD and seen[0].get_header("Content-type") == "application/json"
    assert _warnings(caplog) == []


def test_no_webhook_url_posts_nothing(app_ctx, monkeypatch):
    monkeypatch.setattr(app, "HA_WEBHOOK_URL", "")
    seen = _answer(monkeypatch, 200)
    app.ha.post_watch_logged(PAYLOAD)
    join_ha()
    assert seen == []


@pytest.mark.parametrize("code", [500, 404])
def test_http_error_is_a_host_only_warning(hooked, monkeypatch, caplog, code):
    _answer(monkeypatch, urllib.error.HTTPError(HA_URL, code, "Error", {}, None))
    app.ha.post_watch_logged(PAYLOAD)                     # never raises
    join_ha()
    said = _warnings(caplog)
    assert said == [f"Home Assistant webhook (host ha.example.com) answered HTTP {code}"]
    assert "test-webhook-id" not in caplog.text


def test_odd_status_is_a_warning(hooked, monkeypatch, caplog):
    _answer(monkeypatch, 302)
    app.ha.post_watch_logged(PAYLOAD)
    join_ha()
    assert _warnings(caplog) == ["Home Assistant webhook (host ha.example.com) answered HTTP 302"]


@pytest.mark.parametrize("error", [urllib.error.URLError(f"cannot reach {HA_URL}"), TimeoutError(HA_URL)],
                         ids=["unreachable", "timeout"])
def test_unreachable_is_a_host_only_warning(hooked, monkeypatch, caplog, error):
    _answer(monkeypatch, error)
    app.ha.post_watch_logged(PAYLOAD)
    join_ha()
    assert _warnings(caplog) == [f"Home Assistant webhook (host ha.example.com) failed: {type(error).__name__}"]
    assert "test-webhook-id" not in caplog.text           # str(exc) can echo the URL: it is never logged
