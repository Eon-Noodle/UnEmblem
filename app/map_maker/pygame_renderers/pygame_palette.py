from __future__ import annotations
from typing import TYPE_CHECKING, Dict, Tuple

import struct
from dataclasses import dataclass, field

import pygame

from app.utilities.typing import Pos

from app.map_maker.painter_utils import Painter
from app.map_maker.palette_blending import Recolor, Sheet
from app.map_maker.palette_collection import PALETTES
from app.map_maker.palette_fields import Blend
from app.map_maker.pygame_renderers.renderer_utils import get_image8, get_image16, find_limit8, find_limit16
from app.map_maker.terrain import Terrain
if TYPE_CHECKING:
    from app.map_maker.map_prefab import MapPrefab
    from app.map_maker.palette_collection import Palette, PaletteCollection

@dataclass(eq=False)
class PygamePalette:
    parent: PaletteCollection
    fn: str
    autotile_fn: str = None
    shading_fn: str = None
    image: pygame.Surface = None
    autotile_image: pygame.Surface = None
    shading_image: pygame.Surface = None
    # Key: (tile size, column, offset), Value: how many tiles down the column the sheet holds
    limits: Dict[Tuple[int, int, int], int] = field(default_factory=dict)

    def get_full_image(self) -> pygame.Surface:
        if self.image is None:
            self.image = pygame.image.load(self.fn)
        return self.image

    def limit16(self, idx: int, offset: int = 0) -> int:
        key = (16, idx, offset)
        if key not in self.limits:
            self.limits[key] = find_limit16(self.get_full_image(), idx, offset)
        return self.limits[key]

    def limit8(self, idx: int, offset: int = 0) -> int:
        key = (8, idx, offset)
        if key not in self.limits:
            self.limits[key] = find_limit8(self.get_full_image(), idx, offset)
        return self.limits[key]

    def get_image16(self, painter: Painter, coord: Pos, autotile_num: int) -> pygame.Surface:
        if self.image is None:
            self.image = pygame.image.load(self.fn)
        if painter.has_autotiles() and coord in painter.autotiles:
            column = painter.autotiles[coord]
            if self.autotile_image is None:
                self.autotile_image = pygame.image.load(self.autotile_fn)
            return get_image16(self.autotile_image, (column, autotile_num))
        else:
            return get_image16(self.image, coord)

    def get_shading_image16(self, painter: Painter, coord: Pos) -> pygame.Surface:
        if self.shading_image is None:
            self.shading_image = pygame.image.load(self.shading_fn)
        return get_image16(self.shading_image, coord)

    def subsurface8(self, painter: Painter, coord: Pos, autotile_num: int) -> pygame.Surface:
        if self.image is None:
            self.image = pygame.image.load(self.fn)
        if painter.has_autotiles() and coord in painter.autotiles:
            column = painter.autotiles[coord]
            if self.autotile_image is None:
                self.autotile_image = pygame.image.load(self.autotile_fn)
            return get_image8(self.autotile_image, (column, autotile_num))
        else:
            return get_image8(self.image, coord)

    def get_image8(
            self, painter: Painter,
            coord1: Pos, coord2: Pos, coord3: Pos, coord4: Pos,
            autotile_num: int) -> pygame.Surface:
        base_image = pygame.Surface((16, 16), pygame.SRCALPHA, 32)
        topleft = self.subsurface8(painter, coord1, autotile_num)
        topright = self.subsurface8(painter, coord2, autotile_num)
        bottomright = self.subsurface8(painter, coord3, autotile_num)
        bottomleft = self.subsurface8(painter, coord4, autotile_num)
        base_image.blit(topleft, (0, 0))
        base_image.blit(topright, (8, 0))
        base_image.blit(bottomleft, (0, 8))
        base_image.blit(bottomright, (8, 8))
        return base_image

@dataclass(eq=False)
class BlendedPygamePalette(PygamePalette):
    """The sprites of shape's sheets in the colors of a blend of palettes"""
    shape: PygamePalette = None
    recolor: Recolor = None
    # Key: what the sprite is drawn from, Value: the sprite recolored
    recolored: Dict[tuple, pygame.Surface] = field(default_factory=dict)

    def get_full_image(self) -> pygame.Surface:
        return self.shape.get_full_image()

    def limit16(self, idx: int, offset: int = 0) -> int:
        return self.shape.limit16(idx, offset)

    def limit8(self, idx: int, offset: int = 0) -> int:
        return self.shape.limit8(idx, offset)

    def _recolored(self, key: tuple, draw) -> pygame.Surface:
        if key not in self.recolored:
            self.recolored[key] = recolor_image(draw(), self.recolor)
        # A copy, since a renderer may blit onto it
        return self.recolored[key].copy()

    def get_image16(self, painter: Painter, coord: Pos, autotile_num: int) -> pygame.Surface:
        frame = autotile_num if painter.has_autotiles() and coord in painter.autotiles else 0
        return self._recolored((16, painter, coord, frame),
                               lambda: self.shape.get_image16(painter, coord, autotile_num))

    def get_shading_image16(self, painter: Painter, coord: Pos) -> pygame.Surface:
        return self._recolored(('shading', coord), lambda: self.shape.get_shading_image16(painter, coord))

    def subsurface8(self, painter: Painter, coord: Pos, autotile_num: int) -> pygame.Surface:
        frame = autotile_num if painter.has_autotiles() and coord in painter.autotiles else 0
        return self._recolored((8, painter, coord, frame),
                               lambda: self.shape.subsurface8(painter, coord, autotile_num))

def recolor_image(image: pygame.Surface, recolor: Recolor) -> pygame.Surface:
    image = image.copy()
    for y in range(image.get_height()):
        for x in range(image.get_width()):
            r, g, b, a = image.get_at((x, y))
            # Transparent pixels have no color
            if a:
                rgb = recolor(r << 16 | g << 8 | b)
                image.set_at((x, y), (rgb >> 16, rgb >> 8 & 0xFF, rgb & 0xFF, a))
    return image

def read_sheet(fn: str) -> Sheet:
    image = pygame.image.load(fn)
    width, height = image.get_size()
    # Big-endian ARGB bytes read as 0xAARRGGBB on any machine
    return width, height, struct.unpack('>%dI' % (width * height), pygame.image.tobytes(image, 'ARGB'))

_pygame_palette_cache: Dict[int, PygamePalette] = {}

def get_pygame_palette(palette: Palette) -> PygamePalette:
    """Wraps a framework-agnostic Palette in a PygamePalette (cached by identity
    so the underlying images are only loaded once per palette)."""
    key = id(palette)
    if key not in _pygame_palette_cache:
        _pygame_palette_cache[key] = PygamePalette(
            palette.parent, palette.fn, palette.autotile_fn, palette.shading_fn)
    return _pygame_palette_cache[key]

_blended_palette_cache: Dict[Tuple[Terrain, Blend], PygamePalette] = {}

def get_blended_pygame_palette(terrain: Terrain, blend: Blend) -> PygamePalette:
    """The palette terrain is drawn with in blend"""
    key = (terrain, blend)
    if key not in _blended_palette_cache:
        shape = PALETTES.get(blend.shape).get(terrain)
        if blend.is_pure():
            _blended_palette_cache[key] = get_pygame_palette(shape)
        else:
            recolor = Recolor(shape, [(PALETTES.get(nid).get(terrain), weight) for nid, weight in blend.mix], read_sheet)
            _blended_palette_cache[key] = BlendedPygamePalette(
                shape.parent, shape.fn, shape.autotile_fn, shape.shading_fn,
                shape=get_pygame_palette(shape), recolor=recolor)
    return _blended_palette_cache[key]

def palette_at(tilemap: MapPrefab, terrain: Terrain, pos: Pos) -> PygamePalette:
    """The palette the sprite of terrain at pos is drawn with"""
    return get_blended_pygame_palette(terrain, tilemap.palette_blend(pos, terrain.outdoor))
