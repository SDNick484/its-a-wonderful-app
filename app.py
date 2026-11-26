"""It's a Wonderful App: the family's Christmas movie picker. Flask + SQLite, built like Matinee.

app.py holds the Flask object, the request hooks and every route. The logic lives in route-free sibling modules
(settings, common, db, auth, ...); see CLAUDE.md for the rules.

Routes (every one needs an editor, auth.editor_required, except where noted):
  /                 the single-page app (static/index.html with versioned modules)
  /healthz          no sign-in: {"status": "ok"}, or 503 {"status": "unavailable"}; for a monitor, nothing else
  /api/health       {"ok": true, "schema": "1"}
  /api/me           {"editor": "<who>"}
  /api/tmdb/search  TMDB search for the add sheet (?q=)
  /api/movies       GET the list, POST {tmdb_id, tmdb_type} to add; /api/movies/<id> GET, PUT, DELETE
  /api/search       our list: an exact title, else smart search (AI), else the local filter (?q=)
  /api/surprise     POST {filters, exclude}: three random picks from our list (the Surprise us button)
  /api/people       GET the family (copied from Matinee on first run), POST {name, kind, color} to add one here;
                    POST /api/people/sync copies Matinee's people again
  /api/movies/<id>/ratings/<person_id>   PUT {"rating": 8.5 | null}: one person's rating (0.5 steps), null clears it
  /api/movies/<id>/rating-conflict       POST {"choice": "ours" | "matinee" | "dismiss"}: settle "Matinee says 7, we
                    say 8.9" (the family rating is kept in step with Matinee's, sync.py)
  /api/movies/<id>/tonight   POST {"people": [ids]}?: Watch tonight (spec §10.1) -> the viewing
  /api/movies/<id>/watched   POST {"finished_on": "2026-12-12", "people": [ids]?}: Log date, a night nobody logged at
                    the time -> the viewing and the movie's Watched list (Matinee gets the watch)
  /api/continue     GET the Continue Watching row; /api/prompt GET the "Did you finish?" question, or null
  /api/viewings/<id>/keep | not-yet | finish | abandon   POST: Keep watching tonight, Not yet, We finished
                    ({"finished_on": "2026-12-12"}?; Matinee gets the watch, Home Assistant the movie log), We gave up
  /api/viewings/<id>   DELETE: a finished viewing logged by mistake, and its Matinee watch
  /api/services     GET the streaming services, PUT {key, status} to subscribe, consider or ignore one
  /api/movies/<id>/providers/refresh   POST: ask TMDB where it streams now
  /api/worth        GET Worth a Month?: per considering service, the list movies it would add ({year, season, services})
  /api/calendar     GET ?month=YYYY-MM: the movies watched on each day of a month
  (ownership and shelf come from Matinee: asked on add, on the detail view when over a day old, and nightly)
  /api/theme        GET today's Advent theme {"theme": "fireplace"|"toystore"|"tree"|"sleigh"|null, "until": "YYYY-MM-DD"}
  /api/theme/prefs  GET / PUT {"enabled"?, "mode"?: "system"|"light"|"dark"}: Themes on or off, the plain look
  /posters/<name>   the local poster and backdrop copies
  /hooks/tv         Home Assistant TV events {"state", "source", "at"}: open and close the night's TV session, which
                    sets the finish guess (auth.hook_required: X-Hook-Secret; docs/home-assistant.md)
  /static/<path>    CSS, ES modules, fonts: no auth (no data in them)

Environment: see settings.py and .env.example (/etc/conf.d/wonderful on the host).
"""
import hashlib, json, re, sys, types

from flask import Flask, g, jsonify, make_response, request, send_from_directory

# Moved out of app.py and re-exported: tests and ops scripts use them as app.<name>.
from settings import APP_NAME, APP_DIR, _load_env, parse_hosts, PORT, DATA_DIR, DB_PATH, POSTER_DIR, ART_DIR  # noqa: F401
from settings import CF_TEAM_DOMAIN, CF_AUD, ADMIN_EMAILS, LAN_EDIT, LAN_HOSTS, WONDERFUL_API_KEY, HA_HOOK_SECRET  # noqa: F401
from settings import TMDB_READ_TOKEN, TMDB_API, TMDB_IMG, MATINEE_URL, MATINEE_API_KEY, HA_WEBHOOK_URL  # noqa: F401
from settings import ANTHROPIC_API_KEY, AI_MODEL, AI_DAILY_CAP, AI_TIMEOUT, UA, SERVICES_FILE  # noqa: F401
from common import RATING_ERROR, clean, make_err, validate_rating, round_half_up, today, now_iso  # noqa: F401
from db import SCHEMA, SCHEMA_VERSION, connect, get_db, migrate, init_db  # noqa: F401
from auth import KEY_IDENTITY, presented_key, lan_host, access_identity, cross_site  # noqa: F401
from auth import editor_required, hook_required, public  # noqa: F401
from tmdb import TmdbError  # noqa: F401
import ai, ha, images, matinee, movies, people, providers, randomizer, ratings, search, sync, themes, tmdb, viewings, watched_days, worth  # noqa: F401  (route-free modules; use images.X, movies.X, ...)


# ===================================================================== split modules
# app.py re-exports every name the sibling modules define, so `app.X` works everywhere. A write to app.X (monkeypatch
# in the tests) also rebinds X in each split module that holds it, so their code reads the new value. Patch app.X,
# never the sibling module. A new module goes here and in installer/build.sh's cp line.
_SPLIT_MODULES = ("settings", "common", "db", "auth", "tmdb", "ai", "images", "matinee", "movies", "people", "providers", "randomizer",
                  "ratings", "search", "sync", "ha", "viewings", "themes", "worth",
                  "watched_days")


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


@app.get("/healthz")
@public
def healthz():
    """Is the app up and can it read its database? The one route with no sign-in (CLAUDE.md rule 5), so a
    monitor that cannot sign in still gets an answer. It says nothing else: no schema, no counts, no error text."""
    try:
        get_db().execute("SELECT 1").fetchone()
        resp, code = jsonify(status="ok"), 200
    except Exception:  # noqa: BLE001 - whatever is wrong, the monitor only learns that something is
        resp, code = jsonify(status="unavailable"), 503
    resp.headers["Cache-Control"] = "no-store"
    return resp, code


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
    """{"mode": "exact" | "ai" | "local", "matches": [{"id", "why"}], "suggestions": [{"title", "year", "why", "tmdb_id",
    "tmdb_type"}], "notice": str | null}: an exact title (normalized) is the only match; otherwise smart search (one
    Anthropic call, cached), which falls back to the local filter with the notice "Smart search is off right now." when
    it can't answer. An empty q is the whole list. Suggestions are titles that are not on the list: nothing is added
    until someone taps Add (POST /api/movies)."""
    con = get_db()
    q = clean(request.args.get("q")) or ""
    hit = search.exact(con, q)
    if hit is not None:
        return jsonify(mode="exact", matches=[{"id": hit, "why": "exact title"}], suggestions=[])
    return jsonify(search.ai(con, q))


@app.post("/api/surprise")
@editor_required
def api_surprise():
    """{"picks": [ids], "pool_size": n, "restarted": bool}: up to three distinct movies from the list after the filters
    ({"animated": true|false|null, "cap": null|"G"|"PG"|"PG-13", "under_90", "not_watched_this_year", "ready"}),
    skipping `exclude`, the ids shown since the filters last changed (spec §12). Reads only the local database."""
    return jsonify(randomizer.surprise(get_db(), request.get_json(silent=True)))


@app.get("/api/worth")
@editor_required
def api_worth():
    """Worth a Month? (spec §13): {"year", "season": true in November and December, "services": [{service, name, movies,
    count, reason}]}, the considering services most movies first. Reads the database only."""
    return jsonify(worth.worth(get_db()))


@app.get("/api/calendar")
@editor_required
def api_calendar():
    """§5: {"month", "today", "days": {date: [movie entries]}} for ?month=YYYY-MM (default: this month)."""
    return jsonify(watched_days.month_view(get_db(), request.args.get("month")))


def _movie_json(con, row):
    """movie_out plus the rating fields: family_rating and rating_source (what the poster shows, spec §8.2) and
    `family` {mean, by_person} for the detail view; and `watched_recently` (in the last 45 days), which greys the
    poster on the grid."""
    return {**movies.movie_out(row), **ratings.out(con, row["id"]),
            "watched_recently": viewings.watched_recently(con, row["id"])}


@app.get("/api/movies")
@editor_required
def api_movies():
    """The list. Each movie carries `where_to_watch` read from the providers cache: no TMDB call per card."""
    con = get_db()
    return jsonify([{**_movie_json(con, r), "where_to_watch": providers.where_to_watch(con, r["id"])}
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
    return jsonify({**_movie_json(con, movies.get_row(con, movie_id)), **providers.movie_providers(con, movie_id)}), 201


@app.get("/api/movies/<int:movie_id>")
@editor_required
def api_movie(movie_id):
    """One movie, with where to watch from the cache and `providers_stale` (the page asks for a refresh when true).
    Ownership is asked of Matinee first when the last answer is over a day old; if Matinee can't answer, the last
    known ownership is shown with "(as of <date>)". `today` is the host's date (TZ): the newest date Log date takes,
    and what the Watched list counts "yesterday" from, whatever the phone's clock says."""
    con = get_db()
    movies.refresh_ownership_if_stale(con, movie_id)
    return jsonify({**_movie_json(con, movies.get_row(con, movie_id)), **providers.movie_providers(con, movie_id),
                    "viewing": viewings.open_for_movie(con, movie_id), "watched": viewings.watched(con, movie_id),
                    "today": today().isoformat()})


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
    return jsonify(_movie_json(con, movies.get_row(con, movie_id)))


@app.delete("/api/movies/<int:movie_id>")
@editor_required
def api_movie_remove(movie_id):
    movies.remove_movie(get_db(), movie_id)
    return jsonify(ok=True)


# ========================================================================= people and ratings
@app.get("/api/people")
@editor_required
def api_people():
    """The family: [{id, name, kind, color, sort_order, active}]. When there is nobody yet and Matinee is set up, they
    are copied from Matinee first (spec §8.4); if Matinee can't answer the list is simply empty."""
    con = get_db()
    people.first_run_sync(con)
    return jsonify(people.list_people(con))


@app.post("/api/people")
@editor_required
def api_person_add():
    """{"name", "kind": "adult" | "kid", "color": "green" | "blue" | "red" | "pink" | "purple"} -> the new person (201).
    Someone who lives only here, like a grandparent visiting: they rate, and are not sent to Matinee."""
    return jsonify(people.add_person(get_db(), request.get_json(silent=True))), 201


@app.post("/api/people/sync")
@editor_required
def api_people_sync():
    """Copy Matinee's people by name -> {"added", "updated", "people"}. Matinee down or refusing is a 502 with its reason."""
    con = get_db()
    try:
        done = people.sync_from_matinee(con, matinee.client())
    except (matinee.Unavailable, matinee.Rejected) as e:
        return make_err(502, e.message)
    return jsonify(**done, people=people.list_people(con))


@app.put("/api/movies/<int:movie_id>/ratings/<int:person_id>")
@editor_required
def api_rating_set(movie_id, person_id):
    """{"rating": 8.5 | null} -> {"family_rating", "rating_source", "family"}: one person's rating of one movie in 0.5
    steps from 0 to 10, null clears it. 400 for 7.3 or 11. The family mean is null again when the last rating goes."""
    con = get_db()
    ratings.set(con, movie_id, person_id, ratings.parse_body(request.get_json(silent=True)))
    return jsonify(ratings.out(con, movie_id))


@app.post("/api/movies/<int:movie_id>/rating-conflict")
@editor_required
def api_rating_conflict(movie_id):
    """{"choice": "ours" | "matinee" | "dismiss"} -> {"family_rating", "rating_source", "family", "rating_conflict",
    "rating_pending"}. Ours is sent to Matinee (Matinee down: it stays owed, rating_pending true, and goes tonight);
    Matinee's hands the rating back to Matinee; Dismiss closes the notice. With no notice open nothing changes."""
    con = get_db()
    data = request.get_json(silent=True)
    sync.resolve_conflict(con, movie_id, data.get("choice") if isinstance(data, dict) else None)
    return jsonify(ratings.out(con, movie_id))


# ========================================================================= viewings (spec §10)
def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@app.post("/api/movies/<int:movie_id>/tonight")
@editor_required
def api_watch_tonight(movie_id):
    """{"people": [person ids]}? -> the viewing (out()). Watch tonight: the movie's open viewing, or a new one with every
    active person (or `people`). Any other viewing that was tonight goes back to Continue Watching."""
    con = get_db()
    viewing_id = viewings.watch_tonight(con, movie_id, _body().get("people"))
    return jsonify(viewings.out(con, viewing_id))


@app.post("/api/movies/<int:movie_id>/watched")
@editor_required
def api_log_watched(movie_id):
    """{"finished_on": "YYYY-MM-DD", "people": [person ids]?} -> the viewing (out()) plus "watched", the movie's Watched
    list, and "watched_recently". Log date: a night nobody logged at the time becomes a finished viewing on that date (today or earlier) for
    those people (default: every active person). The movie's open viewing is finished instead when it had begun by
    then. Matinee gets the watch (watch_pending when it couldn't take it yet); Home Assistant only when it is today."""
    con = get_db()
    body = _body()
    viewing_id = viewings.log_watched(con, movie_id, viewings.parse_finished_on(body.get("finished_on")), body.get("people"))
    return jsonify(**viewings.out(con, viewing_id), watched=viewings.watched(con, movie_id),
                   watched_recently=viewings.watched_recently(con, movie_id))


@app.get("/api/continue")
@editor_required
def api_continue():
    """{"viewings": [...]}: the Continue Watching row, tonight's first. A pick left from last night is set aside first."""
    con = get_db()
    viewings.expire_stale(con)
    return jsonify(viewings=viewings.continue_watching(con))


@app.get("/api/prompt")
@editor_required
def api_prompt():
    """{"prompt": {"viewing_id", "title", "guess": "finished" | "not_finished" | null} | null}: "Did you finish …?".
    A TV session left open past runtime + 60 min is closed first (it may be what asks)."""
    con = get_db()
    viewings.expire_stale(con)
    return jsonify(prompt=viewings.pending_prompt(con))


@app.post("/api/viewings/<int:viewing_id>/keep")
@editor_required
def api_viewing_keep(viewing_id):
    con = get_db()
    viewings.keep_watching(con, viewing_id)
    return jsonify(viewings.out(con, viewing_id))


@app.post("/api/viewings/<int:viewing_id>/not-yet")
@editor_required
def api_viewing_not_yet(viewing_id):
    con = get_db()
    viewings.not_yet(con, viewing_id)
    return jsonify(viewings.out(con, viewing_id))


@app.post("/api/viewings/<int:viewing_id>/finish")
@editor_required
def api_viewing_finish(viewing_id):
    """{"finished_on": "YYYY-MM-DD"}? -> the viewing, with watch_pending true when Matinee couldn't take the watch yet
    (it goes tonight). 409 when it was already finished: nothing is sent twice."""
    con = get_db()
    viewings.finish(con, viewing_id, viewings.parse_finished_on(_body().get("finished_on")))
    return jsonify(viewings.out(con, viewing_id))


@app.post("/api/viewings/<int:viewing_id>/abandon")
@editor_required
def api_viewing_abandon(viewing_id):
    con = get_db()
    viewings.abandon(con, viewing_id)
    return jsonify(viewings.out(con, viewing_id))


@app.delete("/api/viewings/<int:viewing_id>")
@editor_required
def api_viewing_delete(viewing_id):
    """Delete a finished viewing and its Matinee watch -> {"ok": true, "watched": the movie's Watched list,
    "watched_recently": whether its poster stays greyed}. 502 (and nothing deleted) when Matinee can't delete the
    watch; 409 for a viewing that isn't finished."""
    con = get_db()
    movie_id = viewings.get_row(con, viewing_id)["movie_id"]
    viewings.delete(con, viewing_id)
    return jsonify(ok=True, watched=viewings.watched(con, movie_id),
                   watched_recently=viewings.watched_recently(con, movie_id))


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


@app.get("/api/theme")
@editor_required
def api_theme():
    """Today's theme by the host's local date (TZ, never UTC), and the last day that answer holds."""
    return jsonify(themes.current(today()))


@app.get("/api/theme/prefs")
@editor_required
def api_theme_prefs():
    return jsonify(themes.get_prefs(get_db()))


@app.put("/api/theme/prefs")
@editor_required
def api_set_theme_prefs():
    """{"enabled": true | false, "mode": "system" | "light" | "dark"}, either one: the household's choice."""
    return jsonify(themes.set_prefs(get_db(), request.get_json(silent=True)))


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
    """Home Assistant's Family Room TV events (spec §10.2), {"state", "source", "at"} -> {"ok": true, "applied",
    "action": "opened" | "closed" | "ignored", "reason"}. An event that doesn't fit (a duplicate, out of order, nothing
    on for tonight) is a 200 that changes nothing; a malformed body is a 400. docs/home-assistant.md has the automation."""
    state, source, at = ha.parse_tv_event(request.get_json(silent=True))
    result = ha.handle_tv_event(get_db(), state, source, at)
    return jsonify(ok=True, applied=result["action"] != "ignored", **result)


init_db()

if __name__ == "__main__":   # development server; the host runs gunicorn (installer/setup-head.sh)
    app.run(host="0.0.0.0", port=PORT, debug=False)
