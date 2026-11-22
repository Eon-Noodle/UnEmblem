import os
import shutil
import sys
import tempfile
import unittest
from typing import List

from app.tests import qt_headless  # noqa: F401  Before the QApplication
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication

import pygame

from app.constants import TILEWIDTH, TILEHEIGHT
import app.map_maker.utilities as map_utils
from app.map_maker.map_prefab import MapPrefab
from app.map_maker.palette_blending import Recolor, color_map, oklab_to_rgb, rgb_to_oklab
from app.map_maker.palette_collection import PALETTES, Palette
from app.map_maker.palette_fields import Blend, PaletteFields, PaletteSource
from app.map_maker.terrain import Terrain
import app.map_maker.pygame_renderers.draw_tilemap as pygame_draw_tilemap
from app.map_maker.pygame_renderers.pygame_palette import read_sheet
from app.tests.test_map_prefab import build_mixed_tilemap, draw_at_frame, fresh_draw_at_frame

app = QApplication.instance() or QApplication(sys.argv)

import app.map_maker.editor.draw_tilemap as qt_draw_tilemap


def fields(*outdoor: PaletteSource, **kwargs) -> PaletteFields:
    return PaletteFields(True, list(outdoor), [], **kwargs)


class BlendTests(unittest.TestCase):
    def test_off_or_without_sources_is_no_blend(self):
        on = fields(PaletteSource('A', (0, 0)))
        self.assertIsNone(PaletteFields(False, on.outdoor).blend_at((0, 0), True))
        self.assertIsNone(on.blend_at((0, 0), False))
        self.assertEqual(on.blend_at((0, 0), True), Blend.pure('A'))

    def test_far_inside_a_field_is_its_palette_alone(self):
        two = fields(PaletteSource('A', (0, 0)), PaletteSource('B', (40, 0)))
        self.assertEqual(two.blend_at((1, 0), True), Blend.pure('A'))
        self.assertEqual(two.blend_at((39, 3), True), Blend.pure('B'))

    def test_halfway_is_half_of_each(self):
        two = fields(PaletteSource('A', (0, 0)), PaletteSource('B', (10, 0)))
        # The first source scoring lowest gives the shape
        self.assertEqual(two.blend_at((5, 0), True), Blend('A', (('A', 4), ('B', 4))))
        blend = two.blend_at((4, 0), True)
        self.assertEqual(blend.shape, 'A')
        self.assertGreater(dict(blend.mix)['A'], dict(blend.mix)['B'])

    def test_strength_moves_the_edge(self):
        two = fields(PaletteSource('A', (0, 0)), PaletteSource('B', (10, 0), strength=2))
        # 4 tiles from A, but 6 tiles from B are 3 at twice the strength
        self.assertEqual(two.blend_at((4, 0), True).shape, 'B')

    def test_weights_add_up_to_steps(self):
        three = fields(PaletteSource('A', (0, 0)), PaletteSource('B', (12, 3)),
                       PaletteSource('C', (5, 11), strength=1.5), steps=8)
        for x in range(-3, 16):
            for y in range(-3, 16):
                blend = three.blend_at((x, y), True)
                if not blend.is_pure():
                    self.assertEqual(sum(n for _, n in blend.mix), 8, (x, y))
                    self.assertEqual([nid for nid, _ in blend.mix], sorted(nid for nid, _ in blend.mix))

    def test_no_transition_draws_one_palette(self):
        two = fields(PaletteSource('A', (0, 0)), PaletteSource('B', (10, 0)), transition=0)
        self.assertEqual(two.blend_at((5, 0), True), Blend.pure('A'))
        self.assertEqual(two.blend_at((6, 0), True), Blend.pure('B'))

    def test_sources_of_one_palette_add_up(self):
        three = fields(PaletteSource('A', (0, 0)), PaletteSource('B', (5, 0)), PaletteSource('A', (10, 0)))
        blend = three.blend_at((5, 0), True)
        self.assertEqual(blend.shape, 'B')
        self.assertEqual([nid for nid, _ in blend.mix], ['A', 'B'])

    def test_indoor_terrain_takes_only_indoor_sources(self):
        both = PaletteFields(True, [PaletteSource('A', (0, 0))], [PaletteSource('X', (0, 0)), PaletteSource('Y', (4, 0))])
        self.assertEqual(both.blend_at((2, 0), True), Blend.pure('A'))
        self.assertEqual(both.blend_at((2, 0), False).shape, 'X')

    def test_map_without_fields_takes_its_one_palette(self):
        tilemap = MapPrefab('test')
        outdoor, indoor = PALETTES.outdoor_palettes(), PALETTES.indoor_palettes()
        self.assertEqual(tilemap.palette_blend((0, 0), True), Blend.pure(outdoor[0].nid))
        tilemap.current_outdoor_palette = outdoor[1].nid
        tilemap.current_indoor_palette = indoor[1].nid
        self.assertEqual(tilemap.palette_blend((0, 0), True), Blend.pure(outdoor[1].nid))
        self.assertEqual(tilemap.palette_blend((0, 0), False), Blend.pure(indoor[1].nid))


class PaletteFieldsSaveTests(unittest.TestCase):
    def test_save_and_restore(self):
        tilemap = MapPrefab('test')
        tilemap.palette_fields = PaletteFields(
            True, [PaletteSource('A', (-3, 2), 1.5)], [PaletteSource('X', (4, 20))], transition=1.5, steps=5)
        restored = MapPrefab.restore(tilemap.save())
        self.assertEqual(restored.palette_fields, tilemap.palette_fields)

    def test_map_saved_before_palette_fields(self):
        s_dict = MapPrefab('test').save()
        del s_dict['palette_fields']
        self.assertEqual(MapPrefab.restore(s_dict).palette_fields, PaletteFields())

    def test_resize_moves_origins(self):
        tilemap = MapPrefab('test')
        tilemap.palette_fields.outdoor.append(PaletteSource('A', (0, 0)))
        tilemap.palette_fields.indoor.append(PaletteSource('X', (14, 9)))
        tilemap.resize(10, 10, -2, 3)
        # Even off the map
        self.assertEqual(tilemap.palette_fields.outdoor[0].origin, (-2, 3))
        self.assertEqual(tilemap.palette_fields.indoor[0].origin, (12, 12))


class ColorMapTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder)

    def palette(self, name: str, rows: List[List[tuple]]) -> Palette:
        """A palette whose sheet holds rows of colors, RGB or RGBA"""
        surface = pygame.Surface((len(rows[0]), len(rows)), pygame.SRCALPHA, 32)
        for y, row in enumerate(rows):
            for x, color in enumerate(row):
                surface.set_at((x, y), color)
        fn = os.path.join(self.folder, name + '.png')
        pygame.image.save(surface, fn)
        return Palette(None, fn)

    def test_colors_at_the_same_places(self):
        red, green, blue = (200, 0, 0), (0, 200, 0), (0, 0, 200)
        source = self.palette('source', [[red, green], [blue, red]])
        target = self.palette('target', [[blue, red], [green, blue]])
        cmap = color_map(source, target, read_sheet)
        self.assertEqual(cmap.found, {0xC80000: 0x0000C8, 0x00C800: 0xC80000, 0x0000C8: 0x00C800})

    def test_most_often_at_the_same_places(self):
        source = self.palette('source', [[(10, 10, 10)] * 3])
        target = self.palette('target', [[(1, 2, 3), (1, 2, 3), (4, 5, 6)]])
        self.assertEqual(color_map(source, target, read_sheet)[0x0A0A0A], 0x010203)

    def test_transparent_pixels_have_no_color(self):
        source = self.palette('source', [[(10, 10, 10), (50, 50, 50)]])
        target = self.palette('target', [[(0, 0, 0, 0), (60, 60, 60)]])
        self.assertEqual(color_map(source, target, read_sheet).found, {0x323232: 0x3C3C3C})

    def test_color_out_of_reach_moves_with_the_nearest(self):
        # The target's sheet is too narrow to reach the source's last color
        source = self.palette('source', [[(100, 0, 0), (0, 0, 100), (110, 0, 0)]])
        target = self.palette('target', [[(0, 100, 0), (0, 0, 100)]])
        guessed = color_map(source, target, read_sheet)[0x6E0000]
        expected = oklab_to_rgb(tuple(t + (x - n) for t, x, n in zip(
            rgb_to_oklab(0x006400), rgb_to_oklab(0x6E0000), rgb_to_oklab(0x640000))))
        self.assertEqual(guessed, expected)

    def test_recolor_blends_in_oklab(self):
        source = self.palette('source', [[(200, 40, 40)]])
        target = self.palette('target', [[(40, 40, 200)]])
        self.assertEqual(Recolor(source, [(target, 1)], read_sheet)(0xC82828), 0x2828C8)
        self.assertEqual(Recolor(source, [(source, 1)], read_sheet)(0xC82828), 0xC82828)
        half = Recolor(source, [(source, 1), (target, 1)], read_sheet)(0xC82828)
        mean = tuple((a + b) / 2 for a, b in zip(rgb_to_oklab(0xC82828), rgb_to_oklab(0x2828C8)))
        self.assertEqual(half, oklab_to_rgb(mean))

    def test_oklab_round_trip(self):
        for r in range(0, 256, 15):
            for g in range(0, 256, 15):
                for b in range(0, 256, 15):
                    rgb = r << 16 | g << 8 | b
                    self.assertEqual(oklab_to_rgb(rgb_to_oklab(rgb)), rgb)


class BlendedDrawTests(unittest.TestCase):
    def setUp(self):
        map_utils.set_random_seed(0)
        self.addCleanup(map_utils.set_random_seed, 0)
        pygame_draw_tilemap.last_autotile_num = 0
        self.tilemap = build_mixed_tilemap()
        outdoor, indoor = PALETTES.outdoor_palettes(), PALETTES.indoor_palettes()
        self.tilemap.current_outdoor_palette = outdoor[0].nid
        self.tilemap.current_indoor_palette = indoor[0].nid
        self.tilemap.palette_fields = PaletteFields(
            True,
            [PaletteSource(outdoor[0].nid, (0, 0)), PaletteSource(outdoor[1].nid, (19, 19))],
            [PaletteSource(indoor[0].nid, (8, 19)), PaletteSource(indoor[1].nid, (19, 15))])
        draw_at_frame(self.tilemap, 0)

    def test_autotile_frames_match_fresh_draw(self):
        for frame in (1, 7, 15):
            incremental = draw_at_frame(self.tilemap, frame)
            self.assertEqual(incremental, fresh_draw_at_frame(self.tilemap, frame), frame)

    def test_far_inside_a_field_drawn_as_with_its_palette_alone(self):
        self.assertEqual(self.tilemap.palette_blend((0, 0), True), Blend.pure(self.tilemap.current_outdoor_palette))
        blended = fresh_draw_at_frame(self.tilemap, 0)
        self.tilemap.palette_fields.enabled = False
        alone = fresh_draw_at_frame(self.tilemap, 0)
        width = self.tilemap.width * TILEWIDTH * 4  # Bytes in a row of pixels

        def tile(image: bytes, pos) -> List[bytes]:
            return [image[(pos[1] * TILEHEIGHT + y) * width + pos[0] * TILEWIDTH * 4:
                          (pos[1] * TILEHEIGHT + y) * width + (pos[0] + 1) * TILEWIDTH * 4]
                    for y in range(TILEHEIGHT)]
        self.assertEqual(tile(blended, (1, 1)), tile(alone, (1, 1)))
        self.assertNotEqual(tile(blended, (10, 10)), tile(alone, (10, 10)))
        self.assertNotEqual(blended, alone)

    def test_qt_draws_as_pygame(self):
        self.tilemap.reset_all()
        qt_draw_tilemap.last_autotile_num = 0
        image = qt_draw_tilemap.draw_tilemap(self.tilemap, autotile_fps=0).convertToFormat(QImage.Format_RGBA8888)
        qt_bytes = image.constBits().asstring(image.sizeInBytes())
        self.assertEqual(qt_bytes, fresh_draw_at_frame(self.tilemap, 0))


if __name__ == '__main__':
    unittest.main()
