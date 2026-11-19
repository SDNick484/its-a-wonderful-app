"""Static and shell-level checks on the installer and the backup (no Alpine needed).

installer/setup-head.sh is the installer header; installer/build.sh appends the app as a payload. These pin the
settings rule (CLAUDE.md): every setting is in .env.example with a comment line, in the installer's add_setting
list (added when missing, never overwritten) and in the init script's export line; and everything in $DATA_DIR is
backed up.
"""
import re
import sqlite3
import subprocess
import tarfile
import gzip
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HEAD = (ROOT / "installer" / "setup-head.sh").read_text(encoding="utf-8")
BUILD = (ROOT / "installer" / "build.sh").read_text(encoding="utf-8")
ENV = (ROOT / ".env.example").read_text(encoding="utf-8")
SETTINGS = (ROOT / "settings.py").read_text(encoding="utf-8")

# spec §16, plus WONDERFUL_API_KEY (the "or a key" of the auth rule) and AI_TIMEOUT (plan Task 12)
SPEC_SETTINGS = ["PORT", "DATA_DIR", "TMDB_READ_TOKEN", "MATINEE_URL", "MATINEE_API_KEY", "HA_HOOK_SECRET",
                 "HA_WEBHOOK_URL", "ANTHROPIC_API_KEY", "AI_MODEL", "AI_DAILY_CAP", "AI_TIMEOUT", "CF_TEAM_DOMAIN", "CF_AUD",
                 "ADMIN_EMAILS", "LAN_EDIT", "LAN_HOSTS", "TZ", "WONDERFUL_API_KEY"]


def env_keys():
    return re.findall(r"^([A-Z][A-Z0-9_]*)=", ENV, re.M)


def init_script():
    m = re.search(r"cat > /etc/init\.d/wonderful <<'EOF'\n(.*?)\nEOF\n", HEAD, re.S)
    assert m, "wonderful init script heredoc not found"
    return m.group(1)


def init_exports():
    line = next(l for l in init_script().splitlines() if l.startswith("export PORT "))
    return line.split()[1:]


def installer_settings():
    return re.findall(r'^add_setting "\$CONF" ([A-Z][A-Z0-9_]*) ', HEAD, re.M)


def shell_fn(name):
    return re.search(rf"^{name}\(\) \{{.*?^\}}$", HEAD, re.S | re.M).group(0)


def test_head_is_valid_sh():
    subprocess.run(["sh", "-n", str(ROOT / "installer" / "setup-head.sh")], check=True)


def test_env_example_has_every_spec_setting_with_a_comment():
    keys = env_keys()
    assert sorted(keys) == sorted(SPEC_SETTINGS), keys
    for key in keys:
        assert re.search(rf"^# .+\n{key}=", ENV, re.M), f"{key} needs a comment line right above it"


def test_every_setting_is_written_and_exported():
    # PORT and DATA_DIR are in the first conf the installer writes; the rest are added when missing
    assert sorted(installer_settings() + ["PORT", "DATA_DIR"]) == sorted(SPEC_SETTINGS)
    assert sorted(init_exports()) == sorted(SPEC_SETTINGS)


def test_every_setting_is_read_by_settings_py():
    for key in SPEC_SETTINGS:
        if key == "TZ":   # common.today() reads TZ on every call
            assert 'os.environ.get("TZ"' in (ROOT / "common.py").read_text(encoding="utf-8")
            continue
        assert f'"{key}"' in SETTINGS, key


def test_no_secret_has_a_value_in_the_example():
    for key in ("MATINEE_API_KEY", "HA_HOOK_SECRET", "HA_WEBHOOK_URL", "ANTHROPIC_API_KEY", "TMDB_READ_TOKEN",
                "WONDERFUL_API_KEY"):
        assert re.search(rf"^{key}=$", ENV, re.M), key


def test_hook_secret_is_generated_only_when_absent(tmp_path):
    conf = tmp_path / "wonderful"
    conf.write_text("PORT=8772\nHA_HOOK_SECRET=kept\n")
    script = shell_fn("add_setting") + "\n" + shell_fn("gen_key") + (
        f'\nadd_setting "{conf}" HA_HOOK_SECRET "$(gen_key)" "secret"'
        f'\nadd_setting "{conf}" LAN_EDIT 1 "lan"\n')
    subprocess.run(["sh", "-c", script], check=True)
    text = conf.read_text()
    assert text.count("HA_HOOK_SECRET=") == 1 and "HA_HOOK_SECRET=kept" in text
    assert "# lan\nLAN_EDIT=1" in text
    assert 'add_setting "$CONF" HA_HOOK_SECRET "$(gen_key)" ' in HEAD


def test_conf_is_root_only():
    assert 'chmod 600 "$CONF"' in HEAD and 'chown root:root "$CONF"' in HEAD


def test_packages_and_folders():
    apk = next(l for l in HEAD.splitlines() if l.startswith("apk add"))
    for pkg in ("python3", "py3-flask", "py3-gunicorn", "py3-pillow", "py3-jwt", "py3-cryptography", "sqlite", "tzdata"):
        assert f" {pkg} " in f" {apk} ", pkg
    assert "pip" not in apk   # runtime dependencies are Alpine packages only
    assert 'mkdir -p "$APP_DIR" "$DATA_DIR/posters" "$DATA_DIR/art" /var/backups/wonderful' in HEAD


def test_init_script():
    s = init_script()
    for needle in ("#!/sbin/openrc-run", 'name="wonderful"', 'command_user="wonderful"', "supervise-daemon",
                   "--chdir /opt/wonderful", "app:app", "/var/log/wonderful.log", "${PORT}"):
        assert needle in s, needle


def test_existing_port_is_kept():
    assert "sed -n 's/^PORT=//p' \"$CONF\"" in HEAD
    assert 'PORT="${WONDERFUL_PORT:-8772}"' in HEAD


def test_backup_job_and_uninstall():
    assert 'install -m 755 "$APP_DIR/ops/wonderful-backup" /etc/periodic/daily/wonderful-backup' in HEAD
    block = HEAD[HEAD.index('"--uninstall"'):HEAD.index("exit 0")]
    for gone in ("/etc/init.d/wonderful", "/etc/periodic/daily/wonderful-backup", '"$APP_DIR"'):
        assert gone in block, gone
    assert "DATA_DIR" not in block.split("echo")[0], "uninstall must keep the data"


def test_nightly_refresh_job_and_uninstall():
    m = re.search(r"cat > /etc/periodic/daily/wonderful-refresh <<'EOF'\n(.*?)\nEOF\nchmod 755 /etc/periodic/daily/wonderful-refresh\n",
                  HEAD, re.S)
    assert m, "the wonderful-refresh wrapper is not written and made executable"
    wrapper = m.group(1)
    assert wrapper.startswith("#!/bin/sh") and "/opt/wonderful/ops/wonderful-refresh" in wrapper
    assert ">> /var/log/ops.log" in wrapper
    subprocess.run(["sh", "-n"], input=wrapper, text=True, check=True)
    block = HEAD[HEAD.index('"--uninstall"'):HEAD.index("exit 0")]
    assert "/etc/periodic/daily/wonderful-refresh" in block
    assert (ROOT / "ops" / "wonderful-refresh").stat().st_mode & 0o111      # the app ships it executable


def test_health_check_uses_the_health_route():
    assert 'add_health_check "Wonderful|http://127.0.0.1:$PORT/api/health|wonderful" wonderful' in HEAD


@pytest.mark.parametrize("initial", ['HEALTH_CHECKS="\nMatinee|http://127.0.0.1:8771/healthz|matinee\n"\n', "FOO=1\n"])
def test_health_check_added_once(tmp_path, initial):
    ops = tmp_path / "ops"
    ops.write_text(initial)
    line = 'add_health_check "Wonderful|http://127.0.0.1:8772/api/health|wonderful" wonderful\n'
    subprocess.run(["sh", "-c", f"OPS_CONF={ops}\n{shell_fn('add_health_check')}\n{line}{line}"], check=True)
    text = ops.read_text()
    assert text.count("|wonderful") == 1
    subprocess.run(["sh", "-n", str(ops)], check=True)


def test_build_ships_every_top_level_module():
    # gunicorn imports app:app, which imports its siblings: a module left out of build.sh installs cleanly and then
    # fails at import on the host.
    cp = next(line for line in BUILD.splitlines() if line.startswith("cp -r ")).split()
    missing = [p.name for p in ROOT.glob("*.py") if p.name not in cp]
    assert not missing, f"installer/build.sh does not ship {missing}"
    for item in ("static", "ops", ".env.example", "README.md"):
        assert item in cp, item


def test_split_modules_are_listed_in_app():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    listed = re.search(r"_SPLIT_MODULES = \(([^)]*)\)", src).group(1)
    modules = sorted(p.stem for p in ROOT.glob("*.py") if p.name != "app.py")
    assert sorted(re.findall(r'"(\w+)"', listed)) == modules


def test_built_installer_carries_the_app(tmp_path):
    subprocess.run(["sh", str(ROOT / "installer" / "build.sh")], check=True, capture_output=True)
    out = (ROOT / "dist" / "setup-wonderful.sh").read_text()
    payload = out.split("__PAYLOAD_BELOW__\n", 1)[1]
    import base64, io
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(payload)), mode="r:gz") as tar:
        names = set(tar.getnames())
    for f in ("wonderful/app.py", "wonderful/auth.py", "wonderful/static/js/package.json", "wonderful/static/js/main.js",
              "wonderful/static/fonts/figtree-latin-wght.woff2", "wonderful/ops/wonderful-backup",
              "wonderful/providers.py", "wonderful/data/services.json", "wonderful/static/js/settings.js"):
        assert f in names, f
    assert not any("__pycache__" in n for n in names)


# ------------------------------------------------------------------------------------------------ the backup
def test_backup_copies_the_database_posters_and_art(tmp_path):
    # needs the sqlite3 CLI (the installer and CI install it): a missing one fails here, it does not skip
    data, backups = tmp_path / "data", tmp_path / "backups"
    (data / "posters").mkdir(parents=True); (data / "art" / "fireplace").mkdir(parents=True)
    (data / "posters" / "10719-p342.jpg").write_bytes(b"jpeg")
    (data / "art" / "fireplace" / "background.webp").write_bytes(b"webp")
    con = sqlite3.connect(data / "wonderful.db")
    con.execute("CREATE TABLE movies (title TEXT)"); con.execute("INSERT INTO movies VALUES ('Elf')"); con.commit()
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "WONDERFUL_DATA": str(data), "LOCAL_DIR": str(backups),
           "LOG": str(tmp_path / "ops.log"), "OPS_CONF": str(tmp_path / "no-ops-conf")}
    r = subprocess.run(["sh", str(ROOT / "ops" / "wonderful-backup")], env=env, capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout, r.stderr, (tmp_path / "ops.log").read_text())
    (day,) = backups.iterdir()
    assert sorted(p.name for p in day.iterdir()) == ["wonderful-art.tar.gz", "wonderful-posters.tar.gz", "wonderful.db.gz"]
    restored = tmp_path / "restored.db"
    restored.write_bytes(gzip.decompress((day / "wonderful.db.gz").read_bytes()))
    assert sqlite3.connect(restored).execute("SELECT title FROM movies").fetchone()[0] == "Elf"
    with tarfile.open(day / "wonderful-art.tar.gz") as tar:
        assert "art/fireplace/background.webp" in tar.getnames()
    with tarfile.open(day / "wonderful-posters.tar.gz") as tar:
        assert "posters/10719-p342.jpg" in tar.getnames()
    assert "ok wonderful.db" in (tmp_path / "ops.log").read_text()


def test_backup_fails_loudly_without_a_database(tmp_path):
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "WONDERFUL_DATA": str(tmp_path / "nothing"),
           "LOCAL_DIR": str(tmp_path / "b"), "LOG": str(tmp_path / "ops.log"), "OPS_CONF": str(tmp_path / "none")}
    r = subprocess.run(["sh", str(ROOT / "ops" / "wonderful-backup")], env=env, capture_output=True)
    assert r.returncode == 1 and "FAILED" in (tmp_path / "ops.log").read_text()


def test_backup_is_atomic():
    text = (ROOT / "ops" / "wonderful-backup").read_text(encoding="utf-8")
    assert ".backup '$out.part'" in text and 'mv -f "$out.gz.part" "$out.gz"' in text
    assert 'mv -f "$tgz.part" "$tgz"' in text
