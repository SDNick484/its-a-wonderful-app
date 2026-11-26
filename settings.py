"""Settings, read once at import from the environment; /etc/conf.d/wonderful (or a local .env next to app.py) fills
in anything the environment leaves unset. app.py re-exports every name here: patch app.<NAME>, which also rebinds
it in this module (see _AppModule in app.py). Every setting is documented in .env.example."""
import os, re
from pathlib import Path


APP_NAME = "It's a Wonderful App"
APP_DIR = Path(__file__).resolve().parent


def _load_env():
    """KEY=value lines from /etc/conf.d/wonderful, then ./.env; a variable already in the environment wins."""
    for conf_file in [Path("/etc/conf.d/wonderful"), APP_DIR / ".env"]:
        if not conf_file.is_file():
            continue
        try:
            with open(conf_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    if line.startswith("export "):
                        line = line[7:].strip()
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                        v = v[1:-1]
                    if k and k not in os.environ:
                        os.environ[k] = v
        except OSError:
            pass


_load_env()


def parse_hosts(raw):
    """'Wonderful.LAN, xmas.home.arpa' -> {'wonderful.lan', 'xmas.home.arpa'}"""
    return {h.strip().lower().rstrip(".") for h in (raw or "").split(",") if h.strip()}


def _int(name, default):
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


PORT = _int("PORT", 8772)
DATA_DIR = Path(os.environ.get("DATA_DIR") or APP_DIR / "data")
DB_PATH = DATA_DIR / "wonderful.db"
POSTER_DIR = DATA_DIR / "posters"   # local poster and backdrop copies (TMDB art)
ART_DIR = DATA_DIR / "art"          # theme art prepared on the host; ops/wonderful-backup keeps both folders
SERVICES_FILE = APP_DIR / "data" / "services.json"   # the streaming services seeded into the database (spec §6)

# ---- access (auth.py)
# bare host: tolerate a pasted "https://team.cloudflareaccess.com/"
CF_TEAM_DOMAIN = re.sub(r"^https?://", "", os.environ.get("CF_TEAM_DOMAIN", "").strip().strip("'\"")).split("/")[0]
CF_AUD = os.environ.get("CF_AUD", "").strip()
ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
LAN_EDIT = os.environ.get("LAN_EDIT", "1").strip() == "1"
# host names (besides IP literals and localhost) that a LAN request may use; see auth.lan_host()
LAN_HOSTS = parse_hosts(os.environ.get("LAN_HOSTS", ""))
# A key for scripts (Authorization: Bearer <key> or X-API-Key: <key>); empty = no key access
WONDERFUL_API_KEY = os.environ.get("WONDERFUL_API_KEY", "").strip()
# Home Assistant posts TV events to /hooks/tv with X-Hook-Secret: <this>; empty = the hook answers 403
HA_HOOK_SECRET = os.environ.get("HA_HOOK_SECRET", "").strip()

# ---- outside services
TMDB_READ_TOKEN = os.environ.get("TMDB_READ_TOKEN", "").strip()
TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p"
MATINEE_URL = os.environ.get("MATINEE_URL", "http://127.0.0.1:8771").strip().rstrip("/")
MATINEE_API_KEY = os.environ.get("MATINEE_API_KEY", "").strip()
# Home Assistant webhook for the movie log (spec §8.5). A SECRET: the webhook id in the URL is its only credential,
# so it is never logged, never returned by a route and never put in a payload.
HA_WEBHOOK_URL = os.environ.get("HA_WEBHOOK_URL", "").strip()
# Home Assistant webhook that starts something on the Family Room TV (Play on TV); empty = the feature is off. A SECRET
# like HA_WEBHOOK_URL: never logged, never returned by a route, never put in a payload.
HA_PLAY_WEBHOOK_URL = os.environ.get("HA_PLAY_WEBHOOK_URL", "").strip()
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
AI_MODEL = os.environ.get("AI_MODEL", "").strip() or "claude-haiku-5-5"
AI_DAILY_CAP = _int("AI_DAILY_CAP", 200)
AI_TIMEOUT = _int("AI_TIMEOUT", 20)   # seconds to wait for Anthropic before search falls back to the list filter
UA = "wonderful/1.0 (family Christmas movie picker; https://github.com/SDNick484/its-a-wonderful-app)"
