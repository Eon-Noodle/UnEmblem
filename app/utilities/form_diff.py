"""
The parts of a record's saved form that changed, and the form with them put back.

Undo keeps only these parts, so a stroke on a big map keeps only the tiles it
painted. Shared by the editor's edit history and the map maker's.
"""
from __future__ import annotations

import copy
from typing import Any, Iterator, List, Tuple

ABSENT = object()  # Where a dict has no such key. Never copied, which would make another object

Where = Tuple[Any, ...]  # The keys and indices from a saved form down to one part of it
FormChange = Tuple[Where, Any, Any]  # Where, the part before, the part after

def form_changes(before, after, where: Where = ()) -> Iterator[FormChange]:
    """The smallest parts of a saved form that differ. Dicts are compared key by key
    and lists of one length item by item; anything else that differs is a part."""
    if before == after:
        return
    if type(before) is dict and type(after) is dict:
        for key in list(before) + [key for key in after if key not in before]:
            yield from form_changes(before.get(key, ABSENT), after.get(key, ABSENT), where + (key,))
    elif type(before) is list and type(after) is list and len(before) == len(after):
        for index, (part_before, part_after) in enumerate(zip(before, after)):
            yield from form_changes(part_before, part_after, where + (index,))
    else:
        yield where, before, after

def patched(form, changes: List[FormChange], side: int) -> Any:
    """form, a saved form of its own, with each changed part as it was before
    (side 1) or after (side 2)"""
    for change in changes:
        where, part = change[0], change[side]
        if not where:
            form = copy.deepcopy(part)
            continue
        parent = form
        for key in where[:-1]:
            parent = parent[key]
        if part is ABSENT:
            del parent[where[-1]]
        else:
            parent[where[-1]] = copy.deepcopy(part)
    return form
