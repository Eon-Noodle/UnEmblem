import unittest
from unittest.mock import patch

from app.engine import base_surf, engine
from app.tests.engine_harness import EngineTestCase

TILE = base_surf.SLICE_9_WIDTH


class CreateBaseSurfTests(EngineTestCase):
    '''A base bigger than 24x24 has several variants of each slice 9 tile.
    Menus build their background every frame, so the tile chosen for each
    place must not change between builds, or the background flickers.'''

    def setUp(self):
        super().setUp()
        # A 40x40 base: 3 variants along each edge and 9 in the center,
        # each tile filled with its own color
        self.base = engine.create_surface((5 * TILE, 5 * TILE))
        for tx in range(5):
            for ty in range(5):
                self.base.fill((tx * 50, ty * 50, 100), (tx * TILE, ty * TILE, TILE, TILE))
        patcher = patch.object(base_surf.SPRITES, 'get', lambda *args, **kwargs: self.base)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _tiles(self, width, height):
        '''Each tile's color, keyed by its place on the surface'''
        surf = base_surf.create_base_surf(width, height, 'test_bg_base')
        return {(x, y): tuple(surf.get_at((x, y)))[:3]
                for x in range(0, surf.get_width(), TILE)
                for y in range(0, surf.get_height(), TILE)}

    def test_same_size_builds_the_same_surface(self):
        self.assertEqual(self._tiles(96, 64), self._tiles(96, 64))

    def test_growing_keeps_the_tiles_already_shown(self):
        small = self._tiles(96, 64)
        big = self._tiles(160, 96)
        for x in range(TILE, 96 - TILE, TILE):
            # Top edge and center stay where they were
            self.assertEqual(small[(x, 0)], big[(x, 0)])
            for y in range(TILE, 64 - TILE, TILE):
                self.assertEqual(small[(x, y)], big[(x, y)])
            # The bottom edge moves down with its tiles
            self.assertEqual(small[(x, 64 - TILE)], big[(x, 96 - TILE)])
        for y in range(TILE, 64 - TILE, TILE):
            self.assertEqual(small[(0, y)], big[(0, y)])
            # The right edge moves right with its tiles
            self.assertEqual(small[(96 - TILE, y)], big[(160 - TILE, y)])

    def test_every_variant_is_used(self):
        tiles = self._tiles(240, 160)
        center = {tiles[(x, y)] for x in range(TILE, 240 - TILE, TILE)
                  for y in range(TILE, 160 - TILE, TILE)}
        top = {tiles[(x, 0)] for x in range(TILE, 240 - TILE, TILE)}
        self.assertEqual(len(center), 9)
        self.assertEqual(len(top), 3)


if __name__ == '__main__':
    unittest.main()
