"""docs/home-assistant.md is what the owner copies into Home Assistant, so it is kept honest here.

There is no YAML parser in the dev environment (and no new dependency), so the checks are on text: the pieces the
Play on TV script and webhook automation must have, and a cheap structural check on every fenced yaml block (spaces
only, even indentation).
"""
import re
from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "docs" / "home-assistant.md"
FENCE = re.compile(r"^( *)```yaml\n(.*?)^ *```", re.S | re.M)
BLOCK_SCALAR = re.compile(r":\s*[>|][-+]?\s*$")


def doc():
    return DOC.read_text(encoding="utf-8")


def yaml_blocks(text):
    """Every fenced yaml block, with the fence's own indent (a block inside a list item) taken off."""
    blocks = []
    for m in FENCE.finditer(text):
        indent = len(m.group(1))
        lines = [ln[indent:] if ln.startswith(" " * indent) else ln for ln in m.group(2).splitlines()]
        blocks.append(lines)
    return blocks


def test_the_doc_has_the_play_pieces():
    text = doc()
    for needle in ("Play on the Family Room TV", "wonderful_play", "wonderful_play_on_tv", "local_only: true",
                   "allowed_methods", "mode: restart", "switch.watch_tv", "switch.watch_a_bluray",
                   "script.turn_on", "continue_on_timeout: false", "HA_PLAY_WEBHOOK_URL",
                   "/etc/conf.d/wonderful", "rc-service wonderful restart", "Traces", "<a long random id>"):
        assert needle in text, needle


def test_the_doc_is_openrc_and_vim_only():
    text = doc()
    assert "systemctl" not in text
    assert not re.search(r"\bvi\b", text)


def test_the_doc_says_what_counts_as_a_copy():
    text = doc()
    assert "physical copy" in text and "digital copy" in text and "Fandango at Home" in text
    assert "(a\ndisc)" not in text and "is owned" not in text


def test_the_automation_hands_off_without_waiting():
    """The app waits 5 s for the webhook's answer, so the automation must start the script and return."""
    text = doc()
    assert "action: script.turn_on" in text
    assert "action: script.wonderful_play_on_tv" not in text


def test_yaml_blocks_use_spaces_and_even_indentation():
    blocks = yaml_blocks(doc())
    assert len(blocks) >= 5, "the doc's yaml blocks were not found"
    for lines in blocks:
        scalar_indent = None            # inside a `>-` or `|` block: free-form text, not structure
        for ln in lines:
            assert "\t" not in ln, f"tab in yaml: {ln!r}"
            if not ln.strip():
                continue
            indent = len(ln) - len(ln.lstrip(" "))
            if scalar_indent is not None:
                if indent > scalar_indent:
                    continue
                scalar_indent = None
            assert indent % 2 == 0, f"odd indentation in yaml: {ln!r}"
            if BLOCK_SCALAR.search(ln):
                scalar_indent = indent
