"""Home Assistant (spec §8.5, §10.2). Outbound: the Family Room movie log. Every finished viewing, owned or not, is
posted to HA_WEBHOOK_URL (the same webhook Matinee uses) with Matinee's ha_payload() shape and event name plus
`"source": "wonderful"`, so the automation that keeps the dashboard's movie log takes it unchanged. The inbound TV events
(/hooks/tv) arrive with the TV webhook task. Route-free; no Flask object here (see CLAUDE.md).

The webhook id in HA_WEBHOOK_URL is its only credential, so the URL is never logged: a failure is one warning naming the
host and the kind of failure (an HTTP status or an exception class), never the URL or str(exc), which can echo it."""
import json, logging, threading, urllib.error, urllib.parse, urllib.request

from flask import current_app, has_app_context

from settings import HA_WEBHOOK_URL, UA

TIMEOUT = 5
EVENT = "matinee_watch_logged"   # Matinee's event name: the HA automation listens for this one


def _host(url):
    """The webhook URL's host, for log lines: the rest of the URL is the credential."""
    try:
        return urllib.parse.urlsplit(url).hostname or "?"
    except ValueError:
        return "?"


def _logger():
    """The Flask app's logger when there is an app context (the thread has none, so it is taken before it starts)."""
    return current_app.logger if has_app_context() else logging.getLogger("wonderful")


def _post(url, payload, log):
    """POST `payload` as JSON. Runs on a daemon thread and never raises; a failure is one host-only warning."""
    host = _host(url)
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            status = getattr(resp, "status", 200)
        if not 200 <= status < 300:
            log.warning("Home Assistant webhook (host %s) answered HTTP %s", host, status)
    except urllib.error.HTTPError as e:
        log.warning("Home Assistant webhook (host %s) answered HTTP %s", host, e.code)
        try:
            e.close()
        except Exception:  # noqa: BLE001 — nothing to read; the warning is already out
            pass
    except Exception as e:  # noqa: BLE001 — fire and forget: whatever goes wrong is a warning, never the caller's problem
        log.warning("Home Assistant webhook (host %s) failed: %s", host, type(e).__name__)


def post_watch_logged(payload):
    """Tell Home Assistant a movie was watched: fire and forget on a daemon thread named "ha-webhook". Does nothing
    when HA_WEBHOOK_URL is empty. `payload` is built by the caller (viewings.ha_payload) on its own connection."""
    url = HA_WEBHOOK_URL
    if not url:
        return
    log = _logger()
    try:
        threading.Thread(target=_post, args=(url, dict(payload), log), daemon=True, name="ha-webhook").start()
    except Exception as e:  # noqa: BLE001 — e.g. no thread to be had: still never the caller's problem
        log.warning("Home Assistant webhook (host %s) not sent: %s", _host(url), type(e).__name__)
