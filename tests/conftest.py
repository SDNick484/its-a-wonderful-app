import io
import os
import re
import tempfile
import urllib.error
import urllib.parse
from pathlib import Path

import pytest

# Importing app runs init_db() on DATA_DIR, so point it at a throwaway folder before any test imports it.
if not os.environ.get("DATA_DIR"):
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="wonderful-test-conftest-")

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"   # tmdb/, matinee/, anthropic/: recorded responses, no live network

# The SPA's ES modules in static/js/. tests/test_js_modules.py checks this list is complete.
JS_DIR = ROOT / "static" / "js"
JS_MODULES = ["add.js", "core.js", "detail.js", "grid.js", "main.js", "settings.js"]


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


# ------------------------------------------------------------------------------------------------ TMDB, recorded
TMDB_TOKEN = "test-token"
TMDB_FIXTURES = FIXTURES / "tmdb"


class FakeTmdb:
    """Stands in for urllib.request.urlopen: answers TMDB API calls from tests/fixtures/tmdb/ and poster downloads
    from poster.jpg, and records what was asked. movie_<id>.json and tv_<id>.json hold the details, search_<query
    letters>.json a search (an unknown query gets search_no_results.json); any other title is a 404. Watch providers
    come from the file `provider_files` names for a TMDB id (a test may add to it); any other id is a 404."""

    def __init__(self):
        self.api, self.images = [], []
        self.provider_files = {10719: "providers_10719.json", 508439: "providers_klaus.json",
                               900001: "providers_empty.json", 990001: "providers_peacock.json",
                               990002: "providers_unknown.json"}

    def __call__(self, req, timeout=None):
        url = urllib.parse.urlparse(req.full_url)
        if url.netloc == "image.tmdb.org":
            self.images.append(req.full_url)
            return io.BytesIO((TMDB_FIXTURES / "poster.jpg").read_bytes())
        assert url.netloc == "api.themoviedb.org", req.full_url
        assert req.get_header("Authorization") == f"Bearer {TMDB_TOKEN}"
        self.api.append(req.full_url)
        if url.path == "/3/search/multi":
            slug = re.sub(r"[^a-z0-9]", "", urllib.parse.parse_qs(url.query)["query"][0].lower())
            path = TMDB_FIXTURES / f"search_{slug}.json"
            path = path if path.is_file() else TMDB_FIXTURES / "search_no_results.json"
        elif re.fullmatch(r"/3/(movie|tv)/\d+/watch/providers", url.path):
            name = self.provider_files.get(int(url.path.split("/")[3]))
            path = TMDB_FIXTURES / name if name else None
            if path is None or not path.is_file():
                raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        else:
            m = re.fullmatch(r"/3/(movie|tv)/(\d+)", url.path)
            path = TMDB_FIXTURES / f"{m.group(1)}_{m.group(2)}.json" if m else None
            if path is None or not path.is_file():
                raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        return io.BytesIO(path.read_bytes())


@pytest.fixture
def tmdb_fixtures(client, monkeypatch):
    """TMDB answers from the recorded fixtures (no live network). Returns the FakeTmdb with its .api and .images
    call lists. Use it with `client` (it shares that app and database)."""
    import urllib.request
    import app as core

    monkeypatch.setattr(core, "TMDB_READ_TOKEN", TMDB_TOKEN)
    fake = FakeTmdb()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


@pytest.fixture
def tmdb_down(client, monkeypatch):
    """TMDB answers every call with HTTP 500."""
    import urllib.request
    import app as core

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "Server Error", {}, None)

    monkeypatch.setattr(core, "TMDB_READ_TOKEN", TMDB_TOKEN)
    monkeypatch.setattr(urllib.request, "urlopen", boom)
