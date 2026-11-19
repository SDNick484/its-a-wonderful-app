"""It's a Wonderful App: the family's Christmas movie picker. Flask + SQLite, built like Matinee.

app.py holds the Flask object, the request hooks and every route. The logic lives in route-free sibling modules
(settings, common, db, auth, ...); see CLAUDE.md for the rules.

Routes (every one needs an editor, auth.editor_required, except where noted):
  /                 the single-page app (static/index.html with versioned modules)
  /api/health       {"ok": true, "schema": "1"}
  /api/me           {"editor": "<who>"}
  /hooks/tv         Home Assistant TV events (auth.hook_required: X-Hook-Secret)
  /static/<path>    CSS, ES modules, fonts: no auth (no data in them)

Environment: see settings.py and .env.example (/etc/conf.d/wonderful on the host).
"""
import hashlib, json, re, sys, types

from flask import Flask, g, jsonify, make_response, request, send_from_directory

# Moved out of app.py and re-exported: tests and ops scripts use them as app.<name>.
from settings import APP_NAME, APP_DIR, _load_env, parse_hosts, PORT, DATA_DIR, DB_PATH, POSTER_DIR, ART_DIR  # noqa: F401
from settings import CF_TEAM_DOMAIN, CF_AUD, ADMIN_EMAILS, LAN_EDIT, LAN_HOSTS, WONDERFUL_API_KEY, HA_HOOK_SECRET  # noqa: F401
from settings import TMDB_READ_TOKEN, TMDB_API, TMDB_IMG, MATINEE_URL, MATINEE_API_KEY, HA_WEBHOOK_URL  # noqa: F401
from settings import ANTHROPIC_API_KEY, AI_MODEL, AI_DAILY_CAP, UA  # noqa: F401
from common import RATING_ERROR, clean, make_err, validate_rating, round_half_up, today, now_iso  # noqa: F401
from db import SCHEMA, SCHEMA_VERSION, connect, get_db, migrate, init_db  # noqa: F401
from auth import KEY_IDENTITY, presented_key, lan_host, access_identity, cross_site  # noqa: F401
from auth import editor_required, hook_required  # noqa: F401


# ===================================================================== split modules
# app.py re-exports every name the sibling modules define, so `app.X` works everywhere. A write to app.X (monkeypatch
# in the tests) also rebinds X in each split module that holds it, so their code reads the new value. Patch app.X,
# never the sibling module. A new module goes here and in installer/build.sh's cp line.
_SPLIT_MODULES = ("settings", "common", "db", "auth")


class _AppModule(types.ModuleType):
    # db.get_db() rebinds _standalone_db itself, so app keeps no copy: this property reads and writes db.py's.
    _standalone_db = property(lambda self: sys.modules["db"]._standalone_db,
                              lambda self, value: setattr(sys.modules["db"], "_standalone_db", value))
    # auth.access_identity() caches the Access key set in auth._jwks; same arrangement.
    _jwks = property(lambda self: sys.modules["auth"]._jwks,
                     lambda self, value: setattr(sys.modules["auth"], "_jwks", value))

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for mod in _SPLIT_MODULES:
            if name in vars(sys.modules[mod]):
                setattr(sys.modules[mod], name, value)


sys.modules[__name__].__class__ = _AppModule

app = Flask(__name__, static_folder=None)


@app.teardown_appcontext
def _close(_exc):
    con = g.pop("db", None)
    if con is not None:
        con.close()


@app.after_request
def security_headers(resp):
    """Baseline headers on every response. No script-src/style-src policy yet: inline style="" attributes are
    house style, which a strict CSP would block."""
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("Content-Security-Policy", "frame-ancestors 'self'")
    return resp


# ============================================================================= pages
_asset_cache = {"key": None, "versions": {}}


def _asset_files():
    """style.css plus every ES module under static/js/."""
    static = APP_DIR / "static"
    files = [static / "style.css"] + sorted((static / "js").glob("*.js"))
    return [f for f in files if f.is_file()]


def asset_versions():
    """{"style.css": …, "js/<name>.js": …}: the first 10 hex chars of each file's SHA-256. Re-hashed only when a
    file's mtime or size changes or a module is added or removed."""
    try:
        static = APP_DIR / "static"
        files = _asset_files()
        key = (str(static),) + tuple((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in files)
        if key != _asset_cache["key"]:
            _asset_cache["versions"] = {f.relative_to(static).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()[:10]
                                        for f in files}
            _asset_cache["key"] = key
        return dict(_asset_cache["versions"])
    except OSError:
        return {}


def _module_tags(versions):
    """The import map, modulepreload links and versioned entry script that replace index.html's
    <script type="module" src="/static/js/main.js">.

    Modules import each other as "./core.js". The browser resolves that to /static/js/core.js, the import map
    rewrites it to /static/js/core.js?v=<hash>, and a ?v= URL is cached for a year. So a warm load fetches no
    module at all, and an edited module is the only one fetched again. The map has to come before the first
    module script, or the browser ignores it."""
    url = {k: f"/static/{k}?v={v}" for k, v in sorted(versions.items()) if k.startswith("js/")}
    deps = {f"/static/{k}": u for k, u in url.items() if k != "js/main.js"}
    tags = ['<script type="importmap">' + json.dumps({"imports": deps}) + "</script>"]
    tags += [f'<link rel="modulepreload" href="{u}">' for u in deps.values()]
    tags.append(f'<script type="module" src="{url.get("js/main.js", "/static/js/main.js")}"></script>')
    return "\n  ".join(tags)


def render_index():
    versions = asset_versions()
    html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")
    html = re.sub(r'href="/static/style\.css(?:\?v=[^"]*)?"',
                  f'href="/static/style.css?v={versions.get("style.css", "1")}"', html)
    html = re.sub(r'<script type="module" src="/static/js/main\.js(?:\?v=[^"]*)?"></script>',
                  lambda _m: _module_tags(versions), html)
    resp = make_response(html)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.get("/")
@editor_required
def index():
    return render_index()


@app.get("/static/<path:p>")
def static_files(p):
    """CSS, ES modules and fonts. Public on purpose (spec: static files are the one exception): they hold no data."""
    if request.args.get("v"):
        return send_from_directory(APP_DIR / "static", p, max_age=31536000)
    if p.startswith("js/"):
        # Only a browser without import maps asks for a module with no ?v=. Revalidate every time (ETag, 304)
        # so it can never run an old module beside a new one.
        resp = send_from_directory(APP_DIR / "static", p, max_age=0)
        resp.cache_control.no_cache = True
        return resp
    return send_from_directory(APP_DIR / "static", p, max_age=60)


# =============================================================================== api
@app.get("/api/health")
@editor_required
def health():
    row = get_db().execute("SELECT v FROM meta WHERE k='schema'").fetchone()
    return jsonify(ok=True, schema=row["v"] if row else None)


@app.get("/api/me")
@editor_required
def me():
    return jsonify(editor=g.editor)


# ============================================================================= hooks
@app.post("/hooks/tv")
@hook_required
def hook_tv():
    """Home Assistant TV events (spec §10.2). The rules arrive with the TV webhook task; until then an
    authenticated event is accepted and changes nothing."""
    return jsonify(ok=True, applied=False)


init_db()

if __name__ == "__main__":   # development server; the host runs gunicorn (installer/setup-head.sh)
    app.run(host="0.0.0.0", port=PORT, debug=False)
