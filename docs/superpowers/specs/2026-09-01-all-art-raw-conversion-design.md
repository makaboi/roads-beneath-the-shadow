# Raw Converter Artwork Design

**Date:** 2026-09-01
**Status:** Approved for planning
**Project:** Roads Beneath the Shadow, Part I

## Goal

Replace every visible terminal illustration with compact raw output from
`ascii-image-converter`. Each conversion begins with a purpose-built generated
reference image. The result must preserve the game's current story flow,
animation behavior, accessibility support, and terminal portability.

The player explicitly selected the raw compact treatment. The converter texture
is therefore intentional, even when a manually redrawn silhouette would be more
recognizable.

## Scope

Convert all 24 exported `*_ART` values plus `TITLE_ART_EXPANDED`:

1. Title screen
2. Prancing Pony rain frame
3. Prancing Pony converter frame
4. Prancing Pony exterior animation
5. Prancing Pony interior
6. Orc attack
7. Bree streets
8. North Gate
9. Third Stone discovery
10. Broken star-key
11. Whole star-key
12. Reforged star-key animation
13. Midgewater ruins
14. Road from Bree
15. Broken lantern
16. Drowned watch post
17. North Wayhouse
18. Ancient Road discovery
19. Wayhouse shrine
20. Orc Tracker introduction
21. Marsh Warg introduction
22. Ghorak Ash-Hand introduction
23. Final ruins battle
24. Dim Black Rider frame
25. Black Rider cliffhanger animation

Animated artwork values may reuse their converted frame references, but every
public still and frame must display converted output. Existing exported names
and story call sites remain stable.

## Reference Images

Generate one high-contrast reference PNG for each still or animation state and
store it under `assets/ascii-sources/`. References use:

- A black background and bright foreground subject
- One dominant, centered subject or location
- Thick, separated shapes and open negative space
- A landscape composition suitable for a 72-column terminal stage
- No text, labels, borders, color-dependent meaning, or fine texture

All references share a restrained retro dark-fantasy visual language. A failed
conversion is corrected by regenerating its reference image, not by hand-drawing
the ASCII result.

## Conversion Contract

Use the installed upstream converter with one fixed stage and character map:

```text
ascii-image-converter INPUT \
  --dimensions 72,20 \
  --map " .:-=+*#@"
```

Some generated PNGs encode the empty background as light pixels. For those
references only, add `--negative`. Select the polarity that produces the lower
background density; this changes no shapes and prevents empty space from
becoming a solid `@` field.

The committed ASCII may receive only mechanical cleanup:

- Remove empty outer rows
- Remove trailing whitespace
- Preserve printable ASCII only
- Keep every row at or below 72 columns

No hand tracing, anatomy correction, or decorative additions are allowed.
Encounter nameplates remain outside the converted body through the existing
`_named_ascii_art` helper.

## Runtime Integration

Replace artwork bodies in `roads_beneath_shadow/artwork.py` while preserving:

- Existing exported constant names
- `AnimatedArtwork` and two-frame animation behavior
- Existing `TerminalUI.art` centering and narrow-terminal viewport behavior
- Screen-reader alternative text
- The current ANSI color system and `--no-color` fallback

This change adds no runtime dependency. `ascii-image-converter` remains a
development tool and is not required to launch the game.

## Demo Output

Update `scripts/generate_marketing_assets.py` so
`assets/gameplay-demo.gif` presents every converted scene in story order. The
GIF remains non-interactive and suitable for viewing without launching the
game. Existing representative screenshots are regenerated from the new art.

## Verification

Automated checks must prove that:

- Every source PNG exists and is a valid non-empty image
- Every public artwork value contains printable ASCII only
- Artwork stays within the 72-column terminal stage
- Animated scenes retain two usable frames
- Raw converter bodies are the bodies displayed by their public artwork values
- No-color and screen-reader behavior remain unchanged

Final verification includes the full unit suite, Python compilation,
`git diff --check`, the standalone installation check with an isolated save
directory, and visual inspection of the regenerated GIF and screenshots.

## Deliberate Tradeoff

Raw converter output is less immediately readable than the simplified trace
approach. That loss is accepted because the player explicitly selected the raw
compact treatment. If a scene is unusable, improve only its generated reference
image and reconvert it; do not silently switch treatments.
