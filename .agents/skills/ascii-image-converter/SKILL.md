---
name: ascii-image-converter
description: Use when creating or revising generated-reference terminal artwork for Roads Beneath the Shadow, especially PNG-to-ASCII conversion, polarity selection, provenance, or preview regeneration.
license: Apache-2.0
metadata:
  source: https://github.com/TheZoraiz/ascii-image-converter
---

# ASCII Image Converter

## Overview

The generated reference is the source of truth. Convert it exactly to the game's 72-by-20 stage; never hand-trace or "fix" the resulting ASCII. If the silhouette is weak, regenerate the reference.

## Reference image

Use a 3:2 monochrome reference with one dominant centered silhouette, thick separated shapes, and large pure-black negative space. Avoid text, borders, fine texture, gradients, tiny props, and overlapping figures. Keep the accepted PNG in `assets/ascii-sources/` and record its exact prompt in the adjacent manifest.

## Convert

Read the executable, version, dimensions, and character map from the manifest. The current Part II profile is:

```bash
/opt/homebrew/bin/ascii-image-converter INPUT \
  --dimensions 72,20 \
  --map " .:-=+*#@"
```

Run the same command once with `--negative`. Clean both outputs only by removing outer blank rows and per-line trailing whitespace. Select the polarity with fewer non-space characters so the background remains empty; record the choice in `manifest.json`.

Do not resize, redraw, relabel, or alter raw converter characters. Encounter nameplates belong in the existing `_named_ascii_art` wrapper, never in the raw `_SPRITE` or `_FRAME` constant. Animation pairs must preserve geometry and change illumination only.

## Integrate

- Put exact raw output in the owning artwork module.
- Bind public art to the real scene state with verbatim manifest alt text.
- Guard companion-specific compositions when a depicted companion is absent.
- Regenerate the GIF and contact sheet after public art changes.
- Keep Pillow, image generation, and the converter out of runtime imports.

## Verify

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q roads_beneath_shadow tests scripts
git diff --check
```

The exact-converter test must run without skipping on the target Mac. Visually inspect the contact sheet and every raw animation frame at full size.

Source: [TheZoraiz/ascii-image-converter](https://github.com/TheZoraiz/ascii-image-converter), Apache-2.0.
