"""Who may use the app (spec §5, auth.py): LAN by host, Cloudflare Access JWT, the script key, and the TV hook.
There is no anonymous view: every route but /hooks/tv and /static/ needs an editor."""
import time

import pytest

import app

EVIL = {"Origin": "https://evil.example.com", "Sec-Fetch-Site": "cross-site"}
LAN = "192.168.1.100:8772"


def test_anonymous_via_cloudflare_is_401(anon_client):
    assert anon_client.get("/api/health", headers={"Cf-Connecting-Ip": "1.2.3.4"}).status_code == 401


def test_lan_ip_host_is_allowed(client):
    assert client.get("/api/health", base_url="http://192.168.1.100:8772").status_code == 200


def test_hook_requires_secret(client, monkeypatch):
    monkeypatch.setattr(app, "HA_HOOK_SECRET", "s3cret")
    assert client.post("/hooks/tv", json={}).status_code == 403


# ------------------------------------------------------------------------------------------------- health
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.get_json() == {"ok": True, "schema": "1"}


def test_index_serves_the_app_with_versioned_modules(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "<title>It's a Wonderful App</title>" in html and 'id="grid"' in html
    assert "/static/style.css?v=" in html and "/static/js/main.js?v=" in html and '"importmap"' in html
    assert "no-cache" in r.headers["Cache-Control"]


def test_static_files_need_no_sign_in(anon_client):
    assert anon_client.get("/static/style.css").status_code == 200
    assert anon_client.get("/static/js/core.js").status_code == 200
    assert anon_client.get("/static/fonts/figtree-latin-wght.woff2").status_code == 200


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors" in r.headers["Content-Security-Policy"]


# ------------------------------------------------------------------------------------- every route is guarded
def test_every_route_needs_an_editor_or_the_hook_secret(anon_client):
    """Walks app.url_map: a new route without @editor_required (or @hook_required) fails here."""
    for rule in app.app.url_map.iter_rules():
        if rule.endpoint in ("static_files",):
            continue
        view = app.app.view_functions[rule.endpoint]
        expected = "hook" if rule.rule.startswith("/hooks/") else "editor"
        assert getattr(view, "auth", None) == expected, f"{rule.rule} must use @{expected}_required"
        url = rule.rule.replace("<int:", "<").replace("<path:", "<")
        url = "/".join("1" if part.startswith("<") else part for part in url.split("/"))
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            r = anon_client.open(url, method=method, json={})
            assert r.status_code == (403 if expected == "hook" else 401), (method, rule.rule, r.status_code)


def test_anonymous_gets_nothing(anon_client):
    for path in ("/", "/api/health", "/api/me"):
        assert anon_client.get(path).status_code == 401, path


# ------------------------------------------------------------------------------------ the LAN identity by host
@pytest.mark.parametrize("host", ["localhost", "localhost:8772", "127.0.0.1", "127.0.0.1:8772", "192.168.1.100", LAN,
                                  "10.0.0.7:8772", "[::1]:8772", "[fd00::50]"])
def test_lan_identity_for_ip_literals_and_localhost(client, host):
    r = client.get("/api/me", headers={"Host": host})
    assert r.status_code == 200, host
    assert r.get_json()["editor"] == "lan"


@pytest.mark.parametrize("host", ["evil.example.com", "evil.example.com:8772", "wonderful.lan",
                                  "localhost.evil.example.com", "192.168.1.100.nip.io", "wonderful.example.com"])
def test_no_lan_identity_for_other_hosts(client, host):
    # DNS rebinding: a page served from its own name never earns "lan", even when the name resolves here
    assert client.get("/api/me", headers={"Host": host}).status_code == 401, host


@pytest.mark.parametrize("host", ["wonderful.lan", "wonderful.lan:8772", "WONDERFUL.LAN", "xmas.home.arpa"])
def test_lan_hosts_names_are_lan(client, monkeypatch, host):
    monkeypatch.setattr(app, "LAN_HOSTS", app.parse_hosts("wonderful.lan, xmas.home.arpa."))
    assert client.get("/api/me", headers={"Host": host}).get_json()["editor"] == "lan"


def test_lan_edit_off_means_no_lan_identity(client, monkeypatch):
    monkeypatch.setattr(app, "LAN_EDIT", False)
    assert client.get("/api/health", headers={"Host": LAN}).status_code == 401


@pytest.mark.parametrize("header", ["Cf-Ray", "Cf-Connecting-Ip"])
def test_requests_through_cloudflare_are_not_lan(client, header):
    assert client.get("/api/health", headers={"Host": LAN, header: "203.0.113.9"}).status_code == 401


def test_cross_site_browser_requests_are_refused(client):
    assert client.post("/hooks/tv", headers=EVIL).status_code == 403          # (no secret either)
    r = client.get("/api/health", headers={"Host": LAN, **EVIL})
    assert r.status_code == 403 and r.get_json()["error"] == "Cross-site request refused"
    r = client.get("/api/health", headers={"Host": LAN, "Origin": "null"})
    assert r.status_code == 403
    r = client.get("/api/health", headers={"Host": LAN, "Origin": f"http://{LAN}", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200


# ------------------------------------------------------------------------------------------------- the key
def test_api_key(anon_client, monkeypatch):
    monkeypatch.setattr(app, "WONDERFUL_API_KEY", "k-123")
    assert anon_client.get("/api/me", headers={"Authorization": "Bearer k-123"}).get_json()["editor"] == "api-key"
    assert anon_client.get("/api/me", headers={"X-API-Key": "k-123"}).status_code == 200
    assert anon_client.get("/api/me", headers={"Authorization": "Bearer wrong"}).status_code == 401
    # a script is not a browser: the key skips the cross-site check
    assert anon_client.get("/api/me", headers={"X-API-Key": "k-123", **EVIL}).status_code == 200


def test_empty_key_setting_admits_no_one(anon_client):
    assert anon_client.get("/api/me", headers={"Authorization": "Bearer "}).status_code == 401
    assert anon_client.get("/api/me", headers={"X-API-Key": ""}).status_code == 401


# --------------------------------------------------------------------------------------- Cloudflare Access
@pytest.fixture
def access(monkeypatch):
    """Access set up with a local RSA key standing in for the team's certs; returns make(email, aud) -> token."""
    jwt = pytest.importorskip("jwt")
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Jwks:
        def get_signing_key_from_jwt(self, token):
            return type("K", (), {"key": key.public_key()})()
    monkeypatch.setattr(app, "_jwks", Jwks())
    monkeypatch.setattr(app, "CF_TEAM_DOMAIN", "family.cloudflareaccess.com")
    monkeypatch.setattr(app, "CF_AUD", "wonderful-aud")

    def make(email, aud="wonderful-aud"):
        return jwt.encode({"aud": aud, "email": email, "iss": "https://family.cloudflareaccess.com",
                           "exp": int(time.time()) + 600}, key, algorithm="RS256")
    return make


TUNNEL = {"Host": "wonderful.example.com", "Cf-Ray": "8e1f-SJC", "Cf-Connecting-Ip": "203.0.113.9"}


def test_access_jwt_for_an_admin_email(anon_client, monkeypatch, access):
    monkeypatch.setattr(app, "ADMIN_EMAILS", {"parent@example.com"})
    r = anon_client.get("/api/me", headers={**TUNNEL, "Cf-Access-Jwt-Assertion": access("Parent@example.com")})
    assert r.status_code == 200 and r.get_json()["editor"] == "parent@example.com"
    assert anon_client.get("/api/me", headers={**TUNNEL, "Cf-Access-Jwt-Assertion": access("stranger@example.com")}).status_code == 401
    assert anon_client.get("/api/me", headers={**TUNNEL, "Cf-Access-Jwt-Assertion": access("parent@example.com", aud="other")}).status_code == 401
    assert anon_client.get("/api/me", headers={**TUNNEL, "Cf-Access-Jwt-Assertion": "not-a-jwt"}).status_code == 401
    r = anon_client.get("/api/me", headers={**TUNNEL, **EVIL, "Cf-Access-Jwt-Assertion": access("parent@example.com")})
    assert r.status_code == 403


def test_access_jwt_with_no_allow_list_admits_whoever_access_admits(anon_client, access):
    r = anon_client.get("/api/me", headers={**TUNNEL, "Cf-Access-Jwt-Assertion": access("guest@example.com")})
    assert r.get_json()["editor"] == "guest@example.com"


def test_tunnel_without_a_jwt_is_401(client):
    assert client.get("/", headers=TUNNEL).status_code == 401


def test_cf_team_domain_is_normalised_to_a_bare_host():
    src = (app.APP_DIR / "settings.py").read_text(encoding="utf-8")
    line = next(l for l in src.splitlines() if l.startswith("CF_TEAM_DOMAIN ="))
    import re
    for raw in ("family.cloudflareaccess.com", "https://family.cloudflareaccess.com/", " 'http://family.cloudflareaccess.com/x' "):
        ns = {"os": type("O", (), {"environ": {"CF_TEAM_DOMAIN": raw}})(), "re": re}
        exec(line, ns)
        assert ns["CF_TEAM_DOMAIN"] == "family.cloudflareaccess.com"


# ------------------------------------------------------------------------------------------------ the TV hook
def test_hook_with_the_secret(anon_client, monkeypatch):
    monkeypatch.setattr(app, "HA_HOOK_SECRET", "s3cret")
    body = {"state": "on", "source": "Disney+", "at": "2026-12-12T19:31:04-08:00"}
    assert anon_client.post("/hooks/tv", json=body, headers={"X-Hook-Secret": "s3cret"}).status_code == 200
    assert anon_client.post("/hooks/tv", json=body, headers={"X-Hook-Secret": "wrong"}).status_code == 403
    assert anon_client.get("/hooks/tv", headers={"X-Hook-Secret": "s3cret"}).status_code == 405


def test_hook_is_off_without_a_secret(client):
    # LAN identity is not enough, and an empty header must not match an empty setting
    assert client.post("/hooks/tv", json={}, headers={"X-Hook-Secret": ""}).status_code == 403


def test_settings_patches_reach_the_sibling_modules(monkeypatch):
    import auth
    monkeypatch.setattr(app, "HA_HOOK_SECRET", "x")
    assert auth.HA_HOOK_SECRET == "x"
