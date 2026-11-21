"""
The undo and redo keys in a focused field. A text field claims them ahead of a
window's Undo and Redo shortcuts, even with no typing of its own to undo, so a
window watching its focused widget passes them on to its history from there.
"""
from PyQt5 import QtGui
from PyQt5.QtWidgets import QAction, QLineEdit, QPlainTextEdit, QTextEdit
from PyQt5.QtGui import QKeySequence

def set_undo_shortcuts(undo_action: QAction, redo_action: QAction) -> None:
    """Gives the actions every key the platform has for undo and redo: Ctrl+Y and
    Ctrl+Shift+Z both redo on Windows. QAction's shortcut= keyword takes only the first"""
    undo_action.setShortcuts(QKeySequence.Undo)
    redo_action.setShortcuts(QKeySequence.Redo)

def handles_own_undo(widget, redo: bool) -> bool:
    """Whether a focused text field has typing of its own to undo or redo"""
    if isinstance(widget, QLineEdit):
        return widget.isRedoAvailable() if redo else widget.isUndoAvailable()
    if isinstance(widget, (QTextEdit, QPlainTextEdit)):
        document = widget.document()
        return document.isRedoAvailable() if redo else document.isUndoAvailable()
    return False

def held_in_text_field(widget, event: QtGui.QKeyEvent) -> bool:
    """Whether the undo or redo keys are held down in a text field. Once its own typing
    runs out they go no further, where held keys would run on through the history into
    edits made in any window. A fresh press goes on to the history."""
    return event.isAutoRepeat() and isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit))
