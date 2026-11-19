"""The Advent calendar (spec §14.2), GET /api/theme on the host's local date, and the household's theme settings.
Review Focus 5 lives here: January 1-6 still shows Santa from the previous Advent, and the date is the host's TZ, not UTC."""
import datetime as dt
import itertools
import struct

import pytest

import app
import themes
from conftest import ROOT

date = dt.date


@pytest.mark.parametrize("d,want", [
    ("2026-11-28", None), ("2026-11-29", "fireplace"), ("2026-12-05", "fireplace"),
    ("2026-12-06", "toystore"), ("2026-12-13", "tree"), ("2026-12-20", "sleigh"),
    ("2027-01-06", "sleigh"), ("2027-01-07", None),            # Review Focus 5
    ("2027-12-19", "sleigh"), ("2027-12-18", "tree"),          # Dec 25, 2027 is a Saturday
    ("2022-12-18", "sleigh"), ("2022-12-11", "tree"),          # Dec 25, 2022 is a Sunday
])
def test_theme_for(d, want):
    assert themes.theme_for(date.fromisoformat(d)) == want


def test_advent_sundays():
    assert [themes.advent_sunday(2026, n) for n in (1, 2, 3, 4)] == [date(2026, 11, 29), date(2026, 12, 6),
                                                                    date(2026, 12, 13), date(2026, 12, 20)]
    assert [themes.advent_sunday(2027, n) for n in (1, 2, 3, 4)] == [date(2027, 11, 28), date(2027, 12, 5),
                                                                    date(2027, 12, 12), date(2027, 12, 19)]
    # Dec 25, 2022 is itself a Sunday, and it is not Advent 4: that is the Sunday a week before.
    assert themes.advent_sunday(2022, 4) == date(2022, 12, 18)
    assert all(themes.advent_sunday(y, n).weekday() == 6 for y in range(2015, 2045) for n in (1, 2, 3, 4))
    for bad in (0, 5, -1):
        with pytest.raises(ValueError):
            themes.advent_sunday(2026, bad)


@pytest.mark.parametrize("year", range(2015, 2045))
def test_every_day_of_every_year_has_one_answer_and_the_windows_fit(year):
    """Advent 1 starts Nov 27 - Dec 3; each theme runs Sunday to Saturday, Santa through Jan 6; every other day is plain."""
    order = list(themes.THEME_KEYS)
    seen = []
    d = date(year, 1, 1)
    while d.year == year:
        seen.append(themes.theme_for(d))
        d += dt.timedelta(days=1)
    assert seen[0] == "sleigh" and seen[5] == "sleigh" and seen[6] is None    # Jan 1-6, then plain
    # the year's own run is fireplace, toystore, tree, sleigh with nothing between them, 7 days each but the last
    runs = [(k, len(list(g))) for k, g in itertools.groupby(seen[6:])]
    assert [k for k, _ in runs] == [None, *order] and runs[1][1] == runs[2][1] == runs[3][1] == 7
    assert date(year, 11, 27) <= themes.advent_sunday(year, 1) <= date(year, 12, 3)


def test_window_gives_the_last_day_the_answer_holds():
    assert themes.theme_window(date(2026, 12, 1)) == ("fireplace", date(2026, 12, 5))
    assert themes.theme_window(date(2026, 12, 20)) == ("sleigh", date(2027, 1, 6))
    assert themes.theme_window(date(2027, 1, 6)) == ("sleigh", date(2027, 1, 6))
    assert themes.theme_window(date(2027, 3, 1)) == (None, date(2027, 11, 27))     # plain until the day before Advent 1
    assert themes.theme_window(date(2026, 11, 20)) == (None, date(2026, 11, 28))


# ------------------------------------------------------------------------------------------------ Review Focus 5
@pytest.mark.parametrize("day", range(1, 7))
def test_january_first_to_sixth_shows_santa_from_the_previous_advent(client, monkeypatch, day):
    monkeypatch.setattr(app, "today", lambda: date(2027, 1, day))
    assert client.get("/api/theme").get_json() == {"theme": "sleigh", "until": "2027-01-06"}


def test_january_seventh_is_plain_until_next_advent(client, monkeypatch):
    monkeypatch.setattr(app, "today", lambda: date(2027, 1, 7))
    assert client.get("/api/theme").get_json() == {"theme": None, "until": "2027-11-27"}


def test_the_theme_follows_the_hosts_tz_not_utc(client, monkeypatch):
    """When it is already Sunday Dec 6 in Auckland it is still Saturday Dec 5 in Samoa: two zones, two themes, both
    from one instant. The route uses common.today(), which reads TZ."""
    real = dt.datetime

    class Frozen(real):
        @classmethod
        def now(cls, tz=None):
            return real(2026, 12, 5, 18, 0, tzinfo=dt.timezone.utc).astimezone(tz)   # 18:00 UTC

    monkeypatch.setattr("common.dt.datetime", Frozen)
    monkeypatch.setenv("TZ", "Pacific/Auckland")        # UTC+13 in December: Sunday Dec 6, 07:00
    assert client.get("/api/theme").get_json() == {"theme": "toystore", "until": "2026-12-12"}
    monkeypatch.setenv("TZ", "Pacific/Pago_Pago")       # UTC-11: Saturday Dec 5, 07:00
    assert client.get("/api/theme").get_json() == {"theme": "fireplace", "until": "2026-12-05"}


def test_the_theme_route_uses_the_real_clock_by_default(client):
    body = client.get("/api/theme").get_json()
    assert body == themes.current(app.today()) and set(body) == {"theme", "until"}


# ------------------------------------------------------------------------------------------------ the household's settings
def test_prefs_default_to_themes_on_and_the_system_look(client):
    assert client.get("/api/theme/prefs").get_json() == {"enabled": True, "mode": "system"}


def test_prefs_are_saved_in_the_database_and_partial_updates_keep_the_rest(client):
    assert client.put("/api/theme/prefs", json={"enabled": False}).get_json() == {"enabled": False, "mode": "system"}
    assert client.put("/api/theme/prefs", json={"mode": "light"}).get_json() == {"enabled": False, "mode": "light"}
    assert client.get("/api/theme/prefs").get_json() == {"enabled": False, "mode": "light"}
    assert client.put("/api/theme/prefs", json={"enabled": True, "mode": "dark"}).get_json() == {"enabled": True, "mode": "dark"}
    with app.app.app_context():     # in the database (meta), not a cookie: every phone in the house sees it
        assert themes.get_prefs(app.get_db()) == {"enabled": True, "mode": "dark"}


@pytest.mark.parametrize("body", [None, [], "dark", {}, {"other": 1}, {"enabled": "yes"}, {"enabled": 1}, {"enabled": None},
                                  {"mode": "sepia"}, {"mode": None}, {"mode": ["dark"]}])
def test_bad_prefs_are_a_400_and_change_nothing(client, body):
    client.put("/api/theme/prefs", json={"mode": "light"})
    r = client.put("/api/theme/prefs", json=body)
    assert r.status_code == 400 and r.get_json()["error"]
    assert client.get("/api/theme/prefs").get_json() == {"enabled": True, "mode": "light"}


def test_an_unreadable_stored_mode_reads_as_system(app_ctx):
    app_ctx.get_db().execute("INSERT INTO meta (k, v) VALUES ('theme_mode', 'neon')")
    assert themes.get_prefs(app_ctx.get_db())["mode"] == "system"


def test_theme_routes_need_an_editor(anon_client):
    for method, path in (("get", "/api/theme"), ("get", "/api/theme/prefs"), ("put", "/api/theme/prefs")):
        assert getattr(anon_client, method)(path, headers={"Cf-Connecting-Ip": "1.2.3.4"}).status_code == 401


# ------------------------------------------------------------------------------------------------ the folders
def webp_size(data):
    """(width, height) from a WebP header: lossy (VP8), lossless (VP8L) or extended (VP8X)."""
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    kind, body = data[12:16], data[20:]
    if kind == b"VP8 ":
        w, h = struct.unpack("<HH", body[6:10])
        return w & 0x3FFF, h & 0x3FFF
    if kind == b"VP8L":
        bits = int.from_bytes(body[1:5], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    assert kind == b"VP8X"
    return int.from_bytes(body[4:7], "little") + 1, int.from_bytes(body[7:10], "little") + 1


@pytest.mark.parametrize("key", themes.THEME_KEYS)
def test_each_theme_folder_has_its_layers(key):
    folder = ROOT / "static" / "themes" / key
    assert sorted(p.name for p in folder.iterdir()) == ["background-wide.webp", "background.webp", "theme.css"]
    for name, size in (("background.webp", (1080, 2340)), ("background-wide.webp", (2340, 1080))):
        data = (folder / name).read_bytes()
        assert webp_size(data) == size, name                          # the master sizes the art pipeline (Task 14) keeps
        assert len(data) < 200_000, name


@pytest.mark.parametrize("key", themes.THEME_KEYS)
def test_theme_css_names_its_own_art_with_relative_paths(key):
    css = (ROOT / "static" / "themes" / key / "theme.css").read_text(encoding="utf-8")
    assert 'url("background.webp")' in css and 'url("background-wide.webp")' in css


def test_theme_files_are_served_without_a_sign_in(anon_client):
    for key in themes.THEME_KEYS:
        for name in ("theme.css", "background.webp", "background-wide.webp"):
            assert anon_client.get(f"/static/themes/{key}/{name}").status_code == 200
