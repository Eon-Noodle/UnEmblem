'''
Plays the Prologue of the sample project, default.ltproj, through the real
engine: its intro, both turns, every event it triggers and the win. What
breaks the engine broadly, or breaks the sample project, breaks this first
'''
from app.tests.engine_harness import EngineHarness, diff_saves, logged_errors_fail
from app.tests.test_turnwheel import TurnwheelTestCase

PROJECT = 'default.ltproj'
# The Prologue: Eirika (4, 5) and Seth (4, 4), Seth already hurt by the
# intro, against the fighters 101 (9, 6) and 102 (8, 6), and O'Neill, the boss,
# guarding (10, 8)
LEVEL = '0'

def play_turn_1(harness: EngineHarness):
    '''
    The intro plays, Seth kills 102, Eirika waits, and in the enemy phase 101
    attacks Seth and dies, which leaves O'Neill alone
    '''
    harness.start_level(LEVEL)
    harness.run_until_state('free', 5000)
    harness.attack('Seth', (8, 5), 5000)
    harness.wait('Eirika', (6, 5))
    harness.run_until_player_turn(2, 10000)

def defeat_oneill(harness: EngineHarness):
    '''
    Seth fights O'Neill, who speaks, and kills him: the level is won, its
    outro plays, and the game asks to save before the next chapter
    '''
    harness.move_unit('Seth', (10, 7))
    harness.choose('Attack')
    harness.run_until_state('weapon_choice')
    harness.press('SELECT')
    harness.run_until_state('combat_targeting')
    harness.press('SELECT')
    harness.run_until_state('title_save', 10000)

class DefaultProjectTests(TurnwheelTestCase):
    project = PROJECT

    def setUp(self):
        super().setUp()
        self.harness.click_through_events = True

    def test_the_prologue_plays_to_its_end(self):
        with logged_errors_fail():
            play_turn_1(self.harness)
            self.assertEqual(["O'Neill"], [unit.nid for unit in self.harness.game.get_enemy_units()])
            defeat_oneill(self.harness)
        self.assertTrue(self.harness.game.get_unit("O'Neill").dead)

    def test_a_loaded_game_plays_out_the_same(self):
        '''A save after Seth's first combat, loaded straight back, changes nothing that follows'''
        with logged_errors_fail():
            play_turn_1(self.harness)
            straight_through, _ = self.harness.game.save()

            self.harness.start_level(LEVEL)
            self.harness.run_until_state('free', 5000)
            self.harness.attack('Seth', (8, 5), 5000)
            self.harness.round_trip()
            self.harness.run_until_state('free')
            self.harness.wait('Eirika', (6, 5))
            self.harness.run_until_player_turn(2, 10000)
            with_a_load, _ = self.harness.game.save()

            for s_dict in (straight_through, with_a_load):
                # Counts frames, and the cursor walks a different route after a load
                del s_dict['playtime']
                # FreeState.begin marks the end of an action group every time it
                # begins, and it begins again on load
                del s_dict['action_log']
            self.assertEqual([], diff_saves(straight_through, with_a_load))
            defeat_oneill(self.harness)

    def test_the_turnwheel_runs_back_through_the_first_turn(self):
        with logged_errors_fail():
            self.assertTurnwheelUndoesAndRedoes(lambda: play_turn_1(self.harness))
