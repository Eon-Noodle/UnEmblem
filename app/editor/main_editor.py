import logging
import os
import sys
import functools
from typing import Optional

from PyQt5.QtWidgets import QMainWindow, QAction, QMenu, QMessageBox, QApplication, \
    QDesktopWidget, \
    QDockWidget, QToolButton, QWidget, QWidgetAction, QStackedWidget
from PyQt5.QtGui import QIcon, QKeySequence
from PyQt5 import sip
from PyQt5.QtCore import QEvent, QTimer

from app import autoupdate, dark_theme
from app.utilities import file_utils

from app.editor.file_manager.project_builder.project_builder import LTProjectBuilder
from app.editor.file_manager.project_builder.web_exporter import WebExporter
from app.editor.font_editor.font_tab import FontDatabase
from app.editor.settings.preferences_tabbed import TabbedPreferencesDialog
from app.editor.settings import MainSettingsController

from app.constants import VERSION
from app.data.database.database import DB

from app.editor import log_viewer, error_viewer, reference_dialogs
from app.editor.custom_widgets import ObjBox
from app.editor.data_editor import EditHistoryDialog, UndoFeedback, report_undo_failure
from app.editor.undo_keys import handles_own_undo, held_in_text_field, set_undo_shortcuts
from app.editor.edit_history import HISTORY, UndoFailed
from app.editor.editor_windows import EditorWindows

# components
from app.editor.lib.components.menubar import MenuBar
from app.editor.lib.components.toolbar import Toolbar
from app.editor.save_viewer import SaveViewer
from app.editor.file_manager.unused_resources_dialog import UnusedResourcesDialog

# Application State
from app.editor.lib.state_editor.editor_state_manager import EditorStateManager
from app.editor.lib.state_editor.state_enums import MainEditorScreenStates

# Saving/Loading Project
from app.editor.file_manager.project_file_backend import ProjectFileBackend, DEFAULT_PROJECT

# Editors
from app.editor.global_editor.global_editor import GlobalEditor
from app.editor.level_editor.level_editor import LevelEditor
from app.editor.overworld_editor.overworld_editor import OverworldEditor

# Game interface
import app.editor.game_actions.game_actions as GAME_ACTIONS

# Databases
from app.editor.unit_editor.new_unit_tab import NewUnitDatabase
from app.editor.team_editor.team_tab import TeamDatabase
from app.editor.faction_editor.faction_tab import FactionDatabase
from app.editor.party_editor.party_tab import PartyDatabase
from app.editor.class_editor.new_class_tab import NewClassDatabase
from app.editor.weapon_editor.weapon_tab import WeaponDatabase
from app.editor.item_editor.new_item_tab import NewItemDatabase
from app.editor.skill_editor.new_skill_tab import NewSkillDatabase
from app.editor.terrain_editor.terrain_tab import TerrainDatabase
from app.editor.stat_editor.stat_tab import StatTypeDatabase
from app.editor.ai_editor.ai_tab import AIDatabase
from app.editor.difficulty_mode_editor.difficulty_mode_tab import DifficultyModeDatabase
from app.editor.constant_tab import ConstantDatabase
from app.editor.tag_widget import TagDialog
from app.editor.game_var_slot_widget import GameVarSlotDialog
from app.editor.mcost_dialog import McostDialog
from app.editor.translation_widget import TranslationDialog
from app.editor.equation_widget import EquationDialog
from app.editor.event_editor.event_tab import EventDatabase
from app.editor.lore_editor.new_lore_tab import NewLoreDatabase
from app.editor.raw_editor.raw_data_tab import RawDataDatabase
from app.editor.credit_editor.new_credit_tab import NewCreditDatabase

# Resources
from app.editor.icon_editor import icon_tab
from app.editor.combat_animation_editor import new_combat_animation_tab
from app.editor.tile_editor import tile_tab
from app.editor.sound_editor import sound_tab
from app.editor.support_editor import support_pair_tab
from app.editor.portrait_editor.new_portrait_tab import NewPortraitDatabase
from app.editor.panorama_editor.panorama_tab import PanoramaDatabase
from app.editor.map_sprite_editor.new_map_sprite_tab import NewMapSpriteDatabase
from app.editor.map_animation_editor.map_animation_tab import MapAnimationDatabase
from app.utilities.system_info import is_editor_engine_built_version

__version__ = VERSION


class MainEditor(QMainWindow):
    def initialize_state_subscriptions(self):
        self.app_state_manager.subscribe_to_key(
            MainEditor.__name__, 'main_editor_mode', self.render_editor)

    def __init__(self, project_path: str):
        super().__init__()
        self.window_title = _('LT Maker')
        self.setWindowTitle(self.window_title)
        self.settings = MainSettingsController()
        # Will be overwritten by auto-open
        desktop = QDesktopWidget()
        main_screen_size = desktop.availableGeometry(desktop.primaryScreen())

        # Use setFixedSize to make it permanent and unchangeable
        default_size = int(main_screen_size.width()*0.7), int(main_screen_size.height()*0.7)
        self.resize(*default_size)

        geometry = self.settings.component_controller.get_geometry(
            self.__class__.__name__)
        if geometry:
            self.restoreGeometry(geometry)

        # initialize application state
        self.app_state_manager = EditorStateManager()
        self.app_state_manager.state.selected_level = '0'
        self.initialize_state_subscriptions()

        self.editor_windows = EditorWindows()

        # initialize save/load handler
        self.project_save_load_handler = ProjectFileBackend(
            self,
            self.app_state_manager)

        self.project_builder = LTProjectBuilder(self.project_save_load_handler)
        self.web_exporter = WebExporter(self.project_save_load_handler)

        # initialize possible editors and put them in the stack
        self.global_editor = GlobalEditor(self.app_state_manager)
        self.level_editor = LevelEditor(self.app_state_manager)
        self.overworld_editor = OverworldEditor(self.app_state_manager)
        # order is *very* important here. The first widget added will be index 0, the second is index 1, etc.
        self.editor_stack = QStackedWidget(self)
        self.editor_stack.addWidget(self.global_editor)
        self.editor_stack.addWidget(self.level_editor)
        self.editor_stack.addWidget(self.overworld_editor)
        # initialize to global editor
        self.setCentralWidget(self.editor_stack)
        self.mode = MainEditorScreenStates.GLOBAL_EDITOR
        self.current_editor = self.global_editor

        # initialize other UI elements
        self.create_actions()
        self.recreate_menus()
        # init toolbar
        self.toolbar = Toolbar(self.addToolBar(_("Edit")))
        self.create_toolbar()
        self.set_icons()
        self.create_statusbar()

        self.render_editor(MainEditorScreenStates.GLOBAL_EDITOR)

        # Actually load data
        self.auto_open(project_path)

        if len(DB.levels) == 0:
            self.level_menu.create_initial_level()

        # initialize to first level
        first_level_nid = DB.levels[0].nid
        self.app_state_manager.change_and_broadcast(
            'selected_level', first_level_nid)

        self.history_changed = False
        HISTORY.listen(self.on_history_changed)
        self.update_undo_actions()
        # A rename leaves event scripts as they are, so the user hears which lines still name the old nid
        HISTORY.listen_to_renames(reference_dialogs.warn_of_event_mentions)
        # The level and overworld editors change their records in place, which the
        # next commit records. A field's edit is done once focus moves on
        self.key_widget = None
        QApplication.instance().focusChanged.connect(self.on_focus_changed)

    def holds(self, widget: QWidget) -> bool:
        """Whether widget is part of this window, a dock floating beside it included"""
        while widget is not None:
            if widget is self:
                return True
            if widget.isWindow() and not isinstance(widget, QDockWidget):
                return False
            widget = widget.parentWidget()
        return False

    def watch_keys(self, widget):
        """Watches widget for the undo keys in place of the one watched before, if it
        is in this window. A text field claims the keys ahead of the Undo action's
        shortcut, even with no typing of its own to undo"""
        if self.key_widget is not None and not sip.isdeleted(self.key_widget):
            self.key_widget.removeEventFilter(self)
        self.key_widget = widget if self.holds(widget) else None
        if self.key_widget is not None:
            self.key_widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.key_widget and event.type() == QEvent.KeyPress:
            if event.matches(QKeySequence.Undo) and not handles_own_undo(obj, redo=False):
                if not held_in_text_field(obj, event):
                    self.undo()
                return True
            if event.matches(QKeySequence.Redo) and not handles_own_undo(obj, redo=True):
                if not held_in_text_field(obj, event):
                    self.redo()
                return True
        return super().eventFilter(obj, event)

    def on_focus_changed(self, old, new):
        self.watch_keys(new)
        if self.holds(old):
            # A field here has finished its edit, an undo step of its own, kept
            # apart from whatever is edited next in another window
            HISTORY.commit(origin=self)
        elif self.holds(new):
            # From another window, whose edits this window has yet to show; an
            # editor window's tab already shows its own
            HISTORY.commit(origin=EditHistoryDialog.tab_holding(old))

    def on_history_changed(self, origin, change_set):
        # A disabled action's shortcut does nothing, so the actions keep up with
        # every change, not only when the menu opens
        self.update_undo_actions()
        # Editor windows change the database beside this window. What this window
        # changed it shows already, and showing it again would drop its selections
        if origin is not None and self.holds(origin):
            return
        if not self.history_changed:
            self.history_changed = True
            QTimer.singleShot(0, self.show_changes)

    def show_changes(self):
        """Shows the database again after an editor window changed it.

        Undo restores a level's fields in place, which rebuilds the units and regions
        inside it. The level editor (and its sub-widgets) cache those and only refresh
        on a 'selected_level' broadcast, so without it unit edits would go to objects
        the level no longer holds -- the "unit positions revert" bug.
        """
        self.history_changed = False
        # Including the boxes of dialogs opened from this window, like Load Unit;
        # editor dialogs refresh their own, leaving out the tab that made the change.
        # PropertyBox keeps its parent as box.window, hiding QWidget.window
        for box in self.findChildren(ObjBox):
            if not isinstance(QWidget.window(box), EditHistoryDialog):
                box.refresh()
        self.broadcast_selection()
        self.app_state_manager.change_and_broadcast('ui_refresh_signal', None)

    def broadcast_selection(self):
        """Broadcasts the selected level, overworld and node again. The global editor's
        map shows whichever of the level and overworld is broadcast last, so the one it
        shows goes last."""
        state = self.app_state_manager.state
        broadcasts = []
        # Sometimes the stored current level nid does not exist as a valid
        # level; check before broadcasting.
        if state.selected_level in DB.levels:
            broadcasts.append(('selected_level', state.selected_level))
        # Overworlds hold their nodes the way levels hold their units
        overworld = DB.overworlds.get(state.selected_overworld)
        if overworld:
            node_nid = state.selected_node if state.selected_node in overworld.overworld_nodes else None
            overworld_broadcasts = [('selected_overworld', overworld.nid), ('selected_node', node_nid)]
            if self.global_editor.shows_overworld():
                broadcasts = broadcasts + overworld_broadcasts
            else:
                broadcasts = overworld_broadcasts + broadcasts
        for key, value in broadcasts:
            self.app_state_manager.change_and_broadcast(key, value)

    def on_clean_changed(self, clean):
        # Change Title
        if clean:
            pass
        else:
            if not self.window_title.startswith('*'):
                self.window_title = '*' + self.window_title

    def set_window_title(self, title):
        if self.window_title.startswith('*'):
            self.window_title = '*' + title + ' -- LT Maker %s' % (__version__)
        else:
            self.window_title = title + ' -- LT Maker %s' % (__version__)
        self.setWindowTitle(self.window_title)

    def set_icons(self, force_theme: Optional[dark_theme.ThemeType] = None):
        theme = dark_theme.get_theme(force_theme)
        icon_folder = theme.icon_dir()

        self.new_act.setIcon(QIcon(f'{icon_folder}/file-plus.png'))
        self.open_act.setIcon(QIcon(f'{icon_folder}/folder.png'))
        self.save_act.setIcon(QIcon(f'{icon_folder}/save.png'))
        self.save_as_act.setIcon(QIcon(f'{icon_folder}/save.png'))
        self.quit_act.setIcon(QIcon(f'{icon_folder}/x.png'))
        self.test_current_act.setIcon(QIcon(f'{icon_folder}/play.png'))
        self.test_load_act.setIcon(QIcon(f'{icon_folder}/play.png'))
        self.test_full_act.setIcon(QIcon(f'{icon_folder}/play_all.png'))
        self.modify_events_act.setIcon(QIcon(f'{icon_folder}/event.png'))

        self.database_button.setIcon(QIcon(f'{icon_folder}/database.png'))
        self.resource_button.setIcon(QIcon(f'{icon_folder}/resource.png'))
        self.test_button.setIcon(QIcon(f'{icon_folder}/play.png'))

        self.global_editor.set_icons(force_theme)

    # === Create Menu ===
    def create_actions(self):
        windows = self.editor_windows.opener
        self.new_act = QAction(_("New Project..."), self,
                               shortcut="Ctrl+N", triggered=self.new)
        self.open_act = QAction(_("Open Project..."), self,
                                shortcut="Ctrl+O", triggered=self.open)
        self.save_act = QAction(_("Save Project"), self,
                                shortcut="Ctrl+S", triggered=self.save)
        self.save_as_act = QAction(
            _("Save Project As..."), self, shortcut="Ctrl+Shift+S", triggered=self.save_as)
        self.quit_act = QAction(
            _("&Quit"), self, shortcut="Ctrl+Q", triggered=self.close)

        # One history for every window: these undo the last change anywhere
        self.undo_act = QAction(_("Undo"), self, triggered=self.undo)
        self.redo_act = QAction(_("Redo"), self, triggered=self.redo)
        set_undo_shortcuts(self.undo_act, self.redo_act)

        self.dump_csv = QAction(
            "Dump CSV data", self, triggered=lambda: self.project_save_load_handler.dump_csv(DB))
        self.dump_script = QAction(
            "Dump script", self, triggered=lambda: self.project_save_load_handler.dump_script(DB))

        self.build_project = QAction(
            "Build project", self, triggered=lambda: self.project_builder.build(self.project_save_load_handler.current_proj))
        if not file_utils.Pltfm.windows():
            self.build_project.setEnabled(False)
            self.build_project.setToolTip("Building is only supported on Windows.")
        self.export_web_act = QAction(
            "Export for Web...", self, triggered=self.web_exporter.export)

        self.preferences_act = QAction(
            _("&Preferences..."), self, triggered=self.edit_preferences)
        self.about_act = QAction(_("&About"), self, triggered=self.about)
        self.remove_unused_resources_act = QAction(
            _("Remove Unused Resources"), self, triggered=self.remove_unused_resources)
        self.check_for_updates_act = QAction(
            _("Check for updates..."), self, triggered=self.check_for_updates)
        self.view_logs_act = QAction(
            _("View logs..."), self, triggered=self.show_logs)
        self.view_errors_act = QAction(
            _("View Error Report..."), self, triggered=self.show_errors)

        # Test actions
        self.test_current_act = QAction(
            "Test Current Chapter...", self, shortcut="F5", triggered=self.test_play_current)
        self.test_current_act.setEnabled(False)
        self.test_load_act = QAction(
            "Test Current Chapter from Preload...", self, shortcut="Ctrl+F5", triggered=self.test_play_load)
        self.test_load_act.setEnabled(False)
        self.test_full_act = QAction(
            "Test Full Game...", self, triggered=self.test_play)
        # self.balance_act = QAction(
        #     "Preload Units...", self, triggered=self.edit_preload_units)

        # Database actions
        # Editors on the edit history open as windows beside this one; the rest
        # are dialogs that block it until they close
        database_actions = {_("Units"): windows(NewUnitDatabase.edit),
                            _("Teams"): windows(TeamDatabase.edit),
                            _("Factions"): windows(FactionDatabase.edit),
                            _("Parties"): windows(PartyDatabase.edit),
                            _("Classes"): windows(NewClassDatabase.edit),
                            _("Tags"): self.edit_tags,
                            _("Game Vars"): self.edit_game_vars,
                            _("Weapon Types"): windows(WeaponDatabase.edit),
                            _("Items"): windows(NewItemDatabase.edit),
                            _("Skills"): windows(NewSkillDatabase.edit),
                            "AI": windows(AIDatabase.edit),
                            _("Terrain"): windows(TerrainDatabase.edit),
                            _("Movement Costs"): self.edit_mcost,
                            _("Stats"): windows(StatTypeDatabase.edit),
                            _("Equations"): self.edit_equations,
                            _("Constants"): windows(ConstantDatabase.edit),
                            _("Difficulty Modes"): windows(DifficultyModeDatabase.edit),
                            _("Supports"): windows(support_pair_tab.get_full_editor),
                            _("Lore"): windows(NewLoreDatabase.edit),
                            _("Raw Data"): windows(RawDataDatabase.edit),
                            _("Translations"): self.edit_translations,
                            _("Credit"): windows(NewCreditDatabase.edit)
                            }
        self.database_actions = {}
        for name, func in database_actions.items():
            self.database_actions[name] = QAction(
                "%s..." % name, self, triggered=functools.partial(func, self))

        resource_actions = {"Icons": windows(icon_tab.get_full_editor),
                            "Portraits": windows(NewPortraitDatabase.edit),
                            "Map Animations": windows(MapAnimationDatabase.edit),
                            "Backgrounds": windows(PanoramaDatabase.edit),
                            "Map Sprites": windows(NewMapSpriteDatabase.edit),
                            "Combat Animations": windows(new_combat_animation_tab.get_full_editor),
                            "Tilemaps": windows(tile_tab.get_full_editor),
                            "Sounds": windows(sound_tab.get_full_editor),
                            "Fonts": windows(FontDatabase.edit)
                            }
        self.resource_actions = {}
        for name, func in resource_actions.items():
            self.resource_actions[name] = QAction(
                "%s..." % name, self, triggered=functools.partial(func, self))

        self.modify_events_act = QAction(
            "Edit Events", self, triggered=functools.partial(windows(EventDatabase.edit), self))

    def finish_editing(self):
        """Ends the edit in the focused field of this window or an editor window beside
        it, which some fields apply only when they lose focus"""
        focused = QApplication.focusWidget()
        if focused is None:
            return
        window = QWidget.window(focused)
        if window is self or any(window is editor for editor in self.editor_windows.windows.values()):
            focused.clearFocus()

    def undo(self):
        self.finish_editing()
        try:
            self.undo_feedback.show_step(HISTORY.undo(), redo=False)
        except UndoFailed as failure:
            report_undo_failure(self, failure)

    def redo(self):
        self.finish_editing()
        try:
            self.undo_feedback.show_step(HISTORY.redo(), redo=True)
        except UndoFailed as failure:
            report_undo_failure(self, failure)

    def update_undo_actions(self):
        """Names what Undo and Redo would change, as far as the history has committed,
        and greys out whichever has nothing to do"""
        def described(change_set) -> str:
            # A menu takes & for a shortcut key
            return HISTORY.describe(change_set).replace('&', '&&')

        last, next_redo = HISTORY.last_change(), HISTORY.next_redo()
        self.undo_act.setEnabled(last is not None)
        self.undo_act.setText(_("Undo %s") % described(last) if last else _("Undo"))
        self.redo_act.setEnabled(next_redo is not None)
        self.redo_act.setText(_("Redo %s") % described(next_redo) if next_redo else _("Redo"))

    def edit_level(self):
        self.app_state_manager.change_and_broadcast(
            'main_editor_mode', MainEditorScreenStates.LEVEL_EDITOR)

    def edit_global(self):
        self.app_state_manager.change_and_broadcast(
            'main_editor_mode', MainEditorScreenStates.GLOBAL_EDITOR)

    def edit_overworld(self):
        self.app_state_manager.change_and_broadcast(
            'main_editor_mode', MainEditorScreenStates.OVERWORLD_EDITOR)

    def recreate_menus(self):
        self.menuBar().clear()
        file_menu = QMenu(_("File"), self)
        file_menu.addAction(self.new_act)
        file_menu.addAction(self.open_act)
        file_menu.addSeparator()
        file_menu.addAction(self.save_act)
        file_menu.addAction(self.save_as_act)
        file_menu.addAction(self.dump_csv)
        file_menu.addAction(self.dump_script)
        if not is_editor_engine_built_version():
            file_menu.addAction(self.build_project)
        file_menu.addAction(self.export_web_act)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_act)

        edit_menu = QMenu(_("Edit"), self)
        edit_menu.aboutToShow.connect(self.update_undo_actions)
        for action in self.database_actions.values():
            edit_menu.addAction(action)
        edit_menu.addSeparator()
        for action in self.resource_actions.values():
            edit_menu.addAction(action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.undo_act)
        edit_menu.addAction(self.redo_act)

        test_menu = QMenu(_("Test"), self)
        test_menu.addAction(self.test_current_act)
        test_menu.addAction(self.test_load_act)
        test_menu.addAction(self.test_full_act)

        help_menu = QMenu(_("Extra"), self)
        help_menu.addAction(self.about_act)
        help_menu.addAction(self.preferences_act)
        help_menu.addAction(self.remove_unused_resources_act)
        help_menu.addAction(self.check_for_updates_act)
        help_menu.addAction(self.view_logs_act)
        help_menu.addAction(self.view_errors_act)
        self.menubar = MenuBar(self.menuBar())
        self.menubar.addMenu(file_menu)
        self.menubar.addMenu(edit_menu)
        self.menubar.addMenu(test_menu)
        self.menubar.addMenu(help_menu)

        # allow current editor to further customize
        try:
            self.current_editor.create_menus(self.menubar)
        except AttributeError:
            pass

    def create_toolbar(self):
        self.database_button = QToolButton(self)
        self.database_button.setPopupMode(QToolButton.InstantPopup)
        database_menu = QMenu(_("Database"), self)
        for action in self.database_actions.values():
            database_menu.addAction(action)
        self.database_button.setMenu(database_menu)
        self.database_button_action = QWidgetAction(self)
        self.database_button_action.setDefaultWidget(self.database_button)

        self.resource_button = QToolButton(self)
        self.resource_button.setPopupMode(QToolButton.InstantPopup)
        resource_menu = QMenu(_("Resource"), self)
        for action in self.resource_actions.values():
            resource_menu.addAction(action)
        self.resource_button.setMenu(resource_menu)
        self.resource_button_action = QWidgetAction(self)
        self.resource_button_action.setDefaultWidget(self.resource_button)

        self.test_button = QToolButton(self)
        self.test_button.setPopupMode(QToolButton.InstantPopup)
        test_menu = QMenu(_("Test"), self)
        test_menu.addAction(self.test_current_act)
        test_menu.addAction(self.test_load_act)
        test_menu.addAction(self.test_full_act)
        self.test_button.setMenu(test_menu)
        self.test_button_action = QWidgetAction(self)
        self.test_button_action.setDefaultWidget(self.test_button)

        # self.toolbar.addToolButton(self.test_button)

    def recreate_toolbar(self):
        self.toolbar.clear()
        self.toolbar.addAction(self.database_button_action)
        self.toolbar.addAction(self.resource_button_action)
        self.toolbar.addAction(self.modify_events_act)
        self.toolbar.addAction(self.test_button_action)
        # let current editor to further customize toolbar
        try:
            self.current_editor.create_toolbar(self.toolbar)
        except AttributeError:
            pass

    def create_statusbar(self):
        self.status_bar = self.statusBar()
        # Permanent, so no status message hides it
        self.undo_feedback = UndoFeedback(self)
        self.status_bar.addPermanentWidget(self.undo_feedback)

    def set_message(self, msg):
        if msg:
            self.status_bar.showMessage(msg)
        else:
            self.status_bar.clearMessage()

    def closeEvent(self, event):
        self.finish_editing()
        self.settings.component_controller.set_geometry(
            self.__class__.__name__, self.saveGeometry())
        if self.project_save_load_handler.maybe_save():
            logging.info("Setting current project %s" %
                         self.settings.get_current_project())
            self.settings.set_current_project(
                self.settings.get_current_project())
            event.accept()
            self.editor_windows.close_all()
            for window in QApplication.topLevelWidgets():
                window.close()
        else:
            event.ignore()

    def test_play_current(self):
        # The game plays the database as it is in memory
        self.finish_editing()
        # Make a save before playing if not on default
        if os.path.basename(self.settings.get_current_project()) != DEFAULT_PROJECT:
            self.save()
        GAME_ACTIONS.test_play_current(
            self.app_state_manager.state.selected_level)

    def test_play(self):
        self.finish_editing()
        # Make a save before playing if not on default
        if os.path.basename(self.settings.get_current_project()) != DEFAULT_PROJECT:
            self.save()
        GAME_ACTIONS.test_play()

    def test_play_load(self):
        self.finish_editing()
        saved_games = GAME_ACTIONS.get_preloaded_games()
        if saved_games:
            save_loc = SaveViewer.get(saved_games, self)
            if not save_loc:
                return
        else:
            save_loc = None
        # Make a save before playing if not on default
        if os.path.basename(self.settings.get_current_project()) != DEFAULT_PROJECT:
            self.save()
        GAME_ACTIONS.test_play_load(
            self.app_state_manager.state.selected_level, save_loc)

    def new(self):
        self.finish_editing()
        if self.project_save_load_handler.new():
            # if we made a new game:
            self.set_window_title('Untitled')
            title = os.path.split(self.settings.get_current_project())[-1]
            self.set_window_title(title)

            # Return to global
            if not self.mode.GLOBAL_EDITOR:
                self.app_state_manager.change_and_broadcast(
                    'main_editor_mode', MainEditorScreenStates.GLOBAL_EDITOR)
            if DB.overworlds:  # Before the level, which the global editor's map then shows
                self.app_state_manager.change_and_broadcast('selected_overworld', DB.overworlds[0].nid)
            self.app_state_manager.change_and_broadcast(
                'selected_level', DB.levels[0].nid)  # Needed in order to update map view
            self.app_state_manager.change_and_broadcast(
                'ui_refresh_signal', None)

    def _open(self):
        title = os.path.split(self.settings.get_current_project())[-1]
        self.set_window_title(title)
        logging.info("Loaded project from %s" %
                     self.settings.get_current_project())
        self.status_bar.showMessage(
            "Loaded project from %s" % self.settings.get_current_project())
        # Return to global
        if not self.mode.GLOBAL_EDITOR:
            self.app_state_manager.change_and_broadcast(
                'main_editor_mode', MainEditorScreenStates.GLOBAL_EDITOR)
        # So the overworld editor shows this project's overworld. Before the level,
        # which the global editor's map then shows
        if DB.overworlds:
            self.app_state_manager.change_and_broadcast('selected_overworld', DB.overworlds[0].nid)
        self.app_state_manager.change_and_broadcast(
            'selected_level', DB.levels[0].nid)  # Needed in order to update map view
        self.app_state_manager.change_and_broadcast(
            'ui_refresh_signal', None)

    def open(self):
        self.finish_editing()
        if self.project_save_load_handler.open():
            self._open()

    def auto_open(self, project_path: Optional[str]):
        if not self.project_save_load_handler.auto_open(project_path):
            self.project_save_load_handler.auto_open(DEFAULT_PROJECT)
        self._open()

    def _save(self):
        current_proj = self.settings.get_current_project()
        title = os.path.split(current_proj)[-1]
        self.set_window_title(title)
        # Remove asterisk on window title
        if self.window_title.startswith('*'):
            self.window_title = self.window_title[1:]
        self.status_bar.showMessage('Saved project to %s' % current_proj)

    def save(self):
        self.finish_editing()
        if self.project_save_load_handler.save():
            self._save()

    def save_as(self):
        self.finish_editing()
        if self.project_save_load_handler.save(True):
            self._save()

    def remove_unused_resources(self):
        self.finish_editing()
        # Need to save first before cleaning
        if self.project_save_load_handler.save():
            unused_resources = self.project_save_load_handler.get_unused_files()
            # Don't bother if we have no unused resources
            if not any(fns for fns in unused_resources.values()):
                QMessageBox.information(
                    self, "Unused Resources", "No unused resources found!")
                return
            # Let the user confirm they want to remove these resources
            ok = UnusedResourcesDialog.get(unused_resources, self)
            if not ok:
                return
            self.project_save_load_handler.clean(unused_resources)
            current_proj = self.settings.get_current_project()
            self.status_bar.showMessage(
                'All unused resources removed from %s' % current_proj)
        else:
            QMessageBox.warning(
                self, "Save Error", "Must save project before removing unused resources!")

    def edit_tags(self, parent=None):
        dialog = TagDialog.create()
        dialog.exec_()

    def edit_game_vars(self, parent=None):
        dialog = GameVarSlotDialog.create()
        dialog.exec_()

    def edit_mcost(self, parent=None):
        dialog = McostDialog(self)
        dialog.exec_()

    def edit_equations(self, parent=None):
        dialog = EquationDialog.create()
        dialog.exec_()

    def edit_translations(self, parent=None):
        dialog = TranslationDialog.create()
        dialog.exec_()

    def edit_preferences(self):
        dialog = TabbedPreferencesDialog(self)
        dialog.exec_()

    def render_editor(self, main_editor_mode):
        self.mode = main_editor_mode
        if self.mode == MainEditorScreenStates.GLOBAL_EDITOR:
            self.current_editor = self.global_editor
            self.editor_stack.setCurrentIndex(0)
            self.test_current_act.setEnabled(True)
            self.test_load_act.setEnabled(True)
            self.recreate_menus()
            self.recreate_toolbar()
        elif self.mode == MainEditorScreenStates.LEVEL_EDITOR:
            self.current_editor = self.level_editor
            self.editor_stack.setCurrentIndex(1)
            self.test_current_act.setEnabled(True)
            self.test_load_act.setEnabled(True)
            self.recreate_menus()
            self.recreate_toolbar()
        elif(self.mode == MainEditorScreenStates.OVERWORLD_EDITOR):
            self.current_editor = self.overworld_editor
            self.editor_stack.setCurrentIndex(2)
            self.test_current_act.setEnabled(False)
            self.test_load_act.setEnabled(False)
            self.recreate_menus()
            self.recreate_toolbar()

    def about(self):
        QMessageBox.about(self, "About Lex Talionis Game Maker",
                          "<p>This is the <b>Lex Talionis</b> Game Maker.</p>"
                          "<p>Check out <a href='https://lt-maker.readthedocs.io/'>https://lt-maker.readthedocs.io/</a> "
                          "for more information and helpful tutorials.</p>"
                          "<p>This program has been freely distributed under the MIT License.</p>"
                          "<p>Copyright 2014-2026 rainlash.</p>")

    def check_for_updates(self):
        # Only check for updates in frozen version
        if is_editor_engine_built_version():
            if autoupdate.check_for_update():
                link = r"https://gitlab.com/rainlash/lt-maker/-/releases/permalink/latest/downloads/lex_talionis_maker"
                QMessageBox.information(self, "Update Available", "A new update to LT-maker is available!\n"
                                        "Copy this link to your browser to download it:\n"
                                        f"{link}",
                                        )
            else:
                QMessageBox.information(
                    self, "Update not found", "No updates found.")
        else:
            QMessageBox.warning(self, "Update unavailable", "<p>This is a standard python version of LT-maker.</p>"
                                      "<p>Use <b>git fetch</b> and <b>git pull</b> to download the latest git repo updates instead.</p>")

    def show_logs(self):
        # reference to keep sub window alive
        self._log_window_ref = log_viewer.show_logs()

    def show_errors(self):
        # reference to keep sub window alive
        self._error_window_ref = error_viewer.show_error_report()

# Testing
# Run "python -m app.editor.main_editor" from main directory
if __name__ == '__main__':
    import sys
    app = QApplication(sys.argv)
    window = MainEditor('default.ltproj')
    window.show()
    app.exec_()
