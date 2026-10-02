"""Immutable-by-copy player information for graphical panels.

The engine builds these dictionaries on its worker before waiting for input;
renderers never read or modify a live GameState.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from .content import ENDING_TEXT, ITEMS, ORIGINS, PART_ONE_ENDINGS, QUEST_NAMES_LOST, QUEST_REACH_CALENOR
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
    "part2_cipher_archive": "The Cipher Archive",
    "part2_erased_statue": "The Erased Statue",
}


def background_snapshot() -> dict[str, Any]:
    """Describe the engine's backgrounds before a character is created."""
    return {
        "origins": [
            {
                "id": origin.origin_id, "name": origin.name,
                "description": origin.description, "max_hp": origin.max_hp,
                "strength": origin.strength, "cunning": origin.cunning, "will": origin.will,
                "ability_name": origin.ability_name, "ability_description": origin.ability_description,
                "ability_rules": "Costs 1 Focus. Use once per battle.",
                "weapon_name": ITEMS[origin.weapon].name,
                "armor_name": ITEMS[origin.armor].name if origin.armor else "Travel clothes",
                "starting_items": [
                    f"{ITEMS[item_id].name}{f' ×{count}' if count > 1 else ''}"
                    for item_id, count in Counter(origin.starting_items).items()
                ],
            }
            for origin in ORIGINS
        ]
    }


def _decision_snapshot(decision: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not decision:
        return None
    options = decision.get("options", ())
    if not isinstance(options, (list, tuple)):
        return None
    return {"heading": str(decision.get("heading", "")), "options": [str(option) for option in options]}


def route_snapshot(state: GameState, *, decision: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Remember explored places without revealing future stops or exits."""
    names = []
    completed_stop_recorded = False
    for place in state.visited:
        name = EXPLORED_PLACES.get(place, LOCATIONS.get(place))
        if name is None:
            # Earlier saves sometimes stored display labels rather than IDs.
            name = place if "_" not in place else "A remembered stop"
        if place == "complete" or name == LOCATIONS["complete"]:
            completed_stop_recorded = True
            continue
        if name not in names:
            names.append(name)
    hall_places = {"The Cipher Archive", "The Erased Statue"}
    hall_rooms = [name for name in names if name in hall_places]
    for flag, name in (
        ("part2_cipher_archive", "The Cipher Archive"),
        ("part2_erased_statue", "The Erased Statue"),
    ):
        if state.flags.get(flag) and name not in hall_rooms:
            hall_rooms.append(name)
    names = [name for name in names if name not in hall_places]
    hall_index = names.index("The Hall of Eight") + 1 if "The Hall of Eight" in names else len(names)
    names[hall_index:hall_index] = hall_rooms
    current = LOCATIONS.get(state.scene, "The road")
    route = [{"name": name, "visited": True, "current": name == current} for name in names]
    if current not in names:
        route.append({"name": current, "visited": completed_stop_recorded if state.scene == "complete" else False, "current": True})
    return {
        "chapter": state.chapter,
        "location": current,
        "route": route,
        "description": "Places you have explored and your present stop on the road.",
        "decision": _decision_snapshot(decision),
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
        "part_one_completions": sum(count for ending, count in profile.endings.items() if ending in PART_ONE_ENDINGS),
        "part_two_completions": sum(count for ending, count in profile.endings.items() if ending in ENDING_TEXT and ending not in PART_ONE_ENDINGS),
        "origins": [origin_names[origin] for origin in profile.origins_completed if origin in origin_names],
        "endings": [
            {"name": ENDING_TEXT[ending][0].title(), "count": count}
            for ending, count in sorted(profile.endings.items()) if ending in ENDING_TEXT and count > 0
        ],
        "achievements": achievements,
    }


def quest_details(state: GameState) -> list[dict[str, Any]]:
    """Restate recorded objectives and link evidence the traveler already has.

    These notes explain existing quest labels. They never predict a future
    stop, reveal an unearned route, or recommend a moral choice.
    """
    notes = {
        "Discover what happened to Calenor": ("Follow the accounts of people who knew Calenor, and keep his messages together.", ("calenor", "messenger", "letter")),
        "Keep the silver star from the servants of the Shadow": ("This promise continues throughout the journey. The clues below record what you know about the star.", ("star", "shadow", "pendant")),
        "Find Calenor's mark at Bree's north gate": ("Calenor's directions point to Bree's north gate. Examine the mark when you reach it.", ("gate", "stone", "token")),
        "Find Calenor's cache behind the north gate's third stone": ("The third stone at Bree's north gate is your lead. The cache still needs to be examined.", ("gate", "stone", "token", "letter")),
        "Find the Dead Road before Calenor is taken there": ("Keep the captain's account beside Calenor's messages; they are the leads you have so far.", ("captain", "dead road", "calenor")),
        "Find missing watchman Ned Barley in the Midgewater fringe": ("The search for Ned is still open. Watch for the signs you have recorded around Midgewater.", ("ned", "lantern", "midgewater", "tracks")),
        "Reach the forgotten North-kingdom wayhouse before Ghorak": ("Follow the wayhouse directions you have found. Your recorded clues preserve what led you there.", ("wayhouse", "map", "ghorak")),
        "Descend the Dead Road and reach Calenor": ("Continue the search along the Dead Road. Listen to the accounts you find there.", ("calenor", "dead road", "warden")),
        "Learn why the silver star is the last seal": ("Compare what you have learned about the star with the testimony recorded along the road.", ("star", "seal", "testimony")),
        QUEST_NAMES_LOST: ("Keep the testimonies you have recovered together. Only recovered accounts are recorded below.", ("testimony", "warden", "oath", "name")),
        "Prisoners of Ash: free the road-captives before the sluice opens": ("The sluice threatens the captives. A decision to help must come before it opens.", ("prisoner", "captive", "sluice", "chain")),
        "Keep the Eighth Name from the Black Rider": ("Keep what you have learned about the Name in mind as you face the Rider.", ("eighth", "rider", "name")),
        "Decide the fate of the Dead Road": ("The decision belongs to you. Your clues preserve the truths you have learned.", ("dead road", "seal", "calenor", "warden")),
    }
    details = []
    for title in state.quests:
        guidance, terms = notes.get(title, ("Keep this promise in mind as you weigh the choices on the road.", ()))
        related = [clue for clue in reversed(state.journal) if any(term in clue.casefold() for term in terms)][:3]
        entry = {"title": title, "guidance": guidance, "related_clues": related}
        if title == QUEST_NAMES_LOST:
            recovered = sum(bool(state.flags.get(f"part2_testimony_{number}")) for number in ("first", "second", "third"))
            entry["progress"] = f"{recovered} of 3 testimonies recovered"
        details.append(entry)
    return details


def _companion_snapshot(state: GameState) -> list[dict[str, Any]]:
    """Restate witnessed departures and fates without guessing missing facts."""
    flags = state.flags
    if state.chapter == 2:
        mara = bool(flags.get("part_two_mara_present", False))
        tobin = bool(flags.get("part_two_tobin_present", False))
    else:
        opening = state.scene == "chapter1_intro"
        mara = not opening
        tobin = not opening and state.scene != "chapter1_decision" and not state.scene.startswith("branch_")

    mara_status = "Traveling with you" if mara else "Not traveling with you"
    if flags.get("part2_mara_left"):
        mara = False
        mara_status = "Left at the burned refuge to seek the prisoners"

    if flags.get("tobin_returns_with_ned"):
        tobin = False
        tobin_status = "Remained above with Ned"
    elif flags.get("tobin_stays_at_threshold"):
        tobin = False
        tobin_status = "Remained at the threshold with Ned's lantern"
    elif not tobin and state.chapter == 2 and flags.get("part_two_ned_safe"):
        # Earlier saves may retain the hand-off facts without its choice flag.
        tobin_status = "Remained above with Ned"
    else:
        tobin_status = "Traveling with you" if tobin else "Not traveling with you"

    companions = [
        {"name": "Mara", "trust": state.character.mara_trust, "present": mara, "status": mara_status},
        {"name": "Tobin", "trust": state.character.tobin_trust, "present": tobin, "status": tobin_status},
    ]
    if state.chapter == 2 and QUEST_REACH_CALENOR in state.completed_quests:
        # Keep the same fate precedence as the episode's ending account.
        if flags.get("part2_calenor_collapsed_road"):
            present, status = False, "Stayed to collapse the road behind the company"
        elif flags.get("part2_calenor_rebound"):
            present, status = False, "Bound again at the Last Seal"
        elif flags.get("part2_calenor_remained"):
            present, status = False, "Remained within the renewed seal"
        elif flags.get("part2_calenor_escaped"):
            present, status = True, "Escaped the Last Seal with you"
        else:
            present, status = True, "Traveling with you"
        companions.append({"name": "Calenor", "present": present, "status": status})
    return companions


def player_snapshot(state: GameState | None, *, decision: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    if state is None:
        return None
    c = state.character
    origin = next((o for o in ORIGINS if o.origin_id == c.origin), None)
    weapon = ITEMS.get(c.weapon or "")
    armor = ITEMS.get(c.armor or "")
    character = {
        "name": c.name, "origin": c.origin,
        "origin_label": origin.name if origin else c.origin.replace("_", " ").title(),
        "origin_description": origin.description if origin else "",
        "ability": origin.ability_name if origin else "",
        "ability_description": origin.ability_description if origin else "",
        "ability_rules": "Costs 1 Focus. Use once per battle." if origin else "",
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
            "healing_effective": item.healing + (2 if item.healing > 0 and c.origin == "healers_apprentice" else 0),
            "attack_delta": item.attack - (weapon.attack if weapon else 0) if item.slot == "weapon" else 0,
            "defense_delta": item.defense - (armor.defense if armor else 0) if item.slot == "armor" else 0,
        })
    companions = _companion_snapshot(state)
    # Flat HUD keys remain available to the small header renderer.
    return {
        **character, "character": character, "items": items, "companions": companions,
        "chapter": state.chapter, "scene": state.scene,
        "location": LOCATIONS.get(state.scene, state.scene.replace("_", " ").title()),
        "activequests": list(state.quests), "completedquests": list(state.completed_quests),
        "clues": list(state.journal), "visited": [entry["name"] for entry in route_snapshot(state)["route"] if entry["visited"]],
        "quest_details": quest_details(state), "decision": _decision_snapshot(decision),
        "play_minutes": state.play_minutes, "ending": state.ending,
        "journey_id": state.journey_id,
    }
