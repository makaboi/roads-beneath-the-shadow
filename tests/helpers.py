"""Reusable scripted players for full-episode tests."""

from __future__ import annotations

import re

from roads_beneath_shadow.combat import CombatResult


class VictoryCombat:
    def __init__(self) -> None:
        self.encounters = []

    def run(self, state, enemies, config=None):
        self.encounters.append({"enemies": [enemy.name for enemy in enemies], "config": config})
        for enemy in enemies:
            enemy.hp = 0
        return CombatResult.VICTORY


class EpisodePlayer:
    """Reads rendered headings and chooses a coherent completionist route."""

    prompt_limit = 500

    def __init__(
        self,
        opening_choice: int = 1,
        origin_choice: int = 1,
        *,
        road_choice: int = 1,
        midgewater_topic: int = 2,
        real_combat: bool = False,
    ) -> None:
        self.opening_choice = opening_choice
        self.origin_choice = origin_choice
        self.road_choice = road_choice
        self.midgewater_topic = midgewater_topic
        self.real_combat = real_combat
        self.output: list[str] = []
        self.cursor = 0
        self.main_menu_visits = 0
        self.prompt_count = 0

    def write(self, line: str) -> None:
        self.output.append(line)

    def read(self, prompt: str) -> str:
        self.prompt_count += 1
        if self.prompt_count > self.prompt_limit:
            raise AssertionError(
                f"Script exceeded {self.prompt_limit} prompts; likely stuck in a loop"
            )
        context = "\n".join(self.output[self.cursor :])
        self.cursor = len(self.output)
        return self._answer(prompt, context)

    def _answer(self, prompt: str, context: str) -> str:
        if "Traveler's name" in prompt:
            return "Arin"
        if "MAIN MENU" in context:
            self.main_menu_visits += 1
            return "1" if self.main_menu_visits == 1 else "6"
        if "Choose your background" in context:
            return str(self.origin_choice)
        if "Accept this background" in context:
            return "1"
        if "What lesson from Calenor do you carry?" in context:
            return "1"
        if "WHAT WILL YOU DO?" in context:
            return str(self.opening_choice)
        if "IN THE KITCHEN" in context:
            return "1"
        if "PRESS YOUR QUESTION" in context:
            return "1"
        if "MARA WARNS YOU" in context:
            return "1"
        if "Choose your action" in context:
            return self._combat_action(context)
        if "Use which item?" in context:
            return "1"
        if "MARA WAITS FOR YOUR ANSWER" in context:
            return "1"
        if "WHERE WILL YOU INVESTIGATE?" in context:
            return "1"
        if "WHAT DO YOU EXAMINE?" in context:
            return "1"
        if "TOBIN LOOKS TO YOU" in context:
            return "1"
        if "CHOOSE ONE BUNDLE" in context:
            return "1"
        if "WHAT DO YOU ASK?" in context:
            return "2"
        if "TOBIN ASKS WHAT THE ORCS WERE SEEKING" in context:
            return "1"
        if "HOW WILL YOU OPEN CALENOR'S CACHE?" in context:
            return "1"
        if "TOBIN READS NED'S NAME" in context:
            return "1"
        if "CHOOSE THE APPROACH TO MIDGEWATER" in context:
            return str(self.road_choice)
        if "WHILE TOBIN SLEEPS" in context:
            return str(self.midgewater_topic)
        if "WHO TAKES THE LAST WATCH?" in context:
            return "1"
        if "HOW DO YOU REACH NED?" in context:
            return "1"
        if "NED IS FADING" in context:
            return "1"
        if "THE WAYHOUSE DEMANDS A WARDEN'S OATH" in context:
            return "1"
        if "EXPLORE THE BURIED WAYHOUSE" in context:
            return "1"
        if "THE OLD BLADE IS BALANCED" in context:
            return "1"
        if "THE REFLECTION OFFERS STRENGTH" in context:
            return "1"
        if "THE FINAL BATTLE" in context:
            return "1"
        if "What next?" in context:
            return "2"
        raise AssertionError(f"Unexpected prompt: {prompt!r}\nContext:\n{context}")

    @staticmethod
    def _combat_action(context: str) -> str:
        health_matches = re.findall(r"Health\s+\[[#-]+\]\s+(\d+)/(\d+)", context)
        focus_matches = re.findall(r"Focus\s+\[[#-]+\]\s+(\d+)/(\d+)", context)
        if health_matches:
            current, maximum = map(int, health_matches[-1])
            if (
                current <= max(7, maximum // 3)
                and "Use an item" in context
                and "You have no usable items." not in context
            ):
                return "4"
        if focus_matches and int(focus_matches[-1][0]) > 0:
            return "2"
        return "1"


class PartTwoPlayer(EpisodePlayer):
    """Chooses the high-Hope completionist route through Part II."""

    prompt_limit = 300

    def _answer(self, prompt: str, context: str) -> str:
        fixed = {
            "WHAT DO YOU CARRY DOWN?": "Calenor's lesson",
            "MARA HEARS THE RIDER ABOVE": "Trust her",
            "HOW DO YOU BUY FOUR ROUNDS?": "broken sword",
            "THE HALL ASKS FOR A NAME": "road-name",
            "WHO HOLDS THE DARK WITH YOU?": "stand together",
            "WHAT MUST SURVIVE AT ECHO BRIDGE?": "Defend the ropes",
            "WHO DO YOU REACH FIRST?": "prisoners",
            "THE SLUICE HORN SOUNDS. CHOOSE.": "Rescue the captives",
            "HOW DO YOU FREE THEM?": "Pick the cage locks",
            "THE CHAINS ARE ARMOR AND LEASH": "Turn the flood wheel",
            "WHAT BECOMES OF THE DROWNED MILE?": "Drain the Drowned Mile",
            "MARA TOUCHES THE COLD SHACKLE": "Share the forge truth",
            "THE COLD SHACKLE REMAINS": "Name the forge truth",
            "CHOOSE A WAY THROUGH THE REFUGE": "child-height handprints",
            "THE HOUSE BURNS AGAIN": "Search every room",
            "A WOMAN HIDES SOMETHING BENEATH THE FLOOR": "Lift the board",
            "THE CHILD REACHES FOR CALENOR": "Take his hand",
            "HOW DO YOU ANSWER TEREN?": "Present the evidence",
            "IF TEREN YIELDS, WHAT FATE WILL FOLLOW?": "Spare Teren",
            "HOW DO YOU BREAK THE SPOKE-CHAIN?": "Warden oath",
            "WHAT ARE YOUR FIRST WORDS TO CALENOR?": "Bring him home",
            "HOW DO YOU JUDGE CALENOR?": "Forgive Calenor",
            "SET THE RITUAL": "Divide among willing voices",
            "THE STAR WHISPERS BENEATH YOUR SKIN": "Reject the star",
            "WHERE DO YOU STAND FOR SIX ROUNDS?": "Hold the center",
            "WHAT BECOMES OF THE LAST SEAL?": "Remake the seal",
        }
        for heading, label in fixed.items():
            if heading in context:
                return self._visible_choice(context, label)
        if "EXPLORE THE HALL OF EIGHT" in context:
            for label in (
                "Cipher Archive",
                "Erased Statue",
                "Dead Testimony",
                "Take the road to Echo Bridge",
            ):
                if label in context:
                    return self._visible_choice(context, label)
        if "HOW DO YOU REACH ECHO BRIDGE?" in context:
            label = "Warden stair" if "Warden stair" in context else "exposed bridgehead"
            return self._visible_choice(context, label)
        if "ASK CALENOR THE THREE TRUTHS" in context:
            for label in ("Why hide", "What did Teren", "Why must the Rider"):
                if label in context:
                    return self._visible_choice(context, label)
        return super()._answer(prompt, context)

    @staticmethod
    def _visible_choice(context: str, label: str) -> str:
        match = re.search(rf"\[(\d+)\]\s+[^\n]*{re.escape(label)}", context)
        if not match:
            raise AssertionError(f"Expected choice containing {label!r}\nContext:\n{context}")
        return match.group(1)
