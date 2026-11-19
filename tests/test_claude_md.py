"""CLAUDE.md's Definition of done names the gate and every CI job, and CI runs the gate's own steps, so the rules
later tasks are checked against cannot drift from what CI checks."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLAUDE = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
GATE = (ROOT / "scripts" / "gate.sh").read_text(encoding="utf-8")


def done_section():
    return CLAUDE.split("## Definition of done", 1)[1]


def ci_jobs():
    return re.findall(r"^  ([a-z][a-z0-9-]*):\s*$", CI.split("\njobs:", 1)[1], flags=re.M)


def test_the_gate_is_one_documented_command():
    assert "sh scripts/gate.sh\n" in done_section()


def test_every_ci_job_is_named():
    assert set(ci_jobs()) == {"lint", "ui-smoke", "test-python", "test-alpine"}
    done = done_section()
    for name in ("Lint (shellcheck + ruff)", "UI smoke", "Python 3.10", "3.11", "3.12", "3.13", "Alpine"):
        assert name in done, name
    assert "seven" in done


def test_ci_runs_on_pull_requests_to_main_on_four_pythons():
    assert re.search(r"pull_request:\n\s+branches: \[ \"main\" \]", CI)
    assert 'python-version: ["3.10", "3.11", "3.12", "3.13"]' in CI
    assert "image: alpine:latest" in CI


def test_ci_jobs_run_gate_steps_and_together_cover_the_whole_gate():
    steps = set()
    for args in re.findall(r"run: sh scripts/gate\.sh ([a-z ]+)$", CI, re.M):
        steps |= set(args.split())
    assert steps == {"lint", "test", "ui", "js", "build"}
    for step in steps:
        assert f"step_{step}() {{" in GATE, step


def test_the_full_gate_requires_the_ui_smoke():
    full = GATE.split('if [ $# -eq 0 ]; then', 1)[1].split("fi", 1)[0]
    assert "REQUIRE_UI=1; export REQUIRE_UI" in full
    for step in ("step_lint", "step_test", "step_js", "step_build"):
        assert step in full, step
    assert "REQUIRE_UI=1" in GATE.split("step_ui() {", 1)[1].split("}", 1)[0]


def test_the_gate_lints_every_shell_script():
    assert "installer/*.sh scripts/*.sh ops/*" in GATE
    assert "shellcheck -s sh" in GATE and "ruff check ." in GATE


def test_the_module_marker_is_proven():
    assert "node --check accepted a broken module" in GATE


def test_smoke_runs_at_phone_size():
    smoke = (ROOT / "tests" / "test_ui_smoke.py").read_text(encoding="utf-8")
    assert '{"width": 412, "height": 915}' in smoke and '"width": 360' in smoke
