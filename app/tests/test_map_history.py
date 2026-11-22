import random
import unittest

import pygame

from app.constants import TILEWIDTH, TILEHEIGHT
import app.map_maker.utilities as map_utils
from app.map_maker.map_history import MAX_STEPS, MapHistory, history_form
from app.map_maker.palette_collection import PALETTES
from app.map_maker.terrain import Terrain
import app.map_maker.pygame_renderers.draw_tilemap as pygame_draw_tilemap
from app.tests.test_map_prefab import build_mixed_tilemap, update_at_frame


class MapHistoryTests(unittest.TestCase):
    def setUp(self):
        map_utils.set_random_seed(0)
        self.addCleanup(map_utils.set_random_seed, 0)
        pygame_draw_tilemap.last_autotile_num = 0
        self.tilemap = build_mixed_tilemap()
        update_at_frame(self.tilemap, 0)
        # The image a view keeps of the map, drawn again only where tile_grid_changed says
        self.image = pygame_draw_tilemap.simple_draw_tilemap(self.tilemap)
        self.tilemap.tile_grid_changed.clear()
        self.history = MapHistory(self.tilemap)
        self.start = history_form(self.tilemap)

    def assert_drawn_as_fresh(self, frame: int, msg=None):
        """The view's image, brought up to date only where tiles changed, is the
        map drawn from scratch"""
        update_at_frame(self.tilemap, frame)
        size = (self.tilemap.width * TILEWIDTH, self.tilemap.height * TILEHEIGHT)
        if self.image.get_size() != size:
            # A view draws a map that changes size again from the start
            self.image = pygame_draw_tilemap.simple_draw_tilemap(self.tilemap)
        else:
            for pos in self.tilemap.tile_grid_changed:
                rect = (pos[0] * TILEWIDTH, pos[1] * TILEHEIGHT, TILEWIDTH, TILEHEIGHT)
                self.image.fill((0, 0, 0, 0), rect)
                if pos in self.tilemap.tile_grid:
                    self.image.blit(self.tilemap.tile_grid[pos], rect)
        self.tilemap.tile_grid_changed.clear()
        drawn = pygame.image.tobytes(self.image, 'RGBA')

        self.tilemap.reset_all()
        pygame_draw_tilemap.last_autotile_num = frame
        update_at_frame(self.tilemap, frame)
        self.tilemap.tile_grid_changed.clear()
        fresh = pygame.image.tobytes(pygame_draw_tilemap.simple_draw_tilemap(self.tilemap), 'RGBA')
        self.assertEqual(drawn, fresh, msg)

    def paint(self, positions, terrain):
        for pos in positions:
            self.tilemap.set(pos, self.tilemap.get_terrain(pos), terrain)

    def test_stroke_undoes_and_redoes(self):
        self.paint([(12, 12), (13, 12), (14, 12)], Terrain.SEA)
        step = self.history.commit('Paint')
        after = history_form(self.tilemap)
        # Only the tiles painted
        self.assertEqual({where for where, _, _ in step.changes},
                         {('terrain_grid', '12,12'), ('terrain_grid', '13,12'), ('terrain_grid', '14,12')})
        self.assert_drawn_as_fresh(1)

        self.assertIs(self.history.undo(), step)
        self.assertEqual(history_form(self.tilemap), self.start)
        self.assertFalse(self.history.can_undo())
        self.assert_drawn_as_fresh(2)

        self.assertIs(self.history.redo(), step)
        self.assertEqual(history_form(self.tilemap), after)
        self.assertFalse(self.history.can_redo())
        self.assert_drawn_as_fresh(3)

    def test_erase_undoes_and_redoes(self):
        for pos in [(0, 0), (1, 0), (2, 3), (15, 15), (11, 4)]:
            self.tilemap.erase_terrain(pos, self.tilemap.get_terrain(pos))
        self.history.commit('Erase')
        after = history_form(self.tilemap)
        self.assert_drawn_as_fresh(1)
        self.history.undo()
        self.assertEqual(history_form(self.tilemap), self.start)
        self.assertEqual(self.tilemap.autotile_set, {pos for pos, terrain in self.tilemap.terrain_grid.items()
                                                     if terrain in (Terrain.SEA, Terrain.RIVER, Terrain.POOL)})
        self.assert_drawn_as_fresh(2)
        self.history.redo()
        self.assertEqual(history_form(self.tilemap), after)
        self.assert_drawn_as_fresh(3)

    def test_resize_and_clear_undo(self):
        self.tilemap.resize(24, 18, 3, -2)
        self.history.commit('Resize')
        resized = history_form(self.tilemap)
        self.assert_drawn_as_fresh(1)
        self.tilemap.clear()
        self.history.commit('Clear All')
        self.assert_drawn_as_fresh(2)

        self.history.undo()
        self.assertEqual(history_form(self.tilemap), resized)
        self.assert_drawn_as_fresh(3)
        self.history.undo()
        self.assertEqual(history_form(self.tilemap), self.start)
        self.assertEqual((self.tilemap.width, self.tilemap.height), (20, 20))
        self.assert_drawn_as_fresh(4)
        self.history.redo()
        self.assertEqual(history_form(self.tilemap), resized)
        self.assert_drawn_as_fresh(5)

    def test_generated_map_of_the_same_size_undoes(self):
        """A generated map replaces the whole terrain grid. Positions it leaves
        empty lose their sprites, and undo puts them back"""
        grid = {(x, y): Terrain.GRASS for x in range(20) for y in range(20) if (x + y) % 3}
        self.tilemap.set_new_terrain_grid((20, 20), grid)
        self.history.commit('Autogenerate Map')
        self.assert_drawn_as_fresh(1)
        self.assertFalse(set(self.tilemap.tile_grid) - set(grid))
        self.history.undo()
        self.assertEqual(history_form(self.tilemap), self.start)
        self.assert_drawn_as_fresh(2)

    def test_fields_undo(self):
        self.tilemap.cliff_markers.append((3, 3))
        self.history.commit('Add Cliff Marker')
        self.tilemap.autotile_fps = 12
        self.history.commit('Change Autotile Speed')
        map_utils.set_random_seed(77)
        self.tilemap.seed = 77
        self.history.commit('Change RNG Seed')
        self.tilemap.current_outdoor_palette = PALETTES.outdoor_palettes()[1].nid
        self.history.commit('Change Outdoor Palette')
        after = history_form(self.tilemap)

        for _ in range(4):
            self.history.undo()
        self.assertEqual(history_form(self.tilemap), self.start)
        self.assertEqual(self.tilemap.cliff_markers, [(7, 5)])
        self.assertEqual((self.tilemap.seed, map_utils.get_random_seed()), (0, 0))
        self.assert_drawn_as_fresh(1)
        for _ in range(4):
            self.history.redo()
        self.assertEqual(history_form(self.tilemap), after)
        self.assertEqual(self.tilemap.cliff_markers, [(7, 5), (3, 3)])
        self.assertEqual((self.tilemap.seed, map_utils.get_random_seed()), (77, 77))
        self.assert_drawn_as_fresh(2)

    def test_merged_changes_are_one_step(self):
        for fps in (1, 12, 120):
            self.tilemap.autotile_fps = fps
            self.history.commit('Change Autotile Speed', merge=True)
        self.assertEqual(len(self.history._undo), 1)
        self.history.undo()
        self.assertEqual(self.tilemap.autotile_fps, 29)
        self.history.redo()
        self.assertEqual(self.tilemap.autotile_fps, 120)

        # Another kind of edit in between starts a new step
        self.paint([(12, 12)], Terrain.SEA)
        self.history.commit('Paint')
        self.tilemap.autotile_fps = 5
        self.history.commit('Change Autotile Speed', merge=True)
        self.assertEqual(len(self.history._undo), 3)

        # Spun back to where it started: no step at all
        self.tilemap.autotile_fps = 120
        self.history.commit('Change Autotile Speed', merge=True)
        self.assertEqual(len(self.history._undo), 2)

    def test_nothing_changed_is_no_step(self):
        self.paint([(0, 0)], Terrain.SEA)  # Sea already
        self.assertIsNone(self.history.commit('Paint'))
        self.assertIsNone(self.history.undo())

    def test_edit_after_undo_drops_redo(self):
        self.paint([(12, 12)], Terrain.SEA)
        self.history.commit('Paint')
        self.history.undo()
        self.paint([(13, 13)], Terrain.SAND)
        self.history.commit('Paint')
        self.assertFalse(self.history.can_redo())

    def test_modified_follows_undo_back_to_the_save(self):
        self.assertFalse(self.history.is_modified())
        self.paint([(12, 12)], Terrain.SEA)
        self.assertTrue(self.history.is_modified())  # Committed by asking
        self.history.mark_saved()
        self.assertFalse(self.history.is_modified())
        self.paint([(13, 12)], Terrain.SEA)
        self.history.commit('Paint')
        self.assertTrue(self.history.is_modified())
        self.history.undo()
        self.assertFalse(self.history.is_modified())
        self.history.undo()
        self.assertTrue(self.history.is_modified())
        self.history.redo()
        self.assertFalse(self.history.is_modified())

    def test_modified_once_undo_cannot_reach_the_opened_map(self):
        for index in range(MAX_STEPS + 1):
            self.tilemap.autotile_fps = 100 + index
            self.history.commit('Change Autotile Speed')
        while self.history.undo():
            pass
        self.assertEqual(self.tilemap.autotile_fps, 100)
        self.assertTrue(self.history.is_modified())

    def test_describe(self):
        self.paint([(12, 12)], Terrain.SEA)
        self.assertEqual(self.history.describe(self.history.commit('Paint')), 'paint')
        self.tilemap.autotile_fps = 3
        self.tilemap.cliff_markers.append((1, 1))
        self.assertEqual(self.history.describe(self.history.commit()), 'edit to autotile speed, cliff markers')

    def test_random_edits_undo_back_to_the_start(self):
        rng = random.Random(4)
        brushes = [Terrain.GRASS, Terrain.SAND, Terrain.SEA, Terrain.RIVER,
                   Terrain.FOREST, Terrain.POOL, Terrain.FLOOR_1, None]
        forms = [self.start]
        for step in range(25):
            positions = [(rng.randrange(20), rng.randrange(20)) for _ in range(rng.randrange(1, 6))]
            brush = rng.choice(brushes)
            if brush:
                self.tilemap.set_many({pos: brush for pos in positions})
            else:
                self.tilemap.erase_many([pos for pos in positions if self.tilemap.get_terrain(pos)])
            if self.history.commit('Paint'):
                forms.append(history_form(self.tilemap))
            self.assert_drawn_as_fresh(step % 16, step)
        for step in range(len(forms) - 1):
            self.history.undo()
            self.assertEqual(history_form(self.tilemap), forms[-2 - step])
            self.assert_drawn_as_fresh(step % 16, ('undo', step))
        for step in range(len(forms) - 1):
            self.history.redo()
            self.assertEqual(history_form(self.tilemap), forms[1 + step])
        self.assert_drawn_as_fresh(5)


if __name__ == '__main__':
    unittest.main()
