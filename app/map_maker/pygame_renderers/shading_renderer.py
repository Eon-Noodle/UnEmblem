from typing import Dict

import pygame

from app.utilities.typing import Pos

from app.map_maker.painter_utils import Painter
from app.map_maker.painters import FloorPainter, RuinedFloorPainter, GrassFloorPainter
from app.map_maker.palette_collection import Palette
from app.map_maker.pygame_renderers.pygame_palette import PygamePalette
from app.map_maker.pygame_renderers import SimpleRenderer

class SimpleShadingRenderer(SimpleRenderer):
    def get_sprite_coord(self, tilemap, position: Pos, palette: PygamePalette):
        self.use_palette(palette)
        coord = self.painter.get_coord(tilemap, position)
        shading_coord = self.painter.get_shading_coord(tilemap, position)
        return coord, shading_coord

    def draw_sprite(self, coord, autotile_num: int, palette: PygamePalette) -> pygame.Surface:
        coord, shading_coord = coord
        base_image = palette.get_image16(self.painter, coord, autotile_num)

        if shading_coord is not None:
            shading_image = palette.get_shading_image16(self.painter, shading_coord)
            base_image.blit(shading_image, (0, 0))
        return base_image

class PoolShadingRenderer(SimpleShadingRenderer):
    """
    Only difference is that limit is set to 2
    To handle both open and non-open pool
    """
    def use_palette(self, palette: PygamePalette):
        limit: Dict[int, int] = {i: palette.limit16(i) for i in range(2)}
        self.painter.set_limit(limit)

class FloorShadingRenderer(SimpleRenderer):
    """
    Floor Shading Renderer needs to be able to switch between painters at runtime
    depending on which palette collection is selected
    """
    def __init__(self, metadata_arg: str, palette: Palette):
        self.metadata_arg = metadata_arg
        self.painters = {
            'default': FloorPainter(),
            'ruins': RuinedFloorPainter(),
            'grass': GrassFloorPainter(),
        }
        self.set_palette(palette)

    def use_palette(self, palette: PygamePalette):
        self.painters['default'].set_limit({0: palette.limit16(0)})
        full_limit = {k: palette.limit16(k) for k in range(16)}
        self.painters['ruins'].set_limit(full_limit)
        self.painters['grass'].set_limit(full_limit)

    def painter_for(self, palette: PygamePalette) -> Painter:
        """The painter of the kind of floor palette's collection has"""
        floor_type = palette.parent.metadata.get(self.metadata_arg, 'default')
        return self.painters.get(floor_type, self.painters['default'])

    @property
    def painter(self) -> Painter:
        return self.painter_for(self.palette)

    def get_sprite_coord(self, tilemap, position: Pos, palette: PygamePalette):
        self.use_palette(palette)
        painter = self.painter_for(palette)
        coord = painter.get_coord(tilemap, position)
        shading_coord = painter.get_shading_coord(tilemap, position)

        extra_coord = None
        pillar_coord = painter.get_pillar_coord(tilemap, position)
        if pillar_coord:
            extra_coord = pillar_coord
        elif painter.is_column_bottom(tilemap, position):
            extra_coord = (7, 0)
        return coord, shading_coord, extra_coord

    def draw_sprite(self, coord, autotile_num: int, palette: PygamePalette) -> pygame.Surface:
        coord, shading_coord, extra_coord = coord
        painter = self.painter_for(palette)

        base_image = palette.get_image16(painter, coord, autotile_num)

        shading_image = None
        if shading_coord is not None:
            shading_image = palette.get_shading_image16(painter, shading_coord)

        extra_image = None
        if extra_coord:
            extra_image = palette.get_shading_image16(painter, extra_coord)

        if shading_image:
            base_image.blit(shading_image, (0, 0))
        if extra_image:
            base_image.blit(extra_image, (0, 0))

        return base_image
