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
JS_MODULES = ["add.js", "continue.js", "core.js", "detail.js", "grid.js", "main.js", "rating.js", "search.js", "settings.js", "surprise.js"]


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
    monkeypatch.setattr(core, "_matinee_failed_at", None, raising=False)   # movies.py's page-view backoff, per test
    monkeypatch.setattr(core, "_first_run_failed_at", None, raising=False)   # people.py's first-run backoff, per test
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


# ------------------------------------------------------------------------------------------------ Matinee, recorded
MATINEE_FIXTURES = FIXTURES / "matinee"
MATINEE_KEY = "matinee-test-key"
MATINEE_HOST = "movies.example.com"


class FakeMatinee:
    """Stands in for urllib.request.urlopen for Matinee's /admin/api, answering from tests/fixtures/matinee/ (shapes
    recorded from Matinee's own responses), and records each request as (method, path, body). It checks the bearer key
    (a wrong one gets Matinee's real 401). `owned_files` maps a TMDB id to the owned-answer file (any other id is "not
    owned"); title 1 is the recorded Elf. Matinee keeps a rating it is sent: after a PUT, title 1 reads back that
    `user_rating`, and a test sets `user_rating[1]` itself to stand for someone changing it in Matinee (None: unrated).
    Requests to any other host go to `other`, the urlopen that was in force
    before, so this composes with tmdb_fixtures."""

    def __init__(self, other):
        self.other = other
        self.calls = []                                # (method, path, body or None), in order
        self.headers = []                              # the Authorization header of each request
        self.owned_files = {10719: "owned_elf.json"}
        self.people_file = "people.json"               # people_five.json has a fifth person
        self.user_rating = {}                          # title id -> the rating Matinee holds now, over the recording

    def _json(self, name):
        return io.BytesIO((MATINEE_FIXTURES / name).read_bytes())

    def _http_error(self, req, code, name):
        raise urllib.error.HTTPError(req.full_url, code, "Error", {}, self._json(name) if name else None)

    def __call__(self, req, timeout=None):
        import json
        url = urllib.parse.urlparse(req.full_url)
        if url.netloc != MATINEE_HOST:
            return self.other(req, timeout=timeout)
        body = json.loads(req.data) if req.data else None
        self.calls.append((req.get_method(), url.path, body))
        self.headers.append(req.get_header("Authorization"))
        if req.get_header("Authorization") != f"Bearer {MATINEE_KEY}":
            self._http_error(req, 401, "unauthorized.json")
        m = req.get_method()
        if m == "GET" and (g := re.fullmatch(r"/admin/api/tmdb/(\d+)/owned", url.path)):
            return self._json(self.owned_files.get(int(g.group(1)), "not_owned.json"))
        if m == "GET" and url.path == "/admin/api/titles/1":
            if 1 not in self.user_rating:
                return self._json("title_detail_elf.json")
            title = json.loads((MATINEE_FIXTURES / "title_detail_elf.json").read_text())
            return io.BytesIO(json.dumps({**title, "user_rating": self.user_rating[1]}).encode())
        if m == "GET" and url.path == "/admin/api/people":
            return self._json(self.people_file)
        if m == "PUT" and url.path == "/admin/api/titles/1/rating":
            if (body["rating"] * 2) % 1:
                self._http_error(req, 400, "rating_400.json")
            self.user_rating[1] = body["rating"]
            return self._json("rating_set.json")
        if m == "POST" and url.path == "/admin/api/titles/1/watches":
            return self._json("watch_added.json")
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)


@pytest.fixture
def matinee_fixtures(client, monkeypatch):
    """Matinee answers from the recorded fixtures (no live network), with MATINEE_URL and the key set. Returns the
    FakeMatinee with its .calls list. Use it with `client`; list tmdb_fixtures before it in a test that needs both."""
    import urllib.request
    import app as core

    monkeypatch.setattr(core, "MATINEE_URL", f"http://{MATINEE_HOST}")
    monkeypatch.setattr(core, "MATINEE_API_KEY", MATINEE_KEY)
    fake = FakeMatinee(urllib.request.urlopen)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


@pytest.fixture
def matinee_down(client, monkeypatch):
    """Matinee is configured but every call fails; set `.error` to an exception to raise (default: a connection
    refused), or to an int for that HTTP status. `.calls` counts the attempts."""
    import urllib.request
    import app as core

    class Down:
        def __init__(self, other):
            self.other, self.error, self.calls = other, urllib.error.URLError(ConnectionRefusedError()), 0

        def __call__(self, req, timeout=None):
            if urllib.parse.urlparse(req.full_url).netloc != MATINEE_HOST:
                return self.other(req, timeout=timeout)    # TMDB still answers (list tmdb_fixtures first)
            self.calls += 1
            if isinstance(self.error, int):
                raise urllib.error.HTTPError(req.full_url, self.error, "Error", {}, None)
            raise self.error

    fake = Down(urllib.request.urlopen)
    monkeypatch.setattr(core, "MATINEE_URL", f"http://{MATINEE_HOST}")
    monkeypatch.setattr(core, "MATINEE_API_KEY", MATINEE_KEY)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake
