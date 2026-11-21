import sys
import unittest
from unittest.mock import patch

from app.tests import qt_headless  # noqa: F401  Before the QApplication
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMessageBox

import app.map_maker.utilities as map_utils
from app.map_maker.map_history import history_form
from app.map_maker.map_prefab import MapPrefab
from app.map_maker.palette_collection import PALETTES
from app.map_maker.terrain import Terrain

app = QApplication.instance() or QApplication(sys.argv)

from app.map_maker.editor.map_editor import MapEditor
from app.map_maker.editor.map_editor_view import PaintTool


class MapMakerUndoTests(unittest.TestCase):
    """Undo and redo through the map maker's window: each stroke or action is a
    step, and the window shows the map's fields again after each"""
    def setUp(self):
        map_utils.set_random_seed(0)
        self.addCleanup(map_utils.set_random_seed, 0)
        self.editor = MapEditor(current=MapPrefab('sample'))
        self.addCleanup(self.editor.deleteLater)
        self.view = self.editor.view
        self.start = history_form(self.editor.current)

    def stroke(self, tool: PaintTool, positions, terrain: Terrain = None):
        """A press, a drag over positions and a release, as the view makes them"""
        self.editor.current_tool = tool
        if terrain:
            self.editor.terrain_tab.setCurrentIndex(0 if terrain.outdoor else 1)
            self.editor.terrain_painter_menu().set_current_terrain(terrain)
        self.view.start_stroke('Paint' if tool == PaintTool.Brush else 'Erase')
        for pos in positions:
            if tool == PaintTool.Brush:
                self.view.paint_terrain(pos)
            else:
                self.view.erase_terrain(pos)
        self.view.end_stroke()

    def test_opening_the_map_is_no_edit(self):
        self.assertFalse(self.editor.history.is_modified())
        self.assertFalse(self.editor.undo_action.isEnabled())
        self.assertFalse(self.editor.redo_action.isEnabled())

    def test_each_stroke_is_one_step(self):
        self.stroke(PaintTool.Brush, [(1, 1), (2, 1), (3, 1)], Terrain.GRASS)
        one = history_form(self.editor.current)
        self.stroke(PaintTool.Erase, [(2, 1)])
        self.assertEqual(self.editor.undo_action.text(), 'Undo erase')

        self.editor.undo_action.trigger()
        self.assertEqual(history_form(self.editor.current), one)
        self.assertEqual(self.editor.undo_feedback.text(), 'Undid erase')
        self.assertEqual(self.editor.redo_action.text(), 'Redo erase')
        self.editor.undo_action.trigger()
        self.assertEqual(history_form(self.editor.current), self.start)
        self.assertFalse(self.editor.undo_action.isEnabled())
        self.editor.redo_action.trigger()
        self.assertEqual(history_form(self.editor.current), one)

    def test_undo_in_the_middle_of_a_stroke_ends_it(self):
        self.editor.current_tool = PaintTool.Brush
        self.editor.terrain_painter_menu().set_current_terrain(Terrain.GRASS)
        self.view.start_stroke('Paint')
        self.view.paint_terrain((4, 4))
        self.editor.undo()
        self.assertFalse(self.view.left_selecting)
        self.assertEqual(history_form(self.editor.current), self.start)
        self.editor.redo()
        self.assertEqual(self.editor.current.get_terrain((4, 4)), Terrain.GRASS)

    def test_boxes_show_undone_values(self):
        self.editor.autotile_fps_box.edit.setValue(10)
        self.editor.autotile_fps_box.edit.setValue(12)
        self.editor.random_seed_box.edit.setValue(40)
        self.editor.undo()
        self.assertEqual(self.editor.random_seed_box.edit.value(), 0)
        self.assertEqual((self.editor.current.seed, map_utils.get_random_seed()), (0, 0))
        self.editor.undo()  # Both values the box took, as one step
        self.assertEqual(self.editor.autotile_fps_box.edit.value(), 29)
        self.assertEqual(self.editor.current.autotile_fps, 29)
        self.assertFalse(self.editor.undo_action.isEnabled())
        self.editor.redo()
        self.assertEqual(self.editor.autotile_fps_box.edit.value(), 12)

    def test_palette_undo_selects_and_draws_it(self):
        palettes = PALETTES.outdoor_palettes()
        before = self.editor.current.current_outdoor_palette
        other = next(p.nid for p in palettes if p.nid != before)
        self.editor.outdoor_palette_selector.edit.setCurrentIndex(palettes.index(other))
        self.assertEqual(self.editor.current.current_outdoor_palette, other)
        self.assertEqual(self.editor.drawn_palettes[1], other)
        self.editor.undo()
        self.assertEqual(self.editor.current.current_outdoor_palette, before)
        self.assertEqual(self.editor.outdoor_palette_selector.edit.currentIndex(), palettes.index(before))
        self.assertEqual(self.editor.drawn_palettes[1], before)
        self.assertFalse(self.editor.undo_action.isEnabled())

    def test_cliff_markers_undo(self):
        self.editor.cliff_marker_widget.add_new_marker((2, 2))
        self.editor.cliff_marker_widget.main_box.edit.setCurrentIndex(0)
        self.editor.remove_cliff_marker()
        self.assertEqual(self.editor.current.cliff_markers, [(2, 2)])
        self.editor.undo()
        self.assertEqual(self.editor.current.cliff_markers, [(7, 5), (2, 2)])
        self.assertEqual(self.editor.cliff_marker_widget.main_box.edit.count(), 2)
        self.editor.undo()
        self.assertEqual(self.editor.current.cliff_markers, [(7, 5)])
        self.assertEqual(self.editor.cliff_marker_widget.main_box.edit.count(), 1)

    def test_clear_all_undo(self):
        self.stroke(PaintTool.Brush, [(5, 5)], Terrain.SAND)
        painted = history_form(self.editor.current)
        self.editor.clear_map()
        self.editor.undo()
        self.assertEqual(history_form(self.editor.current), painted)

    def test_asks_to_save_only_when_modified(self):
        with patch.object(QMessageBox, 'warning', return_value=QMessageBox.Discard) as warning:
            self.assertTrue(self.editor.maybe_save())
            warning.assert_not_called()
            self.stroke(PaintTool.Brush, [(5, 5)], Terrain.SAND)
            self.assertTrue(self.editor.maybe_save())
            warning.assert_called_once()
            # Undone back to the map as it was opened
            self.editor.undo()
            warning.reset_mock()
            self.assertTrue(self.editor.maybe_save())
            warning.assert_not_called()

    def press(self, widget, key, modifiers):
        """A key pressed with widget focused in the active window, through Qt's shortcuts"""
        self.editor.show()
        self.editor.activateWindow()
        widget.setFocus()
        app.processEvents()
        self.assertIs(QApplication.focusWidget(), widget)
        QTest.keyClick(widget, key, modifiers)

    def test_undo_keys_in_the_seed_box(self):
        """The seed box's text claims the undo keys ahead of the window's shortcuts,
        with no typing of its own to undo"""
        seed_box = self.editor.random_seed_box.edit
        seed_box.setValue(40)
        self.press(seed_box, Qt.Key_Z, Qt.ControlModifier)
        self.assertEqual((seed_box.value(), map_utils.get_random_seed()), (0, 0))
        self.press(seed_box, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
        self.assertEqual((seed_box.value(), map_utils.get_random_seed()), (40, 40))
        self.press(seed_box, Qt.Key_Z, Qt.ControlModifier)
        self.press(seed_box, Qt.Key_Y, Qt.ControlModifier)
        self.assertEqual(seed_box.value(), 40)

    def test_both_redo_keys_on_the_map(self):
        self.stroke(PaintTool.Brush, [(5, 5)], Terrain.SAND)
        self.press(self.view, Qt.Key_Z, Qt.ControlModifier)
        self.assertIsNone(self.editor.current.get_terrain((5, 5)))
        self.press(self.view, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
        self.assertEqual(self.editor.current.get_terrain((5, 5)), Terrain.SAND)
        self.press(self.view, Qt.Key_Z, Qt.ControlModifier)
        self.press(self.view, Qt.Key_Y, Qt.ControlModifier)
        self.assertEqual(self.editor.current.get_terrain((5, 5)), Terrain.SAND)

    def test_new_map_starts_a_history_of_its_own(self):
        self.stroke(PaintTool.Brush, [(5, 5)], Terrain.SAND)
        with patch('app.map_maker.editor.map_editor.ResizeDialog.get_new_size', return_value=True), \
                patch.object(QMessageBox, 'warning', return_value=QMessageBox.Discard):
            self.editor.new()
        self.assertFalse(self.editor.undo_action.isEnabled())
        self.assertIs(self.editor.cliff_marker_widget.tilemap, self.editor.current)
        self.stroke(PaintTool.Brush, [(1, 1)], Terrain.SAND)
        self.editor.undo()
        self.assertIsNone(self.editor.current.get_terrain((1, 1)))


if __name__ == '__main__':
    unittest.main()
