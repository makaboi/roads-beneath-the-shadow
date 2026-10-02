"""Native pixel lighting and weather; no story state or navigation authority.

Every surface remains 320×240 until WorldView's final nearest-neighbor scale.
Lighting is authored for the existing architecture and cached by immutable
map geometry. Decorative clocks never allocate a growing frame cache.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from math import hypot
from typing import Any


SIZE = (320, 240)
TILE = 16
MAX_CACHED_MAPS = 16
FLOOR = frozenset(".,=+:;-")
LIGHT_BLOCKERS = frozenset("#HR")


@dataclass(frozen=True)
class Region:
    ambient: tuple[int, int, int]
    mist: tuple[int, int, int]
    water: tuple[int, int, int]
    fog: str = ""
    rain: bool = False
    motes: str = ""


REGIONS = {
    "pony": Region((216, 207, 189), (124, 138, 146), (101, 142, 151)),
    "bree": Region((196, 211, 224), (127, 154, 163), (109, 148, 162), "floor", True),
    "north-gate": Region((187, 207, 220), (122, 150, 160), (106, 145, 155), "floor", True),
    "road-fork": Region((183, 203, 212), (118, 144, 151), (103, 140, 150), "floor", True),
    "camp": Region((180, 199, 205), (132, 157, 154), (113, 154, 150), "water"),
    "watch-post": Region((181, 201, 205), (127, 153, 148), (111, 150, 148), "water"),
    "wayhouse": Region((194, 212, 208), (124, 155, 148), (117, 157, 151), "water"),
    "hall": Region((203, 214, 209), (142, 154, 147), (111, 148, 150), "floor", motes="dust"),
    "bridge": Region((180, 201, 214), (111, 142, 157), (103, 146, 157), "gulf"),
    "drowned-mile": Region((179, 201, 209), (116, 151, 153), (116, 159, 158), "water"),
    "sluice": Region((187, 207, 201), (131, 157, 145), (119, 157, 146), "water"),
    "refuge": Region((190, 204, 194), (146, 153, 139), (111, 145, 139), "floor", motes="ash"),
    "lantern": Region((184, 200, 201), (132, 145, 145), (111, 145, 149), "floor"),
}


@dataclass(frozen=True)
class Light:
    position: tuple[int, int]
    radius: int
    color: tuple[int, int, int]
    kind: str


def light_sources(spec: Any) -> tuple[Light, ...]:
    """Only painted sources emit light. L is a carved stone, not a lamp."""
    warm = (255, 246, 216)
    if spec.key == "bree":
        # The authored gables have warm south-facing panes. A window is not
        # a floating candle on the middle of its roof.
        return tuple(Light(position, radius, warm, "window") for position, radius in (
            ((44, 74), 29), ((68, 74), 25), ((200, 54), 28),
            ((220, 121), 33), ((244, 121), 33), ((268, 121), 31),
            ((296, 117), 29), ((44, 201), 27), ((68, 201), 27), ((92, 201), 24),
        ))
    result = []
    for x, y in spec.lights:
        if spec.key == "camp":
            result.append(Light((x * TILE + 8, y * TILE + 9), 31, (255, 224, 187), "ember"))
        elif spec.key == "lantern":
            result.append(Light((x * TILE + 8, y * TILE - 10), 58, warm, "lantern"))
        elif spec.key == "pony" and spec.grid[y][x] == "F":
            result.append(Light((x * TILE + 8, y * TILE + 5), 52, (255, 237, 204), "hearth"))
        else:
            result.append(Light((x * TILE + 8, y * TILE + 5), 39, warm, "candle"))
    if spec.key == "pony":
        result.extend(Light((x, 25), 33, (217, 239, 255), "glass") for x in (45, 109, 173))
    return tuple(result)


def light_visible(grid: tuple[str, ...], source: tuple[int, int], target: tuple[int, int]) -> bool:
    """Integer rays stop at existing walls, without changing their collision."""
    x, y = source
    tx, ty = target
    dx, dy = abs(tx - x), -abs(ty - y)
    sx, sy = (1 if x < tx else -1), (1 if y < ty else -1)
    error = dx + dy
    while (x, y) != (tx, ty):
        twice = error * 2
        if twice >= dy:
            error += dy
            x += sx
        if twice <= dx:
            error += dx
            y += sy
        if (x, y) == (tx, ty):
            return True
        if not (0 <= y < len(grid) and 0 <= x < len(grid[y])) or grid[y][x] in LIGHT_BLOCKERS:
            return False
    return True


@dataclass
class _Scene:
    region: Region
    lights: tuple[Light, ...]
    lighting: tuple[Any, ...]
    bounce: tuple[Any, ...]
    contact: Any
    water_mask: Any
    fog_mask: Any
    water_tiles: int
    seed: int


class WorldAtmosphere:
    """A bounded bank of native layers, driven by WorldView's existing clock."""

    def __init__(self, pygame: Any) -> None:
        self.pg = pygame
        self._scenes: OrderedDict[tuple[Any, ...], _Scene] = OrderedDict()
        self._layer = pygame.Surface(SIZE, pygame.SRCALPHA)
        self._fog = pygame.Surface(SIZE, pygame.SRCALPHA)
        self._ground_shadow = pygame.Surface((22, 10), pygame.SRCALPHA)
        pygame.draw.ellipse(self._ground_shadow, (7, 12, 17, 58), (1, 1, 20, 8))
        pygame.draw.ellipse(self._ground_shadow, (6, 10, 14, 85), (4, 2, 14, 6))
        pygame.draw.ellipse(self._ground_shadow, (3, 7, 11, 124), (7, 3, 8, 4))

    @property
    def cache_info(self) -> dict[str, int]:
        return {"maps": len(self._scenes), "lighting_frames": len(self._scenes) * 4, "limit": MAX_CACHED_MAPS}

    def _mask(self, spec: Any, glyphs: frozenset[str]) -> Any:
        pg = self.pg
        mask = pg.Surface(SIZE, pg.SRCALPHA)
        mask.fill((255, 255, 255, 0))
        for y, row in enumerate(spec.grid):
            for x, cell in enumerate(row):
                if cell in glyphs:
                    pg.draw.rect(mask, (255, 255, 255, 255), (x * TILE, y * TILE, TILE, TILE))
        return mask

    def _lighting(self, spec: Any, region: Region, lights: tuple[Light, ...], phase: int, *, bounce: bool = False) -> Any:
        pg = self.pg
        image = pg.Surface(SIZE)
        image.fill((0, 0, 0) if bounce else region.ambient)
        for light in lights:
            radius = light.radius
            stamp = pg.Surface((radius * 2 + 1, radius * 2 + 1))
            stamp.fill((0, 0, 0))
            flicker = (0, 3, -2, 1)[phase] if light.kind not in {"glass", "window"} else 0
            if bounce:
                # Multiplication shades the whole cast consistently; this
                # small reflected component makes an actual lantern readable
                # against dark masonry without washing out the tile grain.
                reflected = {
                    "lantern": (37, 25, 10), "hearth": (29, 17, 5),
                    "ember": (19, 9, 2), "candle": (23, 16, 6),
                    "window": (18, 12, 4), "glass": (5, 11, 16),
                }[light.kind]
                difference = tuple(max(0, channel + flicker) for channel in reflected)
            else:
                difference = tuple(max(0, channel - base) for channel, base in zip(light.color, region.ambient))
            for ring in range(12, 0, -1):
                scale = (1 - (ring - 1) / 12) ** 1.45
                color = tuple(round(channel * scale) for channel in difference)
                pg.draw.circle(stamp, color, (radius, radius), max(1, round(radius * ring / 12)))
            left, top = light.position[0] - radius, light.position[1] - radius
            source = (light.position[0] // TILE, light.position[1] // TILE)
            for y in range(max(0, top // TILE), min(15, (top + radius * 2) // TILE + 1)):
                for x in range(max(0, left // TILE), min(20, (left + radius * 2) // TILE + 1)):
                    if not light_visible(spec.grid, source, (x, y)):
                        pg.draw.rect(stamp, (0, 0, 0), (x * TILE - left, y * TILE - top, TILE, TILE))
            image.blit(stamp, (left, top), special_flags=pg.BLEND_RGB_ADD)
        return image

    def _contact(self, spec: Any) -> Any:
        pg = self.pg
        image = pg.Surface(SIZE, pg.SRCALPHA)
        cast = pg.Surface(SIZE, pg.SRCALPHA)
        for y, row in enumerate(spec.grid):
            for x, cell in enumerate(row):
                px, py = x * TILE, y * TILE
                if cell in "#HR" and y + 1 < 15 and spec.grid[y + 1][x] in FLOOR:
                    pg.draw.rect(image, (7, 13, 18, 48), (px, py + 16, 16, 3))
                    pg.draw.line(image, (7, 13, 18, 24), (px, py + 19), (px + 15, py + 19))
                if cell in "VEsnLPQWTr":
                    # Small directional silhouettes read as grounded columns
                    # and foliage, rather than interchangeable floor decals.
                    # They are clipped to existing floor after all props.
                    if cell in "VPW":
                        length = 17 if cell == "V" else 12
                        direction = -1 if x > 9 else 1
                        pg.draw.polygon(cast, (4, 10, 15, 28),
                                        ((px + 2, py + 14), (px + 13, py + 14),
                                         (px + 13 + direction * 6, py + 14 + length),
                                         (px + 5 + direction * 6, py + 14 + length)))
                    wide = cell in "VWr"
                    pg.draw.ellipse(image, (7, 12, 16, 38), (px - (3 if wide else 1), py + 12, 24 if wide else 19, 7))
                    pg.draw.ellipse(image, (4, 9, 13, 60), (px + 3, py + 13, 13, 4))
                if cell == "~":
                    # Submerged contact stays on the water side of the exact
                    # shoreline; neither the ledge nor its collision widens.
                    for dx, dy, a, b in ((0, -1, (px, py), (px + 15, py)), (-1, 0, (px, py), (px, py + 15))):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < 20 and 0 <= ny < 15 and spec.grid[ny][nx] != "~":
                            pg.draw.line(image, (3, 10, 14, 84), a, b, 2)
        cast.blit(self._mask(spec, FLOOR), (0, 0), special_flags=pg.BLEND_RGBA_MULT)
        image.blit(cast, (0, 0))
        return image

    def scene(self, spec: Any) -> _Scene:
        key = (spec.key, spec.grid, spec.lights)
        if key in self._scenes:
            self._scenes.move_to_end(key)
            return self._scenes[key]
        region = REGIONS.get(spec.key, REGIONS["wayhouse"])
        lights = light_sources(spec)
        fog_cells = frozenset("~") if region.fog == "water" else frozenset("X") if region.fog == "gulf" else FLOOR
        static_light = self._lighting(spec, region, lights, 0)
        # Steady windows and source-free regions share one immutable phase.
        # Only actual flames need four finite flicker surfaces.
        reflected = self._lighting(spec, region, lights, 0, bounce=True)
        flickers = any(light.kind not in {"glass", "window"} for light in lights)
        bounce = ((reflected,) + tuple(self._lighting(spec, region, lights, phase, bounce=True) for phase in range(1, 4))) if flickers else (reflected,) * 4
        scene = _Scene(region, lights, (static_light,) * 4, bounce,
                       self._contact(spec), self._mask(spec, frozenset("~")), self._mask(spec, fog_cells),
                       sum(row.count("~") for row in spec.grid),
                       sum((index + 1) * ord(character) for index, character in enumerate(spec.key)))
        if len(self._scenes) >= MAX_CACHED_MAPS:
            self._scenes.popitem(last=False)
        self._scenes[key] = scene
        return scene

    @staticmethod
    def _clock(time: float, reduced_motion: bool) -> int:
        return 0 if reduced_motion else int(max(0, time) * 1000)

    def draw_ground(self, surface: Any, spec: Any, time: float, *, reduced_motion: bool = False) -> None:
        pg = self.pg
        scene = self.scene(spec)
        tick = self._clock(time, reduced_motion)
        surface.blit(scene.contact, (0, 0))
        self._layer.fill((0, 0, 0, 0))
        if scene.water_tiles:
            for index in range(30):
                x = (index * 71 + scene.seed + tick // 360) % 376 - 28
                y = 5 + (index * 43 + scene.seed // 7) % 226
                y += ((tick // 510 + index * 3) % 5) - 2
                length = 9 + index * 7 % 22
                alpha = (28, 38, 45)[index % 3]
                pg.draw.line(self._layer, (*scene.region.water, alpha), (x, y), (x + length, y))
                if index % 3 == 0:
                    pg.draw.line(self._layer, (161, 190, 179, 39), (x + 3, y + 1), (x + 7, y + 1))
            self._layer.blit(scene.water_mask, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
            surface.blit(self._layer, (0, 0))
        self._draw_fog(surface, scene, tick, foreground=False)

    def draw_shadow(self, surface: Any, position: tuple[float, float]) -> None:
        surface.blit(self._ground_shadow, (round(position[0]) - 11, round(position[1]) - 5))

    def _draw_fog(self, surface: Any, scene: _Scene, tick: int, *, foreground: bool) -> None:
        if not scene.region.fog:
            return
        pg = self.pg
        self._fog.fill((0, 0, 0, 0))
        count = 5 if foreground else 9
        for index in range(count):
            x = (index * 83 + scene.seed + tick // (540 if foreground else 760)) % 430 - 95
            y = 24 + (index * 47 + scene.seed // 3) % 198
            if scene.region.fog == "gulf":
                y = 155 + index * 13 % 78
            width = 57 + (index * 29 + scene.seed) % 72
            alpha = (5 if foreground else 10) + index % 3
            for row in range(5):
                inset = (2 - min(row, 4 - row)) * 8
                pg.draw.line(self._fog, (*scene.region.mist, max(1, alpha - abs(2 - row) * 3)),
                             (x + inset, y + row), (x + width - inset, y + row))
        self._fog.blit(scene.fog_mask, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
        surface.blit(self._fog, (0, 0))

    def finish(self, surface: Any, spec: Any, time: float, *, reduced_motion: bool = False) -> None:
        pg = self.pg
        scene = self.scene(spec)
        tick = self._clock(time, reduced_motion)
        phase = 0 if reduced_motion else (0, 1, 0, 2, 0, 1, 3, 0, 2, 1, 0, 1)[tick // 210 % 12]
        surface.blit(scene.lighting[phase], (0, 0), special_flags=pg.BLEND_RGB_MULT)
        surface.blit(scene.bounce[phase], (0, 0), special_flags=pg.BLEND_RGB_ADD)
        self._draw_fog(surface, scene, tick, foreground=True)
        self._layer.fill((0, 0, 0, 0))
        for index, light in enumerate(scene.lights):
            x, y = light.position
            if light.kind == "hearth":
                flame = 0 if reduced_motion else (tick // 190 + index) % 3
                pg.draw.line(self._layer, (247, 180, 71, 170), (x - 2, y + 3), (x - 2, y - flame))
                pg.draw.line(self._layer, (255, 218, 119, 205), (x + 1, y + 3), (x + 1, y - 2 - flame))
                if not reduced_motion:
                    for ember in range(3):
                        age = (tick // 140 + ember * 11) % 29
                        ex = x + ((ember * 5 + age // 8) % 7) - 3
                        pg.draw.rect(self._layer, (228, 152, 66, max(0, 112 - age * 4)), (ex, y - age // 2, 1, 1))
            elif light.kind == "ember":
                # The camp remains a low, smokeless ember: no moving sparks,
                # flame tongues, smoke column, or invented lamp on its stone.
                pg.draw.line(self._layer, (236, 153, 63, 100 + phase * 5), (x - 2, y), (x + 2, y))
            elif light.kind in {"candle", "lantern"}:
                pg.draw.line(self._layer, (255, 218, 129, 105), (x, y), (x, y + 2))
        if scene.region.rain and not reduced_motion:
            for index in range(29):
                front = index % 5 == 0
                x = (index * 83 + scene.seed + tick // (85 if front else 130)) % 330 - 5
                y = (index * 47 + tick // (38 if front else 62) * 3) % 244 - 4
                pg.draw.line(self._layer, (129, 161, 173, 52 if front else 28), (x, y), (x - 1, y + (4 if front else 2)))
        if scene.region.motes and not reduced_motion:
            for index in range(14):
                x = (index * 71 + scene.seed + tick // 480) % 284 + 18
                y = (index * 39 + tick // 630) % 188 + 25
                if scene.region.motes == "dust" and not any(hypot(x - light.position[0], y - light.position[1]) < light.radius for light in scene.lights):
                    continue
                color = (202, 185, 133, 83) if scene.region.motes == "dust" else (154, 166, 149, 47)
                pg.draw.rect(self._layer, color, (x, y, 1, 1))
        surface.blit(self._layer, (0, 0))
