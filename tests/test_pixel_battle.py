"""Real SDL coverage for the battlefield's interactions and motion settings."""

from dataclasses import replace
import gc
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from roads_beneath_shadow.combat_view import (
    CombatActionView, CombatCompanionView, CombatEnemyView, CombatFeedback, CombatPlayerView,
    CombatSnapshot, CombatStatusView,
)
from roads_beneath_shadow.pixel_battle import BattleView, _wrapped


def battle_snapshot(count=3):
    bleeding = CombatStatusView("bleeding", "Bleeding", 2, "Lose 1 Health at the start of each turn.")
    player = CombatPlayerView("Mira", "North Road Scout", 17, 24, 3, 4, "sword", "Ranger's sword", "leather", "Leather coat", 1, (bleeding,))
    names = ("Orc Captain", "Ash-Hand Sapper", "Ash-Hand Archer")
    archetypes = ("commander", "saboteur", "archer")
    enemies = tuple(
        CombatEnemyView(f"enemy_{index}", names[index], archetypes[index], 12 - index * 3, 16 - index * 3, 1 if index == 0 else 0, 1,
                        "heavy", "Heavy Blow", "a crushing attack; Defend or interrupt it", True, 4, 8, "4–8 incoming damage", (), index == 0)
        for index in range(count)
    )
    actions = (CombatActionView("attack", "Attack", 0, True, "", "Strike the target."),
               CombatActionView("power", "Power Attack", 1, True, "", "Disrupt the target."),
               CombatActionView("defend", "Defend", 0, True, "", "Halve incoming physical hits."),
               CombatActionView("mara", "Mara: Crossing Blades", 1, True, "", "Disrupt the target."))
    return CombatSnapshot(2, "active", "Ranger", player, enemies, "enemy_0", actions,
                          (CombatCompanionView("mara", "Mara", 3, True), CombatCompanionView("tobin", "Tobin", 2, True)),
                          "Protect the prisoners and keep the bridge intact.", None, False)


class BattleImportTests(unittest.TestCase):
    def test_import_is_safe_without_a_graphical_display(self):
        code = "import sys; import roads_beneath_shadow.pixel_battle; assert 'pygame' not in sys.modules"
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is required for battlefield SDL tests")
class BattleSDLTests(unittest.TestCase):
    def setUp(self):
        import pygame
        self.pg = pygame
        pygame.init()
        self.surface = pygame.Surface((1000, 760))
        self.view = BattleView(pygame)
        self.snapshot = battle_snapshot()
        self.view.set_snapshot(self.snapshot)
        self.canvas = pygame.Rect(24, 100, 620, 480)
        self.view.draw(self.surface, self.canvas, 400)

    def tearDown(self):
        # Native fonts must be released while SDL_ttf is still initialized.
        # Keeping the renderer alive across pygame.quit leaks font allocations
        # in repeated headless window tests, unlike the game's single window.
        self.view = None
        self.surface = None
        gc.collect()
        self.pg.quit()

    def click(self, pos, button=1):
        return self.view.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=button, pos=pos))

    def test_selecting_enemy_cards_returns_stable_engine_ids(self):
        for rect, enemy_id in self.view.enemy_hits:
            self.assertEqual(self.click(rect.center), (True, enemy_id))
        self.assertEqual(self.snapshot.target_id, "enemy_0", "the renderer must leave selection to the engine")

    def test_selecting_the_visible_enemy_sprite_returns_the_same_target(self):
        for rect, enemy_id in self.view.sprite_hits:
            self.assertEqual(self.click(rect.center), (True, enemy_id))

    def test_fallen_enemy_stays_visible_but_cannot_be_targeted(self):
        enemies = (replace(self.snapshot.enemies[0], hp=0), *self.snapshot.enemies[1:])
        self.view.set_snapshot(replace(self.snapshot, enemies=enemies, target_id="enemy_1"))
        self.view.draw(self.surface, self.canvas)
        self.assertEqual(len(self.view.enemy_hits), 3)
        self.assertEqual(self.click(self.view.enemy_hits[0][0].center), (True, None))
        self.assertEqual(self.click(self.view.enemy_hits[1][0].center), (True, "enemy_1"))

    def test_result_screen_cannot_send_a_new_combat_target(self):
        self.view.set_snapshot(replace(self.snapshot, phase="victory"))
        self.view.draw(self.surface, self.canvas)
        self.assertEqual(self.click(self.view.enemy_hits[0][0].center), (True, None))

    def test_background_and_right_mouse_button_do_not_select_targets(self):
        self.assertEqual(self.click((3, 3)), (False, None))
        self.assertEqual(self.click(self.view.enemy_hits[0][0].center, button=3), (False, None))

    def test_hover_has_no_combat_side_effect(self):
        event = self.pg.event.Event(self.pg.MOUSEMOTION, pos=self.view.enemy_hits[1][0].center, rel=(0, 0), buttons=(0, 0, 0))
        self.assertEqual(self.view.handle_event(event), (False, None))
        self.assertEqual(self.view.hovered_id, "enemy_1")
        self.assertEqual(self.snapshot.target_id, "enemy_0")

    def test_party_name_ink_stays_separate_and_inside_the_actual_arena(self):
        self.surface = self.pg.Surface((2400, 1500))
        for canvas in ((24, 100, 418, 322), (24, 100, 680, 496), (24, 100, 1488, 842), (24, 100, 2256, 1310)):
            for preference in ("standard", "larger"):
                for count in (0, 1, 2):
                    for name in ("Zoë Native", "Éowen — 夜道の旅人星明かり", "É" + "W" * 23):
                        with self.subTest(canvas=canvas, preference=preference, companions=count, name=name):
                            baseline = replace(self.snapshot, companions=self.snapshot.companions[:count],
                                               objective="Read their intent. Choose your target. Survive the road.")
                            self.view.set_snapshot(baseline)
                            self.view.draw(self.surface, canvas, text_size=preference)
                            anchors = dict(self.view.actor_positions)
                            targets = [(rect.copy(), target) for rect, target in self.view.enemy_hits]
                            updated = replace(baseline, player=replace(baseline.player, name=name))
                            self.view.set_snapshot(updated)
                            with patch.object(self.view, "_text", wraps=self.view._text) as text:
                                self.view.draw(self.surface, canvas, text_size=preference)
                            labels = []
                            for call in text.call_args_list:
                                value, position = call.args[1:3]
                                font = call.kwargs.get("font")
                                party = font is self.view.party_font and any(value.startswith(ally.name[:1]) for ally in updated.companions)
                                hero = font is self.view.small_font and value.startswith(name[:1])
                                if party or hero:
                                    glyph = font.render(value, False, call.args[3])
                                    ink = glyph.get_bounding_rect().move(position)
                                    self.assertTrue(self.view._arena_rect.contains(ink), (value, ink, self.view._arena_rect))
                                    self.assertFalse(any(ink.colliderect(previous) for previous in labels), (value, ink, labels))
                                    labels.append(ink)
                            self.assertEqual(len(labels), count + 1, "a visible party name was lost")
                            self.assertEqual(self.view.actor_positions, anchors, "name fitting moved the formation")
                            self.assertEqual(self.view.enemy_hits, targets, "name fitting changed target identity")
                            self.assertIs(self.view.snapshot, updated)
                            self.assertEqual(updated.player.name, name)
                            self.assertEqual(self.view._party_help("player").splitlines()[0], name)

    def test_compact_names_elide_only_the_canvas_and_leave_short_companion_names_readable(self):
        name = "Éowen of the Northern Stars"
        snapshot = replace(self.snapshot, player=replace(self.snapshot.player, name=name),
                           objective="Read their intent. Choose your target. Survive the road.")
        self.view.set_snapshot(snapshot)
        with patch.object(self.view, "_text", wraps=self.view._text) as draw:
            self.view.draw(self.surface, (24, 100, 418, 322), text_size="larger")
        labels = [call.args[1] for call in draw.call_args_list]
        self.assertIn("Mara", labels)
        self.assertIn("Tobin", labels)
        self.assertTrue(any(label.startswith("É") and label.endswith("…") for label in labels), labels)
        self.assertEqual(snapshot.player.name, name)
        self.assertIn(name, self.view._party_help("player"))

    def test_focus_loss_clears_enemy_and_party_hover_without_changing_target(self):
        rect = next(rect for rect, actor_id in self.view.party_hits if actor_id == "mara")
        self.view.handle_event(self.pg.event.Event(self.pg.MOUSEMOTION, pos=rect.center, rel=(0, 0), buttons=(0, 0, 0)))
        self.assertEqual(self.view.hovered_actor_id, "mara")
        self.view.handle_event(self.pg.event.Event(self.pg.WINDOWFOCUSLOST))
        self.assertIsNone(self.view.hovered_actor_id)
        self.assertIsNone(self.view.hovered_id)
        self.assertIsNone(self.view._mouse)
        self.assertEqual(self.view.snapshot.target_id, "enemy_0")

    def test_one_to_three_enemy_cards_fit_at_supported_window_sizes(self):
        for size in ((419, 290), (480, 420), (620, 480), (820, 530)):
            for count in (1, 2, 3):
                canvas = self.pg.Rect(10, 15, *size)
                self.view.set_snapshot(battle_snapshot(count))
                result = self.view.draw(self.surface, canvas)
                self.assertEqual(result, canvas)
                cards = [rect for rect, _ in self.view.enemy_hits]
                self.assertEqual(len(cards), count)
                self.assertTrue(all(canvas.contains(rect) for rect in cards))
                self.assertTrue(all(not first.colliderect(second) for first, second in zip(cards, cards[1:])))

    def test_high_resolution_cards_targets_and_reduced_motion_remain_readable(self):
        surface = self.pg.Surface((3840, 2160))
        guarded = CombatStatusView("guarded", "Guarded", 2, "+2 Armor until struck.")
        for size, hero_height in (((1488, 842), 144), ((2256, 1310), 192)):
            canvas = self.pg.Rect(22, 87, *size)
            for preference in ("standard", "large", "larger"):
                snapshot = battle_snapshot(3)
                snapshot = replace(snapshot, enemies=tuple(replace(enemy, statuses=(guarded,)) for enemy in snapshot.enemies))
                self.view.set_snapshot(snapshot)
                self.view.update(0, reduced_motion=True)
                self.view.draw(surface, canvas, 0, text_size=preference)
                self.assertGreaterEqual(self.view.actor_rects["player"].height, hero_height)
                self.assertGreaterEqual(self.view.small_font.get_height(), 16)
                self.assertTrue(self.view._arena_rect.contains(self.view.target_marker_rect))
                self.assertTrue(all(self.view._arena_rect.contains(rect) for rect, _ in self.view.party_hits))
                for card, enemy_id in self.view.enemy_hits:
                    self.assertTrue(canvas.contains(card))
                    self.assertEqual(self.click(card.center), (True, enemy_id))
                for sprite, enemy_id in self.view.sprite_hits:
                    self.assertTrue(self.view._arena_rect.contains(sprite))
                    self.assertEqual(self.click(sprite.center), (True, enemy_id))
                first = self.pg.image.tobytes(surface, "RGB")
                self.view.draw(surface, canvas, 1700, text_size=preference)
                self.assertEqual(first, self.pg.image.tobytes(surface, "RGB"))
                rect, enemy_id = self.view.enemy_hits[0]
                self.view.handle_event(self.pg.event.Event(self.pg.MOUSEMOTION, pos=rect.center, rel=(0, 0), buttons=(0, 0, 0)))
                self.view.draw(surface, canvas, 1700, text_size=preference)
                self.assertEqual(self.view.hovered_id, enemy_id)
                self.assertTrue(canvas.contains(self.view.tooltip_rect))
                self.view.handle_event(self.pg.event.Event(self.pg.WINDOWLEAVE))

    def test_card_tooltip_after_target_click_preserves_visible_health_and_armor(self):
        surface = self.pg.Surface((3840, 2160))
        canvases = ((418, 330), (680, 496), (1488, 842), (2256, 1310))
        for size in canvases:
            for preference in ("standard", "large", "larger"):
                for count in (1, 2, 3):
                    with self.subTest(canvas=size, preference=preference, enemies=count):
                        snapshot = battle_snapshot(count)
                        self.view.handle_event(self.pg.event.Event(self.pg.WINDOWLEAVE))
                        self.view.set_snapshot(snapshot)
                        self.view.update(0, reduced_motion=True)
                        canvas = self.pg.Rect(22, 87, *size)
                        self.view.draw(surface, canvas, text_size=preference)
                        card, target_id = self.view.enemy_hits[-1]
                        intent = self.view._intent_help(snapshot.enemies[-1])
                        hit = next(rect for rect, text in self.view.tooltip_hits if text == intent and card.contains(rect))
                        pos = (hit.x + 3, hit.y + 3)
                        self.assertEqual(self.click(pos), (True, target_id))
                        self.assertEqual(self.view.snapshot, snapshot)
                        # The engine owns free target selection; publish its
                        # resulting immutable view before recording stats.
                        selected = replace(snapshot, target_id=target_id)
                        self.view.set_snapshot(selected)
                        self.view.draw(surface, canvas, text_size=preference)
                        before = [self.pg.image.tobytes(surface.subsurface(rect), "RGB") for rect in self.view.enemy_stat_rects]
                        rendered = []
                        original = self.view._text

                        def record(surface, text, pos, color=(239, 225, 188), *, font=None):
                            if self.view.tooltip_rect is not None:
                                selected_font = font or self.view.font
                                glyph = selected_font.render(str(text), True, color)
                                rendered.append(self.pg.Rect(*pos, glyph.get_width(), max(glyph.get_height(), selected_font.get_linesize())))
                            original(surface, text, pos, color, font=font)

                        self.view._text = record
                        self.view.handle_event(self.pg.event.Event(self.pg.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(0, 0, 0)))
                        self.view.draw(surface, canvas, text_size=preference)
                        self.view._text = original
                        tooltip = self.view.tooltip_rect
                        self.assertIsNotNone(tooltip)
                        self.assertTrue(canvas.contains(tooltip))
                        self.assertTrue(all(not tooltip.colliderect(rect) for rect in self.view.enemy_stat_rects))
                        self.assertTrue(rendered)
                        self.assertTrue(all(tooltip.contains(glyph) for glyph in rendered))
                        after = [self.pg.image.tobytes(surface.subsurface(rect), "RGB") for rect in self.view.enemy_stat_rects]
                        self.assertEqual(before, after, "hover must leave the actual stats pixels readable")
                        self.assertEqual(self.view.snapshot, selected)
                        self.assertEqual(self.view.snapshot.actions, snapshot.actions)
                        self.assertLessEqual(len(self.view._tooltip_layout_cache), 32)

    def test_enemy_status_tooltip_also_avoids_measured_card_stats(self):
        guarded = CombatStatusView("guarded", "Guarded", 2, "Until your next Attack or Power Attack; Flanking Strike also removes it.")
        snapshot = battle_snapshot(3)
        snapshot = replace(snapshot, enemies=tuple(replace(enemy, statuses=(guarded,)) for enemy in snapshot.enemies))
        self.view.set_snapshot(snapshot)
        canvas = self.pg.Rect(24, 100, 418, 330)
        self.view.draw(self.surface, canvas, text_size="larger")
        hit = next(rect for rect, text in self.view.tooltip_hits if text.startswith("Guarded:"))
        self.view.handle_event(self.pg.event.Event(self.pg.MOUSEMOTION, pos=hit.center, rel=(0, 0), buttons=(0, 0, 0)))
        self.view.draw(self.surface, canvas, text_size="larger")
        self.assertIsNotNone(self.view.tooltip_rect)
        self.assertTrue(canvas.contains(self.view.tooltip_rect))
        self.assertTrue(all(not self.view.tooltip_rect.colliderect(rect) for rect in self.view.enemy_stat_rects))
        self.assertEqual(self.view.snapshot, snapshot)

    def test_optional_scene_floor_aligns_existing_actor_ground_without_moving_actors(self):
        surface = self.pg.Surface((3840, 2160))
        image = self.pg.Surface((320, 240))
        image.fill((61, 75, 84))
        for size in ((418, 330), (680, 496), (1488, 842), (2256, 1310)):
            for preference in ("standard", "larger"):
                with self.subTest(canvas=size, preference=preference):
                    canvas = self.pg.Rect(22, 87, *size)
                    self.view.set_scene(image)
                    self.view.draw(surface, canvas, text_size=preference)
                    positions = self.view.actor_positions.copy()
                    scaled = self.view._scaled_backdrop[2]
                    generic_crop = self.view.backdrop_crop
                    self.assertEqual(generic_crop.y, (scaled.get_height() - self.view._arena_rect.h) // 3)
                    self.view.set_scene(image, ground_y=135)
                    self.view.draw(surface, canvas, text_size=preference)
                    self.assertEqual(self.view.actor_positions, positions)
                    self.assertEqual(self.view.snapshot, self.snapshot)
                    self.assertIs(self.view._scaled_backdrop[2], scaled, "changing the floor must reuse the existing scaled bitmap")
                    crop = self.view.backdrop_crop
                    scale_y = scaled.get_height() / image.get_height()
                    actor_offset = positions["player"][1] - self.view._arena_rect.y
                    native_ground = (crop.y + actor_offset) / scale_y
                    self.assertAlmostEqual(native_ground, 135, delta=0.51 / scale_y)
                    self.assertTrue(scaled.get_rect().contains(crop))
                    self.view.set_scene(image)
                    self.view.draw(surface, canvas, text_size=preference)
                    self.assertEqual(self.view.backdrop_crop, generic_crop)

    def test_scene_floor_crop_clamps_and_diagnostic_cannot_mutate_renderer(self):
        image = self.pg.Surface((320, 240))
        for anchor in (-1000, 1000):
            self.view.set_scene(image, ground_y=anchor)
            self.view.draw(self.surface, self.canvas)
            scaled = self.view._scaled_backdrop[2]
            crop = self.view.backdrop_crop
            self.assertTrue(scaled.get_rect().contains(crop))
            expected = 0 if anchor < 0 else scaled.get_height() - self.view._arena_rect.h
            self.assertEqual(crop.y, expected)
            crop.y = 100000
            self.assertEqual(self.view.backdrop_crop.y, expected)

    def test_scene_floor_and_crop_clear_when_scene_or_journey_changes(self):
        image = self.pg.Surface((320, 240))
        self.view.set_scene(image, ground_y=135)
        self.view.draw(self.surface, self.canvas)
        self.assertIsNotNone(self.view.backdrop_crop)
        self.view.set_scene(self.pg.Surface((320, 240)))
        self.assertIsNone(self.view._scene_ground_y)
        self.assertIsNone(self.view.backdrop_crop)
        self.view.set_scene(image, ground_y=135)
        self.view.draw(self.surface, self.canvas)
        self.view.set_snapshot(None)
        self.assertIsNone(self.view._scene_ground_y)
        self.assertIsNone(self.view.backdrop_crop)
        self.assertFalse(self.view.enemy_stat_rects)

    def test_high_resolution_font_fallback_preserves_actual_card_glyph_bounds(self):
        with patch("roads_beneath_shadow.pixel_theme.FONT_DIRECTORY", Path("/tmp/rbs-missing-battle-fonts")):
            view = BattleView(self.pg)
            view.set_snapshot(battle_snapshot(3))
            surface = self.pg.Surface((3840, 2160))
            canvas = self.pg.Rect(22, 87, 2256, 1310)
            original_text, original_card = view._text, view._draw_card
            active_card = None
            rendered = []

            def record_text(surface, text, pos, color=(239, 225, 188), *, font=None):
                if active_card is not None:
                    selected = font or view.font
                    glyph = selected.render(str(text), True, color)
                    bounds = self.pg.Rect(*pos, glyph.get_width(), max(glyph.get_height(), selected.get_linesize()))
                    self.assertTrue(active_card.contains(bounds), (text, active_card, bounds))
                    rendered.append(str(text))
                original_text(surface, text, pos, color, font=font)

            def record_card(surface, rect, enemy, *, wide=False):
                nonlocal active_card
                active_card = rect
                original_card(surface, rect, enemy, wide=wide)
                active_card = None

            view._text, view._draw_card = record_text, record_card
            view.draw(surface, canvas, text_size="larger")
            text = " ".join(rendered)
            for enemy in view.snapshot.enemies:
                self.assertIn(enemy.name, text)
            for field in ("HEALTH", "ARMOR", "HEAVY BLOW", "DAMAGE", "CAN INTERRUPT"):
                self.assertIn(field, text)
            self.assertTrue(canvas.contains(view._arena_rect))

    def test_repeated_heterogeneous_resizes_bound_actual_battle_surface_bytes(self):
        surface = self.pg.Surface((3840, 2160))
        self.view.update(0, reduced_motion=True)
        sizes = ((419, 324), (677, 495), (1488, 842), (2256, 1310), (1990, 842), (1100, 650))
        sprite_bytes = None
        for index in range(48):
            canvas = self.pg.Rect(22, 87, *sizes[index % len(sizes)])
            self.view.draw(surface, canvas, text_size=("standard", "large", "larger")[index % 3])
            native = sum(sprite.get_pitch() * sprite.get_height() for sprite in self.view._sprites.values())
            if sprite_bytes is None:
                sprite_bytes = native
            self.assertEqual(native, sprite_bytes, "resizing must not add a native sprite for each size")
            image = self.view._scaled_backdrop[2]
            veil = self.view._backdrop_veil
            retained = native + image.get_pitch() * image.get_height() + veil.get_pitch() * veil.get_height()
            self.assertLessEqual(retained, 32 * 1024 * 1024)
            self.assertEqual(veil.get_size(), self.view._arena_rect.size)
            self.assertLessEqual(len(self.view._font_sets), 4)
            cached_veil = veil
            self.view.draw(surface, canvas, text_size=("standard", "large", "larger")[index % 3])
            self.assertIs(self.view._backdrop_veil, cached_veil)

    def test_fitted_large_display_tooltip_keeps_cached_glyphs_inside_its_frame(self):
        surface = self.pg.Surface((3840, 2160))
        canvas = self.pg.Rect(22, 87, 2256, 1000)
        self.view.draw(surface, canvas, text_size="larger")
        text = "\n".join(f"Condition {index}: Inspect the intent before striking." for index in range(40))
        self.view.tooltip_hits[:] = [(canvas, text)]
        self.view._mouse = canvas.center
        original = self.view._text
        glyphs = []

        def record(surface, text, pos, color=(239, 225, 188), *, font=None):
            selected = font or self.view.font
            glyph = selected.render(str(text), True, color)
            glyphs.append(self.pg.Rect(*pos, glyph.get_width(), max(glyph.get_height(), selected.get_linesize())))
            original(surface, text, pos, color, font=font)

        self.view._text = record
        frames = []
        for _ in range(2):
            glyphs.clear()
            self.view._draw_tooltip(surface)
            self.assertTrue(canvas.contains(self.view.tooltip_rect))
            self.assertEqual(len(glyphs), 40)
            self.assertTrue(all(self.view.tooltip_rect.contains(glyph) for glyph in glyphs))
            frames.append(self.view.tooltip_rect.copy())
        self.assertEqual(frames[0], frames[1])

    def test_reduced_motion_is_visually_stable_across_clock_times(self):
        self.view.update(0, reduced_motion=True)
        self.view.draw(self.surface, self.canvas, 20)
        first = self.pg.image.tobytes(self.surface, "RGB")
        self.view.draw(self.surface, self.canvas, 1700)
        second = self.pg.image.tobytes(self.surface, "RGB")
        self.assertEqual(first, second)

    def test_unavailable_companions_do_not_appear_in_the_fighting_party(self):
        for companions in (
            (replace(self.snapshot.companions[0], available=True), replace(self.snapshot.companions[1], available=False)),
            tuple(replace(companion, available=False) for companion in self.snapshot.companions),
        ):
            self.view.set_snapshot(replace(self.snapshot, companions=companions))
            self.view.draw(self.surface, self.canvas)
            self.assertEqual(set(self.view.actor_positions) & {"mara", "tobin"}, {companion.id for companion in companions if companion.available})

    def test_roomy_arena_companions_have_readable_adult_silhouettes(self):
        self.view.draw(self.surface, self.pg.Rect(24, 100, 677, 495))
        hero = self.view.actor_rects["player"]
        for actor_id in ("mara", "tobin"):
            ally = self.view.actor_rects[actor_id]
            self.assertGreaterEqual(ally.height, hero.height * 0.70)
            self.assertTrue(self.view._arena_rect.contains(ally))

    def test_adult_party_uses_equal_native_zoom_without_visible_alpha_overlap(self):
        surface = self.pg.Surface((3840, 2160))
        self.view.update(0, reduced_motion=True)
        for size in ((419, 290), (419, 324), (677, 495), (2256, 1310)):
            for count in (1, 3):
                for origin in ("bree_wayfarer", "north_road_scout", "healers_apprentice"):
                    snapshot = battle_snapshot(count)
                    self.view.set_snapshot(replace(snapshot, player=replace(snapshot.player, origin=origin)))
                    self.view.draw(surface, self.pg.Rect(22, 87, *size))
                    hero = self.view.actor_rects["player"]
                    visible = []
                    for actor_id in ("player", "mara", "tobin"):
                        rect = self.view.actor_rects[actor_id]
                        self.assertEqual(rect.height, hero.height, (size, origin, actor_id))
                        self.assertTrue(self.view._arena_rect.contains(rect))
                        native = self.view._sprite(actor_id, False)
                        alpha = self.pg.transform.scale(native, rect.size).get_bounding_rect()
                        bounds = alpha.move(rect.topleft)
                        visible.append(bounds)
                    # Native19px companion bodies versus the Scout's22px hood
                    # differ by at most one extra raster row at fractional zoom.
                    self.assertGreaterEqual(visible[1].height + 1, visible[0].height * 0.85)
                    self.assertGreaterEqual(visible[2].height + 1, visible[0].height * 0.85)
                    self.assertTrue(all(not first.colliderect(second) for first, second in zip(visible, visible[1:])),
                                    (size, origin, visible))

    def test_compact_single_enemy_uses_spare_card_space_for_the_party(self):
        self.view.set_snapshot(battle_snapshot(1))
        canvas = self.pg.Rect(14, 14, 419, 324)
        self.view.draw(self.surface, canvas)
        self.assertGreaterEqual(self.view._arena_rect.height, 130)
        self.assertLess(self.view.enemy_hits[0][0].height, 150)
        self.assertEqual(len({self.view.actor_positions[actor_id][0] for actor_id in ("player", "mara", "tobin")}), 3)
        hero = self.view.actor_rects["player"]
        for actor_id in ("mara", "tobin"):
            ally = self.view.actor_rects[actor_id]
            self.assertGreaterEqual(ally.height, hero.height * 0.70)
            self.assertTrue(self.view._arena_rect.contains(ally))

    def test_compact_single_card_allocation_reuses_measurements_during_animation(self):
        self.view.set_snapshot(battle_snapshot(1))
        canvas = self.pg.Rect(14, 14, 419, 324)
        with patch.object(self.view, "_card_content_height", wraps=self.view._card_content_height) as measure:
            self.view.draw(self.surface, canvas, 100)
            first_calls = measure.call_count
            self.assertGreater(first_calls, 0)
            self.view.draw(self.surface, canvas, 300)
            self.assertEqual(measure.call_count, first_calls)
        for width in range(419, 459):
            self.view.draw(self.surface, self.pg.Rect(14, 14, width, 324))
        self.assertLessEqual(len(self.view._single_card_heights), 32)

    def test_compact_single_enemy_retains_all_card_fields_with_larger_fonts(self):
        self.view.mini_bold_font = self.pg.font.SysFont("dejavusansmono,courier,monospace", 18, bold=True)
        self.view.mini_font = self.pg.font.SysFont("dejavusansmono,courier,monospace", 17)
        self.view.mini_prose_font = self.pg.font.SysFont("dejavusans,arial,sans", 17)
        guarded = CombatStatusView("guarded", "Guarded", 2, "+2 Armor until struck.")
        weakened = CombatStatusView("weakened", "Weakened", 1, "Reduce incoming attacks by 2.")
        enemy = replace(self.snapshot.enemies[0], name="Ghorak Ash-Hand", phase=2,
                        intent_label="Ash-Hand Execution", telegraph="a devastating blow; interrupt it now",
                        statuses=(guarded, weakened))
        self.view.set_snapshot(replace(self.snapshot, enemies=(enemy,)))
        glyphs = []
        original_text, original_card = self.view._text, self.view._draw_card
        active_card = None

        def record_text(surface, text, pos, color=(239, 225, 188), *, font=None):
            if active_card is not None:
                selected = font or self.view.font
                glyph = selected.render(str(text), True, color)
                bounds = self.pg.Rect(*pos, glyph.get_width(), max(glyph.get_height(), selected.get_linesize()))
                glyphs.append((str(text), bounds))
                self.assertTrue(active_card.contains(bounds), (text, active_card, bounds))
            original_text(surface, text, pos, color, font=font)

        def record_card(surface, rect, enemy, *, wide=False):
            nonlocal active_card
            active_card = rect
            original_card(surface, rect, enemy, wide=wide)
            active_card = None

        self.view._text, self.view._draw_card = record_text, record_card
        self.view.draw(self.surface, self.pg.Rect(14, 14, 419, 324))
        text = " ".join(label for label, _ in glyphs)
        for field in (enemy.name, "HEALTH", "ARMOR", "PHASE", enemy.intent_label.upper(), "DAMAGE", enemy.telegraph, "CAN INTERRUPT", "Guarded 2", "Weakened 1"):
            self.assertIn(field, text)

    def test_normal_mode_has_slow_live_actor_and_environment_motion(self):
        self.view.update(0, reduced_motion=False)
        self.view.draw(self.surface, self.canvas, 20)
        first = self.pg.image.tobytes(self.surface, "RGB")
        self.view.draw(self.surface, self.canvas, 1700)
        self.assertNotEqual(first, self.pg.image.tobytes(self.surface, "RGB"))

    def test_compact_target_marker_and_party_hit_areas_fit_inside_arena(self):
        for size in ((419, 290), (480, 420), (620, 480)):
            canvas = self.pg.Rect(14, 14, *size)
            self.view.draw(self.surface, canvas, 200)
            self.assertIsNotNone(self.view.target_marker_rect)
            self.assertTrue(self.view._arena_rect.contains(self.view.target_marker_rect))
            self.assertEqual({actor_id for _, actor_id in self.view.party_hits}, {"player", "mara", "tobin"})
            self.assertTrue(all(self.view._arena_rect.contains(rect) for rect, _ in self.view.party_hits))

    def test_formation_results_are_bounded_and_clear_of_condition_badges(self):
        for size in ((419, 290), (620, 480)):
            for kind in ("defend", "heal"):
                self.view.set_snapshot(None)
                self.view.set_snapshot(self.snapshot)
                self.view.queue_feedback(CombatFeedback(kind, "player", "player", 5 if kind == "heal" else 0, "Your action."))
                self.view.queue_feedback(CombatFeedback("damage", "player", "player", 1, "Bleeding"))
                for index in range(3):
                    self.view.queue_feedback(CombatFeedback("damage", f"enemy_{index}", "player", index + 3, "Heavy Blow"))
                age = 0
                for when in (0, 0.19, 0.38, 0.57, 0.76, 0.95, 1.14):
                    self.view.update(when - age)
                    age = when
                    self.view.draw(self.surface, self.pg.Rect(14, 14, *size), 200)
                    self.assertLessEqual(len(self.view.feedback_rects), 2)
                    self.assertTrue(all(self.view._arena_rect.contains(rect) for rect in self.view.feedback_rects))
                    self.assertTrue(all(not rect.colliderect(badge) for rect in self.view.feedback_rects for badge, _ in self.view.condition_hits))
                    if len(self.view.feedback_rects) == 2:
                        self.assertFalse(self.view.feedback_rects[0].colliderect(self.view.feedback_rects[1]))
                self.assertEqual(self.view.snapshot, self.snapshot)

    def test_melee_reaches_the_target_before_damage_label_and_returns(self):
        self.view.update(0, reduced_motion=False)
        self.view.draw(self.surface, self.canvas, 0)
        start = self.view.actor_rects["player"].centerx
        self.view.queue_feedback(CombatFeedback("damage", "player", "enemy_0", 7, "Mira strikes."))
        self.view.update(0.14)
        self.view.draw(self.surface, self.canvas, 0)
        self.assertGreater(self.view.actor_rects["player"].centerx, start + 50)
        self.assertEqual(self.view.feedback_rects, [], "numbers should land at the weapon impact")
        self.view.update(0.06)
        self.view.draw(self.surface, self.canvas, 0)
        self.assertEqual(len(self.view.feedback_rects), 1)
        self.view.update(0.3)
        self.view.draw(self.surface, self.canvas, 0)
        self.assertEqual(self.view.actor_rects["player"].centerx, start)

    def test_attacker_returns_before_the_next_incoming_impact(self):
        self.view.draw(self.surface, self.canvas, 0)
        start = self.view.actor_rects["player"].centerx
        self.view.queue_feedback(CombatFeedback("damage", "player", "enemy_0", 6, "Attack"))
        self.view.queue_feedback(CombatFeedback("damage", "enemy_0", "player", 3, "Retaliation"))
        self.view.update(0.37)
        self.view.draw(self.surface, self.canvas, 0)
        self.assertLessEqual(abs(self.view.actor_rects["player"].centerx - start), 5, "only hit recoil should displace the traveler when retaliation lands")
        self.assertTrue(any(actor_id == "player" and label == "−3" for actor_id, label, _ in self.view.feedback_labels))

    def test_combat_sound_cues_land_once_at_the_visible_impact(self):
        self.view.queue_feedback(CombatFeedback("damage", "mara", "enemy_0", 8, "Mara strikes."))
        self.view.queue_feedback(CombatFeedback("interrupt", "player", "enemy_0", 0, "Intent interrupted"))
        self.view.queue_feedback(CombatFeedback("damage", "enemy_1", "player", 4, "Heavy Blow"))
        self.view.update(0.17)
        self.assertEqual(self.view.drain_cues(), ())
        self.view.update(0.02)
        self.assertEqual(self.view.drain_cues(), ("hit", "interrupt"))
        self.view.update(0.4)
        self.assertEqual(self.view.drain_cues(), ("hit",))
        self.view.update(0.2)
        self.assertEqual(self.view.drain_cues(), ())
        self.assertEqual(self.view.snapshot, self.snapshot)

    def test_silent_frontends_keep_the_sound_cue_queue_bounded(self):
        for _ in range(25):
            self.view.queue_feedback(CombatFeedback("defend", "player", "player", 0, "Guard"))
        self.view.update(1)
        self.assertEqual(len(self.view.drain_cues()), 16)
        self.assertEqual(self.view.drain_cues(), ())
        self.view.queue_feedback(CombatFeedback("heal", "player", "player", 4, "Remedy"))
        self.view.update(0.1)
        self.view.set_snapshot(None)
        self.assertEqual(self.view.drain_cues(), ())

    def test_block_and_bleeding_have_distinct_sound_cues_in_reduced_motion(self):
        self.view.update(0, reduced_motion=True)
        self.view.queue_feedback(CombatFeedback("damage", "enemy_0", "player", 0, "Ward absorbs the hit"))
        self.view.queue_feedback(CombatFeedback("damage", "player", "player", 1, "Bleeding"))
        self.view.update(0.1, reduced_motion=True)
        self.assertEqual(self.view.drain_cues(), ("block", "hurt"))

    def test_final_snapshot_preserves_the_foe_until_the_killing_hit_lands(self):
        self.view.queue_feedback(CombatFeedback("damage", "player", "enemy_0", 12, "Final strike"))
        self.view.queue_feedback(CombatFeedback("fallen", "player", "enemy_0", 0, "The captain falls."))
        fallen = replace(self.snapshot.enemies[0], hp=0)
        self.view.set_snapshot(replace(self.snapshot, phase="victory", enemies=(fallen, *self.snapshot.enemies[1:])))
        self.assertEqual(self.view._fall_progress("enemy_0", False), 0)
        self.assertTrue(self.view.busy)
        self.view.update(0.3)
        self.assertGreater(self.view._fall_progress("enemy_0", False), 0)
        self.assertLess(self.view._fall_progress("enemy_0", False), 1)
        self.view.update(0.6)
        self.assertEqual(self.view._fall_progress("enemy_0", False), 1)
        self.assertFalse(self.view.busy)

    def test_paid_action_gate_has_a_short_bound_and_targeting_stays_free(self):
        for reduced, maximum in ((False, self.view.MAX_TURN_DURATION), (True, self.view.REDUCED_MOTION_TURN_DURATION)):
            self.view.set_snapshot(None)
            self.view.set_snapshot(self.snapshot)
            self.view.update(0, reduced_motion=reduced)
            for _ in range(12):
                self.view.queue_feedback(CombatFeedback("damage", "enemy_0", "player", 1, "Formation attack"))
            self.assertTrue(self.view.has_pending_feedback)
            self.view.draw(self.surface, self.canvas, 0)
            self.assertEqual(self.click(self.view.enemy_hits[1][0].center), (True, "enemy_1"))
            self.view.update(maximum + 0.01, reduced_motion=reduced)
            self.assertFalse(self.view.has_pending_feedback)

    def test_a_new_committed_move_does_not_sum_the_previous_rounds_labels(self):
        self.view.queue_feedback(CombatFeedback("damage", "enemy_0", "player", 8, "First round"))
        self.view.update(0.6)
        self.assertFalse(self.view.busy)
        self.assertEqual(len(self.view._effects), 1, "the first round's popup can still linger")
        self.view.queue_feedback(CombatFeedback("damage", "player", "enemy_1", 4, "Next committed move"))
        self.assertEqual(len(self.view._effects), 1)
        self.assertEqual(self.view._effects[0].feedback.amount, 4)

    def test_zero_health_remedy_still_shows_a_meaningful_action_result(self):
        text, _ = self.view._feedback_label(CombatFeedback("heal", "player", "player", 0, "Field Remedy"))
        self.assertEqual(text, "REMEDY")

    def test_interrupt_result_remains_readable_when_bleeding_ticks_follow_it(self):
        self.view.queue_feedback(CombatFeedback("damage", "mara", "enemy_0", 8, "Mara crosses blades."))
        self.view.queue_feedback(CombatFeedback("interrupt", "player", "enemy_0", 0, "Iron Guard interrupted"))
        self.view.queue_feedback(CombatFeedback("damage", "enemy_0", "enemy_0", 1, "Bleeding costs 1 Health."))
        self.view.update(0.74)
        self.view.draw(self.surface, self.pg.Rect(14, 14, 419, 290), 0)
        labels = [text for actor_id, text, _ in self.view.feedback_labels if actor_id == "enemy_0"]
        self.assertIn("INTERRUPTED", labels)
        self.assertIn("−9 ×2", labels)
        self.assertTrue(all(self.view._arena_rect.contains(rect) for rect in self.view.feedback_rects))

    def test_guard_result_survives_a_formation_of_three_incoming_hits(self):
        self.view.queue_feedback(CombatFeedback("defend", "player", "player", 1, "You defend."))
        for index, damage in enumerate((1, 2, 4)):
            self.view.queue_feedback(CombatFeedback("damage", f"enemy_{index}", "player", damage, "Heavy Blow"))
        self.view.update(0.78)
        self.view.draw(self.surface, self.canvas, 0)
        labels = [text for actor_id, text, _ in self.view.feedback_labels if actor_id == "player"]
        self.assertIn("GUARDED", labels)
        self.assertIn("−7 ×3", labels)

    def test_health_loss_trail_is_visual_and_reduced_motion_snaps_it(self):
        damaged = replace(self.snapshot.enemies[0], hp=6)
        self.view.set_snapshot(replace(self.snapshot, enemies=(damaged, *self.snapshot.enemies[1:])))
        self.assertEqual(self.view._health_trails["enemy_0"], 12)
        self.assertEqual(self.view.snapshot.enemies[0].hp, 6)
        self.view.update(0.4)
        self.assertGreater(self.view._health_trails["enemy_0"], 6)
        self.assertLess(self.view._health_trails["enemy_0"], 12)
        self.view.update(0, reduced_motion=True)
        self.assertEqual(self.view._health_trails["enemy_0"], 6)

    def test_displayed_player_health_changes_at_each_visible_incoming_impact(self):
        self.view.queue_feedback(CombatFeedback("damage", "player", "enemy_0", 4, "Attack"))
        self.view.queue_feedback(CombatFeedback("damage", "enemy_0", "player", 3, "Strike"))
        self.view.queue_feedback(CombatFeedback("damage", "enemy_1", "player", 2, "Strike"))
        final = replace(self.snapshot, player=replace(self.snapshot.player, hp=12), round_number=3)
        self.view.set_snapshot(final)
        self.assertEqual(self.view.displayed_player_health, (17, 24))
        self.assertIn("Health 17/24", self.view._party_help("player"))
        self.view.update(0.35)
        self.assertEqual(self.view.displayed_player_health, (17, 24))
        self.view.update(0.02)
        self.assertEqual(self.view.displayed_player_health, (14, 24))
        self.assertIn("Health 14/24", self.view._party_help("player"))
        self.view.set_snapshot(final)  # Free inspection must preserve the animation.
        self.assertEqual(self.view.displayed_player_health, (14, 24))
        self.view.update(0.18)
        self.assertEqual(self.view.displayed_player_health, (12, 24))
        self.view.update(1)
        self.assertEqual(self.view.displayed_player_health, (12, 24))
        self.assertEqual(self.view.snapshot, final)

    def test_displayed_player_health_preserves_exact_pre_hit_value_on_overkill(self):
        initial = replace(self.snapshot, player=replace(self.snapshot.player, hp=2))
        self.view.set_snapshot(initial)
        self.view.queue_feedback(CombatFeedback("damage", "enemy_0", "player", 9, "Final blow"))
        self.view.queue_feedback(CombatFeedback("fallen", "enemy_0", "player", 0, "Fallen"))
        self.view.set_snapshot(replace(initial, phase="defeat", player=replace(initial.player, hp=0)))
        self.view.update(0.17)
        self.assertEqual(self.view.displayed_player_health, (2, 24))
        self.view.update(0.02)
        self.assertEqual(self.view.displayed_player_health, (0, 24))

    def test_displayed_player_health_shows_remedy_then_retaliation_and_bleeding(self):
        self.view.queue_feedback(CombatFeedback("heal", "player", "player", 7, "Remedy"))
        self.view.queue_feedback(CombatFeedback("damage", "enemy_0", "player", 4, "Strike"))
        self.view.queue_feedback(CombatFeedback("damage", "player", "player", 1, "Bleeding"))
        final = replace(self.snapshot, player=replace(self.snapshot.player, hp=19))
        self.view.set_snapshot(final)
        self.assertEqual(self.view.displayed_player_health, (24, 24))
        self.view.update(0.37)
        self.assertEqual(self.view.displayed_player_health, (19, 24))
        self.view.update(0.91)  # The remedy popup expires before later damage.
        self.assertEqual(self.view.displayed_player_health, (19, 24))
        self.view.queue_feedback(CombatFeedback("damage", "enemy_0", "player", 2, "Next turn"))
        self.view.set_snapshot(replace(final, player=replace(final.player, hp=17)))
        self.assertEqual(self.view.displayed_player_health, (19, 24))
        self.view.update(0.2)
        self.assertEqual(self.view.displayed_player_health, (17, 24))

    def test_reduced_motion_health_follows_quick_impacts_and_reset(self):
        self.view.update(0, reduced_motion=True)
        self.view.queue_feedback(CombatFeedback("defend", "player", "player", 1, "Defend"))
        self.view.queue_feedback(CombatFeedback("damage", "enemy_0", "player", 2, "Strike"))
        final = replace(self.snapshot, player=replace(self.snapshot.player, hp=15))
        self.view.set_snapshot(final)
        self.view.update(0.04, reduced_motion=True)
        self.assertEqual(self.view.displayed_player_health, (17, 24))
        self.view.update(0.02, reduced_motion=True)
        self.assertEqual(self.view.displayed_player_health, (15, 24))
        self.assertEqual(self.view.snapshot, final)
        self.view.set_snapshot(None)
        self.assertIsNone(self.view.displayed_player_health)

    def test_defensive_objective_does_not_advertise_unavailable_attacks(self):
        actions = tuple(action for action in self.snapshot.actions if action.id == "defend")
        self.view.set_snapshot(replace(self.snapshot, actions=actions, defensive_objective=True))
        self.view.draw(self.surface, self.canvas, 200)
        help_text = self.view._intent_help(self.snapshot.enemies[0])
        self.assertIn("Defend", help_text)
        self.assertNotIn("Power Attack", help_text)
        self.assertNotIn("Mara", help_text)
        self.assertEqual(self.view._interrupt_label(self.snapshot.enemies[0]), "◇ HOLD YOUR GROUND")

    def test_survival_victory_caption_explains_the_living_invulnerable_foe(self):
        self.view.set_snapshot(replace(self.snapshot, phase="victory", defensive_objective=True, max_rounds=3, round_number=3))
        rendered = []
        original = self.view._text

        def record(surface, text, pos, color=(239, 225, 188), *, font=None):
            rendered.append(str(text))
            original(surface, text, pos, color, font=font)

        self.view._text = record
        self.view.draw(self.surface, self.canvas, 0)
        self.assertIn("YOU HELD THE LINE", rendered)
        self.assertEqual(self.view.snapshot.enemies[0].hp, 12)

    def test_invulnerable_rider_shows_survival_instead_of_sentinel_health(self):
        rider = replace(self.snapshot.enemies[0], name="Black Rider Echo", hp=999, max_hp=999, invulnerable=True)
        self.view.set_snapshot(replace(self.snapshot, enemies=(rider,), defensive_objective=True, max_rounds=6))
        with patch.object(self.view, "_text", wraps=self.view._text) as draw_text:
            self.view.draw(self.surface, self.pg.Rect(14, 14, 419, 324))
        labels = " ".join(call.args[1] for call in draw_text.call_args_list)
        self.assertIn("CANNOT BE WOUNDED", labels)
        self.assertIn("SURVIVE 6 ROUNDS", labels)
        self.assertNotIn("999", labels)
        self.assertTrue(any("Cannot be wounded" in help_text for _, help_text in self.view.tooltip_hits))
        self.assertFalse(any("999" in help_text for _, help_text in self.view.tooltip_hits))

    def test_timed_survival_keeps_exact_health_for_killable_enemies(self):
        ghorak = replace(self.snapshot.enemies[0], name="Ghorak Ash-Hand", hp=34, max_hp=50)
        rider = replace(self.snapshot.enemies[1], name="Black Rider Echo", hp=999, max_hp=999, invulnerable=True)
        self.view.set_snapshot(replace(self.snapshot, enemies=(ghorak, rider), max_rounds=6))
        self.assertEqual(self.view._health_label(ghorak), "34 / 50 HEALTH")
        self.assertIn("CANNOT BE WOUNDED", self.view._health_label(rider))
        self.view.set_snapshot(replace(self.view.snapshot, phase="victory", round_number=6))
        self.assertIn("HELD 6 ROUNDS", self.view._health_label(rider))

    def test_intent_disruption_help_uses_enabled_commands_only(self):
        actions = tuple(replace(action, enabled=False, disabled_reason="Not enough Focus.") if action.id in {"power", "mara"} else action for action in self.snapshot.actions)
        self.view.set_snapshot(replace(self.snapshot, actions=actions))
        text = self.view._intent_help(self.snapshot.enemies[0])
        self.assertIn("no disruption is currently available", text)
        self.assertNotIn("Power Attack or Mara", text)
        self.assertEqual(self.view._interrupt_label(self.snapshot.enemies[0]), "◆ INTERRUPTIBLE")

    def test_companion_hover_explains_role_bond_and_disabled_command(self):
        action = replace(self.snapshot.actions[-1], enabled=False, disabled_reason="Not enough Focus.")
        self.view.set_snapshot(replace(self.snapshot, actions=(*self.snapshot.actions[:-1], action)))
        self.view.draw(self.surface, self.canvas, 200)
        rect = next(rect for rect, actor_id in self.view.party_hits if actor_id == "mara")
        self.view.handle_event(self.pg.event.Event(self.pg.MOUSEMOTION, pos=rect.center, rel=(0, 0), buttons=(0, 0, 0)))
        self.assertEqual(self.view.hovered_actor_id, "mara")
        text = self.view._party_help("mara")
        self.assertIn("Bond 3", text)
        self.assertIn(action.description, text)
        self.assertIn("Not enough Focus", text)

    def test_long_party_tooltip_fits_with_all_actual_status_rules(self):
        from roads_beneath_shadow.combat_view import STATUS_DESCRIPTIONS
        statuses = tuple(CombatStatusView(key, key.title(), 2, STATUS_DESCRIPTIONS[key]) for key in ("bleeding", "exposed", "evade", "ward", "riposte"))
        self.view.set_snapshot(replace(self.snapshot, player=replace(self.snapshot.player, statuses=statuses)))
        canvas = self.pg.Rect(14, 14, 419, 290)
        self.view.draw(self.surface, canvas, 200)
        actor = next(rect for rect, actor_id in self.view.party_hits if actor_id == "player")
        self.view.handle_event(self.pg.event.Event(self.pg.MOUSEMOTION, pos=actor.center, rel=(0, 0), buttons=(0, 0, 0)))
        rendered = []
        original = self.view._text

        def record(surface, text, pos, color=(239, 225, 188), *, font=None):
            if self.view.tooltip_rect is not None:
                glyph = (font or self.view.font).render(str(text), True, color)
                rendered.append((str(text), self.pg.Rect(*pos, glyph.get_width(), glyph.get_height())))
            original(surface, text, pos, color, font=font)

        self.view._text = record
        self.view.draw(self.surface, canvas, 200)
        self.assertIsNotNone(self.view.tooltip_rect)
        self.assertTrue(canvas.contains(self.view.tooltip_rect))
        self.assertTrue(all(self.view.tooltip_rect.contains(bounds) for _, bounds in rendered))
        text = " ".join(line for line, _ in rendered)
        for status in statuses:
            self.assertIn(status.description, text)

    def test_enemy_sprite_hover_shows_its_name_and_tactics(self):
        rect, enemy_id = self.view.sprite_hits[1]
        self.view.handle_event(self.pg.event.Event(self.pg.MOUSEMOTION, pos=rect.center, rel=(0, 0), buttons=(0, 0, 0)))
        self.view.draw(self.surface, self.canvas, 200)
        text = next(text for hit, text in self.view.tooltip_hits if hit.collidepoint(rect.center))
        self.assertIn(self.snapshot.enemies[1].name, text)
        self.assertIn(self.snapshot.enemies[1].telegraph, text)
        self.assertTrue(self.canvas.contains(self.view.tooltip_rect))

    def test_evaded_enemy_attack_has_a_sidestep_and_no_health_mutation(self):
        self.view.draw(self.surface, self.canvas, 0)
        player_x = self.view.actor_rects["player"].centerx
        enemy_x = self.view.actor_rects["enemy_0"].centerx
        self.view.queue_feedback(CombatFeedback("evade", "enemy_0", "player", 0, "Attack evaded"))
        self.view.update(0.14)
        self.view.draw(self.surface, self.canvas, 0)
        self.assertLess(self.view.actor_rects["player"].centerx, player_x)
        self.assertLess(self.view.actor_rects["enemy_0"].centerx, enemy_x - 50)
        self.assertEqual(self.view.snapshot.player.hp, 17)
        self.view.update(0.4)
        self.view.draw(self.surface, self.canvas, 0)
        self.assertEqual(self.view.actor_rects["player"].centerx, player_x)

    def test_escaping_party_retreats_and_stays_out_after_the_cue_expires(self):
        self.view.draw(self.surface, self.canvas, 0)
        player_x = self.view.actor_rects["player"].centerx
        self.view.queue_feedback(CombatFeedback("escape", "player", "player", 0, "You find an opening and escape."))
        self.view.set_snapshot(replace(self.snapshot, phase="escaped"))
        self.view.update(0.14)
        self.view.draw(self.surface, self.canvas, 0)
        self.assertLess(self.view.actor_rects["player"].centerx, player_x)
        self.assertEqual(self.view.snapshot.player.hp, 17)
        self.view.update(2)
        self.view.draw(self.surface, self.canvas, 0)
        self.assertEqual(self.view.party_hits, [])
        self.assertNotIn("player", self.view.actor_rects)

    def test_reduced_motion_escape_settles_without_a_moving_party(self):
        self.view.queue_feedback(CombatFeedback("escape", "player", "player", 0, "You find an opening and escape."))
        self.view.set_snapshot(replace(self.snapshot, phase="escaped"))
        self.view.update(0.1, reduced_motion=True)
        self.view.draw(self.surface, self.canvas, 0)
        self.assertEqual(self.view.party_hits, [])
        first = self.pg.image.tobytes(self.surface, "RGB")
        self.view.draw(self.surface, self.canvas, 1900)
        self.assertEqual(first, self.pg.image.tobytes(self.surface, "RGB"))

    def test_health_trail_waits_for_a_late_formation_hit(self):
        for _ in range(5):
            self.view.queue_feedback(CombatFeedback("damage", "enemy_0", "player", 1, "Formation attack"))
        self.view.set_snapshot(replace(self.snapshot, player=replace(self.snapshot.player, hp=12)))
        self.view.update(0.4)
        self.assertEqual(self.view._health_trails["player"], 17)
        self.view.update(0.6)
        self.assertLess(self.view._health_trails["player"], 17)
        self.assertEqual(self.view.snapshot.player.hp, 12)

    def test_origin_and_equipped_weapon_change_the_shared_traveler_sprite(self):
        images = []
        for origin in ("bree_wayfarer", "north_road_scout", "healers_apprentice"):
            self.view.set_snapshot(replace(self.snapshot, player=replace(self.snapshot.player, origin=origin)))
            images.append(self.pg.image.tobytes(self.view._sprite("player", False), "RGBA"))
        self.assertEqual(len(set(images)), 3)
        images = []
        for weapon in (None, "rusty_sword", "knife", "ash_staff"):
            self.view.set_snapshot(replace(self.snapshot, player=replace(self.snapshot.player, weapon_id=weapon)))
            images.append(self.pg.image.tobytes(self.view._sprite("player", False), "RGBA"))
        self.assertEqual(len(set(images)), 4)

    def test_damage_feedback_draws_then_expires_without_changing_snapshot(self):
        for canvas in (self.canvas, self.pg.Rect(19, 91, 419, 290)):
            self.view.update(0, reduced_motion=True)
            self.view.draw(self.surface, canvas, 200)
            before = self.pg.image.tobytes(self.surface, "RGB")
            self.view.queue_feedback(CombatFeedback("damage", "player", "enemy_0", 7, "Mira strikes the captain."))
            self.view.update(0.1, reduced_motion=True)
            self.view.draw(self.surface, canvas, 200)
            self.assertNotEqual(before, self.pg.image.tobytes(self.surface, "RGB"))
            self.assertEqual(self.snapshot.enemies[0].hp, 12)
            self.view.update(3, reduced_motion=True)
            self.view.draw(self.surface, canvas, 200)
            self.assertEqual(before, self.pg.image.tobytes(self.surface, "RGB"))

    def test_status_and_intent_tooltips_include_the_actual_rules(self):
        text = "\n".join(text for _, text in self.view.tooltip_hits)
        self.assertIn("Lose 1 Health at the start of each turn", text)
        self.assertIn("Defend or interrupt it", text)
        self.assertIn("Power Attack or Mara", text)

    def test_inspection_and_notice_messages_do_not_animate_a_combat_hit(self):
        self.view.update(0, reduced_motion=True)
        self.view.draw(self.surface, self.canvas, 200)
        before = self.pg.image.tobytes(self.surface, "RGB")
        for kind in ("inspect", "notice", "info"):
            self.view.queue_feedback(CombatFeedback(kind, "player", "enemy_0", 0, "Read the enemy's tactics."))
        self.view.update(0.1, reduced_motion=True)
        self.view.draw(self.surface, self.canvas, 200)
        self.assertEqual(before, self.pg.image.tobytes(self.surface, "RGB"))

    def test_protected_damage_forecast_still_says_zero_damage(self):
        enemy = replace(self.snapshot.enemies[0], damage_min=0, damage_max=0, threat="danger")
        self.view.set_snapshot(replace(self.snapshot, enemies=(enemy,)))
        rendered = []
        original_text = self.view._text

        def record_text(surface, text, pos, color=(239, 225, 188), *, font=None):
            rendered.append(str(text))
            original_text(surface, text, pos, color, font=font)

        self.view._text = record_text
        self.view.draw(self.surface, self.canvas)
        self.assertIn("0–0 DAMAGE", rendered)

    def test_small_three_enemy_canvas_keeps_long_intents_and_statuses_visible(self):
        guarded = CombatStatusView("guarded", "Guarded", 2, "+2 Armor until struck.")
        enemies = tuple(replace(enemy, name=("Ash-Hand Commander", "Ash-Hand Sapper", "Ash-Hand Archer")[index],
                                intent_label="Ash-Hand Execution", telegraph="a devastating blow; interrupt it now", statuses=(guarded,))
                        for index, enemy in enumerate(self.snapshot.enemies))
        self.view.set_snapshot(replace(self.snapshot, enemies=enemies))
        rendered = []
        original_text = self.view._text

        def record_text(surface, text, pos, color=(239, 225, 188), *, font=None):
            if text == "Guarded 2":
                rendered.append((pos, (font or self.view.font).get_linesize()))
            original_text(surface, text, pos, color, font=font)

        self.view._text = record_text
        for size in ((480, 420), (419, 290)):
            rendered.clear()
            self.view.draw(self.surface, self.pg.Rect(14, 14, *size))
            self.assertEqual(len(rendered), 3)
            for (pos, line_height), (card, _) in zip(rendered, self.view.enemy_hits):
                self.assertTrue(card.contains(self.pg.Rect(*pos, 50, line_height)))

    def test_larger_platform_font_metrics_keep_every_enemy_card_field_visible(self):
        # Emulate a platform resolving the same requested system family to a
        # taller, wider font. These are real SDL fonts and glyph surfaces.
        self.view.mini_bold_font = self.pg.font.SysFont("dejavusansmono,courier,monospace", 18, bold=True)
        self.view.mini_font = self.pg.font.SysFont("dejavusansmono,courier,monospace", 17)
        self.view.mini_prose_font = self.pg.font.SysFont("dejavusans,arial,sans", 17)
        guarded = CombatStatusView("guarded", "Guarded", 2, "+2 Armor until struck.")
        weakened = CombatStatusView("weakened", "Weakened", 1, "Reduce incoming attacks by 2.")
        enemy = replace(self.snapshot.enemies[0], name="Ash-Hand Commander", phase=2,
                        intent_label="Ash-Hand Execution", telegraph="a devastating blow; interrupt it now",
                        statuses=(guarded, weakened))
        card = self.pg.Rect(14, 14, 134, 164)
        fonts = (self.view.mini_bold_font, self.view.mini_font, self.view.mini_prose_font)
        self.assertGreater(self.view._card_content_height(card, enemy, False, True, fonts), card.h)
        rendered = []
        original_text = self.view._text

        def record_text(surface, text, pos, color=(239, 225, 188), *, font=None):
            selected_font = font or self.view.font
            glyph = selected_font.render(str(text), True, color)
            rendered.append((str(text), self.pg.Rect(*pos, glyph.get_width(), max(glyph.get_height(), selected_font.get_linesize()))))
            original_text(surface, text, pos, color, font=font)

        self.view._text = record_text
        self.view._draw_card(self.surface, card, enemy)
        self.assertTrue(all(card.contains(glyph_rect) for _, glyph_rect in rendered), rendered)
        text = " ".join(text for text, _ in rendered)
        for field in (enemy.name, "HEALTH", "ARMOR", "PHASE", enemy.intent_label.upper(), "DAMAGE", enemy.telegraph, "CAN INTERRUPT", "Guarded 2", "Weakened 1"):
            self.assertIn(field, text)

    def test_fitted_font_measurements_match_its_actual_rendered_glyphs(self):
        from roads_beneath_shadow.pixel_battle import _ScaledFont
        native = self.pg.font.SysFont("dejavusansmono,courier,monospace", 17)
        fitted = _ScaledFont(self.pg, native, 0.73)
        for text in ("Ash-Hand Commander", "◆ CAN INTERRUPT", "Guarded 2"):
            glyph = fitted.render(text, True, (239, 225, 188))
            self.assertEqual(fitted.size(text), glyph.get_size())
            self.assertGreaterEqual(fitted.get_linesize(), glyph.get_height())

    def test_animation_frames_reuse_measured_card_typography(self):
        self.view.mini_font = self.pg.font.SysFont("dejavusansmono,courier,monospace", 17)
        enemy = self.snapshot.enemies[0]
        card = self.pg.Rect(14, 14, 134, 164)
        with patch.object(self.view, "_card_content_height", wraps=self.view._card_content_height) as measure:
            self.view._draw_card(self.surface, card, enemy)
            first_frame_calls = measure.call_count
            self.assertGreater(first_frame_calls, 1)
            self.view._draw_card(self.surface, card, enemy)
            self.assertEqual(measure.call_count, first_frame_calls)
            self.view.set_snapshot(replace(self.snapshot, round_number=3))
            self.view._draw_card(self.surface, card, enemy)
            self.assertGreater(measure.call_count, first_frame_calls)

    def test_original_sprite_styles_distinguish_enemy_roles(self):
        sprites = [self.view._sprite(kind, True) for kind in ("orc", "captain", "archer", "sapper", "warg", "ghorak", "troll", "rider")]
        self.assertEqual(len({self.pg.image.tobytes(sprite, "RGBA") for sprite in sprites}), 8)
        self.assertTrue(all(sprite.get_flags() & self.pg.SRCALPHA for sprite in sprites))

    def test_creature_attacks_change_their_pose_before_the_hit(self):
        for kind in ("warg", "troll", "sapper"):
            with self.subTest(kind=kind):
                idle = self.view._sprite(kind, True)
                attack = self.view._sprite(kind, True, pose=1)
                self.assertEqual(attack.get_size(), idle.get_size())
                self.assertNotEqual(self.pg.image.tobytes(attack, "RGBA"), self.pg.image.tobytes(idle, "RGBA"))
                self.assertIs(self.view._sprite(kind, True, pose=1), attack)
                if kind != "warg":
                    follow_through = self.view._sprite(kind, True, pose=2)
                    self.assertNotEqual(self.pg.image.tobytes(follow_through, "RGBA"), self.pg.image.tobytes(attack, "RGBA"))

    def test_every_equipped_weapon_has_an_attack_and_follow_through(self):
        for weapon in ("sword", "knife", "staff", None):
            with self.subTest(weapon=weapon):
                self.view.set_snapshot(replace(self.snapshot, player=replace(self.snapshot.player, weapon_id=weapon)))
                poses = [self.view._sprite("player", False, pose=pose) for pose in range(3)]
                self.assertEqual(len({self.pg.image.tobytes(sprite, "RGBA") for sprite in poses}), 3)

    def test_boss_phase_result_is_bounded_and_reduced_motion_is_stable(self):
        for reduced in (False, True):
            with self.subTest(reduced_motion=reduced):
                self.view.set_snapshot(None)
                self.view.set_snapshot(self.snapshot)
                self.view.update(0, reduced_motion=reduced)
                self.view.queue_feedback(CombatFeedback("phase", "enemy_0", "enemy_0", 2, "Phase II"))
                self.view.update(0.12, reduced_motion=reduced)
                self.view.draw(self.surface, self.pg.Rect(14, 14, 419, 324), 20)
                self.assertTrue(any(actor_id == "enemy_0" and label == "PHASE II" for actor_id, label, _ in self.view.feedback_labels))
                self.assertTrue(all(self.view._arena_rect.contains(rect) for rect in self.view.feedback_rects))
                first = self.pg.image.tobytes(self.surface, "RGB")
                self.view.draw(self.surface, self.pg.Rect(14, 14, 419, 324), 1900)
                if reduced:
                    self.assertEqual(first, self.pg.image.tobytes(self.surface, "RGB"))
                self.assertEqual(self.view.snapshot, self.snapshot)

    def test_draw_restores_the_callers_clip_and_never_paints_outside_canvas(self):
        sentinel = (222, 6, 203)
        self.surface.fill(sentinel)
        original_clip = self.pg.Rect(3, 3, 900, 700)
        self.surface.set_clip(original_clip)
        self.view.draw(self.surface, self.canvas)
        self.assertEqual(self.surface.get_clip(), original_clip)
        self.assertEqual(tuple(self.surface.get_at((self.canvas.x - 1, self.canvas.y))[:3]), sentinel)
        self.assertEqual(tuple(self.surface.get_at((self.canvas.right, self.canvas.y))[:3]), sentinel)

    def test_leaving_combat_clears_old_clickable_targets(self):
        self.view.queue_feedback(CombatFeedback("heal", "player", "player", 5, "A remedy restores Health."))
        self.view.set_snapshot(None)
        self.assertEqual(self.click(self.canvas.center), (False, None))
        self.assertEqual(self.view.enemy_hits, [])
        self.assertEqual(self.view.actor_positions, {})

    def test_long_enemy_names_are_wrapped_without_losing_words(self):
        name = "Teren the False Ranger and keeper of the drowned gate"
        lines = _wrapped(name, self.view.font, 146)
        self.assertEqual(" ".join(lines), name)
        self.assertTrue(all(self.view.font.size(line)[0] <= 146 for line in lines))


if __name__ == "__main__":
    unittest.main()
