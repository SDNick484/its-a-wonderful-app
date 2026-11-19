"""The local poster cache (spec §7.1): TMDB art is downloaded once into $DATA_DIR/posters/ and served from there, so
the app never hot-links TMDB and keeps working when TMDB is down. Route-free; /posters/<name> is in app.py. Logs
through flask.current_app when there is a request or app context (see CLAUDE.md)."""
import os, re, urllib.request

from flask import current_app, has_app_context

from settings import POSTER_DIR, TMDB_IMG, UA

POSTER_SIZE, BACKDROP_SIZE = "w342", "w780"
MAX_BYTES = 5 * 1024 * 1024
NAME_RE = re.compile(r"^(?:movie|tv)-\d+-(?:w342|backdrop-w780)\.jpg$")


def poster_name(tmdb_type, tmdb_id):
    return f"{tmdb_type}-{int(tmdb_id)}-{POSTER_SIZE}.jpg"


def backdrop_name(tmdb_type, tmdb_id):
    return f"{tmdb_type}-{int(tmdb_id)}-backdrop-{BACKDROP_SIZE}.jpg"


def image_url(name):
    """The URL the page uses for a local file name; None when there is no file (the page shows a titled placeholder)."""
    return f"/posters/{name}" if name else None


def _warn(msg, *args):
    if has_app_context():
        current_app.logger.warning(msg, *args)


def fetch(tmdb_path, size, name):
    """Download TMDB's `tmdb_path` at `size` to POSTER_DIR/name, once. Returns `name`, or None when TMDB has no
    image or the download failed (a missing image only means a placeholder, never a failed add). The file is written
    under a temporary name and renamed, so a half-written file is never served."""
    if not tmdb_path:
        return None
    dest = POSTER_DIR / name
    if dest.is_file():
        return name
    url = f"{TMDB_IMG}/{size}{tmdb_path}"
    tmp = dest.with_name(f".{name}.part")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read(MAX_BYTES)
        if not data.startswith(b"\xff\xd8\xff"):
            raise ValueError("not a JPEG")
        POSTER_DIR.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(data)
        os.replace(tmp, dest)
    except Exception as e:  # noqa: BLE001 — any failure means "no poster for now"
        tmp.unlink(missing_ok=True)
        _warn("poster download failed for %s: %s", name, e)
        return None
    return name


def delete(*names):
    for name in names:
        if name and NAME_RE.match(name):
            (POSTER_DIR / name).unlink(missing_ok=True)
