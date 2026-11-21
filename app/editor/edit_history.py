"""
Undo and redo for edits to the database, one record at a time.

The history never snapshots the whole database. It records three kinds of delta:

- RecordChange: the parts of a record's saved form an edit changed, before and
  after, so a stroke on a big tilemap keeps only the tiles it painted. Undo
  patches the record's saved form as it is now and restores the fields in place
  on the same object, so anything holding the record keeps holding the right
  one. A resource with files keeps its whole saved form before and after
  instead (WholeRecordChange), since keep_files repoints each version's files.
- CatalogChange: a catalog's members and order (object references, not copies),
  plus its categories and, for teams, the alliances. Creating, deleting,
  duplicating, pasting and reordering are all changes of membership.
- GridChange: the movement cost grid before and after, restored in place. The
  grid is one record outside any catalog, compared at every commit like a
  catalog's members.

Editors bind the record they are showing. At each commit point (a change of
selection or of focus, a structural edit, closing, undo) the history compares
each bound record with its baseline and each catalog's members with the last
ones it saw, and turns whatever differs into one change set. Records changed
without being shown, like those a rename cascades into, are recorded by
running the change inside `modifying`; rewrite and clear here do that for the
reference cascades.

After every change set it records, undoes or redoes, the history tells its
listeners, so every open view can show the database again. A change set
remembers its origin, the view that made it and so already shows it.

Set LT_EDITOR_CHECK=1 to log any record that changed without being recorded.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
import logging
import os
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Set, Tuple

from app.data.category import CategorizedCatalog
from app.data.database import references
from app.data.database.constants import Constant
from app.data.database.database import DB
from app.data.database.mcost import McostGrid
from app.data.database.teams import TeamCatalog
from app.data.resources.resource_prefab import WithResources
from app.data.resources.resources import RESOURCES, Resources
from app.data.resources.tiles import TileMapPrefab
from app.editor.file_manager.staging import STAGING
from app.utilities.data import Data
from app.utilities.form_diff import FormChange, Where, form_changes, patched
from app.utilities.typing import NID

MAX_CHANGE_SETS = 100
CHECK_UNRECORDED = bool(os.environ.get('LT_EDITOR_CHECK'))


def saved_form(record) -> Any:
    """A record's saved form, which may share lists and dicts with the record"""
    if isinstance(record, WithResources):
        # With where its files are, which a resource's saved form leaves out
        return {'record': record.save(), 'files': record.file_paths()}
    return record.save()

def saved(record) -> Any:
    """A record's saved form, sharing nothing with the record"""
    return copy.deepcopy(saved_form(record))

def slot_names(cls) -> Iterator[str]:
    for klass in cls.__mro__:
        slots = klass.__dict__.get('__slots__', ())
        for name in ((slots,) if isinstance(slots, str) else slots):
            if not name.startswith('__'):
                yield name

def restore_in_place(record, saved_form) -> None:
    if isinstance(record, Constant):
        # A constant saves only its value; the rest is fixed by the engine
        record.value = copy.deepcopy(saved_form[1])
        return
    files = None
    if isinstance(record, WithResources):
        saved_form, files = saved_form['record'], saved_form['files']
    fresh = type(record).restore(copy.deepcopy(saved_form))
    record.__dict__.clear()
    record.__dict__.update(fresh.__dict__)
    # A slots dataclass, like a font, keeps its fields outside __dict__
    for name in slot_names(type(record)):
        setattr(record, name, getattr(fresh, name))
    if isinstance(record, TileMapPrefab):
        # The layers were built for the fresh copy, which they hold as their parent
        for layer in record.layers:
            layer.parent = record
    if files is not None:
        # Images cached on the record went with the old fields, so they load again from these
        record.set_file_paths(copy.deepcopy(files))

def _file_key(path) -> str:
    """The one spelling of a path, for comparing paths"""
    return os.path.normcase(os.path.abspath(path))

def rebuild_keys(data: Data) -> None:
    """Re-keys a Data from its members' current nids, keeping their order"""
    members = list(data)
    data.clear()
    for member in members:
        data.append(member)


@dataclass(eq=False)
class RecordChange:
    catalog: Data
    record: Any
    changes: List[FormChange]

    def undo(self):
        restore_in_place(self.record, patched(saved(self.record), self.changes, 1))

    def redo(self):
        restore_in_place(self.record, patched(saved(self.record), self.changes, 2))


@dataclass(eq=False)
class WholeRecordChange:
    catalog: Data
    record: WithResources
    before: Any
    after: Any

    def undo(self):
        restore_in_place(self.record, self.before)

    def redo(self):
        restore_in_place(self.record, self.after)


def record_change(data: Data, record, before, after) -> Delta:
    """The change between two saved forms of a record, which share nothing with it"""
    if isinstance(record, WithResources) and record.path_fields:
        # keep_files lists the files of every version, which only the whole version can
        return WholeRecordChange(data, record, before, after)
    return RecordChange(data, record, list(form_changes(before, after)))


@dataclass(frozen=True)
class CatalogState:
    members: Tuple[Any, ...]
    extras: Tuple[Tuple[str, Any], ...]  # Catalog-level attributes, by name

    @classmethod
    def of(cls, data: Data) -> CatalogState:
        extras = []
        if isinstance(data, CategorizedCatalog):
            extras.append(('categories', {nid: list(path) for nid, path in data.categories.items()}))
        if isinstance(data, TeamCatalog):
            extras.append(('alliance_pairs', frozenset(data.alliance_pairs)))
        return cls(tuple(data), tuple(extras))

    def same_as(self, other: CatalogState) -> bool:
        return len(self.members) == len(other.members) and \
            all(a is b for a, b in zip(self.members, other.members)) and \
            self.extras == other.extras

    def apply_to(self, data: Data) -> None:
        data.clear()
        for member in self.members:
            data.append(member)
        for name, value in self.extras:
            if name == 'categories':
                # In place: tabs hold on to the categories object
                data.categories.clear()
                data.categories.update({nid: list(path) for nid, path in value.items()})
            elif name == 'alliance_pairs':
                data.alliance_pairs = set(value)


@dataclass(eq=False)
class CatalogChange:
    catalog: Data
    before: CatalogState
    after: CatalogState

    def undo(self):
        self.before.apply_to(self.catalog)

    def redo(self):
        self.after.apply_to(self.catalog)


@dataclass(eq=False)
class GridChange:
    grid: McostGrid
    before: Any  # The grid's saved form
    after: Any
    catalog = None  # In no catalog, so none to re-key

    def undo(self):
        self.grid.restore(copy.deepcopy(self.before))

    def redo(self):
        self.grid.restore(copy.deepcopy(self.after))


Delta = Any  # RecordChange | WholeRecordChange | CatalogChange | GridChange


@dataclass(eq=False)
class ChangeSet:
    label: str
    origin: Any = None  # The view that made these edits, if one did
    deltas: List[Delta] = field(default_factory=list)

    def catalogs(self) -> List[Data]:
        seen = []
        for delta in self.deltas:
            if delta.catalog is not None and not any(delta.catalog is c for c in seen):
                seen.append(delta.catalog)
        return seen

    def only_edits_fields_of(self, catalogs: List[Data]) -> bool:
        """Whether every change is to the fields of records in these catalogs: none
        adds, removes, reorders or renames a record, or changes anything else"""
        return all(isinstance(delta, RecordChange) and any(delta.catalog is c for c in catalogs)
                   and not any(_may_rename(where) for where, _, _ in delta.changes)
                   for delta in self.deltas)

    def undo(self):
        """Undoes every change, or none: if one fails, those already undone are redone
        before the failure goes on"""
        undone = []
        try:
            for delta in reversed(self.deltas):
                delta.undo()
                undone.append(delta)
        except Exception:
            for delta in reversed(undone):
                delta.redo()
            raise
        finally:
            for data in self.catalogs():
                rebuild_keys(data)

    def redo(self):
        """Redoes every change, or none, as undo does"""
        redone = []
        try:
            for delta in self.deltas:
                delta.redo()
                redone.append(delta)
        except Exception:
            for delta in reversed(redone):
                delta.undo()
            raise
        finally:
            for data in self.catalogs():
                rebuild_keys(data)


class UndoFailed(Exception):
    """An undo or redo that could not be done. Its records are as they were before
    it, and its step is where it was in the history"""
    def __init__(self, change_set: ChangeSet, redo: bool):
        super().__init__('Could not %s %s' % ('redo' if redo else 'undo', change_set.label))
        self.change_set, self.redo = change_set, redo


def _may_rename(where: Where) -> bool:
    """Whether a change at where may change a record's nid, which a database record's
    saved form holds at the top and a resource's under 'record'"""
    return where == ('nid',)[:len(where)] or where == ('record', 'nid')[:len(where)]


class EditHistory:
    def __init__(self, db, resources):
        self.db = db
        self.resources = resources
        self._undo: List[ChangeSet] = []
        self._redo: List[ChangeSet] = []
        self._open: List[ChangeSet] = []  # Nested change sets merge into the outermost
        self._modifying: Set[int] = set()  # id() of each record an open `modifying` watches
        # id(owner) -> id(record) -> (catalog, record, baseline). An owner is
        # whatever shows the records, usually an editor tab
        self._bound: Dict[int, Dict[int, Tuple[Data, Any, Any]]] = {}
        self._catalogs: Dict[int, Tuple[Data, CatalogState]] = {}
        self._grid: Any = None  # The movement cost grid's saved form at the last commit
        self._shadow: Dict[int, dict] = {}  # LT_EDITOR_CHECK only
        self._listeners: List[Callable[[Any], None]] = []
        self._rename_listeners: List[Callable[[references.Target, NID, NID], None]] = []
        self.clear()

    # === Lifetime ===
    def clear(self):
        """Forgets everything. Called when a project loads."""
        self._undo.clear()
        self._redo.clear()
        self._open.clear()
        self._modifying.clear()
        self._bound.clear()
        self._catalogs = {id(data): (data, CatalogState.of(data)) for data in self.watched_catalogs()}
        self._grid = self.db.mcost.save()
        if CHECK_UNRECORDED:
            self._shadow = self._saved_records()

    def watched_catalogs(self) -> List[Data]:
        return [references.catalog(self.db, dtype) for dtype in references.OWNER_TYPES] + \
            [getattr(self.resources, name) for name in Resources.save_data_types]

    def is_watched(self, data: Data) -> bool:
        return id(data) in self._catalogs

    # === Listening ===
    def listen(self, listener: Callable[[Any, ChangeSet], None]) -> None:
        """Calls listener(origin, change_set) after each change set is recorded, undone
        or redone. origin is the view that made the change and already shows it, or
        None when every view needs to show the database again, as after an undo.
        change_set holds what changed, undone or not."""
        self._listeners.append(listener)

    def unlisten(self, listener: Callable[[Any, ChangeSet], None]) -> None:
        self._listeners.remove(listener)

    def listen_to_renames(self, listener: Callable[[references.Target, NID, NID], None]) -> None:
        """Calls listener(target, old_nid, new_nid) after each rename's references are rewritten"""
        self._rename_listeners.append(listener)

    def unlisten_to_renames(self, listener: Callable[[references.Target, NID, NID], None]) -> None:
        self._rename_listeners.remove(listener)

    def _announce(self, origin, change_set: ChangeSet) -> None:
        for listener in self._listeners[:]:
            listener(origin, change_set)

    # === Recording ===
    def bind(self, record, data: Data, owner=None) -> None:
        """Starts watching a record an editor shows, in place of the one its owner showed
        before. Without an owner the record stays bound until the history is cleared.
        Commits whatever changed first.

        Bind once the record is on show. Showing a record must change nothing in it,
        which test_editor_show checks for every editor window: a change made before
        the bind becomes part of the baseline, unrecorded and never undone."""
        watched = record is not None and self.is_watched(data)
        if watched and CHECK_UNRECORDED:
            self._shadow[id(record)] = saved(record)
        self.commit(origin=owner)
        bindings = self._bound.setdefault(id(owner), {})
        if owner is not None:
            kept = bindings.get(id(record))
            bindings.clear()
            if watched and kept is not None and kept[0] is data and kept[1] is record:
                # Shown again, as a tab does after every change elsewhere: the
                # commit has brought its baseline up to date
                bindings[id(record)] = kept
                return
        if watched:
            bindings[id(record)] = (data, record, saved(record))

    def bind_all(self, records: Iterable[Any], data: Data, owner) -> None:
        """Watches every one of these records at once"""
        self.commit(origin=owner)
        bindings = self._bound.setdefault(id(owner), {})
        bindings.clear()
        if self.is_watched(data):
            for record in records:
                bindings[id(record)] = (data, record, saved(record))

    def unbind(self, owner) -> None:
        """Stops watching what owner shows, as when its editor closes"""
        self.commit(origin=owner)
        self._bound.pop(id(owner), None)

    def _is_bound(self, record) -> bool:
        return any(id(record) in bindings for bindings in self._bound.values())

    def _all_bound(self) -> Iterator[Tuple[Dict[int, Tuple[Data, Any, Any]], int]]:
        for bindings in self._bound.values():
            for key in list(bindings):
                yield bindings, key

    def begin(self, label: str = 'Edit', origin=None) -> None:
        if not self._open:
            change_set = ChangeSet(label, origin)
            self._open.append(change_set)
            # Whatever changed since the last commit belongs with this edit
            self._collect(change_set)
        else:
            self._open.append(self._open[0])

    def end(self) -> None:
        change_set = self._open.pop()
        if self._open:
            return
        self._collect(change_set)
        if change_set.deltas:
            self._push(change_set)
        if CHECK_UNRECORDED:
            self._check_unrecorded(change_set)
        if change_set.deltas:
            self._announce(change_set.origin, change_set)

    def change_set(self, label: str = 'Edit', origin=None) -> _ChangeSetContext:
        """with history.change_set('Delete Iron Sword'): ... records everything inside as one undo step.
        origin is the view making the change, when it shows the change by itself."""
        return _ChangeSetContext(self, label, origin)

    def commit(self, label: str = 'Edit', origin=None) -> None:
        """Records whatever changed since the last commit as one undo step"""
        if self._open:
            # Into the open change set now, since a bind may follow and take a new baseline
            self._collect(self._open[0])
            return
        # Nothing changes between its start and end, so it collects once, as it ends
        self._open.append(ChangeSet(label, origin))
        self.end()

    def modifying(self, records: Iterable[Tuple[Any, Data]]) -> _ModifyingContext:
        """with history.modifying([(record, catalog), ...]): changes records nobody has bound"""
        return _ModifyingContext(self, list(records))

    # === References ===
    def rewrite(self, target: references.Target, old_nid: NID, new_nid: NID,
                renamed: bool = True) -> List[references.RefSite]:
        """references.rewrite, recorded. renamed is False for a deletion swapping
        its references onto another record, which rename listeners don't hear of"""
        sites = references.find_referrers(self.db, target, old_nid)
        with self.change_set('Rename %s' % old_nid), self.modifying(self._owners(sites)):
            changed = references.rewrite(self.db, target, old_nid, new_nid)
        if renamed and old_nid and old_nid != new_nid:
            for listener in self._rename_listeners[:]:
                listener(target, old_nid, new_nid)
        return changed

    def clear_references(self, target: references.Target, nid: NID,
                         fallback: Optional[NID] = None) -> List[references.RefSite]:
        """references.clear, recorded"""
        sites = references.find_referrers(self.db, target, nid)
        with self.change_set('Delete %s' % nid), self.modifying(self._owners(sites)):
            return references.clear(self.db, target, nid, fallback)

    def rename(self, data: Data, record, new_nid: NID,
               cascade: Optional[Callable[[NID, NID], Any]] = None) -> None:
        """Renames a record in its catalog, and with cascade(old_nid, new_nid) whatever
        names it, as one undo step"""
        old_nid = record.nid
        if new_nid == old_nid:
            return
        with self.change_set('Rename %s' % old_nid), self.modifying([(record, data)]):
            if cascade:
                cascade(old_nid, new_nid)
            data.update_nid(record, new_nid)

    def _owners(self, sites: List[references.RefSite]) -> Iterator[Tuple[Any, Data]]:
        for owner_type, records in references.owners(sites).items():
            data = references.catalog(self.db, owner_type)
            for record in records:
                yield record, data

    # === Undo ===
    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> Optional[ChangeSet]:
        """Undoes the last change set, whichever window made it. Raises UndoFailed,
        leaving everything as it was, if it cannot."""
        self.commit()
        if not self._undo:
            return None
        change_set = self._undo[-1]
        self._step(change_set, redo=False)
        self._redo.append(self._undo.pop())
        self.rebaseline()
        self._announce(None, change_set)
        return change_set

    def redo(self) -> Optional[ChangeSet]:
        """Redoes the last change set undone, raising UndoFailed as undo does"""
        self.commit()
        if not self._redo:
            return None
        change_set = self._redo[-1]
        self._step(change_set, redo=True)
        self._undo.append(self._redo.pop())
        self.rebaseline()
        self._announce(None, change_set)
        return change_set

    def _step(self, change_set: ChangeSet, redo: bool) -> None:
        """Undoes or redoes change_set, which stays where it is if that fails. A step
        fails when a record changed without being recorded so that the step no
        longer fits it"""
        try:
            if redo:
                change_set.redo()
            else:
                change_set.undo()
        except Exception as error:
            logging.exception("Could not %s %s", 'redo' if redo else 'undo', self.describe(change_set))
            raise UndoFailed(change_set, redo) from error

    def mark(self) -> ChangeSet | None:
        """A point to come back to with undo_to"""
        self.commit()
        return self.last_change()

    def last_change(self) -> Optional[ChangeSet]:
        """The change set undo would take back next, without committing first"""
        return self._undo[-1] if self._undo else None

    def next_redo(self) -> Optional[ChangeSet]:
        """The change set redo would put back next"""
        return self._redo[-1] if self._redo else None

    def describe(self, change_set: ChangeSet) -> str:
        """What a change set changed, in a few words for the user, to follow "Undo"
        or "Undid". Most change sets are labelled only 'Edit', so those are told by
        the records they changed: "edit to Iron Sword (Items)", "edits to Iron Sword,
        Steel Sword +3 (Items)", "adding Iron Sword (Items)". A labelled one, like a
        rename, says how many records it changed besides its own."""
        changed: Dict[int, Tuple[Data, Any]] = {}  # id(record) -> (catalog, record), in order
        added, removed = set(), set()
        reordered: List[Data] = []
        grid = False
        for delta in change_set.deltas:
            if isinstance(delta, CatalogChange):
                before = {id(member) for member in delta.before.members}
                after = {id(member) for member in delta.after.members}
                for member in delta.after.members + delta.before.members:
                    if (id(member) in before) != (id(member) in after):
                        (removed if id(member) in before else added).add(id(member))
                        changed.setdefault(id(member), (delta.catalog, member))
                if before == after:
                    reordered.append(delta.catalog)
            elif isinstance(delta, GridChange):
                grid = True
            else:
                changed.setdefault(id(delta.record), (delta.catalog, delta.record))

        if change_set.label != 'Edit':
            what = change_set.label[:1].lower() + change_set.label[1:]
            # A movement type renamed or deleted is a column of the grid, not a record
            others = len(changed) - (0 if grid else 1)
            if others > 0 and change_set.label.startswith(('Rename ', 'Delete ')):
                what += ' (and %d %s naming it)' % (others, 'record' if others == 1 else 'records')
            return what
        if not changed:
            if grid:
                return 'edit to movement costs'
            if reordered:
                return 'reordering %s' % self.catalog_name(reordered[0])
            return 'edit'
        if added.issuperset(changed):
            verb = 'adding'
        elif removed.issuperset(changed):
            verb = 'removing'
        else:
            verb = 'edit to' if len(changed) == 1 else 'edits to'
        nids = [str(record.nid) for _, record in changed.values()]
        what = '%s %s' % (verb, ', '.join(nids[:2]))
        if len(nids) > 2:
            what += ' +%d' % (len(nids) - 2)
        catalogs = {id(data): data for data, _ in changed.values()}
        if len(catalogs) == 1:
            what += ' (%s)' % self.catalog_name(next(iter(catalogs.values())))
        return what

    def catalog_name(self, data: Data) -> str:
        """A watched catalog's name, from its name on the database or resources"""
        for dtype in references.OWNER_TYPES:
            if references.catalog(self.db, dtype) is data:
                name = dtype.name
                break
        else:
            name = next(name for name in Resources.save_data_types if getattr(self.resources, name) is data)
        # AI, SFX
        return name.upper() if len(name) <= 3 else name.replace('_', ' ').title()

    def undo_to(self, mark: Optional[ChangeSet]) -> None:
        """Puts everything back as it was at mark and forgets what came after.
        A mark that history has since dropped off its end undoes as far as
        history goes. With nothing done since mark, the redo steps stay. A step that
        cannot be undone or redone stops it there and raises UndoFailed."""
        self.commit()
        # Everything undone or redone, for the listeners
        changed = ChangeSet('Undo')
        # A step that fails stops it there, with the steps before it done
        try:
            if mark is not None and any(change_set is mark for change_set in self._redo):
                # Undone past the mark: redo up to it, then forget the steps undone past it
                while self._undo[-1:] != [mark]:
                    change_set = self._redo[-1]
                    self._step(change_set, redo=True)
                    self._undo.append(self._redo.pop())
                    changed.deltas.extend(change_set.deltas)
                self._redo.clear()
            else:
                # A step recorded since mark already cleared the redo steps
                while self._undo and self._undo[-1] is not mark:
                    change_set = self._undo[-1]
                    self._step(change_set, redo=False)
                    self._undo.pop()
                    changed.deltas.extend(change_set.deltas)
        finally:
            self.rebaseline()
            if changed.deltas:
                self._announce(None, changed)

    # === Files ===
    def keep_files(self, paths: Iterable[str]) -> None:
        """Points each resource that uses one of these files, and each version of a
        resource the history holds, at staged copies of the files, since they are
        about to be overwritten or deleted. Each folder holding one of them is staged
        together, so a resource that names several files from one base path keeps
        them side by side."""
        at_risk = {_file_key(path) for path in paths}
        if not at_risk:
            return
        self.commit()
        staged = {}  # A folder's files -> the staged folder holding copies of them

        def kept_paths(resource: WithResources) -> Optional[Dict[str, Any]]:
            by_folder: Dict[str, List[str]] = {}
            for path in resource.used_resources():
                if path:
                    by_folder.setdefault(_file_key(os.path.dirname(path)), []).append(str(path))
            moved = {}
            for folder, files in by_folder.items():
                if any(_file_key(path) in at_risk for path in files):
                    key = tuple(files)
                    if key not in staged:
                        staged[key] = STAGING.stage_files(files)
                    moved[folder] = staged[key]
            if not moved:
                return None
            kept = resource.file_paths()
            for name, path in kept.items():
                if path and _file_key(os.path.dirname(path)) in moved:
                    kept[name] = os.path.join(moved[_file_key(os.path.dirname(path))], os.path.basename(path))
            return kept

        for change_set in self._undo + self._redo:
            for delta in change_set.deltas:
                if isinstance(delta, WholeRecordChange):
                    for saved_form in (delta.before, delta.after):
                        version = type(delta.record).restore(copy.deepcopy(saved_form['record']))
                        version.set_file_paths(copy.deepcopy(saved_form['files']))
                        kept = kept_paths(version)
                        if kept:
                            saved_form['files'] = kept
        for resource in self._resources():
            kept = kept_paths(resource)
            if kept:
                resource.set_file_paths(kept)
        # The resources' files are the same, in another place, which is not an edit
        self.rebaseline()

    def _resources(self) -> List[WithResources]:
        """Every resource in a catalog, or that undo or redo can put back in one"""
        states = [state for _, state in self._catalogs.values()]
        for change_set in self._undo + self._redo:
            for delta in change_set.deltas:
                if isinstance(delta, CatalogChange):
                    states += [delta.before, delta.after]
        resources = {}
        for state in states:
            for member in state.members:
                if isinstance(member, WithResources) and member.path_fields:
                    resources[id(member)] = member
        return list(resources.values())

    # === Internals ===
    def _push(self, change_set: ChangeSet) -> None:
        self._undo.append(change_set)
        del self._undo[:-MAX_CHANGE_SETS]
        self._redo.clear()

    def _collect(self, change_set: ChangeSet) -> None:
        recorded = set()
        for bindings, key in self._all_bound():
            data, record, baseline = bindings[key]
            # Copied only once it differs: most records are unchanged, and a level is big
            form = saved_form(record)
            if form != baseline:
                now = copy.deepcopy(form)
                if key not in recorded:  # Two owners may show the same record
                    change_set.deltas.append(record_change(data, record, baseline, now))
                    recorded.add(key)
                bindings[key] = (data, record, now)
        for key, (data, state) in list(self._catalogs.items()):
            now = CatalogState.of(data)
            if not now.same_as(state):
                change_set.deltas.append(CatalogChange(data, state, now))
                self._catalogs[key] = (data, now)
        grid = self.db.mcost.save()
        if grid != self._grid:
            change_set.deltas.append(GridChange(self.db.mcost, self._grid, grid))
            self._grid = grid

    def rebaseline(self) -> None:
        """Takes everything as it is now as the starting point of the next edit, without
        recording what changed since the last commit"""
        for bindings, key in self._all_bound():
            data, record, _ = bindings[key]
            bindings[key] = (data, record, saved(record))
        for key, (data, _) in list(self._catalogs.items()):
            self._catalogs[key] = (data, CatalogState.of(data))
        self._grid = self.db.mcost.save()
        if CHECK_UNRECORDED:
            self._shadow = self._saved_records()

    def _saved_records(self) -> Dict[int, dict]:
        return {id(record): saved(record) for data in self.watched_catalogs() for record in data}

    def _check_unrecorded(self, change_set: ChangeSet) -> None:
        recorded = {id(delta.record) for delta in change_set.deltas
                    if isinstance(delta, (RecordChange, WholeRecordChange))}
        now = self._saved_records()
        for data in self.watched_catalogs():
            for record in data:
                key = id(record)
                if key in self._shadow and key not in recorded and now[key] != self._shadow[key]:
                    logging.warning("LT_EDITOR_CHECK: %s %s changed without being recorded",
                                    type(record).__name__, record.nid)
        self._shadow = now


class EditSession:
    """The undo steps of a modal editor, like the tilemap editor, from when it opens.
    Its undo and redo stay within them, never taking back what was done before it
    opened in a window it blocks. Each step stays in the history once it closes."""
    def __init__(self, history: EditHistory):
        self.history = history
        self.opened = history.mark()
        self.undone: List[ChangeSet] = []  # The steps this session undid, which it may redo

    def undo(self) -> bool:
        """Undoes the session's last step, if it has one left. Returns whether it did."""
        self.history.commit()
        last = self.history.last_change()
        if last is None or last is self.opened:
            return False
        self.undone.append(self.history.undo())
        return True

    def redo(self) -> bool:
        """Redoes the step the session last undid, unless an edit since dropped it.
        Returns whether it did."""
        self.history.commit()
        if not self.undone or self.history.next_redo() is not self.undone[-1]:
            self.undone.clear()
            return False
        self.history.redo()
        self.undone.pop()
        return True


class _ChangeSetContext:
    def __init__(self, history: EditHistory, label: str, origin):
        self.history, self.label, self.origin = history, label, origin

    def __enter__(self):
        self.history.begin(self.label, self.origin)
        return self

    def __exit__(self, *exc):
        self.history.end()
        return False


class _ModifyingContext:
    def __init__(self, history: EditHistory, records: List[Tuple[Any, Data]]):
        self.history = history
        # A list the history doesn't watch, like a tilemap's layers, changes
        # along with its watched owner or not at all
        self.records = [(record, data) for record, data in records if history.is_watched(data)]

    def __enter__(self):
        self.history.begin()
        # A record an enclosing context already watches is recorded by it, from
        # before either began changing it. Recorded here too, undo would restore
        # the outer context's before and then this one's, which comes later
        watching = self.history._modifying
        self.before = [(record, data, saved(record)) for record, data in self.records if id(record) not in watching]
        watching.update(id(record) for record, _, _ in self.before)
        return self

    def __exit__(self, *exc):
        change_set = self.history._open[0]
        for record, data, before in self.before:
            self.history._modifying.discard(id(record))
            if self.history._is_bound(record):
                continue  # A bound record is diffed against its baseline when the set ends
            after = saved(record)
            if after != before:
                change_set.deltas.append(record_change(data, record, before, after))
        self.history.end()
        return False


# The editor's one history, of the one database it edits
HISTORY = EditHistory(DB, RESOURCES)
