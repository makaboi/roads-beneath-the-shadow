"""Serializable game-state models and inventory rules."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5


SAVE_VERSION = 2

VALID_SCENE_IDS = frozenset(
    {
        "chapter1_intro",
        "chapter1_decision",
        "branch_fight",
        "branch_hide",
        "branch_search",
        "branch_escape",
        "branch_question",
        "aftermath",
        "bree_exploration",
        "north_gate",
        "road_from_bree",
        "midgewater_camp",
        "missing_watchman",
        "marsh_ambush",
        "wayhouse",
        "final_battle",
        "cliffhanger",
        "complete",
        "part2_descent",
        "part2_pursuit",
        "part2_hall",
        "part2_hall_exploration",
        "part2_echo_bridge",
        "part2_drowned_mile",
        "part2_prisoners",
        "part2_chain_troll",
        "part2_house_under_ash",
        "part2_burning_memory",
        "part2_teren",
        "part2_calenor_prison",
        "part2_calenor_reunion",
        "part2_vigil",
        "part2_last_seal",
        "part2_final_battle",
        "part2_seal_choice",
    }
)


@dataclass(frozen=True)
class Item:
    item_id: str
    name: str
    description: str
    kind: str
    slot: str | None = None
    attack: int = 0
    defense: int = 0
    healing: int = 0


@dataclass(frozen=True)
class Origin:
    origin_id: str
    name: str
    description: str
    max_hp: int
    strength: int
    cunning: int
    will: int
    starting_items: tuple[str, ...]
    weapon: str
    armor: str | None = None
    ability_id: str = ""
    ability_name: str = ""
    ability_description: str = ""


@dataclass
class Character:
    name: str
    origin: str
    max_hp: int
    hp: int
    strength: int
    cunning: int
    will: int
    max_focus: int = 3
    focus: int = 3
    hope: int = 0
    corruption: int = 0
    mara_trust: int = 0
    tobin_trust: int = 0
    inventory: dict[str, int] = field(default_factory=dict)
    weapon: str | None = None
    armor: str | None = None

    @classmethod
    def from_origin(cls, name: str, origin: Origin) -> "Character":
        inventory: dict[str, int] = {}
        for item_id in origin.starting_items:
            inventory[item_id] = inventory.get(item_id, 0) + 1
        return cls(
            name=name,
            origin=origin.origin_id,
            max_hp=origin.max_hp,
            hp=origin.max_hp,
            strength=origin.strength,
            cunning=origin.cunning,
            will=origin.will,
            inventory=inventory,
            weapon=origin.weapon,
            armor=origin.armor,
        )

    def add_item(self, item_id: str, quantity: int = 1) -> None:
        if quantity < 1:
            raise ValueError("quantity must be positive")
        self.inventory[item_id] = self.inventory.get(item_id, 0) + quantity

    def remove_item(self, item_id: str, quantity: int = 1) -> bool:
        if quantity < 1:
            raise ValueError("quantity must be positive")
        current = self.inventory.get(item_id, 0)
        if current < quantity:
            return False
        remaining = current - quantity
        if remaining:
            self.inventory[item_id] = remaining
        else:
            self.inventory.pop(item_id, None)
        return True

    def equip(self, item: Item) -> None:
        if self.inventory.get(item.item_id, 0) < 1:
            raise ValueError(f"{item.name} is not in the inventory")
        if item.slot == "weapon":
            self.weapon = item.item_id
        elif item.slot == "armor":
            self.armor = item.item_id
        else:
            raise ValueError(f"{item.name} cannot be equipped")

    def heal(self, amount: int) -> int:
        before = self.hp
        self.hp = min(self.max_hp, self.hp + max(0, amount))
        return self.hp - before

    @property
    def alive(self) -> bool:
        return self.hp > 0


@dataclass
class GameState:
    character: Character
    journey_id: str = field(default_factory=lambda: uuid4().hex)
    scene: str = "chapter1_intro"
    chapter: int = 1
    flags: dict[str, bool] = field(default_factory=dict)
    quests: list[str] = field(default_factory=list)
    journal: list[str] = field(default_factory=list)
    visited: list[str] = field(default_factory=list)
    completed_quests: list[str] = field(default_factory=list)
    play_minutes: int = 0
    ending: str | None = None
    save_version: int = SAVE_VERSION

    def add_journal(self, entry: str) -> None:
        if entry not in self.journal:
            self.journal.append(entry)

    def add_quest(self, quest: str) -> None:
        if quest not in self.quests:
            self.quests.append(quest)

    def complete_quest(self, quest: str) -> None:
        if quest in self.quests:
            self.quests.remove(quest)
        if quest not in self.completed_quests:
            self.completed_quests.append(quest)

    def visit(self, location: str) -> None:
        if location not in self.visited:
            self.visited.append(location)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GameState":
        if not isinstance(payload, dict):
            raise ValueError("Save state must be an object")
        version = _required_int(payload.get("save_version", 0), "save_version")
        if version not in {1, SAVE_VERSION}:
            raise ValueError(f"Unsupported save version: {version}")
        if version == SAVE_VERSION:
            required_state_fields = {
                "character",
                "scene",
                "chapter",
                "flags",
                "quests",
                "journal",
                "visited",
                "completed_quests",
                "play_minutes",
                "ending",
            }
            missing_state = sorted(required_state_fields - payload.keys())
            if missing_state:
                raise ValueError(f"Save state is missing required field: {missing_state[0]}")

        character_payload = payload.get("character")
        if not isinstance(character_payload, dict):
            raise ValueError("character must be an object")
        character_data = dict(character_payload)
        if version == 1:
            character_data.setdefault("tobin_trust", 0)
        character = _character_from_dict(character_data)

        if "journey_id" not in payload:
            # v1 and earlier v2 saves predate stable journey identifiers.
            legacy_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            journey_id = uuid5(NAMESPACE_URL, f"roads-beneath-shadow:{legacy_payload}").hex
        else:
            journey_id = payload["journey_id"]
        _bounded_string(journey_id, "journey_id", minimum=1, maximum=128)

        return cls(
            character=character,
            journey_id=journey_id,
            scene=_bounded_string(payload.get("scene", "chapter1_intro"), "scene", minimum=1, maximum=128),
            chapter=_required_int(payload.get("chapter", 1), "chapter"),
            flags=_bool_dict(payload.get("flags", {}), "flags"),
            quests=_string_list(payload.get("quests", []), "quests"),
            journal=_string_list(payload.get("journal", []), "journal"),
            visited=_string_list(payload.get("visited", []), "visited"),
            completed_quests=_string_list(payload.get("completed_quests", []), "completed_quests"),
            play_minutes=_required_int(payload.get("play_minutes", 0), "play_minutes"),
            ending=_optional_bounded_string(payload.get("ending"), "ending", maximum=128),
            save_version=SAVE_VERSION,
        )


def _required_int(value: Any, field_name: str) -> int:
    """Accept JSON integers only; bool is deliberately not treated as an int."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _bounded_string(value: Any, field_name: str, *, minimum: int = 0, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if not minimum <= len(value) <= maximum:
        raise ValueError(f"{field_name} must contain between {minimum} and {maximum} characters")
    if any(not character.isprintable() for character in value):
        raise ValueError(f"{field_name} must not contain control or non-printing characters")
    return value


def _optional_bounded_string(value: Any, field_name: str, *, maximum: int) -> str | None:
    if value is None:
        return None
    return _bounded_string(value, field_name, minimum=1, maximum=maximum)


def _string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    result: list[str] = []
    for index, entry in enumerate(value):
        result.append(_bounded_string(entry, f"{field_name}[{index}]", maximum=2_000))
    return result


def _bool_dict(value: Any, field_name: str) -> dict[str, bool]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    result: dict[str, bool] = {}
    for key, entry in value.items():
        validated_key = _bounded_string(key, f"{field_name} key", minimum=1, maximum=128)
        if not isinstance(entry, bool):
            raise ValueError(f"{field_name}.{validated_key} must be true or false")
        result[validated_key] = entry
    return result


def _character_from_dict(payload: dict[str, Any]) -> Character:
    required = {
        "name",
        "origin",
        "max_hp",
        "hp",
        "strength",
        "cunning",
        "will",
        "max_focus",
        "focus",
        "hope",
        "corruption",
        "mara_trust",
        "tobin_trust",
        "inventory",
        "weapon",
        "armor",
    }
    optional: set[str] = set()
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError(f"character is missing required field: {missing[0]}")
    unknown = next((key for key in payload if key not in required and key not in optional), None)
    if unknown is not None:
        raise ValueError(f"character contains unknown field: {unknown!r}")

    inventory_payload = payload.get("inventory", {})
    if not isinstance(inventory_payload, dict):
        raise ValueError("character.inventory must be an object")
    inventory: dict[str, int] = {}
    for item_id, quantity in inventory_payload.items():
        validated_id = _bounded_string(item_id, "character.inventory item ID", minimum=1, maximum=128)
        validated_quantity = _required_int(quantity, f"character.inventory.{validated_id}")
        if validated_quantity < 1:
            raise ValueError(f"character.inventory.{validated_id} must be at least 1")
        inventory[validated_id] = validated_quantity

    return Character(
        name=_bounded_string(payload["name"], "character.name", minimum=1, maximum=24),
        origin=_bounded_string(payload["origin"], "character.origin", minimum=1, maximum=128),
        max_hp=_required_int(payload["max_hp"], "character.max_hp"),
        hp=_required_int(payload["hp"], "character.hp"),
        strength=_required_int(payload["strength"], "character.strength"),
        cunning=_required_int(payload["cunning"], "character.cunning"),
        will=_required_int(payload["will"], "character.will"),
        max_focus=_required_int(payload.get("max_focus", 3), "character.max_focus"),
        focus=_required_int(payload.get("focus", 3), "character.focus"),
        hope=_required_int(payload.get("hope", 0), "character.hope"),
        corruption=_required_int(payload.get("corruption", 0), "character.corruption"),
        mara_trust=_required_int(payload.get("mara_trust", 0), "character.mara_trust"),
        tobin_trust=_required_int(payload.get("tobin_trust", 0), "character.tobin_trust"),
        inventory=inventory,
        weapon=_optional_bounded_string(payload.get("weapon"), "character.weapon", maximum=128),
        armor=_optional_bounded_string(payload.get("armor"), "character.armor", maximum=128),
    )


@dataclass
class Enemy:
    name: str
    max_hp: int
    hp: int
    attack_min: int
    attack_max: int
    armor: int = 0
    description: str = ""
    archetype: str = "skirmisher"
    intent_pattern: tuple[str, ...] = ("strike",)
    phase_two_pattern: tuple[str, ...] = ()
    phase_threshold: float = 0.0
    statuses: dict[str, int] = field(default_factory=dict)
    current_intent: str = "strike"
    turn_count: int = 0
    phase: int = 1

    @property
    def alive(self) -> bool:
        return self.hp > 0
