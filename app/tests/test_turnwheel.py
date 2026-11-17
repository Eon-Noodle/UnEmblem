from __future__ import annotations

import pickle
import unittest
from typing import Any, Callable
from unittest.mock import patch

from app.engine import action
from app.engine.game_state import GameState
from app.engine.turnwheel import ActionLog
from app.tests.engine_harness import EngineTestCase, logged_errors_fail
from app.tests.test_save_round_trip import LEVEL, finish_turn_1, play_first_combat

class TurnwheelTests(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_get_action_groups(self):
        # Null Case
        no_action_groups = ActionLog.get_action_groups([], 0)
        self.assertEqual(0, len(no_action_groups))

        # Simple Case w/ Extra
        actions = [
            action.MarkActionGroupStart("Eirika", "free"),
            action.Action(),  # Mock
            action.MarkActionGroupEnd("free"),
            action.Action(),  # Mock
        ]
        action_groups = ActionLog.get_action_groups(actions, 0)
        self.assertEqual(2, len(action_groups))
        self.assertTrue(type(action_groups[0]) == ActionLog.Move)
        self.assertEqual(0, action_groups[0].begin)
        self.assertEqual(2, action_groups[0].end)
        self.assertTrue(type(action_groups[1]) == ActionLog.Extra)
        self.assertEqual(3, action_groups[1].last_move_index)
        self.assertEqual(3, action_groups[1].action_index)

        # Case with 2 mark action begins and ends
        actions = [
            action.MarkActionGroupStart("Eirika", "free"),
            action.Action(),  # Mock
            action.Action(),  # Mock
            action.Action(),  # Mock
            action.MarkActionGroupEnd("free"),
            action.Action(),  # Mock
            action.MarkActionGroupStart("Franz", "free"),
            action.Action(),  # Mock
            action.Action(),  # Mock
            action.MarkActionGroupEnd("free"),
        ]
        action_groups = ActionLog.get_action_groups(actions, 0)
        self.assertEqual(2, len(action_groups))
        self.assertTrue(type(action_groups[0]) == ActionLog.Move)
        self.assertEqual(0, action_groups[0].begin)
        self.assertEqual(4, action_groups[0].end)
        self.assertTrue(type(action_groups[1]) == ActionLog.Move)
        self.assertEqual(6, action_groups[1].begin)
        self.assertEqual(9, action_groups[1].end)

        # Case with MarkPhase
        # Case with 2 mark action begins and ends and a mark phase
        actions = [
            action.MarkActionGroupStart("102", "ai"),
            action.Action(),  # Mock
            action.MarkActionGroupEnd("ai"),
            action.MarkPhase('player'),
            action.MarkActionGroupStart("Eirika", "free"),
            action.Action(),  # Mock
            action.MarkActionGroupEnd("free"),
        ]
        action_groups = ActionLog.get_action_groups(actions, 0)
        self.assertEqual(3, len(action_groups))
        self.assertTrue(type(action_groups[0]) == ActionLog.Move)
        self.assertEqual(0, action_groups[0].begin)
        self.assertEqual(2, action_groups[0].end)
        self.assertTrue(type(action_groups[1]) == ActionLog.Phase)
        self.assertEqual(3, action_groups[1].action_index)
        self.assertTrue(type(action_groups[2]) == ActionLog.Move)
        self.assertEqual(4, action_groups[2].begin)
        self.assertEqual(6, action_groups[2].end)

        # Case with nonzero first free action
        actions = [
            action.MarkActionGroupStart("Eirika", "free"),
            action.Action(),  # Mock
            action.Action(),  # Mock
            action.Action(),  # Mock
            action.MarkActionGroupEnd("free"),
            action.Action(),  # Mock
            action.MarkActionGroupStart("Franz", "free"),
            action.Action(),  # Mock
            action.Action(),  # Mock
            action.MarkActionGroupEnd("free"),
        ]
        action_groups = ActionLog.get_action_groups(actions, 6)
        self.assertEqual(1, len(action_groups))
        self.assertTrue(type(action_groups[0]) == ActionLog.Move)
        self.assertEqual(6, action_groups[0].begin)
        self.assertEqual(9, action_groups[0].end)

# What a snapshot leaves out of the save: the action log is what the turnwheel
# runs through, playtime counts frames, the state stack belongs to the
# turnwheel while it runs, the turnwheel never runs during an event (whose
# local args are proxies resolved against the events running now), and the
# terrain status registry keeps the skill each tile's terrain gives, made the
# first time a unit stands there and reused after (whether a unit holds one
# is in its skills)
UNSNAPSHOTTED = ('action_log', 'playtime', 'state', 'events', 'terrain_status_registry')
# Die.reverse remembers who came back to life, for the turnwheel to tell
DELIBERATELY_KEPT = ('/level_vars/_resurrect',
                     # Hybrid fog remembers the tiles a unit uncovered: the player
                     # has seen them, whichever way time runs
                     '/fog_state',
                     )
# Combat draws from the random number generator between actions, and the
# RecordRandomState at the end of each combat restores it, so only a full turn
# of the wheel checks it
WHOLE_LOG_ONLY = ('/current_random_state',)

ABSENT = '<absent>'

def flatten(value: Any, path: str = '', out: dict[str, Any] | None = None) -> dict[str, Any]:
    '''Every leaf of a save, by its path, with each list's length beside its items'''
    out = {} if out is None else out
    if isinstance(value, dict):
        for key, sub_value in value.items():
            flatten(sub_value, '%s/%s' % (path, key), out)
    elif isinstance(value, (list, tuple)):
        out[path + '#len'] = len(value)
        for idx, sub_value in enumerate(value):
            flatten(sub_value, '%s/%d' % (path, idx), out)
    else:
        out[path] = value
    return out

def held_objects(s_dict: dict[str, Any]) -> None:
    '''
    Keys the save's units by nid and its items, skills and regions by uid and
    nid, so an object keeps its path whatever comes before it, and keeps only
    the items and skills a unit or a convoy holds and the regions the level
    holds. An item, skill or region stays in the game's registry once made,
    held or not, for the turnwheel to give back when it runs forward again;
    one nothing holds is no part of the game. (An ability item, such as
    Steal's, belongs to its skill, and keeps only its targeting between uses)
    '''
    held_items = {uid for unit in s_dict['units'] for uid in unit['items']} | \
        {uid for party in s_dict['parties'] for uid in party['convoy']}
    items = {item['uid']: item for item in s_dict['items']}
    for uid in list(held_items):
        held_items |= set(items[uid]['subitems'])
    s_dict['items'] = {uid: item for uid, item in items.items() if uid in held_items}
    held_skills = {uid for unit in s_dict['units'] for uid, _source, _source_type in unit['skills']}
    s_dict['skills'] = {skill['uid']: skill for skill in s_dict['skills'] if skill['uid'] in held_skills}
    s_dict['units'] = {unit['nid']: unit for unit in s_dict['units']}
    held_regions = set(s_dict['level']['regions'])
    s_dict['regions'] = {region['nid']: region for region in s_dict['regions'] if region['nid'] in held_regions}

def snapshot(game: GameState) -> dict[str, Any]:
    s_dict, _ = game.save()
    # A save shares objects with the game, which goes on changing them
    s_dict = pickle.loads(pickle.dumps(s_dict))
    for key in UNSNAPSHOTTED:
        del s_dict[key]
    held_objects(s_dict)
    return flatten(s_dict)

def changed_paths(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    return {path for path in before.keys() | after.keys() if before.get(path, ABSENT) != after.get(path, ABSENT)}

def ignored(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == prefix or path.startswith(prefix + '/') or path.startswith(prefix + '#') for prefix in prefixes)

class RecordedPlay():
    '''
    Plays through part of a level, snapshotting the game before each action the
    log records, by its place in the log: a save loaded partway restores the
    log with new actions in the same places. Whatever changes between one
    action and the next counts as part of the first: a unit's Move ends when it
    arrives, frames after Move.do
    '''

    def __init__(self, game: GameState, play: Callable[[], None]):
        befores: dict[int, dict[str, Any]] = {}

        def snapshotting(run: Callable[[action.Action], None]) -> Callable[[action.Action], None]:
            def wrapper(act: action.Action):
                log = game.action_log
                top = log.is_recording() and log.action_depth == 0
                before = snapshot(game) if top else None
                place = len(log.actions)
                run(act)
                if top and len(log.actions) > place and log.actions[place] is act:
                    befores[place] = before
            return wrapper

        with patch.object(action, 'do', snapshotting(action.do)),                 patch.object(action, 'execute', snapshotting(action.execute)):
            play()
        final = snapshot(game)

        count = len(game.action_log.actions)
        self.before = [befores[idx] for idx in range(count)]
        self.after = self.before[1:] + [final]

    @property
    def final(self) -> dict[str, Any]:
        return self.after[-1]

class TurnwheelTestCase(EngineTestCase):
    '''
    Every action the turnwheel runs back must undo just what it did, and every
    action it runs forward again must redo just that. Each action is checked
    on its own: the state before it, with what it changed put back, and
    nothing else touched, so one bad reverse fails as itself and not as every
    action after it
    '''

    def setUp(self):
        super().setUp()
        self.harness = self.start_harness()

    def problems(self, start: dict[str, Any], now: dict[str, Any],
                 expect_from: dict[str, Any], expect_to: dict[str, Any]) -> list[str]:
        '''Where now isn't start with the change from expect_from to expect_to made to it'''
        delta = changed_paths(expect_from, expect_to)
        problems = []
        for path in sorted(start.keys() | now.keys()):
            if ignored(path, DELIBERATELY_KEPT + WHOLE_LOG_ONLY):
                continue
            want = expect_to.get(path, ABSENT) if path in delta else start.get(path, ABSENT)
            got = now.get(path, ABSENT)
            if want != got:
                problems.append('%s: should be %r, is %r' % (path, want, got))
        return problems

    def assertTurnwheelUndoesAndRedoes(self, play: Callable[[], None]):
        game = self.harness.game
        played = RecordedPlay(game, play)
        log = game.action_log
        # As the turnwheel does while it runs
        log.stop_recording()
        failures = []

        while not log.at_far_past():
            start = snapshot(game)
            idx = log.action_index
            act = log.run_action_backward()
            problems = self.problems(start, snapshot(game), played.after[idx], played.before[idx])
            failures += ['reversing %s (or what changed after it, before the next action), %s' % (act.__class__.__name__, problem) for problem in problems]
        first_free = played.before[log.action_index + 1]
        failures += ['back at the first free action, %s differs' % path
                     for path in changed_paths(first_free, snapshot(game)) if not ignored(path, DELIBERATELY_KEPT)]

        while not log.at_far_future():
            start = snapshot(game)
            act = log.run_action_forward()
            idx = log.action_index
            problems = self.problems(start, snapshot(game), played.before[idx], played.after[idx])
            failures += ['executing %s (or what changed after it, before the next action), %s' % (act.__class__.__name__, problem) for problem in problems]
        failures += ['forward again at the end, %s differs' % path
                     for path in changed_paths(played.final, snapshot(game)) if not ignored(path, DELIBERATELY_KEPT)]

        self.assertEqual([], failures)

class TurnwheelPlayTests(TurnwheelTestCase):
    '''The turnwheel through each kind of action testing_proj's level 0 can play'''

    def test_combat_and_enemy_phase(self):
        '''Seth kills a fighter, Eirika waits, and the enemy phase plays out'''
        def play():
            play_first_combat(self.harness)
            finish_turn_1(self.harness)
        self.assertTurnwheelUndoesAndRedoes(play)

    def test_event_then_steal(self):
        '''
        An event changes items, vars, money, hp and skills, and Eirika steals
        the Vulnerary it gave fighter 102
        '''
        def play():
            self.harness.start_level(LEVEL)
            self.harness.run_until_state('free')
            self.harness.run_event('\n'.join([
                'give_item;102;Vulnerary;no_banner',
                'game_var;Gathered;5',
                'level_var;Seen;True',
                'give_money;300;no_banner',
                'set_current_hp;Seth;20',
                'give_skill;Eirika;Canto;no_banner',
                'remove_skill;Seth;Inspiration;no_banner',
            ]))
            self.harness.move_unit('Eirika', (8, 5))
            self.harness.choose('Steal')
            self.harness.run_until_state('combat_targeting')
            self.harness.press('SELECT')
            self.harness.run_until_state('item_targeting')
            self.harness.press('SELECT')
            self.harness.run_until_state('free', 2000)
        self.assertTurnwheelUndoesAndRedoes(play)
        self.assertEqual(['Iron_Axe'], [item.nid for item in self.harness.game.get_unit('102').items])

    def test_trade(self):
        '''Eirika hands Seth her Vulnerary, then waits'''
        def play():
            self.harness.start_level(LEVEL)
            self.harness.run_until_state('free')
            # Seth stands beside her
            self.harness.move_unit('Eirika', (4, 5))
            self.harness.choose('Trade')
            self.harness.run_until_state('targeting')
            self.harness.press('SELECT')
            self.harness.run_until_state('trade')
            # Her Vulnerary, to Seth's empty slot
            self.harness.press('SELECT')
            self.harness.press('RIGHT')
            self.harness.press('SELECT')
            self.harness.press('BACK')
            self.harness.run_until_state('menu')
            self.harness.choose('Wait')
            self.harness.run_until_state('free')
        self.assertTurnwheelUndoesAndRedoes(play)
        self.assertEqual(['Steel_Sword', 'Silver_Lance', 'Vulnerary', 'Vulnerary'],
                         [item.nid for item in self.harness.game.get_unit('Seth').items])

    def test_item_use(self):
        '''Eirika, hurt by an event, drinks a Vulnerary'''
        def play():
            self.harness.start_level(LEVEL)
            self.harness.run_until_state('free')
            self.harness.run_event('set_current_hp;Eirika;5')
            self.harness.move_unit('Eirika', (4, 5))
            self.harness.choose('Item')
            self.harness.run_until_state('item')
            self.harness.choose(self.harness.game.get_unit('Eirika').items[0])
            self.harness.run_until_state('item_child')
            self.harness.choose('Use')
            self.harness.run_until_state('free', 2000)
        self.assertTurnwheelUndoesAndRedoes(play)
        self.assertEqual(15, self.harness.game.get_unit('Eirika').get_hp())

    def test_level_up(self):
        '''Seth, one experience point short, levels up killing a fighter'''
        def play():
            self.harness.start_level(LEVEL)
            self.harness.run_until_state('free')
            self.harness.run_event('set_exp;Seth;99')
            self.harness.attack('Seth', (8, 5), 5000)
        self.assertTurnwheelUndoesAndRedoes(play)
        self.assertEqual(2, self.harness.game.get_unit('Seth').level)

    def test_a_loaded_game_turns_back(self):
        '''
        An event takes Seth's Inspiration, the game is saved and loaded, and
        Eirika waits: the turnwheel then runs back through actions that came
        out of the save, which must point at the game's own objects
        '''
        def play():
            self.harness.start_level(LEVEL)
            self.harness.run_until_state('free')
            self.harness.run_event('remove_skill;Seth;Inspiration;no_banner')
            self.harness.round_trip()
            self.harness.run_until_state('free')
            self.harness.wait('Eirika', (4, 5))
            self.harness.run_until_state('free')
        self.assertTurnwheelUndoesAndRedoes(play)

    def play_event(self, *commands: str):
        self.harness.start_level(LEVEL)
        self.harness.run_until_state('free')
        self.harness.run_event('\n'.join(commands))

    def test_promotion_and_class_change(self):
        def play():
            self.harness.start_level(LEVEL)
            self.harness.run_until_state('free')
            with logged_errors_fail():
                self.harness.start_event('promote;Eirika\nchange_class;Seth;Cavalier;silent')
                # Promotion shows what Eirika learns, and waits for a press
                self.harness.run_until_state('alert', 2000)
                self.harness.press('SELECT')
                self.harness.run_until_state('free', 2000)
        self.assertTurnwheelUndoesAndRedoes(play)
        self.assertEqual('Eirika_Great_Lord', self.harness.game.get_unit('Eirika').klass)
        self.assertEqual('Cavalier', self.harness.game.get_unit('Seth').klass)

    def test_units_join_and_leave(self):
        self.assertTurnwheelUndoesAndRedoes(lambda: self.play_event(
            'load_unit;Franz',
            'add_unit;Franz;4,3;immediate',
            'make_generic;Grunt;Fighter;3;enemy',
            'add_unit;Grunt;3,3;immediate',
            "remove_unit;O'Neill;immediate",
            'kill_unit;101;immediate',
            'change_team;102;player',
            'move_unit;Seth;5,3;immediate',
        ))
        game = self.harness.game
        self.assertEqual((4, 3), game.get_unit('Franz').position)
        self.assertEqual((3, 3), game.get_unit('Grunt').position)
        self.assertIsNone(game.get_unit("O'Neill").position)
        self.assertTrue(game.get_unit('101').dead)
        self.assertEqual('player', game.get_unit('102').team)
        self.assertEqual((5, 3), game.get_unit('Seth').position)

    def test_unit_changes(self):
        self.assertTurnwheelUndoesAndRedoes(lambda: self.play_event(
            'set_stats;Seth;STR,3;immediate',
            'add_tag;Seth;Armor',
            'change_ai;101;Guard',
            'set_name;Seth;Sethy',
            'change_affinity;Seth;Fire',
            'autolevel_to;Eirika;5',
            'set_unit_field;Seth;foo;5',
        ))
        game = self.harness.game
        seth = game.get_unit('Seth')
        self.assertIn('Armor', seth.tags)
        self.assertEqual('Guard', game.get_unit('101').ai)
        self.assertEqual('Sethy', seth.name)
        self.assertEqual('Fire', seth.affinity)
        self.assertEqual(5, game.get_unit('Eirika').level)
        self.assertEqual(5, seth.get_field('foo'))

    def test_level_and_party_changes(self):
        self.assertTurnwheelUndoesAndRedoes(lambda: self.play_event(
            'add_region;Patch;5,3;1,1;normal',
            'add_lore;Prologue',
            'give_bexp;100;no_banner',
            'game_var;_convoy;True',
            'give_item;convoy;Vulnerary;no_banner',
        ))
        game = self.harness.game
        self.assertIsNotNone(game.get_region('Patch'))
        self.assertEqual(100, game.get_party().bexp)
        self.assertEqual(['Vulnerary'], [item.nid for item in game.get_party().convoy])
