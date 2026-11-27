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


# ------------------------------------------------------------------------------------------------ starting the title itself
def block_with(text, needle):
    """The fenced yaml block (as one string) that holds `needle`."""
    found = ["\n".join(lines) for lines in yaml_blocks(text) if needle in "\n".join(lines)]
    assert len(found) == 1, f"{needle!r} is in {len(found)} yaml blocks"
    return found[0]


def test_the_doc_starts_a_title_on_netflix_and_youtube():
    text = doc()
    for needle in ("webostv.command", "system.launcher/launch", "m=https://www.netflix.com/watch/{{ content_id }}&source_type=4",
                   "youtube.leanback.v4", "v={{ content_id }}", "content_id", "2026-11-26", "Disney+ ignored"):
        assert needle in text, needle
    assert "^[A-Za-z0-9_-]{1,64}$" in text


def test_the_script_takes_an_optional_content_id_and_falls_back_to_selecting_the_source():
    script = block_with(doc(), "alias: \"Play on the Family Room TV\"")
    fields = script.split("sequence:")[0]
    field = fields.split("content_id:")[1]
    assert "required" not in field and "text:" in field
    stream = script.split("webostv.command")[0]
    assert stream.count("required: true") == 2, "mode and source stay required; content_id is optional"
    # the Netflix and YouTube launches are the two conditions of one choose, and select_source is its default
    after_wait = script.split("seconds: 5")[1]
    assert after_wait.index("- choose:") < after_wait.index("webostv.command") < after_wait.index("default:") \
        < after_wait.index("media_player.select_source") < after_wait.index("switch.watch_a_bluray")
    assert after_wait.count("webostv.command") == 2 and after_wait.count("media_player.select_source") == 1
    assert "source == 'Netflix'" in after_wait and "source == 'YouTube'" in after_wait
    assert "id: netflix" in after_wait and "id: youtube.leanback.v4" in after_wait
    assert "entity_id: media_player.family_room_tv" in after_wait


def test_the_automation_checks_and_passes_content_id():
    automation = block_with(doc(), "webhook_id:")
    condition = automation.split("conditions:")[1].split("actions:")[0]
    # absent passes; present has to be a string of the allowed characters
    assert "trigger.json.content_id is not defined" in condition
    assert "is match('^[A-Za-z0-9_-]{1,64}$')" in condition and "content_id is string" in condition
    assert "or" in condition.split("content_id is not defined")[1].split("is string")[0]
    assert "content_id: \"{{ trigger.json.content_id | default('') }}\"" in automation
    # the old checks are all still there
    for old in ("event == 'wonderful_play'", "mode in ['stream', 'disc']", "(trigger.json.source | default('')) | length > 0"):
        assert old in condition, old


def test_the_doc_shows_the_payload_with_and_without_a_content_id():
    text = doc()
    assert '"title": "Example Movie", "content_id": "80183187"}' in text
    assert '"source": "Disney+", "title": "Example Movie"}' in text
