from __future__ import annotations
from typing import TYPE_CHECKING, Dict, Tuple

import struct
from dataclasses import dataclass, field

from PyQt5.QtGui import QImage, QPixmap, QPainter

from app.utilities.typing import Pos

from app.map_maker.painter_utils import Painter
from app.map_maker.palette_blending import Recolor, Sheet
from app.map_maker.palette_collection import PALETTES
from app.map_maker.palette_fields import Blend
from app.map_maker.qt_renderers.renderer_utils import get_pixmap8, get_pixmap16, find_limit8, find_limit16
from app.map_maker.terrain import Terrain
if TYPE_CHECKING:
    from app.map_maker.map_prefab import MapPrefab
    from app.map_maker.palette_collection import Palette, PaletteCollection

@dataclass(eq=False)
class QtPalette:
    parent: PaletteCollection
    fn: str
    autotile_fn: str = None
    shading_fn: str = None
    pixmap: QPixmap = None
    autotile_pixmap: QPixmap = None
    shading_pixmap: QPixmap = None
    # Key: (painter, coord1, coord2, coord3, coord4, autotile_num), Value: get_pixmap8 of them
    pixmap8_cache: Dict[Tuple[Painter, Pos, Pos, Pos, Pos, int], QPixmap] = field(default_factory=dict)
    # Key: (tile size, column, offset), Value: how many tiles down the column the sheet holds
    limits: Dict[Tuple[int, int, int], int] = field(default_factory=dict)

    def get_full_pixmap(self) -> QPixmap:
        if not self.pixmap:
            self.pixmap = QPixmap(self.fn)
        return self.pixmap

    def limit16(self, idx: int, offset: int = 0) -> int:
        key = (16, idx, offset)
        if key not in self.limits:
            self.limits[key] = find_limit16(self.get_full_pixmap(), idx, offset)
        return self.limits[key]

    def limit8(self, idx: int, offset: int = 0) -> int:
        key = (8, idx, offset)
        if key not in self.limits:
            self.limits[key] = find_limit8(self.get_full_pixmap(), idx, offset)
        return self.limits[key]

    def get_pixmap16(self, painter: Painter, coord: Pos, autotile_num: int) -> QPixmap:
        if not self.pixmap:
            self.pixmap = QPixmap(self.fn)
        if painter.has_autotiles() and coord in painter.autotiles:
            column = painter.autotiles[coord]
            if not self.autotile_pixmap:
                self.autotile_pixmap = QPixmap(self.autotile_fn)
            return get_pixmap16(self.autotile_pixmap, (column, autotile_num))
        else:
            return get_pixmap16(self.pixmap, coord)

    def get_shading_pixmap16(self, painter: Painter, coord: Pos) -> QPixmap:
        if not self.shading_pixmap:
            self.shading_pixmap = QPixmap(self.shading_fn)
        return get_pixmap16(self.shading_pixmap, coord)

    def subsurface8(self, painter: Painter, coord: Pos, autotile_num: int) -> QPixmap:
        if not self.pixmap:
            self.pixmap = QPixmap(self.fn)
        if painter.has_autotiles() and coord in painter.autotiles:
            column = painter.autotiles[coord]
            if not self.autotile_pixmap:
                self.autotile_pixmap = QPixmap(self.autotile_fn)
            return get_pixmap8(self.autotile_pixmap, (column, autotile_num))
        else:
            return get_pixmap8(self.pixmap, coord)

    def get_pixmap8(
            self, painter: Painter,
            coord1: Pos, coord2: Pos, coord3: Pos, coord4: Pos,
            autotile_num: int) -> QPixmap:
        # Many tiles share the same four quarters, so each combination is put together once
        key = (painter, coord1, coord2, coord3, coord4, autotile_num)
        if key not in self.pixmap8_cache:
            base_pixmap = QPixmap(16, 16)
            topleft = self.subsurface8(painter, coord1, autotile_num)
            topright = self.subsurface8(painter, coord2, autotile_num)
            bottomright = self.subsurface8(painter, coord3, autotile_num)
            bottomleft = self.subsurface8(painter, coord4, autotile_num)
            qpainter = QPainter()
            qpainter.begin(base_pixmap)
            qpainter.drawPixmap(0, 0, topleft)
            qpainter.drawPixmap(8, 0, topright)
            qpainter.drawPixmap(0, 8, bottomleft)
            qpainter.drawPixmap(8, 8, bottomright)
            qpainter.end()
            self.pixmap8_cache[key] = base_pixmap
        # The copy shares the cached pixels, but painting on it leaves the cache as it is
        return QPixmap(self.pixmap8_cache[key])

@dataclass(eq=False)
class BlendedQtPalette(QtPalette):
    """The sprites of shape's sheets in the colors of a blend of palettes"""
    shape: QtPalette = None
    recolor: Recolor = None
    # Key: what the sprite is drawn from, Value: the sprite recolored
    recolored: Dict[tuple, QPixmap] = field(default_factory=dict)

    def get_full_pixmap(self) -> QPixmap:
        return self.shape.get_full_pixmap()

    def limit16(self, idx: int, offset: int = 0) -> int:
        return self.shape.limit16(idx, offset)

    def limit8(self, idx: int, offset: int = 0) -> int:
        return self.shape.limit8(idx, offset)

    def _recolored(self, key: tuple, draw) -> QPixmap:
        if key not in self.recolored:
            self.recolored[key] = recolor_pixmap(draw(), self.recolor)
        # The copy shares the cached pixels, but painting on it leaves the cache as it is
        return QPixmap(self.recolored[key])

    def get_pixmap16(self, painter: Painter, coord: Pos, autotile_num: int) -> QPixmap:
        frame = autotile_num if painter.has_autotiles() and coord in painter.autotiles else 0
        return self._recolored((16, painter, coord, frame),
                               lambda: self.shape.get_pixmap16(painter, coord, autotile_num))

    def get_shading_pixmap16(self, painter: Painter, coord: Pos) -> QPixmap:
        return self._recolored(('shading', coord), lambda: self.shape.get_shading_pixmap16(painter, coord))

    def subsurface8(self, painter: Painter, coord: Pos, autotile_num: int) -> QPixmap:
        frame = autotile_num if painter.has_autotiles() and coord in painter.autotiles else 0
        return self._recolored((8, painter, coord, frame),
                               lambda: self.shape.subsurface8(painter, coord, autotile_num))

def recolor_pixmap(pixmap: QPixmap, recolor: Recolor) -> QPixmap:
    image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixel(x, y)
            # Transparent pixels have no color
            if pixel >> 24:
                image.setPixel(x, y, (pixel & 0xFF000000) | recolor(pixel & 0xFFFFFF))
    return QPixmap.fromImage(image)

def read_sheet(fn: str) -> Sheet:
    image = QImage(fn).convertToFormat(QImage.Format_ARGB32)
    width, height = image.width(), image.height()
    # Each pixel of an ARGB32 image is a native 0xAARRGGBB, with no padding at the end of a row
    data = image.constBits().asstring(image.sizeInBytes())
    return width, height, struct.unpack('=%dI' % (width * height), data)

_qt_palette_cache: Dict[int, QtPalette] = {}

def get_qt_palette(palette: Palette) -> QtPalette:
    """Wraps a framework-agnostic Palette in a QtPalette (cached by identity
    so the underlying pixmaps are only loaded once per palette)."""
    key = id(palette)
    if key not in _qt_palette_cache:
        _qt_palette_cache[key] = QtPalette(
            palette.parent, palette.fn, palette.autotile_fn, palette.shading_fn)
    return _qt_palette_cache[key]

_blended_palette_cache: Dict[Tuple[Terrain, Blend], QtPalette] = {}

def get_blended_qt_palette(terrain: Terrain, blend: Blend) -> QtPalette:
    """The palette terrain is drawn with in blend"""
    key = (terrain, blend)
    if key not in _blended_palette_cache:
        shape = PALETTES.get(blend.shape).get(terrain)
        if blend.is_pure():
            _blended_palette_cache[key] = get_qt_palette(shape)
        else:
            recolor = Recolor(shape, [(PALETTES.get(nid).get(terrain), weight) for nid, weight in blend.mix], read_sheet)
            _blended_palette_cache[key] = BlendedQtPalette(
                shape.parent, shape.fn, shape.autotile_fn, shape.shading_fn,
                shape=get_qt_palette(shape), recolor=recolor)
    return _blended_palette_cache[key]

def palette_at(tilemap: MapPrefab, terrain: Terrain, pos: Pos) -> QtPalette:
    """The palette the sprite of terrain at pos is drawn with"""
    return get_blended_qt_palette(terrain, tilemap.palette_blend(pos, terrain.outdoor))
