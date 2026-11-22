"""
The colors of a sprite blended from several palettes, for palette fields
(palette_fields.py).

A tile takes its sprite from one palette's sheets. Each of the other palettes
of its blend gives each color of that sprite a color of its own: palettes keep
their sprites at the same places in their sheets, so the color most often at
the same places as that color in the other palette's sheets of the terrain.
A color never at the same place as any color of the other palette's sheets (as
in a part of the sheet the other palette's sheet does not reach) takes the
color the nearest color that is takes, moved as far as it is from that color.

The colors are blended in Oklab, where equal steps look about equally far apart.

Neither Qt nor pygame is used here: each frontend reads sheets for it.
"""
from __future__ import annotations

import functools
import os
from collections import Counter
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from app.map_maker.palette_collection import Palette

Oklab = Tuple[float, float, float]
# A sheet's width, height, and pixels row by row, each 0xAARRGGBB
Sheet = Tuple[int, int, Sequence[int]]
SheetReader = Callable[[str], Sheet]

# === Oklab (https://bottosson.github.io/posts/oklab/) ===
def _to_linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def _to_channel(linear: float) -> int:
    c = 12.92 * linear if linear <= 0.0031308 else 1.055 * linear ** (1 / 2.4) - 0.055
    return min(max(round(c * 255), 0), 255)

@functools.lru_cache(maxsize=None)
def rgb_to_oklab(rgb: int) -> Oklab:
    r, g, b = _to_linear(rgb >> 16), _to_linear(rgb >> 8 & 0xFF), _to_linear(rgb & 0xFF)
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)

def oklab_to_rgb(lab: Oklab) -> int:
    L, a, b = lab
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = _to_channel(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s)
    g = _to_channel(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s)
    b = _to_channel(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)
    return r << 16 | g << 8 | b

# === Color maps ===
class ColorMap:
    """The color a palette gives each color of another palette's sheets"""
    def __init__(self, found: Dict[int, int]):
        # Each color found at the same places as a color of the other palette's sheets
        self.found = found
        self.guessed: Dict[int, int] = {}

    def __getitem__(self, rgb: int) -> int:
        if rgb in self.found:
            return self.found[rgb]
        if rgb not in self.guessed:
            self.guessed[rgb] = self._guess(rgb)
        return self.guessed[rgb]

    def _guess(self, rgb: int) -> int:
        if not self.found:
            return rgb
        lab = rgb_to_oklab(rgb)
        nearest = min(self.found, key=lambda c: (_distance(lab, rgb_to_oklab(c)), c))
        near_lab, target_lab = rgb_to_oklab(nearest), rgb_to_oklab(self.found[nearest])
        return oklab_to_rgb(tuple(t + (x - n) for t, x, n in zip(target_lab, lab, near_lab)))

def _distance(a: Oklab, b: Oklab) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b))

def sheet_paths(palette: Palette) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    return palette.fn, palette.autotile_fn, palette.shading_fn

_color_maps: Dict[tuple, ColorMap] = {}

def color_map(source: Palette, target: Palette, read_sheet: SheetReader) -> ColorMap:
    """The color target gives each color of source's sheets"""
    key = (sheet_paths(source), sheet_paths(target))
    if key not in _color_maps:
        votes: Counter = Counter()
        for source_fn, target_fn in zip(*key):
            if source_fn and target_fn and os.path.exists(source_fn) and os.path.exists(target_fn):
                source_width, source_height, source_pixels = read_sheet(source_fn)
                target_width, target_height, target_pixels = read_sheet(target_fn)
                width = min(source_width, target_width)
                for y in range(min(source_height, target_height)):
                    votes.update(zip(source_pixels[y * source_width:y * source_width + width],
                                     target_pixels[y * target_width:y * target_width + width]))
        best: Dict[int, Tuple[int, int]] = {}  # Key: source color, Value: (votes, target color)
        for (source_pixel, target_pixel), n in votes.items():
            # Transparent pixels have no color
            if source_pixel >> 24 and target_pixel >> 24:
                source_rgb, target_rgb = source_pixel & 0xFFFFFF, target_pixel & 0xFFFFFF
                # The most votes, then the lowest color, so a tie always goes the same way
                if source_rgb not in best or (n, -target_rgb) > (best[source_rgb][0], -best[source_rgb][1]):
                    best[source_rgb] = (n, target_rgb)
        _color_maps[key] = ColorMap({rgb: target_rgb for rgb, (_, target_rgb) in best.items()})
    return _color_maps[key]

class Recolor:
    """The color each color of shape's sheets is drawn in, blended from the
    palettes of mix, each giving as many parts of it as its weight"""
    def __init__(self, shape: Palette, mix: Sequence[Tuple[Palette, int]], read_sheet: SheetReader):
        # shape's own colors need no map
        self.parts: List[Tuple[Optional[ColorMap], int]] = [
            (None if palette is shape else color_map(shape, palette, read_sheet), weight)
            for palette, weight in mix]
        self.total = sum(weight for _, weight in mix)
        self.colors: Dict[int, int] = {}

    def __call__(self, rgb: int) -> int:
        if rgb not in self.colors:
            blended = [0.0, 0.0, 0.0]
            for cmap, weight in self.parts:
                lab = rgb_to_oklab(rgb if cmap is None else cmap[rgb])
                for i in range(3):
                    blended[i] += lab[i] * weight
            self.colors[rgb] = oklab_to_rgb(tuple(x / self.total for x in blended))
        return self.colors[rgb]
