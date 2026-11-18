'''
A mistake in a game's event script fails with a message that names the event,
the line and what went wrong, rather than an engine traceback that leaves the
designer to work out which of their events caused it
'''
from app.events.event import CommandFailedError
from app.tests.engine_harness import EngineTestCase

# testing_proj level 0: Eirika (4, 5) and Seth (4, 4)
LEVEL = '0'

class EventErrorTests(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.harness = self.start_harness()
        self.harness.start_level(LEVEL)
        self.harness.run_until_state('free')

    def test_a_failing_command_names_its_event_and_line(self):
        self.harness.start_event('speak;Seth;Hello|nid=hi\ngive_money;lots')
        self.harness.click_through_events = True
        with self.assertRaises(CommandFailedError) as caught:
            self.harness.run_until_state('free')
        message = str(caught.exception)
        self.assertIn('Event "Global harness_event", Line 2:', message)
        self.assertIn('give_money;lots', message)
        # What the command itself raised, named, since it says what is wrong
        self.assertIn('TypeError', message)
        self.assertIsInstance(caught.exception.__cause__, TypeError)
