"""Walkable pixel worlds at existing story decisions.

The worlds are a presentation of the choices, not a second game state.  A
point always returns the index of an option in the current request.  Nothing
here changes inventory, relationships, flags, or save files.  Pygame is passed
in by the main-thread renderer and is never imported by the story worker.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from math import hypot
from pathlib import Path
from typing import Any, Sequence

from .pixel_theme import load_font, wrap_text


TILE = 16
WORLD_SIZE = (320, 240)
GRID_SIZE = (20, 15)
ASSET_DIRECTORY = Path(__file__).resolve().parent / "pixel_assets"
WALKABLE = frozenset(".,=+:;-")
CHARACTER_CELL = (20, 24)
CHARACTER_ATLAS_ROWS = {
    "mara": 4, "tobin": 5, "calenor": 6, "edrin": 7, "orc": 8,
    "orc_scout": 9, "patron": 10, "butterbur": 11,
}
MOTION_CHARACTERS = (
    "traveler", "mara", "tobin", "calenor", "orc", "orc_scout", "patron",
    "butterbur", "ned", "warg", "orc_sapper", "captive", "orc_archer",
    "wayfarer", "scout", "healer",
)
MOTION_ROWS = 11
MOTION_FRAMES = 8
ORIGIN_PORTRAITS = ("wayfarer", "scout", "healer")


def hero_sprite_name(origin: str | None) -> str:
    """Origin changes clothing; the equipped combat weapon remains separate."""
    name = str(origin or "").strip().casefold()
    name = {"bree_wayfarer": "wayfarer", "bree wayfarer": "wayfarer", "bree-land wayfarer": "wayfarer", "north_road_scout": "scout", "north road scout": "scout", "north-road scout": "scout", "healers_apprentice": "healer", "healer's apprentice": "healer", "healers apprentice": "healer"}.get(name, name)
    return name if name in ORIGIN_PORTRAITS else "traveler"


def origin_portrait_rect(origin: str | None) -> tuple[int, int, int, int] | None:
    """Three original 20×24 portraits in world-portraits.png, or fallback."""
    name = hero_sprite_name(origin)
    return (ORIGIN_PORTRAITS.index(name) * 20, 0, 20, 24) if name in ORIGIN_PORTRAITS else None


def motion_frame_rect(name: str = "traveler", *, direction: int = 0, frame: int = 0, pose: str = "idle") -> tuple[int, int, int, int]:
    """Eight-frame blocks: four walk/idle rows, then guard/sleep/snared.

    Legacy world-characters.png keeps its original geometry and pixels.
    """
    row = {"walk": direction % 4, "idle": 4 + direction % 4, "guard": 8, "sleep": 9, "snared": 10}.get(pose, 4 + direction % 4)
    character = MOTION_CHARACTERS.index(name) if name in MOTION_CHARACTERS else 0
    return frame % MOTION_FRAMES * 20, (character * MOTION_ROWS + row) * 24, 20, 24


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
    aliases: tuple[str, ...] = ()
    pose: str = "idle"
    decoration: str | None = None

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
    followers: tuple[str, ...] = ()

    def passable(self, tile: tuple[int, int]) -> bool:
        x, y = tile
        return 0 <= x < GRID_SIZE[0] and 0 <= y < GRID_SIZE[1] and self.grid[y][x] in WALKABLE


@dataclass(frozen=True)
class BoundPoint:
    point: WorldPoint
    answer: int
    option: str


@dataclass
class _Follower:
    name: str
    position: tuple[float, float]
    direction: int = 0
    walk_time: float = 0.0
    walking: bool = False
    path: deque[tuple[float, float]] = field(default_factory=deque)
    target: tuple[int, int] | None = None


def _grid(fill: str = ".", *, edge: str = "#") -> list[list[str]]:
    result = [[fill] * GRID_SIZE[0] for _ in range(GRID_SIZE[1])]
    for x in range(GRID_SIZE[0]):
        result[0][x] = result[-1][x] = edge
    for row in result:
        row[0] = row[-1] = edge
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
    return {key: replace(spec, looks=details[key], followers=("mara", "tobin") if key in {"wayhouse", "hall"} else ()) for key, spec in maps.items()}


def _journey_maps() -> dict[str, WorldMap]:
    """The roads between the original hubs, grounded in existing scenes."""
    gate = _grid(",")
    _fill(gate, (1, 4, 18, 1), "#")
    _fill(gate, (9, 1, 3, 13), "=")
    _fill(gate, (3, 6, 6, 3), ";")
    for x, y in ((4, 6), (5, 6), (6, 6)):
        gate[y][x] = "s"
    for x, y in ((2, 2), (5, 2), (15, 2), (17, 3), (3, 11), (16, 10), (14, 12)):
        gate[y][x] = "V"
    gate_points = (
        WorldPoint("star", "The third stone", (6, 6), "Press the broken star into the third stone", "The broken star faces an old mark beneath the mortar."),
        WorldPoint("token", "The hidden notch", (5, 7), "Use Calenor's oak-leaf Ranger token as a lever", "A narrow notch cuts into the weathered boundary stone."),
        WorldPoint("weapon", "Loose mortar", (7, 7), "Pry the stone free with your weapon", "The stone's mortar has loosened in the long rain."),
    )
    gate_looks = (
        WorldLook("old_gate", "The north gate", (10, 4), "The north gate leans into the storm. Beyond it, the northern road lies empty."),
        WorldLook("boundary_stones", "Boundary stones", (4, 6), "Three weathered stones stand beside the gate. Calenor's letter told you which one to count."),
        WorldLook("wet_hawthorn", "Wet hawthorn", (16, 10), "Rain holds in the hawthorn. One distant horn answers from the eastern dark."),
    )

    fork = _grid(",")
    for x in range(20):
        fork[0][x] = fork[-1][x] = "V"
    for row in fork:
        row[0] = row[-1] = "V"
    _fill(fork, (9, 1, 3, 13), "=")
    _fill(fork, (2, 4, 8, 2), ";")
    _fill(fork, (5, 6, 6, 2), ";")
    _fill(fork, (11, 6, 7, 3), ";")
    for x, y in ((3, 2), (6, 2), (7, 3), (15, 3), (17, 4), (3, 10), (6, 11), (14, 11), (17, 12)):
        fork[y][x] = "V"
    fork[3][3] = "r"
    fork[3][5] = "L"
    fork_points = (
        WorldPoint("ranger_marks", "The marked hill path", (4, 3), "Follow Calenor's tiny Ranger marks through the hills", "Small Ranger cuts wait beneath a root at the western fork."),
        WorldPoint("enemy_tracks", "The muddy trail", (16, 7), "Follow the Orc and warg tracks before rain erases them", "Bootprints and broad paw marks cross the wet eastern ground."),
        WorldPoint("cart_road", "The old cart-road", (10, 2), "Take the old cart-road and trust speed over secrecy", "The wider road runs straight toward the marsh."),
    )
    fork_looks = (
        WorldLook("last_lamps", "Bree's last lamps", (9, 12), "Bree's last lamps sink behind wet hawthorn. The horns behind you begin moving east."),
        WorldLook("cart_ruts", "Old cart ruts", (11, 5), "Long ruts cut through the exposed road. There is little shelter between its hedges."),
        WorldLook("root_sign", "A turned stone", (5, 3), "A pale turned stone rests beneath the root beside the narrow hill path."),
    )

    camp = _grid(",", edge="E")
    _fill(camp, (13, 1, 6, 6), "~")
    _fill(camp, (1, 9, 3, 5), "~")
    _fill(camp, (5, 6, 8, 6), ";")
    for x, y in ((3, 3), (4, 4), (12, 2), (12, 4), (14, 7), (15, 8), (3, 8), (4, 10), (12, 12), (17, 11)):
        camp[y][x] = "E"
    camp[5][8] = "s"
    camp[7][8] = "C"
    camp_points = (
        WorldPoint("keep_watch", "The sheltered ember", (8, 7), "Take it yourself and let both companions sleep", "The little ember is sheltered in the standing stone's lee."),
        WorldPoint("wake_mara", "Mara's resting place", (6, 9), "Wake Mara", "Mara has set her boots toward the road.", "mara", pose="sleep"),
        WorldPoint("wake_tobin", "Tobin's resting place", (11, 9), "Wake Tobin", "Tobin sleeps with one hand around his watch-whistle.", "tobin", pose="sleep"),
    )
    camp_looks = (
        WorldLook("standing_stone", "Leaning standing stone", (8, 5), "The ancient stone takes the worst of the wind. Forgotten walls show their teeth beyond the reeds."),
        WorldLook("camp_reeds", "The reed beds", (14, 7), "Midgewater spreads ahead in black pools and reed beds. Somewhere among them a weak watch-whistle sounds."),
        WorldLook("small_ember", "A fire without flame", (7, 7), "Mara made a smokeless ember under her cloak. Its warmth holds close to the ground."),
    )

    post = _grid("~", edge="~")
    _fill(post, (2, 10, 16, 3), ";")
    _fill(post, (2, 2, 4, 9), ";")
    _fill(post, (5, 2, 8, 3), ";")
    _fill(post, (10, 4, 6, 2), ":")
    _fill(post, (12, 4, 6, 5), ":")
    _fill(post, (13, 2, 5, 2), ";")
    _fill(post, (9, 6, 3, 6), "=")
    for x, y in ((2, 2), (4, 2), (2, 5), (4, 6), (5, 8), (13, 2), (17, 2), (17, 4), (2, 13), (16, 12)):
        post[y][x] = "E"
    post[7][15] = "s"
    post[8][13] = "P"
    post_points = (
        WorldPoint("reed_circle", "The reed-side approach", (3, 7), "Circle through the reeds and approach the tracker unseen", "A narrow muddy line circles the black pool."),
        WorldPoint("low_crossing", "The low crossing", (6, 10), "Send Tobin low across the water while you draw the enemy's eyes", "The pool offers a low approach beneath the tracker's sightline."),
        WorldPoint("watch_stones", "The old causeway stones", (10, 10), "Raise the silver star and command the old stones to answer", "Old stone slabs break the black water at the causeway."),
        WorldPoint("causeway", "The causeway entrance", (14, 10), "Rush the causeway before the tracker can loose", "The tracker waits for a step onto the exposed causeway.", aliases=("Break the Dwarf-smoke flask across the causeway",)),
    )
    post_looks = (
        WorldLook("post_pool", "The black pool", (7, 9), "Water surrounds the fallen watch-stone. Across it, yellow eyes wait between the reeds."),
        WorldLook("broken_post", "The fallen watch post", (13, 8), "The drowned watch post has fallen into its own causeway."),
        WorldLook("ned_snare", "Ned's black-rope snare", (16, 7), "Ned is alive inside the black-rope snare. One leg lies trapped beneath fallen masonry; the tracker has left him as bait."),
    )

    bridge = _grid("X")
    _fill(bridge, (1, 1, 5, 13), ":")
    _fill(bridge, (15, 1, 4, 13), ":")
    _fill(bridge, (5, 6, 11, 3), "-")
    for x in (6, 10, 14):
        bridge[5][x] = bridge[9][x] = "P"
    bridge[5][4] = bridge[9][4] = "L"
    bridge_points = (
        WorldPoint("bridgehead", "The exposed bridgehead", (5, 7), "Cross the exposed bridgehead", "The old bridge gives back every footfall."),
        WorldPoint("hidden_stair", "The Warden stair", (3, 3), "Descend the hidden Warden stair", "A known Warden stair descends below the bridge's western arch.", decoration="stairs"),
        WorldPoint("ropes", "The western rope anchor", (4, 5), "Defend the ropes and keep the road open", "Ancient ropes strain above a lightless gulf."),
        WorldPoint("sapper", "The pitch-jar sightline", (4, 9), "Hunt the sapper before the pitch is lit", "Across the gulf, an Orc sapper works beside the old ropes."),
    )
    bridge_looks = (
        WorldLook("echo_gulf", "The bottomless gulf", (7, 7), "The gulf beneath Echo Bridge gives back sound without showing its depth."),
        WorldLook("stone_arch", "An ancient arch", (6, 5), "Three stone arches carry the bridge above the darkness."),
    )

    drowned = _grid("~")
    _fill(drowned, (2, 7, 5, 7), ":")
    _fill(drowned, (5, 9, 9, 3), "=")
    _fill(drowned, (10, 1, 4, 10), "=")
    _fill(drowned, (3, 4, 8, 3), "=")
    _fill(drowned, (14, 7, 5, 4), ":")
    drowned[4][3] = "b"
    drowned[6][12] = "n"
    drowned[7][16] = "L"
    drowned_points = (
        WorldPoint("prisoners", "The flooded cage-road", (4, 5), "Reach the prisoners before the sluice horn", "The flooded cut turns toward the cages beyond the bend."),
        WorldPoint("wards", "The ward-stone turn", (16, 8), "Reach the flood wards before they are broken", "Old ward-stones stand above the rising black water."),
        WorldPoint("calenor", "The northern passage", (11, 2), "Reach Calenor before the Ash-Hand moves him", "The shortest line continues into the dark northern road."),
    )
    drowned_looks = (
        WorldLook("prison_cart", "A broken prison cart", (3, 4), "A prison cart and its snapped wheel lean into the shallow floodwater."),
        WorldLook("drowned_marker", "The drowned milestone", (12, 6), "Black water climbs the milestones, swallowing the old names from the bottom upward."),
    )

    sluice = _grid(":")
    _fill(sluice, (1, 11, 15, 3), "~")
    _fill(sluice, (3, 3, 3, 2), "K")
    _fill(sluice, (7, 3, 3, 2), "K")
    _fill(sluice, (16, 9, 3, 5), ":")
    sluice[3][14] = "W"
    sluice[5][14] = "L"
    sluice[8][11] = "d"
    sluice_points = (
        WorldPoint("captives", "The captives' ledge", (6, 5), "Rescue the captives before the water reaches them", "The captives have been roped together for the march east."),
        WorldPoint("wards", "The flood wards", (14, 6), "Preserve the flood wards and keep the old road alive", "The last Warden wards begin to drown below the cages."),
        WorldPoint("onward", "The eastward passage", (17, 10), "Race onward while the Ash-Hand is still unready", "The road continues beyond the sluice's eastern shelf."),
        WorldPoint("locks", "The cage locks", (3, 5), "Pick the cage locks beneath the horn's next note", "Rusted iron locks bind the captive cages."),
        WorldPoint("hinges", "The rusted hinges", (9, 5), "Break the rusted hinges with Calenor's sword", "The old cage hinges have rusted in the rising damp."),
        WorldPoint("drain", "The Warden drain", (11, 8), "Open the Warden drain and lead them through the dry channel", "An old drain lies below the eight-spoked floodgate wheel."),
    )
    sluice_looks = (
        WorldLook("iron_bars", "Iron cage bars", (4, 3), "Two iron cages hold reaching prisoners above the flooded ledge."),
        WorldLook("floodwheel", "The eight-spoked wheel", (14, 3), "An enormous eight-spoked floodgate wheel rises above the water."),
        WorldLook("rising_water", "Rising floodwater", (8, 11), "The sluice horn sounds beyond the bend. Below the stone shelf, the water keeps rising."),
    )

    refuge = _grid(":")
    _fill(refuge, (7, 3, 6, 5), "H")
    refuge[7][10] = "+"
    _fill(refuge, (1, 1, 5, 1), "r")
    _fill(refuge, (14, 1, 5, 1), "r")
    for x, y in ((3, 2), (5, 4), (14, 3), (17, 2), (15, 8), (3, 10)):
        refuge[y][x] = "r"
    refuge_points = (
        WorldPoint("handprints", "The low western wall", (4, 3), "Follow the child-height handprints", "Small handprints follow the low wall through the refuge."),
        WorldPoint("service", "The Warden service way", (16, 5), "Take the Warden service passage", "A narrow service passage runs beside the rooted house."),
        WorldPoint("dormitory", "The ruined dormitory", (10, 11), "Cross the ruined dormitory", "The dormitory lies on the southern side of the refuge."),
    )
    refuge_looks = (
        WorldLook("ash_shackle", "A cold shackle", (6, 8), "A cold shackle lies in the ash, stamped by Ghorak's forge."),
        WorldLook("great_roots", "The enormous roots", (14, 3), "The roots shelter a small stone house intact beneath the hills."),
        WorldLook("dormitory_stone", "Dormitory stone", (11, 12), "Ash holds in the seams of the old dormitory's stone."),
    )

    return {
        "north-gate": WorldMap("north-gate", "BREE'S NORTH GATE", _freeze(gate), (10, 12), gate_points, "rain", ((9, 8),), (("tobin", (10, 8)), ("mara", (13, 3))), gate_looks),
        "road-fork": WorldMap("road-fork", "OUT THROUGH THE HEDGE", _freeze(fork), (10, 12), fork_points, "rain", (), (), fork_looks, ("mara", "tobin")),
        "camp": WorldMap("camp", "A FIRE WITHOUT FLAME", _freeze(camp), (9, 11), camp_points, "marsh", ((8, 7),), (), camp_looks),
        "watch-post": WorldMap("watch-post", "THE LOST WHISTLE", _freeze(post), (9, 12), post_points, "marsh", (), (("ned", (15, 7)), ("warg", (16, 5)), ("orc_archer", (14, 3))), post_looks, ("mara", "tobin")),
        "bridge": WorldMap("bridge", "ECHO BRIDGE", _freeze(bridge), (3, 11), bridge_points, "gulf", (), (("orc_sapper", (16, 6)), ("orc", (16, 8)), ("orc_archer", (17, 7))), bridge_looks, ("mara", "tobin")),
        "drowned-mile": WorldMap("drowned-mile", "THE DROWNED MILE", _freeze(drowned), (5, 11), drowned_points, "water", (), (), drowned_looks, ("mara", "tobin")),
        "sluice": WorldMap("sluice", "PRISONERS OF ASH", _freeze(sluice), (11, 10), sluice_points, "water", (), (("captive", (4, 4)), ("captive", (8, 4))), sluice_looks, ("mara", "tobin")),
        "refuge": WorldMap("refuge", "THE HOUSE UNDER ASH", _freeze(refuge), (9, 12), refuge_points, "ash", (), (), refuge_looks, ("mara", "tobin")),
    }


WORLD_MAPS = {**_maps(), **_journey_maps()}
DEPTH_CELL = (32, 40)
DEPTH_COLUMNS = 16
DEPTH_OBJECTS = tuple(
    (key, x, y, glyph)
    for key, spec in WORLD_MAPS.items()
    for y, row in enumerate(spec.grid)
    for x, glyph in enumerate(row)
    if glyph in {"V", "E", "s", "n", "L", "P", "Q", "W"}
)


def depth_frame_rect(index: int) -> tuple[int, int, int, int]:
    """Original prop silhouettes, each padded for its canopy or tall crown."""
    return index % DEPTH_COLUMNS * DEPTH_CELL[0], index // DEPTH_COLUMNS * DEPTH_CELL[1], *DEPTH_CELL


MAP_HEADINGS = {
    "WHAT WILL YOU DO?": "pony",
    "WHERE WILL YOU INVESTIGATE?": "bree",
    "EXPLORE THE BURIED WAYHOUSE": "wayhouse",
    "EXPLORE THE HALL OF EIGHT": "hall",
    "BEFORE THE LAST SEAL": "lantern",
    "HOW WILL YOU OPEN CALENOR'S CACHE?": "north-gate",
    "CHOOSE THE APPROACH TO MIDGEWATER": "road-fork",
    "WHO TAKES THE LAST WATCH?": "camp",
    "HOW DO YOU REACH NED?": "watch-post",
    "HOW DO YOU REACH ECHO BRIDGE?": "bridge",
    "WHAT MUST SURVIVE AT ECHO BRIDGE?": "bridge",
    "WHO DO YOU REACH FIRST?": "drowned-mile",
    "THE SLUICE HORN SOUNDS. CHOOSE.": "sluice",
    "HOW DO YOU FREE THEM?": "sluice",
    "CHOOSE A WAY THROUGH THE REFUGE": "refuge",
}


def missing_world_assets() -> list[Path]:
    """The installer can validate worlds alongside the original illustrations."""
    paths = [ASSET_DIRECTORY / f"world-{key}.png" for key in WORLD_MAPS]
    paths.append(ASSET_DIRECTORY / "world-characters.png")
    paths.extend(ASSET_DIRECTORY / name for name in ("world-motion.png", "world-portraits.png", "world-depth.png"))
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
    return option.casefold() in {point.option.casefold(), *(alias.casefold() for alias in point.aliases)}


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
        self._actors: tuple[tuple[str, tuple[int, int]], ...] = ()
        self._hero_name = "traveler"
        self._session_identifier: Any = None
        self._followers: list[_Follower] = []
        self._follower_positions: dict[str, dict[str, tuple[float, float]]] = {}
        self._trail: deque[tuple[float, float]] = deque(maxlen=160)
        self._trail_maps: dict[str, tuple[tuple[float, float], ...]] = {}
        self._revealed_details: dict[str, set[str]] = {}
        self._request_identifier: Any = None
        self._positions: dict[str, tuple[float, float]] = {}
        self._directions: dict[str, int] = {}
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
        self._world_fingerprint: tuple[Any, ...] | None = None
        self._inspection_resume: tuple[tuple[Any, ...], str] | None = None
        self._blocked_until = 0.0
        self._rect = pygame.Rect(0, 0, 0, 0)
        self._backgrounds: dict[str, Any] = {}
        self._atlas: Any = None
        self._motion_atlas: Any = None
        self._depth_atlas: Any = None
        self._depth_sprites: dict[str, list[tuple[int, Any, tuple[int, int]]]] = {}
        self._native = pygame.Surface(WORLD_SIZE)
        self._font = load_font(pygame, 9)
        self._small_font = load_font(pygame, 8)
        self._inspection_fonts: dict[int, tuple[Any, Any]] = {}

    def stop_moving(self) -> None:
        """Cancel held and planned movement when focus or a modal interrupts."""
        self._held.clear()
        self._path.clear()
        self._walking = False
        self._clicked_point = None
        for follower in self._followers:
            follower.path.clear()
            follower.walking = False

    @property
    def active(self) -> bool:
        return self.spec is not None

    @property
    def map_key(self) -> str | None:
        return self.spec.key if self.spec else None

    @property
    def player_position(self) -> tuple[float, float]:
        return self._position

    @property
    def party_positions(self) -> dict[str, tuple[float, float]]:
        """Companions are visible followers, never solid navigation obstacles."""
        return {follower.name: follower.position for follower in self._followers}

    @property
    def surface_kind(self) -> str:
        """The material under the traveler's feet, for presentation cues."""
        if not self.spec:
            return "stone"
        x, y = self._tile()
        glyph = self.spec.grid[y][x]
        if glyph == "-" or (glyph == "." and self.spec.key == "pony"):
            return "wood"
        return {",": "grass", ";": "mud"}.get(glyph, "stone")

    def set_request(self, request: Any | None, *, preserve_inspection: bool = False) -> bool:
        """Suspend an inspection only for an explicitly read-only interruption.

        Returning utilities may create a new request identifier. The same
        presentation, map and complete option list must still match before
        the opened look is restored. A normal answer clears the suspension.
        """
        if preserve_inspection and self._inspected_look and self._world_fingerprint:
            self._inspection_resume = (self._world_fingerprint, self._inspected_look.key)
        if self.spec:
            self._positions[self.spec.key] = self._position
            self._directions[self.spec.key] = self._direction
            self._follower_positions[self.spec.key] = self.party_positions
            self._trail_maps[self.spec.key] = tuple(self._trail)
        spec = None
        if request is not None and getattr(request, "story", False) and getattr(request, "kind", None) == "choice":
            spec = map_for_request(request.label, request.options)
        context = getattr(request, "context", {}) or {}
        journey = context.get("journey_id")
        presentation = context.get("presentation_id")
        session = (journey, presentation)
        if (journey is not None or presentation is not None) and session != self._session_identifier:
            self._positions.clear()
            self._directions.clear()
            self._follower_positions.clear()
            self._trail_maps.clear()
            self._revealed_details.clear()
            self._inspection_resume = None
            self._world_fingerprint = None
            # Reloading an earlier save creates a new presentation of the
            # same journey. Physical positions must not leak from its future.
            # Utilities keep the same state and therefore the same session.
            self._session_identifier = session
            self._walk_time = 0.0
        self._hero_name = hero_sprite_name(context.get("origin"))
        self.spec = spec
        self.points = bind_points(spec, request.options) if spec else ()
        if spec:
            revealed = {bound.point.key for bound in self.points if bound.point.decoration}
            if spec.key == "bridge" and request.label.strip().upper() == "HOW DO YOU REACH ECHO BRIDGE?":
                # Re-entering an older save can remove the learned route.
                # This initial menu is authoritative; the next menu keeps
                # the already revealed stairs while choosing its objective.
                self._revealed_details[spec.key] = revealed
            else:
                self._revealed_details.setdefault(spec.key, set()).update(revealed)
        companion_presence = {
            companion["name"].casefold(): companion.get("present", True)
            for companion in context.get("companions", ())
        }
        self._character_points = tuple(point for point in spec.points if point.sprite and companion_presence.get(point.sprite, True)) if spec else ()
        self._actors = tuple((name, tile) for name, tile in spec.actors if companion_presence.get(name, True)) if spec else ()
        self._navigation_spec = None
        if spec:
            navigation_grid = [list(row) for row in spec.grid]
            occupied = [tile for _name, tile in self._actors]
            occupied.extend(point.tile for point in self._character_points)
            for x, y in occupied:
                navigation_grid[y][x] = "N"
            self._navigation_spec = replace(spec, grid=_freeze(navigation_grid))
        identifier = getattr(request, "identifier", None)
        fingerprint = (self._session_identifier, spec.key, tuple(request.options)) if spec else None
        if identifier != self._request_identifier or (spec and fingerprint != self._world_fingerprint):
            self._path.clear()
            self._held.clear()
            self._clicked_point = None
            self._hovered = None
            self._hovered_look = None
            self._inspected_look = None
            self._blocked_until = 0.0
            self._walking = False
        self._request_identifier = identifier
        if spec is None:
            self.stop_moving()
            self._inspected_look = None
            if not preserve_inspection:
                self._inspection_resume = None
        else:
            if self._inspection_resume:
                saved_fingerprint, look_key = self._inspection_resume
                if saved_fingerprint == fingerprint:
                    self._inspected_look = next((look for look in spec.looks if look.key == look_key), None)
                self._inspection_resume = None
            self._world_fingerprint = fingerprint
        self._followers = []
        self._trail.clear()
        if spec:
            spawn = (spec.spawn[0] * TILE + TILE / 2, spec.spawn[1] * TILE + TILE / 2)
            self._position = self._positions.get(spec.key, spawn)
            self._direction = self._directions.get(spec.key, 0)
            if not self._position_clear(self._position):
                # A companion can return while a utility has suspended the
                # map. Never restore the traveler inside their solid tile.
                tiles = self._reachable_tiles(spec.spawn)
                tile = min(tiles, key=lambda tile: hypot(tile[0] * TILE + 8 - self._position[0], tile[1] * TILE + 8 - self._position[1])) if tiles else spec.spawn
                self._position = (tile[0] * TILE + 8, tile[1] * TILE + 8)
                self._trail_maps.pop(spec.key, None)
            self._trail.extend(self._trail_maps.get(spec.key, (self._position,)))
            previous_followers = self._follower_positions.get(spec.key, {})
            taken = {self._tile()}
            reserved = self._reserved_tiles()
            for name in spec.followers:
                if not companion_presence.get(name, True):
                    continue
                position = previous_followers.get(name)
                if position is None or not self._position_clear(position):
                    tiles = self._reachable_tiles(self._tile())
                    candidates = [tile for tile in tiles if tile not in taken and tile not in reserved]
                    if not tiles:
                        continue
                    tile = min(candidates or list(tiles), key=lambda tile: abs(tile[0] - spec.spawn[0]) + abs(tile[1] - spec.spawn[1]))
                    position = (tile[0] * TILE + TILE / 2, tile[1] * TILE + TILE / 2)
                taken.add(self._tile(position))
                self._followers.append(_Follower(name, position))
        return self.active

    def _reserved_tiles(self) -> set[tuple[int, int]]:
        if not self._navigation_spec:
            return set()
        return {tile for bound in self.points for tile in interaction_tiles(self._navigation_spec, bound.point)}

    def _reachable_tiles(self, start: tuple[int, int]) -> set[tuple[int, int]]:
        if not self._navigation_spec or not self._navigation_spec.passable(start):
            return set()
        frontier, reached = deque([start]), {start}
        while frontier:
            x, y = frontier.popleft()
            for cell in ((x, y - 1), (x - 1, y), (x + 1, y), (x, y + 1)):
                if cell not in reached and self._navigation_spec.passable(cell):
                    reached.add(cell)
                    frontier.append(cell)
        return reached

    def _trail_target(self, gap: float) -> tuple[int, int]:
        previous, distance = self._position, 0.0
        for position in reversed(self._trail):
            distance += hypot(position[0] - previous[0], position[1] - previous[1])
            previous = position
            if distance >= gap:
                return self._tile(position)
        return self._tile(previous)

    def _update_followers(self, dt: float, *, reduced_motion: bool) -> None:
        if not self._navigation_spec or not self._followers:
            return
        # Reduced motion keeps decorative party motion still when the hero
        # stands. A moving hero still has companions on the road.
        if reduced_motion and not self._walking:
            for follower in self._followers:
                follower.walking = False
            return
        reserved, taken = self._reserved_tiles(), {self._tile()}
        for index, follower in enumerate(self._followers):
            target = self._trail_target(28 + index * 22)
            if not self._walking:
                start = self._tile(follower.position)
                tiles = self._reachable_tiles(start)
                nearby = [tile for tile in tiles if tile not in reserved and tile not in taken and hypot(tile[0] * TILE + 8 - self._position[0], tile[1] * TILE + 8 - self._position[1]) <= 52]
                if nearby:
                    target = min(nearby, key=lambda tile: abs(tile[0] - start[0]) + abs(tile[1] - start[1]))
            taken.add(target)
            if target != follower.target or (not follower.path and self._tile(follower.position) != target):
                start = self._tile(follower.position)
                route = shortest_path(self._navigation_spec, start, target)
                follower.path.clear()
                if route or target == start:
                    follower.path.append((start[0] * TILE + 8, start[1] * TILE + 8))
                    follower.path.extend((x * TILE + 8, y * TILE + 8) for x, y in route)
                follower.target = target
            before = follower.position
            remaining = dt
            while follower.path and remaining > 0:
                step = min(remaining, 0.025)
                remaining -= step
                x, y = follower.position
                tx, ty = follower.path[0]
                dx, dy = tx - x, ty - y
                distance = hypot(dx, dy)
                if distance < 0.1:
                    follower.path.popleft()
                    continue
                amount = min(distance, self.SPEED * 1.08 * step)
                position = (x + dx / distance * amount, y + dy / distance * amount)
                if not self._position_clear(position):
                    follower.path.clear()
                    break
                follower.position = position
                follower.direction = (2 if dx > 0 else 1) if abs(dx) > abs(dy) else (0 if dy > 0 else 3)
                if amount == distance:
                    follower.path.popleft()
            follower.walking = before != follower.position
            if follower.walking and not reduced_motion:
                follower.walk_time += dt

    def _nearest(self) -> BoundPoint | None:
        if not self.spec:
            return None
        nearby = [bound for bound in self.points if self._can_interact(bound.point)]
        if not nearby:
            return None
        return min(nearby, key=lambda bound: hypot(self._position[0] - bound.point.position[0], self._position[1] - bound.point.position[1]))

    def _nearest_look(self) -> WorldLook | None:
        if not self.spec:
            return None
        nearby = [look for look in self.spec.looks if self._can_interact(look)]
        return min(nearby, key=lambda look: hypot(self._position[0] - look.position[0], self._position[1] - look.position[1])) if nearby else None

    def _can_interact(self, point: WorldPoint | WorldLook, position: tuple[float, float] | None = None) -> bool:
        """Nearness cannot reach through a wall, table or another character."""
        if not self._navigation_spec:
            return False
        start = position or self._position
        dx, dy = point.position[0] - start[0], point.position[1] - start[1]
        distance = hypot(dx, dy)
        if distance > self.INTERACTION_DISTANCE:
            return False
        previous = self._tile(start)
        steps = max(1, int(distance / 2) + 1)
        for index in range(1, steps + 1):
            tile = self._tile((start[0] + dx * index / steps, start[1] + dy * index / steps))
            if tile != point.tile and not self._navigation_spec.passable(tile):
                return False
            if tile[0] != previous[0] and tile[1] != previous[1]:
                sides = ((tile[0], previous[1]), (previous[0], tile[1]))
                if any(side != point.tile and not self._navigation_spec.passable(side) for side in sides):
                    return False
            previous = tile
        return True

    def _focus(self) -> BoundPoint | WorldLook | None:
        point, look = self._nearest(), self._nearest_look()
        if self._clicked_point and self.spec:
            selected = next((look for look in self.spec.looks if "look:" + look.key == self._clicked_point), None)
            if selected and self._can_interact(selected):
                return selected
            chosen = next((bound for bound in self.points if bound.point.key == self._clicked_point), None)
            if chosen and self._can_interact(chosen.point):
                return chosen
            if self._path and (selected or chosen):
                return None
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
        if self._blocked_until > self._time:
            return "That ground cannot be crossed. Choose a clear path."
        if self._path:
            target = next((bound.point.name for bound in self.points if bound.point.key == self._clicked_point), None)
            if not target and self.spec:
                target = next((look.name for look in self.spec.looks if "look:" + look.key == self._clicked_point), None)
            return f"Walking to {target or 'your destination'}. WASD takes control."
        focus = self._focus()
        if isinstance(focus, BoundPoint):
            return f"[E / ENTER] {focus.option}"
        if isinstance(focus, WorldLook):
            return f"[E / ENTER] Look at {focus.name}"
        if self._hovered:
            return f"{self._hovered.point.name}: click to walk there"
        if self._hovered_look:
            return f"{self._hovered_look.name}: click to walk there"
        return "Click a marked place to walk there."

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

    @property
    def inspection_open(self) -> bool:
        return self._inspected_look is not None

    @property
    def inspection_title(self) -> str:
        """Only an opened discovery has a title for the read-only transcript."""
        return self._inspected_look.name if self._inspected_look else ""

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
            self._blocked_until = 0.0
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
            if self._position != before and (not self._trail or hypot(self._position[0] - self._trail[-1][0], self._position[1] - self._trail[-1][1]) >= 2):
                self._trail.append(self._position)
        self._walking = moved
        if moved and not reduced_motion:
            self._walk_time += max(0.0, min(float(dt), 0.25))
        if self.spec:
            self._positions[self.spec.key] = self._position
        self._update_followers(max(0.0, min(float(dt), 0.25)), reduced_motion=reduced_motion)

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
        self._path.clear()
        start = self._tile()
        targets = tuple(tile for tile in interaction_tiles(self._navigation_spec, point) if self._can_interact(point, (tile[0] * TILE + 8, tile[1] * TILE + 8))) if point else (target,)
        routes = [(shortest_path(self._navigation_spec, start, tile), tile) for tile in targets if self._navigation_spec.passable(tile)]
        routes = [(route, tile) for route, tile in routes if route or tile == start]
        if not routes:
            self._blocked_until = self._time + 1.6
            return False
        self._blocked_until = 0.0
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
            self.stop_moving()
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
                if focus is None and event.key in (pg.K_RETURN, pg.K_KP_ENTER):
                    return False, None
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
                if self._clicked_point == "look:" + look.key and self._can_interact(look):
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
        if self._motion_atlas is None:
            try:
                atlas = self.pg.image.load(str(ASSET_DIRECTORY / "world-motion.png")).convert_alpha()
                if atlas.get_size() != (20 * MOTION_FRAMES, len(MOTION_CHARACTERS) * MOTION_ROWS * 24):
                    raise ValueError("motion atlas has an incompatible geometry")
                self._motion_atlas = atlas
            except (OSError, ValueError, self.pg.error):
                self._motion_atlas = False
        if self._depth_atlas is None:
            try:
                atlas = self.pg.image.load(str(ASSET_DIRECTORY / "world-depth.png")).convert_alpha()
                rows = (len(DEPTH_OBJECTS) + DEPTH_COLUMNS - 1) // DEPTH_COLUMNS
                if atlas.get_size() != (DEPTH_COLUMNS * DEPTH_CELL[0], rows * DEPTH_CELL[1]):
                    raise ValueError("depth atlas has an incompatible geometry")
                self._depth_atlas = atlas
                for index, (key, x, y, glyph) in enumerate(DEPTH_OBJECTS):
                    anchor = y * TILE + (20 if glyph == "W" else 14)
                    sprite = atlas.subsurface(depth_frame_rect(index))
                    self._depth_sprites.setdefault(key, []).append((anchor, sprite, (x * TILE - 8, y * TILE - 16)))
                for sprites in self._depth_sprites.values():
                    sprites.sort(key=lambda prop: prop[0])
            except (OSError, ValueError, self.pg.error):
                self._depth_atlas = False
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

    def _sprite(self, name: str, direction: int = 0, frame: int = 0, pose: str = "idle") -> Any:
        if self._motion_atlas and name in MOTION_CHARACTERS:
            return self._motion_atlas.subsurface(motion_frame_rect(name, direction=direction, frame=frame, pose=pose))
        name = {"wayfarer": "traveler", "scout": "traveler", "healer": "traveler", "ned": "patron", "captive": "patron", "warg": "orc_scout", "orc_sapper": "orc", "orc_archer": "orc_scout"}.get(name, name)
        name = name if name == "traveler" or name in CHARACTER_ATLAS_ROWS else "traveler"
        return self._atlas.subsurface(character_frame_rect(name, direction=direction, frame=frame // 2 if pose == "walk" else 0))

    def _draw_character(self, name: str, position: tuple[float, float], *, direction: int = 0, frame: int = 0, pose: str = "idle") -> None:
        x, y = round(position[0]), round(position[1])
        self.pg.draw.ellipse(self._native, (12, 17, 19), (x - 6, y - 3, 12, 5))
        self._native.blit(self._sprite(name, direction, frame, pose), (x - 10, y - 21))

    def _face_player(self, position: tuple[float, float], default: int = 0) -> int:
        dx, dy = self._position[0] - position[0], self._position[1] - position[1]
        if hypot(dx, dy) > 54:
            return default
        return (2 if dx > 0 else 1) if abs(dx) > abs(dy) else (0 if dy > 0 else 3)

    def _ambient(self, reduced_motion: bool) -> None:
        if not self.spec:
            return
        pg = self.pg
        tick = 0 if reduced_motion else int(self._time * 1000)
        overlay = pg.Surface(WORLD_SIZE, pg.SRCALPHA)
        for index, (x, y) in enumerate(self.spec.lights):
            offset = -10 if self.spec.key == "lantern" else 9 if self.spec.key == "camp" else 5
            cx, cy = x * TILE + 8, y * TILE + offset
            shimmer = 0 if reduced_motion else ((tick // 190 + index * 3) % 4)
            for radius, alpha in ((26, 9), (18, 14), (11, 22), (5, 38)):
                pg.draw.circle(overlay, (235, 164, 69, alpha + shimmer), (cx, cy), radius)
            if self.spec.key != "camp":
                pg.draw.rect(overlay, (255, 215, 125, 235), (cx, cy - shimmer // 2, 1, 3))
        if self.spec.ambience == "rain" and not reduced_motion:
            for index in range(25):
                x = (index * 83 + tick // 70) % WORLD_SIZE[0]
                y = (index * 47 + tick // 35 * 3) % WORLD_SIZE[1]
                pg.draw.line(overlay, (120, 161, 170, 65), (x, y), (x - 1, y + 3))
        elif self.spec.ambience in {"water", "marsh"}:
            for y, row in enumerate(self.spec.grid):
                for x, cell in enumerate(row):
                    if cell == "~":
                        offset = (tick // 390 + x + y) % 7
                        pg.draw.line(overlay, (126, 164, 164, 70), (x * TILE + 3, y * TILE + offset + 4), (x * TILE + 10, y * TILE + offset + 4))
            if self.spec.ambience == "marsh":
                for index in range(5):
                    x = (index * 67 + tick // 310) % 360 - 32
                    y = 61 + (index * 37) % 150
                    pg.draw.line(overlay, (160, 184, 171, 14), (x, y), (x + 29, y))
                    pg.draw.line(overlay, (160, 184, 171, 8), (x + 5, y + 1), (x + 23, y + 1))
        elif self.spec.ambience == "gulf":
            for index in range(3):
                x = 87 + (index * 37 + tick // 480) % 132
                y = 171 + index * 13
                pg.draw.line(overlay, (100, 131, 136, 14), (x, y), (min(247, x + 24), y))
                pg.draw.line(overlay, (70, 102, 111, 9), (x + 3, y + 1), (min(247, x + 19), y + 1))
        elif self.spec.ambience == "dust" and not reduced_motion:
            for index in range(9):
                x = (index * 43 + tick // 210) % 286 + 16
                y = (index * 31 + tick // 380) % 190 + 22
                pg.draw.rect(overlay, (190, 178, 133, 110), (x, y, 1, 1))
        elif self.spec.ambience == "ash" and not reduced_motion:
            for index in range(12):
                x = (index * 71 + tick // 250) % 284 + 18
                y = (index * 39 + tick // 430) % 188 + 25
                pg.draw.rect(overlay, (149, 155, 147, 52), (x, y, 1, 1))
        if not reduced_motion and self.spec.ambience in {"rain", "marsh"}:
            for y, row in enumerate(self.spec.grid):
                for x, cell in enumerate(row):
                    if cell in {"V", "E"}:
                        sway = ((tick // 530 + x + y) % 3) - 1
                        cx, cy = x * TILE + (8 if cell == "V" else 11), y * TILE + (1 if cell == "V" else 3)
                        pg.draw.line(overlay, (116, 139, 97, 115), (cx + sway, cy), (cx + sway + 2, cy))
        self._native.blit(overlay, (0, 0))

    def _scene_details(self) -> None:
        """Known routes can reveal art; unknown optional routes remain hidden."""
        if not self.spec:
            return
        for point in self.spec.points:
            if point.key in self._revealed_details.get(self.spec.key, ()) and point.decoration == "stairs":
                px, py = point.tile[0] * TILE, point.tile[1] * TILE
                self.pg.draw.rect(self._native, (12, 17, 21), (px + 1, py, 14, 15))
                for index in range(5):
                    self.pg.draw.line(self._native, (113 - index * 8, 123 - index * 8, 111 - index * 8), (px + 2 + index // 2, py + index * 3), (px + 13 - index // 2, py + index * 3))

    def _foreground(self) -> None:
        if not self.spec or self.spec.key != "sluice":
            return
        # Cage bars belong in front of the people inside them. They remain
        # static collision geometry and never cover an approach marker.
        for y, row in enumerate(self.spec.grid):
            for x, glyph in enumerate(row):
                if glyph == "K":
                    px, py = x * TILE, y * TILE
                    for offset in (1, 6, 11):
                        self.pg.draw.line(self._native, (72, 84, 82), (px + offset, py + 1), (px + offset, py + 14))
                    self.pg.draw.line(self._native, (98, 105, 99), (px, py + 13), (px + 15, py + 13))

    def draw(self, surface: Any, rect: Any, *, now_ms: int | None = None, reduced_motion: bool = False, text_size: str = "standard") -> Any:
        if not self.spec:
            return self.pg.Rect(rect)
        self._assets()
        pg = self.pg
        self._native.blit(self._backgrounds[self.spec.key], (0, 0))
        self._scene_details()
        self._ambient(reduced_motion)
        for x, y in self._path:
            pg.draw.rect(self._native, (74, 116, 109), (round(x), round(y), 1, 1))
        if self._path:
            x, y = map(round, self._path[-1])
            color = (139, 184, 170) if reduced_motion or int(self._time * 2) % 2 == 0 else (82, 128, 117)
            pg.draw.ellipse(self._native, color, (x - 3, y - 2, 7, 4), 1)
        pose = "walk" if self._walking else "idle"
        frame = 0 if reduced_motion else int((self._walk_time * 16) if self._walking else (self._time * 1.6)) % MOTION_FRAMES
        characters = [(self._position[1], self._hero_name, self._position, self._direction, frame, pose)]
        for follower in self._followers:
            follower_pose = "walk" if follower.walking else "idle"
            follower_frame = 0 if reduced_motion else int((follower.walk_time * 16) if follower.walking else (self._time * 1.4)) % MOTION_FRAMES
            direction = follower.direction if follower.walking else self._face_player(follower.position, follower.direction)
            characters.append((follower.position[1], follower.name, follower.position, direction, follower_frame, follower_pose))
        for name, tile in self._actors:
            position = (tile[0] * TILE + TILE / 2, tile[1] * TILE + TILE / 2)
            sprite_frame = 0 if reduced_motion else int(self._time * 1.3) % MOTION_FRAMES
            actor_pose = "snared" if name in {"ned", "captive"} else "guard" if name.startswith("orc") else "idle"
            # Ned hangs against the watch-stone rather than behind its face.
            depth = position[1] + 8 if name == "ned" else position[1]
            characters.append((depth, name, position, self._face_player(position), sprite_frame, actor_pose))
        for point in self._character_points:
            # Conversations can finish while their companions remain here.
            idle_frame = 0 if reduced_motion or point.sprite == "edrin" else int(self._time * 1.4) % MOTION_FRAMES
            characters.append((point.position[1], point.sprite, point.position, self._face_player(point.position), idle_frame, point.pose))
        props = self._depth_sprites.get(self.spec.key, ())
        prop_index = 0
        for character_y, name, position, direction, sprite_frame, character_pose in sorted(characters):
            while prop_index < len(props) and props[prop_index][0] <= character_y:
                _anchor, sprite, prop_position = props[prop_index]
                self._native.blit(sprite, prop_position)
                prop_index += 1
            self._draw_character(name, position, direction=direction, frame=sprite_frame, pose=character_pose)
        for _anchor, sprite, prop_position in props[prop_index:]:
            self._native.blit(sprite, prop_position)
        self._foreground()
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
        pg.draw.rect(self._native, (13, 18, 22), (7, 7, min(306, self._font.size(self.spec.name)[0] + 12), 15))
        self._native.blit(self._font.render(self.spec.name, False, (220, 186, 115)), (13, 10))
        bound = self._hovered or self._hovered_look or focus
        if isinstance(bound, BoundPoint):
            caption = f"{bound.answer}  {bound.point.name}"
        elif isinstance(bound, WorldLook):
            caption = f"LOOK  {bound.name}"
        else:
            caption = ""
        if self._inspected_look:
            caption = ""
        if caption:
            label = self._small_font.render(caption, False, (225, 216, 184))
            strip = label.get_rect(midbottom=(160, 235)).inflate(12, 8)
            pg.draw.rect(self._native, (13, 18, 22), strip)
            self._native.blit(label, label.get_rect(center=strip.center))
        if self._inspected_look:
            font_size = {"large": 11, "larger": 12}.get(text_size, 10)
            if font_size not in self._inspection_fonts:
                self._inspection_fonts[font_size] = (load_font(pg, font_size), load_font(pg, font_size, bold=True))
            body_font, title_font = self._inspection_fonts[font_size]
            lines = wrap_text(self._inspected_look.text, body_font, 266)
            line_height = body_font.get_linesize() + 1
            body_top = title_font.get_linesize() + 12
            footer_height = self._small_font.get_linesize() + 10
            height = body_top + len(lines) * line_height + footer_height
            bubble = pg.Rect(20, 211 - height, 280, height)
            pg.draw.rect(self._native, (13, 19, 24), bubble)
            pg.draw.rect(self._native, (115, 145, 125), bubble, 1)
            self._native.blit(title_font.render(self._inspected_look.name.upper(), False, (222, 185, 111)), (bubble.left + 7, bubble.top + 6))
            for index, text in enumerate(lines):
                self._native.blit(body_font.render(text, False, (220, 214, 186)), (bubble.left + 7, bubble.top + body_top + index * line_height))
            self._native.blit(self._small_font.render("E / ENTER / ESC  Close", False, (129, 166, 149)), (bubble.left + 7, bubble.bottom - self._small_font.get_linesize() - 6))
        target_rect = pg.Rect(rect)
        scale = min(target_rect.width / WORLD_SIZE[0], target_rect.height / WORLD_SIZE[1])
        if scale >= 2:
            scale = int(scale)
        size = (max(1, int(WORLD_SIZE[0] * scale)), max(1, int(WORLD_SIZE[1] * scale)))
        picture = pg.transform.scale(self._native, size)
        self._rect = picture.get_rect(center=target_rect.center)
        surface.blit(picture, self._rect)
        return self._rect.copy()
