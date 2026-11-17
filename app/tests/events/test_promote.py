from app.tests.engine_harness import EngineTestCase

# testing_proj level 0: Eirika is an Eirika_Lord, who promotes to Eirika_Great_Lord
LEVEL = '0'

class PromoteTests(EngineTestCase):
    '''promote to a class the project doesn't have'''

    def setUp(self):
        super().setUp()
        self.harness = self.start_harness()
        self.harness.start_level(LEVEL)
        self.harness.run_until_state('free')

    def assertRefusesToPromote(self, script: str):
        with self.assertLogs(level='ERROR') as logs:
            self.harness.start_event(script)
            self.harness.run_until_state('free', 2000)
        self.assertIn("promote: No class Great_Lord in the database", logs.output[0])
        self.assertEqual('Eirika_Lord', self.harness.game.get_unit('Eirika').klass)

    def test_a_missing_class(self):
        '''Used to crash: 'NoneType' object has no attribute 'combat_anim_nid' '''
        self.assertRefusesToPromote('promote;Eirika;Great_Lord')

    def test_a_missing_class_among_several(self):
        self.assertRefusesToPromote('promote;Eirika;Eirika_Great_Lord,Great_Lord')
