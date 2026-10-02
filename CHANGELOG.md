# Changelog

## 0.4.0 — A Living Pixel World

- Added five walkable locations: the Prancing Pony, Bree, the buried wayhouse, the Warden hall, and the Last Lantern. WASD movement, collision, nearby prompts, and E interactions lead to the same choices offered by the side menu.
- Placed thirteen optional look spots across the maps, marked by unnumbered diamonds; E reveals local details without spending a turn or resources.
- Added a shared character atlas with directional walking and idle animation for travelers, companions, and encounter characters, plus restrained environmental motion and reduced-motion support.
- Presented story scenes as chronological illustrated pages, with adjustable text reveal and reading position preserved when the window changes size.
- Added animated tactical battle panels showing the party, enemies, health, Focus, intentions, status, selectable targets, and action feedback.
- Added graphical inventory, character, journal, road map, Chronicle, and enemy inspection panels while keeping item actions and consequences in the shared game engine.
- Added a separate automatic checkpoint at safe story transitions, Resume checkpoint on the main menu, and F5 saving while exploring. Existing version-2 saves and the three manual slots remain compatible.
- Added R for the road map, Tab for the story archive, Page Up/Down for archive browsing, and Backspace to revisit the previous illustrated story page.
- Made Defend protect against every incoming attack in the round and restore 1 Focus, giving outnumbered travelers a reliable way to recover. Companion guard commands now support survival objectives.
- Added wound recovery after the opening encounter and corrected repeated Bleeding damage when inspecting enemies or changing targets; these free actions no longer advance status effects.
- Composed five original, seamless ambient scores through deterministic procedural synthesis, with scene crossfades and quiet interaction effects. Sound stays off by default and gracefully handles unavailable audio devices.
- Added standalone, checksummed downloads for Linux x64, Windows x64, Apple-silicon macOS, and Intel macOS, with frozen-asset and launch checks before all four publish together.
- Kept both complete episodes, existing story routes, terminal play, screen-reader prompts, and accessibility preferences.

## 0.3.0 — Pixel-Art Edition

- Made the desktop pixel-art game the default presentation, with illustrated dark fantasy scenes, parchment menus, graphical character meters, and mouse and keyboard controls.
- Kept the complete two-episode story, tactical combat, companion routes, quests, inventory, Chronicle, and existing version-2 saves on the same engine.
- Added scrollable narration and choice lists, name entry, resizing, fullscreen, reduced motion, and a headless screenshot command.
- Retained dependency-free terminal play with `--terminal`; screen-reader preferences select the accessible terminal presentation.
- Bundled pixel scenes and sound cues, added pygame-ce installation instructions, and updated GitHub quality and macOS packaging checks for graphical and terminal play.

## Unreleased — Bold Silhouettes

- Rebuilt the title, Prancing Pony exterior, mounted Black Rider, Marsh Warg, Ghorak, ruined-gateway battle, and final-seal confrontation from new flat, high-contrast references that stay recognizable at terminal size.
- Replaced the inn and Rider's changing compositions with dim and bright versions of the same silhouettes. Anchored the dim inn frame to prevent a one-row jump after conversion trimming.
- Recorded exact generation and edit prompts, parent references, image and ASCII checksums, converter polarity, and frame origins; the verification script checks all twelve refreshed references.
- Updated screen-reader descriptions to match the new illustrations and retained the portable 72-column stage, no-color output, and reduced-motion stills.
- Expanded the gameplay GIF to eleven scenes and 33 frames, added four encounter screenshots, and refreshed scene and animation sheets with the same colors used in the game.

## Unreleased — The Last Lantern

- Added four-tone lighting to converted ASCII scenes without changing their raw characters, no-color output, or screen-reader descriptions.
- Regenerated the opening Orc encounter with three separated, stronger silhouettes and added generated-reference artwork for the Midgewater camp and Last Lantern refuge.
- Added an optional pre-finale scene with nine dialogue responses across Mara, Tobin, and Calenor. Earlier shared memories and Ned's fate shape the dialogue; the choices return at the seal and in the ending recap.
- Deepened the Midgewater camp and Calenor's explanation of the years he kept hidden, leaving room for trust to be rebuilt without forcing forgiveness.
- Carried the player's chosen childhood lesson into the Part II descent and reunion, instead of treating every traveler as having chosen kindness.
- Corrected the Part II descent to address Tobin or the lone traveler when Mara is absent, without changing an absent companion's trust.
- Let the traveler carry anger without corruption; an explicit bargain with the star-mark now carries that cost, and both choices return in Calenor's reunion.
- Corrected the ruined-road ending to record Calenor's escape when Teren pays the cost, keeping the lantern memory consistent with his actual fate.
- Kept completed conversations across saves and prevented repeated time, journal, and relationship rewards. Existing version-2 saves remain compatible.
- Made preview generation portable across macOS, Linux, and Windows fonts; refreshed the eight-scene gameplay GIF, covers, screenshots, and scene and animation contact sheets.
- Added provenance checks and a pinned-converter verification command for the three refreshed scene references.
- Made Ctrl-C, Ctrl-D, and closed input exit raw-key menus cleanly, and kept screen-reader menus on numbered line prompts without cursor redraws.

## 0.2.2 — Identifiable Terminal Art

- Rebuilt the Orc attack, tracker, Marsh Warg, Ghorak, final battle, and Black Rider scenes around sparse, recognizable anatomy and props.
- Replaced the dense Rider block with an outlined horse and mounted figure, and tightened the Warg around clear eyes, muzzle, nose, and fangs.
- Added unlabeled, actual-size visual recognition checks during design and structural regression tests for every action sprite.
- Gave the North wayhouse its own exterior art so the final battle is no longer shown before the climax.
- Refreshed the gameplay animation and combat and cliffhanger screenshots.

## 0.2.1 — Readable Retro Art

- Replaced ambiguous symbol wedges with outlined, recognizable retro sprites.
- Added clear encounter nameplates for Orcs, the Marsh Warg, Ghorak, the final battle, and the Black Rider.
- Redrew the Prancing Pony, inn interior, Bree, North Gate, third stone, Midgewater ruins, and buried road.
- Added artwork legibility checks for visual density, negative space, anatomy landmarks, weapons, and terminal width.
- Refreshed the GitHub gameplay animation and screenshots with the new art.

## 0.2.0 — Definitive Edition

This release rebuilds Part I around clearer terminal art, more tactical combat, stronger consequences, and a smoother macOS launch.

### Presentation

- Replaced the original scene icons with a cohesive 64-column retro dark-fantasy art set guided by a generated monochrome concept sheet.
- Added restrained rain and star-light animation with a persistent reduced-motion option.
- Added original optional sound cues for danger, discovery, corruption, victory, and menu feedback.
- Added W/S and arrow-key menu navigation, narrow-terminal wrapping, adjustable narration speed, and screen-reader scene descriptions.

### Combat and choices

- Added telegraphed enemy intentions, target switching, interrupts, status effects, multi-enemy turns, and Ghorak's second phase.
- Added a unique once-per-encounter ability for every origin and distinct tactical commands for Mara and Tobin.
- Added Story, Ranger, and Shadow modes. Shadow requires deliberate interrupts, defense, and companion play rather than repeated damage attacks.
- Rebuilt the ending logic around hope, corruption, discoveries, rescued characters, and companion trust, with four causal endings and a readable consequence recap.

### Player experience

- Added a persistent Traveler's Chronicle, ending history, and seven achievements.
- Added persistent settings for color, sound, narration speed, motion, screen-reader mode, and difficulty.
- Hardened save migration and validation, protected unsaved journeys from accidental replacement, and prevented duplicate ending credit.
- Added verified standalone Apple-silicon and Intel macOS packaging workflows, bundled-data smoke tests, checksums, and cross-platform source tests.
