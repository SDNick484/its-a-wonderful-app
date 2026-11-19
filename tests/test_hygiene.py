"""The repo is public: no personal hostnames, LAN addresses, container IDs or family names in the published tree.

Design history (docs/superpowers/, .superpowers/) records what was true at the time and is exempt. Code, fixtures
and docs use wonderful.example.com, movies.example.com, ha.example.com and 192.168.1.100, and people in tests
and fixtures get made-up names.

This file must not spell out what it guards against, so it matches on hashes: every line is split into lowercase
word tokens (a hostname splits into its dot-separated parts), each token and each pair of neighbouring tokens
joined together (so "ab 12" is also checked as "ab12") is hashed with SHA-256, and the digests are compared with a
frozen set. To block another identifier, add sha256(<lowercase token>).hexdigest() to BLOCKED, never the token.
"""
import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXEMPT = ("docs/superpowers/", ".superpowers/")
SKIP_DIRS = {".git", "dist", "data", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "node_modules", ".queue"}

# sha256 of the lowercase tokens: family first names, the owner's login and domain label, the host container id
BLOCKED = frozenset({
    "522ce7057fd0523adcd6672db24bb671d09d1ffa2f1e7c97c13e6c68ae6fcb13",
    "ad89552caee4dc4c7a33351bca79a0e04c5acf02ac26e307bda621426a7ee101",
    "b918c3f9116ce3a61efd71a1bada0d46c8f575283ce5d5798454a4abfb56ae79",
    "2bd806c97f0e00af1a1fc3328fa763a9269723c8db8fac4f93af71db186d6e90",
    "dc1f68437c6fc4ab54da855326a832845672015ec2e2cc4e19b30870266fb6ab",
    "390e587a4f212f71c73df0e230459c67f438eb87bab74f48d6cbc1afaffb30c9",
    "608ae3ea96619f9fd0bdd8777f65d6e45b92cbd11af7d9634155f2007e25431e",
    "319236f5ad5015707023c7558e4adbeb400f2dc876d18f8801afa1c9ae765bdf",
})
# Test-only: sha256("snowglobetwelve"), a made-up token that proves the mechanism without naming anyone.
SELF_TEST = frozenset({"ddcf437db240cc23ec977afa32b0b7f04708a7e4c56aeddc8fb75e56ed3173c2"})

# any 192.168 address but the documented example (a pattern, not a secret)
LAN_IP = re.compile(r"192\.168\.(?!1\.100\b)\d{1,3}\.\d{1,3}")
TOKEN = re.compile(r"[a-z0-9]+")


def digests(line):
    """SHA-256 of every lowercase token in the line and of every two neighbouring tokens joined."""
    tokens = TOKEN.findall(line.lower())
    words = tokens + [a + b for a, b in zip(tokens, tokens[1:])]
    return {hashlib.sha256(w.encode()).hexdigest() for w in words}


def blocked(line, digest_set=BLOCKED):
    return bool(digests(line) & digest_set)


def tracked_files():
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                             capture_output=True, check=True)
        files = [ROOT / p for p in out.stdout.decode().split("\0") if p]
    except (OSError, subprocess.CalledProcessError):     # no git (a source tarball): walk the tree
        files = [p for p in ROOT.rglob("*") if p.is_file()]
    return [p for p in files if p.is_file() and not SKIP_DIRS & set(p.relative_to(ROOT).parts)]


def hits(check):
    found = []
    for path in tracked_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(EXEMPT):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:                      # fonts, images
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if check(line):
                found.append(f"{rel}:{n}")   # the line itself is not echoed: it holds what we are hiding
    return found


def test_no_personal_identifiers_or_family_names():
    found = hits(blocked)
    assert not found, "personal identifiers or family names found (use made-up names and example.com):\n" + "\n".join(found)


def test_no_personal_lan_addresses():
    found = hits(LAN_IP.search)
    assert not found, "LAN address found (use 192.168.1.100):\n" + "\n".join(found)


def test_the_checks_catch_what_they_should():
    for line in ("rated by Snowglobetwelve", "https://mcp.snowglobetwelve.com/x", "on SNOWGLOBE TWELVE",
                 "snowglobetwelve@example.com"):
        assert blocked(line, SELF_TEST), line
    for line in ("snowglobetwelves", "snow globe", "twelve snowglobes"):
        assert not blocked(line, SELF_TEST), line
    other = "192.168." + "7.23"   # built from parts so the scan above does not flag this file
    assert LAN_IP.search(f"http://{other}:8771") and LAN_IP.search("192.168." + "1.10")
    assert not LAN_IP.search("http://192.168.1.100:8772")
    assert not blocked("A movie night with Ann and Ben at wonderful.example.com")
