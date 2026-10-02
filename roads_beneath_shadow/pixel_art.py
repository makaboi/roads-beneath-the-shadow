"""Resolve the story's terminal illustrations to packaged pixel-art scenes."""

from __future__ import annotations

from pathlib import Path
import re

from . import artwork, journey_artwork, part_two_artwork


ASSET_DIR = Path(__file__).resolve().parent / "pixel_assets"

# Keep the artwork constants as the story's public interface. Matching their
# text also handles copied strings, named sprites, and individual animation
# frames without depending on the identity of a particular string object.
_SCENE_GROUPS: dict[str, tuple[str, ...]] = {
    "title": (
        "TITLE_ART_EXPANDED", "PART_TWO_TITLE_ART",
    ),
    "tavern": (
        "PRANCING_PONY_EXTERIOR_STILL", "PRANCING_PONY_EXTERIOR_DIM_ART",
        "PRANCING_PONY_EXTERIOR_FRAMES", "PRANCING_PONY_EXTERIOR_ART",
        "BREE_STREETS_ART", "NORTH_GATE_ART", "BREE_WAYFARER_ORIGIN_ART",
    ),
    "tavern-interior": (
        "PRANCING_PONY_INTERIOR_ART", "KITCHEN_ESCAPE_ART",
        "TOBIN_REED_ARRIVES_ART", "EDRINS_ROOM_ART",
    ),
    "marsh": (
        "MIDGEWATER_RUINS_ART", "ROAD_FROM_BREE_ART",
        "DROWNED_WATCH_POST_ART", "NORTH_WAYHOUSE_ART",
        "GHORAK_PRISONER_TRAIL_ART",
        "LIVING_ROAD_ENDING_ART", "ROAD_IN_RUIN_ENDING_ART",
    ),
    "camp": (
        "HEALERS_APPRENTICE_ORIGIN_ART",
        "CALENOR_LAST_LESSON_ART", "MARA_FIRE_CONFESSION_ART",
    ),
    "rider": (
        "BLACK_RIDER_SPRITE", "BLACK_RIDER_DIM_SPRITE",
        "BLACK_RIDER_CLIFFHANGER_STILL", "BLACK_RIDER_STAR_DIM_ART",
        "BLACK_RIDER_CLIFFHANGER_FRAMES", "BLACK_RIDER_CLIFFHANGER_ART",
        "FLOODED_DITCH_RIDER_ART", "RIDER_WAYHOUSE_THRESHOLD_ART",
        "RIDER_PURSUIT_INTRO_SPRITE", "RIDER_PURSUIT_INTRO_ART",
        "RIDER_FINAL_ENTRANCE_SPRITE", "RIDER_FINAL_ENTRANCE_ART",
        "SHADOWS_NAME_ENDING_ART",
    ),
    "seal": (
        "THIRD_STONE_DISCOVERY_ART", "ANCIENT_ROAD_DISCOVERY_ART",
        "WAYHOUSE_SHRINE_ART", "FALLING_SILVER_STAIR_ART",
        "SEVERED_SEAL_GATE_ART", "DEAD_ROAD_PANORAMA_ART",
        "COMPANIONS_DESCENDING_ART", "WALL_NAMES_DIM_FRAME",
        "WALL_NAMES_LIT_FRAME", "WALL_NAMES_AWAKENING_ART",
        "HIDDEN_WARDEN_STAIR_ART",
        "SECOND_WARDEN_TESTIMONY_ART", "THIRD_WARDEN_TESTIMONY_ART",
        "LAST_SEAL_VAULT_ART", "EIGHT_SPOKED_RITUAL_ART",
        "FINAL_SEAL_BATTLE_SPRITE", "FINAL_SEAL_BATTLE_ART",
        "LAST_WARDEN_ENDING_ART",
    ),
    "orc": (
        "ORC_ATTACK_SPRITE", "ORC_ATTACK_ART", "ORC_TRACKER_SPRITE",
        "ORC_TRACKER_INTRO_ART", "FIGHT_BESIDE_MARA_ART",
        "ORC_CAPTAIN_PARLEY_ART", "ORC_SAPPER_INTRO_SPRITE",
        "ORC_SAPPER_INTRO_ART", "ECHO_BRIDGE_BATTLE_ART",
    ),
    "warg": (
        "MARSH_WARG_SPRITE", "MARSH_WARG_INTRO_ART",
    ),
    "ghorak": (
        "GHORAK_ASH_HAND_SPRITE", "GHORAK_ASH_HAND_INTRO_ART",
        "FINAL_RUINS_BATTLE_SPRITE", "FINAL_RUINS_BATTLE_ART",
    ),
    "troll": (
        "CHAIN_TROLL_INTRO_SPRITE", "CHAIN_TROLL_INTRO_ART",
        "CHAIN_TROLL_BATTLE_ART",
    ),
    "ranger": (
        "NORTH_ROAD_SCOUT_ORIGIN_ART",
        "CALENOR_REUNION_ART",
    ),
    "key": (
        "STAR_KEY_WHOLE_ART", "STAR_KEY_REFORGED_FRAMES",
        "STAR_KEY_REFORGED_ART", "NED_RETURNS_STAR_RAY_ART",
    ),
    "broken-key": (
        "STAR_KEY_BROKEN_ART", "EDRIN_DELIVERS_STAR_ART",
        "HIDDEN_HEARTH_STAR_ART",
    ),
    "sword": (
        "MARA_DRAWS_BLADES_ART", "PONY_PANTRY_CHOICE_ART",
        "DROWNED_ARMORY_ART", "CALENOR_BROKEN_SWORD_ART",
    ),
    "map": (
        "EDRIN_RANGER_CIPHER_ART", "CALENOR_LETTER_ART",
        "CALENOR_CACHE_CONTENTS_ART", "RANGER_TRAIL_MARKS_ART",
        "DEAD_ROAD_MOSAIC_ART", "FORNOST_MAP_DIM_FRAME",
        "FORNOST_MAP_LIT_FRAME", "FORNOST_MAP_CLIFFHANGER_ART",
    ),
    "lantern": (
        "BROKEN_LANTERN_ART",
    ),
    "cages": (
        "MARA_SHACKLE_FORGE_ART", "CALENOR_PRISON_ART",
    ),
    "midgewater-camp": ("MIDGEWATER_CAMP_ART",),
    "hall-of-eight": (
        "HALL_EIGHT_WARDENS_ART", "ERASED_EIGHTH_STATUE_ART", "FIRST_WARDEN_TESTIMONY_ART",
    ),
    "echo-bridge": ("ECHO_BRIDGE_ART",),
    "drowned-mile": ("DROWNED_MILE_ART", "DROWNED_CARAVAN_ART"),
    "sluice-prison": ("PRISONERS_IRON_CAGES_ART", "FLOODGATE_WHEEL_ART"),
    "house-under-ash": ("HOUSE_UNDER_ASH_ART",),
    "last-lantern-scene": ("LAST_LANTERN_ART",),
    "burning-house-memory": (
        "CALENOR_BURNING_HOUSE_MEMORY_ART", "BURNING_HOUSE_MEMORY_FULL_ART",
    ),
    "false-ranger-duel": (
        "TEREN_REVEAL_ART", "FALSE_RANGER_DUEL_SPRITE", "FALSE_RANGER_DUEL_ART",
    ),
}

_SCENE_BY_NAME = {
    name: scene for scene, names in _SCENE_GROUPS.items() for name in names
}

# These rules cover descriptions of new scenes and dynamically created
# nameplates. Character names take precedence over environmental words.
_DESCRIPTION_RULES = (
    (r"\bmidgewater camp\b|\bstanding stone\b.*\bember\b", "midgewater-camp"),
    (r"\bhall of eight\b|\beight stone seats\b|\berased stone plinth\b", "hall-of-eight"),
    (r"\becho bridge\b|\bbridge\b.*\b(bottomless gulf|three stone arches)\b", "echo-bridge"),
    (r"\bdrowned mile\b|\bhalf.submerged road\b|\bbroken prison cart\b", "drowned-mile"),
    (r"\b(two iron cages|floodgate wheel|sluice prison)\b", "sluice-prison"),
    (r"\bhouse under ash\b|\bhouse\b.*\b(enormous roots|underground refuge)\b", "house-under-ash"),
    (r"\b(sheltering arch|last lantern)\b|\bsingle lantern\b.*\blow stone arch\b", "last-lantern-scene"),
    (r"\bburning (house|memory)\b", "burning-house-memory"),
    (r"\bghorak\b", "ghorak"),
    (r"\b(warg|wolf|wolves)\b", "warg"),
    (r"\btroll\b", "troll"),
    (r"\b(rider|mounted shadow)\b", "rider"),
    (r"\b(orcs?|sapper)\b", "orc"),
    (r"\bfalse ranger\b|\bteren\b", "false-ranger-duel"),
    (r"\bbroken\b.*\b(star|key|pendant)\b", "broken-key"),
    (r"\b(key|pendant)\b|\bsilver (star|ray)\b", "key"),
    (r"\b(sword|blade|blades|armory)\b", "sword"),
    (r"\b(map|mosaic|cipher|letter|trail marks|cache)\b", "map"),
    (r"\b(cages?|prisoners?|prison|shackles?|chain)\b", "cages"),
    (r"\blantern\b", "lantern"),
    (r"\b(interior|pantry|kitchen|room|hearth|crowded inn)\b", "tavern-interior"),
    (r"\b(tavern|inn|pony|bree|roofs|gate|doorway)\b", "tavern"),
    (r"\b(camp|campfire|embers?|fire|burning|healer)\b", "camp"),
    (r"\b(ranger|scout|calenor)\b", "ranger"),
    (r"\b(seal|warden|vault|stair|bridge|arch|ritual|statue|cavern|names)\b", "seal"),
    (r"\b(title|mountains?|peaks)\b", "title"),
    (r"\b(marsh|water|reeds|road|ruins|watch)\b", "marsh"),
)


def _described_scene(description: str) -> str:
    description = description.casefold().replace("_", " ").replace("-", " ")
    for pattern, scene in _DESCRIPTION_RULES:
        if re.search(pattern, description):
            return scene
    return "marsh" if description.strip() else "title"


def _build_registry() -> dict[str, str]:
    registry: dict[str, str] = {}
    sequences: list[tuple[tuple[str, ...], str]] = []
    for module in (artwork, journey_artwork, part_two_artwork):
        for name, value in vars(module).items():
            if not name.isupper():
                continue
            scene = _SCENE_BY_NAME.get(name) or _described_scene(name)
            if isinstance(value, str):
                registry[str(value)] = scene
                if isinstance(value, artwork.AnimatedArtwork):
                    sequences.append((value.frames, scene))
            elif isinstance(value, tuple) and all(isinstance(frame, str) for frame in value):
                sequences.append((value, scene))

    # A named frame has a more specific scene than its enclosing animation:
    # reforging begins with the broken key and finishes with the whole key.
    for frames, scene in sequences:
        for frame in frames:
            registry.setdefault(str(frame), scene)
    return registry


_SCENE_BY_TEXT = _build_registry()


def scene_key(text: str, alt_text: str | None = None) -> str:
    """Return a stable scene name, preferring the story's exact artwork text."""

    exact_scene = _SCENE_BY_TEXT.get(str(text))
    if exact_scene is not None:
        return exact_scene
    return _described_scene(alt_text or str(text))


def resolve_scene(text: str, alt_text: str | None = None) -> Path:
    """Return the packaged PNG for a still, sprite, or animation frame."""

    return ASSET_DIR / f"{scene_key(text, alt_text)}.png"


def missing_assets() -> list[Path]:
    """Return missing scene PNGs so the graphical UI can report an incomplete install."""

    return [
        ASSET_DIR / f"{scene}.png"
        for scene in _SCENE_GROUPS
        if not (ASSET_DIR / f"{scene}.png").is_file()
    ]
