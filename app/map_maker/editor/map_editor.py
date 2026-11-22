from typing import Optional, Tuple

import os
import json

from PyQt5.QtWidgets import QFrame, QVBoxLayout, \
    QToolBar, QSpinBox, QAction, QMenu, QDockWidget, \
    QActionGroup, QWidget, QMainWindow, QLabel, QSizePolicy, \
    QDesktopWidget, QFileDialog, QHBoxLayout, QMessageBox, \
    QTabWidget, QApplication
from PyQt5 import sip
from PyQt5.QtCore import Qt, QDir, QEvent, QTimer
from PyQt5.QtGui import QIcon, QImage, QPainter, QColor, QKeySequence

from app import dark_theme

from app.constants import TILEWIDTH, TILEHEIGHT, AUTOTILE_FRAMES

from app.extensions.custom_gui import PropertyBox, ComboBox
from app.editor.settings import MainSettingsController
from app.editor.undo_keys import handles_own_undo, held_in_text_field, set_undo_shortcuts

from .resize_dialog import ResizeDialog
from .terrain_painter_menu import TerrainPainterMenu
from .map_editor_view import PaintTool, MapEditorView
from .draw_tilemap import simple_draw_tilemap
from .palette_model import PaletteModel
from .palette_fields_widget import PaletteFieldsWidget
from .nid_dialog import NidDialog
from .autogenerate_indoor_map import AutogenerateIndoorMap
from .autogenerate_outdoor_map import AutogenerateOutdoorMap

from app.map_maker.map_prefab import MapPrefab
from app.map_maker.map_history import MapHistory, MapStep
import app.map_maker.utilities as map_utils
from app.map_maker.palette_collection import PALETTES
from app.map_maker.qt_renderers.qt_palette import palette_at
from app.map_maker.qt_renderers.renderer_database import RENDERERS
from app.map_maker.terrain import Terrain

class CliffMarkerWidget(QWidget):
    def __init__(self, parent=None, tilemap=None):
        super().__init__(parent)
        self.window = parent
        self.tilemap = tilemap

        self.layout = QHBoxLayout()
        self.setLayout(self.layout)
        self.layout.setSpacing(0)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.main_box = PropertyBox("Cliff Markers", ComboBox, self)
        self.main_box.setMaximumWidth(100)
        self.main_box.setMinimumWidth(100)
        self.show_markers()
        # self.main_box.edit.activated.connect(self.main_box_activation)

        self.toolbar = QToolBar(self)
        self.toolbar.addAction(self.window.add_cliff_marker_action)
        self.toolbar.addAction(self.window.remove_cliff_marker_action)

        self.layout.addWidget(self.main_box)
        self.layout.addWidget(self.toolbar)

    def set_current(self, current):
        self.tilemap = current
        self.show_markers()
        self.reset()

    def show_markers(self):
        self.main_box.edit.clear()
        for cliff_marker in self.tilemap.cliff_markers:
            self.main_box.edit.addItem("%d, %d" % cliff_marker)
        self.toggle_remove_button()

    def reset(self):
        self.window.add_cliff_marker_action.setChecked(False)
        self.toggle_remove_button()

    def add_new_marker(self, pos):
        self.reset()
        self.tilemap.cliff_markers.append(pos)
        self.main_box.edit.addItem("%d, %d" % self.tilemap.cliff_markers[-1])
        self.tilemap.reset_all()
        self.toggle_remove_button()
        self.window.commit('Add Cliff Marker')

    def toggle_remove_button(self):
        self.window.remove_cliff_marker_action.setEnabled(len(self.tilemap.cliff_markers) > 1)

class UndoFeedback(QLabel):
    """Says what an undo or redo just took back or put back, for a few seconds"""
    SHOWN_FOR = 5000  # ms

    def __init__(self, parent=None):
        super().__init__(parent)
        self.clear_timer = QTimer(self)
        self.clear_timer.setSingleShot(True)
        self.clear_timer.timeout.connect(self.clear)

    def show_step(self, history: MapHistory, step: Optional[MapStep], redo: bool) -> None:
        """step is what history.undo or redo returned, None when there was nothing to do"""
        if step is None:
            self.setText("Nothing to redo" if redo else "Nothing to undo")
        else:
            self.setText(("Redid %s" if redo else "Undid %s") % history.describe(step))
        self.clear_timer.start(self.SHOWN_FOR)

class MapEditor(QMainWindow):
    title = "LT Map Maker"

    def __init__(self, parent=None, current: Optional[MapPrefab] = None):
        super().__init__(parent)
        self.window = parent
        self.setWindowTitle(self.title)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        self.settings = MainSettingsController()

        desktop = QDesktopWidget()
        main_screen_size = desktop.availableGeometry(desktop.primaryScreen())
        default_size = int(main_screen_size.width()*0.7), int(main_screen_size.height()*0.7)
        self.resize(*default_size)

        self.current = current
        self.current_map_save_location = None
        self.current_tool = PaintTool.NoTool

        self.outdoor_terrain_painter_menu = TerrainPainterMenu(Terrain.outdoor_terrain(), self)
        self.indoor_terrain_painter_menu = TerrainPainterMenu(Terrain.indoor_terrain(), self)

        self.view = MapEditorView(self)
        self.view.set_current(current)

        self.autotile_fps_box = PropertyBox("Autotile Speed", QSpinBox, self)
        self.autotile_fps_box.edit.setValue(self.current.autotile_fps)
        self.autotile_fps_box.setMaximumWidth(100)
        self.autotile_fps_box.edit.setAlignment(Qt.AlignRight)
        self.autotile_fps_box.edit.valueChanged.connect(self.autotile_fps_changed)

        self.random_seed_box = PropertyBox("RNG Seed", QSpinBox, self)
        self.random_seed_box.edit.setRange(0, 1023)
        self.random_seed_box.edit.setValue(map_utils.get_random_seed())
        self.random_seed_box.setMaximumWidth(100)
        self.random_seed_box.edit.setAlignment(Qt.AlignRight)
        self.random_seed_box.edit.valueChanged.connect(self.random_seed_changed)

        self.setCentralWidget(self.view)

        self.create_actions()
        self.create_menus()
        self.create_toolbar()

        self.cliff_marker_widget = CliffMarkerWidget(self, self.current)

        self.toolbar.addSeparator()
        self.toolbar.addWidget(self.cliff_marker_widget)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.toolbar.addWidget(spacer)
        self.toolbar.addWidget(self.autotile_fps_box)
        fixed_space = QLabel()
        fixed_space.setFixedWidth(10)
        self.toolbar.addWidget(fixed_space)
        self.toolbar.addWidget(self.random_seed_box)

        # Palette selectors
        self.outdoor_palette_selector = PropertyBox("Palette", ComboBox, self)
        outdoor_palette_model = PaletteModel(PALETTES.outdoor_palettes(), self)
        self.outdoor_palette_selector.edit.setModel(outdoor_palette_model)
        self.outdoor_palette_selector.edit.currentIndexChanged.connect(self.outdoor_palette_changed)

        self.indoor_palette_selector = PropertyBox("Palette", ComboBox, self)
        indoor_palette_model = PaletteModel(PALETTES.indoor_palettes(), self)
        self.indoor_palette_selector.edit.setModel(indoor_palette_model)
        self.indoor_palette_selector.edit.currentIndexChanged.connect(self.indoor_palette_changed)

        # The palettes the renderers draw with, (indoor, outdoor)
        self.drawn_palettes = (None, None)
        self.show_palettes()

        self.terrain_tab = QTabWidget(self)

        # Outdoor
        outdoor_frame = QFrame(self)
        outdoor_layout = QVBoxLayout()
        outdoor_frame.setLayout(outdoor_layout)
        outdoor_layout.addWidget(self.outdoor_terrain_painter_menu)
        outdoor_layout.addWidget(self.outdoor_palette_selector)
        self.terrain_tab.addTab(outdoor_frame, "Outdoor Terrain")

        # Indoor
        indoor_frame = QFrame(self)
        indoor_layout = QVBoxLayout()
        indoor_frame.setLayout(indoor_layout)
        indoor_layout.addWidget(self.indoor_terrain_painter_menu)
        indoor_layout.addWidget(self.indoor_palette_selector)
        self.terrain_tab.addTab(indoor_frame, "Indoor Terrain")

        self.terrain_dock = QDockWidget("Terrain", self)
        self.terrain_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.terrain_dock.setWidget(self.terrain_tab)
        self.terrain_dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.addDockWidget(Qt.RightDockWidgetArea, self.terrain_dock)

        # Shown only while the map has its palette fields on
        self.palette_fields_widget = PaletteFieldsWidget(self)
        self.palette_fields_dock = QDockWidget("Palette Fields", self)
        self.palette_fields_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.palette_fields_dock.setWidget(self.palette_fields_widget)
        self.palette_fields_dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.addDockWidget(Qt.RightDockWidgetArea, self.palette_fields_dock)
        # Which source's origin a click on the map places, as (outdoor, index)
        self.picked_source: Optional[Tuple[bool, int]] = None
        self.show_palette_fields()

        self.position_bar = QLabel("", self)
        self.position_bar.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        self.position_bar.setMinimumWidth(100)
        self.undo_feedback = UndoFeedback(self)
        self.statusBar().addPermanentWidget(self.undo_feedback)
        self.statusBar().addPermanentWidget(self.position_bar)

        self.check_brush()

        self.history = MapHistory(self.current)
        self.update_undo_actions()
        # The focused widget, watched for the undo keys
        self.key_widget: Optional[QWidget] = None
        QApplication.instance().focusChanged.connect(self.on_focus_changed)

        # Restore Geometry
        geometry = self.settings.component_controller.get_geometry(self._type())
        if geometry:
            self.restoreGeometry(geometry)

        self.view.update_view()

    def terrain_painter_menu(self):
        if self.terrain_tab.currentIndex() == 0:
            return self.outdoor_terrain_painter_menu
        else:
            return self.indoor_terrain_painter_menu

    def palette_selector(self):
        if self.terrain_tab.currentIndex() == 0:
            return self.outdoor_palette_selector
        else:
            return self.indoor_palette_selector

    def create_actions(self):
        theme = dark_theme.get_theme()
        icon_folder = theme.icon_dir()

        paint_group = QActionGroup(self)
        self.brush_action = QAction(QIcon(f"{icon_folder}/brush.png"), "Brush", self, shortcut="B", triggered=self.set_brush)
        self.brush_action.setCheckable(True)
        paint_group.addAction(self.brush_action)
        self.paint_action = QAction(QIcon(f"{icon_folder}/fill.png"), "Fill", self, shortcut="F", triggered=self.set_fill)
        self.paint_action.setCheckable(True)
        paint_group.addAction(self.paint_action)
        self.erase_action = QAction(QIcon(f"{icon_folder}/eraser.png"), "Erase", self, shortcut="E", triggered=self.set_erase)
        self.erase_action.setCheckable(True)
        paint_group.addAction(self.erase_action)
        self.resize_action = QAction(QIcon(f"{icon_folder}/resize.png"), "Resize", self, shortcut="R", triggered=self.resize_map)

        self.clear_all_action = QAction(QIcon(f"{icon_folder}/eraser.png"), "Clear All", self, triggered=self.clear_map)
        self.export_as_png_action = QAction(QIcon(f"{icon_folder}/export_as_png.png"), "Export Current Image as PNG", self, triggered=self.export_as_png)
        self.export_to_lt_action = QAction(QIcon("favicon.ico"), "Export to LT-maker", self, triggered=self.export_to_lt)

        self.show_gridlines_action = QAction(QIcon(f"{icon_folder}/gridlines.png"), "Show GridLines", self, triggered=self.gridline_toggle)
        self.show_gridlines_action.setCheckable(True)
        self.show_gridlines_action.setChecked(True)

        self.add_cliff_marker_action = QAction(QIcon(f"{icon_folder}/plus.png"), "Add Cliff Marker", self, triggered=self.choose_cliff_marker)
        self.add_cliff_marker_action.setCheckable(True)
        self.remove_cliff_marker_action = QAction(QIcon(f"{icon_folder}/minus.png"), "Remove Cliff Marker", self, triggered=self.remove_cliff_marker)
        self.remove_cliff_marker_action.setEnabled(False)

        self.palette_fields_action = QAction("Palette Fields", self, triggered=self.toggle_palette_fields)
        self.palette_fields_action.setCheckable(True)
        self.palette_fields_action.setToolTip("Draws the map with several palettes at once, blending into each other")

        self.undo_action = QAction("Undo", self, triggered=self.undo)
        self.redo_action = QAction("Redo", self, triggered=self.redo)
        set_undo_shortcuts(self.undo_action, self.redo_action)

        self.new_action = QAction("New Map...", self,
                                  shortcut="Ctrl+N", triggered=self.new)
        self.open_action = QAction("Open Map...", self,
                                   shortcut="Ctrl+O", triggered=self.open)
        self.save_action = QAction("Save Map", self,
                                   shortcut="Ctrl+S", triggered=self.save)
        self.save_as_action = QAction(
            "Save Map As...", self, shortcut="Ctrl+Shift+S", triggered=self.save_as)
        self.quit_action = QAction(
            "&Quit", self, shortcut="Ctrl+Q", triggered=self.close)

        self.autogenerate_indoor_map_action = QAction("Autogenerate Indoor Map...", self, triggered=self.autogenerate_indoor_map)
        self.autogenerate_outdoor_map_action = QAction("Autogenerate Outdoor Map...", self, triggered=self.autogenerate_outdoor_map)

        self.about_action = QAction("About", self, triggered=self.about)
        self.help_action = QAction("Help", self, triggered=self.display_help)

        # menu actions
        self.zoom_in_action = QAction(
            QIcon(f"{icon_folder}/zoom_in.png"),
            "Zoom in", self, shortcut="Ctrl++", triggered=self.view.zoom_in)
        self.zoom_out_action = QAction(
            QIcon(f"{icon_folder}/zoom_out.png"),
            "Zoom out", self, shortcut="Ctrl+-", triggered=self.view.zoom_out)

    def create_menus(self):
        self.menuBar().clear()
        file_menu = QMenu("File", self)
        file_menu.addAction(self.new_action)
        file_menu.addAction(self.open_action)
        file_menu.addSeparator()
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.save_as_action)
        file_menu.addAction(self.export_as_png_action)
        file_menu.addAction(self.export_to_lt_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

        edit_menu = QMenu("Edit", self)
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.brush_action)
        edit_menu.addAction(self.paint_action)
        edit_menu.addAction(self.erase_action)
        edit_menu.addAction(self.add_cliff_marker_action)
        edit_menu.addAction(self.remove_cliff_marker_action)
        edit_menu.addAction(self.palette_fields_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.clear_all_action)
        edit_menu.addAction(self.show_gridlines_action)
        edit_menu.addAction(self.zoom_in_action)
        edit_menu.addAction(self.zoom_out_action)

        auto_menu = QMenu("Auto", self)
        auto_menu.addAction(self.autogenerate_indoor_map_action)
        auto_menu.addAction(self.autogenerate_outdoor_map_action)

        extra_menu = QMenu("Extra", self)
        extra_menu.addAction(self.about_action)
        extra_menu.addAction(self.help_action)

        self.menuBar().addMenu(file_menu)
        self.menuBar().addMenu(edit_menu)
        self.menuBar().addMenu(auto_menu)
        self.menuBar().addMenu(extra_menu)

    def create_toolbar(self):
        self.toolbar = self.addToolBar("Edit")
        self.toolbar.addAction(self.brush_action)
        self.toolbar.addAction(self.paint_action)
        self.toolbar.addAction(self.erase_action)
        self.toolbar.addAction(self.resize_action)
        self.toolbar.addAction(self.export_as_png_action)
        self.toolbar.addAction(self.show_gridlines_action)
        self.toolbar.setAllowedAreas(Qt.TopToolBarArea)
        self.toolbar.setFloatable(False)
        self.toolbar.setMovable(False)

    def set_title(self):
        if self.current_map_save_location:
            self.setWindowTitle(self.current_map_save_location + " -- " + self.title)
        else:
            self.setWindowTitle(self.title)

    def set_message(self, msg):
        if msg:
            self.statusBar().showMessage(msg)
        else:
            self.statusBar().clearMessage()

    def set_position_bar(self, pos):
        if pos:
            self.position_bar.setText("Position (%d, %d)" % (pos[0], pos[1]))
        else:
            self.position_bar.setText("")

    def void_right_selection(self):
        self.view.right_selection.clear()
        self.view.update_view()

    def check_brush(self):
        self.brush_action.setChecked(True)
        self.set_brush(True)

    def set_brush(self, val):
        self.cliff_marker_widget.reset()
        self.current_tool = PaintTool.Brush
        self.view.update_view()

    def set_fill(self, val):
        self.cliff_marker_widget.reset()
        self.current_tool = PaintTool.Fill
        self.view.update_view()

    def set_erase(self, val):
        self.cliff_marker_widget.reset()
        self.current_tool = PaintTool.Erase
        self.view.update_view()

    def choose_cliff_marker(self, checked):
        if checked:
            self.set_cliff_marker()
            self.add_cliff_marker_action.setChecked(True)

    def set_cliff_marker(self):
        self.brush_action.setChecked(False)
        self.paint_action.setChecked(False)
        self.erase_action.setChecked(False)
        self.current_tool = PaintTool.CliffMarker
        self.view.update_view()

    def pick_palette_origin(self, outdoor: bool, index: int):
        """Has the next click on the map place the origin of a source"""
        self.brush_action.setChecked(False)
        self.paint_action.setChecked(False)
        self.erase_action.setChecked(False)
        self.cliff_marker_widget.reset()
        self.picked_source = (outdoor, index)
        self.current_tool = PaintTool.PaletteOrigin
        self.view.update_view()

    def place_palette_origin(self, pos):
        outdoor, index = self.picked_source
        self.palette_fields_widget.set_origin(outdoor, index, pos)
        self.check_brush()

    def remove_cliff_marker(self):
        if len(self.current.cliff_markers) > 1:
            idx = self.cliff_marker_widget.main_box.edit.currentIndex()
            self.current.cliff_markers.pop(idx)
            self.cliff_marker_widget.main_box.edit.removeItem(idx)
            self.current.reset_all()
            self.commit('Remove Cliff Marker')
        else:
            QMessageBox.warning(self, "Warning", "Cannot remove last cliff marker!")
        self.cliff_marker_widget.toggle_remove_button()

    def set_current(self, current: MapPrefab):
        """Shows a map just made or opened, with a history of its own"""
        self.current = current
        self.current.reset_all()
        self.view.set_current(current)
        self.cliff_marker_widget.set_current(current)
        self.show_fields()
        self.history.clear(current)
        self.update_undo_actions()

    def show_fields(self):
        """Shows the map's fields in the boxes and palette selectors, as after an undo"""
        for box, value in ((self.autotile_fps_box, self.current.autotile_fps),
                           (self.random_seed_box, map_utils.get_random_seed())):
            box.edit.blockSignals(True)
            box.edit.setValue(value)
            box.edit.blockSignals(False)
        self.show_palettes()
        self.show_palette_fields()
        self.cliff_marker_widget.show_markers()
        self.view.update_view()

    # === Undo ===
    def commit(self, label: str = 'Edit', merge: bool = False):
        """Records whatever the map changed since the last commit as one undo step"""
        if self.history.commit(label, merge):
            self.update_undo_actions()

    def undo(self):
        self.view.end_stroke()
        self.undo_feedback.show_step(self.history, self.history.undo(), redo=False)
        self.show_fields()
        self.update_undo_actions()

    def redo(self):
        self.view.end_stroke()
        self.undo_feedback.show_step(self.history, self.history.redo(), redo=True)
        self.show_fields()
        self.update_undo_actions()

    def on_focus_changed(self, old, new):
        """Watches the widget given focus for the undo keys in place of the one
        watched before, if it is in this window. A text field, like the seed box's,
        claims the keys ahead of the Undo action's shortcut, even with no typing of
        its own to undo"""
        if self.key_widget is not None and not sip.isdeleted(self.key_widget):
            self.key_widget.removeEventFilter(self)
        self.key_widget = new if new is not None and self.isAncestorOf(new) else None
        if self.key_widget is not None:
            self.key_widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.key_widget and event.type() == QEvent.KeyPress:
            for keys, redo in ((QKeySequence.Undo, False), (QKeySequence.Redo, True)):
                if event.matches(keys) and not handles_own_undo(obj, redo):
                    if not held_in_text_field(obj, event):
                        step = self.redo if redo else self.undo
                        step()
                    return True
        return super().eventFilter(obj, event)

    def update_undo_actions(self):
        """Names what Undo and Redo would change"""
        last, next_redo = self.history.last_change(), self.history.next_redo()
        self.undo_action.setEnabled(last is not None)
        self.undo_action.setText("Undo %s" % self.history.describe(last) if last else "Undo")
        self.redo_action.setEnabled(next_redo is not None)
        self.redo_action.setText("Redo %s" % self.history.describe(next_redo) if next_redo else "Redo")

    def resize_map(self):
        if ResizeDialog.get_new_size(self.current, self):
            self.commit('Resize')

    def clear_map(self):
        self.current.clear()
        self.current.reset_all()
        self.view.update_view()
        self.commit('Clear All')

    def gridline_toggle(self, val):
        self.view.draw_gridlines = val
        self.view.update_view()

    def autotile_fps_changed(self, val):
        self.current.autotile_fps = val
        # Each value typed or spun to joins one step
        self.commit('Change Autotile Speed', merge=True)

    def random_seed_changed(self, val):
        map_utils.set_random_seed(val)
        self.current.seed = val  # keep prefab attr in sync with the global
        print("--- Seed Changed to %d ---" % val)
        self.current.reset_all()
        self.commit('Change RNG Seed', merge=True)

    def drawn_with_fields(self, outdoor: bool) -> bool:
        """Whether outdoor or indoor terrain is drawn with palette fields, not its one palette"""
        fields = self.current.palette_fields
        return fields.enabled and bool(fields.outdoor if outdoor else fields.indoor)

    def indoor_palette_changed(self, idx: int):
        self.current.current_indoor_palette = PALETTES.indoor_palettes()[idx].nid
        if not self.drawn_with_fields(False):
            self.current.reset_all()
        self.show_palettes()
        self.commit('Change Indoor Palette')

    def outdoor_palette_changed(self, idx: int):
        self.current.current_outdoor_palette = PALETTES.outdoor_palettes()[idx].nid
        if not self.drawn_with_fields(True):
            self.current.reset_all()
        self.show_palettes()
        self.commit('Change Outdoor Palette')

    def show_palettes(self):
        """Selects the map's palettes and shows its terrain's icons in them. A map
        with no palettes yet takes the ones on show. A kind of terrain drawn with
        palette fields draws nothing with its one palette, which then only shows
        the icons in it"""
        if not self.current.current_indoor_palette:
            self.current.current_indoor_palette = self.drawn_palettes[0] or PALETTES.indoor_palettes()[0].nid
        if not self.current.current_outdoor_palette:
            self.current.current_outdoor_palette = self.drawn_palettes[1] or PALETTES.outdoor_palettes()[0].nid
        for selector, palettes, nid, outdoor in (
                (self.indoor_palette_selector, PALETTES.indoor_palettes(), self.current.current_indoor_palette, False),
                (self.outdoor_palette_selector, PALETTES.outdoor_palettes(), self.current.current_outdoor_palette, True)):
            selector.edit.blockSignals(True)
            selector.edit.setCurrentIndex(palettes.index(nid))
            selector.edit.blockSignals(False)
            selector.setToolTip("The map is drawn with palette fields: this palette only shows the terrain icons in it"
                                if self.drawn_with_fields(outdoor) else "")

        drawn = (self.current.current_indoor_palette, self.current.current_outdoor_palette)
        if drawn == self.drawn_palettes:
            return
        self.drawn_palettes = drawn
        indoor, outdoor = PALETTES.get(drawn[0]), PALETTES.get(drawn[1])
        for terrain, renderer in RENDERERS.items():
            renderer.set_palette((outdoor if terrain.outdoor else indoor).get(terrain))
        self.indoor_terrain_painter_menu.reset()
        self.outdoor_terrain_painter_menu.reset()

    def show_palette_fields(self):
        """Shows the map's palette fields, if it has them on"""
        enabled = self.current.palette_fields.enabled
        self.palette_fields_action.setChecked(enabled)
        self.palette_fields_dock.setVisible(enabled)
        self.palette_fields_widget.show_fields()
        # The source picked may be gone
        if self.current_tool == PaintTool.PaletteOrigin:
            self.check_brush()

    def toggle_palette_fields(self, checked: bool):
        self.current.palette_fields.enabled = checked
        self.current.reset_all()
        self.show_palettes()
        self.show_palette_fields()
        self.view.update_view()
        self.commit('Turn On Palette Fields' if checked else 'Turn Off Palette Fields')

    def autogenerate_indoor_map(self):
        AutogenerateIndoorMap.customize(self)

    def autogenerate_outdoor_map(self):
        AutogenerateOutdoorMap.customize(self)

    def export_as_png(self):
        if self.current:
            image = simple_draw_tilemap(self.current)
            starting_path = self.settings.get_last_open_path()
            fn, ok = QFileDialog.getSaveFileName(
                self, "Export Current Image", starting_path,
                "PNG Files (*.png)")
            if fn and ok:
                image.save(fn)
                parent_dir = os.path.split(fn)[0]
                self.settings.set_last_open_path(parent_dir)

    def export_to_lt(self):
        if not self.current:
            QMessageBox.critical(self, self.title, "There is no current map!")
            return

        QMessageBox.warning(self, self.title, "Do not select a .ltproj that's currently open in the LT Editor!\n"
                            "Doing so may cause corruption of your files!")

        image: QImage = simple_draw_tilemap(self.current)

        starting_path = self.settings.get_last_open_path()
        fn = QFileDialog.getExistingDirectory(
            self, "Select LT Project", starting_path)

        if fn:
            parent_dir = os.path.split(fn)[0]
            self.settings.set_last_open_path(parent_dir)

            nid = NidDialog.get(self)
            if not nid:
                return

            loc = os.path.join(fn, 'resources', 'tilesets')
            assert os.path.isdir(loc)
            manifest = os.path.join(loc, 'tilesets.json')
            full_path = os.path.join(loc, nid + '.png')
            autotile_path = os.path.join(loc, nid + '_autotiles.png')
            image.save(full_path)

            s_dict = {}
            s_dict['nid'] = nid
            s_dict['terrain_grid'] = {}

            # Build autotiles
            s_dict['autotiles'] = {}
            all_autotile_positions = []
            for pos in sorted(self.current.terrain_grid):
                # Determine what terrain is in this position
                terrain = self.current.get_terrain(pos)
                if not terrain:
                    continue
                painter = RENDERERS.get(terrain).painter
                if painter.has_autotiles():
                    all_autotile_positions.append((pos, terrain))

            if all_autotile_positions:
                autotile_width = TILEWIDTH * len(all_autotile_positions)
                autotile_height = TILEHEIGHT * AUTOTILE_FRAMES
                autotile_image = QImage(autotile_width, autotile_height, QImage.Format_ARGB32)
                autotile_image.fill(QColor(255, 255, 255, 0))

                qpainter = QPainter(autotile_image)
                for idx, (pos, terrain) in enumerate(all_autotile_positions):
                    str_coord = "%d,%d" % (pos[0], pos[1])
                    s_dict['autotiles'][str_coord] = idx
                    renderer = RENDERERS.get(terrain)
                    palette = palette_at(self.current, terrain, pos)
                    coord = renderer.get_sprite_coord(self.current, pos, palette)
                    for pidx in range(AUTOTILE_FRAMES):
                        sprite = renderer.draw_sprite(coord, pidx, palette)
                        qpainter.drawPixmap(idx * TILEWIDTH, pidx * TILEHEIGHT, sprite)
                qpainter.end()
                autotile_image.save(autotile_path)
            # Completed creating autotiles

            # Modify the tileset manifest of the project
            import json
            with open(manifest) as fp:
                data = json.load(fp)
            data.append(s_dict)
            with open(manifest, 'w') as fp:
                json.dump(data, fp, indent=4)

            QMessageBox.information(self, self.title, "Map successfully exported as tileset with nid *%s* to %s" % (nid, fn))

    def update_view(self):
        self.view.update_view()

    def maybe_save(self):
        if not self.history.is_modified():
            return True
        ret = QMessageBox.warning(self, self.title, "The current map may have been modified.\n"
                                  "Do you want to save your changes?",
                                  QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if ret == QMessageBox.Save:
            return self.save()
        elif ret == QMessageBox.Cancel:
            return False
        return True

    def save(self, new=False):
        if new or not self.current_map_save_location:
            starting_path = self.current_map_save_location or QDir.currentPath()
            fn, ok = QFileDialog.getSaveFileName(self, "Save Map", starting_path,
                                                 "All Files (*)")
            if ok:
                if fn.endswith('.json'):
                    self.current_map_save_location = fn
                else:
                    self.current_map_save_location = fn + '.json'
            else:
                return False
            new = True

        if new:
            if os.path.exists(self.current_map_save_location):
                ret = QMessageBox.warning(self, "Save Map", "The file already exists.\nDo you want to overwrite it?",
                                          QMessageBox.Save | QMessageBox.Cancel)
                if ret == QMessageBox.Save:
                    pass
                else:
                    return False

        # Actually save project
        self.saved_data = self.current.save()
        with open(self.current_map_save_location, 'w') as save_file:
            json.dump(self.saved_data, save_file, indent=4)
        self.history.mark_saved()
        self.set_title()
        return True

    def save_as(self):
        return self.save(True)

    def new(self):
        if not self.maybe_save():
            return False
        new_tilemap_prefab = MapPrefab('sample')
        # Keeps the seed on show, which the painters read from the map and from map_utils
        new_tilemap_prefab.seed = map_utils.get_random_seed()
        result = ResizeDialog.get_new_size(new_tilemap_prefab)
        if not result:
            return False
        self.current_map_save_location = None
        self.set_current(new_tilemap_prefab)
        self.set_title()
        return result

    def open(self):
        if self.maybe_save():
            if self.current_map_save_location:
                starting_path = os.path.join(self.current_map_save_location, '..')
            else:
                starting_path = QDir.currentPath()
            fn, ok = QFileDialog.getOpenFileName(self, "Open Saved Map", starting_path, "JSON Files (*.json)")
            if fn:
                self.current_map_save_location = fn
                self.load()
                self.set_title()
                return True
            else:
                return False
        return False

    def load(self):
        if os.path.exists(self.current_map_save_location):
            with open(self.current_map_save_location) as load_file:
                s_dict = json.load(load_file)
            self.set_current(MapPrefab.restore(s_dict))

    def closeEvent(self, event):
        if self.maybe_save():
            event.accept()
        else:
            event.ignore()
        self.save_geometry()

    def about(self):
        QMessageBox.about(self, "About Lex Talionis Map Maker",
                          "<p>This is the <b>Lex Talionis</b> Map Maker.</p>"
                          "<p>Check out <a href='https://lt-maker.readthedocs.io/'>https://lt-maker.readthedocs.io/</a> "
                          "for more information and helpful tutorials.</p>"
                          "<p>This program has been freely distributed under the MIT License.</p>"
                          "<p>Copyright 2014-2025 rainlash.</p>")

    def display_help(self):
        QMessageBox.about(self, "Help for Lex Talionis Map Maker",
                          "<p>Check out <a href='https://lt-maker.readthedocs.io/'>https://lt-maker.readthedocs.io/</a> "
                          "for information and helpful tutorials.</p>"
                          "<p>Or visit the LT community discord at <a href='https://discord.gg/dC6VWGh4sw'>https://discord.gg/dC6VWGh4sw</a> "
                          "for answers to your questions and a helpful community.</p>")

    def _type(self):
        return 'map_maker'

    def save_geometry(self):
        self.settings.component_controller.set_geometry(self._type(), self.saveGeometry())
        # self.settings.component_controller.set_state(self._type(), (self.main_splitter.saveState(), self.right_frame.saveState()))
