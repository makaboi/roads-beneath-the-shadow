"""Application loop and Chapter One story flow."""

from __future__ import annotations

import random
from collections.abc import Sequence

from .artwork import (
    ANCIENT_ROAD_DISCOVERY_ART,
    BLACK_RIDER_CLIFFHANGER_ART,
    BREE_WAYFARER_ORIGIN_ART,
    BREE_STREETS_ART,
    BROKEN_LANTERN_ART,
    CALENOR_BURNING_HOUSE_MEMORY_ART,
    CALENOR_CACHE_CONTENTS_ART,
    CALENOR_LAST_LESSON_ART,
    CALENOR_LETTER_ART,
    DEAD_ROAD_MOSAIC_ART,
    DROWNED_ARMORY_ART,
    DROWNED_WATCH_POST_ART,
    EDRIN_DELIVERS_STAR_ART,
    EDRIN_RANGER_CIPHER_ART,
    EDRINS_ROOM_ART,
    FINAL_RUINS_BATTLE_ART,
    FIGHT_BESIDE_MARA_ART,
    FLOODED_DITCH_RIDER_ART,
    GHORAK_ASH_HAND_INTRO_ART,
    GHORAK_PRISONER_TRAIL_ART,
    HEALERS_APPRENTICE_ORIGIN_ART,
    HIDDEN_HEARTH_STAR_ART,
    KITCHEN_ESCAPE_ART,
    MARA_DRAWS_BLADES_ART,
    MARA_FIRE_CONFESSION_ART,
    MARSH_WARG_INTRO_ART,
    MIDGEWATER_RUINS_ART,
    NED_RETURNS_STAR_RAY_ART,
    NORTH_GATE_ART,
    NORTH_ROAD_SCOUT_ORIGIN_ART,
    NORTH_WAYHOUSE_ART,
    ORC_CAPTAIN_PARLEY_ART,
    ORC_ATTACK_ART,
    ORC_TRACKER_INTRO_ART,
    PONY_PANTRY_CHOICE_ART,
    PRANCING_PONY_EXTERIOR_ART,
    PRANCING_PONY_INTERIOR_ART,
    RANGER_TRAIL_MARKS_ART,
    ROAD_FROM_BREE_ART,
    STAR_KEY_BROKEN_ART,
    STAR_KEY_REFORGED_ART,
    THIRD_STONE_DISCOVERY_ART,
    TITLE_ART_EXPANDED,
    TOBIN_REED_ARRIVES_ART,
    WAYHOUSE_SHRINE_ART,
)
from .combat import (
    CombatConfig,
    CombatDifficulty,
    CombatEngine,
    CombatResult,
    ghorak,
    marsh_warg,
    orc_captain,
    orc_scout,
)
from .content import (
    CHAPTER_ONE_CHOICES,
    ENDING_TEXT,
    ITEMS,
    ORIGINS,
    PART_ONE_ENDINGS,
    QUEST_MISSING_WATCHMAN,
    QUEST_THIRD_STONE,
    QUEST_WAYHOUSE,
)
from .models import Character, GameState
from .journey_artwork import MIDGEWATER_CAMP_ART
from .part_two import PartTwoEpisode, begin_part_two, part_two_ending_breakdown
from .profile import ACHIEVEMENTS, PlayerProfile, ProfileManager
from .savegame import SaveManager
from .settings import SettingsManager, UserSettings
from .ui import Color, TerminalUI


DIFFICULTY_MODES = {
    "story": CombatDifficulty.STORY,
    "ranger": CombatDifficulty.NORMAL,
    "shadow": CombatDifficulty.HARD,
}

DIFFICULTY_DESCRIPTIONS = {
    "story": "Story — gentler damage; focus on choices and atmosphere",
    "ranger": "Ranger — the intended tactical balance",
    "shadow": "Shadow — aggressive openings and stricter tactics for veterans",
}


class Game:
    def __init__(
        self,
        ui: TerminalUI,
        *,
        saves: SaveManager | None = None,
        rng: random.Random | None = None,
        settings_manager: SettingsManager | None = None,
        user_settings: UserSettings | None = None,
        profile: ProfileManager | None = None,
        difficulty: CombatDifficulty | str | None = None,
    ) -> None:
        self.ui = ui
        self.saves = saves or SaveManager()
        self.rng = rng or random.Random()
        self.settings_manager = settings_manager
        self.user_settings = user_settings or UserSettings(
            color_mode="on" if ui.color else "off",
            sound=ui.sound_enabled,
            text_speed=ui.text_speed if isinstance(ui.text_speed, str) else "normal",
            reduced_motion=ui.reduced_motion,
            screen_reader=ui.screen_reader,
        )
        self.profile = profile
        selected_difficulty = difficulty or DIFFICULTY_MODES[self.user_settings.difficulty]
        self.combat = CombatEngine(ui, self.rng, difficulty=selected_difficulty)
        self.part_two = PartTwoEpisode(
            ui,
            self._story_choice,
            lambda state, enemies, config: self.combat.run(state, enemies, config),
        )
        self.state: GameState | None = None

    def run(self) -> None:
        while True:
            self.ui.clear()
            self.ui.art(
                TITLE_ART_EXPANDED,
                Color.SILVER,
                alt_text="An eight-pointed star shines above a winding road between two mountain peaks.",
            )
            self.ui.write(
                "R O A D S   B E N E A T H   T H E   S H A D O W".center(min(72, self.ui.width)),
                color=Color.YELLOW,
                bold=True,
            )
            subtitle = (
                "Part II — The Dead Road"
                if self.state is not None and self.state.chapter == 2
                else "Part I — The Black Rider's Letter"
            )
            self.ui.write(subtitle.center(68), color=Color.DIM)
            options: list[str] = []
            routes: list[str] = []
            if self.state is not None and not self.state.ending:
                options.append(f"Continue {self.state.character.name}'s journey")
                routes.append("continue")
            options.extend(
                ["Begin a new journey", "Load a journey", "Chronicle", "How to play", "Settings", "Quit"]
            )
            routes.extend(["new", "load", "chronicle", "help", "settings", "quit"])
            choice = self.ui.choose("MAIN MENU", options)
            route = routes[choice - 1]
            if route == "continue":
                self._run_journey()
            elif route == "new":
                if self._new_journey():
                    self._run_journey()
            elif route == "load":
                if self._load_menu():
                    self._run_journey()
            elif route == "chronicle":
                self._show_chronicle()
            elif route == "help":
                self._how_to_play()
            elif route == "settings":
                self._settings()
            elif route == "quit":
                self.ui.write("May a star shine upon your road.", color=Color.SILVER)
                return

    def _new_journey(self) -> bool:
        if self.state is not None and not self.state.ending:
            current_name = self.state.character.name
            confirm = self.ui.choose(
                f"Discard {current_name}'s unfinished journey?",
                ["Keep the current journey", "Discard it and begin a new journey"],
            )
            if confirm != 2:
                self.ui.write("Your current journey has been kept.", color=Color.YELLOW)
                return False
        self.ui.clear()
        self.ui.title("WHO WALKS THE ROAD?")
        self.ui.narrate(
            "In Bree you were never a hero—only another face beside the fire. Before the storm "
            "finds you, choose the name by which Middle-earth will remember you."
        )
        while True:
            name = self.ui.prompt("Traveler's name: ").strip()
            if 1 <= len(name) <= 24 and name.isprintable():
                break
            self.ui.write("Enter a printable name from 1 to 24 characters.", color=Color.RED)

        while True:
            labels = [
                f"{origin.name} — HP {origin.max_hp}, STR {origin.strength}, CUN {origin.cunning}, WIL {origin.will}"
                for origin in ORIGINS
            ]
            selected = self.ui.choose("Choose your background", labels)
            if selected is None:
                continue
            origin = ORIGINS[selected - 1]
            origin_art, origin_alt = (
                (
                    BREE_WAYFARER_ORIGIN_ART,
                    "A sturdy Bree traveler waits beneath a hedge gate with an ash staff.",
                ),
                (
                    NORTH_ROAD_SCOUT_ORIGIN_ART,
                    "A hooded North-road scout studies tracks beside the road.",
                ),
                (
                    HEALERS_APPRENTICE_ORIGIN_ART,
                    "A healer's apprentice kneels beside an open field kit with herbs and an ash staff.",
                ),
            )[selected - 1]
            self.ui.write()
            self.ui.art(origin_art, Color.SILVER, alt_text=origin_alt)
            self.ui.narrate(origin.description, color=Color.CYAN)
            confirmed = self.ui.choose("Accept this background?", ["Yes", "Choose again"])
            if confirmed == 1:
                break

        character = Character.from_origin(name, origin)
        self.state = GameState(character=character)
        self.ui.art(
            CALENOR_LAST_LESSON_ART,
            Color.YELLOW,
            alt_text="Calenor teaches a younger traveler to read trail signs beside a campfire.",
        )
        lesson = self.ui.choose(
            "What lesson from Calenor do you carry?",
            [
                '"No road is so dark that kindness cannot find it."',
                '"Read the ground first, then read the sky."',
                '"Fear is a warning. It is not your master."',
            ],
        )
        if lesson == 1:
            character.hope += 1
            self.state.flags["lesson_kindness"] = True
            self.state.add_journal("Calenor taught me that kindness can find even the darkest road.")
        elif lesson == 2:
            character.cunning += 1
            self.state.flags["lesson_tracking"] = True
            self.state.add_journal("Calenor taught me to read the ground before the sky.")
        else:
            character.will += 1
            self.state.flags["lesson_courage"] = True
            self.state.add_journal("Calenor taught me that fear is a warning, not a master.")
        self.state.add_quest("Discover what happened to Calenor")
        self.state.add_journal("Calenor left Bree three weeks ago and never returned.")
        return True

    def _run_journey(self) -> None:
        assert self.state is not None
        while self.state is not None:
            if self.state.ending:
                self._show_ending()
                if self.state.ending:
                    return
                continue
            scene = self.state.scene
            if scene.startswith("part2_"):
                if not self.part_two.run_scene(self.state):
                    return
            elif scene == "chapter1_intro":
                self._chapter_one_intro()
            elif scene == "chapter1_decision":
                if not self._chapter_one_decision():
                    return
            elif scene == "branch_fight":
                self._branch_fight()
            elif scene == "branch_hide":
                self._branch_hide()
            elif scene == "branch_search":
                self._branch_search()
            elif scene == "branch_escape":
                if not self._branch_escape():
                    return
            elif scene == "branch_question":
                if not self._branch_question():
                    return
            elif scene == "aftermath":
                if not self._aftermath():
                    return
            elif scene == "bree_exploration":
                if not self._bree_exploration():
                    return
            elif scene == "north_gate":
                if not self._north_gate():
                    return
            elif scene == "road_from_bree":
                if not self._road_from_bree():
                    return
            elif scene == "midgewater_camp":
                if not self._midgewater_camp():
                    return
            elif scene == "missing_watchman":
                if not self._missing_watchman():
                    return
            elif scene == "marsh_ambush":
                if not self._marsh_ambush():
                    return
            elif scene == "wayhouse":
                if not self._wayhouse():
                    return
            elif scene == "final_battle":
                if not self._final_battle():
                    return
            elif scene == "cliffhanger":
                self._cliffhanger()
            else:
                self.ui.write(f"Unknown scene: {scene}", color=Color.RED)
                return

    def _chapter_one_intro(self) -> None:
        assert self.state is not None
        self.ui.clear()
        self.ui.art(
            PRANCING_PONY_EXTERIOR_ART,
            Color.BLUE,
            alt_text="A steep-roofed timber inn has a smoking chimney, a dark doorway, and a hanging horse sign.",
        )
        self.ui.title("PART I — THE BLACK RIDER'S LETTER")
        self.ui.write("Chapter 1 — Blood at the Prancing Pony", color=Color.RED, bold=True)
        self.ui.write()
        self.ui.narrate(
            "War has not yet reached Bree, but rumors travel faster than armies. Merchants speak "
            "of Orcs crossing the distant hills. Rangers have disappeared from the roads. Calenor, "
            "your guardian, promised to return within seven days. Three weeks have passed."
        )
        self.ui.narrate(
            "Rain pours across Bree as you enter the Prancing Pony. A warm fire burns in the stone "
            "hearth, yet nobody sings. Nobody laughs. A wounded stranger rises beside the fire."
        )
        self.ui.art(
            PRANCING_PONY_INTERIOR_ART,
            Color.YELLOW,
            alt_text="A low fire burns inside a silent, crowded inn.",
        )
        self.ui.art(
            EDRIN_DELIVERS_STAR_ART,
            Color.SILVER,
            alt_text="The wounded messenger Edrin offers a sealed letter and broken silver star.",
        )
        self.ui.write('"Calenor sent me," he whispers.', color=Color.CYAN)
        self.ui.art(
            STAR_KEY_BROKEN_ART,
            Color.SILVER,
            alt_text="A broken silver pendant shaped as an eight-pointed star.",
        )
        self.ui.narrate(
            "He presses a sealed letter and a broken eight-pointed silver star into your hands. One "
            "ray has been snapped away. The pendant is unnaturally cold."
        )
        self.ui.write('"Do not let them find it. The star opens the road."', color=Color.CYAN, bold=True)
        self.ui.narrate(
            "The window shatters. A black-feathered arrow takes the messenger through the back. "
            "A horn answers from beyond Bree's gate, and two Orc scouts force through the inn's "
            "doors beside their captain. He points a broad cleaver at you."
        )
        self.ui.art(
            ORC_ATTACK_ART,
            Color.RED,
            alt_text="Three broad-shouldered Orc raiders advance through a doorway, their captain carrying a cleaver.",
        )
        self.ui.write('"The silver star. Take its bearer alive."', color=Color.RED, bold=True)
        self.ui.art(
            MARA_DRAWS_BLADES_ART,
            Color.MAGENTA,
            alt_text="Mara throws back her cloak and draws two short blades.",
        )
        self.ui.narrate(
            "A traveler named Mara steps between you and the Orcs and draws two short blades."
        )
        self.ui.write('"If you wish to survive," she says, "choose quickly."', color=Color.MAGENTA)
        character = self.state.character
        if "sealed_letter" not in character.inventory:
            character.add_item("sealed_letter")
            character.add_item("silver_star")
        self.state.add_journal("A dying messenger delivered Calenor's letter and a broken silver star.")
        self.state.add_quest("Keep the silver star from the servants of the Shadow")
        self.state.scene = "chapter1_decision"
        self.ui.pause()

    def _chapter_one_decision(self) -> bool:
        assert self.state is not None
        choice = self._story_choice("WHAT WILL YOU DO?", CHAPTER_ONE_CHOICES)
        if choice is None:
            return False
        self.state.scene = {
            1: "branch_fight",
            2: "branch_hide",
            3: "branch_search",
            4: "branch_escape",
            5: "branch_question",
        }[choice]
        return True

    def _branch_fight(self) -> None:
        assert self.state is not None
        self.ui.art(
            FIGHT_BESIDE_MARA_ART,
            Color.RED,
            alt_text="You and Mara stand back-to-back against the Orc attackers.",
        )
        self.ui.narrate(
            "You step beside Mara and draw your weapon. For the first time that night, she smiles. "
            '"Good. Take the scout. The scarred one is mine."'
        )
        self.state.flags["stood_with_mara"] = True
        self.state.character.mara_trust += 2
        self.state.character.hope += 1
        result = self.combat.run(
            self.state,
            [orc_scout(), orc_captain(wounded=True)],
            CombatConfig(mara_aid=True),
        )
        self._resolve_combat(result)

    def _branch_hide(self) -> None:
        assert self.state is not None
        character = self.state.character
        self.ui.art(
            HIDDEN_HEARTH_STAR_ART,
            Color.YELLOW,
            alt_text="You hide the broken silver star beneath a split hearthstone as Orc boots approach.",
        )
        self.ui.narrate(
            "You slip the star inside a split beneath the hearthstone and tuck Calenor's letter "
            "behind your belt. The captain sees your empty hand and hesitates. Mara uses that "
            "heartbeat of doubt to open his sword arm."
        )
        self.state.flags["pendant_hidden"] = True
        character.hope += 1
        character.mara_trust += 1
        result = self.combat.run(
            self.state,
            [orc_scout("Orc Tracker"), orc_captain(wounded=True)],
            CombatConfig(surprise_round=True, mara_aid=True),
        )
        if result == CombatResult.VICTORY:
            self.ui.narrate("When the room falls quiet, you recover the star. No Orc saw where it lay.")
        self._resolve_combat(result)

    def _branch_search(self) -> None:
        assert self.state is not None
        character = self.state.character
        self.ui.art(
            EDRIN_RANGER_CIPHER_ART,
            Color.SILVER,
            alt_text="An oak-leaf Ranger token and black arrowhead lie beside the fallen Edrin.",
        )
        self.ui.narrate(
            "You drop beside the messenger while Mara meets the first blade. Sewn beneath his "
            "collar is an oak-leaf token scored with Calenor's private cipher: NORTH GATE. THIRD STONE."
        )
        character.add_item("ranger_token")
        character.add_item("black_arrowhead")
        character.hp = max(1, character.hp - 2)
        character.mara_trust += 1
        self.state.flags["found_ranger_cipher"] = True
        self.state.add_quest("Find Calenor's mark at Bree's north gate")
        self.state.add_journal("The messenger hid a token directing me to the north gate's third stone.")
        self.ui.write("An Orc blade grazes you while you search. You lose 2 Health.", color=Color.RED)
        result = self.combat.run(
            self.state,
            [orc_scout("Black-fletched Scout"), orc_captain(wounded=True)],
            CombatConfig(mara_aid=True),
        )
        self._resolve_combat(result)

    def _branch_escape(self) -> bool:
        assert self.state is not None
        character = self.state.character
        self.ui.art(
            KITCHEN_ESCAPE_ART,
            Color.BLUE,
            alt_text="Broken crockery leads toward an open rain door and the stable wall beyond.",
        )
        self.ui.narrate(
            "You shoulder through the kitchen as crockery bursts behind you. The rain door stands "
            "open. Beyond it: the stable yard, a low wall, and freedom. Mara is still fighting inside."
        )
        choice = self._story_choice(
            "IN THE KITCHEN",
            ["Turn back and strike from the Orcs' flank", "Climb the stable wall and leave Bree", "Set an oil-and-iron trap in the doorway"],
        )
        if choice is None:
            return False
        if choice == 2:
            character.mara_trust -= 2
            character.corruption += 1
            self.state.flags["abandoned_mara"] = True
            self.ui.art(
                BREE_STREETS_ART,
                Color.BLUE,
                alt_text="Rain-dark lanes wind between Bree's leaning roofs and closed shutters.",
            )
            self.ui.narrate(
                "You vault the stable wall and run into the rain. At the eastern bend, every lamp "
                "goes out at once. A tall rider sits motionless on a black horse, listening. The "
                "silver star turns so cold that your breath smokes around it. When the hood begins "
                "to turn toward you, you crawl beneath the hedge and circle back through the mud."
            )
            character.hp = max(1, character.hp - 3)
            self.state.flags["saw_black_rider_early"] = True
            self.state.scene = "aftermath"
            return True
        if choice == 1:
            character.mara_trust += 1
            character.hope += 1
            self.state.flags["returned_for_mara"] = True
            result = self.combat.run(
                self.state,
                [orc_scout("Kitchen Pursuer"), orc_captain(wounded=True)],
                CombatConfig(surprise_round=True, mara_aid=True),
            )
        else:
            self.state.flags["kitchen_trap"] = True
            character.mara_trust += 1
            if character.cunning >= 3:
                self.ui.narrate("The scout crashes through your trap. Iron pans and burning oil take it out of the fight.")
                enemies = [orc_captain(wounded=True)]
            else:
                character.hp = max(1, character.hp - 3)
                self.ui.write("The trap catches late. You take 3 damage in the burst of flame.", color=Color.RED)
                enemies = [orc_scout("Burned Scout"), orc_captain(wounded=True)]
            result = self.combat.run(self.state, enemies, CombatConfig(surprise_round=True, mara_aid=True))
        self._resolve_combat(result)
        return True

    def _branch_question(self) -> bool:
        assert self.state is not None
        character = self.state.character
        self.ui.write('"Why does the Shadow fear a broken trinket?" you call.', color=Color.CYAN)
        self.ui.art(
            ORC_CAPTAIN_PARLEY_ART,
            Color.RED,
            alt_text="The scarred Orc captain raises a fist and stills every blade in the inn.",
        )
        self.ui.narrate("The captain raises one fist. For an instant, the Orcs wait.")
        choice = self._story_choice(
            "PRESS YOUR QUESTION",
            ["Ask what happened to Calenor", "Ask where the silver star leads", "Offer the pendant in exchange for safe passage"],
        )
        if choice is None:
            return False
        if choice == 3:
            confirm = self._story_choice(
                "MARA WARNS YOU",
                ["Pull the star back and attack", "Place it on the floor and surrender"],
            )
            if confirm is None:
                return False
            if confirm == 2:
                character.corruption += 2
                character.mara_trust -= 3
                self.state.flags["surrendered_star"] = True
                self.ui.narrate(
                    "You lower the star to the floor. The captain reaches for it—and Mara's knife "
                    "pins his hand to the boards. The star rings like struck glass. Shame burns "
                    "hotter than fear as you snatch it back and fight for the life you nearly sold."
                )
                result = self.combat.run(
                    self.state,
                    [orc_captain(wounded=True), orc_scout("Startled Scout")],
                    CombatConfig(surprise_round=True, mara_aid=True),
                )
                self._resolve_combat(result)
                return True
            character.hope += 1
            character.mara_trust += 1
            self.state.flags["false_surrender"] = True
            result = self.combat.run(
                self.state,
                [orc_captain(wounded=True), orc_scout("Startled Scout")],
                CombatConfig(surprise_round=True, mara_aid=True),
            )
        elif choice == 1:
            self.ui.write('"The Ranger lives," the captain says. "For now. The Dead Road needs his blood."', color=Color.RED)
            self.state.flags["calenor_may_live"] = True
            self.state.add_quest("Find the Dead Road before Calenor is taken there")
            self.state.add_journal("The Orc captain claimed Calenor is alive and named the Dead Road.")
            character.mara_trust += 1
            result = self.combat.run(
                self.state,
                [orc_scout(), orc_captain(wounded=True)],
                CombatConfig(mara_aid=True),
            )
        else:
            self.ui.write('"Beneath the kingless city," he says. "Where the North-king sealed his shame."', color=Color.RED)
            self.state.flags["heard_shadow_road"] = True
            self.state.add_journal("The star may open a buried road beneath a ruined city of the North-kingdom.")
            if character.will < 3:
                character.corruption += 1
                self.ui.narrate("The star pulses against your chest. For one breath, you want to follow its cold call.", color=Color.MAGENTA)
            else:
                character.hope += 1
            result = self.combat.run(
                self.state,
                [orc_scout("Red-eye Scout"), orc_captain(wounded=True)],
                CombatConfig(surprise_round=character.will >= 3, mara_aid=True),
            )
        self._resolve_combat(result)
        return True

    def _resolve_combat(self, result: CombatResult) -> None:
        assert self.state is not None
        if result == CombatResult.DEFEAT:
            self.state.character.hp = 1
            self.state.character.mara_trust -= 1
            self.state.flags["mara_saved_player"] = True
            self.ui.narrate(
                "Your knees strike the boards. Before the captain can bind you, Mara drives both "
                "blades beneath his guard. Bree-folk surge from behind overturned tables with "
                "pokers and axes. You wake beside the dying fire, alive by another person's choice."
            )
            self.state.scene = "aftermath"
        elif result == CombatResult.ESCAPED:
            self.state.character.mara_trust -= 1
            self.state.scene = "aftermath"
        else:
            self.state.scene = "aftermath"

    def _aftermath(self) -> bool:
        assert self.state is not None
        character = self.state.character
        if not self.state.flags.get("aftermath_setup"):
            self.ui.title("AFTER THE BLOOD")
            self.ui.narrate(
                "The Prancing Pony is wrecked. Rain blows through the arrow-torn window; ale and blood "
                "run together between the floorboards. The surviving guests bar the doors while Mara "
                "kneels beside the messenger and closes his eyes. His name, she tells you, was Edrin. "
                "He carried messages for the Rangers for twenty years and feared only failing one."
            )
            if "orc_cleaver" not in character.inventory:
                character.add_item("orc_cleaver")
                self.ui.write("Item gained: Orc Cleaver", color=Color.YELLOW)
            recovered = character.heal(max(8, character.max_hp // 2))
            if recovered:
                self.ui.write(f"Mara binds your wounds. You recover {recovered} Health.", color=Color.GREEN)
            self.ui.art(
                CALENOR_LETTER_ART,
                Color.SILVER,
                alt_text="Calenor's rain-stained letter bears an eight-pointed star and a road leading north.",
            )
            self.ui.narrate(
                "At last you break Calenor's seal. Most of the page is blank. Three lines occupy its "
                "center in the square hand he used when a lesson mattered:\n\n"
                "If I do not return, carry the star north. At Bree's north gate, count three stones "
                "from the hinge. Seek the road beneath the road. Trust no path that casts no shadow.\n\n"
                "Below the words is the charcoal shape of an eight-pointed star with one ray missing, "
                "matching your pendant. Whatever door it opens, Calenor expected you to restore it."
            )
            self.state.add_journal("Calenor's letter says to carry the star north and seek the stones of the lost kingdom.")
            self.state.add_quest(QUEST_THIRD_STONE)

            self.ui.art(
                TOBIN_REED_ARRIVES_ART,
                Color.BLUE,
                alt_text="Tobin Reed stands rain-soaked in the wrecked inn, clutching his watch badge.",
            )
            self.ui.narrate(
                "A young member of the Bree watch pushes through the crowd. Tobin Reed is broad-faced, "
                "rain-soaked, and trying not to look at Edrin's body. His partner, Ned Barley, vanished "
                "from the north gate before the attack. The gate was found open, its lantern broken, "
                "and black-fletched tracks led east."
            )
            self.state.flags["aftermath_setup"] = True
        choice = self._story_choice(
            "MARA WAITS FOR YOUR ANSWER",
            [
                'Thank her: "Edrin and I would both be dead without you."',
                'Challenge her: "You knew Calenor. Tell me everything now."',
                'Keep your distance: "Help me reach the north gate, then we part."',
            ],
        )
        if choice is None:
            return False
        if choice == 1:
            character.mara_trust += 2
            character.hope += 1
            self.state.flags["thanked_mara"] = True
            self.ui.write('"Remember that feeling," Mara says. "We may need it before dawn."', color=Color.MAGENTA)
        elif choice == 2:
            character.mara_trust += 1
            self.state.flags["pressed_mara"] = True
            self.ui.narrate(
                '"I met Calenor at the Last Bridge," she says. "He was wounded, carrying the other '
                "half of a map. He believed someone among the Rangers served the Enemy. He sent me "
                'west to watch you—not because he distrusted you, but because he knew they would come."'
            )
            self.state.add_journal("Calenor suspected a traitor among the Rangers and sent Mara to watch over me.")
        else:
            character.mara_trust -= 1
            self.state.flags["kept_mara_distant"] = True
            self.ui.write('"The road will decide that," Mara answers, sheathing one blade.', color=Color.MAGENTA)

        self.state.flags["aftermath_dialogue_complete"] = True
        self.state.scene = "bree_exploration"
        self.state.play_minutes = max(self.state.play_minutes, 8)
        return True

    def _bree_exploration(self) -> bool:
        """Let the player investigate Bree before committing to Calenor's road."""
        assert self.state is not None
        if not self.state.flags.get("bree_map_seen"):
            self.ui.clear()
            self.ui.art(
                BREE_STREETS_ART,
                Color.BLUE,
                alt_text="Rain-dark lanes wind between Bree's leaning roofs and closed shutters.",
            )
            self.ui.title("BREE BEFORE MIDNIGHT")
            self.ui.narrate(
                "The rain weakens to a cold mist. Bree has drawn in upon itself: shutters closed, "
                "hedges whispering, the watch calling from one locked gate to another. Somewhere "
                "beyond those gates a horn answers at long intervals. Whoever commanded the Orcs "
                "has not given up the hunt."
            )
            self.state.flags["bree_map_seen"] = True

        while True:
            options: list[str] = []
            routes: list[str] = []
            if "messenger_room" not in self.state.visited:
                options.append("Examine Edrin's room and the black-fletched arrow")
                routes.append("messenger_room")
            if "stable_yard" not in self.state.visited:
                options.append("Search the stable yard with Tobin")
                routes.append("stable_yard")
            if "pony_kitchen" not in self.state.visited:
                options.append("Gather one set of supplies from the Pony's kitchen")
                routes.append("pony_kitchen")
            if "mara_fire" not in self.state.visited:
                options.append("Speak privately with Mara beside the dying fire")
                routes.append("mara_fire")
            options.append("Go to the north gate and find the third stone")
            routes.append("north_gate")

            choice = self._story_choice("WHERE WILL YOU INVESTIGATE?", options)
            if choice is None:
                return False
            route = routes[choice - 1]
            if route == "north_gate":
                if len(self.state.visited) < 2:
                    self.ui.write(
                        "The letter gives you a destination, but too much about tonight remains unknown. "
                        "Investigate at least two places before leaving the Pony.",
                        color=Color.YELLOW,
                    )
                    continue
                self.state.scene = "north_gate"
                self.state.play_minutes += 8
                return True
            if route == "messenger_room":
                if not self._explore_messenger_room():
                    return False
            elif route == "stable_yard":
                if not self._explore_stable_yard():
                    return False
            elif route == "pony_kitchen":
                if not self._explore_kitchen():
                    return False
            elif route == "mara_fire":
                if not self._talk_with_mara():
                    return False

    def _explore_messenger_room(self) -> bool:
        assert self.state is not None
        self.ui.title("EDRIN'S ROOM")
        self.ui.art(
            EDRINS_ROOM_ART,
            Color.SILVER,
            alt_text="Edrin's attic room holds muddy tracks, an untouched bed, a candle, and a blood-pink basin.",
        )
        self.ui.narrate(
            "Edrin rented the smallest room beneath the eaves. The bed is untouched. Mud from the "
            "Greenway dries in crescents across the floor, and a washbasin contains water gone pink "
            "with blood. He had reached Bree already wounded, then waited here for you instead of "
            "seeking a healer."
        )
        choice = self._story_choice(
            "WHAT DO YOU EXAMINE?",
            [
                "Study the black arrow that killed him",
                "Read the marks cut into the room's candle",
                "Ask Barliman Butterbur what Edrin said while he waited",
            ],
        )
        if choice is None:
            return False
        if choice == 1:
            if "black_arrowhead" not in self.state.character.inventory:
                self.state.character.add_item("black_arrowhead")
            self.state.flags["identified_ghorak_mark"] = True
            self.state.add_journal(
                "The black arrow bears an ash-white hand over a red eye—the personal mark of an Orc called Ghorak."
            )
            self.ui.narrate(
                "Under the soot you find a second brand: an ash-white hand. Mara knows it. Ghorak "
                "Ash-Hand raids the empty lands between the Weather Hills and the Last Bridge. He "
                "does not serve as a common scout; he hunts relics and the people who can open them."
            )
        elif choice == 2:
            self.state.flags["read_edrin_countdown"] = True
            self.state.add_journal("Edrin counted five horn-calls approaching Bree; a sixth was never marked.")
            self.ui.narrate(
                "Six bands circle the candle. Five are crossed through. Edrin was counting the horn "
                "calls outside Bree. The sixth band is untouched. Whatever force he expected has "
                "not yet announced itself."
            )
        else:
            self.state.character.hope += 1
            self.state.flags["heard_edrins_last_words"] = True
            self.ui.narrate(
                'Butterbur twists his apron. "He asked whether Calenor had taught you the old rhyme: '
                "stone remembers star, star remembers blood. Then he said something queer—said your "
                'guardian chose you before he knew your name."'
            )
            self.state.add_journal("Edrin said Calenor chose me before he knew my name.")
        self.state.visit("messenger_room")
        return True

    def _explore_stable_yard(self) -> bool:
        assert self.state is not None
        character = self.state.character
        self.ui.title("THE STABLE YARD")
        self.ui.art(
            BROKEN_LANTERN_ART,
            Color.YELLOW,
            alt_text="A broken watch-lantern lies beside huge wolf tracks in the rain.",
        )
        self.ui.narrate(
            "Tobin holds a shuttered lantern low while you cross the churned yard. The Orcs entered "
            "on foot, but outside the wall their prints mingle with something broader: a great wolf's "
            "pads, deep enough to fill with rain. A broken watch-lantern lies beneath the hedge. "
            "Ned Barley's initials are scratched into its brass door."
        )
        choice = self._story_choice(
            "TOBIN LOOKS TO YOU",
            [
                "Promise that finding Ned is part of finding Calenor",
                "Say the star must come first, whatever happened to Ned",
                "Ask Tobin to show you how a Bree watchman reads a trail",
            ],
        )
        if choice is None:
            return False
        self.state.add_quest(QUEST_MISSING_WATCHMAN)
        self.state.flags["found_neds_lantern"] = True
        if choice == 1:
            character.tobin_trust += 2
            character.hope += 1
            self.state.flags["promised_tobin"] = True
            self.ui.write('"Then I am coming," Tobin says. "Watch orders or no."', color=Color.CYAN)
        elif choice == 2:
            character.tobin_trust -= 1
            self.state.flags["put_star_first"] = True
            self.ui.write('"I heard you," Tobin says quietly. He does not say that he agrees.', color=Color.CYAN)
        else:
            character.tobin_trust += 1
            self.state.flags["learned_bree_tracking"] = True
            self.ui.narrate(
                "Tobin shows you bent clover beneath the mud and black wool caught on thorn. The "
                "tracks run northeast toward the Midgewater fringe. One set of bootprints drags its "
                "left foot. Ned may have walked away from the gate alive."
            )
        self.state.add_journal("Ned's broken lantern and Orc tracks point northeast toward Midgewater.")
        self.state.visit("stable_yard")
        return True

    def _explore_kitchen(self) -> bool:
        assert self.state is not None
        self.ui.title("WHAT THE ROAD ALLOWS")
        self.ui.art(
            PONY_PANTRY_CHOICE_ART,
            Color.YELLOW,
            alt_text="A sword, healing herbs, and a smoke flask wait on the Prancing Pony pantry table.",
        )
        self.ui.narrate(
            "Butterbur opens the locked pantry without being asked. The Pony cannot spare much if "
            "Bree is besieged, but he sets three bundles on the table. You may carry only one without "
            "slowing the company."
        )
        choice = self._story_choice(
            "CHOOSE ONE BUNDLE",
            [
                "A Bree-forged sword from behind the bar",
                "Two bundles of healing herbs and bandages",
                "A Dwarf-smoke flask left by a traveler",
            ],
        )
        if choice is None:
            return False
        character = self.state.character
        if choice == 1:
            character.add_item("bree_blade")
            character.equip(ITEMS["bree_blade"])
            self.ui.write("You equip the Bree-forged Sword. Attack increased.", color=Color.GREEN)
        elif choice == 2:
            character.add_item("healing_herb", 2)
            self.ui.write("You pack two Healing Herbs.", color=Color.GREEN)
        else:
            character.add_item("smoke_bomb")
            self.state.flags["has_smoke_plan"] = True
            self.ui.write("You pack the Dwarf-smoke Flask.", color=Color.GREEN)
        self.state.visit("pony_kitchen")
        return True

    def _talk_with_mara(self) -> bool:
        assert self.state is not None
        character = self.state.character
        self.ui.title("THE WOMAN WITH TWO BLADES")
        self.ui.art(
            MARA_FIRE_CONFESSION_ART,
            Color.MAGENTA,
            alt_text="Mara cleans her twin knives beside dying embers, a shackle scar visible at her wrist.",
        )
        self.ui.narrate(
            "Mara cleans her knives with a strip torn from an Orc cloak. In the quiet she looks "
            "younger than she did in battle, but not less tired. A narrow burn circles her left wrist, "
            "the kind left by a shackle heated in a forge. She notices you looking and covers it."
        )
        choice = self._story_choice(
            "WHAT DO YOU ASK?",
            [
                '"Why did Calenor trust you?"',
                '"What does Ghorak want with the star?"',
                '"Who put that scar around your wrist?"',
            ],
        )
        if choice is None:
            return False
        if choice == 1:
            character.mara_trust += 1
            self.state.flags["mara_oath_known"] = True
            self.ui.narrate(
                '"He did not," she says. "Not at first. Trust was the work of a hundred cold miles. '
                "At the Last Bridge I swore that if he fell, I would keep you alive until you could "
                'choose the road for yourself. I keep my oaths even when I dislike them."'
            )
        elif choice == 2:
            self.state.flags["mara_knows_star"] = True
            self.ui.narrate(
                '"It is not treasure. It is permission," Mara says. "The old North-kingdom built '
                "roads beneath roads—refuges, armories, ways to move unseen. Most doors died with "
                'their keepers. Your star remembers one of them, and Ghorak has learned where."'
            )
            self.state.add_journal("The silver star is a key to hidden roads built by the lost North-kingdom.")
        else:
            if character.mara_trust >= 1:
                character.mara_trust += 2
                self.state.flags["mara_captive_past"] = True
                self.ui.narrate(
                    '"Ghorak," she says after a long silence. "Two winters ago. He wanted a name I '
                    "would not give him. Calenor opened the cage. That is another oath between us—and "
                    'the reason Ghorak will not leave this hunt while either of us breathes."'
                )
            else:
                character.mara_trust -= 1
                self.ui.write('"Not every wound belongs to your story," she says.', color=Color.MAGENTA)
        self.state.visit("mara_fire")
        return True

    def _north_gate(self) -> bool:
        assert self.state is not None
        character = self.state.character
        if not self.state.flags.get("north_gate_intro_seen"):
            self.ui.clear()
            self.ui.art(
                NORTH_GATE_ART,
                Color.SILVER,
                alt_text="Bree's barred north gate opens onto an empty road beneath the hills.",
            )
            self.ui.title("THE THIRD STONE")
            self.ui.narrate(
                "The north gate leans into the storm like an old man against a door. Tobin lifts the "
                "lantern while Mara watches the empty road. From the eastern dark comes one distant horn. "
                "Edrin's unmarked sixth call. The horse beyond it does not sound like any horse bred in Bree."
            )
            self.state.flags["north_gate_intro_seen"] = True

        if not self.state.flags.get("north_gate_truth_chosen"):
            choice = self._story_choice(
                "TOBIN ASKS WHAT THE ORCS WERE SEEKING",
                [
                    "Show him the silver star and tell him everything",
                    "Tell him only that Calenor left a map behind the stone",
                    "Claim the Orcs came only for Edrin's letter",
                ],
            )
            if choice is None:
                return False
            if choice == 1:
                character.tobin_trust += 2
                character.hope += 1
                self.state.flags["tobin_knows_star"] = True
                if "watch_badge" not in character.inventory:
                    character.add_item("watch_badge")
                self.ui.write('Tobin gives you his watch badge. "Then my eyes are yours."', color=Color.CYAN)
            elif choice == 2:
                self.state.flags["tobin_knows_map"] = True
                self.ui.write("Tobin accepts the half-truth, though Mara does not look at you.", color=Color.DIM)
            else:
                character.tobin_trust -= 2
                character.mara_trust -= 1
                self.state.flags["lied_to_tobin"] = True
                self.ui.write('"Poor lie," Mara murmurs when Tobin turns away.', color=Color.MAGENTA)
            self.state.flags["north_gate_truth_chosen"] = True

        if not self.state.flags.get("north_gate_cache_opened"):
            method_options = [
                "Press the broken star into the third stone",
                "Use Calenor's oak-leaf Ranger token as a lever",
                "Pry the stone free with your weapon",
            ]
            method = self._story_choice("HOW WILL YOU OPEN CALENOR'S CACHE?", method_options)
            if method is None:
                return False
            if method == 1:
                self.ui.art(
                    THIRD_STONE_DISCOVERY_ART,
                    Color.CYAN,
                    alt_text="The eight-pointed star answers a hidden mark cut into an ancient boundary stone.",
                )
                self.ui.sound("discovery")
                if character.will >= 3:
                    character.hope += 1
                    self.ui.narrate(
                        "Silver light runs through the mortar. You feel the star search your memories, "
                        "find Calenor's voice, and accept the bond without taking anything from you."
                    )
                else:
                    character.corruption += 1
                    self.ui.narrate(
                        "The stone opens, but for a heartbeat the star shows you a crown beneath black "
                        "water. Power waits there. The longing it leaves is not wholly your own.",
                        color=Color.MAGENTA,
                    )
            elif method == 2 and "ranger_token" in character.inventory:
                self.ui.art(
                    THIRD_STONE_DISCOVERY_ART,
                    Color.GREEN,
                    alt_text="Three weathered boundary stones reveal an old Ranger sign.",
                )
                self.state.flags["opened_cache_as_ranger"] = True
                character.hope += 1
                self.ui.narrate("The oak-leaf fits a hidden notch. Calenor meant Edrin's token to open this without waking the star.")
            else:
                character.hp = max(1, character.hp - 2)
                self.state.flags["forced_cache"] = True
                self.ui.write("The stone gives suddenly and cuts your hand. You lose 2 Health.", color=Color.RED)

            if "calenor_map" not in character.inventory:
                character.add_item("calenor_map")
                character.add_item("ranger_cloak")
            self.ui.art(
                CALENOR_CACHE_CONTENTS_ART,
                Color.SILVER,
                alt_text="Calenor's hidden cache holds a folded Ranger cloak, a map, and a sealed note.",
            )
            self.ui.narrate(
                "Inside lies Calenor's weathered cloak, a waxed road-map, and a note written only days ago. "
                "The map shows a ruined wayhouse at the edge of Midgewater, built over a stair called the "
                "Dead Road. Calenor's note reads:\n\n"
                "The star is wounded. I gave its missing ray to Watchman Ned Barley. If Ghorak finds him, "
                "the wayhouse will open for the Shadow. If the road opens for you, do not follow my blood "
                "unless you are willing to learn why I chose you."
            )
            self.state.complete_quest(QUEST_THIRD_STONE)
            self.state.add_quest(QUEST_MISSING_WATCHMAN)
            self.state.add_quest(QUEST_WAYHOUSE)
            self.state.add_journal("Calenor hid a map to a Midgewater wayhouse built above the Dead Road.")
            self.state.flags["north_gate_cache_opened"] = True

        if not self.state.flags.get("north_gate_promise_chosen"):
            promise = self._story_choice(
                "TOBIN READS NED'S NAME",
                [
                    'Promise: "We bring him home before we seek the wayhouse."',
                    'Be honest: "We find him if Ghorak has not reached him first."',
                    'Refuse: "The road matters more than one watchman."',
                ],
            )
            if promise is None:
                return False
            if promise == 1:
                character.tobin_trust += 2
                character.hope += 1
                self.state.flags["swore_to_save_ned"] = True
            elif promise == 2:
                character.tobin_trust += 1
                self.state.flags["honest_with_tobin"] = True
            else:
                character.tobin_trust -= 2
                character.corruption += 1
                self.state.flags["refused_ned_quest"] = True
            self.state.flags["north_gate_promise_chosen"] = True
        self.state.scene = "road_from_bree"
        self.state.play_minutes += 6
        return True

    def _road_from_bree(self) -> bool:
        assert self.state is not None
        character = self.state.character
        self.ui.clear()
        self.ui.art(
            ROAD_FROM_BREE_ART,
            Color.BLUE,
            alt_text="Bree's last lamps recede behind a narrow road into the wild.",
        )
        self.ui.title("OUT THROUGH THE HEDGE")
        self.ui.narrate(
            "You leave by a shepherd's cut in the northern hedge before the watch can raise the gate. "
            "Bree's last lamps sink behind wet hawthorn. Tobin carries Ned's broken lantern; Mara "
            "walks where the ground is darkest. No one speaks until the horns behind you begin moving east."
        )
        route = self._story_choice(
            "CHOOSE THE APPROACH TO MIDGEWATER",
            [
                "Follow Calenor's tiny Ranger marks through the hills",
                "Follow the Orc and warg tracks before rain erases them",
                "Take the old cart-road and trust speed over secrecy",
            ],
        )
        if route is None:
            return False
        if route == 1:
            self.state.flags["followed_ranger_marks"] = True
            character.hope += 1
            self.ui.art(
                RANGER_TRAIL_MARKS_ART,
                Color.GREEN,
                alt_text="Calenor's trail marks appear beneath a root beside a pale turned stone and red thread.",
            )
            self.ui.narrate(
                "At every fork you find Calenor's sign: three cuts beneath a root, a stone turned pale "
                "side upward. Once, a fresh red thread clings to the mark. He passed this way hurt, "
                "but he was still choosing his path."
            )
        elif route == 2:
            self.state.flags["tracked_ghorak"] = True
            self.ui.art(
                GHORAK_PRISONER_TRAIL_ART,
                Color.RED,
                alt_text="Orc boots, a huge paw print, and a prisoner's dragging foot cross the muddy road.",
            )
            if character.cunning >= 3 or self.state.flags.get("learned_bree_tracking"):
                self.state.flags["ambush_warning"] = True
                self.ui.narrate(
                    "You distinguish three Orcs, one warg, and the dragged foot of a prisoner. A second "
                    "trail doubles behind them. Ghorak left a tracker to watch whoever followed."
                )
            else:
                character.hp = max(1, character.hp - 2)
                self.ui.write("The trail leads through knife-grass. You lose 2 Health before Mara finds firmer ground.", color=Color.RED)
        else:
            self.state.flags["took_cart_road"] = True
            character.mara_trust -= 1
            self.ui.art(
                FLOODED_DITCH_RIDER_ART,
                Color.BLUE,
                alt_text="Three travelers hide in a flooded ditch while a mounted shadow passes overhead.",
            )
            self.ui.narrate(
                "The cart-road is fast and exposed. Once, hoofbeats approach from behind. You lie in "
                "a flooded ditch while a rider-shaped darkness passes without a lantern. Mara waits "
                "until it is gone before whispering that speed has a price."
            )
        self.state.scene = "midgewater_camp"
        self.state.play_minutes += 4
        return True

    def _midgewater_camp(self) -> bool:
        assert self.state is not None
        character = self.state.character
        if not self.state.flags.get("midgewater_camp_setup"):
            self.ui.clear()
            self.ui.art(
                MIDGEWATER_CAMP_ART,
                Color.YELLOW,
                alt_text="A leaning standing stone shelters a small ember beside reeds and dark marsh water.",
            )
            self.ui.title("A FIRE WITHOUT FLAME")
            self.ui.narrate(
                "Near dawn you shelter in the lee of an ancient standing stone. Mara makes a smokeless "
                "ember under her cloak. Midgewater spreads ahead: reed beds, black pools, and the teeth "
                "of forgotten walls. Somewhere among them a man gives one weak blast on a Bree watch-whistle."
            )
            healed = character.heal(6)
            if healed:
                self.ui.write(f"A brief rest restores {healed} Health.", color=Color.GREEN)
            self.state.flags["midgewater_camp_setup"] = True

        if not self.state.flags.get("midgewater_topic_chosen"):
            topic = self._story_choice(
                "WHILE TOBIN SLEEPS, MARA SPEAKS",
                [
                    'Ask why Calenor wrote, "unless you are willing to learn why I chose you"',
                    "Tell Mara about your life before Calenor took you in",
                    "Ask whether she will stay after the star-road opens",
                ],
            )
            if topic is None:
                return False
            if topic == 1:
                self.state.flags["asked_about_adoption"] = True
                self.ui.art(
                    CALENOR_BURNING_HOUSE_MEMORY_ART,
                    Color.RED,
                    alt_text="A Ranger approaches a child beneath a starless sky as a North Downs house burns.",
                )
                self.ui.narrate(
                    '"He never told me," Mara says. "But once, fevered, he spoke of a house burning near '
                    "the North Downs and a child beneath a sky with no stars. He believed finding you was "
                    'not chance. I believed guilt had made him superstitious. Tonight I am less certain."'
                )
                self.state.add_journal("Calenor found me as a child near a burning house in the North Downs.")
            elif topic == 2:
                character.mara_trust += 2
                character.hope += 1
                self.state.flags["shared_past_with_mara"] = True
                self.ui.narrate(
                    "You speak of chores, winter roads, Calenor's impossible standards for a clean camp, "
                    "and the quiet terror of realizing he might never return. Mara listens without offering "
                    "an easy promise. When you finish, she gives you half her waybread."
                )
                self.ui.narrate(
                    "'He taught me to leave no footprints,' she says. 'You make it sound as though "
                    "he taught you to come home.' She turns the bread in her fingers. 'I would "
                    "have liked to know that man.'"
                )
                if "lembas_scrap" not in character.inventory:
                    character.add_item("lembas_scrap")
            else:
                if character.mara_trust >= 2:
                    character.mara_trust += 1
                    self.state.flags["mara_promised_part_two"] = True
                    self.ui.write('"Ask me when we stand before it," she says. "If we still stand."', color=Color.MAGENTA)
                else:
                    self.state.flags["mara_noncommittal"] = True
                    self.ui.write('"I promised Calenor one road," she says. "Do not mistake that for forever."', color=Color.MAGENTA)
            self.state.flags["midgewater_topic_chosen"] = True

        if not self.state.flags.get("midgewater_watch_chosen"):
            watch = self._story_choice(
                "WHO TAKES THE LAST WATCH?",
                ["Take it yourself and let both companions sleep", "Wake Mara", "Wake Tobin"],
            )
            if watch is None:
                return False
            if watch == 1:
                character.hope += 1
                character.mara_trust += 1
                character.tobin_trust += 1
                self.state.flags["kept_last_watch"] = True
                self.ui.narrate(
                    "You cup the ember until the wind passes. Tobin sleeps with one hand around "
                    "his whistle; Mara has set her boots toward the road. For a little while, "
                    "neither has to be useful to anyone. You keep the light for them."
                )
            elif watch == 2:
                character.mara_trust += 1
                self.state.flags["mara_saw_tracker"] = True
                self.ui.narrate(
                    "Mara wakes at the touch of your sleeve. She points to a reed bending "
                    "against the wind. 'Someone else is keeping watch.' She shifts the ember "
                    "behind the stone, then sits close enough for you both to share its warmth."
                )
            else:
                character.tobin_trust += 1
                self.state.flags["tobin_saw_tracker"] = True
                self.ui.narrate(
                    "Tobin counts the lights that ought to be burning along the marsh road. "
                    "One is missing. 'Ned never lets his go out,' he says. He does not reach "
                    "for his whistle. Something beyond the reeds might answer first."
                )
            self.state.flags["midgewater_watch_chosen"] = True
        self.state.scene = "missing_watchman"
        self.state.play_minutes += 6
        return True

    def _missing_watchman(self) -> bool:
        assert self.state is not None
        character = self.state.character
        if not self.state.flags.get("missing_watchman_intro_seen"):
            self.ui.art(
                DROWNED_WATCH_POST_ART,
                Color.SILVER,
                alt_text="Ned hangs in a black-rope snare above a drowned watch post.",
            )
            self.ui.title("THE LOST WHISTLE")
            self.ui.narrate(
                "The whistle leads to a fallen watch-stone surrounded by water. Ned Barley hangs inside "
                "a snare of black rope, one leg trapped beneath masonry. Someone left him alive as bait. "
                "Across the pool, yellow eyes open between the reeds. Above them an Orc tracker draws a "
                "black-feathered arrow and waits for you to step onto the causeway."
            )
            self.state.flags["missing_watchman_intro_seen"] = True

        if not self.state.flags.get("missing_watchman_approach_chosen"):
            approach = self._story_choice(
                "HOW DO YOU REACH NED?",
                [
                    "Circle through the reeds and approach the tracker unseen",
                    "Send Tobin low across the water while you draw the enemy's eyes",
                    "Raise the silver star and command the old stones to answer",
                    "Break the Dwarf-smoke flask across the causeway" if "smoke_bomb" in character.inventory else "Rush the causeway before the tracker can loose",
                ],
            )
            if approach is None:
                return False
            if approach == 1:
                if character.cunning >= 3 or self.state.flags.get("ambush_warning"):
                    self.state.flags["ambushed_tracker"] = True
                    self.ui.write("You reach striking distance before the Orc scents you.", color=Color.GREEN)
                else:
                    character.hp = max(1, character.hp - 3)
                    self.state.flags["tracker_shot_player"] = True
                    self.ui.write("The tracker's arrow finds your shoulder. You lose 3 Health.", color=Color.RED)
            elif approach == 2:
                character.tobin_trust += 2
                self.state.flags["tobin_freed_ned_early"] = True
                self.ui.narrate("Tobin disappears beneath the black water and surfaces behind Ned's stone. The brothers of the watch clasp hands once.")
            elif approach == 3:
                if character.will >= 3:
                    character.hope += 1
                    self.state.flags["woke_watch_stones"] = True
                    self.ui.narrate("Pale lines wake in the causeway. For an instant the hidden road shows you every safe foothold.")
                else:
                    character.corruption += 1
                    self.state.flags["star_revealed_player"] = True
                    self.ui.narrate("The star shows you the path—and shows every servant of the Shadow exactly where you stand.", color=Color.MAGENTA)
            elif "smoke_bomb" in character.inventory:
                character.remove_item("smoke_bomb")
                self.state.flags["smoked_causeway"] = True
                self.ui.narrate("Grey smoke rolls low across the water. The tracker curses; the warg howls at a world gone scentless.")
            else:
                character.hp = max(1, character.hp - 2)
                self.state.flags["rushed_causeway"] = True
                self.ui.write("You cross under fire and lose 2 Health to a grazing arrow.", color=Color.RED)
            self.ui.narrate(
                "Ned is conscious, barely. Beneath his watch coat something silver pulses in answer to "
                "your pendant. He grips your sleeve. 'Calenor gave me the missing ray. Said only you could "
                "join it. Ghorak took him east. The captain is waiting at the wayhouse.'"
            )
            self.state.flags["missing_watchman_approach_chosen"] = True

        if not self.state.flags.get("missing_watchman_rescue_chosen"):
            rescue_options = []
            rescue_routes = []
            if character.origin == "healers_apprentice":
                rescue_options.append("Set Ned's leg and bind the wound with your healer's training")
                rescue_routes.append("heal_skill")
            if character.inventory.get("healing_herb", 0):
                rescue_options.append("Use one Healing Herb to steady Ned")
                rescue_routes.append("herb")
            rescue_options.extend([
                "Free him now and have Tobin defend him during the fight",
                "Leave him concealed until the enemies are defeated",
            ])
            rescue_routes.extend(["free_now", "hide"])
            rescue = self._story_choice("NED IS FADING", rescue_options)
            if rescue is None:
                return False
            route = rescue_routes[rescue - 1]
            if route == "heal_skill":
                self.state.flags["ned_stabilized"] = True
                character.tobin_trust += 2
                character.hope += 1
            elif route == "herb":
                character.remove_item("healing_herb")
                self.state.flags["ned_stabilized"] = True
                character.tobin_trust += 2
                character.hope += 1
            elif route == "free_now":
                self.state.flags["ned_freed_before_combat"] = True
                character.tobin_trust += 1
            else:
                self.state.flags["ned_hidden_during_combat"] = True
                character.tobin_trust -= 1
            self.state.flags["missing_watchman_rescue_chosen"] = True
        self.state.scene = "marsh_ambush"
        self.state.play_minutes += 6
        return True

    def _marsh_ambush(self) -> bool:
        assert self.state is not None
        character = self.state.character
        self.ui.clear()
        self.ui.art(
            ORC_TRACKER_INTRO_ART,
            Color.RED,
            alt_text="A scarred Orc tracker lowers a barbed spear in the reeds.",
        )
        self.ui.art(
            MARSH_WARG_INTRO_ART,
            Color.YELLOW,
            alt_text="A wolf-like marsh Warg bares long fangs above four braced paws.",
        )
        enemies = [orc_scout("Ghorak's Tracker"), marsh_warg()]
        surprise = any(
            self.state.flags.get(flag)
            for flag in ("ambushed_tracker", "smoked_causeway", "woke_watch_stones", "mara_saw_tracker", "tobin_saw_tracker")
        )
        result = self.combat.run(
            self.state,
            enemies,
            CombatConfig(
                surprise_round=surprise,
                mara_aid=character.mara_trust >= 0,
                tobin_aid=character.tobin_trust >= 0 and not self.state.flags.get("ned_freed_before_combat"),
                location_text="The tracker whistles once. Reeds explode as the Marsh Warg charges across black water.",
                objective="Defeat the hunters before they can carry the star-key to Ghorak",
            ),
        )
        if result == CombatResult.DEFEAT:
            character.hp = 4
            self.state.flags["lost_marsh_fight"] = True
            self.state.flags["ned_survived"] = bool(self.state.flags.get("ned_stabilized"))
            character.tobin_trust -= 2
            self.ui.narrate(
                "The warg bears you into the water. Mara's blade finds its throat before the dark "
                "takes you completely, but Ghorak's tracker escapes east with a horn-call. When you "
                "wake, the wayhouse knows you are coming."
            )
        else:
            self.state.flags["won_marsh_fight"] = True
            self.state.flags["ned_survived"] = True
            self.ui.art(
                NED_RETURNS_STAR_RAY_ART,
                Color.SILVER,
                alt_text="Wounded Ned extends the missing silver ray toward the broken star-key.",
            )
            self.ui.narrate(
                "The warg shudders into stillness. Ned cuts a silver point from inside his coat. It "
                "flies from his palm to your broken pendant. With a sound like winter ice cracking, "
                "the missing ray joins its place and the completed eight-pointed star-key wakes."
            )
        self.ui.art(
            STAR_KEY_REFORGED_ART,
            Color.SILVER,
            alt_text="The completed eight-pointed star-key wakes with silver light.",
        )
        if "star_key" not in character.inventory:
            character.remove_item("silver_star")
            character.add_item("star_key")
        if self.state.flags.get("ned_survived"):
            character.tobin_trust += 2
            self.state.complete_quest(QUEST_MISSING_WATCHMAN)
            self.state.add_journal("Ned survived and gave me the second shard of the star-key.")
            self.ui.write("Quest complete: Find missing watchman Ned Barley", color=Color.GREEN, bold=True)
        else:
            self.state.complete_quest(QUEST_MISSING_WATCHMAN)
            self.state.add_journal("Ned died at Midgewater, but the star-key shard was recovered.")
        healed = character.heal(5)
        if healed:
            self.ui.write(f"Ned's field kit restores {healed} Health.", color=Color.GREEN)
        self.state.scene = "wayhouse"
        self.state.play_minutes += 6
        return True

    def _wayhouse(self) -> bool:
        assert self.state is not None
        character = self.state.character
        if not self.state.flags.get("wayhouse_opened"):
            self.ui.clear()
            self.ui.art(
                ANCIENT_ROAD_DISCOVERY_ART,
                Color.SILVER,
                alt_text="A buried stone road descends beneath the ruined wayhouse.",
            )
            self.ui.sound("discovery")
            self.ui.title("THE ROAD BENEATH THE ROAD")
            self.ui.narrate(
                "Calenor's map ends at a hill that should be empty. At sunrise the joined star-key "
                "pulls toward a slab buried under roots. All eight silver points burn, but an old "
                "warden's oath bars the lock. The hill answers with the grinding of stones untouched for centuries."
            )
            opening = self._story_choice(
                "THE WAYHOUSE DEMANDS A WARDEN'S OATH",
                [
                    "Place your palm over the star and speak Calenor's name",
                    "Cut your palm and offer the star your blood",
                    "Use the map to find the counterweight and force the ancient mechanism",
                ],
            )
            if opening is None:
                return False
            if opening == 1:
                if character.hope >= character.corruption:
                    character.hope += 1
                    self.state.flags["gate_opened_by_bond"] = True
                    self.ui.narrate(
                        "All eight points fill with warm light. The key does not remember a bloodline; "
                        "it remembers an oath freely given. Somewhere below, Calenor's voice says your name."
                    )
                else:
                    character.corruption += 1
                    self.state.flags["gate_tasted_memory"] = True
                    self.ui.narrate(
                        "The key opens by taking one memory: Calenor laughing beside a summer fire. "
                        "You know something precious is gone even though you can no longer name it.",
                        color=Color.MAGENTA,
                    )
            elif opening == 2:
                character.corruption += 2
                character.hp = max(1, character.hp - 3)
                self.state.flags["blood_opened_gate"] = True
                self.ui.narrate(
                    "Blood crosses the silver and every buried lock opens at once. For one terrible "
                    "moment you feel all the roads below you—and something far beneath them feels you back.",
                    color=Color.MAGENTA,
                )
            else:
                self.state.flags["forced_wayhouse"] = True
                self.state.flags["ghorak_surprise"] = False
                self.ui.narrate(
                    "The counterweight yields. The star remains dark, but stone teeth announce your "
                    "arrival all through the hill. Mara says nothing about stealth; none remains."
                )
            self.ui.art(
                NORTH_WAYHOUSE_ART,
                Color.BLUE,
                alt_text="Moonlight cuts across the shattered arches of an ancient northern fortress.",
            )
            self.state.flags["wayhouse_opened"] = True
            self.state.visit("wayhouse_entry")

        while True:
            options: list[str] = []
            routes: list[str] = []
            if "wayhouse_armory" not in self.state.visited:
                options.append("Search the drowned armory")
                routes.append("armory")
            if "wayhouse_archive" not in self.state.visited:
                options.append("Read the wall-map in the archive")
                routes.append("archive")
            if "wayhouse_shrine" not in self.state.visited:
                options.append("Enter the chamber where the star is calling")
                routes.append("shrine")
            explored = sum(1 for item in self.state.visited if item.startswith("wayhouse_") and item != "wayhouse_entry")
            if explored >= 2:
                options.append("Descend to the sealed road before Ghorak arrives")
                routes.append("descend")
            choice = self._story_choice("EXPLORE THE BURIED WAYHOUSE", options)
            if choice is None:
                return False
            route = routes[choice - 1]
            if route == "descend":
                self.state.complete_quest(QUEST_WAYHOUSE)
                self.state.scene = "final_battle"
                self.state.play_minutes += 8
                return True
            if route == "armory":
                self.ui.art(
                    DROWNED_ARMORY_ART,
                    Color.BLUE,
                    alt_text="A leaf-shaped sword rests on a stone table in the flooded wayhouse armory.",
                )
                self.ui.narrate(
                    "Bronze hooks line a room half full of black water. Most weapons have become rust, "
                    "but one leaf-shaped short sword lies sealed in oilcloth beneath the captain's table. "
                    "Letters along its fuller brighten when the star passes over them."
                )
                if "numenorean_blade" not in character.inventory:
                    character.add_item("numenorean_blade")
                equip = self._story_choice("THE OLD BLADE IS BALANCED FOR YOUR HAND", ["Equip it", "Keep your current weapon"])
                if equip is None:
                    return False
                if equip == 1:
                    character.equip(ITEMS["numenorean_blade"])
                    self.ui.write("You equip the North-kingdom Blade. Attack greatly increased.", color=Color.GREEN)
                self.state.visit("wayhouse_armory")
            elif route == "archive":
                self.ui.art(
                    DEAD_ROAD_MOSAIC_ART,
                    Color.SILVER,
                    alt_text="A floor mosaic shows silver roads and one black route ending at a split crown.",
                )
                self.ui.narrate(
                    "A mosaic map covers the archive floor. Silver roads join Fornost, Amon Sul, and "
                    "places whose names have worn away. One black line was added later. It descends from "
                    "this wayhouse beneath the Weather Hills and ends at a crown split into eight pieces."
                )
                self.state.flags["learned_dead_road_map"] = True
                self.state.add_journal(
                    "The Dead Road leads beneath the Weather Hills to a place marked by a crown split into eight pieces."
                )
                if self.state.flags.get("identified_ghorak_mark"):
                    self.state.flags["found_ghorak_flank"] = True
                    self.ui.narrate(
                        "Ash-white handprints cross the eastern passage. Because you studied Ghorak's "
                        "mark, you recognize a false trail and find the narrow flank he meant to use."
                    )
                self.state.visit("wayhouse_archive")
            else:
                self.ui.art(
                    WAYHOUSE_SHRINE_ART,
                    Color.MAGENTA,
                    alt_text="A stone chair faces a polished wall where a crowned reflection raises its hand.",
                )
                self.ui.narrate(
                    "The chamber contains no altar—only a stone chair facing a polished wall. In its "
                    "surface you see Calenor chained below the hills. Behind him stands a figure wearing "
                    "your face and an eight-pointed crown. The reflection raises one hand. The star raises yours."
                )
                answer = self._story_choice(
                    "THE REFLECTION OFFERS STRENGTH",
                    ["Break eye contact and speak your companions' names", "Accept enough power to face Ghorak", "Ask it why Calenor chose you"],
                )
                if answer is None:
                    return False
                if answer == 1:
                    character.hope += 2
                    character.mara_trust += 1
                    character.tobin_trust += 1
                    self.state.flags["refused_star_vision"] = True
                elif answer == 2:
                    character.corruption += 2
                    character.heal(character.max_hp)
                    character.focus = character.max_focus
                    self.state.flags["accepted_star_power"] = True
                    self.ui.sound("corruption")
                    self.ui.write("Cold strength fills you. Your Health is restored.", color=Color.MAGENTA)
                else:
                    character.corruption += 1
                    self.state.flags["learned_eighth_heir"] = True
                    self.ui.narrate(
                        '"Because you were found where the eighth house died," the reflection says. '
                        '"Because the road knows what slept beneath your cradle." Then the wall cracks.'
                    )
                    self.state.add_journal("The star called me an heir of an unknown eighth house.")
                self.state.visit("wayhouse_shrine")

    def _final_battle(self) -> bool:
        assert self.state is not None
        character = self.state.character
        self.ui.clear()
        self.ui.art(
            GHORAK_ASH_HAND_INTRO_ART,
            Color.RED,
            alt_text="A broad armored Orc commander holds a cleaver beside an oversized gauntlet.",
        )
        self.ui.narrate(
            "Ghorak Ash-Hand steps from the eastern arch wearing Calenor's broken sword across his "
            "back. Orcs fan out behind him. His pale gauntlet is dusted with the silver of shattered "
            "star-keys. He looks at Mara's scar, Tobin's watch badge, and finally at you."
        )
        self.ui.write(
            '"Calenor opened the Dead Road and learned what you are," Ghorak says. "He ran from the answer. You will not."',
            color=Color.RED,
            bold=True,
        )
        approach = self._story_choice(
            "THE FINAL BATTLE",
            [
                "Challenge Ghorak and keep his attention away from the star-door",
                "Use the ruined pillars to divide his warriors",
                "Let the star's cold power guide your first strike",
            ],
        )
        if approach is None:
            return False
        enemies = [ghorak(), orc_scout("Ash-hand Guard")]
        surprise = False
        objective = "Defeat Ghorak before he opens the Dead Road for the Shadow"
        max_rounds = None
        if approach == 1:
            character.mara_trust += 1
            character.hope += 1
            self.state.flags["challenged_ghorak"] = True
            enemies[0].hp -= 2
        elif approach == 2:
            self.state.flags["used_falling_pillars"] = True
            if self.state.flags.get("learned_dead_road_map") or character.cunning >= 3:
                enemies = [ghorak()]
                surprise = True
                self.ui.narrate("The guard vanishes beneath a falling arch. Ghorak reaches you alone.", color=Color.GREEN)
            else:
                character.hp = max(1, character.hp - 3)
                max_rounds = 6
                objective = "Survive six rounds while the wayhouse collapses around Ghorak"
        else:
            character.corruption += 1
            self.state.flags["used_star_in_final"] = True
            self.ui.sound("corruption")
            surprise = True
            enemies[0].hp -= 4

        self.ui.art(
            FINAL_RUINS_BATTLE_ART,
            Color.YELLOW,
            alt_text="A sword-bearing traveler faces a cleaver-wielding Orc warlord between two ruined pillars.",
        )
        result = self.combat.run(
            self.state,
            enemies,
            CombatConfig(
                surprise_round=surprise or self.state.flags.get("found_ghorak_flank", False),
                mara_aid=character.mara_trust >= 0,
                tobin_aid=character.tobin_trust >= 1 and self.state.flags.get("ned_survived", False),
                location_text="Ghorak's cleaver strikes sparks from the buried stones as the star-door wakes behind you.",
                objective=objective,
                max_rounds=max_rounds,
            ),
        )
        if result == CombatResult.VICTORY:
            self.state.flags["defeated_ghorak"] = True
            self.ui.narrate(
                "Ghorak falls against the star-door. His ash-white hand leaves one last print, then "
                "slides away. Calenor's broken sword rings on the stone. From the passage above comes "
                "the slow tread of a horse that should never fit inside the hill."
            )
        else:
            character.hp = 1
            self.state.flags["defeated_by_ghorak"] = True
            self.ui.narrate(
                "Ghorak beats you to one knee and tears the star-key from your hand. Before he can "
                "claim victory, every torch turns blue. A long black blade passes through his chest "
                "from behind. The thing that killed him is not an ally."
            )
        self.state.scene = "cliffhanger"
        self.state.play_minutes += 7
        return True

    def _cliffhanger(self) -> None:
        assert self.state is not None
        character = self.state.character
        self.ui.clear()
        self.ui.art(
            BLACK_RIDER_CLIFFHANGER_ART,
            Color.MAGENTA,
            alt_text="A faceless hooded Rider raises a sword from the saddle of a broadside horse.",
        )
        self.ui.title("THE EIGHTH HORN")
        self.ui.sound("danger")
        self.ui.narrate(
            "The sixth horn sounds at last—not from Bree, but from directly above the buried chamber. "
            "A Black Rider waits on the broken road. Its hood turns toward you with the certainty of "
            "a compass finding north. The silver star tears itself free and locks into the door."
        )
        if self.state.flags.get("defeated_ghorak"):
            self.ui.narrate(
                "With his last breath, Ghorak laughs. 'Too late. The Nine do not need your key now. "
                "They need the name the road buried inside you.'"
            )
        self.ui.narrate(
            "The floor splits along lines of silver. Far below, a man cries out. You know Calenor's "
            "voice even through stone and years of fear.\n\n"
            '"Do not bring the star to me!" he shouts. "It was never a key. It is the last seal."\n\n'
            "The Rider draws a long blade. Behind you, the only passage back to daylight fills with shadow. "
            "Before you, stairs descend beneath the Weather Hills toward Calenor, the broken crown, "
            "and the truth of the night he found you."
        )
        if character.mara_trust >= 2:
            self.ui.write('Mara takes your left side. "My oath was one road. I choose the next."', color=Color.MAGENTA)
            self.state.flags["mara_chose_to_continue"] = True
        elif character.mara_trust >= 0:
            self.ui.write('Mara draws both blades. "We settle our debts below."', color=Color.MAGENTA)
            self.state.flags["mara_continues_warily"] = True
        else:
            self.ui.write('Mara watches you, not the Rider. "Give me one reason to trust you on those stairs."', color=Color.MAGENTA)
            self.state.flags["mara_part_two_uncertain"] = True
        if character.tobin_trust >= 2 and self.state.flags.get("ned_survived"):
            self.ui.write('Tobin nocks his last arrow. "Ned is safe. I finish the watch."', color=Color.CYAN)
            self.state.flags["tobin_chose_to_continue"] = True
        elif self.state.flags.get("ned_survived"):
            self.ui.write(
                'Tobin looks back toward the marsh. "Ned lives. I will see him home before I choose another road."',
                color=Color.CYAN,
            )
            self.state.flags["tobin_returns_with_ned"] = True
        elif character.tobin_trust >= 2:
            self.ui.write(
                'Tobin lays Ned\'s broken lantern at the threshold. "I could not save him. I can still finish his watch."',
                color=Color.CYAN,
            )
            self.state.flags["tobin_carries_neds_watch"] = True
        else:
            self.ui.write(
                "Tobin remains at the threshold with Ned's lantern, grief standing where trust should have been.",
                color=Color.CYAN,
            )
            self.state.flags["tobin_stays_at_threshold"] = True
        self.ui.write()
        self.ui.write("You lift Calenor's broken sword and descend as the Black Rider enters the wayhouse.", color=Color.SILVER, bold=True)

        # Keep this transition safe to replay from a save made at the scene boundary.
        # Journal and quest helpers are already idempotent; the flag also protects time
        # and any future one-time Part II hand-off effects.
        if not self.state.flags.get("cliffhanger_resolved"):
            self.state.add_journal(
                "Calenor is alive beneath the Weather Hills. He says the silver star is the last seal, not a key."
            )
            self.state.complete_quest("Discover what happened to Calenor")
            self.state.complete_quest("Keep the silver star from the servants of the Shadow")
            self.state.add_quest("Descend the Dead Road and reach Calenor")
            self.state.flags["part_one_complete"] = True
            self.state.play_minutes += 3
            self._prepare_part_two_consequences()
            self.state.flags["cliffhanger_resolved"] = True

        self._set_ending(self.state.ending or self._determine_ending())

    def _discovery_flags(self) -> tuple[str, ...]:
        """Return the major truths the player can carry beyond Part I."""
        assert self.state is not None
        discoveries = (
            "found_ranger_cipher",
            "identified_ghorak_mark",
            "heard_edrins_last_words",
            "read_edrin_countdown",
            "calenor_may_live",
            "asked_about_adoption",
            "learned_dead_road_map",
            "learned_eighth_heir",
        )
        return tuple(flag for flag in discoveries if self.state.flags.get(flag))

    def _knows_hidden_road(self) -> bool:
        """The archive map only becomes actionable when another clue reveals how to read it."""
        assert self.state is not None
        flags = self.state.flags
        can_read_map = any(
            flags.get(flag)
            for flag in (
                "found_ghorak_flank",
                "found_ranger_cipher",
                "asked_about_adoption",
                "learned_eighth_heir",
            )
        )
        return bool(flags.get("learned_dead_road_map") and can_read_map)

    def _determine_ending(self) -> str:
        """Resolve Part I from moral, relational, rescue, and discovery consequences."""
        assert self.state is not None
        character = self.state.character
        flags = self.state.flags

        shadow_dominant = character.corruption >= max(3, character.hope + 2)
        embraced_shadow_twice = bool(
            flags.get("accepted_star_power")
            and flags.get("used_star_in_final")
            and character.corruption > character.hope
        )
        if flags.get("defeated_by_ghorak") or shadow_dominant or embraced_shadow_twice:
            return "shadow_claim"

        if self._knows_hidden_road() and character.hope >= character.corruption:
            return "hidden_road"

        fellowship_holds = bool(
            flags.get("ned_survived")
            and character.mara_trust >= 1
            and character.tobin_trust >= 1
            and character.hope >= character.corruption
        )
        if fellowship_holds:
            return "fellowship"
        return "keeper_of_secrets"

    def _prepare_part_two_consequences(self) -> None:
        """Record stable, player-readable hand-off flags for the next episode."""
        assert self.state is not None
        character = self.state.character
        flags = self.state.flags

        flags["part_two_hidden_route_known"] = self._knows_hidden_road()
        flags["part_two_ned_safe"] = bool(flags.get("ned_survived"))
        flags["part_two_neds_watch_continues"] = bool(
            not flags.get("ned_survived") and character.tobin_trust >= 2
        )
        flags["part_two_mara_present"] = True
        tobin_continues = flags.get("tobin_chose_to_continue") or flags.get(
            "tobin_carries_neds_watch"
        )
        tobin_left = flags.get("tobin_returns_with_ned") or flags.get(
            "tobin_stays_at_threshold"
        )
        flags["part_two_tobin_present"] = bool(
            tobin_continues or (not tobin_left and character.tobin_trust >= 2)
        )

    def _ending_copy(self) -> tuple[str, str]:
        """Return ending prose, replacing the obsolete early-exit Hidden Road copy."""
        assert self.state is not None and self.state.ending is not None
        if self.state.ending == "hidden_road":
            return (
                "THE HIDDEN ROAD",
                "The archive's silver map answers the clues you gathered along the way. An unmarked "
                "stair opens beneath the broken crown, forcing the Black Rider toward the longer road. "
                "You have not escaped the Shadow—but your discoveries have bought the company a path "
                "Ghorak never knew existed.",
            )
        return ENDING_TEXT[self.state.ending]

    def _ending_breakdown(self) -> list[tuple[str, str]]:
        """Explain the decisions that created this ending and their Part II payoff."""
        assert self.state is not None
        character = self.state.character
        flags = self.state.flags

        if character.hope > character.corruption:
            moral = "Hope prevailed; the star answered your bonds without owning them."
        elif character.corruption > character.hope:
            moral = "The star found a foothold in the power and fear you accepted."
        else:
            moral = "Hope and corruption remain evenly matched; the next choice may decide them."

        if character.mara_trust >= 2:
            mara = "She follows by choice, not merely because of her oath to Calenor."
        elif character.mara_trust >= 0:
            mara = "She continues warily; your actions earned cooperation, but not faith."
        else:
            mara = "She no longer trusts the bearer of the star and watches you as closely as the road."

        if flags.get("ned_survived") and character.tobin_trust >= 2:
            watch = "Ned lives, and Tobin follows after entrusting his friend to the Bree watch."
        elif flags.get("ned_survived"):
            watch = "Ned lives, but Tobin returns with him; one companion will not enter the Dead Road."
        elif character.tobin_trust >= 2:
            watch = "Ned fell, and Tobin carries his watch into the dark in Ned's name."
        else:
            watch = "Ned fell, and Tobin remains behind with grief your choices did not heal."

        discoveries = len(self._discovery_flags())
        if flags.get("part_two_hidden_route_known"):
            truth = f"{discoveries} major truths recovered; the archive clues revealed a hidden descent."
        elif discoveries:
            truth = f"{discoveries} major truth{'s' if discoveries != 1 else ''} recovered, but the buried map remains incomplete."
        else:
            truth = "No optional truths recovered; you enter Part II without a map of the enemy's design."

        if flags.get("defeated_ghorak"):
            battle = "Ghorak was defeated; Calenor's broken sword and the initiative pass to you."
        else:
            battle = "Ghorak defeated you; the Black Rider marked the threshold before you escaped below."

        return [
            ("Moral path", moral),
            ("Mara", mara),
            ("Tobin and Ned", watch),
            ("Lost-kingdom lore", truth),
            ("Final stand", battle),
        ]

    def _set_ending(self, ending: str) -> None:
        assert self.state is not None
        self.state.ending = ending
        self.state.scene = "complete"

    def _begin_part_two(self) -> None:
        assert self.state is not None
        self._prepare_part_two_consequences()
        begin_part_two(self.state)

    def _show_ending(self) -> None:
        assert self.state is not None and self.state.ending is not None
        unlocked = self._record_completed_journey()
        title, text = self._ending_copy()
        self.ui.clear()
        self.ui.title(title)
        self.ui.narrate(text, color=Color.SILVER)
        character = self.state.character
        self.ui.write()
        self.ui.title("THE ROAD YOU MADE")
        breakdown = (
            part_two_ending_breakdown(self.state)
            if self.state.chapter == 2
            else self._ending_breakdown()
        )
        for label, consequence in breakdown:
            self.ui.write(f"{label}: {consequence}")
        self.ui.write()
        self.ui.write(
            f"Hope {character.hope}   Corruption {character.corruption}   "
            f"Mara {character.mara_trust:+d}   Tobin {character.tobin_trust:+d}",
            color=Color.DIM,
        )
        if self.state.chapter == 2:
            self.ui.narrate(
                "An underground map illuminates another sealed spoke beneath ruined Fornost.",
                color=Color.SILVER,
            )
            self.ui.narrate(
                "We guarded the road. The Shadow was waking the city.", color=Color.SILVER
            )
            self.ui.write(
                "These choices shape the road to Fornost.", color=Color.YELLOW, bold=True
            )
            self.ui.write()
            self.ui.write("PART II COMPLETE", color=Color.YELLOW, bold=True)
            self.ui.narrate(
                "The road continues in Part III: The Waking City.", color=Color.CYAN
            )
        else:
            self.ui.write(
                "These consequences are carried into Part II.", color=Color.YELLOW, bold=True
            )
            self.ui.write()
            self.ui.write("PART I COMPLETE", color=Color.YELLOW, bold=True)
            self.ui.narrate("The road continues in Part II: The Dead Road.", color=Color.CYAN)
        if unlocked:
            self.ui.write()
            self.ui.title("ACHIEVEMENTS UNLOCKED")
            for achievement in unlocked:
                self.ui.write(f"* {ACHIEVEMENTS[achievement]}", color=Color.GREEN)
        options = ["Save this journey", "Return to the main menu"]
        if self.state.chapter == 1 and self.state.ending in PART_ONE_ENDINGS:
            options.append("Begin Part II — The Dead Road")
        choice = self.ui.choose("What next?", options)
        if choice == 1:
            self._save_menu()
        elif choice == 3:
            self._begin_part_two()

    def _record_completed_journey(self) -> list[str]:
        """Record a completed route exactly once, even if its save is reopened."""

        assert self.state is not None
        recorded_flag = f"profile_recorded_part_{self.state.chapter}"
        legacy_recorded = self.state.chapter == 1 and self.state.flags.get("profile_recorded")
        if self.profile is None or self.state.flags.get(recorded_flag) or legacy_recorded:
            return []
        try:
            unlocked = self.profile.record(self.state)
        except OSError:
            return []
        self.state.flags[recorded_flag] = True
        return unlocked

    def _show_chronicle(self) -> None:
        profile = self.profile.load() if self.profile is not None else PlayerProfile()
        self.ui.clear()
        self.ui.title("THE TRAVELER'S CHRONICLE")
        if profile.completed_runs == 0:
            self.ui.narrate(
                "No completed road has yet been written here. Finish Part I to record an ending, "
                "an origin, and any achievements earned along the way."
            )
            self.ui.pause()
            return

        self.ui.write(f"Completed journeys: {profile.completed_runs}", color=Color.CYAN, bold=True)
        origins = ", ".join(origin.replace("_", " ").title() for origin in profile.origins_completed)
        self.ui.write(f"Origins completed: {origins or 'None'}")
        self.ui.write()
        self.ui.write("Endings witnessed", color=Color.YELLOW, bold=True)
        for ending, count in sorted(profile.endings.items()):
            self.ui.write(f"- {ending.replace('_', ' ').title()}: {count}")
        self.ui.write()
        self.ui.write("Achievements", color=Color.YELLOW, bold=True)
        for achievement, description in ACHIEVEMENTS.items():
            marker = "[x]" if achievement in profile.achievements else "[ ]"
            self.ui.write(f"{marker} {description}")
        self.ui.pause()

    def _story_choice(self, heading: str, options: Sequence[str]) -> int | None:
        while True:
            self.ui.write()
            self.ui.rule()
            self.ui.write(heading.center(min(72, self.ui.width)), color=Color.YELLOW, bold=True)
            self.ui.rule()
            for index, option in enumerate(options, 1):
                self.ui.write(f"[{index}] {option}")
            self.ui.write("[I] Inventory  [C] Character  [J] Journal  [S] Save  [M] Main menu", color=Color.DIM)
            answer = self.ui.prompt("Enter your choice: ").lower()
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return int(answer)
            if answer in {"i", "inventory"}:
                self._inventory_menu()
            elif answer in {"c", "character", "status"}:
                self._show_character()
            elif answer in {"j", "journal", "quests"}:
                self._show_journal()
            elif answer in {"s", "save"}:
                self._save_menu()
            elif answer in {"m", "menu", "q", "quit"}:
                return None
            else:
                self.ui.write("Choose a number or one of the listed commands.", color=Color.RED)

    def _inventory_menu(self) -> None:
        assert self.state is not None
        character = self.state.character
        while True:
            self.ui.title("INVENTORY")
            if not character.inventory:
                self.ui.write("Your pack is empty.", color=Color.DIM)
            for item_id, quantity in character.inventory.items():
                item = ITEMS[item_id]
                markers = []
                if character.weapon == item_id or character.armor == item_id:
                    markers.append("equipped")
                suffix = f" x{quantity}" if quantity > 1 else ""
                marker = f" ({', '.join(markers)})" if markers else ""
                self.ui.write(f"- {item.name}{suffix}{marker}: {item.description}")
            choice = self.ui.choose("Inventory actions", ["Equip an item", "Use a healing item", "Back"])
            if choice == 1:
                equippable = [item_id for item_id in character.inventory if ITEMS[item_id].slot]
                if not equippable:
                    self.ui.write("You have nothing that can be equipped.", color=Color.YELLOW)
                    continue
                labels = [
                    f"{ITEMS[item_id].name} (+{ITEMS[item_id].attack} attack, +{ITEMS[item_id].defense} armor)"
                    for item_id in equippable
                ]
                selected = self.ui.choose("Equip which item?", labels, allow_back=True)
                if selected:
                    item = ITEMS[equippable[selected - 1]]
                    character.equip(item)
                    self.ui.write(f"Equipped {item.name}.", color=Color.GREEN)
            elif choice == 2:
                self.combat.use_item(self.state)
            else:
                return

    def _show_character(self) -> None:
        assert self.state is not None
        c = self.state.character
        weapon = ITEMS[c.weapon].name if c.weapon else "Unarmed"
        armor = ITEMS[c.armor].name if c.armor else "None"
        self.ui.title(c.name.upper())
        self.ui.write(self.ui.meter("Health", c.hp, c.max_hp))
        self.ui.write(f"Strength {c.strength}   Cunning {c.cunning}   Will {c.will}")
        self.ui.write(
            f"Hope {c.hope}   Corruption {c.corruption}   Mara's trust {c.mara_trust}   Tobin's trust {c.tobin_trust}"
        )
        self.ui.write(f"Weapon: {weapon}   Armor: {armor}")

    def _show_journal(self) -> None:
        assert self.state is not None
        self.ui.title("JOURNAL")
        self.ui.write("Active quests", color=Color.YELLOW, bold=True)
        for quest in self.state.quests:
            self.ui.write(f"- {quest}")
        if self.state.completed_quests:
            self.ui.write()
            self.ui.write("Completed quests", color=Color.GREEN, bold=True)
            for quest in self.state.completed_quests:
                self.ui.write(f"- {quest}")
        self.ui.write()
        self.ui.write("Clues", color=Color.YELLOW, bold=True)
        for entry in self.state.journal:
            self.ui.write(f"- {entry}")

    def _save_menu(self) -> bool:
        if self.state is None:
            return False
        labels = self._slot_labels()
        selected = self.ui.choose("Choose a save slot", labels, allow_back=True)
        if selected is None:
            return False
        existing = self.saves.slot_metadata(selected)
        if existing:
            confirm = self.ui.choose(f"Overwrite save slot {selected}?", ["Yes", "No"])
            if confirm != 1:
                return False
        try:
            self.saves.save(selected, self.state)
        except (OSError, ValueError, TypeError) as error:
            self.ui.write(f"Could not save the journey: {error}", color=Color.RED)
            return False
        self.ui.write(f"Journey saved in slot {selected}.", color=Color.GREEN)
        return True

    def _load_menu(self) -> bool:
        labels = self._slot_labels()
        selected = self.ui.choose("Load which journey?", labels, allow_back=True)
        if selected is None:
            return False
        metadata = self.saves.slot_metadata(selected)
        if metadata is None:
            self.ui.write("That slot is empty.", color=Color.YELLOW)
            self.ui.pause()
            return False
        if metadata.get("corrupt"):
            self.ui.write("That save file is damaged and cannot be loaded.", color=Color.RED)
            self.ui.pause()
            return False
        try:
            self.state = self.saves.load(selected)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.ui.write(f"Could not load the journey: {error}", color=Color.RED)
            self.ui.pause()
            return False
        self.ui.write(f"Welcome back, {self.state.character.name}.", color=Color.GREEN)
        return True

    def _slot_labels(self) -> list[str]:
        labels = []
        for slot, metadata in enumerate(self.saves.all_slots(), 1):
            if metadata is None:
                labels.append(f"Slot {slot} — Empty")
            elif metadata.get("corrupt"):
                labels.append(f"Slot {slot} — Damaged save")
            else:
                status = "Chapter complete" if metadata.get("ending") else f"Chapter {metadata['chapter']}"
                labels.append(f"Slot {slot} — {metadata['name']} ({status})")
        return labels

    def _how_to_play(self) -> None:
        self.ui.clear()
        self.ui.title("HOW TO PLAY")
        self.ui.narrate(
            "Enter the number beside a story choice or combat action. Menus also support W/S, the "
            "arrow keys, and Return in an interactive terminal. At story "
            "choices, use I for inventory, C for character status, J for the journal, S to save, "
            "or M to return to the main menu."
        )
        self.ui.write("Combat", color=Color.YELLOW, bold=True)
        self.ui.narrate(
            "Enemies announce their next intent before you act. Attack is dependable. Power attacks "
            "spend Focus, interrupt dangerous moves, and leave you Exposed. Defending halves every "
            "incoming attack that round and restores Focus. Each background has a unique ability, "
            "while companions can disrupt or weaken a chosen enemy."
        )
        self.ui.write("Choices and consequences", color=Color.YELLOW, bold=True)
        self.ui.narrate(
            "Hope, corruption, trust, clues, and surviving companions change available routes. "
            "The game does not mark a single choice as correct."
        )
        self.ui.pause()

    def _settings(self) -> None:
        while True:
            sound = "On" if self.ui.sound_enabled else "Off"
            color = self.user_settings.color_mode.title()
            speed = str(self.user_settings.text_speed).title()
            motion = "Reduced" if self.ui.reduced_motion else "Full"
            reader = "On" if self.ui.screen_reader else "Off"
            difficulty = DIFFICULTY_DESCRIPTIONS[self.user_settings.difficulty]
            choice = self.ui.choose(
                "SETTINGS",
                [
                    f"Original sound cues: {sound}",
                    f"Color mode: {color}",
                    f"Narration speed: {speed}",
                    f"Motion: {motion}",
                    f"Screen-reader mode: {reader}",
                    f"Difficulty: {difficulty}",
                    "Back",
                ],
            )
            if choice == 1:
                self.ui.sound_enabled = not self.ui.sound_enabled
                self.user_settings.sound = self.ui.sound_enabled
                if self.ui.sound_enabled:
                    self.ui.sound("notice")
            elif choice == 2:
                modes = ["auto", "on", "off"]
                current = modes.index(self.user_settings.color_mode)
                self.user_settings.color_mode = modes[(current + 1) % len(modes)]
                if self.user_settings.color_mode == "auto":
                    self.ui.color = self.ui._supports_color()
                else:
                    self.ui.color = self.user_settings.color_mode == "on"
            elif choice == 3:
                speeds = ["slow", "normal", "fast", "instant"]
                current = speeds.index(self.user_settings.text_speed)
                self.user_settings.text_speed = speeds[(current + 1) % len(speeds)]
                self.ui.set_text_speed(self.user_settings.text_speed)
            elif choice == 4:
                self.ui.reduced_motion = not self.ui.reduced_motion
                self.user_settings.reduced_motion = self.ui.reduced_motion
            elif choice == 5:
                self.ui.screen_reader = not self.ui.screen_reader
                self.user_settings.screen_reader = self.ui.screen_reader
            elif choice == 6:
                difficulties = ["story", "ranger", "shadow"]
                current = difficulties.index(self.user_settings.difficulty)
                self.user_settings.difficulty = difficulties[(current + 1) % len(difficulties)]
                self.combat.set_difficulty(DIFFICULTY_MODES[self.user_settings.difficulty])
            else:
                return
            self._persist_settings()

    def _persist_settings(self) -> None:
        if self.settings_manager is None:
            return
        try:
            self.settings_manager.save(self.user_settings)
        except OSError as error:
            self.ui.write(f"Settings could not be saved: {error}", color=Color.RED)
