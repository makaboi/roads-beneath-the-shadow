# Part II — The Dead Road Design

**Date:** 2026-09-01
**Status:** Approved for planning and implementation
**Project:** Roads Beneath the Shadow

## Goal

Extend the existing macOS Terminal RPG with a complete second episode that
continues every Part I journey, delivers 110–130 minutes on a normal first
playthrough, and ends with a decisive resolution plus a Part III cliffhanger.
Optional exploration may extend a completionist route to roughly 135 minutes.

Part II must feel authored rather than padded. Its playtime comes from
exploration, consequence-bearing dialogue, two quests, tactical combat, and
route variation—not repeated prose or mandatory grinding.

## Product Shape

Part II uses one shared dramatic spine with conditional scenes and encounter
modifiers. Part I consequences change available paths, companion presence,
dialogue, resources, and ending access without creating separate campaigns.

The episode contains:

- One direct continuation from every Part I ending
- A prologue and five chapters
- Four mandatory tactical encounters and one avoidable encounter
- Four linked main objectives and two optional quests
- Four Part II endings
- Forty new generated-reference ASCII compositions
- One shared cliffhanger pointing toward ruined Fornost

The game remains a dependency-free Python application at runtime. Part II adds
no dialogue engine, event bus, content DSL, database, or third-party package.

## Pacing Contract

`GameState.play_minutes` remains an authored estimate and is cumulative across
episodes. Automated routes measure the Part II delta from the continuation
boundary.

| Section | Target | Play |
| --- | ---: | --- |
| Prologue — The Door Below | 12 minutes | Recap, party handoff, pursuit survival |
| Chapter 2 — The Road of Names | 23 minutes | Hall exploration, testimony, Echo Bridge |
| Chapter 3 — The Drowned Mile | 24 minutes | Rescue quest, flood choice, Chain Troll |
| Chapter 4 — The House Under Ash | 24 minutes | Mara and childhood truths, Teren confrontation |
| Chapter 5 — Calenor's Chain | 18 minutes | Reunion, judgment, ritual preparation |
| Chapter 6 — The Last Seal | 19 minutes | Final survival battle, seal decision, ending |
| **Typical total** | **120 minutes** | Four mandatory combats |

Acceptance ranges:

- Typical scripted first playthrough: 110–130 Part II minutes
- Completionist route: no more than 140 Part II minutes
- At least 35 meaningful non-combat prompts
- Four mandatory encounters; a fifth only when evidence cannot prevent Teren's duel
- Art appears at major transitions, discoveries, introductions, battles, and
  endings—not during every paragraph

One manual macOS playthrough at the default text speed validates that the
authored estimate feels credible. Automated tests do not claim real wall-clock
reading speed.

## Story Structure

### Prologue — The Door Below

The player descends while the Black Rider enters the wayhouse above. Calenor's
broken sword can delay the Rider but cannot wound it. Mara and Tobin appear only
when their Part I handoff flags say they continued. The opening encounter is a
four-round survival objective while the party closes a falling seal-gate.

The episode restores a player who entered at one Health to at least half Health
and refills Focus before control returns. This is framed as a brief warding rest,
not an unexplained reset.

### Chapter 2 — The Road of Names

The Dead Road opens into the Hall of Eight. The lost realm was governed by
eight wardens rather than eight kings. The silver star preserves the Eighth
Warden's Name—an oath-title the Shadow can use only if the player speaks it
willingly.

Players explore two of three chambers on the critical path and may return for
the third:

1. The Cipher Archive reveals how the wardens hid commands inside road marks.
2. The Erased Statue reveals that the eighth warden was deliberately removed
   from public memory.
3. The Dead Testimony reveals the first part of the oath and advances **Names
   of the Lost**.

At Echo Bridge, Ash-Hand remnants attempt to destroy the crossing. The battle
uses multiple targets and a protect-the-bridge objective. Hidden-route knowledge
opens a safer approach; Tobin's presence changes ranged support.

### Chapter 3 — The Drowned Mile

Ghorak's surviving Orcs are flooding the road and moving captives toward the
Shadow. The player chooses between rescuing prisoners, protecting the old road,
or racing toward Calenor. Rescuing the prisoners opens **Prisoners of Ash** and
provides witnesses and ritual aid later. Ignoring them preserves initiative but
costs Hope and companion trust.

A chained cave troll guards the sluice. Its first phase is restrained but
armored; breaking or exploiting the chains changes its second-phase intent
pattern. Afterward, the player decides whether to drain the mile, preserve its
ancient wards, or collapse the flooded branch.

### Chapter 4 — The House Under Ash

An underground refuge mirrors the house that burned in the player's childhood.
The location connects Mara's former captivity, the player's hidden identity,
and the betrayal of the wardens.

Teren, a Ranger traitor foreshadowed by Part I clues, admits that he exposed the
Eighth Warden's household. Calenor rescued the child and concealed their
birth-name so the Shadow could not command the seal. Two strong pieces of
evidence—or the Ranger token combined with one testimony—allow a nonviolent
confrontation. Otherwise Teren becomes the optional fifth encounter.

The player may spare, bind, or kill Teren. Each choice changes information,
Mara's trust, corruption, and the final ritual.

### Chapter 5 — Calenor's Chain

Calenor is alive and bound as the temporary anchor of the failing seal. The
reunion is an extended dialogue rather than another fight. The player may
forgive him, condemn him, or command him to finish his duty. Calenor reveals
that the Rider needs the player to willingly speak the Eighth Name.

This chapter resolves **Descend the Dead Road and reach Calenor**, completes the
remaining testimonies available on the route, and prepares the final ritual.

### Chapter 6 — The Last Seal

The party reaches an eight-spoked vault. The Black Rider attacks while the
companions perform the chosen ritual. It cannot be killed; the encounter is a
six-round survival objective. Performance changes the ritual's cost and who can
escape, not whether the Rider dies.

The final choice is to renew, remake, destroy, or claim the seal. Available
choices and their outcomes depend on testimony, prisoner rescue, corruption,
Calenor's judgment, Teren's fate, companion bonds, and battle performance.

## Quests

Main quests:

- Descend the Dead Road and reach Calenor
- Learn why the silver star is the last seal
- Keep the Eighth Name from the Black Rider
- Decide the fate of the Dead Road

Optional quests:

- **Names of the Lost:** recover three Warden testimonies. Required for the
  strongest version of the Living Road ending.
- **Prisoners of Ash:** free the road-captives before the sluice opens. Their
  survival supplies ritual help and moral proof during the finale.

Part I handoff also cleans up the two dangling Part I objectives concerning
Calenor's north-gate mark and finding the Dead Road.

## Tactical Encounters

1. **Black Rider Pursuit** — survive four rounds while a seal-gate closes.
2. **Ash-Hand Remnants** — defeat an Orc sapper, commander, and archer before
   Echo Bridge falls.
3. **The Chain Troll** — two-phase objective boss shaped by the player's sluice
   and chain choice.
4. **Teren the False Ranger** — avoidable duel when evidence is insufficient or
   the player attacks.
5. **Black Rider at the Last Seal** — survive six rounds while the ritual resolves.

New enemy factories compose the existing intents, phase thresholds,
difficulty profiles, objectives, companion aid, and deterministic RNG. No new
combat subsystem is introduced. Every factory returns a fresh mutable `Enemy`.

Companion aid is based on presence flags, not trust alone. A trusted companion
who remained above cannot appear in combat.

## Consequence Contract

| Input or choice | Immediate effect | Later payoff |
| --- | --- | --- |
| Hidden route known | Opens Warden stair | First testimony, safer bridge approach, best-ending access |
| Shadow foothold | Rider starts closer; star whispers | Harder resistance choices and easier Shadow ending |
| Mara distrusts player | Mara follows at distance | She may leave unless prisoners are freed or truth is shared |
| Tobin continues | Enables combat aid | Pinning support and final lantern route |
| Tobin carries Ned's watch | Enables altered aid | Grief dialogue and sacrifice protection |
| Speak a name in the Hall | Gains lore at a moral cost | Gives the Rider leverage later |
| Rescue prisoners | Costs initiative | Final allies, Hope, and ritual proof |
| Preserve road | Retains wards | Easier renewal, fewer rescued allies |
| Race onward | Keeps initiative | Easier next encounter, relationship cost |
| Spare, bind, or kill Teren | Changes evidence and morality | Alters the witness available at the seal |
| Forgive, condemn, or command Calenor | Defines the guardian bond | Changes who volunteers to anchor the ritual |
| Renew, remake, destroy, or claim | Resolves the episode | Selects the Part II ending |

New durable state uses the existing Boolean `flags`, `visited`, quests,
journal, inventory, and trust scores. No new reputation meter or general
counter system is added. The Part I ending is preserved as exactly one Boolean
flag named `part_one_ending_<ending_id>` before `ending` is cleared.

## Endings

### The Living Road

The player recovers all testimonies, rescues the prisoners, resists the Shadow,
and maintains at least one strong companion bond. The seal is remade as a
freely shared oath and Calenor survives.

### The Last Warden

The old seal is renewed. Calenor remains below as its anchor while the company
escapes.

### The Road in Ruin

The route is destroyed. Calenor or a spared Teren stays behind to collapse it,
barring the Rider at permanent cost.

### The Shadow's Name

The player claims the road or reaches the ritual with dominant corruption. The
Rider learns part of the Eighth Name and gains access to the buried network.

All endings reveal an underground map whose next sealed spoke glows beneath
ruined Fornost. The closing line is: “We guarded the road. The Shadow was
waking the city.”

## Continuation and Save Design

The Part I ending screen adds `Begin Part II — The Dead Road` after its existing
Save and Main Menu choices so current input numbers remain stable.

The continuation operation is idempotent and atomic from the player's point of
view:

1. Preserve the Part I ending in a one-hot Boolean flag.
2. Recompute missing stable Part II consequence flags for older completed saves.
3. Clean up dangling Part I quests.
4. Remove `star_key` after it locks into the door.
5. Add `calenor_broken_sword` to the item catalog and inventory.
6. Restore the minimum safe Health and Focus described in the prologue.
7. Clear `ending`, set `chapter=2`, set `scene="part2_descent"`, and set
   `part_two_started=True`.
8. Add the opening Part II quests.

Existing save fields already represent all required Part II state, so
`SAVE_VERSION` remains 2. Every Part II checkpoint uses a `part2_*` scene ID in
`VALID_SCENE_IDS`. Active Part II states keep `ending=None`; a final Part II
ending sets `scene="complete"` under the existing validation invariant.

Scene/chapter validation rejects `part2_*` scenes outside Chapter 2. Old v1 and
v2 Part I saves remain loadable and are changed only when the player explicitly
begins Part II.

Every one-time reward, trust change, quest transition, minute increment, and
ending transition is guarded against save/re-entry duplication. Saves resume at
coarse scene boundaries rather than in the middle of combat rounds.

## Module Boundaries

- `app.py` remains responsible for the main menu, character creation, Part I,
  save/load UI, inventory, Chronicle, and top-level dispatch.
- New `part_two.py` owns Part II story scenes and exposes a narrow episode
  controller used by `Game`.
- `combat.py` keeps the engine and adds only fresh Part II enemy factories.
- `content.py` keeps shared items, quests, and ending text.
- New `part_two_artwork.py` contains only Part II ASCII constants and restrained
  animations.
- `models.py`, `savegame.py`, and `profile.py` receive only the compatibility
  changes required by Part II.

The Part II controller receives the existing UI, story-choice behavior, and a
combat callback. `GameState` remains the sole durable journey state. There is no
second save model and no generic scene language.

## Chronicle Design

Profile recording distinguishes episode completions using
`<journey_id>:part_<chapter>` while still accepting existing unqualified Part I
journey IDs. Part I and Part II each record once. Existing profile files migrate
through tolerant loading without a destructive reset or `PROFILE_VERSION` bump.

The Chronicle labels Part I and Part II outcomes separately and adds only the
achievements directly supported by the finished episode:

- The Dead Road — Complete Part II
- Names Remembered — Recover all three Warden testimonies
- None Forsaken — Rescue the prisoners and keep every available companion alive
- No Name for the Shadow — Reach the Living Road ending without accepting the star's power

## Artwork Direction

Part II preserves the approved Part I conversion contract:

```text
ascii-image-converter INPUT \
  --dimensions 72,20 \
  --map " .:-=+*#@"
```

Use `--negative` only when it creates the sparser background. Every reference is
a purpose-built high-contrast generated PNG with one dominant silhouette,
separated shapes, strong negative space, no embedded text, and no detail that
must survive color. Runtime remains independent of the converter.

Forty compositions:

1. Part II title
2. Black Rider at the wayhouse threshold
3. Calenor's broken sword
4. Falling silver stair
5. Black Rider pursuit introduction
6. Severed seal-gate
7. Dead Road panorama
8. Companions descending
9. Hall of Eight Wardens
10. Erased eighth statue
11. Wall of Names awakening
12. First Warden testimony
13. Hidden Warden stair
14. Echo Bridge
15. Orc sapper introduction
16. Echo Bridge battle
17. Drowned Mile panorama
18. Drowned caravan
19. Mara's shackle forge
20. Prisoners in iron cages
21. Floodgate wheel
22. Chain Troll introduction
23. Chain Troll battle
24. Second Warden testimony
25. House Under Ash
26. Full burning-house memory
27. Teren's reveal
28. False Ranger duel
29. Calenor's prison
30. Calenor reunion
31. Third Warden testimony
32. Last Seal vault
33. Eight-spoked ritual floor
34. Black Rider final entrance
35. Final seal battle
36. Fornost map cliffhanger
37. Living Road ending
38. Last Warden ending
39. Road in Ruin ending
40. Shadow's Name ending

The Wall of Names awakening and Fornost map each use two restrained frames. The
forty public compositions therefore use forty-two source PNGs. All art has
screen-reader alternative text and retains ANSI color, `--no-color`, reduced
motion, centering, and narrow-terminal viewport behavior.

## Artwork Acceptance

- Forty-two source PNGs exist under `assets/ascii-sources/part-two/`.
- Each source is valid and non-empty.
- Every public Part II artwork value uses exact fixed-profile converter output,
  apart from outer blank-row and trailing-whitespace cleanup.
- Every body is portable ASCII, at most 72 columns and 20 rows.
- A manifest records source filename, output constant, polarity, and story beat.
- A Part II contact sheet and demo GIF show all forty compositions in story order.
- Visual inspection rejects conversions whose primary subject cannot be
  identified at normal Terminal size; failed references are regenerated rather
  than hand-traced.

## Test and Verification Contract

Test-driven slices must cover:

1. Continuation across all four Part I endings, including an older completed v2
   save missing new consequence flags.
2. Idempotent continuation with no duplicated items, quests, flags, or minutes.
3. Save round-trips for active Part II and completed Part II states.
4. Rejection of chapter/scene and scene/ending mismatches.
5. One full completionist Part II route with 110–130 estimated minutes, at least
   35 meaningful prompts, all required transcript beats, and the intended
   encounter count.
6. Focused routes for hidden knowledge, united companions, Mara distrust/Ned
   loss, and the Shadow foothold.
7. All four Part II endings without a Cartesian combination matrix.
8. Replay safety at a reward boundary, after the major boss, and at the finale.
9. One real-combat smoke route and focused enemy-factory tests.
10. Screen-reader descriptions for every displayed Part II scene.
11. Exact converter provenance, dimensions, ASCII portability, manifest
    coverage, animation frames, and marketing-asset coverage.
12. The entire existing Part I suite without weakened assertions.

Final verification includes the full unit suite, Python compilation,
`git diff --check`, an isolated-save launch, direct macOS Terminal playtesting,
and visual inspection of the Part II GIF and contact sheet.

## Deliberate Limits

- No canonical-character cameo in Part II.
- No commercial-license claim; this remains an unofficial fan project.
- No mid-combat saves.
- No new companion beyond Calenor and Teren's story roles.
- No voice acting, music system, procedural dungeon, or online feature.
- No claim that automated estimated minutes prove exact wall-clock duration.

These limits protect the two-hour episode's writing, consequence, combat, and
art quality from unrelated expansion.
