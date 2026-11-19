"""It's a Wonderful App: the family's Christmas movie picker. Flask + SQLite, built like Matinee.

app.py holds the Flask object, the request hooks and every route. The logic lives in route-free sibling modules
(settings, common, db, auth, ...); see CLAUDE.md for the rules.

Routes (every one needs an editor, auth.editor_required, except where noted):
  /                 the single-page app (static/index.html with versioned modules)
  /api/health       {"ok": true, "schema": "1"}
  /api/me           {"editor": "<who>"}
  /api/tmdb/search  TMDB search for the add sheet (?q=)
  /api/movies       GET the list, POST {tmdb_id, tmdb_type} to add; /api/movies/<id> GET, PUT, DELETE
  /api/search       our list: an exact title, else the local filter (?q=)
  /api/services     GET the streaming services, PUT {key, status} to subscribe, consider or ignore one
  /api/movies/<id>/providers/refresh   POST: ask TMDB where it streams now
  (ownership and shelf come from Matinee: asked on add, on the detail view when over a day old, and nightly)
  /posters/<name>   the local poster and backdrop copies
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
from settings import ANTHROPIC_API_KEY, AI_MODEL, AI_DAILY_CAP, UA, SERVICES_FILE  # noqa: F401
from common import RATING_ERROR, clean, make_err, validate_rating, round_half_up, today, now_iso  # noqa: F401
from db import SCHEMA, SCHEMA_VERSION, connect, get_db, migrate, init_db  # noqa: F401
from auth import KEY_IDENTITY, presented_key, lan_host, access_identity, cross_site  # noqa: F401
from auth import editor_required, hook_required  # noqa: F401
from tmdb import TmdbError  # noqa: F401
import images, matinee, movies, providers, search, tmdb  # noqa: F401  (route-free modules; use images.X, movies.X, ...)


# ===================================================================== split modules
# app.py re-exports every name the sibling modules define, so `app.X` works everywhere. A write to app.X (monkeypatch
# in the tests) also rebinds X in each split module that holds it, so their code reads the new value. Patch app.X,
# never the sibling module. A new module goes here and in installer/build.sh's cp line.
_SPLIT_MODULES = ("settings", "common", "db", "auth", "tmdb", "images", "matinee", "movies", "providers", "search")


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


# ============================================================================ movies
@app.errorhandler(TmdbError)
def tmdb_error(e):
    return make_err(e.status, e.message, reason=e.reason)


@app.get("/api/tmdb/search")
@editor_required
def api_tmdb_search():
    """{"results": [{tmdb_id, tmdb_type, title, year, poster_path, on_list}], "message": null | "…"}: on_list is the
    movie's id when it is already on our list. No match is a 200 with an empty list and a message."""
    q = clean(request.args.get("q"))
    if not q:
        return make_err(400, "Type a title to search for.")
    results = tmdb.search(q)
    have = {(r["tmdb_type"], r["tmdb_id"]): r["id"] for r in get_db().execute("SELECT id, tmdb_type, tmdb_id FROM movies")}
    for r in results:
        r["on_list"] = have.get((r["tmdb_type"], r["tmdb_id"]))
    return jsonify(results=results, message=None if results else f'TMDB has nothing called "{q}".')


@app.get("/api/search")
@editor_required
def api_search():
    """{"mode": "exact" | "local", "matches": [{"id", "why"}], "suggestions": []}: an exact title (normalized) is the
    only match; otherwise the local filter. An empty q is the whole list. Suggestions come with AI search (Task 12)."""
    con = get_db()
    q = clean(request.args.get("q")) or ""
    hit = search.exact(con, q)
    if hit is not None:
        return jsonify(mode="exact", matches=[{"id": hit, "why": "exact title"}], suggestions=[])
    return jsonify(mode="local", matches=search.local_matches(con, q), suggestions=[])


@app.get("/api/movies")
@editor_required
def api_movies():
    """The list. Each movie carries `where_to_watch` read from the providers cache: no TMDB call per card."""
    con = get_db()
    return jsonify([{**movies.movie_out(r), "where_to_watch": providers.where_to_watch(con, r["id"])}
                    for r in movies.list_rows(con)])


@app.post("/api/movies")
@editor_required
def api_movie_add():
    tmdb_id, tmdb_type = movies.parse_ref(request.get_json(silent=True))
    con = get_db()
    movie_id = movies.add_movie(con, tmdb_id, tmdb_type, g.editor)
    try:
        providers.get(con, movie_id)
    except TmdbError as e:   # the movie is added; its providers arrive on the next refresh
        app.logger.warning("watch providers for movie %s: %s", movie_id, e.message)
    movies.refresh_ownership(con, movie_id)   # never fails: Matinee down means "not known yet", the nightly job retries
    return jsonify({**movies.movie_out(movies.get_row(con, movie_id)), **providers.movie_providers(con, movie_id)}), 201


@app.get("/api/movies/<int:movie_id>")
@editor_required
def api_movie(movie_id):
    """One movie, with where to watch from the cache and `providers_stale` (the page asks for a refresh when true).
    Ownership is asked of Matinee first when the last answer is over a day old; if Matinee can't answer, the last
    known ownership is shown with "(as of <date>)"."""
    con = get_db()
    movies.refresh_ownership_if_stale(con, movie_id)
    return jsonify({**movies.movie_out(movies.get_row(con, movie_id)), **providers.movie_providers(con, movie_id)})


@app.post("/api/movies/<int:movie_id>/providers/refresh")
@editor_required
def api_providers_refresh(movie_id):
    """Ask TMDB where this movie streams right now. A TMDB failure is a 502 and the old answer stays."""
    con = get_db()
    movies.get_row(con, movie_id)
    providers.refresh(con, movie_id)
    return jsonify(providers.movie_providers(con, movie_id))


@app.put("/api/movies/<int:movie_id>")
@editor_required
def api_movie_update(movie_id):
    con = get_db()
    movies.update_movie(con, movie_id, request.get_json(silent=True))
    return jsonify(movies.movie_out(movies.get_row(con, movie_id)))


@app.delete("/api/movies/<int:movie_id>")
@editor_required
def api_movie_remove(movie_id):
    movies.remove_movie(get_db(), movie_id)
    return jsonify(ok=True)


@app.get("/api/services")
@editor_required
def api_services():
    return jsonify(providers.list_services(get_db()))


@app.put("/api/services")
@editor_required
def api_service_status():
    """{"key": "peacock", "status": "subscribed" | "considering" | "ignore"} -> the whole list."""
    con = get_db()
    providers.set_status(con, request.get_json(silent=True))
    return jsonify(providers.list_services(con))


@app.get("/posters/<name>")
@editor_required
def poster_file(name):
    """A poster or backdrop saved by images.fetch(). Only the names images.py writes are served."""
    if not images.NAME_RE.match(name):
        return make_err(404, "No such image.")
    return send_from_directory(POSTER_DIR, name, max_age=86400)


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
