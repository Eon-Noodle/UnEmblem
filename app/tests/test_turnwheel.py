from __future__ import annotations

import pickle
import unittest
from typing import Any, Callable
from unittest.mock import patch

from app.engine import action
from app.engine.game_state import GameState
from app.engine.turnwheel import ActionLog
from app.tests.engine_harness import EngineTestCase
from app.tests.test_save_round_trip import finish_turn_1, play_first_combat

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
# runs through, playtime counts frames, and the state stack belongs to the
# turnwheel while it runs
UNSNAPSHOTTED = ('action_log', 'playtime', 'state')
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

def snapshot(game: GameState) -> dict[str, Any]:
    s_dict, _ = game.save()
    # A save shares objects with the game, which goes on changing them
    s_dict = pickle.loads(pickle.dumps(s_dict))
    for key in UNSNAPSHOTTED:
        del s_dict[key]
    return flatten(s_dict)

def changed_paths(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    return {path for path in before.keys() | after.keys() if before.get(path, ABSENT) != after.get(path, ABSENT)}

def ignored(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == prefix or path.startswith(prefix + '/') or path.startswith(prefix + '#') for prefix in prefixes)

class RecordedPlay():
    '''
    Plays through part of a level, snapshotting the game before each action the
    log records. Whatever changes between one action and the next counts as
    part of the first: a unit's Move ends when it arrives, frames after Move.do
    '''

    def __init__(self, game: GameState, play: Callable[[], None]):
        self.game = game
        befores: dict[int, dict[str, Any]] = {}

        def snapshotting(run: Callable[[action.Action], None]) -> Callable[[action.Action], None]:
            def wrapper(act: action.Action):
                if game.action_log.is_recording() and game.action_log.action_depth == 0:
                    befores[id(act)] = snapshot(game)
                run(act)
            return wrapper

        with patch.object(action, 'do', snapshotting(action.do)),                 patch.object(action, 'execute', snapshotting(action.execute)):
            play()
        self.final = snapshot(game)

        actions = game.action_log.actions
        self.before = {id(act): befores[id(act)] for act in actions}
        self.after = {id(act): befores[id(actions[idx + 1])] for idx, act in enumerate(actions[:-1])}
        self.after[id(actions[-1])] = self.final

class TurnwheelPlayTests(EngineTestCase):
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
            act = log.run_action_backward()
            problems = self.problems(start, snapshot(game), played.after[id(act)], played.before[id(act)])
            failures += ['reversing %s (or what changed after it, before the next action), %s' % (act.__class__.__name__, problem) for problem in problems]
        first_free = played.before[id(log.actions[log.action_index + 1])]
        failures += ['back at the first free action, %s differs' % path
                     for path in changed_paths(first_free, snapshot(game)) if not ignored(path, DELIBERATELY_KEPT)]

        while not log.at_far_future():
            start = snapshot(game)
            act = log.run_action_forward()
            problems = self.problems(start, snapshot(game), played.before[id(act)], played.after[id(act)])
            failures += ['executing %s (or what changed after it, before the next action), %s' % (act.__class__.__name__, problem) for problem in problems]
        failures += ['forward again at the end, %s differs' % path
                     for path in changed_paths(played.final, snapshot(game)) if not ignored(path, DELIBERATELY_KEPT)]

        self.assertEqual([], failures)

    def test_combat_and_enemy_phase(self):
        '''Seth kills a fighter, Eirika waits, and the enemy phase plays out'''
        def play():
            play_first_combat(self.harness)
            finish_turn_1(self.harness)
        self.assertTurnwheelUndoesAndRedoes(play)
