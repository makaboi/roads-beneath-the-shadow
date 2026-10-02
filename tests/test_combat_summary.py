"""Persistent compact combat results without a graphical dependency."""

import unittest

from roads_beneath_shadow.combat_view import (
    CombatActionView, CombatEnemyView, CombatFeedback, CombatPlayerView,
    CombatSnapshot, CombatTurnSummary,
)


def action(identifier, label=None, enabled=True):
    return CombatActionView(identifier, label or identifier.title(), 0, enabled, "", "")


def snapshot(name="Ash-Hand Sapper"):
    player = CombatPlayerView("Mira", "healers_apprentice", 17, 24, 1, 3, None, "Unarmed", None, "No armor", 0, ())
    enemy = CombatEnemyView("enemy_0", name, "saboteur", 12, 24, 0, 1, "guard", "Guard", "raises Armor", True, 0, 0, "setup", (), True)
    return CombatSnapshot(2, "active", "Ranger", player, (enemy,), "enemy_0", (), (), None, None, False)


class CombatSummaryTests(unittest.TestCase):
    def test_mara_impact_survives_later_bleeding_and_incoming_hits(self):
        log = CombatTurnSummary().begin_action(action("mara", "Mara: Crossing Blades (-1 Focus)"))
        for event in (
            CombatFeedback("damage", "mara", "enemy_0", 8, "Different transcript wording"),
            CombatFeedback("interrupt", "player", "enemy_0", 0, ""),
            CombatFeedback("damage", "enemy_0", "enemy_0", 1, "Enemy Bleeding"),
            CombatFeedback("damage", "enemy_1", "player", 4, "An attack"),
            CombatFeedback("damage", "player", "player", 1, "Player Bleeding"),
        ):
            log = log.append(event)
        first, second = log.lines(snapshot(), max_columns=50)
        self.assertEqual(first, "Mara · −8 damage · interrupted · Ash-Hand Sapper")
        self.assertEqual(second, "Incoming −4 Health · Bleeding −1")

    def test_inspect_target_and_disabled_actions_preserve_paid_result(self):
        log = CombatTurnSummary().begin_action(action("attack")).append(CombatFeedback("damage", "player", "enemy_0", 6, ""))
        for command in (action("inspect"), action("target"), action("power", enabled=False)):
            self.assertIs(log.begin_action(command), log)
        self.assertIs(log.append(CombatFeedback("inspect", "player", "enemy_0", 0, "Inspection")), log)
        self.assertIs(log.append(CombatFeedback("notice", "player", "player", 0, "Cannot do that")), log)
        self.assertEqual(log.lines(snapshot())[0], "Attack · −6 damage · Ash-Hand Sapper")

    def test_cancelled_remedy_preserves_result_until_a_new_real_action(self):
        previous = CombatTurnSummary().begin_action(action("attack")).append(CombatFeedback("damage", "player", "enemy_0", 6, ""))
        canceled = previous.begin_action(action("item"))
        self.assertEqual(canceled.lines(snapshot()), previous.lines(snapshot()))
        self.assertEqual(canceled.append(CombatFeedback("notice", "player", "player", 0, "Canceled")).lines(snapshot()), previous.lines(snapshot()))
        next_turn = canceled.begin_action(action("defend")).append(CombatFeedback("defend", "player", "player", 1, "Guard"))
        self.assertEqual(next_turn.lines(), ("Defend · guarded · +1 Focus", "No incoming Health damage"))
        self.assertEqual(previous.lines(snapshot())[0], "Attack · −6 damage · Ash-Hand Sapper", "the summary is immutable")

    def test_healing_guard_and_enemy_preparation_are_explicit(self):
        log = CombatTurnSummary().begin_action(action("origin", "Field Remedy (-1 Focus)"))
        log = log.append(CombatFeedback("heal", "player", "player", 6, "Healed"))
        log = log.append(CombatFeedback("info", "enemy_0", "enemy_0", 0, "Enemy took aim"))
        self.assertEqual(log.lines(), ("Field Remedy · +6 Health", "No incoming Health damage · enemies prepared"))
        guard = CombatTurnSummary().begin_action(action("tobin_guard")).append(CombatFeedback("defend", "tobin", "player", 0, ""))
        guard = guard.append(CombatFeedback("evade", "enemy_0", "player", 0, ""))
        guard = guard.append(CombatFeedback("damage", "enemy_1", "player", 0, ""))
        self.assertEqual(guard.lines(), ("Tobin guard · guarded", "Incoming blocked · 1 evaded"))

    def test_flee_success_and_failure_do_not_report_an_invented_hit(self):
        attempt = CombatTurnSummary().begin_action(action("flee"))
        escaped = attempt.append(CombatFeedback("escape", "player", "player", 0, ""))
        self.assertEqual(escaped.lines(), ("Escape · escaped", "No enemy retaliation"))
        failed = attempt.append(CombatFeedback("damage", "enemy_0", "player", 3, ""))
        self.assertEqual(failed.lines(), ("Escape · escape blocked", "Incoming −3 Health"))

    def test_enemy_bleeding_does_not_count_as_incoming_player_damage(self):
        log = CombatTurnSummary().begin_action(action("mara"))
        log = log.append(CombatFeedback("damage", "mara", "enemy_0", 8, ""))
        log = log.append(CombatFeedback("damage", "enemy_0", "enemy_0", 1, ""))
        self.assertEqual(log.lines(), ("Mara · −8 damage", "No incoming Health damage"))

    def test_menace_focus_loss_and_bleeding_are_not_confused_with_strikes(self):
        log = CombatTurnSummary().begin_action(action("defend"))
        log = log.append(CombatFeedback("defend", "player", "player", 0, ""))
        log = log.append(CombatFeedback("info", "enemy_0", "player", 1, "Shadow mark"))
        log = log.append(CombatFeedback("damage", "player", "player", 1, "Bleeding"))
        self.assertEqual(log.lines()[1], "Bleeding −1 Health · −1 Focus")

    def test_zero_focus_shadow_mark_is_not_reported_as_enemy_preparation(self):
        log = CombatTurnSummary().begin_action(action("defend"))
        log = log.append(CombatFeedback("defend", "player", "player", 0, ""))
        log = log.append(CombatFeedback("info", "enemy_0", "player", 0, "Shadow mark"))
        self.assertEqual(log.lines()[1], "No incoming Health damage · shadow mark")
        focused = CombatTurnSummary().begin_action(action("defend"))
        focused = focused.append(CombatFeedback("info", "enemy_0", "player", 1, "Shadow mark"))
        self.assertEqual(focused.lines()[1], "Incoming −1 Focus")

    def test_zero_heal_kill_and_defeat_remain_meaningful(self):
        remedy = CombatTurnSummary().begin_action(action("item")).append(CombatFeedback("heal", "player", "player", 0, "Cleanse"))
        self.assertEqual(remedy.lines()[0], "Remedy · remedy applied")
        killing = CombatTurnSummary().begin_action(action("power")).append(CombatFeedback("damage", "player", "enemy_0", 12, ""))
        killing = killing.append(CombatFeedback("fallen", "player", "enemy_0", 0, ""))
        self.assertIn("foe fallen", killing.lines()[0])
        defeated = killing.append(CombatFeedback("damage", "enemy_1", "player", 9, ""))
        defeated = defeated.append(CombatFeedback("fallen", "enemy_1", "player", 0, ""))
        self.assertEqual(defeated.lines()[1], "Incoming −9 Health · fallen")

    def test_long_target_names_and_feedback_history_have_fixed_bounds(self):
        log = CombatTurnSummary().begin_action(action("attack"))
        log = log.append(CombatFeedback("damage", "player", "enemy_0", 6, ""))
        first, second = log.lines(snapshot("Teren the False Ranger and keeper of the drowned gate"), max_columns=38)
        self.assertTrue(first.startswith("Attack · −6 damage"))
        self.assertTrue(first.endswith("…"))
        self.assertLessEqual(len(first), 38)
        self.assertLessEqual(len(second), 38)
        for _ in range(60):
            log = log.append(CombatFeedback("info", "enemy_0", "enemy_0", 0, ""))
        self.assertEqual(len(log.feedback), 24)

    def test_initial_surprise_uses_its_actor_without_a_selected_command(self):
        log = CombatTurnSummary().append(CombatFeedback("damage", "player", "enemy_0", 5, "Surprise"))
        self.assertEqual(log.lines(snapshot())[0], "Opening strike · −5 damage · Ash-Hand Sapper")

    def test_boss_phase_is_explicit_without_changing_the_damage_totals(self):
        log = CombatTurnSummary().begin_action(action("attack"))
        log = log.append(CombatFeedback("damage", "player", "enemy_0", 6, ""))
        log = log.append(CombatFeedback("phase", "enemy_0", "enemy_0", 2, "Ghorak enters Phase II."))
        self.assertEqual(log.lines()[0], "Attack · −6 damage · Phase II")
        self.assertEqual(log.lines()[1], "No incoming Health damage")


if __name__ == "__main__":
    unittest.main()
