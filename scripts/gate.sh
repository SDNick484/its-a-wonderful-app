#!/bin/sh
# The verification gate: everything CI checks, in one command (CLAUDE.md, "Definition of done").
#
#   sh scripts/gate.sh              all of it: lint, the whole pytest suite with the UI smoke required, js, build
#   sh scripts/gate.sh lint js      only some steps (CI runs its jobs this way, so CI and this file cannot drift)
#
# Steps: lint (ruff + shellcheck), test (pytest; REQUIRE_UI=1 turns a UI smoke skip into a failure), ui (only the
# Playwright smoke, required), js (node --check on every module, and proof the module marker works), build
# (installer). Uses .venv/bin first when it exists.
set -eu
cd "$(dirname "$0")/.."
if [ -x .venv/bin/python3 ]; then PATH="$PWD/.venv/bin:$PATH"; export PATH; fi
PY=${PYTHON:-python3}

shell_files() {  # every POSIX sh script in the repo: installer/*.sh, scripts/*.sh and the sh ones in ops/
  for f in installer/*.sh scripts/*.sh ops/*; do
    [ -f "$f" ] && head -n1 "$f" | grep -q '^#!/bin/sh' && echo "$f"
  done
  return 0
}

step_lint() {
  echo "==> ruff"
  ruff check .
  echo "==> shellcheck"
  # shellcheck disable=SC2046  # file names have no spaces: word-splitting is the point
  shellcheck -s sh $(shell_files)
}

step_test() {
  echo "==> pytest"
  "$PY" -m pytest -q -rs
}

step_ui() {
  echo "==> UI smoke (Playwright + Chromium, 412 x 915)"
  REQUIRE_UI=1 "$PY" -m pytest -v -rs tests/test_ui_*.py
}

step_js() {
  echo "==> node --check"
  for f in static/js/*.js; do node --check "$f"; done
  # Without static/js/package.json ("type": "module"), node --check exits 0 on a broken file that uses `import`.
  # Prove the marker still makes Node parse modules: a broken copy beside it must be rejected.
  t=$(mktemp -d)
  cp static/js/package.json static/js/core.js "$t/"
  echo 'const x = ;' >> "$t/core.js"
  if node --check "$t/core.js" 2>/dev/null; then echo "node --check accepted a broken module" >&2; rm -rf "$t"; exit 1; fi
  rm -rf "$t"
}

step_build() {
  echo "==> installer"
  sh installer/build.sh
  sh -n dist/setup-wonderful.sh
}

if [ $# -eq 0 ]; then
  step_lint
  REQUIRE_UI=1; export REQUIRE_UI
  step_test
  step_js
  step_build
  echo "==> gate passed"
  exit 0
fi
for s in "$@"; do
  case "$s" in
    lint|test|ui|js|build) "step_$s" ;;
    *) echo "unknown step: $s (lint, test, ui, js, build)" >&2; exit 2 ;;
  esac
done
