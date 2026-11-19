"""The art pipeline (spec §14.4, plan Task 14): ops/prepare-theme turns a photo of a drawing into a theme's two
pictures. The photo is generated here with Pillow (a rotated, GPS-tagged JPEG), so no binary fixture is needed."""
import importlib.machinery
import importlib.util
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ORIENTATION, GPS_IFD = 0x0112, 0x8825


def load_cli():
    """ops/prepare-theme has no .py suffix, so load it by path."""
    loader = importlib.machinery.SourceFileLoader("prepare_theme", str(ROOT / "ops" / "prepare-theme"))
    spec = importlib.util.spec_from_loader("prepare_theme", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


prepare_theme = load_cli()


@pytest.fixture
def themes(tmp_path):
    """A stand-in for static/themes with two theme folders."""
    for key in ("fireplace", "sleigh"):
        (tmp_path / key).mkdir()
        (tmp_path / key / "theme.css").write_text("#scene {}\n")
    return tmp_path


def drawing_photo(path):
    """A portrait drawing as a camera would store it: 3000 x 4000 pixels as displayed, a red top third and a blue
    bottom, saved sideways with EXIF orientation 6 (turn 90 degrees clockwise to display) and a GPS location."""
    display = Image.new("RGB", (3000, 4000), (0, 0, 255))
    display.paste((255, 0, 0), (0, 0, 3000, 1333))
    stored = display.transpose(Image.Transpose.ROTATE_90)        # 4000 x 3000 on disk
    exif = stored.getexif()
    exif[ORIENTATION] = 6
    exif.get_ifd(GPS_IFD).update({1: "N", 2: (37.0, 0.0, 0.0), 3: "W", 4: (122.0, 0.0, 0.0)})
    stored.save(path, "JPEG", quality=95, exif=exif.tobytes())
    return path


def test_prepare_theme_crops_and_strips_exif(tmp_path, themes):
    photo = drawing_photo(tmp_path / "drawing.jpg")
    assert Image.open(photo).getexif().get(ORIENTATION) == 6
    portrait, wide = prepare_theme.prepare("fireplace", photo, themes)

    assert portrait == themes / "fireplace" / "background.webp"
    assert wide == themes / "fireplace" / "background-wide.webp"
    with Image.open(portrait) as img:
        assert img.size == (1080, 2340) and img.format == "WEBP"
        assert not img.getexif() and "exif" not in img.info
        # the orientation was applied: the red top of the drawing is at the top, the blue bottom at the bottom
        assert img.getpixel((540, 100))[0] > 200 and img.getpixel((540, 2240))[2] > 200
    with Image.open(wide) as img:
        assert img.size == (2340, 1080) and not img.getexif() and "exif" not in img.info
    raw = portrait.read_bytes() + wide.read_bytes()
    assert b"EXIF" not in raw and b"XMP " not in raw
    assert not list(portrait.parent.glob("*.tmp"))            # the temp files were replaced, not left behind


def test_unknown_theme_is_refused_and_writes_nothing(tmp_path, themes):
    photo = drawing_photo(tmp_path / "drawing.jpg")
    with pytest.raises(ValueError, match="no theme called 'castle'"):
        prepare_theme.prepare("castle", photo, themes)
    assert prepare_theme.main(["castle", str(photo)], themes_dir=themes) == 2
    assert not (themes / "castle").exists()
    assert not list(themes.rglob("*.webp"))


def test_unreadable_photo_is_refused_and_keeps_the_old_pictures(tmp_path, themes):
    (themes / "fireplace" / "background.webp").write_bytes(b"old picture")
    bad = tmp_path / "not-a-picture.jpg"
    bad.write_text("this is text, not a photo")
    assert prepare_theme.main(["fireplace", str(bad)], themes_dir=themes) == 1
    assert (themes / "fireplace" / "background.webp").read_bytes() == b"old picture"

