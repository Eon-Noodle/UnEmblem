import unittest
from unittest.mock import MagicMock

from app.data.database.database import DB
from app.data.serialization.versions import CURRENT_SERIALIZATION_VERSION
from app.engine import equations

class EquationParserTests(unittest.TestCase):
    def setUp(self):
        DB.load('testing_proj.ltproj', CURRENT_SERIALIZATION_VERSION)
        # Cleanups run last first: the project's own equations come back, then
        # the parser is built from them again
        self.addCleanup(equations.clear)
        self.addCleanup(DB.load, 'testing_proj.ltproj', CURRENT_SERIALIZATION_VERSION)

    def unit(self, **stats):
        unit = MagicMock()
        unit.stats = stats
        unit.stat_bonus = lambda nid: 0
        return unit

    def test_an_equation_reads_stats_and_calls_other_equations(self):
        DB.equations.get('HIT').expression = 'SKL*2 + LCK//2'
        DB.equations.get('AVOID').expression = 'HIT + 1'
        parser = equations.Parser()
        unit = self.unit(SKL=5, LCK=3)
        self.assertEqual(11, parser.hit(unit))
        self.assertEqual(12, parser.avoid(unit))
        self.assertEqual(12, parser.get_expression('HIT + 1', unit))

    def test_an_equation_is_an_int_unless_it_mentions_float(self):
        DB.equations.get('HIT').expression = 'SKL / 2'
        DB.equations.get('AVOID').expression = 'float(SKL) / 2'
        parser = equations.Parser()
        unit = self.unit(SKL=5)
        self.assertEqual(2, parser.hit(unit))
        self.assertEqual(2.5, parser.avoid(unit))

    def test_an_equation_that_is_not_valid_names_itself(self):
        '''Rather than show the Python it was turned into'''
        DB.equations.get('DAMAGE').expression = 'STR +'
        with self.assertRaises(ValueError) as caught:
            equations.Parser()
        self.assertEqual('Equation DAMAGE is not a valid expression: STR +', str(caught.exception))

if __name__ == '__main__':
    unittest.main()
