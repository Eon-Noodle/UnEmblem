from __future__ import annotations

from app.data.database.components import ComponentType
from app.data.database.database import DB
from app.data.database.item_components import ItemComponent, ItemTags
from app.engine import (action, banner, combat_calcs, engine, equations,
                        image_mods, item_funcs, item_system, skill_system)
from app.engine.game_state import game
from app.engine.objects.unit import UnitObject
from app.utilities import utils, static_random

from app.engine.item_components.utility_components import Heal, EquationHeal

class DoNothing(ItemComponent):
    nid = 'do_nothing'
    desc = 'does nothing'
    tag = ItemTags.CUSTOM

    expose = ComponentType.Int
    value = 1

class HealPlus(Heal):
    tag = ItemTags.CUSTOM

    def __init__(self, value=None):
        super().__init__(value)
        self.desc += ". Won't work on unit with HealBlock tag."

    def target_restrict(self, unit, item, def_pos, splash) -> bool:
        # Restricts target based on whether any unit has < full hp
        defender = game.board.get_unit(def_pos)
        if defender and defender.get_hp() < defender.get_max_hp() and 'HealBlock' not in defender.tags:
            return True
        for s_pos in splash:
            s = game.board.get_unit(s_pos)
            if s and s.get_hp() < s.get_max_hp() and 'HealBlock' not in s.tags:
                return True
        return False

    def ai_priority(self, unit, item, target, move):
        if 'HealBlock' in target.tags:
            return 0
        super().ai_priority(unit, item, target, move)

class EquationHealPlus(EquationHeal, HealPlus):
    tag = ItemTags.CUSTOM

class IncDamageOnHit(ItemComponent):
    nid = 'inc_damage_on_hit'
    desc = "Damage of item increases by **amount** permanently, for each time it lands a hit on units of listed classes."
    tag = ItemTags.SPECIAL

    expose = ComponentType.NewMultipleOptions
    options = {
        'amount': ComponentType.Int,
        'class': (ComponentType.List, ComponentType.Class)
    }

    def __init__(self, value=None):
        self.value = {
            'amount': 1,
            'class': []
        }
        if value and isinstance(value, dict):
            self.value.update(value)

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        if target.klass not in self.value.get('class', []):
            return
        prefab = DB.items.get(item.nid)
        if prefab.components.get('damage'):
            prefab.damage.value += self.value.get('amount', 1)
            item.damage.value += self.value.get('amount', 1)