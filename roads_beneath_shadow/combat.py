"""Telegraphed, tactical turn-based combat for terminal encounters."""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

from .content import ITEMS, ORIGINS
from .combat_view import (
    ACTION_DESCRIPTIONS,
    STATUS_DESCRIPTIONS,
    CombatActionView,
    CombatCompanionView,
    CombatCommand,
    CombatEnemyView,
    CombatFeedback,
    CombatPlayerView,
    CombatSnapshot,
    CombatStatusView,
)
from .models import Enemy, GameState, Origin
from .ui import Color, TerminalUI


class CombatResult(str, Enum):
    VICTORY = "victory"
    DEFEAT = "defeat"
    ESCAPED = "escaped"


class CombatDifficulty(str, Enum):
    STORY = "story"
    NORMAL = "normal"
    HARD = "hard"


@dataclass(frozen=True)
class DifficultyProfile:
    incoming_multiplier: float
    outgoing_bonus: int
    flee_bonus: int
    power_bonus: int
    power_focus_cost: int
    exposure_penalty: int
    regular_resistance: int
    boss_resistance: int
    aggressive_opening: bool


DIFFICULTY_PROFILES: dict[CombatDifficulty, DifficultyProfile] = {
    # Story keeps the full tactical rules, but makes recovery from a mistake
    # generous.  Ranger deliberately preserves the original v0.2 numbers.
    CombatDifficulty.STORY: DifficultyProfile(0.70, 1, 1, 5, 1, 1, 0, 0, False),
    CombatDifficulty.NORMAL: DifficultyProfile(1.00, 0, 0, 5, 1, 2, 0, 0, False),
    # Shadow changes tempo instead of merely inflating every health bar.  Enemy
    # formations open with a telegraphed attack, armor matters more, and a Power
    # Attack is a deliberate two-Focus commitment.  Companion commands and
    # origin abilities bypass this resistance, rewarding tactical play.
    CombatDifficulty.HARD: DifficultyProfile(1.25, 0, -1, 4, 2, 3, 1, 2, True),
}


@dataclass
class CombatConfig:
    allow_flee: bool = False
    surprise_round: bool = False
    mara_aid: bool = False
    tobin_aid: bool = False
    location_text: str = "Steel clears leather. Rain hisses through the broken window."
    objective: str | None = None
    max_rounds: int | None = None
    objective_enemy_invulnerable: bool = False
    difficulty: CombatDifficulty | str | None = None


@dataclass(frozen=True)
class IntentSpec:
    label: str
    telegraph: str
    kind: str
    damage_bonus: int = 0
    interruptible: bool = False
    inflicts_bleeding: bool = False


INTENTS: dict[str, IntentSpec] = {
    "strike": IntentSpec("Strike", "a direct weapon attack", "damage"),
    "quick": IntentSpec("Quick Cut", "a fast but lighter attack", "damage", damage_bonus=-1),
    "aim": IntentSpec("Take Aim", "prepares a stronger next attack", "aim", interruptible=True),
    "guard": IntentSpec("Iron Guard", "raises Armor until your next weapon hit", "guard", interruptible=True),
    "command": IntentSpec("War Cry", "empowers the other enemies", "command", interruptible=True),
    "heavy": IntentSpec("Heavy Blow", "a crushing attack; Defend or interrupt it", "damage", 2, True),
    "prowl": IntentSpec("Prowl", "lines up a vicious pounce", "aim", interruptible=True),
    "pounce": IntentSpec("Pounce", "a heavy leap that causes Bleeding", "damage", 2, True, True),
    "maul": IntentSpec("Maul", "teeth and claws that cause Bleeding", "damage", 0, False, True),
    "cleave": IntentSpec("Ash Cleave", "a broad, punishing sweep", "damage", 1),
    "brace": IntentSpec("Ashen Brace", "fortifies Armor until your next weapon hit", "guard", interruptible=True),
    "menace": IntentSpec("Shadow Mark", "drains Focus and leaves you Exposed", "menace", interruptible=True),
    "execution": IntentSpec("Ash-Hand Execution", "a devastating blow; interrupt it now", "damage", 4, True),
}


class CombatEngine:
    """Runs one encounter.

    Every enemy announces an intent before the player commits to an action.  The
    engine accepts an injected ``random.Random`` instance, so damage, evasion,
    and companion reactions remain completely deterministic in tests.
    """

    def __init__(
        self,
        ui: TerminalUI,
        rng: random.Random | None = None,
        difficulty: CombatDifficulty | str = CombatDifficulty.NORMAL,
    ) -> None:
        self.ui = ui
        self.rng = rng or random.Random()
        self.default_difficulty = self._coerce_difficulty(difficulty)
        self._profile = DIFFICULTY_PROFILES[self.default_difficulty]
        self._player_statuses: dict[str, int] = {}
        self._ability_used = False
        self._origin: Origin | None = None
        self._enemy_ids: dict[int, str] = {}
        self._difficulty = self.default_difficulty

    def set_difficulty(self, difficulty: CombatDifficulty | str) -> None:
        """Change the default profile used by future encounters."""

        self.default_difficulty = self._coerce_difficulty(difficulty)
        self._profile = DIFFICULTY_PROFILES[self.default_difficulty]

    def run(self, state: GameState, enemies: list[Enemy], config: CombatConfig | None = None) -> CombatResult:
        config = config or CombatConfig()
        if not enemies:
            return CombatResult.VICTORY

        difficulty = self._coerce_difficulty(config.difficulty or self.default_difficulty)
        self._difficulty = difficulty
        self._profile = DIFFICULTY_PROFILES[difficulty]
        character = state.character
        character.focus = character.max_focus
        self._player_statuses = {}
        self._ability_used = False
        self._origin = next((origin for origin in ORIGINS if origin.origin_id == character.origin), None)
        self._enemy_ids = {id(enemy): f"enemy_{index}" for index, enemy in enumerate(enemies)}
        for enemy in enemies:
            enemy.statuses.clear()
            enemy.phase = 1
            enemy.current_intent = "strike"
            enemy.turn_count = self._opening_turn_index(enemy)

        begin = getattr(self.ui, "combat_begin", None)
        if callable(begin):
            begin()
        self.ui.sound("danger")
        self.ui.title("COMBAT")
        self.ui.narrate(config.location_text, color=Color.RED)
        if config.objective:
            self.ui.write(f"Objective: {config.objective}", color=Color.YELLOW, bold=True)
        difficulty_label = {
            CombatDifficulty.STORY: "Story",
            CombatDifficulty.NORMAL: "Ranger",
            CombatDifficulty.HARD: "Shadow",
        }[difficulty]
        self.ui.write(f"Difficulty: {difficulty_label}", color=Color.DIM)
        if difficulty is CombatDifficulty.HARD:
            self.ui.write(
                "Shadow rules: enemies open aggressively; Power Attack costs 2 Focus.",
                color=Color.DIM,
            )

        if config.surprise_round and enemies and not config.objective_enemy_invulnerable:
            first = next((enemy for enemy in enemies if enemy.alive), None)
            if first:
                damage = self._player_damage(state, first, power=False)
                first.hp = max(0, first.hp - damage)
                self.ui.write(
                    f"You seize the opening and strike {first.name} for {damage} damage!",
                    color=Color.GREEN,
                )
                self._damage_feedback(first, damage, "player", "You seize the opening.")

        round_number = 1
        active = next((enemy for enemy in enemies if enemy.alive), enemies[0])
        defensive_objective = config.objective_enemy_invulnerable
        prepare_round = True
        while character.alive and any(enemy.alive for enemy in enemies):
            if prepare_round:
                self._prepare_round(enemies)
                if not any(enemy.alive for enemy in enemies):
                    break
                self._plan_intents(enemies)
                prepare_round = False
            if not active.alive:
                active = next(enemy for enemy in enemies if enemy.alive)
            self._show_status(state, enemies, round_number, active, defensive_objective=defensive_objective)

            if defensive_objective:
                actions = ["defend", "item", "inspect"]
                options = [
                    "Defend (halve physical hits, recover 1 Focus)",
                    "Use an item",
                    "Inspect enemy",
                ]
            else:
                actions = ["attack", "power", "defend", "item", "inspect"]
                options = [
                    "Attack",
                    f"Power attack (-{self._profile.power_focus_cost} Focus, become Exposed)",
                    "Defend (halve physical hits, recover 1 Focus)",
                    "Use an item",
                    "Inspect enemy",
                ]
            if not defensive_objective and sum(enemy.alive for enemy in enemies) > 1:
                actions.append("target")
                options.append(f"Change target (current: {active.name})")
            if (
                self._origin
                and self._origin.ability_name
                and (
                    not defensive_objective or self._origin.ability_id in {"field_remedy", "stand_fast"}
                )
            ):
                actions.append("origin")
                availability = "spent" if self._ability_used else "-1 Focus"
                if defensive_objective and self._origin.ability_id == "stand_fast":
                    availability += ", guard and cleanse"
                options.append(f"{self._origin.ability_name} ({availability})")
            if config.mara_aid:
                actions.append("mara_guard" if defensive_objective else "mara")
                options.append(
                    "Mara: Crossing Guard (-1 Focus, defend)"
                    if defensive_objective
                    else "Mara: Crossing Blades (-1 Focus, disrupt)"
                )
            if config.tobin_aid:
                actions.append("tobin_guard" if defensive_objective else "tobin")
                options.append(
                    "Tobin: Deflecting Shot (-1 Focus, defend)"
                    if defensive_objective
                    else "Tobin: Pinning Shot (-1 Focus, weaken)"
                )
            if config.allow_flee and not defensive_objective:
                actions.append("flee")
                options.append("Attempt to flee")

            self._publish_snapshot(state, enemies, round_number, active, config, actions, options)
            combat_choice = getattr(self.ui, "choose_combat", None)
            selected = combat_choice(options) if callable(combat_choice) else self.ui.choose("Choose your action", options)
            if isinstance(selected, CombatCommand):
                if selected.kind == "target" and not defensive_objective:
                    clicked_target = next((
                        enemy for enemy in enemies
                        if enemy.alive and self._enemy_id(enemy) == selected.target_id
                    ), None)
                    if clicked_target is not None:
                        active = clicked_target
                        self.ui.write(f"You turn your attention to {active.name}.", color=Color.CYAN)
                continue
            if selected is None:
                continue
            if isinstance(selected, bool) or not isinstance(selected, int) or not 1 <= selected <= len(actions):
                continue
            action = actions[selected - 1]

            defended = False
            consumes_turn = True
            if action == "attack":
                damage = self._player_damage(state, active, power=False)
                active.hp = max(0, active.hp - damage)
                self._consume_hit_statuses(active)
                self.ui.write(f"You strike {active.name} for {damage} damage.", color=Color.GREEN)
                self._damage_feedback(active, damage, "player", f"You strike {active.name}.")
            elif action == "power":
                if character.focus < self._profile.power_focus_cost:
                    needed = self._profile.power_focus_cost
                    self._notice(f"Power Attack requires {needed} Focus. Choose another action.")
                    continue
                character.focus -= self._profile.power_focus_cost
                self._player_statuses["exposed"] = 1
                damage = self._player_damage(state, active, power=True)
                active.hp = max(0, active.hp - damage)
                interrupted = (
                    active.current_intent in INTENTS
                    and INTENTS[active.current_intent].interruptible
                )
                active.statuses["staggered"] = 1
                active.statuses.pop("guarded", None)
                active.statuses.pop("vulnerable", None)
                text = f"Your committed blow deals {damage} damage to {active.name}"
                text += " and interrupts its intent" if interrupted else ""
                text += ", but leaves you Exposed!"
                self.ui.write(text, color=Color.GREEN, bold=True)
                self._damage_feedback(active, damage, "player", text)
            elif action == "defend":
                defended = True
                restored = 1 if character.focus < character.max_focus else 0
                character.focus = min(character.max_focus, character.focus + restored)
                message = "You set your feet. Every incoming physical hit will be halved."
                if restored:
                    message += " You recover 1 Focus."
                self.ui.write(message, color=Color.CYAN)
                self._feedback("defend", "player", "player", restored, message)
            elif action == "item":
                consumes_turn = self.use_item(state)
                if not consumes_turn:
                    continue
            elif action == "inspect":
                self._inspect(active, defensive_objective=defensive_objective)
                consumes_turn = False
            elif action == "target":
                living = [enemy for enemy in enemies if enemy.alive]
                target = self.ui.choose(
                    "Choose a target",
                    [f"{enemy.name} ({enemy.hp}/{enemy.max_hp} Health)" for enemy in living],
                    allow_back=True,
                )
                if isinstance(target, int) and not isinstance(target, bool) and 1 <= target <= len(living):
                    active = living[target - 1]
                    self.ui.write(f"You turn your attention to {active.name}.", color=Color.CYAN)
                consumes_turn = False
            elif action == "origin":
                consumes_turn, defended = self._use_origin_ability(state, active, defensive_objective=defensive_objective)
                if not consumes_turn:
                    continue
            elif action in {"mara_guard", "tobin_guard"}:
                if character.focus <= 0:
                    self._notice("You have no Focus left. Choose another action.")
                    continue
                character.focus -= 1
                defended = True
                if action == "mara_guard":
                    self._player_statuses["ward"] = max(2, self._player_statuses.get("ward", 0))
                    companion = "Mara crosses your guard: halve every attack and absorb 2 damage from the next hit."
                else:
                    self._player_statuses["evade"] = max(1, self._player_statuses.get("evade", 0))
                    companion = "Tobin's covering shot lets you evade the next attack and halve the others."
                self.ui.write(companion, color=Color.CYAN)
                self._feedback("defend", "mara" if action == "mara_guard" else "tobin", "player", 0, companion)
            elif action == "mara":
                if character.focus <= 0:
                    self._notice("You have no Focus left. Choose another action.")
                    continue
                character.focus -= 1
                damage = self.rng.randint(3, 5) + max(0, character.mara_trust)
                active.hp = max(0, active.hp - damage)
                active.statuses["staggered"] = 1
                active.statuses["bleeding"] = max(2, active.statuses.get("bleeding", 0))
                self.ui.write(
                    f"Mara crosses your attack for {damage} damage, leaving {active.name} Bleeding and disrupted.",
                    color=Color.MAGENTA,
                )
                self._damage_feedback(active, damage, "mara", f"Mara crosses your attack on {active.name}.")
            elif action == "tobin":
                if character.focus <= 0:
                    self._notice("You have no Focus left. Choose another action.")
                    continue
                character.focus -= 1
                damage = self.rng.randint(2, 4) + max(0, character.tobin_trust)
                active.hp = max(0, active.hp - damage)
                active.statuses["weakened"] = max(2, active.statuses.get("weakened", 0))
                self.ui.write(
                    f"Tobin's pinning arrow deals {damage} damage; {active.name}'s next attacks are Weakened.",
                    color=Color.CYAN,
                )
                self._damage_feedback(active, damage, "tobin", f"Tobin pins {active.name}.")
            elif action == "flee":
                if self.rng.randint(1, 6) + character.cunning + self._profile.flee_bonus >= 6:
                    self.ui.write("You overturn a table and vanish through the smoke.", color=Color.CYAN)
                    self._feedback("escape", "player", "player", 0, "You find an opening and escape.")
                    self._publish_snapshot(state, enemies, round_number, active, config, phase="escaped")
                    self._player_statuses.clear()
                    return CombatResult.ESCAPED
                self.ui.write("The enemy cuts off your escape.", color=Color.RED)
                self._feedback("notice", "player", "player", 0, "The enemy cuts off your escape.")

            if not consumes_turn:
                continue
            if not active.alive:
                self.ui.write(f"{active.name} falls.", color=Color.YELLOW, bold=True)
                if not any(enemy.alive for enemy in enemies):
                    break
                active = next(enemy for enemy in enemies if enemy.alive)

            self._tick_player_bleeding(character)
            if not character.alive:
                break
            self._enemy_phase(state, enemies, defended=defended, config=config)
            if not character.alive or not any(enemy.alive for enemy in enemies):
                break
            round_number += 1
            prepare_round = True
            if config.max_rounds and round_number > config.max_rounds and character.alive:
                self.ui.write(
                    "Your objective is complete—the surviving enemies lose their chance to stop you.",
                    color=Color.GREEN,
                )
                self._publish_snapshot(state, enemies, round_number - 1, active, config, phase="victory")
                self._player_statuses.clear()
                return CombatResult.VICTORY

        if character.alive:
            self.ui.sound("victory")
            self.ui.write("The last enemy crashes to the floor.", color=Color.GREEN, bold=True)
            self._publish_snapshot(state, enemies, round_number, active, config, phase="victory")
            self._player_statuses.clear()
            return CombatResult.VICTORY
        self.ui.write("Your strength fails. Black shapes close around you.", color=Color.RED, bold=True)
        self._publish_snapshot(state, enemies, round_number, active, config, phase="defeat")
        self._player_statuses.clear()
        return CombatResult.DEFEAT

    def _enemy_id(self, enemy: Enemy) -> str:
        return self._enemy_ids.get(id(enemy), "enemy_0")

    def _feedback(self, kind: str, actor_id: str, target_id: str, amount: int, text: str) -> None:
        hook = getattr(self.ui, "combat_feedback", None)
        if callable(hook):
            hook(CombatFeedback(kind, actor_id, target_id, amount, text))

    def _damage_feedback(self, enemy: Enemy, amount: int, actor_id: str, text: str) -> None:
        enemy_id = self._enemy_id(enemy)
        self._feedback("damage", actor_id, enemy_id, amount, text)
        if not enemy.alive:
            self._feedback("fallen", actor_id, enemy_id, 0, f"{enemy.name} falls.")

    def _notice(self, message: str) -> None:
        self.ui.write(message, color=Color.YELLOW)
        self._feedback("notice", "player", "player", 0, message)

    @staticmethod
    def _status_views(statuses: dict[str, int]) -> tuple[CombatStatusView, ...]:
        return tuple(
            CombatStatusView(name, name.replace("_", " ").title(), remaining, STATUS_DESCRIPTIONS.get(name, ""))
            for name, remaining in statuses.items()
            if remaining > 0
        )

    @staticmethod
    def _intent_presentation(enemy: Enemy, *, defensive_objective: bool = False) -> tuple[IntentSpec, str, bool]:
        """Describe the current tools without changing the enemy's intent.

        The Rider survival encounters prohibit offensive actions, so their
        ordinary interrupt advice would offer the player an impossible move.
        Resolution still uses the original intent specification.
        """

        spec = INTENTS.get(enemy.current_intent, INTENTS["strike"])
        telegraph = spec.telegraph
        if defensive_objective:
            telegraph = {
                "heavy": "a crushing attack; guard the blow",
                "execution": "a devastating blow; guard the blow",
            }.get(enemy.current_intent, telegraph)
        return spec, telegraph, spec.interruptible and not defensive_objective

    def _publish_snapshot(
        self,
        state: GameState,
        enemies: list[Enemy],
        round_number: int,
        target: Enemy,
        config: CombatConfig,
        actions: list[str] | None = None,
        options: list[str] | None = None,
        *,
        phase: str = "active",
    ) -> None:
        hook = getattr(self.ui, "combat_snapshot", None)
        if not callable(hook):
            return
        character = state.character
        weapon = ITEMS.get(character.weapon) if character.weapon else None
        armor = ITEMS.get(character.armor) if character.armor else None
        player = CombatPlayerView(
            name=character.name,
            origin=character.origin,
            hp=character.hp,
            max_hp=character.max_hp,
            focus=character.focus,
            max_focus=character.max_focus,
            weapon_id=character.weapon,
            weapon_name=weapon.name if weapon else "Unarmed",
            armor_id=character.armor,
            armor_name=armor.name if armor else "No armor",
            armor=armor.defense if armor else 0,
            statuses=self._status_views(self._player_statuses),
        )
        enemy_views: list[CombatEnemyView] = []
        # Forecast the existing formation's announced attacks without drawing
        # random numbers or consuming live statuses.  Guarding or interrupting
        # changes this forecast when the player commits their action.
        forecast_player = dict(self._player_statuses)
        forecast_empowered = {id(enemy): bool(enemy.statuses.get("empowered")) for enemy in enemies}
        for enemy in enemies:
            spec, telegraph, interruptible = self._intent_presentation(
                enemy, defensive_objective=config.objective_enemy_invulnerable,
            )
            minimum = maximum = 0
            interrupted = enemy.statuses.get("staggered") and spec.interruptible
            if enemy.alive and not interrupted:
                if spec.kind == "command":
                    for ally in enemies:
                        if ally is not enemy and ally.alive:
                            forecast_empowered[id(ally)] = True
                elif spec.kind == "menace":
                    forecast_player["exposed"] = 1
                elif spec.kind == "damage":
                    evade = forecast_player.get("evade", 0)
                    if evade:
                        self._decrement_status(forecast_player, "evade")
                    else:
                        bonus = spec.damage_bonus
                        bonus += 2 if enemy.statuses.get("aimed") else 0
                        bonus += 1 if forecast_empowered[id(enemy)] else 0
                        bonus += 1 if enemy.phase == 2 else 0
                        bonus -= 2 if enemy.statuses.get("staggered") else 0
                        bonus -= 2 if enemy.statuses.get("weakened") else 0
                        exposed = self._profile.exposure_penalty if forecast_player.pop("exposed", 0) else 0
                        ward = forecast_player.pop("ward", 0)
                        def forecast(attack: int) -> int:
                            raw = max(1, int((attack + bonus) * self._profile.incoming_multiplier + 0.5))
                            return max(0, max(1, raw - player.armor) + exposed - ward)
                        minimum, maximum = forecast(enemy.attack_min), forecast(enemy.attack_max)
                        if config.mara_aid:
                            minimum = max(0, minimum - 2)
            threat = (
                "danger" if spec.kind == "damage" and (spec.damage_bonus >= 2 or spec.inflicts_bleeding)
                else "attack" if spec.kind == "damage"
                else "mark" if spec.kind == "menace"
                else "setup"
            )
            enemy_views.append(CombatEnemyView(
                id=self._enemy_id(enemy), name=enemy.name, archetype=enemy.archetype,
                hp=enemy.hp, max_hp=enemy.max_hp,
                armor=enemy.armor + (2 if enemy.statuses.get("guarded") else 0),
                phase=enemy.phase, intent_id=enemy.current_intent, intent_label=spec.label,
                telegraph=telegraph, interruptible=interruptible,
                damage_min=minimum, damage_max=maximum, threat=threat,
                statuses=self._status_views(enemy.statuses), targeted=enemy is target and enemy.alive,
                invulnerable=config.objective_enemy_invulnerable,
            ))
        action_views: list[CombatActionView] = []
        for action, label in zip(actions or (), options or ()):
            cost = self._profile.power_focus_cost if action == "power" else 1 if action in {
                "origin", "mara", "tobin", "mara_guard", "tobin_guard",
            } else 0
            reason = ""
            if action == "origin" and self._ability_used:
                reason = "Already used in this battle"
            elif character.focus < cost:
                reason = f"Requires {cost} Focus"
            elif action == "item" and not any(
                quantity and ITEMS[item_id].healing for item_id, quantity in character.inventory.items()
            ):
                reason = "No healing items remaining"
            elif action == "item" and character.hp >= character.max_hp and not self._player_statuses.get("bleeding"):
                reason = "Already at full Health"
            description = self._origin.ability_description if action == "origin" and self._origin else ACTION_DESCRIPTIONS.get(action, "")
            if action == "origin" and self._origin and self._origin.ability_id == "stand_fast" and config.objective_enemy_invulnerable:
                description = "Guard every incoming physical hit and clear Bleeding and Exposed. This survival stance does not counterattack."
            action_views.append(CombatActionView(action, label, cost, not reason, reason, description))
        hook(CombatSnapshot(
            round_number=round_number, phase=phase, difficulty=self._difficulty.value,
            player=player, enemies=tuple(enemy_views),
            target_id=self._enemy_id(target) if target.alive else None,
            actions=tuple(action_views),
            companions=(
                CombatCompanionView("mara", "Mara", character.mara_trust, config.mara_aid),
                CombatCompanionView("tobin", "Tobin", character.tobin_trust, config.tobin_aid),
            ),
            objective=config.objective, max_rounds=config.max_rounds,
            defensive_objective=config.objective_enemy_invulnerable,
        ))

    @staticmethod
    def _coerce_difficulty(value: CombatDifficulty | str) -> CombatDifficulty:
        try:
            return value if isinstance(value, CombatDifficulty) else CombatDifficulty(str(value).lower())
        except ValueError as error:
            valid = ", ".join(mode.value for mode in CombatDifficulty)
            raise ValueError(f"Unknown combat difficulty {value!r}; choose {valid}") from error

    def _prepare_round(self, enemies: list[Enemy]) -> None:
        for enemy in enemies:
            if not enemy.alive:
                continue
            bleeding = enemy.statuses.get("bleeding", 0)
            if bleeding:
                enemy.hp = max(0, enemy.hp - 1)
                self.ui.write(f"{enemy.name} loses 1 Health from Bleeding.", color=Color.MAGENTA)
                self._damage_feedback(enemy, 1, self._enemy_id(enemy), "Bleeding costs 1 Health.")
                self._decrement_status(enemy.statuses, "bleeding")
                if not enemy.alive:
                    self.ui.write(f"{enemy.name} falls from its wounds.", color=Color.YELLOW, bold=True)
                    continue
            if (
                enemy.phase == 1
                and enemy.phase_two_pattern
                and enemy.phase_threshold > 0
                and enemy.hp <= enemy.max_hp * enemy.phase_threshold
            ):
                enemy.phase = 2
                enemy.turn_count = self._opening_turn_index(enemy, phase_two=True)
                self.ui.write(
                    f"PHASE II — {enemy.name} casts aside restraint; ash burns along its weapon.",
                    color=Color.RED,
                    bold=True,
                )
                self._feedback("phase", self._enemy_id(enemy), self._enemy_id(enemy), enemy.phase, f"{enemy.name} enters Phase II.")

    def _plan_intents(self, enemies: list[Enemy]) -> None:
        for enemy in enemies:
            if not enemy.alive:
                continue
            pattern = enemy.phase_two_pattern if enemy.phase == 2 and enemy.phase_two_pattern else enemy.intent_pattern
            pattern = pattern or ("strike",)
            intent = pattern[enemy.turn_count % len(pattern)]
            enemy.current_intent = intent if intent in INTENTS else "strike"

    def _opening_turn_index(self, enemy: Enemy, *, phase_two: bool = False) -> int:
        """Choose a fair, telegraphed opening for the selected difficulty.

        Ranger and Story use each authored pattern exactly as written.  Shadow
        starts at the first directly hostile intent, avoiding the old sequence
        where commanders, predators, and bosses all granted a free setup round.
        The player still sees the intent before choosing an action.
        """

        if not self._profile.aggressive_opening:
            return 0
        pattern = enemy.phase_two_pattern if phase_two and enemy.phase_two_pattern else enemy.intent_pattern
        for index, intent_name in enumerate(pattern or ("strike",)):
            if INTENTS.get(intent_name, INTENTS["strike"]).kind in {"damage", "menace"}:
                return index
        return 0

    def _enemy_phase(self, state: GameState, enemies: list[Enemy], *, defended: bool, config: CombatConfig) -> None:
        for enemy in enemies:
            if not enemy.alive or not state.character.alive:
                continue
            self._resolve_enemy_action(state, enemy, enemies, defended=defended, config=config)

    def _resolve_enemy_action(
        self,
        state: GameState,
        enemy: Enemy,
        enemies: list[Enemy],
        *,
        defended: bool,
        config: CombatConfig,
    ) -> None:
        spec = INTENTS.get(enemy.current_intent, INTENTS["strike"])
        staggered = bool(enemy.statuses.pop("staggered", 0))
        if staggered and spec.interruptible:
            self.ui.write(f"{enemy.name}'s {spec.label} is interrupted!", color=Color.GREEN, bold=True)
            self._feedback("interrupt", "player", self._enemy_id(enemy), 0, f"{spec.label} interrupted")
            enemy.turn_count += 1
            return

        if spec.kind == "aim":
            enemy.statuses["aimed"] = 1
            self.ui.write(f"{enemy.name} circles and takes aim. Its next attack will hit harder.", color=Color.YELLOW)
            self._feedback("info", self._enemy_id(enemy), self._enemy_id(enemy), 0, f"{enemy.name} takes aim: +2 attack strength on its next landed physical hit.")
        elif spec.kind == "guard":
            enemy.statuses["guarded"] = 1
            self.ui.write(f"{enemy.name} braces behind iron: +2 Armor until your next weapon hit.", color=Color.YELLOW)
            self._feedback("info", self._enemy_id(enemy), self._enemy_id(enemy), 0, f"{enemy.name} gains +2 Armor until your next weapon hit.")
        elif spec.kind == "command":
            allies = [ally for ally in enemies if ally is not enemy and ally.alive]
            for ally in allies:
                ally.statuses["empowered"] = max(1, ally.statuses.get("empowered", 0))
            if allies:
                self.ui.write(f"{enemy.name}'s war cry empowers its allies' next attacks.", color=Color.RED)
                self._feedback("info", self._enemy_id(enemy), self._enemy_id(enemy), 0, f"{enemy.name} empowers its allies: +1 attack strength on their next landed physical hits.")
            else:
                enemy.statuses["empowered"] = 1
                self.ui.write(f"{enemy.name}'s war cry steels its own next attack.", color=Color.RED)
                self._feedback("info", self._enemy_id(enemy), self._enemy_id(enemy), 0, f"{enemy.name} empowers its next landed physical hit: +1 attack strength.")
        elif spec.kind == "menace":
            lost = 1 if state.character.focus > 0 else 0
            state.character.focus = max(0, state.character.focus - 1)
            self._player_statuses["exposed"] = 1
            message = f"{enemy.name}'s shadow mark leaves you Exposed"
            message += " and drains 1 Focus." if lost else "."
            self.ui.write(message, color=Color.MAGENTA, bold=True)
            self._feedback("info", self._enemy_id(enemy), "player", lost, message)
        else:
            self._enemy_attack(state, enemy, spec, defended=defended, config=config, staggered=staggered)
        enemy.turn_count += 1

    def _enemy_attack(
        self,
        state: GameState,
        enemy: Enemy,
        spec: IntentSpec,
        *,
        defended: bool,
        config: CombatConfig,
        staggered: bool,
    ) -> None:
        character = state.character
        if self._player_statuses.get("evade", 0):
            self._decrement_status(self._player_statuses, "evade")
            self.ui.write(f"You evade {enemy.name}'s {spec.label} completely.", color=Color.CYAN, bold=True)
            self._feedback("evade", self._enemy_id(enemy), "player", 0, "Attack evaded")
            return

        raw = self.rng.randint(enemy.attack_min, enemy.attack_max) + spec.damage_bonus
        if enemy.statuses.pop("aimed", 0):
            raw += 2
        if enemy.statuses.pop("empowered", 0):
            raw += 1
        if enemy.phase == 2:
            raw += 1
        if staggered:
            raw -= 2
        weakened = enemy.statuses.get("weakened", 0)
        if weakened:
            raw -= 2
            self._decrement_status(enemy.statuses, "weakened")
        raw = max(1, int(raw * self._profile.incoming_multiplier + 0.5))

        armor = ITEMS[character.armor].defense if character.armor else 0
        incoming = max(1, raw - armor)
        if self._player_statuses.pop("exposed", 0):
            incoming += self._profile.exposure_penalty
            self.ui.write("The enemy exploits your Exposed stance.", color=Color.RED)
        if defended:
            incoming = max(1, incoming // 2)
        ward = self._player_statuses.pop("ward", 0)
        if ward:
            incoming = max(0, incoming - ward)
            self.ui.write("Your ward absorbs part of the blow.", color=Color.CYAN)
        if config.mara_aid and self.rng.random() < 0.20:
            incoming = max(0, incoming - 2)
            self.ui.write("Mara turns part of the blow with her second blade.", color=Color.MAGENTA)

        character.hp = max(0, character.hp - incoming)
        self.ui.write(f"{enemy.name}'s {spec.label} hits you for {incoming} damage.", color=Color.RED)
        self._feedback("damage", self._enemy_id(enemy), "player", incoming, f"{enemy.name}: {spec.label}")
        if not character.alive:
            self._feedback("fallen", self._enemy_id(enemy), "player", 0, "Your strength fails.")
        if spec.inflicts_bleeding and incoming > 0:
            self._player_statuses["bleeding"] = max(2, self._player_statuses.get("bleeding", 0))
            self.ui.write("You are Bleeding. Remedy it before the next enemy phase.", color=Color.MAGENTA)

        if self._player_statuses.pop("riposte", 0) and character.alive and enemy.alive and not config.objective_enemy_invulnerable:
            counter = character.strength + 2
            enemy.hp = max(0, enemy.hp - counter)
            self.ui.write(f"You answer from behind your guard for {counter} damage!", color=Color.GREEN)
            self._damage_feedback(enemy, counter, "player", "Counterattack")
            if not enemy.alive:
                self.ui.write(f"{enemy.name} falls to the counterattack.", color=Color.YELLOW, bold=True)

    def _tick_player_bleeding(self, character) -> None:
        bleeding = self._player_statuses.get("bleeding", 0)
        if not bleeding:
            return
        character.hp = max(0, character.hp - 1)
        self.ui.write("Bleeding costs you 1 Health.", color=Color.MAGENTA)
        self._feedback("damage", "player", "player", 1, "Bleeding")
        if not character.alive:
            self._feedback("fallen", "player", "player", 0, "Your strength fails.")
        self._decrement_status(self._player_statuses, "bleeding")

    def _use_origin_ability(
        self,
        state: GameState,
        enemy: Enemy,
        *,
        defensive_objective: bool = False,
    ) -> tuple[bool, bool]:
        character = state.character
        origin = self._origin
        if not origin or not origin.ability_id:
            return False, False
        if self._ability_used:
            self._notice(f"{origin.ability_name} has already been used in this battle.")
            return False, False
        if character.focus <= 0:
            self._notice("You have no Focus left. Choose another action.")
            return False, False

        character.focus -= 1
        self._ability_used = True
        if origin.ability_id == "stand_fast":
            self._player_statuses.pop("exposed", None)
            self._player_statuses.pop("bleeding", None)
            if not defensive_objective:
                self._player_statuses["riposte"] = 1
            message = (
                "STAND FAST — You clear Bleeding and Exposed and guard every blow until this round ends."
                if defensive_objective
                else "STAND FAST — You clear Bleeding and Exposed, guard every blow, and ready a counter."
            )
            self.ui.write(
                message,
                color=Color.CYAN,
                bold=True,
            )
            self._feedback("defend", "player", "player", 0, "Stand Fast")
            return True, True
        if origin.ability_id == "flanking_strike":
            self._player_statuses["evade"] = 1
            weapon_attack = ITEMS[character.weapon].attack if character.weapon else 0
            damage = (
                self.rng.randint(1, 3)
                + character.cunning
                + weapon_attack
                + self._profile.outgoing_bonus
            )
            enemy.hp = max(0, enemy.hp - damage)
            enemy.statuses.pop("guarded", None)
            enemy.statuses["vulnerable"] = 1
            self.ui.write(
                f"FLANKING STRIKE — You bypass Armor for {damage} damage; {enemy.name} is Vulnerable and you gain Evasion.",
                color=Color.GREEN,
                bold=True,
            )
            self._damage_feedback(enemy, damage, "player", "Flanking Strike")
            return True, False
        if origin.ability_id == "field_remedy":
            healed = character.heal(4 + character.will)
            self._player_statuses.pop("bleeding", None)
            self._player_statuses.pop("exposed", None)
            self._player_statuses["ward"] = 2
            self.ui.write(
                f"FIELD REMEDY — You recover {healed} Health, clear hostile effects, and ward the next blow.",
                color=Color.CYAN,
                bold=True,
            )
            self._feedback("heal", "player", "player", healed, "Field Remedy")
            return True, False
        self.ui.write("Your training offers no opening here.", color=Color.YELLOW)
        return False, False

    def _player_damage(self, state: GameState, enemy: Enemy, *, power: bool) -> int:
        character = state.character
        weapon_attack = ITEMS[character.weapon].attack if character.weapon else 0
        roll = self.rng.randint(1, 3)
        guarded = 0 if power else (2 if enemy.statuses.get("guarded", 0) else 0)
        vulnerable = 2 if enemy.statuses.get("vulnerable", 0) else 0
        bonus = self._profile.power_bonus if power else 0
        resistance = (
            self._profile.boss_resistance
            if enemy.archetype == "boss"
            else self._profile.regular_resistance
        )
        return max(
            1,
            roll
            + character.strength
            + weapon_attack
            + bonus
            + vulnerable
            + self._profile.outgoing_bonus
            - enemy.armor
            - guarded
            - resistance,
        )

    @staticmethod
    def _consume_hit_statuses(enemy: Enemy) -> None:
        enemy.statuses.pop("guarded", None)
        enemy.statuses.pop("vulnerable", None)

    @staticmethod
    def _decrement_status(statuses: dict[str, int], name: str) -> None:
        remaining = statuses.get(name, 0) - 1
        if remaining > 0:
            statuses[name] = remaining
        else:
            statuses.pop(name, None)

    def use_item(self, state: GameState) -> bool:
        character = state.character
        consumables = [
            item_id
            for item_id, quantity in character.inventory.items()
            if quantity and ITEMS[item_id].healing
        ]
        if not consumables:
            self._notice("You have no usable items.")
            return False
        labels = [f"{ITEMS[item_id].name} x{character.inventory[item_id]}" for item_id in consumables]
        choice = self.ui.choose("Use which item?", labels, allow_back=True)
        if isinstance(choice, bool) or not isinstance(choice, int) or not 1 <= choice <= len(consumables):
            return False
        item = ITEMS[consumables[choice - 1]]
        if character.hp >= character.max_hp and not self._player_statuses.get("bleeding"):
            self._notice("You are already at full health.")
            return False
        character.remove_item(item.item_id)
        origin_bonus = 2 if character.origin == "healers_apprentice" else 0
        healed = character.heal(item.healing + origin_bonus)
        cured = bool(self._player_statuses.pop("bleeding", 0))
        message = f"You use {item.name} and recover {healed} Health."
        if cured:
            message += " The Bleeding stops."
        self.ui.write(message, color=Color.GREEN)
        self._feedback("heal", "player", "player", healed, message)
        return True

    def _inspect(self, enemy: Enemy, *, defensive_objective: bool = False) -> None:
        intent, telegraph, interruptible = self._intent_presentation(enemy, defensive_objective=defensive_objective)
        effective_armor = enemy.armor + (2 if enemy.statuses.get("guarded") else 0)
        health = "Cannot be wounded here" if defensive_objective else f"{enemy.hp}/{enemy.max_hp} Health"
        self.ui.write(
            f"{enemy.name}: {health}, {effective_armor} Armor, Phase {enemy.phase}",
            color=Color.CYAN,
        )
        self.ui.write(f"Intent — {intent.label}: {telegraph}.", color=Color.YELLOW)
        if enemy.description:
            self.ui.narrate(enemy.description, color=Color.DIM)
        summary = (
            f"{enemy.name}: {health}, {effective_armor} Armor, Phase {enemy.phase}. "
            f"Intent — {intent.label}: {telegraph}."
        )
        self._feedback("inspect", "player", self._enemy_id(enemy), 0, summary)
        panel = getattr(self.ui, "show_panel", None)
        if callable(panel):
            advice = (
                "Guard physical hits while the objective is completed. Setup effects still resolve."
                if defensive_objective else
                "This intent can be interrupted." if interruptible else
                "This intent cannot be interrupted; disruption still reduces its damage."
            )
            sections = [
                {"heading": "Defenses", "text": f"{health}. Armor {effective_armor}. Phase {enemy.phase}."},
                {"heading": f"Intent — {intent.label}", "text": telegraph.capitalize() + ". " + advice},
            ]
            if enemy.description:
                sections.append({"heading": "Field notes", "text": enemy.description})
            if enemy.statuses:
                effects = [f"{name.title()}: {STATUS_DESCRIPTIONS.get(name, '')}" for name, amount in enemy.statuses.items() if amount > 0]
                if effects:
                    sections.append({"heading": "Current effects", "text": "\n\n".join(effects)})
            panel("information", {"title": enemy.name, "subtitle": "Enemy inspection / no turn spent", "sections": sections})

    def _show_status(self, state: GameState, enemies: list[Enemy], round_number: int, target: Enemy, *, defensive_objective: bool = False) -> None:
        character = state.character
        self.ui.write()
        self.ui.write(f"-- Round {round_number} --", color=Color.YELLOW, bold=True)
        self.ui.write(self.ui.meter("Health", character.hp, character.max_hp))
        self.ui.write(self.ui.meter("Focus", character.focus, character.max_focus, color=Color.CYAN))
        player_effects = [name.title() for name, turns in self._player_statuses.items() if turns]
        if player_effects:
            self.ui.write("Effects: " + ", ".join(player_effects), color=Color.MAGENTA)
        for enemy in enemies:
            if not enemy.alive:
                continue
            reader = self.ui.screen_reader
            label = enemy.name if reader else enemy.name[:7]
            marker = (" (targeted)" if reader else " < TARGET") if enemy is target else ""
            if defensive_objective:
                self.ui.write(f"{enemy.name}: Cannot be wounded here" + marker, color=Color.RED)
            else:
                self.ui.write(self.ui.meter(label, enemy.hp, enemy.max_hp, color=Color.RED) + marker)
            intent, telegraph, interruptible = self._intent_presentation(enemy, defensive_objective=defensive_objective)
            if reader:
                warning = " (can be interrupted)" if interruptible else ""
                self.ui.write(f"Intent: {intent.label}{warning}: {telegraph}", color=Color.YELLOW)
            else:
                warning = " !" if interruptible else ""
                self.ui.write(f"  -> {intent.label}{warning}: {telegraph}", color=Color.YELLOW)
            effects = [name.title() for name, turns in enemy.statuses.items() if turns]
            if effects:
                self.ui.write("     " + ", ".join(effects), color=Color.DIM)


def orc_scout(name: str = "Orc Scout") -> Enemy:
    return Enemy(
        name,
        max_hp=9,
        hp=9,
        attack_min=3,
        attack_max=6,
        armor=0,
        description="Lean, rain-blackened, and dangerous when allowed time to aim.",
        archetype="skirmisher",
        intent_pattern=("strike", "aim", "quick"),
    )


def orc_captain(*, wounded: bool = False) -> Enemy:
    hp = 12 if wounded else 16
    return Enemy(
        "Orc Captain",
        max_hp=16,
        hp=hp,
        attack_min=4,
        attack_max=7,
        armor=1,
        description="A scarred Uruk who commands allies before committing to crushing blows.",
        archetype="commander",
        intent_pattern=("command", "strike", "heavy"),
    )


def marsh_warg() -> Enemy:
    return Enemy(
        "Marsh Warg",
        max_hp=14,
        hp=14,
        attack_min=4,
        attack_max=7,
        armor=0,
        description="A huge grey hunter. Its pounce can be interrupted; its mauling jaws cause Bleeding.",
        archetype="predator",
        intent_pattern=("prowl", "pounce", "maul"),
    )


def ghorak() -> Enemy:
    return Enemy(
        "Ghorak Ash-Hand",
        max_hp=25,
        hp=25,
        attack_min=5,
        attack_max=8,
        armor=2,
        description="The Orc commander changes tactics at half Health. His execution must be interrupted or guarded.",
        archetype="boss",
        intent_pattern=("command", "cleave", "brace", "heavy"),
        phase_two_pattern=("menace", "cleave", "execution"),
        phase_threshold=0.5,
    )


def black_rider_echo(*, final: bool = False) -> Enemy:
    return Enemy(
        "Black Rider",
        max_hp=999,
        hp=999,
        attack_min=6 if final else 3,
        attack_max=9 if final else 5,
        armor=3,
        description="A hooded shape that cannot be slain here; survive until the seal answers.",
        archetype="nazgul",
        intent_pattern=("menace", "heavy", "quick"),
        phase_two_pattern=("menace", "execution", "cleave") if final else (),
        phase_threshold=0.5 if final else 0.0,
    )


def ash_sapper() -> Enemy:
    return Enemy(
        "Ash-Hand Sapper",
        max_hp=10,
        hp=10,
        attack_min=3,
        attack_max=5,
        armor=0,
        description="An Orc engineer carrying pitch and a hooked demolition hammer.",
        archetype="saboteur",
        intent_pattern=("aim", "heavy", "quick"),
    )


def ash_commander() -> Enemy:
    return Enemy(
        "Ash-Hand Commander",
        max_hp=14,
        hp=14,
        attack_min=4,
        attack_max=7,
        armor=1,
        description="Ghorak's surviving lieutenant drives the formation with threats.",
        archetype="commander",
        intent_pattern=("command", "strike", "heavy"),
    )


def ash_archer() -> Enemy:
    return Enemy(
        "Ash-Hand Archer",
        max_hp=9,
        hp=9,
        attack_min=3,
        attack_max=6,
        armor=0,
        description="A black-fletched archer searching for the bridge ropes.",
        archetype="archer",
        intent_pattern=("aim", "quick", "strike"),
    )


def chain_troll() -> Enemy:
    return Enemy(
        "Chain Troll",
        max_hp=30,
        hp=30,
        attack_min=5,
        attack_max=9,
        armor=3,
        description="A blinded cave troll armored in floodgate chains.",
        archetype="boss",
        intent_pattern=("guard", "heavy", "cleave"),
        phase_two_pattern=("execution", "menace", "heavy"),
        phase_threshold=0.5,
    )


def teren_false_ranger() -> Enemy:
    return Enemy(
        "Teren the False Ranger",
        max_hp=22,
        hp=22,
        attack_min=4,
        attack_max=8,
        armor=1,
        description="A Ranger oath-breaker who knows every lesson Calenor taught you.",
        archetype="duelist",
        intent_pattern=("quick", "aim", "heavy"),
    )
