import unittest

from app.data.database.database import DB
from app.engine import action, unit_funcs
from app.engine.game_state import game
from app.tests.engine_harness import EngineTestCase


class WexpRankBannerTests(EngineTestCase):
    '''
    A unit tells of reaching a weapon rank only in a weapon type it can use: a class
    may gain weapon experience in a type it cannot use, for a skill that lets it
    '''

    def rank_up(self, weapon_type: str) -> list:
        unit = game.get_unit('Eirika')
        alerts_before = len(game.alerts)
        action.do(action.AddWexp(unit, weapon_type, DB.weapon_ranks[0].requirement))
        return game.alerts[alerts_before:]

    def test_a_rank_in_a_usable_weapon_type_shows_a_banner(self):
        harness = self.start_harness()
        harness.start_level('0')
        harness.run_until_state('free')
        unit = game.get_unit('Eirika')
        usable = sorted(unit_funcs.usable_wtypes(unit))[0]
        unit.wexp[usable] = 0
        self.assertEqual(1, len(self.rank_up(usable)))

    def test_a_rank_in_an_unusable_weapon_type_shows_no_banner(self):
        harness = self.start_harness()
        harness.start_level('0')
        harness.run_until_state('free')
        unit = game.get_unit('Eirika')
        unusable = next(nid for nid in DB.weapons.keys() if nid not in unit_funcs.usable_wtypes(unit))
        unit.wexp[unusable] = 0
        self.assertEqual([], self.rank_up(unusable))
        self.assertEqual(DB.weapon_ranks[0].requirement, unit.wexp[unusable])


if __name__ == '__main__':
    unittest.main()
