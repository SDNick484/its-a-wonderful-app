#!/bin/sh
# It's a Wonderful App (family Christmas movie picker) installer for Alpine Linux (OpenRC).
# Re-runnable: upgrades the app in place; never touches existing data, and only *adds* missing settings to an
# existing config file.
#
#   sh setup-wonderful.sh               install / upgrade
#   WONDERFUL_PORT=8772 sh setup-wonderful.sh
#   sh setup-wonderful.sh --uninstall   remove app + service (keeps /var/lib/wonderful, config and backups)
set -eu
APP_DIR=/opt/wonderful
DATA_DIR=/var/lib/wonderful
CONF=/etc/conf.d/wonderful
OPS_CONF="${OPS_CONF:-/etc/conf.d/ops}"
SVC_USER=wonderful
PORT="${WONDERFUL_PORT:-8772}"

if [ "$(id -u)" != 0 ]; then echo "Run as root"; exit 1; fi
command -v apk >/dev/null || { echo "This installer is for Alpine (apk)."; exit 1; }

if [ "${1:-}" = "--uninstall" ]; then
  rc-service wonderful stop 2>/dev/null || true
  rc-update del wonderful default 2>/dev/null || true
  rm -f /etc/init.d/wonderful /etc/periodic/daily/wonderful-backup
  rm -rf "$APP_DIR"
  echo "Removed app, service and backup job. Data kept in $DATA_DIR, config in $CONF, backups in /var/backups/wonderful."
  exit 0
fi

# an existing install keeps its port
[ -f "$CONF" ] && PORT=$(sed -n 's/^PORT=//p' "$CONF" | head -n1) && PORT=${PORT:-8772}

echo "==> Installing packages"
# python3 + Flask + gunicorn run the app; Pillow prepares theme art; jwt + cryptography check Cloudflare Access
# tokens; sqlite is the CLI ops/wonderful-backup uses; tzdata makes TZ (local dates) work.
apk add --no-cache python3 py3-flask py3-gunicorn py3-pillow py3-jwt py3-cryptography sqlite tzdata >/dev/null

[ -x /etc/init.d/wonderful ] && rc-service wonderful stop >/dev/null 2>&1 || true
IP=$(ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | head -n1)
IP=${IP:-127.0.0.1}
if netstat -ltn 2>/dev/null | awk '{print $4}' | grep -q ":$PORT\$"; then
  echo "Port $PORT is already in use by something else. Re-run with WONDERFUL_PORT=<free port>."; exit 1
fi

echo "==> Creating user and folders"
# BusyBox adduser -S puts a new user in "nogroup" unless told otherwise, so make the app's own group first.
grep -q "^$SVC_USER:" /etc/group || addgroup -S "$SVC_USER"
if ! id "$SVC_USER" >/dev/null 2>&1; then
  adduser -S -D -H -h "$DATA_DIR" -s /sbin/nologin -G "$SVC_USER" "$SVC_USER"
fi
mkdir -p "$APP_DIR" "$DATA_DIR/posters" "$DATA_DIR/art" /var/backups/wonderful

echo "==> Unpacking app"
TMP=$(mktemp -d /tmp/wonderful-tmp.XXXXXX 2>/dev/null || mktemp -d -t wonderful-tmp.XXXXXX 2>/dev/null || mktemp -d)
sed -n '/^__PAYLOAD_BELOW__$/,$p' "$0" | tail -n +2 | base64 -d | ( cd "$TMP" && tar -xzf - )
rm -rf "$APP_DIR.new" && mv "$TMP/wonderful" "$APP_DIR.new"
rm -rf "$APP_DIR.old"; [ -d "$APP_DIR" ] && mv "$APP_DIR" "$APP_DIR.old"
mv "$APP_DIR.new" "$APP_DIR"; rm -rf "$APP_DIR.old" "$TMP"
chown -R root:root "$APP_DIR"
chown -R "$SVC_USER:$SVC_USER" "$DATA_DIR"
chmod 750 "$DATA_DIR"

# ---------------------------------------------------------------- config
add_setting() {  # add_setting FILE KEY VALUE COMMENT: only if KEY isn't there yet
  grep -q "^$2=" "$1" 2>/dev/null && return 0
  printf '\n# %s\n%s=%s\n' "$4" "$2" "$3" >> "$1"
  ADDED="${ADDED:-} $2"
}
gen_key() {  # 43 URL-safe characters (256 bits) for a new secret
  python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
}

if [ ! -f "$CONF" ]; then
  echo "==> Writing $CONF"
  cat > "$CONF" <<EOF
# It's a Wonderful App configuration. After editing: rc-service wonderful restart
PORT=$PORT
DATA_DIR=$DATA_DIR
EOF
fi
add_setting "$CONF" TZ "America/Los_Angeles" "Time zone for local dates (Advent themes, 'this year', finished_on); the host's zone, not UTC"
add_setting "$CONF" CF_TEAM_DOMAIN "" "Cloudflare Access team domain, e.g. yourteam.cloudflareaccess.com"
add_setting "$CONF" CF_AUD "" "AUD tag of the Access application in front of this app's hostname"
add_setting "$CONF" ADMIN_EMAILS "" "Only these Access emails may use the app (comma separated); empty = anyone the Access policy lets in"
add_setting "$CONF" LAN_EDIT 1 "1 = direct LAN requests (by IP, localhost or a LAN_HOSTS name, not through Cloudflare) may use the app"
add_setting "$CONF" LAN_HOSTS "" "Host names LAN requests may use besides IPs and localhost, e.g. wonderful.lan (comma separated)"
add_setting "$CONF" WONDERFUL_API_KEY "" "Optional key for scripts (Authorization: Bearer <key>); empty = no key access"
add_setting "$CONF" HA_HOOK_SECRET "$(gen_key)" "Shared secret Home Assistant sends as X-Hook-Secret to /hooks/tv; empty = the hook is off"
add_setting "$CONF" HA_WEBHOOK_URL "" "Home Assistant webhook URL for the movie log (the same one Matinee uses), a secret; empty = off"
add_setting "$CONF" TMDB_READ_TOKEN "" "TMDB API Read Access Token (themoviedb.org -> Settings -> API); adding movies needs it"
add_setting "$CONF" MATINEE_URL "http://127.0.0.1:8771" "Matinee's address on the LAN (ownership, ratings and watches)"
add_setting "$CONF" MATINEE_API_KEY "" "Matinee's MATINEE_API_KEY (its write key); empty = no Matinee sync"
add_setting "$CONF" ANTHROPIC_API_KEY "" "Anthropic API key for smart search; empty = smart search is off"
add_setting "$CONF" AI_MODEL "claude-haiku-5-5" "Model smart search uses"
add_setting "$CONF" AI_DAILY_CAP 200 "Smart searches per day across the family; past it search falls back to the list filter"
# Holds API keys, so root only: OpenRC and the cron jobs run as root; the service gets what it needs from the environment.
chmod 600 "$CONF"; chown root:root "$CONF"

# health checks: add the app to HEALTH_CHECKS if the host's ops config exists
add_health_check() {  # add_health_check "Name|url|service" service  (sets HC_ADDED / HC_MANUAL)
  [ -f "$OPS_CONF" ] || return 0
  grep -Eq "\|$2([^-A-Za-z0-9_]|\$)" "$OPS_CONF" && return 0
  if ! grep -q '^HEALTH_CHECKS=' "$OPS_CONF"; then
    cat >> "$OPS_CONF" <<EOF

# Apps checked every 15 min (name|url|service); added by setup-wonderful.sh
HEALTH_CHECKS="$1"
EOF
    HC_ADDED="${HC_ADDED:-} $2"
    return 0
  fi
  # append inside the existing (usually multi-line) HEALTH_CHECKS="..." value, before its closing quote
  awk -v add="$1" '
    !done && /^HEALTH_CHECKS="/ { inb = 1; if ($0 == "HEALTH_CHECKS=\"") { print; next } }
    inb && /"[ \t]*$/ { sub(/"[ \t]*$/, ""); print; print add "\""; inb = 0; done = 1; next }
    { print }' "$OPS_CONF" > "$OPS_CONF.new"
  if grep -Eq "\|$2([^-A-Za-z0-9_]|\$)" "$OPS_CONF.new" && sh -n "$OPS_CONF.new" 2>/dev/null; then
    cat "$OPS_CONF.new" > "$OPS_CONF"; HC_ADDED="${HC_ADDED:-} $2"
  else
    HC_MANUAL="${HC_MANUAL:-}
      $1"
  fi
  rm -f "$OPS_CONF.new"
}
# /api/health needs an editor: 127.0.0.1 is the "lan" identity while LAN_EDIT=1
add_health_check "Wonderful|http://127.0.0.1:$PORT/api/health|wonderful" wonderful

# ---------------------------------------------------------------- service
cat > /etc/init.d/wonderful <<'EOF'
#!/sbin/openrc-run
name="wonderful"
description="It's a Wonderful App (family Christmas movie picker)"
: ${PORT:=8772}
: ${DATA_DIR:=/var/lib/wonderful}
export HOME=/var/lib/wonderful  # newer gunicorn keeps a small control socket under $HOME
export PORT DATA_DIR TZ CF_TEAM_DOMAIN CF_AUD ADMIN_EMAILS LAN_EDIT LAN_HOSTS WONDERFUL_API_KEY HA_HOOK_SECRET HA_WEBHOOK_URL TMDB_READ_TOKEN MATINEE_URL MATINEE_API_KEY ANTHROPIC_API_KEY AI_MODEL AI_DAILY_CAP
supervisor="supervise-daemon"
respawn_delay=5
respawn_max=10
respawn_period=600
command="/usr/bin/gunicorn"
command_args="--preload --workers 2 --threads 4 --timeout 60 --bind 0.0.0.0:${PORT} --chdir /opt/wonderful --access-logfile /var/log/wonderful.log --error-logfile /var/log/wonderful.log app:app"
command_user="wonderful"
depend() { need net; after firewall; }
start_pre() { checkpath -f -o wonderful /var/log/wonderful.log; }
EOF
chmod +x /etc/init.d/wonderful

# ---------------------------------------------------------------- backups
echo "==> Installing the nightly backup"
mkdir -p /etc/periodic/daily
install -m 755 "$APP_DIR/ops/wonderful-backup" /etc/periodic/daily/wonderful-backup
rc-update add crond default >/dev/null 2>&1 || true
rc-service crond start >/dev/null 2>&1 || true

# ---------------------------------------------------------------- start
up() {  # up URL: 0 once the app answers at all (any HTTP status: /api/health is 401 when LAN_EDIT=0)
  python3 -c 'import sys, urllib.request, urllib.error
try:
    urllib.request.urlopen(sys.argv[1], timeout=2)
except urllib.error.HTTPError:
    pass
except Exception:
    sys.exit(1)' "$1"
}
echo "==> Starting service"
rc-update add wonderful default >/dev/null 2>&1 || true
rc-service wonderful start
i=0
until up "http://127.0.0.1:$PORT/api/health"; do
  i=$((i+1)); [ $i -gt 25 ] && { echo "Service didn't come up; see /var/log/wonderful.log"; tail -n 20 /var/log/wonderful.log; exit 1; }
  sleep 1
done

echo "==> Taking a first backup"
/etc/periodic/daily/wonderful-backup || echo "    (backup reported a problem; see /var/log/ops.log)"

echo
echo "It's a Wonderful App is running:  http://$IP:$PORT/"
echo "Health: $(wget -qO- "http://127.0.0.1:$PORT/api/health" 2>/dev/null || echo 'needs LAN_EDIT=1 to answer here')"
[ -n "${ADDED:-}" ] && echo "New settings added:${ADDED}"
grep -q '^TMDB_READ_TOKEN=$' "$CONF" && echo "  - Adding movies is off until you set TMDB_READ_TOKEN in $CONF (then: rc-service wonderful restart)"
grep -q '^CF_AUD=$' "$CONF" && echo "  - Set CF_TEAM_DOMAIN and CF_AUD in $CONF after creating the Access app for <your-hostname>"
[ -n "${HC_ADDED:-}" ] && echo "  - Added to HEALTH_CHECKS in $OPS_CONF:${HC_ADDED}"
[ -n "${HC_MANUAL:-}" ] && echo "  - Couldn't edit HEALTH_CHECKS in $OPS_CONF: add these lines:${HC_MANUAL}"
[ -f "$OPS_CONF" ] || echo "  - No $OPS_CONF: backups still run nightly into /var/backups/wonderful"
echo "  - Tunnel: <your-hostname> -> http://$IP:$PORT"
echo "Config: $CONF   Data: $DATA_DIR   Logs: /var/log/wonderful.log, /var/log/ops.log"
exit 0
