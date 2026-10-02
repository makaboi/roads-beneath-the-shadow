"""Immutable combat presentation data shared by graphical and terminal UIs.

The engine publishes these values without calling graphical APIs.  A frontend
can show targets, explain actions, and animate outcomes without interpreting
the wording or order of the terminal transcript.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CombatStatusView:
    id: str
    label: str
    remaining: int
    description: str


@dataclass(frozen=True)
class CombatPlayerView:
    name: str
    origin: str
    hp: int
    max_hp: int
    focus: int
    max_focus: int
    weapon_id: str | None
    weapon_name: str
    armor_id: str | None
    armor_name: str
    armor: int
    statuses: tuple[CombatStatusView, ...]


@dataclass(frozen=True)
class CombatEnemyView:
    id: str
    name: str
    archetype: str
    hp: int
    max_hp: int
    armor: int
    phase: int
    intent_id: str
    intent_label: str
    telegraph: str
    interruptible: bool
    damage_min: int
    damage_max: int
    threat: str
    statuses: tuple[CombatStatusView, ...]
    targeted: bool


@dataclass(frozen=True)
class CombatActionView:
    id: str
    label: str
    focus_cost: int
    enabled: bool
    disabled_reason: str
    description: str


@dataclass(frozen=True)
class CombatCompanionView:
    id: str
    name: str
    trust: int
    available: bool


@dataclass(frozen=True)
class CombatSnapshot:
    round_number: int
    phase: str
    difficulty: str
    player: CombatPlayerView
    enemies: tuple[CombatEnemyView, ...]
    target_id: str | None
    actions: tuple[CombatActionView, ...]
    companions: tuple[CombatCompanionView, ...]
    objective: str | None
    max_rounds: int | None
    defensive_objective: bool


@dataclass(frozen=True)
class CombatFeedback:
    kind: str
    actor_id: str
    target_id: str
    amount: int
    text: str


@dataclass(frozen=True)
class CombatCommand:
    """An optional graphical command that does not consume the player's turn."""

    kind: str
    target_id: str


STATUS_DESCRIPTIONS: dict[str, str] = {
    "bleeding": "Lose 1 Health each turn. A remedy stops Bleeding.",
    "exposed": "The next incoming hit deals extra damage.",
    "evade": "Evade the next incoming attack completely.",
    "ward": "Absorb damage from the next incoming hit.",
    "riposte": "Counter the next attacker from behind your guard.",
    "guarded": "+2 Armor until struck. Power Attack bypasses this guard.",
    "vulnerable": "The next weapon attack deals 2 extra damage.",
    "staggered": "Interrupt an interruptible intent; otherwise reduce the next hit by 2.",
    "aimed": "The next attack deals 2 extra damage.",
    "empowered": "The next attack deals 1 extra damage.",
    "weakened": "Reduce incoming attacks by 2 while this effect lasts.",
}


ACTION_DESCRIPTIONS: dict[str, str] = {
    "attack": "Strike your target with your equipped weapon. Costs no Focus.",
    "power": "Deal extra damage, bypass raised guards, and disrupt your target. Become Exposed.",
    "defend": "Halve every incoming attack this round and recover 1 Focus.",
    "item": "Use a healing item and stop Bleeding. Uses your turn.",
    "inspect": "Read your target's defenses and intent. Does not use your turn.",
    "target": "Select a different enemy. Does not use your turn.",
    "mara": "Mara damages and disrupts your target, causing Bleeding.",
    "tobin": "Tobin damages your target and weakens its next two attacks.",
    "mara_guard": "Halve every incoming attack this round. Mara absorbs 2 damage from the next hit.",
    "tobin_guard": "Halve every incoming attack this round and evade the next attack completely.",
    "flee": "Attempt an escape. A failed attempt uses your turn.",
}
