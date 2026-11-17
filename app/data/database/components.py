from __future__ import annotations

import copy
from enum import Enum
from typing import Dict, List, Optional, Tuple

from app.utilities import str_utils
from app.utilities.data import Data

def saved_value(value):
    '''
    A component's value as a save holds it: a list, dict or set is deep
    copied, since the game can change it in place before the save is pickled,
    and a plain value, which nothing can change, goes as it is
    '''
    if isinstance(value, (list, dict, set)):
        return copy.deepcopy(value)
    return value

class ComponentType(Enum):
    Bool = 0
    Int = 1
    Float = 2
    String = 3
    WeaponType = 4  # Stored as Nids
    WeaponRank = 5  # Stored as Nids
    Unit = 6  # Stored as Nids
    Class = 7  # Stored as Nids
    Tag = 8
    Color3 = 9
    Color4 = 10
    Item = 12  # Stored as Nids
    Skill = 13  # Stored as Nids
    Stat = 14  # Stored as Nids
    MapAnimation = 15  # Stored as Nids
    Equation = 16  # Stored as Nids
    MovementType = 17  # Stored as Nid
    Sound = 18  # Stored as Nid
    AI = 19  # Stored as Nid
    Music = 20  # Stored as Nid
    CombatAnimation = 21  # Stored as Nid
    EffectAnimation = 22  # Stored as Nid
    Affinity = 23  # Stored as Nid
    Terrain = 24  # stored as Nid
    Lore = 25 # Lore entry stored as an NID
    Shape = 26 #List of lists of [x,y] coordinates
    StatFloat = 27 # Special handling for stat as float
    StatString = 28 # Special handling for stat as string
    TextColor = 29 # Stored as a text palette name for the default text font
    Event = 80
    List = 100  # List containing Items
    Dict = 101  # List of Tuples of [Item, integer]
    FloatDict = 102  # List of Tuples of [Item, float]
    MultipleChoice = 103  # item is a string value from a number of choices
    MultipleOptions = 104  # Deprecated
    StringDict = 105  # List of Tuples of [Item, str]
    NewMultipleOptions = 106  # item is a dict of string options with types that can be individually configured

def convert_type_from_string(tstr: str, ttype: ComponentType):
    if ttype == ComponentType.Int:
        return int(tstr)
    if ttype == ComponentType.Float:
        return float(tstr)
    else:
        return tstr


class Component():
    nid: str
    desc: str
    author: str = 'rainlash'
    expose: Optional[ComponentType] = None  # Attribute
    paired_with: list = []
    tag: Enum
    value = None

    def __init__(self, value=None):
        if value is not None:
            self.value = value

    @property
    def name(self):
        name = self.__class__.__name__
        return str_utils.ignore_numbers(str_utils.camel_case(name))

    @classmethod
    def class_name(cls):
        name = cls.__name__
        return str_utils.ignore_numbers(str_utils.camel_case(name))

    def defines(self, function_name):
        return hasattr(self, function_name)

    @classmethod
    def copy(cls, other):
        return cls(other.value)

    def save(self):
        if isinstance(self.value, Data):
            return self.nid, self.value.save()
        elif isinstance(self.value, list) or isinstance(self.value, dict):
            # Handle lists of lists or dictionaries with deepcopy
            return self.nid, copy.deepcopy(self.value)
        else:
            return self.nid, self.value

class ComponentData(Data[Component]):
    """
    The components of an item or a skill. Asked which of its components define a
    hook, it remembers the answer, so the item and skill systems need not ask
    each component on every call. Any change to the components forgets it all,
    since the answer depends on which components there are and their order
    """
    def __init__(self, vals: Optional[List[Component]] = None):
        super().__init__(vals)
        self._with_hooks: Dict[Tuple[str, ...], Tuple[Component, ...]] = {}

    def with_hook(self, *hook_names: str) -> Tuple[Component, ...]:
        """The components, in order, that define any of hook_names"""
        found = self._with_hooks.get(hook_names)
        if found is None:
            found = tuple(component for component in self._list
                          if any(component.defines(hook_name) for hook_name in hook_names))
            self._with_hooks[hook_names] = found
        return found

    def append(self, val: Component, overwrite: bool = False):
        super().append(val, overwrite)
        self._with_hooks.clear()

    def delete(self, val: Component):
        super().delete(val)
        self._with_hooks.clear()

    def remove_key(self, key: str):
        super().remove_key(key)
        self._with_hooks.clear()

    def pop(self, idx: Optional[int] = None):
        super().pop(idx)
        self._with_hooks.clear()

    def insert(self, idx: int, val: Component):
        super().insert(idx, val)
        self._with_hooks.clear()

    def clear(self):
        super().clear()
        self._with_hooks.clear()

    def move_index(self, old_index: int, new_index: int):
        super().move_index(old_index, new_index)
        self._with_hooks.clear()

    def sort(self, sort_func=None):
        super().sort(sort_func)
        self._with_hooks.clear()
