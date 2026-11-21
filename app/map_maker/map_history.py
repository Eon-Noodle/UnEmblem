"""
Undo and redo for the map maker's map, one edit at a time.

As in the editor's edit history (app/editor/edit_history.py), a step keeps only
the parts of the map's saved form that the edit changed: a brush stroke keeps
the tiles it painted. Undo patches the map's saved form as it is now and changes
the map in place into it (MapPrefab.restore_in_place), so only the sprites the
undo reaches are drawn again.

The map maker commits after each edit: a brush or eraser stroke once the mouse
is released, a fill, a cliff marker, a resize, a generated map, and each change
of a box or palette. A commit records whatever changed since the last one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from app.map_maker.map_prefab import MapPrefab
from app.utilities.form_diff import FormChange, form_changes, patched

MAX_STEPS = 100

# What each part of the map's saved form is, for the user
FIELD_NAMES = {
    'nid': 'name',
    'size': 'map size',
    'autotile_fps': 'autotile speed',
    'cliff_markers': 'cliff markers',
    'terrain_grid': 'terrain',
    'seed': 'RNG seed',
    'indoor_palette': 'indoor palette',
    'outdoor_palette': 'outdoor palette',
}

def history_form(tilemap: MapPrefab) -> dict:
    """The map's saved form, less its autotile positions, which follow from its terrain"""
    form = tilemap.save()
    del form['autotile_set']
    return form


@dataclass(eq=False)
class MapStep:
    label: str
    changes: List[FormChange]


# Where the map was saved, once undo no longer reaches it
UNREACHABLE = MapStep('Unreachable', [])


class MapHistory:
    def __init__(self, tilemap: MapPrefab):
        self.clear(tilemap)

    def clear(self, tilemap: MapPrefab) -> None:
        """Forgets everything, and watches tilemap from now on, as when a map is opened"""
        self.tilemap = tilemap
        self._undo: List[MapStep] = []
        self._redo: List[MapStep] = []
        self._baseline = history_form(tilemap)
        self._saved_at: Optional[MapStep] = None  # The last step when the map was saved

    def commit(self, label: str = 'Edit', merge: bool = False) -> Optional[MapStep]:
        """Records whatever changed since the last commit as one step, and returns it.
        With merge, a step with this label just before it, with nothing undone since,
        takes this change into itself, as each value a box takes as it is typed or
        spun does, so it all undoes as one."""
        now = history_form(self.tilemap)
        if now == self._baseline:
            return None
        last = self.last_change()
        if merge and last is not None and last.label == label and not self._redo and last is not self._saved_at:
            before = patched(self._baseline, last.changes, 1)
            last.changes = list(form_changes(before, now))
            if not last.changes:  # Back where it started
                self._undo.pop()
            self._baseline = now
            return last
        step = MapStep(label, list(form_changes(self._baseline, now)))
        self._baseline = now
        self._undo.append(step)
        if len(self._undo) > MAX_STEPS:
            del self._undo[:-MAX_STEPS]
            if self._saved_at is None:
                # Undo no longer reaches the map as it was saved
                self._saved_at = UNREACHABLE
        self._redo.clear()
        return step

    # === Undo ===
    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def last_change(self) -> Optional[MapStep]:
        """The step undo would take back next"""
        return self._undo[-1] if self._undo else None

    def next_redo(self) -> Optional[MapStep]:
        """The step redo would put back next"""
        return self._redo[-1] if self._redo else None

    def undo(self) -> Optional[MapStep]:
        """Takes back the last step, committing what changed since it first"""
        self.commit()
        if not self._undo:
            return None
        step = self._undo.pop()
        self._apply(step, side=1)
        self._redo.append(step)
        return step

    def redo(self) -> Optional[MapStep]:
        """Puts back the last step undone"""
        self.commit()
        if not self._redo:
            return None
        step = self._redo.pop()
        self._apply(step, side=2)
        self._undo.append(step)
        return step

    def _apply(self, step: MapStep, side: int) -> None:
        self.tilemap.restore_in_place(patched(history_form(self.tilemap), step.changes, side))
        self._baseline = history_form(self.tilemap)

    def describe(self, step: MapStep) -> str:
        """What a step changed, in a few words to follow "Undo" or "Undid": its
        label, or for one labelled only 'Edit', the parts of the map it changed"""
        if step.label != 'Edit':
            return step.label[:1].lower() + step.label[1:]
        fields = []
        for where, _, _ in step.changes:
            name = FIELD_NAMES[where[0]]
            if name not in fields:
                fields.append(name)
        return 'edit to %s' % ', '.join(fields)

    # === Saving ===
    def mark_saved(self) -> None:
        """The map is as it was saved, until it changes again"""
        self.commit()
        self._saved_at = self.last_change()

    def is_modified(self) -> bool:
        """Whether the map differs from when it was last saved or opened"""
        self.commit()
        return self.last_change() is not self._saved_at
