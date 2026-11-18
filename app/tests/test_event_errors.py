'''
A mistake in a game's event script fails with a message that names the event,
the line and what went wrong, rather than an engine traceback that leaves the
designer to work out which of their events caused it
'''
from app.events.event import CommandFailedError
from app.events.python_eventing.errors import InvalidPythonError
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

    def test_python_raised_in_the_engine_names_the_event_line(self):
        '''
        The error is raised inside UnitObject, not on the event's own line,
        and the event has no commands, so it fails as the event starts
        '''
        with self.assertRaises(InvalidPythonError) as caught:
            self.harness.start_event("#pyev1\nseth = game.get_unit('Seth')\nx = seth.no_such_attribute\n")
        message = str(caught.exception)
        self.assertIn('Line 3:', message)
        self.assertIn('x = seth.no_such_attribute', message)
        self.assertIn('AttributeError', message)

    def test_python_raised_by_other_executed_code_names_the_event_line(self):
        '''
        eval runs its code as "<string>", which equations and {e:} expressions
        do too, so finding the event's line by that name would find eval's
        '''
        self.harness.start_event("#pyev1\n$wait 1\nx = eval('1 / 0')\n")
        with self.assertRaises(InvalidPythonError) as caught:
            self.harness.run_until_state('free')
        message = str(caught.exception)
        self.assertIn('Line 3:', message)
        self.assertIn("x = eval('1 / 0')", message)
        self.assertIn('ZeroDivisionError', message)
