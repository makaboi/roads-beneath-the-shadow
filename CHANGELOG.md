# Changelog

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
