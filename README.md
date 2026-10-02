# The Lord of the Rings: Roads Beneath the Shadow

> A pixel-art, choice-driven dark fantasy RPG where trust, clues, and corruption reshape the road ahead.

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Pixel edition](https://img.shields.io/badge/pixel_edition-macOS_%7C_Windows_%7C_Linux-dba85c)](#play-the-pixel-art-edition)
[![Quality Gate](https://github.com/makaboi/roads-beneath-the-shadow/actions/workflows/quality.yml/badge.svg)](https://github.com/makaboi/roads-beneath-the-shadow/actions/workflows/quality.yml)
[![GitHub stars](https://img.shields.io/github/stars/makaboi/roads-beneath-the-shadow?style=social)](https://github.com/makaboi/roads-beneath-the-shadow/stargazers)

**Version 0.4.0 brings the road to life.** Walk through five pixel-art locations, meet animated characters, and explore clues and conversations in the world. Story scenes unfold in readable illustrated pages; battles show the party, enemy intentions, and action feedback together. Both complete episodes and existing saves remain playable in the desktop and terminal editions.

*Roads Beneath the Shadow* is a story-driven RPG set in Middle-earth during the War of the Ring. You play an unknown traveler whose guardian has vanished and whose quiet life ends when a dying messenger delivers a broken silver star.

The game contains two complete playable episodes: **Part I — The Black Rider's Letter** and **Part II — The Dead Road**. Part I is roughly 45–70 minutes; Part II is roughly 110–130 minutes for a normal first playthrough, depending on reading speed, exploration, and combat choices.

![Pixel-art edition main menu](assets/pixel-title.png)

## Play the pixel-art edition

### Download and play

[Download the latest release](https://github.com/makaboi/roads-beneath-the-shadow/releases/latest), extract the complete archive, and launch the game. **Python is not required.** Choose the download for your operating system and processor:

| Platform | Download | Launch after extracting |
| --- | --- | --- |
| macOS, Apple silicon | [macOS Apple silicon ZIP](https://github.com/makaboi/roads-beneath-the-shadow/releases/latest/download/Roads-Beneath-the-Shadow-macOS-Apple-Silicon.zip) | Double-click `Play Roads Beneath the Shadow.command` |
| macOS, Intel | [macOS Intel ZIP](https://github.com/makaboi/roads-beneath-the-shadow/releases/latest/download/Roads-Beneath-the-Shadow-macOS-Intel.zip) | Double-click `Play Roads Beneath the Shadow.command` |
| Windows, x64 | [Windows ZIP](https://github.com/makaboi/roads-beneath-the-shadow/releases/latest/download/Roads-Beneath-the-Shadow-Windows-x64.zip) | Double-click `Roads-Beneath-the-Shadow.exe` |
| Linux, x64 | [Linux TAR.GZ](https://github.com/makaboi/roads-beneath-the-shadow/releases/latest/download/Roads-Beneath-the-Shadow-Linux-x64.tar.gz) | Run `./Roads-Beneath-the-Shadow` from the extracted folder |

Each release includes a matching `.sha256` checksum for every archive and a `START-HERE.txt` guide. A desktop display is required for pixel mode. The game runs offline, and the same executable accepts `--terminal` for terminal play.

### Run from source

Source installation requires **Python 3.10+** on macOS, Windows, or Linux. Install the game into a virtual environment:

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

The pixel edition uses **pygame-ce**. World maps, character animation, illustrations, and original audio are bundled locally; the game does not need an internet connection while playing. The macOS source launcher, `Play Roads Beneath the Shadow.command`, uses the local `.venv` when available.

### Explore the road

At the Prancing Pony, Bree, the wayhouse, the Warden hall, and the Last Lantern, use **WASD** to walk and **E** beside a character, clue, or doorway to interact. Nearby points show what they offer. Walking leads to the same story choices shown in the side menu, so you can also click an option or use its number without crossing the room.

Thirteen unnumbered diamond markers offer small details of these places. Approach one and press **E** to look closer; reading these descriptions is free and leaves your story choices open.

Continue illustrated story pages with **Space** or **Enter**. During battle, enemy cards show health, status, and the next telegraphed intention; choose your target and command from the action menu. Inventory, character, and journal panels keep equipment, relationships, quests, and clues close at hand.

The game records a separate automatic checkpoint at safe story transitions. **Resume checkpoint** restores it from the main menu. Your three manual save slots remain available, and **F5** opens saving while exploring. A checkpoint returns to a story decision rather than a character's exact position in a room or an unfinished combat turn.

![Walk around Bree and inspect the environment](assets/pixel-exploration.gif)

### Pixel controls

| Control | Action |
| --- | --- |
| W / A / S / D | Walk in exploration locations |
| E | Interact with a nearby character, clue, or doorway |
| Click a choice | Select a story, exploration, or combat action |
| Up / Down | Navigate menu choices |
| Return / Space | Reveal or advance the story; confirm a menu selection |
| Backspace | Return to the previous story page |
| Number keys | Choose the corresponding option |
| Tab | Open or close the story archive |
| Page Up / Page Down | Open and scroll the story archive |
| Mouse wheel | Scroll menu choices or an open story archive |
| I / C / J | Inventory, character, and journal at story decisions |
| R | Open the road map at story decisions |
| F5 | Open save slots while exploring |
| M | Return to the main menu at story decisions |
| F11 | Toggle fullscreen |
| Escape | Close a utility panel or return from a menu with Back |

Enter your traveler's name with the keyboard. Resize the window to fit your display. Every exploration choice remains available through the side menu; walking is optional.

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

Set persistent preferences from **Settings**. Sound starts **off**; enable it there or with `--sound` for original ambience, music, and cues. Five subtle scores follow the tavern, northern road, buried halls, Last Lantern, and combat, with smooth transitions between them. Reduced motion quiets character and scene animation while keeping exploration controls available. Combat difficulty choices are **Story**, **Ranger**, and **Shadow**. In a server or CI environment without a desktop, use terminal mode or the headless screenshot command under Development.

## Current features

- Five walkable pixel-art locations with collision, nearby interaction prompts, thirteen optional look spots, animated characters, and direct menu alternatives
- Illustrated story pages that preserve each scene and paragraph in order, with adjustable text reveal and reading position during window resizing
- Animated tactical battle presentation with party and enemy sprites, health and Focus, enemy intentions, status, target cards, and action feedback
- Graphical inventory, character, journal, road map, Chronicle, and enemy inspection panels for equipment, relationships, quests, clues, achievements, and tactical decisions
- A separate automatic story checkpoint alongside three manual save slots, with atomic writes and compatible existing saves
- Eighteen bundled scene illustrations, five world maps, and a shared character animation atlas in a restrained dark fantasy palette
- Five original, seamless ambient scores and quiet optional interaction sounds, all generated from original procedural synthesis
- Two complete episodes: Part I at roughly 45–70 minutes and Part II at roughly 110–130 minutes for a normal first playthrough
- Character name, three distinct backgrounds, and a formative lesson from Calenor
- Five opening tactics that alter clues, trust, resources, and later options
- Substantive conversations with Mara and watchman Tobin Reed
- Rescue, testimony, and prisoner quests whose outcomes carry into later scenes and endings
- Eight encounter slots across both episodes: three in Part I, four mandatory in Part II, and an avoidable duel with Teren
- Telegraphed enemy intentions, target selection, interrupts, status effects, Focus, defense, armor, healing, and encounter objectives
- Reliable defense against multiple enemies: Defend halves every incoming attack that round and restores 1 Focus; companions can protect you during survival objectives
- Recovery after the opening fight keeps the journey moving, and inspecting or switching targets never repeats an enemy's Bleeding damage
- A distinct combat ability for each background, plus different tactical commands for Mara and Tobin
- Story, Ranger, and Shadow combat difficulty modes; Shadow rewards interrupts, defense, and companion tactics instead of damage-racing
- Persistent hope, corruption, clues, companion trust, and quest outcomes across both episodes; completed Part I saves can begin Part II directly from the ending screen
- Eight causally different endings across Parts I and II, each with an explicit recap of the choices that created it
- A persistent Traveler's Chronicle with episode-aware ending records and eleven achievements
- An optional Last Lantern scene before the Part II finale: hear Mara's hopes, share Tobin's watch, or speak to Calenor beyond his Warden duty; these conversations remember earlier choices and return in the ending recap
- Adjustable narration speed, reduced motion, narrow-terminal handling, and screen-reader scene descriptions
- Mouse choices, number keys, arrow navigation, resizing, and fullscreen in the pixel edition; W/S and numbered prompts in the terminal
- A Part I Black Rider cliffhanger, a complete Part II resolution, and a new road toward Part III: *The Waking City*
- Shared story and combat logic across the desktop and terminal presentations

Save files are stored in:

```text
~/Library/Application Support/Roads Beneath the Shadow/saves/
```

Set `RBS_SAVE_DIR` to use a different save location.

On Windows and Linux, the default save directory is `~/.roads_beneath_shadow/saves/`. Both presentations share the same save slots.

The automatic checkpoint is `checkpoint.json` inside the same save directory. Settings and Chronicle progress are stored beside the `saves` folder. Completed journeys have stable IDs, so reopening an ending save cannot duplicate its Chronicle credit.

![Character panel showing the traveler's equipment and relationships](assets/pixel-character.png)

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

The GitHub quality workflow checks the game on macOS, Windows, and Linux. The desktop release workflow builds Linux x64, Windows x64, Apple-silicon macOS, and Intel macOS downloads. Each frozen game verifies its bundled assets, graphical rendering, and terminal input before packaging; all four archives and their SHA-256 checksums publish together. The workflow runs when the project version changes on `main`, or can be started manually.

The code is split into portable systems:

- `pixel_ui.py` — desktop controls and the main-thread bridge to the story engine
- `pixel_world.py` / `pixel_assets/` — walkable maps, collision, interaction points, and character animation
- `narrative.py` — chronological illustrated story pages and resize-aware reading position
- `pixel_battle.py` / `combat_view.py` — tactical battle presentation and immutable combat snapshots
- `pixel_panels.py` / `player_view.py` — inventory, character, and journal panels with immutable player snapshots
- `pixel_art.py` — story illustration selection
- `app.py` / `part_two.py` — story flow, consequences, and endings
- `combat.py` / `models.py` — tactical combat and character state
- `savegame.py` / `checkpoint.py` / `profile.py` / `settings.py` — save slots, automatic checkpoints, Chronicle, and preferences
- `ui.py` — original terminal presentation and accessibility
- `artwork.py` / `journey_artwork.py` / `part_two_artwork.py` — original terminal art
- `audio.py` / `soundscapes.py` — optional original cues, ambience, and nonblocking music transitions
- `content.py` — items, backgrounds, and chapter content

Pixel artwork provenance is bundled with the assets. `scripts/generate_world_assets.py` rebuilds the authored world maps and character atlas; `scripts/generate_soundscapes.py` reproduces the five original ambient WAVs using Python's standard library. Original terminal references remain in `assets/ascii-sources/`; `scripts/generate_marketing_assets.py` regenerates the terminal preview collection. Pillow is a development tool and is not needed to play.

## Roadmap

1. Part III — The Waking City
2. More walkable locations, companion relationship routes, and camp scenes
3. More equipment sets, rare conditions, and enemy archetypes
4. Optional signed macOS application bundle

## Support the journey

- [Star the repository](https://github.com/makaboi/roads-beneath-the-shadow) if you want the road to continue into Part III.
- [Report a bug](https://github.com/makaboi/roads-beneath-the-shadow/issues) if something interrupts your adventure.
- Share your background, major choices, and ending without spoiling the path for new players.

This is an unofficial fan project. Middle-earth and *The Lord of the Rings* are the property of their respective rights holders.
