"""Main-thread input from SDL's mapped game controllers.

Only SDL controller mappings are interpreted: an unknown joystick is never
assigned guessed button or axis numbers.  The caller owns the pygame event
pump and calls ``update`` once per frame, after passing events here.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite
from typing import Any


@dataclass(frozen=True)
class PadAction:
    """A context-independent button or menu-navigation action."""

    id: str


class GamepadInput:
    """Own mapped Controller handles; leave other pygame owners initialized.

    ``backend`` can supply pygame._sdl2.controller's interface for tests.
    Movement is the cached, bounded left-stick vector updated by ``update``.
    The D-pad produces menu navigation only.  ``reset``
    requires the active pad to become neutral before any further input, which
    prevents a held button or stick from crossing a decision or modal boundary.
    All methods that touch pygame must run on the event-pump thread.
    """

    DEAD_ZONE = 0.20
    NAVIGATION_THRESHOLD = 0.55
    REPEAT_DELAY = 0.35
    REPEAT_INTERVAL = 0.10
    MAX_DT = 0.25
    DISCOVERY_INTERVAL = 1.0
    _DIRECTIONS = ("up", "down", "left", "right")

    def __init__(self, pg: Any, backend: Any = None) -> None:
        self.pg = pg
        self._errors = (pg.error,)
        self._backend = backend
        self._owns_backend = False
        self._closed = False
        self._focused = True
        self._devices: dict[int, Any] = {}
        self._names: dict[int, str] = {}
        self._active: int | None = None
        self._movement = (0.0, 0.0)
        self._axes: tuple[float, ...] = (0.0,) * 6
        self._held: set[int] = set()
        self._event_down: set[int] = set()
        self._neutral_required = True
        self._repeat: dict[str, float] = {}
        self._discovery_elapsed = 0.0
        self.last_error: str | None = None
        self._actions = {
            pg.CONTROLLER_BUTTON_A: "confirm",
            pg.CONTROLLER_BUTTON_B: "back",
            pg.CONTROLLER_BUTTON_X: "inventory",
            pg.CONTROLLER_BUTTON_Y: "journal",
            pg.CONTROLLER_BUTTON_BACK: "archive",
            pg.CONTROLLER_BUTTON_START: "pause",
            pg.CONTROLLER_BUTTON_LEFTSHOULDER: "previous_target",
            pg.CONTROLLER_BUTTON_RIGHTSHOULDER: "next_target",
            pg.CONTROLLER_BUTTON_LEFTSTICK: "map",
            pg.CONTROLLER_BUTTON_RIGHTSTICK: "character",
            pg.CONTROLLER_BUTTON_DPAD_UP: "up",
            pg.CONTROLLER_BUTTON_DPAD_DOWN: "down",
            pg.CONTROLLER_BUTTON_DPAD_LEFT: "left",
            pg.CONTROLLER_BUTTON_DPAD_RIGHT: "right",
        }
        self._axis_ids = (
            pg.CONTROLLER_AXIS_LEFTX, pg.CONTROLLER_AXIS_LEFTY,
            pg.CONTROLLER_AXIS_RIGHTX, pg.CONTROLLER_AXIS_RIGHTY,
            pg.CONTROLLER_AXIS_TRIGGERLEFT, pg.CONTROLLER_AXIS_TRIGGERRIGHT,
        )
        if self._backend is None:
            try:
                from pygame._sdl2 import controller
            except ImportError as error:
                self.last_error = str(error)
            else:
                self._backend = controller
        self._discover()

    @property
    def available(self) -> bool:
        return self._active is not None and not self._closed

    @property
    def name(self) -> str:
        return self._names.get(self._active, "")

    @property
    def movement(self) -> tuple[float, float]:
        return self._movement

    @property
    def active_instance_id(self) -> int | None:
        """Stable SDL identity, useful for diagnostics; never a device index."""
        return self._active

    def _error(self, error: Exception) -> None:
        self.last_error = str(error)

    def _initialize(self) -> bool:
        if self._closed or self._backend is None:
            return False
        try:
            if not self._backend.get_init():
                self._backend.init()
                self._owns_backend = True
        except self._errors as error:
            self._error(error)
            return False
        return True

    def _discover(self) -> None:
        if not self._initialize():
            return
        try:
            count = self._backend.get_count()
        except self._errors as error:
            self._error(error)
            return
        for index in range(count):
            self._open(index)

    def _open(self, index: int) -> None:
        if not self._initialize():
            return
        controller = None
        try:
            if not self._backend.is_controller(index):
                return
            # Controller.id is a captured device INDEX in pygame-ce, and
            # Controller.as_joystick() reuses it even after reindexing.  Resolve
            # current identity before opening a possibly cached Controller.
            joystick = self.pg.joystick.Joystick(index)
            instance_id = joystick.get_instance_id()
            if instance_id in self._devices:
                return
            controller = self._backend.Controller(index)
            if not controller.attached():
                self._quit_controller(controller)
                return
            name = str(controller.name or "Gamepad")
        except self._errors as error:
            self._error(error)
            if controller is not None:
                self._quit_controller(controller)
            return
        # pygame caches Joystick wrappers and may return another owner's
        # object.  Leave those wrappers to their subsystem's lifetime instead
        # of calling quit() on an alias owned by another caller.
        self._devices[instance_id] = controller
        self._names[instance_id] = name
        if self._active is None:
            self._activate(instance_id)

    def _activate(self, instance_id: int | None) -> None:
        self._active = instance_id
        self._movement = (0.0, 0.0)
        self._held.clear()
        self._event_down.clear()
        self._axes = (0.0,) * 6
        self._repeat.clear()
        self._neutral_required = True
        if instance_id is not None and self._read_active():
            self._event_down = set(self._held)
            self._release_gate()

    def _quit_controller(self, controller: Any) -> None:
        try:
            controller.quit()
        except self._errors as error:
            self._error(error)

    def _remove(self, instance_id: int) -> None:
        controller = self._devices.pop(instance_id, None)
        self._names.pop(instance_id, None)
        if controller is not None:
            self._quit_controller(controller)
        if instance_id == self._active:
            self._activate(next(iter(self._devices), None))

    @staticmethod
    def _axis(value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not isfinite(number):
            return 0.0
        return max(-1.0, min(1.0, number / (32768.0 if number < 0 else 32767.0)))

    @classmethod
    def _stick(cls, x: float, y: float) -> tuple[float, float]:
        magnitude = hypot(x, y)
        if magnitude <= cls.DEAD_ZONE:
            return 0.0, 0.0
        strength = (min(1.0, magnitude) - cls.DEAD_ZONE) / (1.0 - cls.DEAD_ZONE)
        return x / magnitude * strength, y / magnitude * strength

    def _read_active(self) -> bool:
        if self._active is None or self._closed:
            return False
        instance_id = self._active
        controller = self._devices[instance_id]
        try:
            if not controller.attached():
                self._remove(instance_id)
                return False
            axes = tuple(self._axis(controller.get_axis(axis)) for axis in self._axis_ids)
            held = {
                button for button in range(self.pg.CONTROLLER_BUTTON_MAX)
                if controller.get_button(button)
            }
        except self._errors as error:
            self._error(error)
            self._remove(instance_id)
            return False
        self._axes = axes
        self._held = held
        self._set_movement()
        return True

    def _is_neutral(self) -> bool:
        return (
            not self._held and not self._event_down
            and hypot(*self._axes[:2]) <= self.DEAD_ZONE
            and hypot(*self._axes[2:4]) <= self.DEAD_ZONE
            and all(abs(axis) <= self.DEAD_ZONE for axis in self._axes[4:])
        )

    def _release_gate(self) -> None:
        if self._focused and self._neutral_required and self._is_neutral():
            self._neutral_required = False
        self._set_movement()

    def _dpad(self) -> tuple[int, int]:
        pg = self.pg
        x = int(pg.CONTROLLER_BUTTON_DPAD_RIGHT in self._held) - int(pg.CONTROLLER_BUTTON_DPAD_LEFT in self._held)
        y = int(pg.CONTROLLER_BUTTON_DPAD_DOWN in self._held) - int(pg.CONTROLLER_BUTTON_DPAD_UP in self._held)
        return x, y

    def _set_movement(self) -> None:
        if self._active is None or not self._focused or self._neutral_required:
            self._movement = (0.0, 0.0)
            return
        self._movement = self._stick(*self._axes[:2])

    def reset(self) -> None:
        """Stop current input and require neutral before the next context."""
        self._neutral_required = True
        self._movement = (0.0, 0.0)
        self._repeat.clear()
        if self._read_active():
            self._event_down.update(self._held)
            self._release_gate()

    @staticmethod
    def _event_instance(event: Any) -> int | None:
        # pygame-ce uses instance_id; older SDL event wrappers use which.
        return getattr(event, "instance_id", getattr(event, "which", None))

    def handle_event(self, event: Any) -> tuple[PadAction, ...]:
        if self._closed:
            return ()
        pg = self.pg
        if event.type == pg.WINDOWFOCUSLOST:
            self._focused = False
            self.reset()
            return ()
        if event.type == pg.WINDOWFOCUSGAINED:
            self._focused = True
            self.reset()
            return ()
        if event.type == pg.CONTROLLERDEVICEADDED:
            index = getattr(event, "device_index", getattr(event, "which", None))
            if isinstance(index, int) and index >= 0:
                self._open(index)
            return ()
        if event.type == pg.CONTROLLERDEVICEREMOVED:
            instance_id = self._event_instance(event)
            if instance_id is not None:
                self._remove(instance_id)
            return ()
        if event.type == pg.CONTROLLERDEVICEREMAPPED:
            if self._event_instance(event) == self._active:
                self.reset()
            return ()
        if event.type not in (pg.CONTROLLERBUTTONDOWN, pg.CONTROLLERBUTTONUP, pg.CONTROLLERAXISMOTION):
            return ()
        if self._event_instance(event) != self._active or self._active is None:
            return ()
        if not self._read_active():
            return ()
        if event.type == pg.CONTROLLERAXISMOTION:
            self._release_gate()
            return ()
        button = event.button
        if event.type == pg.CONTROLLERBUTTONUP:
            self._event_down.discard(button)
            self._release_gate()
            return ()
        already_down = button in self._event_down
        self._event_down.add(button)
        if already_down or not self._focused or self._neutral_required:
            return ()
        action = self._actions.get(button)
        if action is None:
            return ()
        if action in self._DIRECTIONS:
            self._repeat[action] = self.REPEAT_DELAY
        return (PadAction(action),)

    @classmethod
    def _dt(cls, dt: Any) -> float:
        try:
            number = float(dt)
        except (TypeError, ValueError):
            return 0.0
        return min(cls.MAX_DT, max(0.0, number)) if isfinite(number) else 0.0

    def update(self, dt: float, *, stick_navigation: bool) -> tuple[PadAction, ...]:
        if self._closed:
            return ()
        elapsed = self._dt(dt)
        if self._active is None:
            self._discovery_elapsed += elapsed
            if self._discovery_elapsed >= self.DISCOVERY_INTERVAL:
                self._discovery_elapsed = 0.0
                self._discover()
        if not self._read_active():
            return ()
        self._event_down = set(self._held)
        self._release_gate()
        if not self._focused or self._neutral_required:
            return ()
        x, y = self._dpad()
        desired = set()
        if x:
            desired.add("right" if x > 0 else "left")
        if y:
            desired.add("down" if y > 0 else "up")
        if stick_navigation:
            x_axis, y_axis = self._axes[:2]
            if max(abs(x_axis), abs(y_axis)) >= self.NAVIGATION_THRESHOLD:
                if abs(x_axis) > abs(y_axis):
                    desired.add("right" if x_axis > 0 else "left")
                else:
                    desired.add("down" if y_axis > 0 else "up")
        self._repeat = {direction: delay for direction, delay in self._repeat.items() if direction in desired}
        actions = []
        for direction in self._DIRECTIONS:
            if direction not in desired:
                continue
            if direction not in self._repeat:
                actions.append(PadAction(direction))
                self._repeat[direction] = self.REPEAT_DELAY
                continue
            remaining = self._repeat[direction] - elapsed
            if remaining <= 1e-9:
                actions.append(PadAction(direction))
                # At most one repeat per direction per frame after a stall.
                remaining %= self.REPEAT_INTERVAL
                if remaining <= 1e-9:
                    remaining = self.REPEAT_INTERVAL
            self._repeat[direction] = remaining
        return tuple(actions)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for controller in self._devices.values():
            self._quit_controller(controller)
        self._devices.clear()
        self._names.clear()
        self._active = None
        self._movement = (0.0, 0.0)
        self._held.clear()
        self._event_down.clear()
        self._repeat.clear()
        if self._owns_backend:
            try:
                self._backend.quit()
            except self._errors as error:
                self._error(error)
