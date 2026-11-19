# It's a Wonderful App: rules for agents and contributors

A phone-first Christmas movie picker for one family, built like its sibling Matinee (`SDNick484/matinee`). A Flask
app (`app.py`: the Flask object, request hooks and every route) with route-free code in sibling modules
(`settings.py`, `common.py`, `db.py`, `auth.py`, and more as tasks add them), SQLite, a vanilla-JS SPA (`static/`,
native ES modules in `static/js/`), and an Alpine/OpenRC installer (`installer/`). The design is
`docs/superpowers/specs/2026-11-18-its-a-wonderful-app-design.md`; the plan, task by task, is
`docs/superpowers/plans/2026-11-18-its-a-wonderful-app.md`. Read the code before proposing changes; trust the code
over any doc that disagrees.

**Python modules.** The sibling modules never import `app`, and none holds the Flask object, so a route, an `@app`
hook or an `app.logger` call stays in `app.py` (a sibling logs with `flask.current_app.logger`). `app.py` re-exports
every sibling name: patch and read `app.X` in tests and ops scripts, never the sibling module, because `_AppModule`
copies a write to `app.X` into each module that holds `X`. A new module goes in `_SPLIT_MODULES` and in
`installer/build.sh`'s `cp` line (`tests/test_installer_static.py` fails otherwise).

## Engineering rules

1. **Footprint.** Runtime dependencies are Alpine `py3-*` packages installed by `apk` (the CI Alpine job enforces
   this). No frontend framework, bundler or npm build step; plain files in `static/`. The SPA is native ES modules
   in `static/js/` (`main.js` is the entry): import with `import { name } from "./x.js";`, list exports in one
   `export { … };` at the end, and keep `core.js` free of imports. `render_index()` versions every module through
   an import map, so never hand-edit `?v=`. A new module goes in `JS_MODULES` in `tests/conftest.py`;
   `tests/test_js_modules.py` checks the graph.
2. **Schema.** Changes go through the idempotent `db.migrate()`, which works from every earlier version, and
   `SCHEMA_VERSION` is bumped (it is `"1"`; the whole spec §6 schema is already in v1, so most tasks need no
   migration). No manual DB step on the host, ever.
3. **Tests.** pytest with recorded fixtures in `tests/fixtures/{tmdb,matinee,anthropic}/` and no live network
   (the `client` fixtures make `urllib.request.urlopen` raise). Add a fixture rather than calling an API. Every
   external call has a miss test and an HTTP-error test. Never skip or loosen a test to get green.
4. **CI** must stay green: Python 3.10–3.13 on Ubuntu, the Alpine container job, the lint and UI smoke jobs, and
   `node --check` on every `static/js/*.js`. `static/js/package.json` (`{"type": "module"}`) is what makes Node
   parse them as modules; without it a broken file passes. The CI jobs call `scripts/gate.sh` steps, so a check
   added to CI goes in the gate script.
5. **Auth.** There is no anonymous view. Every route has `@editor_required` (LAN host, Cloudflare Access JWT for
   `ADMIN_EMAILS`, or `WONDERFUL_API_KEY`), except `/hooks/*` (`@hook_required`: `X-Hook-Secret` =
   `HA_HOOK_SECRET`) and `/static/`. `tests/test_auth.py` walks every rule in `app.url_map`; a new route must pass it.
6. **Phone-first.** Android Chrome at 412 px is the primary screen: at least 3 poster columns and no horizontal
   scroll at 412 px and 360 px, tap targets ≥ 44 px, text contrast ≥ 4.5:1 (WCAG AA) including over themes. A UI
   change gets a Playwright check in the smoke tests (`tests/test_ui_*.py`, run by the ui-smoke job). Colours in
   `style.css` are `light-dark()` pairs (themes are always dark); a theme's `theme.css` never changes the scrim's
   floor (`--scrim-min`), and a new text colour is added to `TOKENS` in `tests/test_theme_ui.py`, which checks it over
   a white drawing.
7. **Settings.** Every new setting goes in `.env.example` (with a comment line above it), in `settings.py`, in the
   installer's `add_setting` list (add missing keys, never overwrite), and in the init script's `export` line
   (`tests/test_installer_static.py` checks all four). Anything new in `$DATA_DIR` must be covered by
   `ops/wonderful-backup` and kept by the installer.
8. **Ratings.** 0.0–10.0 in 0.5 steps (`common.validate_rating`, 400 otherwise). Matinee receives the per-person
   mean rounded to the nearest 0.5, half up (`common.round_half_up`: 8.25 → 8.5, 8.75 → 9.0), never `null`.
   Dates are the host's local date (`common.today()`, `TZ`), never UTC.
9. **Attribution.** TMDB attribution (logo + notice) on the about screen; JustWatch attribution wherever watch
   providers show.
10. **Hygiene.** The repo is public. No personal hostnames, LAN addresses, container IDs or family names outside
    the exempt design history in `docs/superpowers/` (`tests/test_hygiene.py`). Use `wonderful.example.com`,
    `movies.example.com`, `ha.example.com`, `192.168.1.100`, and made-up names for people in tests and fixtures.
11. **Commits.** Conventional Commits (`feat(scope):`, `fix:`, `docs:`, `chore:`, `ci:`, `test:`), one logical
    change each, on a feature branch merged by PR, one PR per plan task. Author
    `SDNick484 <SDNick484@users.noreply.github.com>`.
12. **Docs and shell.** The owner runs Gentoo and the host is Alpine. Write OpenRC commands
    (`rc-service wonderful restart`), never systemd, and say `vim`, not `vi`. A feature that changes what the app
    does updates `README.md` in the same PR.

## Workflow (Superpowers)

- Specs: `docs/superpowers/specs/YYYY-MM-DD-<feature>-design.md`
- Plans: `docs/superpowers/plans/YYYY-MM-DD-<feature>.md`
- Subagent-driven-development ledger: `.superpowers/sdd/`; reviews: `.superpowers/review/`

Each plan task is a "Prompt:" issue. Read the task and the spec sections it cites, then TDD on a feature branch.
The plan's **Review Focus** section lists the failure cases reviewers check first; a task that owns one of those
tests must ship it. Tasks tagged **(M)** end their PR description with a "Try it" note: what to open on the phone
after the deploy, and what should show.

## Definition of done

Run the gate and report its result before opening the PR. It is one command, and it runs everything CI runs
(ruff, shellcheck, the whole pytest suite with the Playwright smoke required, `node --check`, and the installer
build):

```sh
sh scripts/gate.sh
```

It uses `.venv/bin` when there is one (`python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt &&
.venv/bin/python -m playwright install chromium`). Report pytest's summary line and any skip with its reason; with
the gate's `REQUIRE_UI=1` a missing browser fails rather than skips. The steps also run one at a time:
`sh scripts/gate.sh lint|test|ui|js|build`.

Then push the branch, open a PR against `main` (do not merge it), and wait for CI: all seven jobs must finish green:
Lint (shellcheck + ruff), UI smoke (Playwright + Chromium, 412 px), Python 3.10, 3.11, 3.12 and 3.13 on Ubuntu,
and Alpine. If one fails, fix it, push, and wait again.
