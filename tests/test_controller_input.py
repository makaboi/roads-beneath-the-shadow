"""Mapped SDL controller behavior with independent fake physical state.

These tests need no controller hardware or pygame initialization.  Device
indices reindex while SDL instance IDs stay stable, as on real SDL hotplug.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from math import hypot, isfinite
from types import SimpleNamespace
import unittest

from roads_beneath_shadow.controller_input import GamepadInput, PadAction


class NativeError(RuntimeError):
    pass


class FakeController:
    def __init__(self, instance_id, *, mapped=True, name="Mapped pad"):
        self.instance_id = instance_id
        self.mapped = mapped
        self.name = name
        self.id = None  # Captured device index, deliberately NOT instance ID.
        self.axes = [0] * 6
        self.buttons = set()
        self.connected = True
        self.quit_calls = 0
        self.failure = None

    def attached(self):
        return self.connected and not self.quit_calls

    def get_axis(self, axis):
        if self.failure is not None:
            raise self.failure
        return self.axes[axis]

    def get_button(self, button):
        if self.failure is not None:
            raise self.failure
        return button in self.buttons

    def quit(self):
        self.quit_calls += 1


class FakeBackend:
    def __init__(self, devices=(), *, initialized=False):
        self.devices = list(devices)
        self.initialized = initialized
        self.init_calls = 0
        self.quit_calls = 0
        self.open_calls = []
        self.identity_calls = []
        self.init_failure = None
        self.discovery_failure = None
        self.open_failure = None

    def get_init(self):
        return self.initialized

    def init(self):
        self.init_calls += 1
        if self.init_failure is not None:
            raise self.init_failure
        self.initialized = True

    def quit(self):
        self.quit_calls += 1
        self.initialized = False

    def get_count(self):
        if self.discovery_failure is not None:
            raise self.discovery_failure
        return len(self.devices)

    def is_controller(self, index):
        return self.devices[index].mapped

    def Controller(self, index):
        if self.open_failure is not None:
            raise self.open_failure
        device = self.devices[index]
        self.open_calls.append(device.instance_id)
        # pygame returns its cached object even after the device reindexes.
        if device.id is None:
            device.id = index
        return device

    def Joystick(self, index):
        self.identity_calls.append(index)
        device = self.devices[index]
        return SimpleNamespace(get_instance_id=lambda: device.instance_id)

    def detach(self, instance_id):
        device = next(device for device in self.devices if device.instance_id == instance_id)
        device.connected = False
        self.devices.remove(device)


def fake_pygame(backend):
    # Values are SDL's STANDARD mapped controller enums, not raw device slots.
    names = ("A", "B", "X", "Y", "BACK", "GUIDE", "START", "LEFTSTICK", "RIGHTSTICK",
             "LEFTSHOULDER", "RIGHTSHOULDER", "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT")
    constants = {f"CONTROLLER_BUTTON_{name}": index for index, name in enumerate(names)}
    axes = ("LEFTX", "LEFTY", "RIGHTX", "RIGHTY", "TRIGGERLEFT", "TRIGGERRIGHT")
    constants.update({f"CONTROLLER_AXIS_{name}": index for index, name in enumerate(axes)})
    events = ("WINDOWFOCUSLOST", "WINDOWFOCUSGAINED", "CONTROLLERDEVICEADDED",
              "CONTROLLERDEVICEREMOVED", "CONTROLLERDEVICEREMAPPED", "CONTROLLERBUTTONDOWN",
              "CONTROLLERBUTTONUP", "CONTROLLERAXISMOTION")
    constants.update({name: 1000 + index for index, name in enumerate(events)})
    return SimpleNamespace(**constants, CONTROLLER_BUTTON_MAX=21, error=NativeError,
                           joystick=SimpleNamespace(Joystick=backend.Joystick))


class ControllerInputTests(unittest.TestCase):
    def setUp(self):
        self.device = FakeController(91)
        self.backend = FakeBackend([self.device])
        self.pg = fake_pygame(self.backend)
        self.pad = GamepadInput(self.pg, self.backend)
        self.addCleanup(self.pad.close)

    def event(self, kind, **attributes):
        return SimpleNamespace(type=getattr(self.pg, kind), **attributes)

    def button(self, device, button, down=True, *, which=False):
        if down:
            device.buttons.add(button)
        else:
            device.buttons.discard(button)
        identity = {"which" if which else "instance_id": device.instance_id}
        return self.pad.handle_event(self.event("CONTROLLERBUTTONDOWN" if down else "CONTROLLERBUTTONUP",
                                                button=button, **identity))

    def update(self, dt=0.016, *, navigation=False):
        return self.pad.update(dt, stick_navigation=navigation)

    def ids(self, actions):
        return tuple(action.id for action in actions)

    def test_actions_are_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            PadAction("confirm").id = "back"

    def test_only_mapped_devices_are_opened_and_instance_id_is_used(self):
        self.pad.close()
        unknown = FakeController(38, mapped=False, name="Unknown joystick")
        mapped = FakeController(902, name="SDL mapped controller")
        self.backend = FakeBackend([unknown, mapped])
        self.pg = fake_pygame(self.backend)
        self.pad = GamepadInput(self.pg, self.backend)
        self.addCleanup(self.pad.close)
        self.assertTrue(self.pad.available)
        self.assertEqual(self.pad.name, "SDL mapped controller")
        self.assertEqual(self.pad.active_instance_id, 902)
        self.assertEqual(mapped.id, 1)
        self.assertEqual(self.backend.open_calls, [902])
        self.assertEqual(self.backend.identity_calls, [1])
        self.assertEqual(unknown.quit_calls, 0)

    def test_all_standard_button_aliases_and_duplicate_edges(self):
        aliases = (("A", "confirm"), ("B", "back"), ("X", "inventory"), ("Y", "journal"),
                   ("BACK", "archive"), ("START", "pause"), ("LEFTSHOULDER", "previous_target"),
                   ("RIGHTSHOULDER", "next_target"), ("LEFTSTICK", "map"), ("RIGHTSTICK", "character"),
                   ("DPAD_UP", "up"), ("DPAD_DOWN", "down"), ("DPAD_LEFT", "left"), ("DPAD_RIGHT", "right"))
        for button_name, action in aliases:
            with self.subTest(button=button_name):
                button = getattr(self.pg, f"CONTROLLER_BUTTON_{button_name}")
                self.assertEqual(self.ids(self.button(self.device, button)), (action,))
                self.assertEqual(self.button(self.device, button), ())
                self.assertEqual(self.button(self.device, button, False), ())
        self.assertEqual(self.button(self.device, self.pg.CONTROLLER_BUTTON_GUIDE), ())

    def test_confirm_is_event_edge_only_and_never_repeats(self):
        a = self.pg.CONTROLLER_BUTTON_A
        self.assertEqual(self.ids(self.button(self.device, a)), ("confirm",))
        for _ in range(20):
            self.assertEqual(self.update(0.25, navigation=True), ())
        self.assertEqual(self.button(self.device, a), ())
        self.button(self.device, a, False)
        self.assertEqual(self.ids(self.button(self.device, a)), ("confirm",))

    def test_physical_confirm_without_an_event_never_selects(self):
        self.device.buttons.add(self.pg.CONTROLLER_BUTTON_A)
        self.assertEqual(self.update(0.25, navigation=True), ())
        self.device.buttons.clear()
        self.assertEqual(self.update(0.25, navigation=True), ())

    def test_quick_press_and_release_event_is_not_lost_to_neutral_physical_state(self):
        event = self.event("CONTROLLERBUTTONDOWN", instance_id=91, button=self.pg.CONTROLLER_BUTTON_A)
        self.assertEqual(self.ids(self.pad.handle_event(event)), ("confirm",))
        self.assertEqual(self.pad.handle_event(event), ())
        self.pad.handle_event(self.event("CONTROLLERBUTTONUP", instance_id=91, button=self.pg.CONTROLLER_BUTTON_A))
        self.assertEqual(self.ids(self.pad.handle_event(event)), ("confirm",))

    def test_radial_dead_zone_and_fractional_movement(self):
        self.device.axes[0] = round(0.19 * 32767)
        self.update()
        self.assertEqual(self.pad.movement, (0.0, 0.0))
        self.device.axes[0] = round(0.5 * 32767)
        self.update()
        self.assertAlmostEqual(self.pad.movement[0], 0.375, places=4)
        self.assertEqual(self.pad.movement[1], 0.0)
        # Two individually small axes outside the radial circle still move.
        self.device.axes[:2] = [round(0.16 * 32767)] * 2
        self.update()
        self.assertGreater(hypot(*self.pad.movement), 0.0)
        self.assertLess(hypot(*self.pad.movement), 0.1)

    def test_extreme_nonfinite_and_diagonal_axes_stay_finite_and_bounded(self):
        for x, y in ((32767, 32767), (-32768, -32768), (10**20, -10**20),
                     (float("inf"), float("nan")), (None, "bad")):
            with self.subTest(axes=(x, y)):
                self.device.axes[:2] = [x, y]
                self.update()
                self.assertTrue(all(isfinite(axis) for axis in self.pad.movement))
                self.assertLessEqual(hypot(*self.pad.movement), 1.0 + 1e-12)
        self.device.axes[:2] = [-32768, 0]
        self.update()
        self.assertEqual(self.pad.movement, (-1.0, 0.0))

    def test_held_dpad_navigates_without_moving_or_overriding_left_stick(self):
        self.device.buttons = {self.pg.CONTROLLER_BUTTON_DPAD_RIGHT, self.pg.CONTROLLER_BUTTON_DPAD_UP}
        self.assertEqual(self.ids(self.update()), ("up", "right"))
        self.assertEqual(self.pad.movement, (0.0, 0.0))
        self.device.axes[0] = -32768
        self.update()
        self.assertEqual(self.pad.movement, (-1.0, 0.0))
        self.device.buttons.clear()
        self.device.axes[0] = 0
        self.update()
        self.assertEqual(self.pad.movement, (0.0, 0.0))

    def test_dpad_repeat_has_initial_delay_interval_and_stops_on_release(self):
        down = self.pg.CONTROLLER_BUTTON_DPAD_DOWN
        self.assertEqual(self.ids(self.button(self.device, down)), ("down",))
        self.assertEqual(self.update(0.25), ())
        self.assertEqual(self.update(0.09), ())
        self.assertEqual(self.ids(self.update(0.01)), ("down",))
        self.assertEqual(self.update(0.09), ())
        self.assertEqual(self.ids(self.update(0.01)), ("down",))
        self.button(self.device, down, False)
        self.assertEqual(self.update(0.25), ())
        self.assertEqual(self.ids(self.button(self.device, down)), ("down",))

    def test_repeat_time_is_finite_capped_and_does_not_flood_after_a_stall(self):
        self.button(self.device, self.pg.CONTROLLER_BUTTON_DPAD_RIGHT)
        for dt in (float("nan"), float("inf"), -2, None):
            self.assertEqual(self.update(dt), ())
        self.assertEqual(self.update(1000), ())  # Capped at 0.25 seconds.
        self.assertEqual(self.ids(self.update(1000)), ("right",))
        self.assertEqual(self.ids(self.update(1000)), ("right",))

    def test_left_stick_navigates_only_when_requested(self):
        self.device.axes[:2] = [25000, 2000]
        self.assertEqual(self.update(navigation=False), ())
        self.assertGreater(self.pad.movement[0], 0)
        self.assertEqual(self.ids(self.update(navigation=True)), ("right",))
        self.assertEqual(self.update(0.25, navigation=True), ())
        self.assertEqual(self.ids(self.update(0.1, navigation=True)), ("right",))
        self.assertEqual(self.update(0.25, navigation=False), ())
        self.device.axes[:2] = [2000, -25000]
        self.assertEqual(self.ids(self.update(navigation=True)), ("up",))
        self.device.axes[:2] = [0, 0]
        self.assertEqual(self.update(0.25, navigation=True), ())

    def test_reset_blocks_retained_button_and_axes_until_neutral(self):
        a = self.pg.CONTROLLER_BUTTON_A
        self.button(self.device, a)
        self.device.axes[0] = 25000
        self.update()
        self.pad.reset()
        self.assertEqual(self.pad.movement, (0.0, 0.0))
        self.assertEqual(self.update(0.25, navigation=True), ())
        self.assertEqual(self.button(self.device, a), ())
        self.button(self.device, a, False)
        self.assertEqual(self.update(0.25, navigation=True), ())  # Stick still held.
        self.device.axes[0] = 0
        self.assertEqual(self.update(navigation=True), ())
        self.assertEqual(self.ids(self.button(self.device, a)), ("confirm",))

    def test_startup_with_held_input_requires_neutral(self):
        self.pad.close()
        device = FakeController(100)
        device.buttons.add(self.pg.CONTROLLER_BUTTON_A)
        device.axes[0] = 32767
        backend = FakeBackend([device])
        self.pg = fake_pygame(backend)
        self.pad = GamepadInput(self.pg, backend)
        self.addCleanup(self.pad.close)
        self.assertEqual(self.update(navigation=True), ())
        self.assertEqual(self.pad.movement, (0.0, 0.0))
        self.assertEqual(self.button(device, self.pg.CONTROLLER_BUTTON_A), ())
        device.buttons.clear()
        device.axes[0] = 0
        self.update()
        self.assertEqual(self.ids(self.button(device, self.pg.CONTROLLER_BUTTON_A)), ("confirm",))

    def test_focus_regain_requires_neutral_and_stops_movement(self):
        self.device.axes[0] = 32767
        self.update()
        self.assertEqual(self.pad.movement, (1.0, 0.0))
        self.pad.handle_event(self.event("WINDOWFOCUSLOST"))
        self.assertEqual(self.pad.movement, (0.0, 0.0))
        self.assertEqual(self.button(self.device, self.pg.CONTROLLER_BUTTON_A), ())
        self.pad.handle_event(self.event("WINDOWFOCUSGAINED"))
        self.assertEqual(self.update(0.25, navigation=True), ())
        self.assertEqual(self.pad.movement, (0.0, 0.0))
        self.device.axes[0] = 0
        self.button(self.device, self.pg.CONTROLLER_BUTTON_A, False)
        self.update()
        self.assertEqual(self.ids(self.button(self.device, self.pg.CONTROLLER_BUTTON_A)), ("confirm",))

    def test_foreign_and_old_instance_events_cannot_control_active_pad(self):
        foreign = FakeController(200)
        self.backend.devices.append(foreign)
        self.pad.handle_event(self.event("CONTROLLERDEVICEADDED", device_index=1))
        self.assertEqual(self.pad.active_instance_id, 91)
        self.assertEqual(self.button(foreign, self.pg.CONTROLLER_BUTTON_A), ())
        foreign.axes[0] = 32767
        self.pad.handle_event(self.event("CONTROLLERAXISMOTION", instance_id=200, axis=0, value=1.0))
        self.update()
        self.assertEqual(self.pad.movement, (0.0, 0.0))
        self.backend.detach(91)
        self.pad.handle_event(self.event("CONTROLLERDEVICEREMOVED", instance_id=91))
        self.assertEqual(self.pad.active_instance_id, 200)
        self.assertEqual(self.pad.movement, (0.0, 0.0))  # Newly active pad held.
        self.assertEqual(self.button(self.device, self.pg.CONTROLLER_BUTTON_A), ())
        foreign.buttons.clear()
        foreign.axes[0] = 0
        self.update()
        self.assertEqual(self.ids(self.button(foreign, self.pg.CONTROLLER_BUTTON_A)), ("confirm",))

    def test_removal_reindex_new_instance_and_duplicate_add_are_safe(self):
        second = FakeController(103)
        self.backend.devices.append(second)
        self.pad.handle_event(self.event("CONTROLLERDEVICEADDED", which=1))
        self.assertEqual(second.id, 1)
        self.pad.handle_event(self.event("CONTROLLERDEVICEADDED", device_index=1))
        self.assertEqual(self.backend.open_calls, [91, 103])
        self.assertEqual(second.quit_calls, 0)
        self.backend.detach(91)
        self.pad.handle_event(self.event("CONTROLLERDEVICEREMOVED", which=91))
        self.assertEqual(self.pad.active_instance_id, 103)
        # Second is now index zero, while Controller.id remains index one.
        self.pad.handle_event(self.event("CONTROLLERDEVICEADDED", device_index=0))
        self.assertEqual(self.backend.open_calls, [91, 103])
        third = FakeController(219)
        self.backend.devices.append(third)
        self.pad.handle_event(self.event("CONTROLLERDEVICEADDED", device_index=1))
        self.assertEqual(third.id, 1)
        self.assertEqual(self.backend.open_calls, [91, 103, 219])
        self.backend.detach(103)
        self.pad.handle_event(self.event("CONTROLLERDEVICEREMOVED", instance_id=103))
        self.assertEqual(self.pad.active_instance_id, 219)
        self.assertEqual(self.ids(self.button(third, self.pg.CONTROLLER_BUTTON_A)), ("confirm",))
        self.assertEqual((self.device.quit_calls, second.quit_calls, third.quit_calls), (1, 1, 0))

    def test_disconnect_without_remove_event_stops_input_and_closes_owned_handle(self):
        self.device.axes[0] = 32767
        self.update()
        self.backend.detach(91)
        self.assertEqual(self.update(), ())
        self.assertFalse(self.pad.available)
        self.assertEqual(self.pad.name, "")
        self.assertEqual(self.pad.movement, (0.0, 0.0))
        self.assertEqual(self.device.quit_calls, 1)

    def test_device_read_failure_falls_back_and_retry_recovers_discovery_errors(self):
        self.device.failure = NativeError("device disconnected")
        self.assertEqual(self.update(), ())
        self.assertFalse(self.pad.available)
        self.assertEqual(self.pad.last_error, "device disconnected")
        self.backend.devices.clear()
        self.backend.discovery_failure = NativeError("temporarily unavailable")
        for _ in range(4):
            self.update(0.25)
        self.assertEqual(self.pad.last_error, "temporarily unavailable")
        replacement = FakeController(301)
        self.backend.devices.append(replacement)
        self.backend.discovery_failure = None
        for _ in range(4):
            self.update(0.25)
        self.assertEqual(self.pad.active_instance_id, 301)

    def test_startup_native_initialization_error_recovers_without_breaking_keyboard(self):
        self.pad.close()
        backend = FakeBackend([FakeController(50)])
        backend.init_failure = NativeError("controller service unavailable")
        self.pg = fake_pygame(backend)
        self.pad = GamepadInput(self.pg, backend)
        self.addCleanup(self.pad.close)
        self.assertFalse(self.pad.available)
        self.assertEqual(self.pad.handle_event(SimpleNamespace(type=20, key=45)), ())
        backend.init_failure = None
        for _ in range(4):
            self.update(0.25)
        self.assertTrue(self.pad.available)

    def test_unrelated_logic_errors_are_not_swallowed(self):
        self.pad.close()
        backend = FakeBackend([])
        backend.discovery_failure = ValueError("implementation bug")
        with self.assertRaisesRegex(ValueError, "implementation bug"):
            GamepadInput(fake_pygame(backend), backend)

    def test_remapping_resets_held_input(self):
        self.button(self.device, self.pg.CONTROLLER_BUTTON_DPAD_DOWN)
        self.pad.handle_event(self.event("CONTROLLERDEVICEREMAPPED", instance_id=91))
        self.assertEqual(self.update(0.25, navigation=True), ())
        self.assertEqual(self.pad.movement, (0.0, 0.0))
        self.button(self.device, self.pg.CONTROLLER_BUTTON_DPAD_DOWN, False)
        self.update()
        self.assertEqual(self.ids(self.button(self.device, self.pg.CONTROLLER_BUTTON_DPAD_DOWN)), ("down",))

    def test_close_is_idempotent_and_only_quits_a_backend_it_initialized(self):
        self.pad.close()
        self.pad.close()
        self.assertEqual(self.device.quit_calls, 1)
        self.assertEqual(self.backend.quit_calls, 1)
        self.assertFalse(self.pad.available)
        self.assertEqual(self.update(navigation=True), ())
        self.assertEqual(self.pad.handle_event(self.event("CONTROLLERDEVICEADDED", device_index=0)), ())
        external_device = FakeController(10)
        external_backend = FakeBackend([external_device], initialized=True)
        pad = GamepadInput(fake_pygame(external_backend), external_backend)
        pad.close()
        self.assertEqual(external_device.quit_calls, 1)
        self.assertEqual(external_backend.init_calls, 0)
        self.assertEqual(external_backend.quit_calls, 0)
        self.assertTrue(external_backend.initialized)


if __name__ == "__main__":
    unittest.main()
