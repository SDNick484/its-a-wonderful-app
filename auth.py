"""Who may use the app (spec §5). Ported from Matinee's app.py: the same LAN, Cloudflare Access and key rules.

There is no anonymous view. Every route is wrapped in @editor_required, except /hooks/tv (@hook_required) and
static files. An editor is one of:
  * a direct LAN request (LAN_EDIT=1): addressed by an IP literal, localhost or a LAN_HOSTS name, and not
    carrying Cloudflare's Cf-Ray / Cf-Connecting-Ip headers;
  * a request through the Cloudflare tunnel with a valid Access JWT (audience CF_AUD, team CF_TEAM_DOMAIN) whose
    email is in ADMIN_EMAILS (empty ADMIN_EMAILS = anyone the Access policy admits);
  * a script presenting WONDERFUL_API_KEY as `Authorization: Bearer <key>` or `X-API-Key: <key>`.
No Flask object and no routes here (see CLAUDE.md)."""
import hmac, ipaddress, urllib.parse
from functools import wraps

from flask import current_app, g, jsonify, request

from settings import ADMIN_EMAILS, CF_AUD, CF_TEAM_DOMAIN, HA_HOOK_SECRET, LAN_EDIT, LAN_HOSTS, WONDERFUL_API_KEY

KEY_IDENTITY = "api-key"   # scripts, not browsers: exempt from the cross-site check
_jwks = None               # PyJWKClient for the team's Access certs, made on first use


def presented_key():
    """The token from `Authorization: Bearer <key>` or `X-API-Key: <key>`, or ""."""
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.headers.get("X-API-Key", "").strip()


def lan_host():
    """True when the Host header is an IP literal, localhost, or listed in LAN_HOSTS.

    A DNS-rebinding page is served from its own name (Host: evil.example.com) even after that name resolves to
    this box, so a name we don't know never earns the "lan" identity."""
    host = (request.host or "").strip().lower()
    if host.startswith("["):                      # [fd00::50]:8772
        name = host[1:host.find("]")] if "]" in host else ""
    elif host.count(":") == 1:                    # 192.168.1.100:8772, wonderful.lan:8772
        name = host.rsplit(":", 1)[0]
    else:                                         # 192.168.1.100, wonderful.lan
        name = host
    name = name.rstrip(".")
    if not name:
        return False
    if name == "localhost" or name in LAN_HOSTS:
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


def access_identity():
    """The editor's email, 'lan', 'access-user' (Access JWT without an email) or 'api-key'; None for anyone else."""
    presented = presented_key()
    if presented and WONDERFUL_API_KEY and hmac.compare_digest(presented, WONDERFUL_API_KEY):
        return KEY_IDENTITY
    token = request.headers.get("Cf-Access-Jwt-Assertion")
    if token and CF_TEAM_DOMAIN and CF_AUD:
        global _jwks
        import jwt
        try:
            if _jwks is None:
                _jwks = jwt.PyJWKClient(f"https://{CF_TEAM_DOMAIN}/cdn-cgi/access/certs", cache_keys=True)
            key = _jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], audience=CF_AUD, issuer=f"https://{CF_TEAM_DOMAIN}")
        except Exception as e:  # noqa: BLE001 — any failure means "not an editor"
            current_app.logger.warning("Access JWT rejected: %s", e)
            return None
        email = (claims.get("email") or "").lower()
        if ADMIN_EMAILS and email not in ADMIN_EMAILS:
            return None
        return email or "access-user"
    via_cloudflare = request.headers.get("Cf-Ray") or request.headers.get("Cf-Connecting-Ip")
    if LAN_EDIT and not via_cloudflare and not token and lan_host():
        return "lan"
    return None


def cross_site():
    """True when a browser says this request comes from another site: an Origin that isn't this host (including
    the opaque "null"), or Sec-Fetch-Site: cross-site. A text/plain POST is a CORS "simple request" with no
    preflight, so without this a page on any site could drive the API from a family phone on the LAN.

    A top-level GET page load outside /api/ is let through. Chrome marks the page load after a Cloudflare Access
    sign-in (a redirect back from <team>.cloudflareaccess.com) as cross-site, and a tap on a link in Gmail too. A
    GET changes nothing and another site can't read what a navigation returns. /api/ stays guarded so a link
    can't spend TMDB or AI quota (/api/search). Cross-site fetches (Sec-Fetch-Mode cors / no-cors) and form POSTs
    (navigate, but not GET) are still refused."""
    if (request.method in ("GET", "HEAD") and request.headers.get("Sec-Fetch-Mode") == "navigate"
            and not request.path.startswith("/api/")):
        return False
    origin = (request.headers.get("Origin") or "").strip()
    if origin and urllib.parse.urlparse(origin).netloc != request.host:
        return True
    return (request.headers.get("Sec-Fetch-Site") or "").lower() == "cross-site"


def editor_required(fn):
    """401 for anyone who isn't an editor, 403 for a browser request from another site; sets g.editor."""
    @wraps(fn)
    def inner(*a, **kw):
        who = access_identity()
        if not who:
            return jsonify(error="Sign in first"), 401
        if who != KEY_IDENTITY and cross_site():
            return jsonify(error="Cross-site request refused"), 403
        g.editor = who
        return fn(*a, **kw)
    inner.auth = "editor"   # tests/test_auth.py checks every route carries one of these marks
    return inner


def hook_required(fn):
    """Home Assistant's webhook (spec §10.2): `X-Hook-Secret` must equal HA_HOOK_SECRET. An unset secret turns the
    hook off (403), so a fresh install never accepts events from anyone."""
    @wraps(fn)
    def inner(*a, **kw):
        presented = request.headers.get("X-Hook-Secret", "")
        if not HA_HOOK_SECRET or not hmac.compare_digest(presented.encode(), HA_HOOK_SECRET.encode()):
            return jsonify(error="Bad or missing X-Hook-Secret"), 403
        g.editor = "hook"
        return fn(*a, **kw)
    inner.auth = "hook"
    return inner
