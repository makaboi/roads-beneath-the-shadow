"""Immutable combat presentation data shared by graphical and terminal UIs.

The engine publishes these values without calling graphical APIs.  A frontend
can show targets, explain actions, and animate outcomes without interpreting
the wording or order of the terminal transcript.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


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
    invulnerable: bool = False


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


@dataclass(frozen=True)
class CombatTurnSummary:
    """Two persistent result lines, independent of transcript wording.

    Frontends replace this value with ``begin_action`` when submitting a paid
    command and with ``append`` while draining feedback. A selected command
    becomes the displayed turn only after real feedback arrives, so a canceled
    item menu or free inspection preserves the preceding exchange.
    """

    action_id: str = ""
    action_label: str = ""
    feedback: tuple[CombatFeedback, ...] = ()
    pending_action: CombatActionView | None = None

    def begin_action(self, action: CombatActionView) -> CombatTurnSummary:
        if not action.enabled or action.id in {"inspect", "target"}:
            return self
        return replace(self, pending_action=action)

    def append(self, feedback: CombatFeedback) -> CombatTurnSummary:
        if feedback.kind in {"inspect", "notice"}:
            return self
        if self.pending_action is not None:
            action = self.pending_action
            return CombatTurnSummary(action.id, action.label.split(" (", 1)[0], (feedback,))
        return replace(self, feedback=(*self.feedback, feedback)[-24:])

    def lines(self, snapshot: CombatSnapshot | None = None, *, max_columns: int = 46) -> tuple[str, str]:
        """Summarize party impact and incoming damage in two measured rows.

        Damage to the player from another actor and self-inflicted Bleeding
        are counted separately. Enemy Bleeding ticks cannot inflate a party
        strike or the player's loss. ``max_columns`` suits a monospace font;
        the frontend can supply its measured width in characters.
        """
        limit = max(8, int(max_columns))

        def fitted(parts: list[str]) -> str:
            text = " · ".join(part for part in parts if part)
            return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"

        events = self.feedback
        if not events:
            return fitted(["Your turn. Choose your move."]), fitted(["Inspect and change targets freely."])
        party = {"player", "mara", "tobin"}
        outgoing = [event for event in events if event.kind == "damage" and event.actor_id in party and event.target_id not in party]
        healed = [event for event in events if event.kind == "heal" and event.target_id == "player"]
        guarded = [event for event in events if event.kind == "defend" and event.target_id == "player"]
        escaped = any(event.kind == "escape" for event in events)
        interrupted = any(event.kind == "interrupt" and event.target_id not in party for event in events)
        fallen = any(event.kind == "fallen" and event.target_id not in party for event in events)
        label = {"attack": "Attack", "power": "Power Attack", "defend": "Defend", "item": "Remedy",
                 "mara": "Mara", "tobin": "Tobin", "mara_guard": "Mara guard", "tobin_guard": "Tobin guard", "flee": "Escape"}.get(self.action_id, self.action_label)
        if not label:
            actor = outgoing[0].actor_id if outgoing else events[0].actor_id
            label = {"player": "Opening strike", "mara": "Mara", "tobin": "Tobin"}.get(actor, "Enemy exchange")
        impact = [label]
        if escaped:
            impact.append("escaped")
        elif self.action_id == "flee":
            impact.append("escape blocked")
        if healed:
            healing = sum(max(0, event.amount) for event in healed)
            impact.append(f"+{healing} Health" if healing else "remedy applied")
        if guarded:
            impact.append("guarded")
            restored = sum(max(0, event.amount) for event in guarded if event.actor_id == "player")
            if restored:
                impact.append(f"+{restored} Focus")
        if outgoing:
            damage = sum(max(0, event.amount) for event in outgoing)
            impact.append(f"−{damage} damage" if damage else "blocked")
        if interrupted:
            impact.append("interrupted")
        if fallen:
            impact.append("foe fallen")
        phases = sorted({event.amount for event in events if event.kind == "phase" and event.amount > 1})
        for phase in phases:
            impact.append("Phase " + {2: "II", 3: "III"}.get(phase, str(phase)))
        targets = {event.target_id for event in outgoing}
        if len(targets) == 1 and snapshot is not None:
            target = next(iter(targets))
            enemy = next((enemy for enemy in snapshot.enemies if enemy.id == target), None)
            if enemy is not None:
                impact.append(enemy.name)
        elif len(targets) > 1:
            impact.append(f"{len(targets)} foes")

        incoming = [event for event in events if event.kind == "damage" and event.target_id == "player" and event.actor_id != "player"]
        bleeding = sum(max(0, event.amount) for event in events if event.kind == "damage" and event.actor_id == event.target_id == "player")
        damage = sum(max(0, event.amount) for event in incoming)
        shadow_events = [event for event in events if event.kind == "info" and event.target_id == "player" and event.actor_id not in party]
        focus_lost = sum(max(0, event.amount) for event in shadow_events)
        evaded = sum(event.kind == "evade" and event.target_id == "player" for event in events)
        blocked = sum(event.amount == 0 for event in incoming)
        reply: list[str] = []
        if escaped:
            reply.append("No enemy retaliation")
        elif incoming:
            reply.append(f"Incoming −{damage} Health" if damage else "Incoming blocked")
        elif evaded:
            reply.append("Incoming evaded")
        if bleeding:
            reply.append(f"Bleeding −{bleeding}" if reply else f"Bleeding −{bleeding} Health")
        if focus_lost:
            reply.append(f"−{focus_lost} Focus" if reply else f"Incoming −{focus_lost} Focus")
        if evaded and incoming:
            reply.append(f"{evaded} evaded")
        if blocked and damage:
            reply.append(f"{blocked} blocked")
        if any(event.kind == "fallen" and event.target_id == "player" for event in events):
            reply.append("fallen")
        if not reply:
            prepared = any(event.kind == "info" and event.actor_id not in party for event in events)
            reply.append("No incoming Health damage")
            if shadow_events:
                reply.append("shadow mark")
            elif prepared:
                reply.append("enemies prepared")
        return fitted(impact), fitted(reply)


STATUS_DESCRIPTIONS: dict[str, str] = {
    "bleeding": "Lose 1 Health each committed turn. Inspecting and changing targets spend no turn. A remedy stops Bleeding.",
    "exposed": "The next physical hit deals extra damage. Guarding reduces that hit.",
    "evade": "Avoid the next physical attack completely. Setup actions do not consume Evasion.",
    "ward": "Absorb the shown amount of damage from the next physical hit, after guarding.",
    "riposte": "Counter the next physical hit if you survive it. Evasion preserves the counter.",
    "guarded": "+2 Armor. Attack removes it; Power Attack and Flanking Strike bypass and remove it. Companions and counters leave it intact.",
    "vulnerable": "The next weapon attack deals 2 extra damage.",
    "staggered": "Interrupt an interruptible intent; otherwise reduce the next hit by 2.",
    "aimed": "The next landed physical hit gains 2 attack strength. Evasion preserves this effect.",
    "empowered": "The next landed physical hit gains 1 attack strength. Evasion preserves this effect.",
    "weakened": "Reduce this enemy's attack strength by 2 while this effect lasts. Evaded attacks do not use it up.",
}


ACTION_DESCRIPTIONS: dict[str, str] = {
    "attack": "Strike your target with your equipped weapon. Costs no Focus.",
    "power": "Deal extra damage, bypass a raised guard, and disrupt your target. Become Exposed: the next physical hit deals extra damage.",
    "defend": "Halve incoming physical hits (minimum 1 before wards) and restore up to 1 Focus. Bleeding and setup effects still resolve.",
    "item": "Use a healing item and stop Bleeding. Uses your turn.",
    "inspect": "Read your target's defenses and intent. Does not use your turn.",
    "target": "Select a different enemy. Does not use your turn.",
    "mara": "Damage through Armor, disrupt your target's intent, and cause Bleeding.",
    "tobin": "Damage through Armor and weaken your target's next two landed attacks.",
    "mara_guard": "Halve incoming physical hits (minimum 1 before wards). Mara absorbs 2 damage from the next hit. Bleeding and setup effects still resolve.",
    "tobin_guard": "Halve incoming physical hits and evade the next attack completely. Bleeding and setup effects still resolve.",
    "flee": "Attempt an escape. A failed attempt uses your turn.",
}
