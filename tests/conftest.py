import os
import tempfile
from pathlib import Path

import pytest

# Importing app runs init_db() on DATA_DIR, so point it at a throwaway folder before any test imports it.
if not os.environ.get("DATA_DIR"):
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="wonderful-test-conftest-")

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"   # tmdb/, matinee/, anthropic/: recorded responses, no live network

# The SPA's ES modules in static/js/. tests/test_js_modules.py checks this list is complete.
JS_DIR = ROOT / "static" / "js"
JS_MODULES = ["core.js", "main.js"]


def _no_network(*a, **kw):
    raise AssertionError("tests must not touch the network")


def _isolate(tmp_path, monkeypatch):
    """A fresh database and data folders under tmp_path, no keys, no network. Patch app.X, never a sibling module
    (CLAUDE.md): app.py copies the write into every module that holds X."""
    import urllib.request
    import app as core

    monkeypatch.setattr(core, "DATA_DIR", tmp_path)
    monkeypatch.setattr(core, "DB_PATH", tmp_path / "wonderful.db")
    monkeypatch.setattr(core, "POSTER_DIR", tmp_path / "posters")
    monkeypatch.setattr(core, "ART_DIR", tmp_path / "art")
    monkeypatch.setattr(core, "_standalone_db", None)
    monkeypatch.setattr(core, "LAN_HOSTS", set())
    monkeypatch.setattr(core, "ADMIN_EMAILS", set())
    monkeypatch.setattr(core, "CF_TEAM_DOMAIN", "")
    monkeypatch.setattr(core, "CF_AUD", "")
    monkeypatch.setattr(core, "WONDERFUL_API_KEY", "")
    monkeypatch.setattr(core, "HA_HOOK_SECRET", "")
    monkeypatch.setattr(core, "HA_WEBHOOK_URL", "")
    monkeypatch.setattr(core, "TMDB_READ_TOKEN", "")
    monkeypatch.setattr(core, "MATINEE_API_KEY", "")
    monkeypatch.setattr(core, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(urllib.request, "urlopen", _no_network)
    core.init_db()
    return core


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A test client with the LAN identity: LAN_EDIT=1 and the default Host (localhost)."""
    core = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(core, "LAN_EDIT", True)
    with core.app.test_client() as c:
        yield c


@pytest.fixture
def anon_client(tmp_path, monkeypatch):
    """A test client nobody signed in on: LAN_EDIT=0, no key, no Access JWT."""
    core = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(core, "LAN_EDIT", False)
    with core.app.test_client() as c:
        yield c


@pytest.fixture
def app_ctx(tmp_path, monkeypatch):
    """An application context on an isolated database, for code that calls abort() or get_db()."""
    core = _isolate(tmp_path, monkeypatch)
    with core.app.app_context():
        yield core
