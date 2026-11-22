from typing import Dict

import pygame

from app.utilities.typing import Pos

from app.map_maker.painter_utils import Painter
from app.map_maker.palette_collection import Palette
from app.map_maker.pygame_renderers.pygame_palette import PygamePalette, get_pygame_palette

class SimpleRenderer:
    """Draws the sprites of a terrain. Each position may be drawn with a
    palette of its own (palette_at), which each call is given"""
    def __init__(self, painter: Painter, palette: Palette):
        self.painter = painter
        self.set_palette(palette)

    def set_palette(self, palette: Palette):
        """The palette the terrain's icon is drawn with"""
        self.palette = get_pygame_palette(palette)

    def use_palette(self, palette: PygamePalette):
        """Has the painter choose among the sprites palette's sheet holds"""
        self.painter.set_limit({0: palette.limit16(0)})

    def get_display_sprite(self) -> pygame.Surface:
        return self.palette.get_image16(self.painter, self.painter.base_coord, 0)

    def get_sprite_coord(self, tilemap, position: Pos, palette: PygamePalette):
        """Everything draw_sprite needs to draw this position with palette.
        Does not depend on the autotile frame, so the autotile
        frames of a position can be drawn from a single call"""
        self.use_palette(palette)
        return self.painter.get_coord(tilemap, position)

    def draw_sprite(self, coord, autotile_num: int, palette: PygamePalette) -> pygame.Surface:
        return palette.get_image16(self.painter, coord, autotile_num)

    def determine_sprite(self, tilemap, position: Pos, autotile_num: int, palette: PygamePalette) -> pygame.Surface:
        return self.draw_sprite(self.get_sprite_coord(tilemap, position, palette), autotile_num, palette)

class SimpleRenderer8(SimpleRenderer):
    def use_palette(self, palette: PygamePalette):
        self.painter.set_limit({0: palette.limit8(0)})

    def get_display_sprite(self) -> pygame.Surface:
        coord1 = self.painter.base_coord
        coord2 = self.painter.base_coord[0], self.painter.base_coord[1] + 1
        coord3 = self.painter.base_coord[0], self.painter.base_coord[1] + 2
        coord4 = self.painter.base_coord[0], self.painter.base_coord[1] + 3
        return self.palette.get_image8(self.painter, coord1, coord2, coord3, coord4, 0)

    def draw_sprite(self, coord, autotile_num: int, palette: PygamePalette) -> pygame.Surface:
        coord1, coord2, coord3, coord4 = coord
        return palette.get_image8(self.painter, coord1, coord2, coord3, coord4, autotile_num)

class DisplayRenderer8(SimpleRenderer8):
    """Identical to SimpleRenderer8 just modifies
    how the display sprite is drawn
    to always use the base coord position of the base image
    """
    def get_display_sprite(self) -> pygame.Surface:
        coord1 = self.painter.base_coord
        coord2 = self.painter.base_coord[0] + 1, self.painter.base_coord[1]
        coord3 = self.painter.base_coord[0] + 1, self.painter.base_coord[1] + 1
        coord4 = self.painter.base_coord[0], self.painter.base_coord[1] + 1
        return self.palette.get_image8(self.painter, coord1, coord2, coord3, coord4, 0)

class LimitRenderer16(SimpleRenderer):
    """
    Finds the full vertical limit of the drawn part of the .png
    for each column (0 - 15)
    """
    def use_palette(self, palette: PygamePalette):
        limit: Dict[int, int] = {i: palette.limit16(i) for i in range(16)}
        self.painter.set_limit(limit)

class LimitRenderer8(SimpleRenderer8):
    """
    Finds the full vertical limit of the drawn part of the .png
    for each column (0 - 15)
    """
    def use_palette(self, palette: PygamePalette):
        limit: Dict[int, int] = {i: palette.limit8(i) for i in range(16)}
        self.painter.set_limit(limit)
