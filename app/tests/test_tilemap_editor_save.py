import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.tests import qt_headless  # noqa: F401 -- before any QApplication

MARKER = 'TEST_MARKER_TERRAIN'


class TilemapEditorSaveTests(unittest.TestCase):
    '''
    The tilemap editor has only Close, which keeps its edits, as every editor window
    does; undo takes them back. Like every resource edit, they reach the project on
    disk when the project is saved.
    '''

    @classmethod
    def setUpClass(cls) -> None:
        import sys
        from app.editor.editor_locale import init_locale
        init_locale()
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self) -> None:
        from app.data.database.database import DB
        from app.data.resources.resources import RESOURCES
        from app.data.serialization.versions import CURRENT_SERIALIZATION_VERSION
        from app.editor.edit_history import HISTORY

        self.tmp_dir = tempfile.mkdtemp()
        self.proj = os.path.join(self.tmp_dir, 'save_test.ltproj')
        # testing_proj, not default.ltproj: a sixth the size, so copying and
        # loading it takes a fraction of the time
        shutil.copytree('testing_proj.ltproj', self.proj)

        DB.load(self.proj, CURRENT_SERIALIZATION_VERSION)
        RESOURCES.load(self.proj, CURRENT_SERIALIZATION_VERSION)
        HISTORY.clear()
        self.version = CURRENT_SERIALIZATION_VERSION

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @classmethod
    def tearDownClass(cls) -> None:
        # RESOURCES.load points the global SPRITES dict at the loaded project's
        # custom_sprites, so every temp project this class loads leaves those
        # entries holding paths under a directory tearDown has deleted. The next
        # sprites.load_images() anywhere in the suite then dies on a missing file.
        # Leave the singletons on the project the rest of the suite expects.
        from app.data.database.database import DB
        from app.data.resources.resources import RESOURCES
        from app.data.serialization.versions import CURRENT_SERIALIZATION_VERSION
        RESOURCES.load('testing_proj.ltproj', CURRENT_SERIALIZATION_VERSION)
        DB.load('testing_proj.ltproj', CURRENT_SERIALIZATION_VERSION)

    def terrain(self):
        from app.data.resources.resources import RESOURCES
        return RESOURCES.tilemaps[0].layers[0].terrain_grid.get((0, 0))

    def terrain_on_disk(self):
        """What the project on disk says the first tilemap's origin terrain is"""
        from app.data.resources.resources import RESOURCES
        RESOURCES.load(self.proj, self.version)
        return self.terrain()

    def edit_and_close(self, editor):
        editor.current.layers[0].terrain_grid[(0, 0)] = MARKER
        editor.reject()  # As Close, Escape and the window's X do

    def test_closing_the_tilemap_editor_keeps_its_edits(self):
        from app.data.resources.resources import RESOURCES
        from app.editor.tilemap_editor import MapEditor
        self.edit_and_close(MapEditor(None, RESOURCES.tilemaps[0]))

        self.assertEqual(MARKER, self.terrain())

    def test_edits_survive_closing_the_tilemap_dialog_and_undo_there_takes_them_back(self):
        from app.editor.data_editor import SingleResourceEditor
        from app.editor.tile_editor.tile_tab import TileMapDatabase
        from app.editor.tilemap_editor import MapEditor
        before = self.terrain()
        dialog = SingleResourceEditor(TileMapDatabase, ['tilemaps'])
        self.addCleanup(dialog.stop_history)
        tab = dialog.tab
        tab.view.setCurrentIndex(tab.model.index(0))

        with patch.object(MapEditor, 'exec_', lambda editor: self.edit_and_close(editor)):
            tab.edit_current()
        self.assertEqual(MARKER, self.terrain())
        dialog.undo()
        self.assertEqual(before, self.terrain())
        dialog.redo()
        dialog.reject()

        self.assertEqual(MARKER, self.terrain())

    def test_the_tilemap_list_shows_the_picture_the_edits_leave(self):
        from app.editor.data_editor import SingleResourceEditor
        from app.editor.tile_editor import tile_model
        from app.editor.tile_editor.tile_tab import TileMapDatabase
        from app.editor.tilemap_editor import MapEditor
        dialog = SingleResourceEditor(TileMapDatabase, ['tilemaps'])
        self.addCleanup(dialog.stop_history)
        tab = dialog.tab
        tab.view.setCurrentIndex(tab.model.index(0))
        tilemap = tab.current
        before = tilemap.pixmap.toImage()

        def erase_a_tile(editor):
            base = editor.current.layers.get('base')
            del base.sprite_grid[next(iter(base.sprite_grid))]
            editor.reject()
        with patch.object(MapEditor, 'exec_', erase_a_tile):
            tab.edit_current()

        shown = tilemap.pixmap.toImage()
        self.assertNotEqual(before, shown)
        self.assertEqual(tile_model.create_tilemap_pixmap(tilemap).toImage(), shown)

    def test_edits_write_nothing_to_the_project_until_it_is_saved(self):
        from app.data.resources.resources import RESOURCES
        from app.editor.tilemap_editor import MapEditor
        before = self.terrain()
        self.edit_and_close(MapEditor(None, RESOURCES.tilemaps[0]))

        self.assertEqual(before, self.terrain_on_disk())


class TileEditorUndoTests(TilemapEditorSaveTests):
    """Undo and redo in the tilemap and tileset terrain editors reach only the steps
    made since the editor opened, one per stroke, and after Close they stay in the
    edit history"""
    def setUp(self) -> None:
        super().setUp()
        from app.data.resources.resources import RESOURCES
        from app.editor.edit_history import HISTORY
        self.history = HISTORY
        self.tilemap = RESOURCES.tilemaps[0]
        # An edit from before the editor opens, which its undo must leave alone
        HISTORY.bind(self.tilemap, RESOURCES.tilemaps, self)
        self.grid()[(2, 0)] = 'Before'
        HISTORY.unbind(self)
        self.original = dict(self.grid())

    def grid(self) -> dict:
        # Read afresh each time: an undo rebuilds the tilemap's layers
        return self.tilemap.layers[0].terrain_grid

    def open_map_editor(self):
        from app.editor.tilemap_editor import MapEditor
        editor = MapEditor(None, self.tilemap)
        self.addCleanup(editor.deleteLater)
        return editor

    def stroke(self, editor, coord, terrain_nid):
        """Paints terrain, finished by the mouse button's release on the map"""
        from PyQt5.QtCore import QPoint, Qt
        from PyQt5.QtTest import QTest
        editor.current.layers[0].terrain_grid[coord] = terrain_nid
        QTest.mouseRelease(editor.view.viewport(), Qt.LeftButton, pos=QPoint(4, 4))

    def test_each_stroke_is_undone_and_redone_on_its_own_and_undo_stops_where_it_opened(self):
        editor = self.open_map_editor()
        self.stroke(editor, (0, 0), 'A')
        self.stroke(editor, (1, 0), 'B')

        editor.undo()
        self.assertEqual('A', self.grid().get((0, 0)))
        self.assertEqual(self.original.get((1, 0)), self.grid().get((1, 0)))
        editor.undo()
        editor.undo()  # Nothing left of this editor's to undo
        self.assertEqual(self.original, dict(self.grid()))
        self.assertEqual('Before', self.grid()[(2, 0)])

        editor.redo()
        editor.redo()
        self.assertEqual('A', self.grid()[(0, 0)])
        self.assertEqual('B', self.grid()[(1, 0)])

    def test_the_layer_list_shows_the_layers_an_undo_leaves(self):
        editor = self.open_map_editor()
        count = len(self.tilemap.layers)
        editor.layer_menu.new()
        self.assertEqual(count + 1, len(self.tilemap.layers))

        editor.undo()

        self.assertEqual(count, len(self.tilemap.layers))
        self.assertIs(self.tilemap.layers, editor.layer_menu.model._data)
        self.assertEqual(count, editor.layer_menu.model.rowCount())
        self.assertTrue(editor.layer_menu.view.currentIndex().isValid())

    def test_after_close_each_stroke_is_still_an_undo_step(self):
        editor = self.open_map_editor()
        self.stroke(editor, (0, 0), 'A')
        self.stroke(editor, (1, 0), 'B')
        editor.reject()

        self.history.undo()

        self.assertEqual('A', self.grid()[(0, 0)])
        self.assertEqual(self.original.get((1, 0)), self.grid().get((1, 0)))

    def test_the_tileset_terrain_editor_undoes_each_stroke_and_close_keeps_them(self):
        from app.data.resources.resources import RESOURCES
        from app.editor.tileset_editor import TileSetEditor
        tileset = RESOURCES.tilesets[0]
        original = dict(tileset.terrain_grid)
        editor = TileSetEditor(None, tileset)
        self.addCleanup(editor.deleteLater)
        for coord, terrain_nid in (((0, 0), 'A'), ((1, 0), 'B')):
            tileset.terrain_grid[coord] = terrain_nid
            editor.handle_mouse_release()  # As the stroke's release does

        editor.undo()
        self.assertEqual('A', tileset.terrain_grid[(0, 0)])
        self.assertEqual(original.get((1, 0)), tileset.terrain_grid.get((1, 0)))
        self.assertIsNotNone(tileset.pixmap)  # Loaded again for the view
        editor.redo()
        self.assertEqual('B', tileset.terrain_grid[(1, 0)])

        editor.reject()
        self.assertEqual('A', tileset.terrain_grid[(0, 0)])
        self.assertEqual('B', tileset.terrain_grid[(1, 0)])
        self.history.undo()
        self.assertEqual(original.get((1, 0)), tileset.terrain_grid.get((1, 0)))


if __name__ == '__main__':
    unittest.main()


class TilemapFillTests(TilemapEditorSaveTests):
    """The bucket fills with the tile a right click picked off the map, as with one
    picked from the tileset"""
    def click(self, editor, button, coord):
        from PyQt5.QtCore import Qt
        from PyQt5.QtTest import QTest
        from app.constants import TILEWIDTH, TILEHEIGHT
        pos = editor.view.mapFromScene(coord[0] * TILEWIDTH + TILEWIDTH // 2, coord[1] * TILEHEIGHT + TILEHEIGHT // 2)
        QTest.mousePress(editor.view.viewport(), button, Qt.NoModifier, pos)
        QTest.mouseRelease(editor.view.viewport(), button, Qt.NoModifier, pos)

    def test_the_bucket_fills_with_a_tile_picked_by_right_click(self):
        from PyQt5.QtCore import Qt
        from app.data.resources.resources import RESOURCES
        from app.editor.tilemap_editor import MapEditor, PaintTool
        tilemap = RESOURCES.tilemaps[0]
        layer = tilemap.layers[0]
        tileset_nid = tilemap.tilesets[0]
        layer.sprite_grid.clear()
        for x in range(tilemap.width):
            for y in range(tilemap.height):
                layer.set_sprite((x, y), tileset_nid, (0, 0))
        layer.set_sprite((0, 0), tileset_nid, (1, 0))

        editor = MapEditor(None, tilemap)
        self.addCleanup(editor.deleteLater)
        editor.current_tool = PaintTool.Brush
        self.click(editor, Qt.RightButton, (0, 0))
        editor.current_tool = PaintTool.Fill
        self.click(editor, Qt.LeftButton, (2, 2))

        self.assertEqual({(1, 0)}, {sprite.tileset_position for sprite in tilemap.layers[0].sprite_grid.values()})
