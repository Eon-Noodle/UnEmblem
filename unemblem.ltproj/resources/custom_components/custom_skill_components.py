from __future__ import annotations

from app.data.database.components import ComponentType
from app.data.database.database import DB
from app.data.database.skill_components import SkillComponent, SkillTags

from app.engine import (action, banner, combat_calcs, engine, equations, evaluate,
                        image_mods, item_funcs, item_system, skill_system)
from app.engine.game_state import game
from app.engine.objects.unit import UnitObject
from app.engine.source_type import SourceType
from app.engine.combat import playback as pb
from app.engine.movement import movement_funcs

from app.utilities import utils, static_random
from app.utilities.enums import Strike

import logging

from app.engine.skill_components.advanced_components import get_proc_rate, get_weapon_filter
from app.engine.skill_components.charge_components import get_marks, DrainCharge
from app.engine.skill_components.combat2_components import get_pc_damage
from app.engine.skill_components.status_components import Regeneration, UpkeepDamage
from app.engine.skill_components.time_components import EndTime


class DoNothing(SkillComponent):
    nid = 'do_nothing'
    desc = 'does nothing'
    tag = SkillTags.CUSTOM

    expose = ComponentType.Int
    value = 1


class EventOnRemoveWithArgs(SkillComponent):
    nid = 'event_on_remove_with_args'
    desc = "Calls and sends custom args(e.g: 'arg1, value1, arg2, value2') to an event when removed"
    tag = SkillTags.TIME

    expose = ComponentType.NewMultipleOptions

    options = {
        'event_on_remove': ComponentType.Event,
        'extra_args': ComponentType.String
    }

    def __init__(self, value=None):
        self.value = value or {}

    def after_true_remove(self, unit, skill):
        event_prefab = DB.events.get_from_nid(self.value.get('event_on_remove'))
        extra_args = self.value.get('extra_args')
        if not (event_prefab and extra_args):
            return

        try:
            tokens = extra_args.split(',')
            args_dict = {tokens[i].strip() : evaluate.evaluate(tokens[i+1], unit, local_args={'skill': skill}) 
                            for i in range(0, len(tokens), 2)}

        except Exception as e:
            logging.error("Could not evaluate %s (%s)" % (extra_args, e))
            args_dict = None
            
        game.events.trigger_specific_event(event_prefab.nid, unit, local_args=args_dict)


class DrainChargeExpression(DrainCharge):
    nid = 'drain_charge_expression'
    desc = "Drain Charge. But total charge is given based on expression."
    expose = ComponentType.String

    def init(self, skill):
        pass

    def after_add(self, unit, skill):
        try:
            value = int(evaluate.evaluate(self.value, unit, local_args={'skill': skill}))
        except Exception as e:
            logging.error("Couldn't evaluate %s conditional (%s)", self.value, e)
            value = 1
        self.skill.data['charge'] = value
        self.skill.data['total_charge'] = value


class RegenerationPlus(Regeneration):
    tag = SkillTags.CUSTOM

    def __init__(self, value=None):
        super().__init__(value)
        self.desc += ". Won't work on unit with HealBlock tag."
    
    def on_upkeep(self, actions, playback, unit):
        if 'HealBlock' in unit.tags:
            return
        super().on_upkeep(actions, playback, unit)
        skill_system.after_take_strike(actions, playback, unit, None, None, None, 'defense', (0, 0), Strike.HIT)


class TrueMiracleGiveStatus(SkillComponent):
    nid = 'true_miracle_give_status'
    desc = "Unit survives on 1 hp and gain status"
    tag = SkillTags.COMBAT2

    expose = ComponentType.Skill

    def after_take_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        did_something = False
        for act in reversed(actions):
            if isinstance(act, action.ChangeHP) and -act.num >= act.old_hp and act.unit == unit:
                act.num = -act.old_hp + 1
                did_something = True
                playback.append(pb.DefenseHitProc(unit, self.skill))

        if did_something:
            action.do(action.AddSkill(unit, self.value))
            actions.append(action.TriggerCharge(unit, self.skill))


class EnemyPass(SkillComponent):
    nid = 'enemy_pass'
    desc = "Enemies can move through this unit"
    tag = SkillTags.MOVEMENT

    author = 'beccarte'

    def enemy_pass_through(self, unit):
        return True


class UpkeepDamageInSync(UpkeepDamage):
    nid = 'upkeep_damage_in_sync'
    desc = "Units taking damage at upkeep at same time"

    def _playback_processing(self, playback, unit, hp_change):
        # Adding playback will make the engine process one unit at a time
        # so we add dmg number directly instead
        unit.sprite.add_damage_number(hp_change)


class Spread(SkillComponent):
    nid = 'spread'
    desc = "Nearby allies received this skill at upkeep"
    tag = SkillTags.STATUS

    expose = ComponentType.Shape

    def init(self, skill):
        skill.data['created_turn'] = game.turncount

    def condition(self, unit, item) -> bool:
        return self.skill.data.get('created_turn') != game.turncount

    def on_upkeep(self, actions, playback, unit):
        if not unit.position:
            return
        for relative_pos in self.value:
            pos = utils.tuple_add(unit.position, relative_pos)
            if not game.board.check_bounds(pos):
                continue
            ally = game.board.get_unit(pos)
            if ally and skill_system.check_ally(unit, ally) \
                    and not ally.get_skill(self.skill.nid):
                actions.append(action.AddSkill(ally, self.skill.nid, unit))
                actions.append(action.TriggerCharge(unit, self.skill))


class ImmunityCheck(SkillComponent):
    nid = 'immunity_check'
    desc = "Skill does not work if unit has immunity."
    tag = SkillTags.ATTRIBUTE

    expose = (ComponentType.List, ComponentType.Tag)

    def condition(self, unit, item):
        for skill in unit.skills[:]:
            for component in skill.components:
                if component.nid == 'immunity' and \
                        set(component.value) & set(self.value):
                    return False
        return True


class Immunity(SkillComponent):
    nid = 'immunity'
    desc = "Unit is immune to skills with `ImmunityCheck`"
    tag = SkillTags.ATTRIBUTE

    expose = (ComponentType.List, ComponentType.Tag)

    def after_gain_skill(self, unit, other_skill):
        if not (unit.get_skill(other_skill) and \
                skill_system.condition(self.skill, unit)):
            return
        for component in other_skill.components:
            if component.nid == 'immunity_check' and \
                    set(component.value) & set(self.value):
                action.do(action.RemoveSkill(unit, other_skill))


class CannotUseItemsExcept(SkillComponent):
    nid = 'cannot_use_items_except'
    desc = "Unit cannot use or equip any items except the listed items"
    tag = SkillTags.BASE

    expose = (ComponentType.List, ComponentType.Item)

    def available(self, unit, item) -> bool:
        return item.nid in self.value


class CannotUseCurrentItem(SkillComponent):
    nid = 'cannot_use_current_item'
    desc = "Unit cannot use the item that was equipped at the moment of gaining this skill"
    tag = SkillTags.BASE

    def after_add(self, unit, skill):
        if item := unit.get_weapon():
            self.value = item.nid
            skill.data['disabled_weapon'] = item.name

    def available(self, unit, item) -> bool:
        return item.nid != self.value


class Shield(SkillComponent):
    nid = 'shield'
    desc = "Equipped weapon lost one use after combat if unit took strike"
    tag = SkillTags.COMBAT2

    def init(self, skill):
        self._did_something = False

    def after_take_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        self._did_something = True

    def cleanup_combat(self, playback, unit, item, target, item2, mode):
        if not self._did_something:
            return

        self._did_something = False
        did_something = False
        if not item:
            return

        # Handles Uses
        if item.data.get('uses', None):
            did_something = True
            action.do(action.SetObjData(item, 'uses', item.data['uses'] - 1))

        # Handles Chapter Uses
        if item.data.get('c_uses', None):
            did_something = True
            action.do(action.SetObjData(item, 'c_uses', item.data['c_uses'] - 1))

        if did_something:
            action.do(action.UpdateRecords('item_use', (unit.nid, item.nid)))


class EvalEndTime(EndTime):
    nid = 'eval_end_time'
    desc = "Lasts for X turns solved using evaluate (checked on endstep)"
    tag = SkillTags.TIME

    expose = ComponentType.String

    def init(self, skill):
        eval_int = 0
        try:
            eval_int = int(evaluate.evaluate(self.value, local_args={'skill': self.skill}))
        except Exception as e:
            logging.error("Couldn't evaluate %s conditional (%s)", self.value, e)

        self.skill.data['turns'] = eval_int
        self.skill.data['starting_turns'] = eval_int


class IncDamageOnHit(SkillComponent):
    nid = 'inc_damage_on_hit'
    desc = "Damage increases by **amount** permanently, for each attack on units of listed classes."
    paired_with = ('damage',)
    tag = SkillTags.COMBAT

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

    def after_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        if not target or target.klass not in self.value.get('class', []) or not self.skill:
            return

        for p in playback:
            if p.nid in ('mark_hit', 'mark_crit') and p.attacker == unit:
                prefab = DB.skills.get(self.skill.nid)
                if prefab.components.get('damage'):
                    prefab.damage.value += self.value.get('amount', 1)
                    self.skill.damage.value += self.value.get('amount', 1)
                return
