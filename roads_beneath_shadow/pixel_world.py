"""Walkable pixel worlds at existing story decisions.

The worlds are a presentation of the choices, not a second game state.  A
point always returns the index of an option in the current request.  Nothing
here changes inventory, relationships, flags, or save files.  Pygame is passed
in by the main-thread renderer and is never imported by the story worker.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from math import hypot
from pathlib import Path
from typing import Any, Sequence


TILE = 16
WORLD_SIZE = (320, 240)
GRID_SIZE = (20, 15)
ASSET_DIRECTORY = Path(__file__).resolve().parent / "pixel_assets"
WALKABLE = frozenset(".,=+:")
CHARACTER_CELL = (20, 24)
CHARACTER_ATLAS_ROWS = {
    "mara": 4, "tobin": 5, "calenor": 6, "edrin": 7, "orc": 8,
    "orc_scout": 9, "patron": 10, "butterbur": 11,
}


def character_frame_rect(name: str = "traveler", *, direction: int = 0, frame: int = 0) -> tuple[int, int, int, int]:
    """Shared sprite identity for exploration, combat, and character panels."""
    row = direction % 4 if name == "traveler" else CHARACTER_ATLAS_ROWS[name]
    return frame % 4 * CHARACTER_CELL[0], row * CHARACTER_CELL[1], *CHARACTER_CELL


@dataclass(frozen=True)
class WorldPoint:
    key: str
    name: str
    tile: tuple[int, int]
    option: str
    description: str
    sprite: str | None = None

    @property
    def position(self) -> tuple[float, float]:
        return self.tile[0] * TILE + TILE / 2, self.tile[1] * TILE + TILE / 2


@dataclass(frozen=True)
class WorldLook:
    key: str
    name: str
    tile: tuple[int, int]
    text: str

    @property
    def position(self) -> tuple[float, float]:
        return self.tile[0] * TILE + TILE / 2, self.tile[1] * TILE + TILE / 2


@dataclass(frozen=True)
class WorldMap:
    key: str
    name: str
    grid: tuple[str, ...]
    spawn: tuple[int, int]
    points: tuple[WorldPoint, ...]
    ambience: str
    lights: tuple[tuple[int, int], ...] = ()
    actors: tuple[tuple[str, tuple[int, int]], ...] = ()
    looks: tuple[WorldLook, ...] = ()

    def passable(self, tile: tuple[int, int]) -> bool:
        x, y = tile
        return 0 <= x < GRID_SIZE[0] and 0 <= y < GRID_SIZE[1] and self.grid[y][x] in WALKABLE


@dataclass(frozen=True)
class BoundPoint:
    point: WorldPoint
    answer: int
    option: str


def _grid(fill: str = ".") -> list[list[str]]:
    result = [[fill] * GRID_SIZE[0] for _ in range(GRID_SIZE[1])]
    for x in range(GRID_SIZE[0]):
        result[0][x] = result[-1][x] = "#"
    for row in result:
        row[0] = row[-1] = "#"
    return result


def _fill(grid: list[list[str]], box: tuple[int, int, int, int], char: str) -> None:
    x, y, width, height = box
    for row in range(y, y + height):
        for column in range(x, x + width):
            grid[row][column] = char


def _freeze(grid: list[list[str]]) -> tuple[str, ...]:
    return tuple("".join(row) for row in grid)


def _maps() -> dict[str, WorldMap]:
    pony = _grid()
    _fill(pony, (1, 1, 18, 1), "#")
    _fill(pony, (14, 3, 4, 1), "B")
    _fill(pony, (14, 2, 4, 1), "S")
    _fill(pony, (5, 5, 3, 2), "T")
    _fill(pony, (11, 7, 3, 2), "T")
    _fill(pony, (4, 10, 2, 1), "T")
    pony[4][1] = "F"
    for x, y in ((17, 4), (17, 11), (2, 11)):
        pony[y][x] = "O"
    pony[3][18] = "+"
    pony[13][10] = "+"
    pony_points = (
        WorldPoint("fight", "Mara", (8, 7), "Draw your weapon and fight beside Mara", "Mara holds the raiders at the overturned tables.", "mara"),
        WorldPoint("hide", "Hearth shadows", (3, 6), "Hide the pendant and protect the letter", "The low fire leaves a pocket of darkness beside the hearth."),
        WorldPoint("search", "Edrin", (3, 3), "Search the fallen messenger for another clue", "The fallen messenger still carries the marks of his journey.", "edrin"),
        WorldPoint("escape", "Kitchen door", (18, 3), "Escape through the inn's kitchen", "The kitchen door stands behind the long wooden bar."),
        WorldPoint("question", "Orc captain", (10, 12), "Attempt to question the Orc captain", "The captain demands the silver star.", "orc"),
    )

    bree = _grid(",")
    _fill(bree, (9, 1, 3, 13), "=")
    _fill(bree, (2, 6, 17, 2), "=")
    _fill(bree, (5, 8, 10, 3), "=")
    _fill(bree, (12, 2, 7, 6), "H")
    _fill(bree, (14, 8, 4, 1), "H")
    _fill(bree, (2, 2, 4, 3), "H")
    _fill(bree, (2, 9, 5, 4), "R")
    for x, y in ((2, 6), (6, 2), (7, 12), (16, 12), (17, 11), (2, 13), (13, 13)):
        bree[y][x] = "V"
    bree[1][10] = "+"
    bree[3][12] = "+"
    bree[7][18] = "+"
    bree[8][14] = "+"
    bree[10][6] = "+"
    bree_points = (
        WorldPoint("messenger_room", "Edrin's attic", (12, 3), "Examine Edrin's room and the black-fletched arrow", "A narrow stair climbs beneath the Pony's eaves."),
        WorldPoint("stable_yard", "Stable yard", (6, 10), "Search the stable yard with Tobin", "Tobin lowers his lantern beside the churned stable mud.", "tobin"),
        WorldPoint("pony_kitchen", "Pony kitchen", (18, 7), "Gather one set of supplies from the Pony's kitchen", "Warm light spills from the pantry's open back door."),
        WorldPoint("mara_fire", "Pony hearth", (14, 8), "Speak privately with Mara beside the dying fire", "Mara waits inside, beside the last warmth of the hearth.", "mara"),
        WorldPoint("north_gate", "North gate", (10, 1), "Go to the north gate and find the third stone", "Calenor's letter points toward the gate's third stone."),
    )

    wayhouse = _grid(":")
    _fill(wayhouse, (7, 1, 1, 7), "#")
    _fill(wayhouse, (12, 1, 1, 7), "#")
    wayhouse[6][7] = wayhouse[6][12] = "+"
    _fill(wayhouse, (1, 2, 3, 3), "~")
    _fill(wayhouse, (4, 3, 2, 1), "A")
    _fill(wayhouse, (9, 2, 2, 2), "M")
    _fill(wayhouse, (14, 2, 3, 1), "S")
    wayhouse[3][15] = "Q"
    wayhouse[11][10] = "D"
    wayhouse_points = (
        WorldPoint("armory", "Drowned armory", (5, 4), "Search the drowned armory", "Black water covers the bronze hooks and the captain's table."),
        WorldPoint("archive", "Wall-map archive", (10, 4), "Read the wall-map in the archive", "Silver routes converge on a mosaic of the old northern roads."),
        WorldPoint("shrine", "Star chamber", (15, 4), "Enter the chamber where the star is calling", "A stone chair faces a polished wall.", None),
        WorldPoint("descend", "Sealed stair", (10, 11), "Descend to the sealed road before Ghorak arrives", "The stair falls beneath the hill. Its seal is waiting."),
    )

    hall = _grid(":")
    for x, y in ((3, 3), (7, 3), (12, 3), (16, 3), (3, 10), (7, 10), (12, 10), (16, 10)):
        hall[y][x] = "P"
    _fill(hall, (2, 1, 4, 1), "S")
    _fill(hall, (14, 1, 3, 1), "S")
    hall[2][10] = "Q"
    hall[7][3] = "Q"
    hall[7][19] = "+"
    hall_points = (
        WorldPoint("archive", "Cipher Archive", (4, 2), "Enter the Cipher Archive", "Shelves preserve the road marks of the Wardens."),
        WorldPoint("statue", "Erased Statue", (10, 3), "Study the Erased Statue", "An eighth figure has lost its face, its name, and its crown."),
        WorldPoint("testimony", "Dead Testimony", (4, 7), "Hear the Dead Testimony", "An empty stone seat remembers the returning road."),
        WorldPoint("leave", "Echo Bridge", (18, 7), "Take the road to Echo Bridge", "The east arch leads farther down the Dead Road."),
    )

    lantern = _grid(":")
    _fill(lantern, (1, 1, 18, 3), "#")
    _fill(lantern, (1, 12, 18, 2), "#")
    _fill(lantern, (8, 1, 4, 3), ":")
    _fill(lantern, (8, 12, 4, 2), ":")
    lantern[2][10] = "D"
    lantern[6][4] = "P"
    lantern[6][15] = "P"
    lantern[10][4] = "P"
    lantern[10][15] = "P"
    lantern_points = (
        WorldPoint("mara", "Mara", (5, 6), "Speak with Mara about the road after this one", "Mara has a few words before the vault opens.", "mara"),
        WorldPoint("tobin", "Tobin's lantern", (14, 6), "Help Tobin tend the lantern", "Soot marks the ordinary lantern's glass.", "tobin"),
        WorldPoint("calenor", "Calenor", (6, 10), "Sit beside Calenor for a moment", "Your guardian rests beneath the low stone arch.", "calenor"),
        WorldPoint("rest", "Rest beneath the arch", (13, 10), "Rest and tend your wounds", "An ordinary pause to bind wounds and gather strength."),
        WorldPoint("leave", "Last Seal", (10, 3), "Enter the Last Seal", "Beyond the last lantern, the vault waits."),
    )

    maps = {
        "pony": WorldMap("pony", "THE PRANCING PONY", _freeze(pony), (9, 10), pony_points, "fire", ((1, 4), (15, 4), (3, 2)), (("orc_scout", (8, 12)), ("orc_scout", (12, 12)), ("patron", (4, 8)), ("patron", (15, 8)), ("patron", (7, 3)), ("butterbur", (16, 2)))),
        "bree": WorldMap("bree", "BREE BEFORE MIDNIGHT", _freeze(bree), (10, 11), bree_points, "rain", ((13, 3), (18, 7), (14, 8), (6, 10), (9, 1))),
        "wayhouse": WorldMap("wayhouse", "THE BURIED WAYHOUSE", _freeze(wayhouse), (10, 9), wayhouse_points, "water", ((6, 6), (13, 6), (16, 4))),
        "hall": WorldMap("hall", "THE HALL OF EIGHT", _freeze(hall), (10, 12), hall_points, "dust", ((2, 6), (17, 6), (10, 2))),
        "lantern": WorldMap("lantern", "THE LAST LANTERN", _freeze(lantern), (10, 11), lantern_points, "lantern", ((13, 6),)),
    }
    details = {
        "pony": (
            WorldLook("pony_window", "Rain-dark window", (10, 1), "Rain beads against the leaded panes. Beyond them, Bree has fallen silent."),
            WorldLook("pony_fire", "The low fire", (1, 4), "The hearth still burns, but nobody sings. Nobody laughs."),
            WorldLook("pony_barrel", "Inn's stores", (17, 11), "The Pony's stores sit against the wall, well away from the overturned tables."),
        ),
        "bree": (
            WorldLook("pony_sign", "Hanging horse sign", (12, 6), "The Prancing Pony's horse sign hangs above the rain-dark lane."),
            WorldLook("stable_fence", "Stable fence", (4, 8), "Cold mist settles over the churned yard. Beyond the stable wall, Bree's hedges whisper."),
            WorldLook("bree_shutter", "Closed shutters", (4, 4), "Bree has drawn in upon itself. The shutters are closed, and the watch calls from gate to gate."),
        ),
        "wayhouse": (
            WorldLook("armory_water", "Black water", (2, 4), "The drowned armory's dark water lies still beneath the old bronze hooks."),
            WorldLook("bronze_hooks", "Bronze hooks", (5, 2), "Bronze hooks line the wall. Most of the weapons they held have become rust."),
            WorldLook("fallen_lintel", "Fallen stone", (16, 11), "Shattered northern stone lies beside the road that descends beneath the hill."),
        ),
        "hall": (
            WorldLook("wall_names", "The wall of names", (16, 2), "Eight columns of names awaken across the dark stone. A road is kept by those who return."),
            WorldLook("eight_spokes", "Eight spokes", (10, 7), "The eight-spoked stone marks the middle of the Wardens' hall."),
        ),
        "lantern": (
            WorldLook("ordinary_lantern", "An ordinary lantern", (13, 5), "Soot marks its glass, and its handle is patched. No ancient power keeps it alight; someone remembered to fill it."),
            WorldLook("low_arch", "The last low arch", (3, 4), "Beyond this low stone arch, the vault waits. There is still time for a few words."),
        ),
    }
    return {key: replace(spec, looks=details[key]) for key, spec in maps.items()}


WORLD_MAPS = _maps()
MAP_HEADINGS = {
    "WHAT WILL YOU DO?": "pony",
    "WHERE WILL YOU INVESTIGATE?": "bree",
    "EXPLORE THE BURIED WAYHOUSE": "wayhouse",
    "EXPLORE THE HALL OF EIGHT": "hall",
    "BEFORE THE LAST SEAL": "lantern",
}


def missing_world_assets() -> list[Path]:
    """The installer can validate worlds alongside the original illustrations."""
    paths = [ASSET_DIRECTORY / f"world-{key}.png" for key in WORLD_MAPS]
    paths.append(ASSET_DIRECTORY / "world-characters.png")
    return [path for path in paths if not path.is_file()]


def map_for_request(label: str, options: Sequence[str]) -> WorldMap | None:
    """Only activate a map when every live choice has an explicit binding."""
    key = MAP_HEADINGS.get(label.strip().upper())
    if key is None or not options:
        return None
    spec = WORLD_MAPS[key]
    return spec if all(any(_matches_option(point, option) for point in spec.points) for option in options) else None


def _matches_option(point: WorldPoint, option: str) -> bool:
    # The optional recovery action describes the difficulty-dependent amount
    # in a suffix. Only this explicitly reserved action has a dynamic label.
    if point.key == "rest":
        option = option.casefold()
        prefix = point.option.casefold() + " (recover up to "
        suffix = " health and all focus)"
        return option == point.option.casefold() or (option.startswith(prefix) and option.endswith(suffix) and option[len(prefix):-len(suffix)].isdigit())
    return point.option.casefold() == option.casefold()


def bind_points(spec: WorldMap, options: Sequence[str]) -> tuple[BoundPoint, ...]:
    return tuple(BoundPoint(point, index, option) for index, option in enumerate(options, 1) for point in spec.points if _matches_option(point, option))


def shortest_path(spec: WorldMap, start: tuple[int, int], target: tuple[int, int]) -> tuple[tuple[int, int], ...]:
    """Return an obstacle-respecting four-way route, excluding the start."""
    if not spec.passable(start) or not spec.passable(target):
        return ()
    frontier = deque([start])
    parents: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    while frontier:
        cell = frontier.popleft()
        if cell == target:
            route = []
            while parents[cell] is not None:
                route.append(cell)
                cell = parents[cell]  # type: ignore[assignment]
            return tuple(reversed(route))
        x, y = cell
        for neighbor in ((x, y - 1), (x - 1, y), (x + 1, y), (x, y + 1)):
            if neighbor not in parents and spec.passable(neighbor):
                parents[neighbor] = cell
                frontier.append(neighbor)
    return ()


def interaction_tiles(spec: WorldMap, point: WorldPoint | WorldLook) -> tuple[tuple[int, int], ...]:
    """A blocked stair/table remains usable from a neighboring floor tile."""
    x, y = point.tile
    return tuple(cell for cell in ((x, y), (x, y + 1), (x - 1, y), (x + 1, y), (x, y - 1)) if spec.passable(cell))


class WorldView:
    """Render and control one small world, entirely on the display thread."""

    SPEED = 66.0
    INTERACTION_DISTANCE = 26.0

    def __init__(self, pygame: Any) -> None:
        self.pg = pygame
        self.spec: WorldMap | None = None
        self._navigation_spec: WorldMap | None = None
        self.points: tuple[BoundPoint, ...] = ()
        self._character_points: tuple[WorldPoint, ...] = ()
        self._request_identifier: Any = None
        self._positions: dict[str, tuple[float, float]] = {}
        self._position = (0.0, 0.0)
        self._direction = 0
        self._walking = False
        self._walk_time = 0.0
        self._time = 0.0
        self._held: set[int] = set()
        self._path: deque[tuple[float, float]] = deque()
        self._clicked_point: str | None = None
        self._hovered: BoundPoint | None = None
        self._hovered_look: WorldLook | None = None
        self._inspected_look: WorldLook | None = None
        self._rect = pygame.Rect(0, 0, 0, 0)
        self._backgrounds: dict[str, Any] = {}
        self._atlas: Any = None
        self._native = pygame.Surface(WORLD_SIZE)
        self._font = pygame.font.SysFont("dejavusansmono,courier,monospace", 9)
        self._small_font = pygame.font.SysFont("dejavusansmono,courier,monospace", 8)

    @property
    def active(self) -> bool:
        return self.spec is not None

    @property
    def map_key(self) -> str | None:
        return self.spec.key if self.spec else None

    @property
    def player_position(self) -> tuple[float, float]:
        return self._position

    def set_request(self, request: Any | None) -> bool:
        if self.spec:
            self._positions[self.spec.key] = self._position
        spec = None
        if request is not None and getattr(request, "story", False) and getattr(request, "kind", None) == "choice":
            spec = map_for_request(request.label, request.options)
        self.spec = spec
        self.points = bind_points(spec, request.options) if spec else ()
        companion_presence = {
            companion["name"].casefold(): companion.get("present", True)
            for companion in getattr(request, "context", {}).get("companions", ())
        }
        self._character_points = tuple(point for point in spec.points if point.sprite and companion_presence.get(point.sprite, True)) if spec else ()
        self._navigation_spec = None
        if spec:
            navigation_grid = [list(row) for row in spec.grid]
            occupied = [tile for _name, tile in spec.actors]
            occupied.extend(point.tile for point in self._character_points)
            for x, y in occupied:
                navigation_grid[y][x] = "N"
            self._navigation_spec = replace(spec, grid=_freeze(navigation_grid))
        identifier = getattr(request, "identifier", None)
        if identifier != self._request_identifier:
            self._path.clear()
            self._held.clear()
            self._clicked_point = None
            self._hovered = None
            self._hovered_look = None
            self._inspected_look = None
            self._walking = False
        self._request_identifier = identifier
        if spec:
            spawn = (spec.spawn[0] * TILE + TILE / 2, spec.spawn[1] * TILE + TILE / 2)
            self._position = self._positions.get(spec.key, spawn)
        return self.active

    def _nearest(self) -> BoundPoint | None:
        if not self.spec:
            return None
        nearby = [bound for bound in self.points if hypot(self._position[0] - bound.point.position[0], self._position[1] - bound.point.position[1]) <= self.INTERACTION_DISTANCE]
        if not nearby:
            return None
        return min(nearby, key=lambda bound: hypot(self._position[0] - bound.point.position[0], self._position[1] - bound.point.position[1]))

    def _nearest_look(self) -> WorldLook | None:
        if not self.spec:
            return None
        nearby = [look for look in self.spec.looks if hypot(self._position[0] - look.position[0], self._position[1] - look.position[1]) <= self.INTERACTION_DISTANCE]
        return min(nearby, key=lambda look: hypot(self._position[0] - look.position[0], self._position[1] - look.position[1])) if nearby else None

    def _focus(self) -> BoundPoint | WorldLook | None:
        point, look = self._nearest(), self._nearest_look()
        if look and self._clicked_point == "look:" + look.key:
            return look
        if point and self._clicked_point == point.point.key:
            return point
        if point and look:
            point_distance = hypot(self._position[0] - point.point.position[0], self._position[1] - point.point.position[1])
            look_distance = hypot(self._position[0] - look.position[0], self._position[1] - look.position[1])
            return point if point_distance <= look_distance else look
        return point or look

    @property
    def focused_option(self) -> int | None:
        focus = self._focus()
        return focus.answer if isinstance(focus, BoundPoint) and self._inspected_look is None else None

    @property
    def hint_text(self) -> str:
        if self._inspected_look:
            return "[E / ENTER / ESC] Close inspection"
        focus = self._focus()
        if isinstance(focus, BoundPoint):
            return f"[E / ENTER] {focus.option}"
        if isinstance(focus, WorldLook):
            return f"[E / ENTER] Look at {focus.name}"
        if self._hovered:
            return f"{self._hovered.point.name}: click to walk there"
        if self._hovered_look:
            return f"{self._hovered_look.name}: click to walk there"
        if self._path:
            return "Walking to your destination. WASD takes control."
        return "WASD: walk   E: interact   Click: walk to a place"

    @property
    def inspection_text(self) -> str:
        if self._inspected_look:
            return self._inspected_look.text
        focus = self._hovered or self._hovered_look or self._focus()
        if isinstance(focus, BoundPoint):
            return focus.point.description
        if isinstance(focus, WorldLook):
            return f"Press E to inspect {focus.name}."
        return ""

    def _tile(self, position: tuple[float, float] | None = None) -> tuple[int, int]:
        x, y = position or self._position
        return int(x // TILE), int(y // TILE)

    def _position_clear(self, position: tuple[float, float]) -> bool:
        if not self._navigation_spec:
            return False
        # Feet occupy a small square; sprite coats may overlap a wall naturally.
        x, y = position
        return all(self._navigation_spec.passable((int((x + dx) // TILE), int((y + dy) // TILE))) for dx, dy in ((-3, -3), (3, -3), (-3, 3), (3, 3)))

    def _move(self, dx: float, dy: float) -> None:
        x, y = self._position
        if self._position_clear((x + dx, y)):
            x += dx
        if self._position_clear((x, y + dy)):
            y += dy
        self._position = (x, y)
        if abs(dx) > abs(dy):
            self._direction = 2 if dx > 0 else 1
        elif dy:
            self._direction = 0 if dy > 0 else 3

    def update(self, dt: float, keys: Any = None, *, reduced_motion: bool = False) -> None:
        if not self.active:
            return
        # Bounded substeps avoid tunneling through a tile when a frame stalls.
        remaining = max(0.0, min(float(dt), 0.25))
        self._time += remaining
        pg = self.pg
        held = self._held if keys is None else {key for key in (pg.K_w, pg.K_a, pg.K_s, pg.K_d) if keys[key]}
        dx = float(pg.K_d in held) - float(pg.K_a in held)
        dy = float(pg.K_s in held) - float(pg.K_w in held)
        length = hypot(dx, dy)
        if length:
            self._path.clear()
            self._clicked_point = None
            self._inspected_look = None
        moved = False
        while remaining > 0:
            step = min(remaining, 0.025)
            remaining -= step
            before = self._position
            if length:
                self._move(dx / length * self.SPEED * step, dy / length * self.SPEED * step)
            elif self._path:
                tx, ty = self._path[0]
                x, y = self._position
                delta_x, delta_y = tx - x, ty - y
                distance = hypot(delta_x, delta_y)
                if distance <= self.SPEED * step:
                    self._move(delta_x, delta_y)
                    if hypot(self._position[0] - tx, self._position[1] - ty) < 0.1:
                        self._path.popleft()
                    else:
                        self._path.clear()
                elif distance:
                    self._move(delta_x / distance * self.SPEED * step, delta_y / distance * self.SPEED * step)
            moved |= before != self._position
        self._walking = moved
        if moved and not reduced_motion:
            self._walk_time += max(0.0, min(float(dt), 0.25))
        if self.spec:
            self._positions[self.spec.key] = self._position

    def _local_position(self, screen_position: tuple[int, int]) -> tuple[float, float] | None:
        if not self._rect.width or not self._rect.collidepoint(screen_position):
            return None
        return ((screen_position[0] - self._rect.left) * WORLD_SIZE[0] / self._rect.width, (screen_position[1] - self._rect.top) * WORLD_SIZE[1] / self._rect.height)

    def _point_at(self, position: tuple[float, float]) -> BoundPoint | None:
        nearby = [bound for bound in self.points if (
            hypot(position[0] - bound.point.position[0], position[1] - bound.point.position[1]) <= 13
            or hypot(position[0] - bound.point.position[0] - 7, position[1] - bound.point.position[1] + 17) <= 8
        )]
        return min(nearby, key=lambda bound: hypot(position[0] - bound.point.position[0], position[1] - bound.point.position[1])) if nearby else None

    def _look_at(self, position: tuple[float, float]) -> WorldLook | None:
        if not self.spec:
            return None
        nearby = [look for look in self.spec.looks if (
            hypot(position[0] - look.position[0], position[1] - look.position[1]) <= 9
            or hypot(position[0] - look.position[0], position[1] - look.position[1] + 10) <= 7
        )]
        return min(nearby, key=lambda look: hypot(position[0] - look.position[0], position[1] - look.position[1])) if nearby else None

    def walk_to(self, target: tuple[int, int], *, point: WorldPoint | WorldLook | None = None) -> bool:
        """Choose the shortest reachable adjacent tile for a marked feature."""
        if not self._navigation_spec:
            return False
        start = self._tile()
        targets = interaction_tiles(self._navigation_spec, point) if point else (target,)
        routes = [(shortest_path(self._navigation_spec, start, tile), tile) for tile in targets if self._navigation_spec.passable(tile)]
        routes = [(route, tile) for route, tile in routes if route or tile == start]
        if not routes:
            return False
        route, _tile = min(routes, key=lambda item: len(item[0]))
        # First center within the current tile, then follow tile centers.  This
        # stops diagonal corner cutting after a manually controlled movement.
        centers = [(start[0] * TILE + TILE / 2, start[1] * TILE + TILE / 2)]
        centers.extend((x * TILE + TILE / 2, y * TILE + TILE / 2) for x, y in route)
        self._path = deque(centers)
        return True

    def handle_event(self, event: Any) -> tuple[bool, int | None]:
        if not self.active:
            return False, None
        pg = self.pg
        movement = (pg.K_w, pg.K_a, pg.K_s, pg.K_d)
        if event.type == pg.KEYUP and event.key in movement:
            self._held.discard(event.key)
            return True, None
        if event.type == getattr(pg, "WINDOWFOCUSLOST", -1):
            self._held.clear()
            return False, None
        if event.type == pg.KEYDOWN:
            if event.key in movement:
                self._held.add(event.key)
                return True, None
            if event.key in (pg.K_e, pg.K_RETURN, pg.K_KP_ENTER):
                if self._inspected_look:
                    self._inspected_look = None
                    return True, None
                focus = self._focus()
                if isinstance(focus, WorldLook):
                    self._inspected_look = focus
                    self._path.clear()
                    self._held.clear()
                return True, focus.answer if isinstance(focus, BoundPoint) else None
            if event.key == pg.K_ESCAPE and self._inspected_look:
                self._inspected_look = None
                return True, None
        if event.type == pg.MOUSEMOTION:
            local = self._local_position(event.pos)
            self._hovered = self._point_at(local) if local else None
            self._hovered_look = self._look_at(local) if local and self._hovered is None else None
            return False, None
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
            local = self._local_position(event.pos)
            if local is None:
                return False, None
            self._inspected_look = None
            bound = self._point_at(local)
            if bound:
                nearest = self._nearest()
                if self._clicked_point == bound.point.key and nearest and nearest.point.key == bound.point.key:
                    return True, bound.answer
                self._clicked_point = bound.point.key
                self.walk_to(bound.point.tile, point=bound.point)
            elif (look := self._look_at(local)) is not None:
                if self._clicked_point == "look:" + look.key and hypot(self._position[0] - look.position[0], self._position[1] - look.position[1]) <= self.INTERACTION_DISTANCE:
                    self._inspected_look = look
                    self._path.clear()
                    self._held.clear()
                else:
                    self._clicked_point = "look:" + look.key
                    self.walk_to(look.tile, point=look)
            else:
                self._clicked_point = None
                self.walk_to((int(local[0] // TILE), int(local[1] // TILE)))
            return True, None
        return False, None

    def _assets(self) -> None:
        if self._atlas is None:
            try:
                self._atlas = self.pg.image.load(str(ASSET_DIRECTORY / "world-characters.png")).convert_alpha()
            except (OSError, ValueError, self.pg.error):
                # A partial installation must never remove a story choice.
                self._atlas = self.pg.Surface((80, 288), self.pg.SRCALPHA)
                for row in range(12):
                    for frame in range(4):
                        x, y = frame * 20, row * 24
                        self.pg.draw.rect(self._atlas, (72, 103, 91), (x + 6, y + 9, 8, 11))
                        self.pg.draw.rect(self._atlas, (197, 166, 117), (x + 7, y + 4, 6, 5))
                        self.pg.draw.rect(self._atlas, (22, 26, 29), (x + 6, y + 20, 8, 2))
        if self.spec and self.spec.key not in self._backgrounds:
            try:
                self._backgrounds[self.spec.key] = self.pg.image.load(str(ASSET_DIRECTORY / f"world-{self.spec.key}.png")).convert()
            except (OSError, ValueError, self.pg.error):
                background = self.pg.Surface(WORLD_SIZE)
                for y, row in enumerate(self.spec.grid):
                    for x, glyph in enumerate(row):
                        color = (44, 53, 51) if glyph in WALKABLE else (27, 36, 41)
                        self.pg.draw.rect(background, color, (x * TILE, y * TILE, TILE - 1, TILE - 1))
                self._backgrounds[self.spec.key] = background

    def _sprite(self, name: str, direction: int = 0, frame: int = 0) -> Any:
        return self._atlas.subsurface(character_frame_rect(name, direction=direction, frame=frame))

    def _draw_character(self, name: str, position: tuple[float, float], *, direction: int = 0, frame: int = 0) -> None:
        x, y = round(position[0]), round(position[1])
        self.pg.draw.ellipse(self._native, (12, 17, 19), (x - 6, y - 3, 12, 5))
        self._native.blit(self._sprite(name, direction, frame), (x - 10, y - 21))

    def _ambient(self, reduced_motion: bool) -> None:
        if not self.spec:
            return
        pg = self.pg
        tick = 0 if reduced_motion else int(self._time * 1000)
        overlay = pg.Surface(WORLD_SIZE, pg.SRCALPHA)
        for index, (x, y) in enumerate(self.spec.lights):
            cx, cy = x * TILE + 8, y * TILE + (5 if self.spec.key != "lantern" else -10)
            shimmer = 0 if reduced_motion else ((tick // 190 + index * 3) % 4)
            for radius, alpha in ((26, 9), (18, 14), (11, 22), (5, 38)):
                pg.draw.circle(overlay, (235, 164, 69, alpha + shimmer), (cx, cy), radius)
            pg.draw.rect(overlay, (255, 215, 125, 235), (cx, cy - shimmer // 2, 1, 3))
        if self.spec.ambience == "rain" and not reduced_motion:
            for index in range(25):
                x = (index * 83 + tick // 70) % WORLD_SIZE[0]
                y = (index * 47 + tick // 35 * 3) % WORLD_SIZE[1]
                pg.draw.line(overlay, (120, 161, 170, 65), (x, y), (x - 1, y + 3))
        elif self.spec.ambience == "water":
            for y, row in enumerate(self.spec.grid):
                for x, cell in enumerate(row):
                    if cell == "~":
                        offset = (tick // 390 + x + y) % 7
                        pg.draw.line(overlay, (126, 164, 164, 70), (x * TILE + 3, y * TILE + offset + 4), (x * TILE + 10, y * TILE + offset + 4))
        elif self.spec.ambience == "dust" and not reduced_motion:
            for index in range(9):
                x = (index * 43 + tick // 210) % 286 + 16
                y = (index * 31 + tick // 380) % 190 + 22
                pg.draw.rect(overlay, (190, 178, 133, 110), (x, y, 1, 1))
        self._native.blit(overlay, (0, 0))

    def draw(self, surface: Any, rect: Any, *, now_ms: int | None = None, reduced_motion: bool = False) -> Any:
        if not self.spec:
            return self.pg.Rect(rect)
        self._assets()
        pg = self.pg
        self._native.blit(self._backgrounds[self.spec.key], (0, 0))
        self._ambient(reduced_motion)
        for x, y in self._path:
            pg.draw.rect(self._native, (74, 116, 109), (round(x), round(y), 1, 1))
        frame = int(self._walk_time * 8) % 4 if self._walking and not reduced_motion else 0
        characters = [(self._position[1], "traveler", self._position, self._direction, frame)]
        for name, tile in self.spec.actors:
            position = (tile[0] * TILE + TILE / 2, tile[1] * TILE + TILE / 2)
            sprite_frame = 0 if reduced_motion else int(self._time * 1.3) % 4
            characters.append((position[1], name, position, 0, sprite_frame))
        for point in self._character_points:
            # Conversations can finish while their companions remain here.
            idle_frame = 0 if reduced_motion or point.sprite == "edrin" else int(self._time * 1.4) % 4
            characters.append((point.position[1], point.sprite, point.position, 0, idle_frame))
        for _y, name, position, direction, sprite_frame in sorted(characters):
            self._draw_character(name, position, direction=direction, frame=sprite_frame)
        focus = self._focus()
        nearest = focus if isinstance(focus, BoundPoint) else None
        for bound in self.points:
            x, y = map(round, bound.point.position)
            focused = nearest is not None and nearest.point.key == bound.point.key
            hovered = self._hovered is not None and self._hovered.point.key == bound.point.key
            color = (248, 213, 126) if focused or hovered else (139, 184, 170)
            pg.draw.circle(self._native, (14, 21, 24), (x + 7, y - 17), 5)
            pg.draw.circle(self._native, color, (x + 7, y - 17), 5, 1)
            number = self._small_font.render(str(bound.answer), False, color)
            self._native.blit(number, number.get_rect(center=(x + 7, y - 17)))
            if focused:
                pg.draw.ellipse(self._native, color, (x - 8, y - 4, 17, 8), 1)
        for look in self.spec.looks:
            x, y = map(round, look.position)
            selected = focus is look or self._hovered_look is look
            color = (219, 185, 112) if selected else (82, 128, 117)
            pg.draw.polygon(self._native, (12, 19, 23), ((x, y - 14), (x + 4, y - 10), (x, y - 6), (x - 4, y - 10)))
            pg.draw.polygon(self._native, color, ((x, y - 13), (x + 3, y - 10), (x, y - 7), (x - 3, y - 10)), 1)
        # Native-size labels stay crisp after the same nearest-neighbor scale
        # as the map.  Opaque slim bands keep names legible over busy artwork.
        pg.draw.rect(self._native, (13, 18, 22), (7, 7, min(306, len(self.spec.name) * 6 + 12), 15))
        self._native.blit(self._font.render(self.spec.name, False, (220, 186, 115)), (13, 10))
        bound = self._hovered or self._hovered_look or focus
        if isinstance(bound, BoundPoint):
            caption = f"{bound.answer}  {bound.point.name}"
        elif isinstance(bound, WorldLook):
            caption = f"LOOK  {bound.name}"
        else:
            caption = "WASD WALK    E INTERACT    CLICK TO WALK"
        label = self._small_font.render(caption, False, (225, 216, 184))
        strip = label.get_rect(midbottom=(160, 235)).inflate(12, 8)
        pg.draw.rect(self._native, (13, 18, 22), strip)
        self._native.blit(label, label.get_rect(center=strip.center))
        if self._inspected_look:
            words = self._inspected_look.text.split()
            lines: list[str] = []
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if self._small_font.size(candidate)[0] > 266 and current:
                    lines.append(current)
                    current = word
                else:
                    current = candidate
            if current:
                lines.append(current)
            bubble = pg.Rect(20, 211 - (len(lines) + 3) * 10, 280, (len(lines) + 3) * 10)
            pg.draw.rect(self._native, (13, 19, 24), bubble)
            pg.draw.rect(self._native, (115, 145, 125), bubble, 1)
            self._native.blit(self._font.render(self._inspected_look.name.upper(), False, (222, 185, 111)), (bubble.left + 7, bubble.top + 5))
            for index, text in enumerate(lines):
                self._native.blit(self._small_font.render(text, False, (220, 214, 186)), (bubble.left + 7, bubble.top + 17 + index * 10))
            self._native.blit(self._small_font.render("E / ENTER / ESC  Close", False, (129, 166, 149)), (bubble.left + 7, bubble.bottom - 10))
        target_rect = pg.Rect(rect)
        scale = min(target_rect.width / WORLD_SIZE[0], target_rect.height / WORLD_SIZE[1])
        if scale >= 2:
            scale = int(scale)
        size = (max(1, int(WORLD_SIZE[0] * scale)), max(1, int(WORLD_SIZE[1] * scale)))
        picture = pg.transform.scale(self._native, size)
        self._rect = picture.get_rect(center=target_rect.center)
        surface.blit(picture, self._rect)
        return self._rect.copy()
