"""Immutable-by-copy player information for graphical panels.

The engine builds these dictionaries on its worker before waiting for input;
renderers never read or modify a live GameState.
"""

from __future__ import annotations

from typing import Any

from .content import ENDING_TEXT, ITEMS, ORIGINS
from .models import GameState
from .profile import ACHIEVEMENTS, PlayerProfile


LOCATIONS = {
    "chapter1_intro": "The Prancing Pony", "chapter1_decision": "The Prancing Pony",
    "branch_fight": "The Prancing Pony", "branch_hide": "The Prancing Pony",
    "branch_search": "The Prancing Pony", "branch_escape": "The Prancing Pony",
    "branch_question": "The Prancing Pony", "aftermath": "The Prancing Pony",
    "bree_exploration": "Bree", "north_gate": "Bree's North Gate",
    "road_from_bree": "The North Road", "midgewater_camp": "Midgewater Camp",
    "missing_watchman": "The Watchman's Trail", "marsh_ambush": "Midgewater Marsh",
    "wayhouse": "The Buried Wayhouse", "final_battle": "The Ruined Gateway",
    "cliffhanger": "The Dead Road", "part2_descent": "The Dead Road",
    "part2_pursuit": "The Dead Road", "part2_hall": "The Hall of Eight",
    "part2_hall_exploration": "The Hall of Eight", "part2_echo_bridge": "Echo Bridge",
    "part2_drowned_mile": "The Drowned Mile", "part2_prisoners": "The Iron Cages",
    "part2_chain_troll": "The Floodgate", "part2_house_under_ash": "The House Under Ash",
    "part2_burning_memory": "The Burning Memory", "part2_teren": "The Warden Refuge",
    "part2_calenor_prison": "Calenor's Prison", "part2_calenor_reunion": "The Warden Refuge",
    "part2_vigil": "The Last Lantern", "part2_last_seal": "The Last Seal",
    "part2_final_battle": "The Last Seal", "part2_seal_choice": "The Last Seal",
    "complete": "The Road Ahead",
}

EXPLORED_PLACES = {
    "messenger_room": "Edrin's Room",
    "stable_yard": "The Pony's Stable Yard",
    "pony_kitchen": "The Pony's Kitchen",
    "mara_fire": "Mara's Fireside",
    "wayhouse_entry": "Buried Wayhouse Entrance",
    "wayhouse_armory": "The Drowned Armory",
    "wayhouse_archive": "The Wayhouse Archive",
    "wayhouse_shrine": "The Star Chamber",
}


def route_snapshot(state: GameState) -> dict[str, Any]:
    """Remember explored places without revealing future stops or exits."""
    names = []
    for place in state.visited:
        name = EXPLORED_PLACES.get(place, LOCATIONS.get(place))
        if name is None:
            # Earlier saves sometimes stored display labels rather than IDs.
            name = place if "_" not in place else "A remembered stop"
        if name not in names:
            names.append(name)
    for flag, name in (
        ("part2_cipher_archive", "The Cipher Archive"),
        ("part2_erased_statue", "The Erased Statue"),
    ):
        if state.flags.get(flag) and name not in names:
            names.append(name)
    current = LOCATIONS.get(state.scene, "The road")
    route = [{"name": name, "visited": True, "current": name == current} for name in names]
    if current not in names:
        route.append({"name": current, "visited": False, "current": True})
    return {
        "chapter": state.chapter,
        "location": current,
        "route": route,
        "description": "Places you have explored and your present stop on the road.",
    }


def chronicle_snapshot(profile: PlayerProfile) -> dict[str, Any]:
    """Copy completion records into display cards without modifying the profile."""
    origin_names = {origin.origin_id: origin.name for origin in ORIGINS}
    achievements = []
    for identifier, description in ACHIEVEMENTS.items():
        name, _, details = description.partition(" — ")
        achievements.append({
            "id": identifier, "name": name, "description": details,
            "earned": identifier in profile.achievements,
        })
    return {
        "completed_runs": profile.completed_runs,
        "origins": [origin_names[origin] for origin in profile.origins_completed if origin in origin_names],
        "endings": [
            {"name": ENDING_TEXT[ending][0].title(), "count": count}
            for ending, count in sorted(profile.endings.items()) if ending in ENDING_TEXT and count > 0
        ],
        "achievements": achievements,
    }


def player_snapshot(state: GameState | None) -> dict[str, Any] | None:
    if state is None:
        return None
    c = state.character
    origin = next((o for o in ORIGINS if o.origin_id == c.origin), None)
    weapon = ITEMS.get(c.weapon or "")
    armor = ITEMS.get(c.armor or "")
    character = {
        "name": c.name, "origin": c.origin,
        "origin_label": origin.name if origin else c.origin.replace("_", " ").title(),
        "ability": origin.ability_name if origin else "",
        "ability_description": origin.ability_description if origin else "",
        "hp": c.hp, "max_hp": c.max_hp, "focus": c.focus, "max_focus": c.max_focus,
        "strength": c.strength, "cunning": c.cunning, "will": c.will,
        "hope": c.hope, "corruption": c.corruption,
        "weapon": weapon.name if weapon else "Unarmed",
        "armor": armor.name if armor else "None",
        "weapon_attack": weapon.attack if weapon else 0,
        "armor_defense": armor.defense if armor else 0,
        "mara_trust": c.mara_trust, "tobin_trust": c.tobin_trust,
    }
    items = []
    for item_id, count in c.inventory.items():
        item = ITEMS[item_id]
        items.append({
            "id": item_id, "name": item.name, "description": item.description,
            "kind": item.kind, "slot": item.slot,
            "attack": item.attack, "defense": item.defense, "healing": item.healing,
            "count": count, "equipped": item_id in {c.weapon, c.armor},
            "attack_delta": item.attack - (weapon.attack if weapon else 0) if item.slot == "weapon" else 0,
            "defense_delta": item.defense - (armor.defense if armor else 0) if item.slot == "armor" else 0,
        })
    if state.chapter == 2:
        mara = state.flags.get("part_two_mara_present", False)
        tobin = state.flags.get("part_two_tobin_present", False)
    else:
        opening = state.scene == "chapter1_intro"
        mara = not opening
        tobin = not opening and state.scene != "chapter1_decision" and not state.scene.startswith("branch_")
        if state.flags.get("tobin_returns_with_ned") or state.flags.get("tobin_stays_at_threshold"):
            tobin = False
    companions = [
        {"name": "Mara", "trust": c.mara_trust, "present": mara},
        {"name": "Tobin", "trust": c.tobin_trust, "present": tobin},
    ]
    # Flat HUD keys remain available to the small header renderer.
    return {
        **character, "character": character, "items": items, "companions": companions,
        "chapter": state.chapter, "scene": state.scene,
        "location": LOCATIONS.get(state.scene, state.scene.replace("_", " ").title()),
        "activequests": list(state.quests), "completedquests": list(state.completed_quests),
        "clues": list(state.journal), "visited": [entry["name"] for entry in route_snapshot(state)["route"] if entry["visited"]],
        "play_minutes": state.play_minutes, "ending": state.ending,
        "journey_id": state.journey_id,
    }
