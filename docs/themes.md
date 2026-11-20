# Draw the pictures for the app

Each week before Christmas, the app wears a new picture behind the movie posters. You can draw them.

There are four pictures. Each one has a short name:

| Name | When it shows |
|------|---------------|
| `fireplace` | From the first Sunday of Advent |
| `toystore` | From the second Sunday of Advent |
| `tree` | From the third Sunday of Advent |
| `sleigh` | From the fourth Sunday of Advent, until January 6 |

All four pictures are drawn now. To change one, follow the steps again with a new drawing.

## What you need

- Paper, and something to draw with
- A phone with a camera
- Daylight, and a table to put the paper on

## Steps

1. **Draw it tall.** Hold the paper up and down, like the phone. Draw the whole page. The posters sit on top of
   your picture, so the middle and the edges are the parts people see most.

2. **Take a photo in daylight.** Lay the paper flat on the table. Hold the phone straight above it, so the paper
   is not tilted and there is no shadow on it.

3. **Save the photo in the `art/originals` folder.** Give it a short name, like `fireplace.jpg`.

4. **Ask a grown-up to make the picture ready.** They type this in the Terminal, from the app's folder. Use the
   name from the table, and the photo's name:

   ```
   ops/prepare-theme fireplace art/originals/fireplace.jpg
   ```

   It makes two pictures for the app, one for phones and one for computers. Your photo is not changed.

5. **Look at it.** Open the app on the phone and go to **Settings**, then **Preview themes**, then pick your
   picture.

Want another try? Draw again, take a new photo, and do step 3 and step 4 again. The new picture takes the place of
the old one.

**Stuck, or the paper edges show?** Ask Claude to help clean up the photo first, for example to take away the
background. Save the cleaned photo in `art/originals` and do step 4 with that one.

---

## For a grown-up

- `ops/prepare-theme <name> <photo>` writes `static/themes/<name>/background.webp` (1080 × 2340, the phone) and
  `background-wide.webp` (2340 × 1080, the computer). It crops from the middle, applies the photo's rotation, and
  removes the photo's location and camera data. It needs Pillow: `py3-pillow` on the host, `pip install Pillow` on a
  computer.
- The computer picture is wide, so it only has room for about a third of a tall drawing. `--wide-y` picks which
  third: 0 the top, 0.5 the middle (the default), 1 the bottom. The current art was made with:

  | Theme | Command |
  |-------|---------|
  | `fireplace` | `ops/prepare-theme fireplace art/originals/fireplace.jpg --wide-y 1` (the fire) |
  | `toystore` | `ops/prepare-theme toystore art/originals/toystore.jpg --wide-y 0.3` (the shelves and the tree) |
  | `tree` | `ops/prepare-theme tree art/originals/tree.jpg --wide-y 0.75` (the tree, star first) |
  | `sleigh` | `ops/prepare-theme sleigh art/originals/sleigh.jpg --wide-y 0.22` (the moon and the sleigh) |

- Each picture must stay under 200 KB (a test checks it). The script starts at WebP quality 82 and steps down, then
  smooths the pencil grain a little, until it fits.
- A new drawing puts things in new places, so check each theme's `theme.css`: `--fx-x`/`--fx-y` (where the
  fireplace's sparks rise and the tree's glow sits) and `--moon-x`/`--moon-y` (the sleigh's halo, and the height the
  gold sleigh flies at). Each has its own values for the phone and, under `orientation: landscape`, the computer.
- The script reads JPEG and PNG photos. An iPhone photo saved as HEIC must be saved as JPEG first.
- The originals in `art/originals/` are kept in git. Keep photos small (a phone photo is fine).
- The app picks up the new pictures after the next deploy: run the installer again (`sh setup-wonderful.sh`) or
  copy the `static/themes` folder over.
