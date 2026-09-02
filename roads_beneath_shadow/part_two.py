"""Part II story flow and the completed-Part-I handoff."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from . import part_two_artwork as artwork
from .combat import (
    CombatConfig,
    CombatResult,
    ash_archer,
    ash_commander,
    ash_sapper,
    black_rider_echo,
    chain_troll,
    teren_false_ranger,
)
from .content import (
    PART_ONE_ENDINGS,
    QUEST_DEAD_ROAD_FATE,
    QUEST_EIGHTH_NAME,
    QUEST_LAST_SEAL,
    QUEST_NAMES_LOST,
    QUEST_PRISONERS_ASH,
    QUEST_REACH_CALENOR,
)
from .models import Enemy, GameState
from .ui import Color, TerminalUI


PART_TWO_FIRST_SCENE = "part2_descent"
LEGACY_PART_ONE_QUESTS = (
    "Find Calenor's mark at Bree's north gate",
    "Find the Dead Road before Calenor is taken there",
)

StoryChoice = Callable[[str, Sequence[str]], int | None]
CombatRunner = Callable[[GameState, list[Enemy], CombatConfig], CombatResult]


class PartTwoEpisode:
    def __init__(self, ui: TerminalUI, story_choice: StoryChoice, combat: CombatRunner) -> None:
        self.ui = ui
        self.story_choice = story_choice
        self.combat = combat

    def run_scene(self, state: GameState) -> bool:
        scene = state.scene
        if scene == "part2_descent":
            return self._descent(state)
        elif scene == "part2_pursuit":
            return self._pursuit(state)
        elif scene == "part2_hall":
            return self._hall(state)
        elif scene == "part2_hall_exploration":
            return self._hall_exploration(state)
        elif scene == "part2_echo_bridge":
            return self._echo_bridge(state)
        elif scene == "part2_drowned_mile":
            return self._drowned_mile(state)
        elif scene == "part2_prisoners":
            return self._prisoners(state)
        elif scene == "part2_chain_troll":
            return self._chain_troll(state)
        elif scene == "part2_house_under_ash":
            return self._house_under_ash(state)
        elif scene == "part2_burning_memory":
            return self._burning_memory(state)
        elif scene == "part2_teren":
            return self._teren(state)
        elif scene == "part2_calenor_prison":
            return self._calenor_prison(state)
        elif scene == "part2_calenor_reunion":
            return self._calenor_reunion(state)
        elif scene == "part2_last_seal":
            return self._last_seal(state)
        elif scene == "part2_final_battle":
            return self._final_battle(state)
        elif scene == "part2_seal_choice":
            return self._seal_choice(state)
        raise ValueError(f"Unknown Part II scene: {scene}")

    def _descent(self, state: GameState) -> bool:
        self.ui.clear()
        self.ui.art(
            artwork.PART_TWO_TITLE_ART,
            Color.SILVER,
            alt_text="An eight-pointed star hangs above a stair descending into a black mountain.",
        )
        self.ui.title("PROLOGUE — THE DOOR BELOW")
        self.ui.art(
            artwork.RIDER_WAYHOUSE_THRESHOLD_ART,
            Color.MAGENTA,
            alt_text="A mounted Black Rider fills the broken doorway of a ruined wayhouse.",
        )
        self.ui.narrate(
            "The silver star locks into the buried door. Beyond it, a stair of pale stone drops "
            "under the hills while the Black Rider crosses the wayhouse above."
        )
        self.ui.art(
            artwork.CALENOR_BROKEN_SWORD_ART,
            Color.YELLOW,
            alt_text="Calenor's broken Ranger sword lies across a pale stair above darkness.",
        )
        if state.flags.get("part_two_mara_present", False):
            self.ui.narrate("Mara keeps the rear stair, listening to iron-shod hooves overhead.")
        if state.flags.get("part_two_tobin_present", False):
            self.ui.narrate("Tobin raises his lantern and finds old Ranger marks below the dust.")
        if not state.flags.get("part_two_mara_present", False) and not state.flags.get(
            "part_two_tobin_present", False
        ):
            self.ui.narrate("Only your footsteps answer as the sealed stair falls away behind you.")
        if state.flags.get("part_two_mara_present", False) and state.flags.get(
            "part_two_tobin_present", False
        ):
            self.ui.art(
                artwork.FALLING_SILVER_STAIR_ART,
                Color.SILVER,
                alt_text="A tight group of three travelers descends a collapsing silver stair.",
            )
            self.ui.art(
                artwork.COMPANIONS_DESCENDING_ART,
                Color.SILVER,
                alt_text=(
                    "A traveler, a twin-blade woman, and an archer descend a steep buried road."
                ),
            )

        carried = self.story_choice(
            "WHAT DO YOU CARRY DOWN?",
            [
                "Calenor's lesson: kindness can find the darkest road",
                "Anger at the secrets Calenor kept",
                "The unnamed truth the Shadow fears",
            ],
        )
        if carried is None:
            return False
        mara_response = self.story_choice(
            "MARA HEARS THE RIDER ABOVE",
            [
                "Trust her to hold the rear",
                "Warn her that the Rider wants a willing name",
                "Demand obedience until the stair is sealed",
            ],
        )
        if mara_response is None:
            return False

        if carried == 1:
            state.character.hope += 1
        elif carried == 2:
            state.character.corruption += 1
        if mara_response == 1:
            state.character.mara_trust += 1
        elif mara_response == 3:
            state.character.mara_trust -= 1

        state.play_minutes += 5
        state.scene = "part2_pursuit"
        return True

    def _pursuit(self, state: GameState) -> bool:
        self.ui.clear()
        self.ui.art(
            artwork.RIDER_PURSUIT_INTRO_ART,
            Color.MAGENTA,
            alt_text="A mounted Black Rider descends an impossible stair over a black chasm.",
        )
        self.ui.title("THE RIDER ON THE STAIR")
        self.ui.narrate(
            "Above you, iron shoes strike the first stair. The sound arrives before the horse."
        )
        self.ui.narrate(
            "A severed seal-gate hangs four landings below. Hold the descent long enough for the "
            "counterweights to bury the stair, and the Rider must find another road."
        )
        self.ui.art(
            artwork.SEVERED_SEAL_GATE_ART,
            Color.SILVER,
            alt_text="A massive seal-gate closes across a silver road inside an angular cavern.",
        )
        tactic = self.story_choice(
            "HOW DO YOU BUY FOUR ROUNDS?",
            [
                "Raise Calenor's broken sword",
                "Command the star-mark to bar the stair",
            ],
        )
        if tactic is None:
            return False

        rider = black_rider_echo(final=False)
        if tactic == 1:
            rider.attack_min -= 1
            rider.attack_max -= 1
            self.ui.narrate(
                "The broken blade cannot wound what follows, but its old oath makes the Rider "
                "pause at every dying step."
            )
        else:
            state.flags["part2_star_commanded"] = True
            state.character.corruption += 1
            rider.attack_min -= 2
            rider.attack_max -= 2
            self.ui.narrate(
                "Cold light crosses your palm and seals three stairs at once. Something beneath "
                "the road remembers that you gave it a command."
            )

        result = self.combat(
            state,
            [rider],
            CombatConfig(
                max_rounds=4,
                objective_enemy_invulnerable=True,
                mara_aid=state.flags.get("part_two_mara_present", False)
                and state.character.mara_trust >= 0,
                tobin_aid=state.flags.get("part_two_tobin_present", False),
                objective="Survive four rounds while the seal-gate closes",
                location_text=(
                    "The Rider descends without haste as each stair dies beneath its horse."
                ),
            ),
        )
        if result == CombatResult.VICTORY:
            self.ui.narrate(
                "The seal-gate tears free. Stone fills the stair, buying distance—not victory."
            )
        else:
            state.character.hp = 1
            state.character.corruption += 1
            self.ui.narrate(
                "The gate closes too late. The Rider enters the hall behind you, and only the "
                "road's first turning keeps its hand from your shoulder."
            )

        state.play_minutes += 7
        state.scene = "part2_hall"
        return True

    def _hall(self, state: GameState) -> bool:
        self.ui.clear()
        self.ui.art(
            artwork.DEAD_ROAD_PANORAMA_ART,
            Color.SILVER,
            alt_text=(
                "An ancient buried road crosses a vast underground gulf toward distant arches."
            ),
        )
        self.ui.title("THE HALL OF EIGHT")
        self.ui.art(
            artwork.HALL_EIGHT_WARDENS_ART,
            Color.SILVER,
            alt_text="Eight stone seats form a ring around an eight-pointed floor seal.",
        )
        self.ui.narrate(
            "Seven names ring the floor. The eighth place has been polished until even the "
            "chisel marks are gone."
        )
        self.ui.art(
            artwork.ERASED_EIGHTH_STATUE_ART,
            Color.YELLOW,
            alt_text="An erased stone plinth stands before seven intact guardian statues.",
        )
        self.ui.narrate(
            "No throne stands here. Eight low seats face one another across a map of roads, and "
            "the empty seat waits for a voice."
        )
        name_choice = self.story_choice(
            "THE HALL ASKS FOR A NAME",
            [
                "Refuse to speak any name",
                "Offer only your road-name",
                "Speak the hidden syllable the star already knows",
            ],
        )
        if name_choice is None:
            return False

        holders: list[tuple[str, str]] = [
            ("shared", "We stand together; no single voice owns the dark"),
        ]
        if state.flags.get("part_two_mara_present", False):
            holders.append(("mara", "Mara holds it with me"))
        if state.flags.get("part_two_tobin_present", False):
            holders.append(("tobin", "Tobin holds it with me"))
        holder_choice = self.story_choice(
            "WHO HOLDS THE DARK WITH YOU?",
            [label for _key, label in holders],
        )
        if holder_choice is None:
            return False

        if name_choice == 1:
            state.character.hope += 1
            self.ui.narrate("You give the empty seat silence, and the silence does not break you.")
        elif name_choice == 2:
            state.flags["part2_spoke_road_name"] = True
            self.ui.narrate(
                f'"{state.character.name}," you say—the name carried on open roads, and no more.'
            )
        else:
            state.flags["part2_spoke_hidden_name"] = True
            state.character.corruption += 1
            self.ui.narrate(
                "You release one broken syllable. The hall answers, but the full hidden name "
                "remains yours."
            )

        holder = holders[holder_choice - 1][0]
        if holder == "shared":
            state.character.hope += 1
        elif holder == "mara":
            state.character.mara_trust += 1
        else:
            state.character.tobin_trust += 1

        state.play_minutes += 5
        state.scene = "part2_hall_exploration"
        return True

    def _hall_exploration(self, state: GameState) -> bool:
        self.ui.clear()
        self.ui.art(
            artwork.WALL_NAMES_AWAKENING_ART,
            Color.YELLOW,
            alt_text="Eight columns of names awaken across a dark stone wall.",
        )
        self.ui.title("THE ROAD OF NAMES")
        self.ui.narrate(
            "We were wardens, not kings, says the dust. A road is kept by those who return."
        )
        self.ui.art(
            artwork.FIRST_WARDEN_TESTIMONY_ART,
            Color.SILVER,
            alt_text="A ghostly Warden raises an open hand above a stone seal.",
        )
        self.ui.art(
            artwork.HIDDEN_WARDEN_STAIR_ART,
            Color.YELLOW,
            alt_text="A narrow hidden stair opens beneath a split crown emblem.",
        )
        chambers = (
            (
                "archive",
                "Enter the Cipher Archive",
                "Road marks cover the shelves: distances to travelers, commands to those who "
                "knew how to turn the letters sideways.",
            ),
            (
                "statue",
                "Study the Erased Statue",
                "Seven stone wardens face an eighth body whose face, name, and crown were removed "
                "by careful hands rather than an enemy's hammer.",
            ),
            (
                "testimony",
                "Hear the Dead Testimony",
                "Dust speaks through the empty seat: We kept no crown. We kept the returning road.",
            ),
        )
        chosen: list[str] = []
        while True:
            choices = [(key, label, prose) for key, label, prose in chambers if key not in chosen]
            if len(chosen) >= 2:
                choices.append(("leave", "Take the road to Echo Bridge", ""))
            selection = self.story_choice(
                "EXPLORE THE HALL OF EIGHT",
                [label for _key, label, _prose in choices],
            )
            if selection is None:
                return False
            key, _label, prose = choices[selection - 1]
            if key == "leave":
                break
            chosen.append(key)
            if key == "testimony" and not state.flags.get("part2_spoke_road_name", False):
                prose = (
                    "The empty seat gives back only your last footstep. Without the road-name, "
                    "the testimony remains unanswered."
                )
            self.ui.narrate(prose)

        if "archive" in chosen:
            state.flags["part2_cipher_archive"] = True
        if "statue" in chosen:
            state.flags["part2_erased_statue"] = True
        if "testimony" in chosen and state.flags.get("part2_spoke_road_name", False):
            state.flags["part2_testimony_first"] = True
            state.add_quest(QUEST_NAMES_LOST)
        state.play_minutes += 10 + (4 if len(chosen) == 3 else 0)
        state.scene = "part2_echo_bridge"
        return True

    def _echo_bridge(self, state: GameState) -> bool:
        self.ui.clear()
        self.ui.art(
            artwork.ECHO_BRIDGE_ART,
            Color.SILVER,
            alt_text="An ancient bridge spans a bottomless gulf beneath three stone arches.",
        )
        self.ui.title("ECHO BRIDGE")
        self.ui.narrate("Echo Bridge gives back every footfall except the Rider's.")
        self.ui.narrate(
            "Across the gulf, surviving Ash-Hand Orcs lash pitch jars to the old ropes. Their "
            "captain wears Ghorak's scorched handprint, but not his crown."
        )
        self.ui.art(
            artwork.ORC_SAPPER_INTRO_ART,
            Color.RED,
            alt_text="A hunched Orc sapper grips a hooked hammer beside a pitch jar.",
        )
        approaches = [("exposed", "Cross the exposed bridgehead")]
        if state.flags.get("part_two_hidden_route_known", False):
            approaches.append(("stair", "Descend the hidden Warden stair"))
        approach_choice = self.story_choice(
            "HOW DO YOU REACH ECHO BRIDGE?",
            [label for _key, label in approaches],
        )
        if approach_choice is None:
            return False
        objective_choice = self.story_choice(
            "WHAT MUST SURVIVE AT ECHO BRIDGE?",
            [
                "Defend the ropes and keep the road open",
                "Hunt the sapper before the pitch is lit",
            ],
        )
        if objective_choice is None:
            return False

        approach = approaches[approach_choice - 1][0]
        sapper = ash_sapper()
        enemies = [sapper, ash_commander(), ash_archer()]
        if approach == "stair":
            state.flags["part2_testimony_first"] = True
            state.add_quest(QUEST_NAMES_LOST)
            self.ui.narrate(
                "The hidden stair passes a silver oath cut beneath the bridge. Its first testimony "
                "belongs to anyone who returns by the road."
            )
        if objective_choice == 2:
            sapper.hp = max(1, sapper.hp - 4)

        if state.flags.get("part_two_mara_present", False) and state.flags.get(
            "part_two_tobin_present", False
        ):
            self.ui.art(
                artwork.ECHO_BRIDGE_BATTLE_ART,
                Color.RED,
                alt_text=(
                    "A compact hero formation defends bridge ropes from three Orc silhouettes."
                ),
            )

        result = self.combat(
            state,
            enemies,
            CombatConfig(
                surprise_round=approach == "stair",
                mara_aid=state.flags.get("part_two_mara_present", False)
                and state.character.mara_trust >= 0,
                tobin_aid=state.flags.get("part_two_tobin_present", False),
                objective="Stop the Ash-Hand remnants before Echo Bridge falls",
                location_text=(
                    "Pitch smokes over a lightless gulf while the bridge ropes strain under steel."
                ),
            ),
        )
        if result == CombatResult.VICTORY:
            if objective_choice == 1:
                state.character.hope += 1
                self.ui.narrate("Both ancient ropes hold. The road remains open behind you.")
            else:
                self.ui.narrate("The sapper's pitch gutters out before it can take the bridge.")
        else:
            state.character.hp = 1
            state.character.corruption += 1
            self.ui.narrate(
                "The eastern ropes burn through. You reach the far arch as half the bridge folds "
                "into the gulf behind you."
            )

        state.play_minutes += 8
        state.scene = "part2_drowned_mile"
        return True

    def _drowned_mile(self, state: GameState) -> bool:
        self.ui.clear()
        self.ui.art(
            artwork.DROWNED_MILE_ART,
            Color.BLUE,
            alt_text="A half-submerged road and its marker stones vanish into black water.",
        )
        self.ui.title("THE DROWNED MILE")
        self.ui.narrate(
            "Black water climbs the milestones, swallowing the old names from the bottom upward."
        )
        self.ui.art(
            artwork.DROWNED_CARAVAN_ART,
            Color.BLUE,
            alt_text="A broken prison cart and snapped wheel lean into shallow floodwater.",
        )
        self.ui.narrate(
            "A sluice horn sounds beyond the bend. Two trails cross the flooded stones before "
            "both vanish under the rising water."
        )
        if state.flags.get("part_two_mara_present", False):
            self.ui.art(
                artwork.MARA_SHACKLE_FORGE_ART,
                Color.MAGENTA,
                alt_text="An open shackle rests on a forge anvil while Mara faces it.",
            )
        priority = self.story_choice(
            "WHO DO YOU REACH FIRST?",
            [
                "Reach the prisoners before the sluice horn",
                "Reach the flood wards before they are broken",
                "Reach Calenor before the Ash-Hand moves him",
            ],
        )
        if priority is None:
            return False

        if priority == 1:
            self.ui.narrate("You take the flooded cut toward the cages; the horn sounds again.")
        elif priority == 2:
            self.ui.narrate("You mark the ward-stones as you run, learning where the old water turns.")
        else:
            self.ui.narrate(
                "You choose the shortest line toward Calenor, though every chain in the dark calls "
                "that choice into question."
            )
        state.add_quest(QUEST_PRISONERS_ASH)
        state.play_minutes += 5
        state.scene = "part2_prisoners"
        return True

    def _prisoners(self, state: GameState) -> bool:
        self.ui.clear()
        self.ui.art(
            artwork.PRISONERS_IRON_CAGES_ART,
            Color.BLUE,
            alt_text="Two iron cages hold reaching prisoners above a flooded ledge.",
        )
        self.ui.title("PRISONERS OF ASH")
        self.ui.narrate(
            "Iron cages stand on a shelf above the sluice. The captives have been roped together "
            "for the march east; below them, the last Warden wards begin to drown."
        )
        if state.flags.get("part_two_mara_present", False):
            self.ui.narrate(
                "Mara says, 'A road that survives by leaving people in chains deserves to drown.'"
            )
        self.ui.art(
            artwork.FLOODGATE_WHEEL_ART,
            Color.BLUE,
            alt_text="An enormous eight-spoked floodgate wheel rises above rushing water.",
        )
        choice = self.story_choice(
            "THE SLUICE HORN SOUNDS. CHOOSE.",
            [
                "Rescue the captives before the water reaches them",
                "Preserve the flood wards and keep the old road alive",
                "Race onward while the Ash-Hand is still unready",
            ],
        )
        if choice is None:
            return False

        rescue_method = None
        if choice == 1:
            rescue_method = self.story_choice(
                "HOW DO YOU FREE THEM?",
                [
                    "Pick the cage locks beneath the horn's next note",
                    "Break the rusted hinges with Calenor's sword",
                    "Open the Warden drain and lead them through the dry channel",
                ],
            )
            if rescue_method is None:
                return False

        if choice == 1:
            state.flags["part2_prisoners_rescued"] = True
            state.character.hope += 1
            if state.flags.get("part_two_mara_present", False):
                state.character.mara_trust += 1
            if state.flags.get("part_two_tobin_present", False):
                state.character.tobin_trust += 1
            state.complete_quest(QUEST_PRISONERS_ASH)
            rescue_copy = (
                "One lock yields after another; the captives crawl free between horn notes.",
                "The old blade tears the hinges loose, and the cage opens like a broken jaw.",
                "The drain answers the Warden marks. You lead every captive through the dry stone.",
            )
            self.ui.narrate(rescue_copy[rescue_method - 1])
        elif choice == 2:
            state.flags["part2_flood_wards_preserved"] = True
            self.ui.narrate(
                "You turn the carved stones back into their sockets. The wards hold, but the cage "
                "chain disappears down the next passage."
            )
        else:
            state.flags["part2_kept_initiative"] = True
            if state.flags.get("part_two_mara_present", False):
                state.character.mara_trust -= 1
            if state.flags.get("part_two_tobin_present", False):
                state.character.tobin_trust -= 1
            self.ui.narrate(
                "You run before the horn can finish. Behind you, iron wheels begin to move."
            )

        state.play_minutes += 10 + (4 if choice == 1 else 0)
        state.scene = "part2_chain_troll"
        return True

    def _chain_troll(self, state: GameState) -> bool:
        self.ui.clear()
        self.ui.art(
            artwork.CHAIN_TROLL_INTRO_ART,
            Color.RED,
            alt_text="A huge chained cave troll fills a narrow sluice tunnel.",
        )
        self.ui.title("THE CHAIN TROLL")
        self.ui.narrate(
            "The troll rises with the floodgate on its back, blind eyes sewn shut, every chain "
            "stamped with a dead oath."
        )
        tactic = self.story_choice(
            "THE CHAINS ARE ARMOR AND LEASH",
            [
                "Break the restraining chain and strip away its armor",
                "Turn the flood wheel against the troll",
                "Preserve the restraining chain and fight within its reach",
            ],
        )
        if tactic is None:
            return False
        flood_outcome = self.story_choice(
            "WHAT BECOMES OF THE DROWNED MILE?",
            [
                "Drain the Drowned Mile into the lower dark",
                "Preserve the Drowned Mile's ancient wards",
                "Collapse the flooded branch behind you",
            ],
        )
        if flood_outcome is None:
            return False

        troll = chain_troll()
        if tactic == 1:
            troll.armor = max(0, troll.armor - 2)
        elif tactic == 2:
            troll.hp = max(1, troll.hp - 6)
        else:
            troll.attack_min = max(0, troll.attack_min - 1)
            troll.attack_max = max(0, troll.attack_max - 1)

        if state.flags.get("part_two_mara_present", False) and state.flags.get(
            "part_two_tobin_present", False
        ):
            self.ui.art(
                artwork.CHAIN_TROLL_BATTLE_ART,
                Color.RED,
                alt_text="A chained troll towers over three small defenders beside a flood wheel.",
            )

        result = self.combat(
            state,
            [troll],
            CombatConfig(
                surprise_round=state.flags.get("part2_kept_initiative", False),
                mara_aid=state.flags.get("part_two_mara_present", False)
                and state.character.mara_trust >= 0,
                tobin_aid=state.flags.get("part_two_tobin_present", False),
                objective="Pass the floodgate and survive the Chain Troll",
                location_text=(
                    "Floodwater pounds the gate while oath-chains scrape sparks from the stone."
                ),
            ),
        )
        if result == CombatResult.VICTORY:
            self.ui.narrate(
                "The floodgate opens. Water carries the great chained shape into the dark, and "
                "the second Warden testimony sounds through every link."
            )
        else:
            state.character.hp = 1
            state.character.corruption += 1
            self.ui.narrate(
                "The troll hurls you through the opening gate. The flood bears you onward, alive "
                "only because the oath-chain drags the beast the other way."
            )
        for fate_flag in (
            "part2_drowned_mile_preserved",
            "part2_drowned_branch_collapsed",
            "part2_flood_wards_preserved",
        ):
            state.flags.pop(fate_flag, None)
        if flood_outcome == 1:
            state.character.hope += 1
            self.ui.narrate(
                "You wrench the final wheel open. The black mile drains into the lower dark, "
                "leaving its milestones free to bear names again."
            )
        elif flood_outcome == 2:
            state.flags["part2_drowned_mile_preserved"] = True
            state.flags["part2_flood_wards_preserved"] = True
            self.ui.narrate(
                "You reset the carved wards. The water stills between them, preserving the old "
                "road without surrendering it to the flood."
            )
        else:
            state.flags["part2_drowned_branch_collapsed"] = True
            self.ui.narrate(
                "You break the branch-stone. The flooded passage folds behind you, denying the "
                "Ash-Hand its nearest road to the surface."
            )
        self.ui.art(
            artwork.SECOND_WARDEN_TESTIMONY_ART,
            Color.SILVER,
            alt_text=(
                "A ghostly armored Warden holds a broken chain above a flooded road marker."
            ),
        )
        state.flags["part2_testimony_second"] = True
        state.play_minutes += 9
        state.scene = "part2_house_under_ash"
        return True

    def _house_under_ash(self, state: GameState) -> bool:
        self.ui.clear()
        self.ui.art(
            artwork.HOUSE_UNDER_ASH_ART,
            Color.YELLOW,
            alt_text=(
                "A small stone house lies intact beneath enormous roots in an underground refuge."
            ),
        )
        self.ui.title("THE HOUSE UNDER ASH")
        self.ui.narrate("The house has burned for years. Its ash still knows your step.")
        mara_present = state.flags.get("part_two_mara_present", False)
        if mara_present:
            self.ui.narrate(
                "Mara finds a cold shackle in the ash. Ghorak's ash-hand stamp matches the chain "
                "she once wore."
            )
            truth_heading = "MARA TOUCHES THE COLD SHACKLE"
            truth_options = ["Share the forge truth with Mara", "Keep moving"]
        else:
            self.ui.narrate(
                "A cold shackle lies in the ash, stamped by Ghorak's forge—the forge that once "
                "held Mara."
            )
            truth_heading = "THE COLD SHACKLE REMAINS"
            truth_options = ["Name the forge truth aloud", "Keep moving"]

        truth_choice = self.story_choice(truth_heading, truth_options)
        if truth_choice is None:
            return False
        routes = (
            "Follow the child-height handprints",
            "Take the Warden service passage",
            "Cross the ruined dormitory",
        )
        route_choice = self.story_choice(
            "CHOOSE A WAY THROUGH THE REFUGE",
            routes,
        )
        if route_choice is None:
            return False

        if mara_present:
            if truth_choice == 1:
                state.flags["part2_shared_mara_truth"] = True
                state.character.mara_trust += 1
                self.ui.narrate(
                    "Mara closes the shackle in both hands. 'That forge made my chain. It does "
                    "not get to make my silence.'"
                )
            else:
                state.character.mara_trust -= 1
                self.ui.narrate("You leave the shackle unnamed between you and keep walking.")

        route_label = routes[route_choice - 1]
        self.ui.narrate(f"You {route_label[0].lower() + route_label[1:]} through the ash.")

        if (
            mara_present
            and state.character.mara_trust < 0
            and not state.flags.get("part2_prisoners_rescued", False)
            and not state.flags.get("part2_shared_mara_truth", False)
        ):
            state.flags["part_two_mara_present"] = False
            state.flags["part2_mara_left"] = True
            self.ui.narrate(
                "At the refuge arch, Mara stops. 'I will not follow another keeper who leaves "
                "chains unnamed.' Her steps turn back toward the prisoners' road."
            )

        state.play_minutes += 6
        state.scene = "part2_burning_memory"
        return True

    def _burning_memory(self, state: GameState) -> bool:
        self.ui.clear()
        self.ui.art(
            artwork.BURNING_HOUSE_MEMORY_FULL_ART,
            Color.RED,
            alt_text=(
                "A burning house dominates the night as a child faces an approaching Ranger."
            ),
        )
        self.ui.title("THE BURNING MEMORY")
        self.ui.narrate(
            "The refuge becomes the house from your childhood. Flame climbs walls that have "
            "already been ash for years."
        )
        search_choice = self.story_choice(
            "THE HOUSE BURNS AGAIN",
            [
                "Search every room before the roof falls",
                "Follow the child-self through the smoke",
                "Ask the star-mark beneath your skin to remember",
            ],
        )
        if search_choice is None:
            return False
        floor_choice = self.story_choice(
            "A WOMAN HIDES SOMETHING BENEATH THE FLOOR",
            [
                "Lift the board and see what she protected",
                "Call to her through the memory",
                "Mark the place and keep your distance",
            ],
        )
        if floor_choice is None:
            return False
        bond_choice = self.story_choice(
            "THE CHILD REACHES FOR CALENOR",
            [
                "Take his hand",
                "Look back at the burning house",
                "Ask why he knew the way out",
            ],
        )
        if bond_choice is None:
            return False

        if search_choice == 1:
            state.flags["part2_memory_complete"] = True
            self.ui.narrate(
                "You search every room. The woman hid road-ciphers, never a spoken name; Calenor "
                "broke from the pursuit to carry the child out."
            )
        elif search_choice == 2:
            state.character.hope += 1
            self.ui.narrate("You follow the child and learn that terror did not choose the road.")
        else:
            state.flags["part2_star_read_memory"] = True
            state.character.corruption += 1
            self.ui.narrate(
                "Cold points open beneath your skin. The mark shows the fire, but keeps one ember "
                "for itself."
            )

        if floor_choice == 1:
            self.ui.narrate("Beneath the board lies an Eighth-house road cipher cut in silver ash.")
        elif floor_choice == 2:
            self.ui.narrate("She cannot answer, but she turns toward the sound of your voice.")
        else:
            self.ui.narrate("You keep the hiding place intact, a truth witnessed without possession.")
        if bond_choice == 1:
            self.ui.narrate("Calenor's remembered hand closes around yours and leads you out.")
        elif bond_choice == 2:
            self.ui.narrate("You look back once. No hidden name follows you through the smoke.")
        else:
            self.ui.narrate("The memory gives no answer. Calenor's living voice must do that.")

        state.play_minutes += 8 + (4 if search_choice == 1 else 0)
        state.scene = "part2_teren"
        return True

    def _teren(self, state: GameState) -> bool:
        self.ui.clear()
        self.ui.art(
            artwork.TEREN_REVEAL_ART,
            Color.YELLOW,
            alt_text="Teren reveals a broken Ranger oath emblem beneath his cloak.",
        )
        self.ui.title("TEREN THE FALSE RANGER")
        self.ui.narrate(
            "A Ranger waits beside the next seal-door with his oak-leaf clasp filed smooth. "
            "Teren lowers his bow only when he sees Calenor's broken blade."
        )
        if state.flags.get("part2_memory_complete", False):
            self.ui.narrate(
                "The burning memory places him at the edge of the pursuit, but memory alone is "
                "not proof another witness can carry."
            )
        self.ui.narrate(
            "'I did not betray a child. I betrayed a door. Then the door began to cry.'"
        )

        approaches = [("evidence", "Present the evidence and demand the truth")]
        if state.character.inventory.get("ranger_token", 0):
            approaches.append(("token", "Invoke Calenor's Ranger token"))
        approaches.append(("attack", "Attack before Teren can speak again"))
        approach_choice = self.story_choice(
            "HOW DO YOU ANSWER TEREN?",
            [label for _key, label in approaches],
        )
        if approach_choice is None:
            return False
        fate_choice = self.story_choice(
            "IF TEREN YIELDS, WHAT FATE WILL FOLLOW?",
            ["Spare Teren", "Bind Teren for judgment", "Kill Teren"],
        )
        if fate_choice is None:
            return False

        approach = approaches[approach_choice - 1][0]
        strong_evidence = sum(
            state.flags.get(flag, False)
            for flag in (
                "part2_cipher_archive",
                "part2_erased_statue",
                "part2_testimony_first",
            )
        )
        confession = (approach == "evidence" and strong_evidence >= 2) or (
            approach == "token" and strong_evidence >= 1
        )
        if confession:
            state.flags["part2_teren_confessed"] = True
            self.ui.narrate(
                "The proofs close every retreat. Teren admits he exposed the Eighth household, "
                "believing one sacrificed door would protect the wider Ranger network. Calenor "
                "abandoned the pursuit to rescue the child."
            )
        else:
            if approach == "attack":
                state.character.corruption += 1
            teren = teren_false_ranger()
            self.ui.art(
                artwork.FALSE_RANGER_DUEL_ART,
                Color.RED,
                alt_text="Two Rangers circle in a leaf-blade duel across a star-shaped floor.",
            )
            result = self.combat(
                state,
                [teren],
                CombatConfig(
                    surprise_round=approach == "attack",
                    mara_aid=state.flags.get("part_two_mara_present", False)
                    and state.character.mara_trust >= 0,
                    tobin_aid=state.flags.get("part_two_tobin_present", False),
                    objective="Force Teren to yield at the broken seal-door",
                    location_text=(
                        "Ash drifts between Ranger road-marks while Teren answers every lesson "
                        "Calenor taught you."
                    ),
                ),
            )
            if result == CombatResult.VICTORY:
                self.ui.narrate("Teren's sword leaves his hand. The broken seal-door bars retreat.")
            else:
                state.character.hp = 1
                state.character.corruption += 1
                self.ui.narrate(
                    "Teren brings you down, but falling masonry pins him beside the seal-door. "
                    "Neither of you can pretend the choice of his fate has vanished."
                )

        if fate_choice == 1:
            state.flags["part2_teren_spared"] = True
            self.ui.narrate("Teren lives and must bear witness where silence once served him.")
        elif fate_choice == 2:
            state.flags["part2_teren_bound"] = True
            self.ui.narrate("You bind Teren with his own Ranger cord and keep his testimony intact.")
        else:
            state.flags["part2_teren_killed"] = True
            state.character.corruption += 1
            if state.flags.get("part_two_mara_present", False):
                state.character.mara_trust -= 1
            self.ui.narrate("Teren dies without giving the Shadow any name to carry.")

        state.play_minutes += 10
        state.scene = "part2_calenor_prison"
        return True

    def _calenor_prison(self, state: GameState) -> bool:
        self.ui.clear()
        self.ui.art(
            artwork.CALENOR_PRISON_ART,
            Color.SILVER,
            alt_text="Calenor hangs from one luminous chain above a cracked seal.",
        )
        self.ui.title("CALENOR'S CHAIN")
        self.ui.narrate(
            "Calenor hangs within the vault, alive. One arm has been drawn into a silver spoke, "
            "and every breath keeps the failing seal from opening."
        )
        methods: list[tuple[str, str]] = []
        if state.character.inventory.get("calenor_broken_sword", 0):
            methods.append(("sword", "Use Calenor's broken sword against the chain"))
        methods.append(("star", "Command the star-mark beneath your skin"))
        testimony_count = sum(
            state.flags.get(flag, False)
            for flag in (
                "part2_testimony_first",
                "part2_testimony_second",
                "part2_testimony_third",
            )
        )
        if testimony_count >= 2:
            methods.append(("oath", "Speak the Warden oath carried by two testimonies"))
        method_choice = self.story_choice(
            "HOW DO YOU BREAK THE SPOKE-CHAIN?",
            [label for _key, label in methods],
        )
        if method_choice is None:
            return False
        words_choice = self.story_choice(
            "WHAT ARE YOUR FIRST WORDS TO CALENOR?",
            [
                "Bring him home",
                "Demand why he buried the name",
                "Command him to finish the road",
            ],
        )
        if words_choice is None:
            return False

        method = methods[method_choice - 1][0]
        if method == "sword":
            state.flags["part2_sword_broke_chain"] = True
            self.ui.narrate(
                "The broken sword enters its own oath-groove. The chain opens without taking the "
                "blade; its last duty is not finished."
            )
        elif method == "star":
            state.flags["part2_star_broke_chain"] = True
            state.character.corruption += 1
            self.ui.narrate("The cold mark commands the chain, and the chain obeys too eagerly.")
        else:
            self.ui.narrate("Two remembered voices name the spoke's duty, and iron releases flesh.")

        if words_choice == 1:
            self.ui.narrate("'I came to bring you home.' Calenor opens his eyes.")
        elif words_choice == 2:
            self.ui.narrate("'Why did you bury my name?' Calenor does not look away.")
        else:
            self.ui.narrate("'Finish the road you began.' Calenor bows his head once.")

        state.complete_quest(QUEST_REACH_CALENOR)
        state.play_minutes += 8
        state.scene = "part2_calenor_reunion"
        return True

    def _calenor_reunion(self, state: GameState) -> bool:
        self.ui.clear()
        self.ui.art(
            artwork.CALENOR_REUNION_ART,
            Color.YELLOW,
            alt_text="Calenor and the traveler reach toward each other across a broken chain.",
        )
        self.ui.title("THE TRUTHS CALENOR KEPT")
        self.ui.narrate(
            "Calenor sits beside the opened spoke. There is no time left for another half-truth."
        )
        questions = [
            (
                "hidden_name",
                "Why hide the birth-name?",
                "I hid your name because love was the one lock the Shadow had not learned to pick.",
            ),
            (
                "teren",
                "What did Teren do to the Eighth House?",
                "Teren exposed one household to protect the wider Ranger network. I abandoned "
                "the pursuit and carried you from the fire.",
            ),
            (
                "rider",
                "Why must the Rider make me speak?",
                "The silver star was the last seal. Your willing voice matters because the road "
                "recognizes its lawful bearer; the Eighth Name is its Warden oath-title, not the "
                "hidden name I kept from the Shadow.",
            ),
        ]
        remaining = list(questions)
        while remaining:
            question_choice = self.story_choice(
                "ASK CALENOR THE THREE TRUTHS",
                [label for _key, label, _answer in remaining],
            )
            if question_choice is None:
                return False
            _key, _label, answer = remaining.pop(question_choice - 1)
            self.ui.narrate(answer)
        judgment_choice = self.story_choice(
            "HOW DO YOU JUDGE CALENOR?",
            [
                "Forgive Calenor and ask him to leave with you",
                "Condemn Calenor to answer for the hidden years",
                "Command Calenor to finish the road beside you",
            ],
        )
        if judgment_choice is None:
            return False

        state.flags.pop("part2_calenor_condemned", None)
        state.flags.pop("part2_calenor_commanded", None)
        if judgment_choice == 1:
            state.character.hope += 1
            self.ui.narrate("You forgive the guardian without pretending his silence did no harm.")
        elif judgment_choice == 2:
            state.flags["part2_calenor_condemned"] = True
            self.ui.narrate("Calenor accepts the judgment and offers himself as the final anchor.")
        else:
            state.flags["part2_calenor_commanded"] = True
            self.ui.narrate("Calenor rises under your command. This time, he will finish the road.")

        self.ui.art(
            artwork.THIRD_WARDEN_TESTIMONY_ART,
            Color.SILVER,
            alt_text="A final ghostly Warden offers an eight-pointed seal to the traveler.",
        )
        state.flags["part2_testimony_third"] = True
        if all(
            state.flags.get(flag, False)
            for flag in (
                "part2_testimony_first",
                "part2_testimony_second",
                "part2_testimony_third",
            )
        ):
            state.complete_quest(QUEST_NAMES_LOST)
        state.complete_quest(QUEST_LAST_SEAL)
        state.add_quest(QUEST_EIGHTH_NAME)
        state.play_minutes += 10
        state.scene = "part2_last_seal"
        return True

    def _last_seal(self, state: GameState) -> bool:
        self.ui.clear()
        self.ui.art(
            artwork.LAST_SEAL_VAULT_ART,
            Color.SILVER,
            alt_text="Eight radial doorways surround a pedestal in a vast circular vault.",
        )
        self.ui.title("THE LAST SEAL")
        self.ui.narrate("The vault does not open. It listens.")
        ritual_choice = self.story_choice(
            "SET THE RITUAL",
            [
                "Calenor anchors the failing spoke",
                "Divide among willing voices",
                "Prepare the vault for collapse",
            ],
        )
        if ritual_choice is None:
            return False
        star_choice = self.story_choice(
            "THE STAR WHISPERS BENEATH YOUR SKIN",
            ["Reject the star's bargain", "Bargain for enough power to hold the road"],
        )
        if star_choice is None:
            return False
        state.flags.pop("part2_ritual_collapse_prepared", None)
        if ritual_choice == 3:
            state.flags["part2_ritual_collapse_prepared"] = True
        if star_choice == 1:
            state.flags["part2_star_rejected"] = True
            state.character.hope += 1
            self.ui.narrate("You reject the cold voice. The willing company answers in its place.")
        else:
            state.flags["part2_star_bargain"] = True
            state.character.corruption += 1
            self.ui.narrate("You bargain with the mark, and it remembers the shape of your consent.")
        if state.flags.get("part_two_mara_present", False) and state.flags.get(
            "part_two_tobin_present", False
        ):
            self.ui.art(
                artwork.EIGHT_SPOKED_RITUAL_ART,
                Color.SILVER,
                alt_text="An eight-spoked ritual floor holds four figures around its center.",
            )
        state.add_quest(QUEST_DEAD_ROAD_FATE)
        state.play_minutes += 6
        state.scene = "part2_final_battle"
        return True

    def _final_battle(self, state: GameState) -> bool:
        self.ui.clear()
        self.ui.art(
            artwork.RIDER_FINAL_ENTRANCE_ART,
            Color.MAGENTA,
            alt_text="A towering Black Rider crosses a shattered circular vault doorway.",
        )
        self.ui.title("THE BLACK RIDER AT THE LAST SEAL")
        self.ui.narrate(
            "The Rider enters the eight-spoked vault without breaking the door. Its hood turns "
            "toward the cold mark beneath your skin."
        )
        tactic_choice = self.story_choice(
            "WHERE DO YOU STAND FOR SIX ROUNDS?",
            [
                "Hold the center while the oath is spoken",
                "Guard the ritual and every willing voice",
                "Challenge the Rider and draw it from the spokes",
            ],
        )
        if tactic_choice is None:
            return False

        state.flags.pop("part2_final_ritual_guarded", None)
        if tactic_choice == 2:
            state.flags["part2_final_ritual_guarded"] = True
        reduction = 0
        if state.flags.get("part2_calenor_commanded", False):
            reduction += 1
        if tactic_choice == 3:
            reduction += 2
            state.character.corruption += 1
        if state.flags.get("part2_flood_wards_preserved", False) or state.flags.get(
            "part2_drowned_mile_preserved", False
        ) or state.flags.get("part2_drowned_branch_collapsed", False):
            reduction += 1

        rider = black_rider_echo(final=True)
        rider.attack_min = max(1, rider.attack_min - reduction)
        rider.attack_max = max(1, rider.attack_max - reduction)
        if state.flags.get("part_two_mara_present", False) and state.flags.get(
            "part_two_tobin_present", False
        ):
            self.ui.art(
                artwork.FINAL_SEAL_BATTLE_ART,
                Color.RED,
                alt_text=(
                    "A towering Rider presses against three defenders holding a blazing seal circle."
                ),
            )
        result = self.combat(
            state,
            [rider],
            CombatConfig(
                surprise_round=False,
                mara_aid=state.flags.get("part_two_mara_present", False)
                and state.character.mara_trust >= 0,
                tobin_aid=state.flags.get("part_two_tobin_present", False),
                objective="Survive six rounds while the Last Seal is remade",
                max_rounds=6,
                objective_enemy_invulnerable=True,
                location_text=(
                    "Eight silver spokes burn beneath the company while the Rider reaches for "
                    "the one voice it cannot command."
                ),
            ),
        )
        if result == CombatResult.VICTORY:
            self.ui.narrate("The Rider takes one step backward. It is not wounded. It is denied.")
        else:
            state.character.hp = 1
            cost_flags = (
                "part2_teren_took_spoke",
                "part2_calenor_rebound",
            )
            for flag in cost_flags:
                state.flags.pop(flag, None)
            if state.flags.get("part2_sword_broke_chain", False) and state.character.remove_item(
                "calenor_broken_sword"
            ):
                self.ui.narrate(
                    "Calenor's broken sword takes the empty spoke and shatters. Calenor remains free."
                )
            elif state.flags.get("part2_teren_spared", False):
                state.flags["part2_teren_took_spoke"] = True
                self.ui.narrate("Teren takes the empty spoke, paying the witness-debt with his body.")
            elif state.flags.get("part2_final_ritual_guarded", False):
                self.ui.narrate(
                    "Your guard keeps every companion clear. The empty spoke closes through your "
                    "shadow and leaves a silver scar."
                )
            else:
                state.flags["part2_calenor_rebound"] = True
                self.ui.narrate(
                    "Calenor is drawn back into the spoke. The company survives, but his chain closes again."
                )

        state.play_minutes += 8
        state.scene = "part2_seal_choice"
        return True

    def _seal_choice(self, state: GameState) -> bool:
        self.ui.clear()
        self.ui.title("THE FATE OF THE DEAD ROAD")
        options: list[tuple[str, str]] = [
            ("renew", "Renew the ancient seal"),
        ]
        if _can_remake_seal(state):
            options.append(("remake", "Remake the seal as a freely shared oath"))
        options.extend(
            [
                ("destroy", "Destroy the Dead Road and bury every spoke"),
                ("claim", "Claim the road in your own voice"),
            ]
        )
        choice = self.story_choice(
            "WHAT BECOMES OF THE LAST SEAL?",
            [label for _key, label in options],
        )
        if choice is None:
            return False
        seal_choice = options[choice - 1][0]
        ending = part_two_ending(state, seal_choice)

        if ending == "shadows_name":
            self.ui.art(
                artwork.SHADOWS_NAME_ENDING_ART,
                Color.YELLOW,
                alt_text=(
                    "A traveler raises a blackened star as branching roads ignite beneath a "
                    "hooded Rider."
                ),
            )
        elif state.flags.get("part_two_mara_present", False) and state.flags.get(
            "part_two_tobin_present", False
        ):
            if ending == "living_road":
                self.ui.art(
                    artwork.LIVING_ROAD_ENDING_ART,
                    Color.YELLOW,
                    alt_text=(
                        "Calenor and his companions walk toward a bright road beneath eight stars."
                    ),
                )
            elif ending == "last_warden":
                self.ui.art(
                    artwork.LAST_WARDEN_ENDING_ART,
                    Color.YELLOW,
                    alt_text=(
                        "A lone seated Ranger holds a sword before a closed seal as others depart."
                    ),
                )
            else:
                self.ui.art(
                    artwork.ROAD_IN_RUIN_ENDING_ART,
                    Color.YELLOW,
                    alt_text=(
                        "An ancient bridge collapses behind escaping companions while the Rider "
                        "remains across the gulf."
                    ),
                )

        state.flags[f"part2_seal_choice_{seal_choice}"] = True
        if ending == "living_road":
            state.flags["part2_calenor_escaped"] = True
            self.ui.narrate("One voice cannot own a road.")
            self.ui.narrate(
                "The oath passes freely among the company. Calenor leaves the opened spoke alive."
            )
        elif ending == "last_warden":
            if state.flags.get("part2_calenor_rebound", False):
                reason = "because the Rider's final blow closed his chain again"
            elif state.flags.get("part2_calenor_condemned", False):
                state.flags["part2_calenor_remained"] = True
                reason = "as the sentence he accepted"
            elif state.flags.get("part2_calenor_commanded", False):
                state.flags["part2_calenor_remained"] = True
                reason = "under the final duty you commanded"
            else:
                state.flags["part2_calenor_remained"] = True
                reason = "willingly, as his final duty"
            self.ui.narrate(f"Calenor remains within the renewed spoke {reason}.")
        elif ending == "road_in_ruin":
            if state.flags.get("part2_teren_spared", False) and not state.flags.get(
                "part2_calenor_condemned", False
            ) and not state.flags.get("part2_teren_took_spoke", False):
                state.flags["part2_teren_stayed_to_collapse"] = True
                self.ui.narrate("Teren stays to break the last support while Calenor leads you out.")
            elif state.flags.get("part2_calenor_rebound", False) or state.flags.get(
                "part2_teren_took_spoke", False
            ):
                state.flags["part2_company_collapsed_road"] = True
                occupied_spoke = (
                    "Calenor's closed chain"
                    if state.flags.get("part2_calenor_rebound", False)
                    else "the spoke Teren took"
                )
                if state.flags.get("part2_ritual_collapse_prepared", False):
                    self.ui.narrate(
                        "The company strikes the prepared fault-lines and brings the road down around "
                        f"{occupied_spoke}."
                    )
                else:
                    self.ui.narrate(
                        "The company breaks the vault supports and collapses the road around "
                        f"{occupied_spoke}."
                    )
            else:
                state.flags["part2_calenor_collapsed_road"] = True
                self.ui.narrate("Calenor triggers the collapse and seals the ruined road behind you.")
        else:
            self.ui.narrate(
                "Only part of the Eighth Name crosses the vault. It is enough for the Shadow to "
                "find the buried network, but the whole oath remains unspoken."
            )

        state.complete_quest(QUEST_DEAD_ROAD_FATE)
        if ending == "shadows_name":
            if QUEST_EIGHTH_NAME in state.quests:
                state.quests.remove(QUEST_EIGHTH_NAME)
        else:
            state.complete_quest(QUEST_EIGHTH_NAME)
        for optional_quest in (QUEST_NAMES_LOST, QUEST_PRISONERS_ASH):
            if optional_quest in state.quests:
                state.quests.remove(optional_quest)
        state.add_journal(
            "An underground map revealed another sealed spoke beneath ruined Fornost."
        )
        state.play_minutes += 5
        state.ending = ending
        state.scene = "complete"
        self.ui.art(
            artwork.FORNOST_MAP_CLIFFHANGER_ART,
            Color.YELLOW,
            alt_text=(
                "A branching underground map points to a sealed node beneath ruined Fornost."
            ),
        )
        return True


def part_two_ending(state: GameState, seal_choice: str) -> str:
    character = state.character
    shadow_dominant = character.corruption >= max(4, character.hope + 2)
    if seal_choice == "claim" or shadow_dominant:
        return "shadows_name"
    if seal_choice == "remake":
        return "living_road"
    if seal_choice == "destroy":
        return "road_in_ruin"
    return "last_warden"


def part_two_ending_breakdown(state: GameState) -> list[tuple[str, str]]:
    flags = state.flags
    testimonies = sum(
        flags.get(flag, False)
        for flag in (
            "part2_testimony_first",
            "part2_testimony_second",
            "part2_testimony_third",
        )
    )
    if state.ending == "shadows_name":
        name = "Part of the Warden oath reached the Shadow; the full Eighth Name stayed unspoken."
    elif testimonies == 3:
        name = "All three Warden testimonies were remembered, and the Eighth Name remained guarded."
    else:
        name = f"{testimonies} of three Warden testimonies were recovered before the seal was decided."

    if flags.get("part2_mara_left", False):
        mara = "Mara left at the burned refuge when trust and shared purpose failed."
    elif flags.get("part_two_mara_present", False):
        mara = "Mara reached the Last Seal and carried her own voice into its judgment."
    else:
        mara = "Mara was not present on the Dead Road."

    if flags.get("part_two_tobin_present", False):
        if flags.get("part_two_neds_watch_continues", False):
            watch = "Tobin carried Ned's watch through the Dead Road and survived the Last Seal."
        else:
            watch = "Tobin brought Bree's lantern through the Dead Road and survived the Last Seal."
    elif flags.get("part_two_ned_safe", False):
        watch = "Tobin remained above with Ned; both were beyond the Last Seal's cost."
    else:
        watch = "Tobin did not descend, and Ned's lost watch remained with the road above."

    if flags.get("part2_teren_stayed_to_collapse", False):
        guardians = "Teren stayed to collapse the road; Calenor escaped."
    elif flags.get("part2_calenor_collapsed_road", False):
        guardians = "Calenor stayed to collapse the road behind the company."
    elif flags.get("part2_calenor_rebound", False):
        guardians = "The Rider's final blow rebound Calenor to the old duty beneath the hills."
        if flags.get("part2_company_collapsed_road", False):
            guardians += " The company collapsed the road around his bound spoke."
    elif flags.get("part2_calenor_remained", False):
        guardians = "Calenor remains with the old duty beneath the hills."
    elif flags.get("part2_calenor_escaped", False):
        guardians = "Calenor left the spoke alive."
    else:
        guardians = "Calenor survived the ritual."

    if not flags.get("part2_teren_stayed_to_collapse", False):
        if flags.get("part2_teren_took_spoke", False):
            guardians += " Teren took the empty spoke."
        elif flags.get("part2_teren_bound", False):
            guardians += " Teren remains bound for judgment."
        elif flags.get("part2_teren_spared", False):
            guardians += " Teren survived as a witness."
        elif flags.get("part2_teren_killed", False):
            guardians += " Teren died at the broken seal-door."
        elif flags.get("part2_teren_confessed", False):
            guardians += " Teren's confession entered the witness record."

    if state.ending == "shadows_name":
        attempted_choice = next(
            (
                wording
                for flag, wording in (
                    ("part2_seal_choice_claim", "control the road"),
                    ("part2_seal_choice_destroy", "destroy the road"),
                    ("part2_seal_choice_remake", "remake the seal"),
                )
                if flags.get(flag, False)
            ),
            "renew the seal",
        )
        road_text = (
            f"Corruption overrode the attempt to {attempted_choice} and opened part of its "
            "buried network to the Shadow."
        )
    else:
        road_text = {
            "living_road": "The seal became a living oath shared freely by its witnesses.",
            "last_warden": "The ancient seal was renewed under one final guardian.",
            "road_in_ruin": "The Dead Road was destroyed to deny its buried network to the Rider.",
        }.get(state.ending, "The Last Seal waits for its final judgment.")
    return [
        ("The Eighth Name", name),
        ("Mara", mara),
        ("Tobin and Ned", watch),
        ("Calenor and Teren", guardians),
        ("The Dead Road", road_text),
    ]


def _can_remake_seal(state: GameState) -> bool:
    flags = state.flags
    all_testimonies = all(
        flags.get(flag, False)
        for flag in (
            "part2_testimony_first",
            "part2_testimony_second",
            "part2_testimony_third",
        )
    )
    strong_companion = (
        flags.get("part_two_mara_present", False) and state.character.mara_trust >= 2
    ) or (
        flags.get("part_two_tobin_present", False) and state.character.tobin_trust >= 2
    )
    return bool(
        all_testimonies
        and flags.get("part2_prisoners_rescued", False)
        and state.character.hope >= state.character.corruption
        and strong_companion
        and not flags.get("part2_calenor_rebound", False)
    )


def begin_part_two(state: GameState) -> None:
    if state.flags.get("part_two_started"):
        return
    if state.ending not in PART_ONE_ENDINGS or state.scene != "complete":
        raise ValueError("Part II can begin only from a completed Part I journey")

    for quest in LEGACY_PART_ONE_QUESTS:
        state.complete_quest(quest)
    state.character.remove_item("star_key")
    state.character.add_item("calenor_broken_sword")
    state.character.hp = max(state.character.hp, (state.character.max_hp + 1) // 2)
    state.character.focus = state.character.max_focus
    state.add_quest("Descend the Dead Road and reach Calenor")
    state.add_quest("Learn why the silver star is the last seal")
    state.ending = None
    state.chapter = 2
    state.scene = PART_TWO_FIRST_SCENE
    state.flags["part_two_started"] = True
