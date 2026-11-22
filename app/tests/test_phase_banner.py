import unittest

from app.constants import WINHEIGHT, WINWIDTH
from app.data.database.database import DB
from app.data.database.teams import Team
from app.engine import engine
from app.engine.game_state import game
from app.engine.objects.team import TeamObject
from app.engine.phase import PhaseIn
from app.engine.sprites import SPRITES
from app.tests.engine_harness import EngineTestCase


class PhaseBannerTests(EngineTestCase):
    def setUp(self):
        super().setUp()
        game.teams = {team.nid: TeamObject.from_prefab(team) for team in DB.teams}

    def add_team(self, nid: str, combat_color: str) -> None:
        team = Team(nid, combat_color=combat_color)
        DB.teams.append(team)
        game.teams[nid] = TeamObject.from_prefab(team)

    def begin(self, nid: str) -> PhaseIn:
        phase_in = PhaseIn(nid)
        phase_in.begin()
        return phase_in

    def test_a_team_shows_its_banner_in_its_combat_color(self):
        game.teams['enemy'].combat_color = 'green'

        self.assertIs(SPRITES.get('turnbanner_enemy_green'), self.begin('enemy').image)

    def test_a_team_with_no_banner_in_its_color_shows_its_uncolored_banner(self):
        game.teams['enemy'].combat_color = 'no_such_color'

        self.assertIs(SPRITES.get('turnbanner_enemy'), self.begin('enemy').image)

    def test_a_team_with_no_banner_of_its_own_shows_the_other_teams_banner(self):
        self.add_team('rebels', 'blue')

        phase_in = self.begin('rebels')

        self.assertIs(SPRITES.get('turnbanner_other_blue'), phase_in.image)
        phase_in.draw(engine.create_surface((WINWIDTH, WINHEIGHT)))

    def test_a_team_with_no_banner_and_an_unknown_color_shows_the_uncolored_other_banner(self):
        self.add_team('rebels', 'no_such_color')

        self.assertIs(SPRITES.get('turnbanner_other'), self.begin('rebels').image)


if __name__ == '__main__':
    unittest.main()
