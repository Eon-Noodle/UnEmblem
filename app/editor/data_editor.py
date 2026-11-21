from __future__ import annotations

import logging
from typing import List, Optional

from PyQt5 import QtGui, sip
from PyQt5.QtWidgets import QAbstractButton, QAbstractItemView, QAbstractSpinBox, QApplication, QComboBox, \
    QDialog, QGridLayout, QDialogButtonBox, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QTabWidget, QTextEdit, \
    QSizePolicy, QTreeWidget, QWidget
from PyQt5.QtCore import QAbstractItemModel, QAbstractListModel, QEvent, QModelIndex, Qt, QTimer
from PyQt5.QtGui import QKeySequence

from app.data.database.database import DB
from app.data.resources.resources import RESOURCES
from app.editor.edit_history import CHECK_UNRECORDED, HISTORY, ChangeSet, UndoFailed
from app.editor.undo_keys import handles_own_undo, held_in_text_field
from app.editor.settings import MainSettingsController
from app.editor.settings.preference_definitions import Preference

def map_catalogs() -> list:
    """The catalogs of what the main window's level, overworld and tilemap editors
    edit, a change with every click on a map"""
    return [DB.levels, DB.overworlds, RESOURCES.tilemaps]

def widget_state(widget: QWidget) -> list:
    """What widget and the widgets inside it show, as far as text and choices go"""
    state = []
    for child in [widget] + widget.findChildren(QWidget):
        if isinstance(child, QLineEdit):
            state.append(child.text())
        elif isinstance(child, (QTextEdit, QPlainTextEdit)):
            state.append(child.toPlainText())
        elif isinstance(child, QComboBox):
            state.append((child.currentText(), [child.itemText(i) for i in range(child.count())]))
        elif isinstance(child, QAbstractSpinBox):
            state.append(child.text())
        elif isinstance(child, QAbstractButton) and child.isCheckable():
            state.append(child.isChecked())
        elif isinstance(child, QLabel):
            state.append(child.text())
        elif isinstance(child, QAbstractItemView) and child.model() is not None:
            state.append(model_rows(child.model(), QModelIndex(), isinstance(child, QTreeWidget)))
    return state

def model_rows(model: QAbstractItemModel, parent: QModelIndex, tree: bool) -> list:
    """What model shows under parent, row by row. Only a tree's rows are asked for rows
    of their own: the editor's list models, tree views' columns among them, count
    their rows whatever the parent. Its only trees are tree widgets."""
    # A list model's columnCount is private to Qt, and it has one
    columns = 1 if isinstance(model, QAbstractListModel) else model.columnCount(parent)
    state = []
    for row in range(model.rowCount(parent)):
        for column in range(columns):
            # The editor's models take the role without a default
            state.append(model.data(model.index(row, column, parent), Qt.DisplayRole))
        if tree:
            state.append(model_rows(model, model.index(row, 0, parent), tree))
    return state

def check_shows_the_same(tab) -> None:
    """LT_EDITOR_CHECK only: shows the database again in a tab that skipped doing so,
    and logs whether that changed what it shows, which the skip would have missed"""
    before = widget_state(tab)
    tab.reset()
    if widget_state(tab) != before:
        logging.warning("LT_EDITOR_CHECK: %s skipped showing a map edit that changes what it shows; "
                        "it reads maps", type(tab).__name__)

def report_undo_failure(parent, failure: UndoFailed) -> None:
    """Tells the user an undo or redo could not be done, which left everything as it was"""
    step = HISTORY.describe(failure.change_set)
    if failure.redo:
        title, text = _("Redo failed"), _("Could not redo %s. Nothing was changed, "
                                          "and redo cannot go past it.") % step
    else:
        title, text = _("Undo failed"), _("Could not undo %s. Nothing was changed, "
                                          "and undo cannot go past it.") % step
    QMessageBox.critical(parent, title, text + "\n\n" + _("The error is in the editor's log."))

class UndoFeedback(QLabel):
    """Says what an undo or redo just took back or put back, for a few seconds"""
    SHOWN_FOR = 5000  # ms

    def __init__(self, parent=None):
        super().__init__(parent)
        self.clear_timer = QTimer(self)
        self.clear_timer.setSingleShot(True)
        self.clear_timer.timeout.connect(self.clear)

    def show_step(self, change_set: Optional[ChangeSet], redo: bool) -> None:
        """change_set is what HISTORY.undo or redo returned, None when there was nothing to do"""
        if change_set is None:
            self.setText(_("Nothing to redo") if redo else _("Nothing to undo"))
        else:
            self.setText((_("Redid %s") if redo else _("Undid %s")) % HISTORY.describe(change_set))
        self.clear_timer.start(self.SHOWN_FOR)

class EditHistoryDialog(QDialog):
    """
    A dialog whose edits go into the edit history. Closing it keeps them all: undo is
    the way back. With undo_enabled, Ctrl+Z and Ctrl+Shift+Z step back and forth
    through the history, whichever window made the edit, unless the focused text
    field has typing of its own to undo.

    A picker, run modal to choose a record, has OK to choose the record it shows and
    Cancel to choose nothing in place of Close. Its edits stay either way.

    Whenever the history changes, the tab on show shows the database again, unless
    the change was its own edit, or only edited fields of the main window's maps
    (map_catalogs) and the tab reads none of them (its reads_maps) or none it reads
    there (a tab that reads maps says which edits it reads with reads_map_edit). Those
    edits come with every click on a map. A tab of a window with several shows the database
    again when switched to.
    """
    undo_enabled = True
    # Every dialog whose history is running, to find the tab a widget is in
    running: List[EditHistoryDialog] = []

    def start_history(self):
        self.history_running = True
        # Beside the buttons, which each subclass places
        self.undo_feedback = UndoFeedback(self)
        EditHistoryDialog.running.append(self)
        self.changes = []  # (origin, change set) of each change no tab shows yet
        app = QApplication.instance()
        app.focusChanged.connect(self.on_focus_changed)
        # A key press goes to the focused widget, or to the dialog when nothing in it
        # has focus, so only those are watched for the undo keys. Filtering every
        # event the application sends slowed every click and redraw
        self.installEventFilter(self)
        self.key_widget = None
        self.watch_keys(QApplication.focusWidget())
        HISTORY.listen(self.on_history_changed)
        self.finished.connect(self.stop_history)

    def stop_history(self):
        if not self.history_running:
            return
        self.history_running = False
        EditHistoryDialog.running.remove(self)
        app = QApplication.instance()
        app.focusChanged.disconnect(self.on_focus_changed)
        self.watch_keys(None)
        self.removeEventFilter(self)
        HISTORY.unlisten(self.on_history_changed)
        for tab in self.history_tabs():
            HISTORY.unbind(tab)

    def watch_keys(self, widget):
        """Watches widget for the undo keys in place of the one watched before, if it
        is in this dialog"""
        if self.key_widget is not None and not sip.isdeleted(self.key_widget):
            self.key_widget.removeEventFilter(self)
        self.key_widget = widget if widget is not None and self.isAncestorOf(widget) else None
        if self.key_widget is not None:
            self.key_widget.installEventFilter(self)

    def history_tabs(self) -> list:
        raise NotImplementedError

    def current_history_tab(self):
        raise NotImplementedError

    def finish_editing(self):
        """Ends the edit in the focused field. Some fields apply their edit only when
        they lose focus -- a typed ID renames the record then -- so that has to happen
        before the dialog commits or undoes, not after it closes."""
        focused = QApplication.focusWidget()
        if focused is not None and self.isAncestorOf(focused):
            focused.clearFocus()

    def history_tab_holding(self, widget):
        return next((tab for tab in self.history_tabs() if widget is not None and tab.isAncestorOf(widget)), None)

    @classmethod
    def tab_holding(cls, widget):
        """The tab of any dialog on the history that widget is in, if one is"""
        return next((tab for dialog in cls.running for tab in [dialog.history_tab_holding(widget)] if tab), None)

    def button_box(self, picker: bool) -> QDialogButtonBox:
        if picker:
            buttons = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        else:
            buttons = QDialogButtonBox.Close
        box = QDialogButtonBox(buttons, Qt.Horizontal, self)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        return box

    def on_focus_changed(self, old, new):
        self.watch_keys(new)
        # The field losing focus has finished its edit by now: Qt sends it
        # FocusOut before announcing the change. Focus coming into this dialog or
        # leaving it commits the edit, made in the tab holding the field, whichever
        # dialog that is, so that tab is not shown again
        if (new is not None and self.isAncestorOf(new)) or (old is not None and self.isAncestorOf(old)):
            HISTORY.commit(origin=EditHistoryDialog.tab_holding(old))

    def on_history_changed(self, origin, change_set: ChangeSet):
        # The change may still be under way -- a tab's own rename or delete --
        # so the tabs show it once the event that made it is done
        if not self.changes:
            QTimer.singleShot(0, self.show_changes)
        self.changes.append((origin, change_set))

    def show_changes(self):
        """Shows the database again in the tab on show, unless no change can alter what
        it shows. The others show it when switched to."""
        changes, self.changes = self.changes, []
        if not self.history_running:
            return
        tab = self.current_history_tab()
        if all(origin is tab for origin, _ in changes):
            return
        if all(origin is tab or (change_set.only_edits_fields_of(map_catalogs())
                                 and not (tab.reads_maps and tab.reads_map_edit(change_set)))
               for origin, change_set in changes):
            if CHECK_UNRECORDED:
                check_shows_the_same(tab)
            return
        tab.reset()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and self.undo_enabled and self.isActiveWindow():
            if event.matches(QKeySequence.Undo):
                redo = False
            elif event.matches(QKeySequence.Redo):
                redo = True
            else:
                return super().eventFilter(obj, event)
            focused = QApplication.focusWidget()
            if handles_own_undo(focused, redo):
                return super().eventFilter(obj, event)
            if held_in_text_field(focused, event):
                return True
            if redo:
                self.redo()
            else:
                self.undo()
            return True
        return super().eventFilter(obj, event)

    def undo(self):
        self.finish_editing()
        try:
            self.undo_feedback.show_step(HISTORY.undo(), redo=False)
        except UndoFailed as failure:
            report_undo_failure(self, failure)
        self.show_changes()

    def redo(self):
        self.finish_editing()
        try:
            self.undo_feedback.show_step(HISTORY.redo(), redo=True)
        except UndoFailed as failure:
            report_undo_failure(self, failure)
        self.show_changes()

class SingleDatabaseEditor(EditHistoryDialog):
    def __init__(self, tab, parent=None, picker=False):
        super().__init__(parent)
        self.window = parent
        self.main_editor = self.window

        self.set_up(picker)

        self.tab = tab.create(self)
        self.grid.addWidget(self.tab, 0, 0, 1, 2)

        self.setWindowTitle(self.tab.windowTitle())

        # Restore Geometry
        self.settings = MainSettingsController()
        geometry = self.settings.component_controller.get_geometry(self._type())
        if geometry:
            self.restoreGeometry(geometry)
        state = self.settings.component_controller.get_state(self._type())
        if state:
            self.tab.splitter.restoreState(state)

    def keyPressEvent(self, keypress: QtGui.QKeyEvent) -> None:
        if keypress.key() == self.settings.get_preference(Preference.EDITOR_CLOSE_BUTTON):
            self.reject()
        else:
            pass

    def set_up(self, picker: bool):
        self.setStyleSheet("font: 10pt;")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)

        self.start_history()

        self.grid = QGridLayout(self)
        self.setLayout(self.grid)

        self.buttonbox = self.button_box(picker)
        self.grid.addWidget(self.undo_feedback, 1, 0)
        self.grid.addWidget(self.buttonbox, 1, 1)

    def history_tabs(self) -> list:
        return [self.tab]

    def current_history_tab(self):
        return self.tab

    def on_tab_close(self):
        self.tab.on_tab_close()

    def done(self, result):
        # Whichever button closed it, the edits stay
        self.finish_editing()
        self.save_geometry()
        self.on_tab_close()
        HISTORY.commit()
        super().done(result)

    def closeEvent(self, event):
        self.save_geometry()
        self.on_tab_close()
        super().closeEvent(event)

    def _type(self):
        return self.tab.__class__.__name__

    def save_geometry(self):
        self.settings.component_controller.set_geometry(self._type(), self.saveGeometry())
        self.settings.component_controller.set_state(self._type(), self.tab.splitter.saveState())

class MultiDatabaseEditor(SingleDatabaseEditor):
    def __init__(self, tabs, parent=None):
        EditHistoryDialog.__init__(self, parent)
        self.window = parent
        self.main_editor = self.window

        self.set_up(picker=False)

        self.tab_bar = QTabWidget(self)
        self.grid.addWidget(self.tab_bar, 0, 0, 1, 2)
        self.tabs = []
        for tab in tabs:
            new_tab = tab.create(self)
            self.tabs.append(new_tab)
            self.tab_bar.addTab(new_tab, new_tab.windowTitle())

        self.current_tab = self.tab_bar.currentWidget()
        self.tab_bar.currentChanged.connect(self.on_tab_changed)

        # Restore Geometry
        self.settings = MainSettingsController()
        geometry = self.settings.component_controller.get_geometry(self._type())
        if geometry:
            self.restoreGeometry(geometry)
        for tab in self.tabs:
            _type = tab.__class__.__name__
            state = self.settings.component_controller.get_state(_type)
            if state and tab.splitter:
                tab.splitter.restoreState(state)
            # Also handle the frame itself
            right_frame_type = _type + '_right_frame'
            state = self.settings.component_controller.get_state(right_frame_type)
            if state:
                tab.right_frame.restore_state(state)

    def history_tabs(self) -> list:
        return self.tabs

    def current_history_tab(self):
        return self.current_tab

    def on_tab_changed(self, idx):
        # Make each tab individually resizable
        for i in range(self.tab_bar.count()):
            if i == idx:
                self.tab_bar.widget(i).setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            else:
                self.tab_bar.widget(i).setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        new_tab = self.tab_bar.currentWidget()
        self.current_tab = new_tab
        self.current_tab.update_list()
        self.current_tab.reset()

    def _type(self):
        s = ''
        for tab in self.tabs:
            s += tab.__class__.__name__
        return s

    def on_tab_close(self, event=None):
        if event:
            for tab in self.tabs:
                tab.closeEvent(event)

    def save_geometry(self):
        self.settings.component_controller.set_geometry(self._type(), self.saveGeometry())
        for tab in self.tabs:
            _type = tab.__class__.__name__
            if hasattr(tab, 'splitter') and tab.splitter:
                self.settings.component_controller.set_state(_type, tab.splitter.saveState())
            if hasattr(tab, 'right_frame') and hasattr(tab.right_frame, 'save_state'):
                state = tab.right_frame.save_state()
                right_frame_type = _type + '_right_frame'
                if state:
                    self.settings.component_controller.set_state(right_frame_type, state)

    def closeEvent(self, event):
        self.save_geometry()
        self.on_tab_close(event)
        super().closeEvent(event)

class SingleResourceEditor(EditHistoryDialog):
    """
    Resources are recorded like the database, and reach the project when it is
    saved.
    """
    def __init__(self, tab, resource_types=None, parent=None, *args, picker=False, **kwargs):
        super().__init__(parent)
        self.window = parent
        self.main_editor = parent
        self.resource_types = resource_types
        self.setStyleSheet("font: 10pt;")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)

        self.start_history()

        self.grid = QGridLayout(self)
        self.setLayout(self.grid)

        self.buttonbox = self.button_box(picker)
        self.grid.addWidget(self.undo_feedback, 1, 0)
        self.grid.addWidget(self.buttonbox, 1, 1)

        self.tab = tab.create(self, *args, **kwargs)
        self.grid.addWidget(self.tab, 0, 0, 1, 2)

        self.setWindowTitle(self.tab.windowTitle())

        # Restore Geometry
        self.settings = MainSettingsController()
        geometry = self.settings.component_controller.get_geometry(self._type())
        if geometry:
            self.restoreGeometry(geometry)
        state = self.settings.component_controller.get_state(self._type())
        if state:
            self.tab.splitter.restoreState(state)

    def history_tabs(self) -> list:
        return [self.tab]

    def current_history_tab(self):
        return self.tab

    def done(self, result):
        # Whichever button closed it, the edits stay
        self.finish_editing()
        self.save_geometry()
        HISTORY.commit()
        super().done(result)
        self.close()

    def closeEvent(self, event):
        self.save_geometry()
        super().closeEvent(event)

    def _type(self):
        return self.tab.__class__.__name__

    def save_geometry(self):
        self.settings.component_controller.set_geometry(self._type(), self.saveGeometry())
        if hasattr(self.tab, 'splitter'):
            self.settings.component_controller.set_state(self._type(), self.tab.splitter.saveState())

class MultiResourceEditor(SingleResourceEditor):
    def __init__(self, tabs, resource_types, parent=None):
        EditHistoryDialog.__init__(self, parent)
        self.window = parent
        self.main_editor = parent
        self.resource_types = resource_types
        self.setWindowTitle("Resource Editor")
        self.setStyleSheet("font: 10pt;")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)

        self.start_history()

        self.grid = QGridLayout(self)
        self.setLayout(self.grid)

        self.buttonbox = self.button_box(picker=False)
        self.grid.addWidget(self.undo_feedback, 1, 0)
        self.grid.addWidget(self.buttonbox, 1, 1)

        self.tab_bar = QTabWidget(self)
        self.grid.addWidget(self.tab_bar, 0, 0, 1, 2)
        self.tabs = []
        for tab in tabs:
            new_tab = tab.create(self)
            self.tabs.append(new_tab)
            self.tab_bar.addTab(new_tab, new_tab.windowTitle())

        self.current_tab = self.tab_bar.currentWidget()
        self.tab_bar.currentChanged.connect(self.on_tab_changed)

        # Restore Geometry
        self.settings = MainSettingsController()
        geometry = self.settings.component_controller.get_geometry(self._type())
        if geometry:
            self.restoreGeometry(geometry)
        for tab in self.tabs:
            _type = tab.__class__.__name__
            state = self.settings.component_controller.get_state(_type)
            if state and tab.splitter:
                tab.splitter.restoreState(state)
            # Also handle the frame itself
            right_frame_type = _type + '_right_frame'
            state = self.settings.component_controller.get_state(right_frame_type)
            if state:
                tab.right_frame.restore_state(state)

    def history_tabs(self) -> list:
        return self.tabs

    def current_history_tab(self):
        return self.current_tab

    def on_tab_changed(self, idx):
        # Make each tab individually resizable
        for i in range(self.tab_bar.count()):
            if i == idx:
                self.tab_bar.widget(i).setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            else:
                self.tab_bar.widget(i).setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        new_tab = self.tab_bar.currentWidget()
        self.current_tab = new_tab
        self.current_tab.update_list()
        self.current_tab.reset()

    def _type(self):
        s = ''
        for tab in self.tabs:
            s += tab.__class__.__name__
        return s

    def save_geometry(self):
        self.settings.component_controller.set_geometry(self._type(), self.saveGeometry())
        for tab in self.tabs:
            _type = tab.__class__.__name__
            if hasattr(tab, 'splitter') and tab.splitter:
                self.settings.component_controller.set_state(_type, tab.splitter.saveState())
            if hasattr(tab, 'right_frame') and hasattr(tab.right_frame, 'save_state'):
                state = tab.right_frame.save_state()
                right_frame_type = _type + '_right_frame'
                if state:
                    self.settings.component_controller.set_state(right_frame_type, state)

    def closeEvent(self, event):
        self.save_geometry()
        for tab in self.tabs:
            tab.closeEvent(event)
        super().closeEvent(event)

class NewMultiResourceEditor(MultiResourceEditor):
    def on_tab_changed(self, idx):
        # Make each tab individually resizable
        for i in range(self.tab_bar.count()):
            if i == idx:
                self.tab_bar.widget(i).setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            else:
                self.tab_bar.widget(i).setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        new_tab = self.tab_bar.currentWidget()
        self.current_tab = new_tab
        self.current_tab.reset()
