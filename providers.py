"""Where to watch and the subscriptions (spec §7.2, decision 15): the services the family knows about, TMDB's US watch
providers kept in providers_cache, and the ordered "where to watch" lines for a card. Route-free: a bad request aborts
with common.make_err, and a TMDB failure raises tmdb.TmdbError for app.py to answer. No Flask object here (see
CLAUDE.md).

Reading is cheap and never calls TMDB (where_to_watch, ready_tonight read the cache, so the whole grid can use them);
get() and refresh() are what talk to TMDB."""
import datetime as dt, json

from flask import abort

import movies
import tmdb
from common import clean, local_date, make_err, now_iso
from settings import SERVICES_FILE

TIERS = tmdb.PROVIDER_TIERS        # flatrate, free, ads, rent, buy
STATUSES = ("subscribed", "considering", "ignore")
STALE_DAYS = 7


# ------------------------------------------------------------------------------------------------ services
def seed_services(con, path=None):
    """Add the services in data/services.json that the database lacks, and keep each one's name, TMDB provider ids and
    tv_source in step with the file (TMDB renames providers, so those stay data-driven). A status somebody set on the
    settings screen is never overwritten. Runs from db.migrate() on every start."""
    path = path or SERVICES_FILE
    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
    except (OSError, ValueError):
        return
    for e in entries:
        con.execute(
            "INSERT INTO services (key, name, tmdb_provider_ids, status, tv_source) VALUES (?,?,?,?,?)"
            " ON CONFLICT(key) DO UPDATE SET name=excluded.name, tmdb_provider_ids=excluded.tmdb_provider_ids,"
            " tv_source=excluded.tv_source",
            (e["key"], e["name"], json.dumps(e.get("tmdb_provider_ids") or []), e["status"], e.get("tv_source")))


def _ids(raw):
    try:
        ids = json.loads(raw) if raw else []
    except ValueError:
        ids = []
    return [i for i in ids if isinstance(i, int)]


def list_services(con):
    """Every service, in the order of data/services.json (insertion order): the settings screen's list."""
    return [{"key": r["key"], "name": r["name"], "status": r["status"], "tv_source": r["tv_source"],
             "tmdb_provider_ids": _ids(r["tmdb_provider_ids"])}
            for r in con.execute("SELECT * FROM services ORDER BY rowid")]


def set_status(con, data):
    """PUT /api/services {key, status}: 400 for a bad body or status, 404 for an unknown key."""
    if not isinstance(data, dict):
        abort(make_err(400, "Send a JSON body with key and status."))
    key, status = data.get("key"), data.get("status")
    if not isinstance(key, str) or not key:
        abort(make_err(400, "Say which service (key)."))
    if status not in STATUSES:
        abort(make_err(400, "status must be one of " + ", ".join(STATUSES) + "."))
    if con.execute("UPDATE services SET status=? WHERE key=?", (status, key)).rowcount == 0:
        abort(make_err(404, "No such service."))
    con.commit()


# ------------------------------------------------------------------------------------------------ the cache
def _empty():
    return {t: [] for t in TIERS}


def _provider_map(con):
    """{TMDB provider id: service key}; the first service to claim an id keeps it."""
    out = {}
    for r in con.execute("SELECT key, tmdb_provider_ids FROM services ORDER BY rowid"):
        for pid in _ids(r["tmdb_provider_ids"]):
            out.setdefault(pid, r["key"])
    return out


def _parse(raw):
    """The cached JSON as {tier: [service key or raw name]}; junk reads as empty."""
    try:
        d = json.loads(raw)
    except (TypeError, ValueError):
        d = None
    d = d if isinstance(d, dict) else {}
    return {t: [x for x in d.get(t) or [] if isinstance(x, str)] for t in TIERS}


def _cache_row(con, movie_id):
    return con.execute("SELECT * FROM providers_cache WHERE movie_id=?", (movie_id,)).fetchone()


def is_stale(row, max_age_days=STALE_DAYS):
    """True when there is no cache row, or it is older than max_age_days (an unreadable date counts as old)."""
    if row is None:
        return True
    try:
        fetched = dt.datetime.strptime(row["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return True
    return dt.datetime.now(dt.timezone.utc) - fetched > dt.timedelta(days=max_age_days)


def refresh(con, movie_id):
    """Ask TMDB now and replace the cache. A provider TMDB lists that matches a service by TMDB id is stored as that
    service's key; any other is stored by its raw name, so a new or renamed provider still shows. Returns the five
    tiers. TmdbError when TMDB can't answer (the old cache stays)."""
    row = movies.get_row(con, movie_id)
    found = tmdb.watch_providers(row["tmdb_id"], row["tmdb_type"])
    by_id = _provider_map(con)
    data = _empty()
    for tier in TIERS:
        for p in found[tier]:
            name = by_id.get(p["id"]) or p["name"]
            if name not in data[tier]:
                data[tier].append(name)
    con.execute("INSERT INTO providers_cache (movie_id, data, link, fetched_at) VALUES (?,?,?,?)"
                " ON CONFLICT(movie_id) DO UPDATE SET data=excluded.data, link=excluded.link, fetched_at=excluded.fetched_at",
                (movie_id, json.dumps(data), found["link"], now_iso()))
    con.commit()
    return data


def get(con, movie_id, max_age_days=STALE_DAYS):
    """{flatrate, free, ads, rent, buy}: lists of service keys or raw provider names. Served from the cache while it
    is younger than max_age_days, otherwise TMDB is asked again. When TMDB can't answer, an older cache is served
    rather than nothing; with no cache at all the TmdbError goes to the caller."""
    row = _cache_row(con, movie_id)
    if row is not None and not is_stale(row, max_age_days):
        return _parse(row["data"])
    try:
        return refresh(con, movie_id)
    except tmdb.TmdbError:
        if row is not None:
            return _parse(row["data"])
        raise


def cached(con, movie_id):
    """The cache as it stands, with no TMDB call: (tiers, link, fetched_at, stale). Never fetched reads as empty
    tiers, no link, fetched_at None and stale True."""
    row = _cache_row(con, movie_id)
    if row is None:
        return _empty(), None, None, True
    return _parse(row["data"]), row["link"], row["fetched_at"], is_stale(row)


# ------------------------------------------------------------------------------------------------ the lines
def where_to_watch(con, movie_id):
    """[{kind, label}] from the cache, best first (spec §7.2); no TMDB call. The card shows the first line, the detail
    view all of them.
      owned        from Matinee's last answer (matinee_sync): "Blu-ray · Family Room › Media Cabinet › Shelf 2". When
                   that answer is over a day old (Matinee has not answered since) it ends "(as of Dec 3)"
      subscribed   flatrate on a subscribed service: "On Netflix"
      free         TMDB free or ads, any service not set to ignore: "Free with ads on The Roku Channel"
      considering  flatrate on a service we don't have: "On Peacock (you don't have it)". A provider the services list
                   has never heard of counts here too: shown by its raw name
      rent_buy     rent or buy only, or nothing known for the US: "Rent or buy"
    A service set to ignore is never mentioned."""
    data = cached(con, movie_id)[0]
    svc = {r["key"]: r for r in con.execute("SELECT key, name, status FROM services")}

    def known(name):          # (display name, status) of a cached entry; raw names have no status
        r = svc.get(name)
        return (r["name"], r["status"]) if r else (name, None)

    subscribed, free, considering = [], [], []
    for name in data["flatrate"]:
        shown, status = known(name)
        if status == "subscribed":
            subscribed.append({"kind": "subscribed", "label": f"On {shown}"})
        elif status != "ignore":
            considering.append({"kind": "considering", "label": f"On {shown} (you don't have it)"})
    for tier, words in (("free", "Free"), ("ads", "Free with ads")):
        for name in data[tier]:
            shown, status = known(name)
            if status != "ignore":
                free.append({"kind": "free", "label": f"{words} on {shown}"})
    out = []
    owned = _owned_line(con, movie_id)
    if owned:
        out.append(owned)
    for entry in subscribed + free + considering:
        if entry not in out:
            out.append(entry)
    if data["rent"] or data["buy"] or not out:
        out.append({"kind": "rent_buy", "label": "Rent or buy"})
    return out


def _owned_line(con, movie_id):
    """The owned entry from matinee_sync, or None when Matinee has never said the movie is owned (or says it isn't)."""
    s = con.execute("SELECT matinee_title_id, owned_summary, location_path, checked_at FROM matinee_sync WHERE movie_id=?",
                    (movie_id,)).fetchone()
    if s is None or s["matinee_title_id"] is None or not clean(s["owned_summary"]):
        return None
    label = " · ".join(x for x in (clean(s["owned_summary"]), clean(s["location_path"])) if x)
    if movies.ownership_is_stale(s["checked_at"]):
        day = local_date(s["checked_at"])
        if day:
            label += f" (as of {day:%b} {day.day})"
    return {"kind": "owned", "label": label}


def ready_tonight(con, movie_id):
    """True when the movie can be watched right now without paying anything more (the "Ready to watch" filter,
    decision 20): owned, on a subscribed service, or free (with ads too)."""
    return any(e["kind"] in ("owned", "subscribed", "free") for e in where_to_watch(con, movie_id))


def movie_providers(con, movie_id):
    """What the detail view shows about where to watch: the lines, TMDB's watch-page link for the JustWatch
    attribution, when the cache was fetched, and whether it is due for a refresh."""
    _data, link, fetched_at, stale = cached(con, movie_id)
    link = clean(link)
    return {"where_to_watch": where_to_watch(con, movie_id), "providers_link": link if link and link.startswith("https://") else None,
            "providers_fetched_at": fetched_at, "providers_stale": stale}
