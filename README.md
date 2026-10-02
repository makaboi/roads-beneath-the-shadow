# The Lord of the Rings: Roads Beneath the Shadow

> A pixel-art, choice-driven dark fantasy RPG where trust, clues, and corruption reshape the road ahead.

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Pixel edition](https://img.shields.io/badge/pixel_edition-macOS_%7C_Windows_%7C_Linux-dba85c)](#play-the-pixel-art-edition)
[![Quality Gate](https://github.com/makaboi/roads-beneath-the-shadow/actions/workflows/quality.yml/badge.svg)](https://github.com/makaboi/roads-beneath-the-shadow/actions/workflows/quality.yml)
[![GitHub stars](https://img.shields.io/github/stars/makaboi/roads-beneath-the-shadow?style=social)](https://github.com/makaboi/roads-beneath-the-shadow/stargazers)

**Version 0.3.0 adds a desktop pixel-art edition of the complete game.** Play both episodes in a graphical window with mouse and keyboard controls. The original terminal presentation is available with `--terminal`, and existing saves work in either edition.

**Download note:** [older standalone macOS releases](https://github.com/makaboi/roads-beneath-the-shadow/releases/latest) contain the earlier terminal game. Use the source instructions below for the new pixel edition; a new standalone binary has not been released.

*Roads Beneath the Shadow* is a story-driven RPG set in Middle-earth during the War of the Ring. You play an unknown traveler whose guardian has vanished and whose quiet life ends when a dying messenger delivers a broken silver star.

The source edition contains two complete playable episodes: **Part I — The Black Rider's Letter** and **Part II — The Dead Road**. Part I is roughly 45–70 minutes; Part II is roughly 110–130 minutes for a normal first playthrough, depending on reading speed, exploration, and combat choices.

![Pixel-art edition main menu](assets/pixel-title.png)

## Play the pixel-art edition

Requires **Python 3.10+** on macOS, Windows, or Linux with a desktop display. Install the game into a virtual environment:

```bash
git clone https://github.com/makaboi/roads-beneath-the-shadow.git
cd roads-beneath-the-shadow
python3 -m venv .venv
```

On macOS and Linux:

```bash
.venv/bin/python -m pip install .
.venv/bin/python -m roads_beneath_shadow
```

On Windows, use `py` in place of `python3` when creating the environment, then:

```powershell
.venv\Scripts\python.exe -m pip install .
.venv\Scripts\python.exe -m roads_beneath_shadow
```

The pixel edition uses **pygame-ce**. Artwork and sound cues are bundled locally; the game does not need an internet connection while playing. The macOS source launcher, `Play Roads Beneath the Shadow.command`, uses the local `.venv` when available.

### Pixel controls

| Control | Action |
| --- | --- |
| Click a choice | Select a story or combat action |
| Up / Down, W / S | Navigate menus; story `S` opens saves |
| Return / Space | Confirm selection or continue |
| Number keys | Choose the corresponding option |
| Mouse wheel / Page Up / Page Down | Scroll the story or choices |
| I / C / J / S / M | Inventory, character, journal, save, main menu at story decisions |
| F11 | Toggle fullscreen |
| Escape | Return from menus that offer Back |

Enter your traveler's name with the keyboard. Resize the window to fit your display. Long narration and long choice lists remain scrollable.

### Terminal and accessibility

The terminal edition still runs with only the Python standard library:

```bash
python3 -m roads_beneath_shadow --terminal
python3 -m roads_beneath_shadow --screen-reader
```

Screen-reader mode uses terminal prompts and scene descriptions. If this preference was saved, the next launch uses terminal mode; `--pixel` explicitly opens the graphical game.

These options apply to either presentation:

```bash
.venv/bin/python -m roads_beneath_shadow --sound
.venv/bin/python -m roads_beneath_shadow --reduced-motion
.venv/bin/python -m roads_beneath_shadow --text-speed fast
.venv/bin/python -m roads_beneath_shadow --difficulty story
```

Set persistent preferences from **Settings**. Combat difficulty choices are **Story**, **Ranger**, and **Shadow**. In a server or CI environment without a desktop, use terminal mode or the headless screenshot command under Development.

## Current features

- Eighteen bundled pixel illustrations: twelve environment and encounter scenes plus six story props, all at 320×240 with a restrained dark fantasy palette
- Two complete episodes: Part I at roughly 45–70 minutes and Part II at roughly 110–130 minutes for a normal first playthrough
- Character name, three distinct backgrounds, and a formative lesson from Calenor
- Five opening tactics that alter clues, trust, resources, and later options
- Explorable Bree locations and a multi-room North-kingdom wayhouse
- Substantive conversations with Mara and watchman Tobin Reed
- Rescue, testimony, and prisoner quests whose outcomes carry into later scenes and endings
- Eight encounter slots across both episodes: three in Part I, four mandatory in Part II, and an avoidable duel with Teren
- Telegraphed enemy intentions, target selection, interrupts, status effects, Focus, defense, armor, healing, and encounter objectives
- A distinct combat ability for each background, plus different tactical commands for Mara and Tobin
- Inventory, consumable items, and equipment management
- Story, Ranger, and Shadow combat difficulty modes; Shadow rewards interrupts, defense, and companion tactics instead of damage-racing
- Three versioned save/load slots with migration, strict validation, and safe atomic writes
- Persistent hope, corruption, clues, companion trust, and quest outcomes across both episodes; completed Part I saves can begin Part II directly from the ending screen
- Eight causally different endings across Parts I and II, each with an explicit recap of the choices that created it
- A persistent Traveler's Chronicle with episode-aware ending records and eleven achievements
- A cohesive pixel-art scene collection, parchment menus, graphical Health and Focus meters, original optional sound cues, and a retained terminal art mode
- Four-tone scene lighting, a clearer three-Orc opening encounter, and new lantern-lit camp illustrations
- Bold silhouette artwork for the title, inn, mounted Rider, Warg, Ghorak, and both episode finales; inn and Rider animations change light while keeping their subjects in place
- An optional Last Lantern scene before the Part II finale: hear Mara's hopes, share Tobin's watch, or speak to Calenor beyond his Warden duty; these conversations remember earlier choices and return in the ending recap
- Adjustable narration speed, reduced motion, narrow-terminal handling, and screen-reader scene descriptions
- Mouse choices, number keys, arrow navigation, scrollable narration, and fullscreen in the pixel edition; W/S and numbered prompts in the terminal
- A Part I Black Rider cliffhanger, a complete Part II resolution, and a new road toward Part III: *The Waking City*
- Shared story and combat logic across the desktop and terminal presentations

Save files are stored in:

```text
~/Library/Application Support/Roads Beneath the Shadow/saves/
```

Set `RBS_SAVE_DIR` to use a different save location.

On Windows and Linux, the default save directory is `~/.roads_beneath_shadow/saves/`. Both presentations share the same save slots.

Settings and Chronicle progress are stored beside the `saves` folder. Completed journeys have stable IDs, so reopening an ending save cannot duplicate its Chronicle credit.

![Pixel-art combat with telegraphed enemy intent](assets/pixel-combat.png)

## Controls

The terminal edition uses numbered choices. During story decisions:

| Key | Action |
| --- | --- |
| `1`–`9` | Choose a menu or story option |
| `W` / `S`, arrows | Move through supported menus |
| `Return` / `D` | Confirm the highlighted menu choice |
| `I` | Open inventory and equipment |
| `C` | Show character status |
| `J` | Read quests and clues |
| `S` | Save the journey |
| `M` | Return to the main menu |

## Development

Install the development dependencies and run the complete suite:

```bash
.venv/bin/python -m pip install '.[test]'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q roads_beneath_shadow
.venv/bin/python -m roads_beneath_shadow --check-install
```

The graphical tests use dummy SDL drivers and do not open a window. To render a real title-screen screenshot without a desktop on macOS/Linux:

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
  .venv/bin/python -m roads_beneath_shadow --pixel --screenshot /tmp/pixel-title.png
```

On Windows, set `$env:SDL_VIDEODRIVER="dummy"` and `$env:SDL_AUDIODRIVER="dummy"` in PowerShell before the same command. Pixel scenes use nearest-neighbor scaling; the renderer keeps all graphics operations on the main thread while the story engine waits for choices in a worker.

The GitHub quality workflow checks the game on macOS, Windows, and Linux. The macOS packaging workflow builds the pixel edition, bundles all scenes and sounds, and verifies both the graphical screenshot and terminal fallback. It can be run manually or by a release tag matching the project version.

The code is split into portable systems:

- `pixel_ui.py` — desktop rendering, mouse/keyboard controls, scrolling, and the engine bridge
- `pixel_art.py` / `pixel_assets/` — pixel scene selection and bundled artwork
- `app.py` / `part_two.py` — story flow, consequences, and endings
- `combat.py` / `models.py` — tactical combat and character state
- `savegame.py` / `profile.py` / `settings.py` — save slots, Chronicle, and preferences
- `ui.py` — original terminal presentation and accessibility
- `artwork.py` / `journey_artwork.py` / `part_two_artwork.py` — original terminal art
- `audio.py` — optional original sound cues
- `content.py` — items, backgrounds, and chapter content

Pixel artwork provenance is bundled with the assets. Original terminal references remain in `assets/ascii-sources/`; `scripts/generate_marketing_assets.py` regenerates the terminal preview collection. Pillow is a development tool and is not needed to play.

## Roadmap

1. Part III — The Waking City
2. Additional companion relationship routes and camp scenes
3. More equipment sets, rare conditions, and enemy archetypes
4. Native Windows Terminal launcher and full compatibility verification
5. Optional signed macOS application bundle

## Support the journey

- [Star the repository](https://github.com/makaboi/roads-beneath-the-shadow) if you want the road to continue into Part III.
- [Report a bug](https://github.com/makaboi/roads-beneath-the-shadow/issues) if something interrupts your adventure.
- Share your background, major choices, and ending without spoiling the path for new players.

This is an unofficial fan project. Middle-earth and *The Lord of the Rings* are the property of their respective rights holders.
