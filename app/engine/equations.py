import functools

from app.data.database.database import DB
from app.data.database.equations import EQUATION_ARGS, to_python

class Parser():
    def __init__(self):
        self.stat_nids = [stat.nid for stat in DB.stats]
        self.equation_nids = [equation.nid for equation in DB.equations.values() if equation.expression]
        # Each equation becomes a function in this dict, which they all share as
        # their globals, so each can call the others through it
        self.equations = {}
        for equation in DB.equations.values():
            if equation.expression:
                python = to_python(equation.expression, self.stat_nids, self.equation_nids)
                try:
                    exec("def %s(%s): return %s" % (equation.nid, ', '.join(EQUATION_ARGS), python), self.equations)
                except SyntaxError as e:
                    raise ValueError("Equation %s is not a valid expression: %s" % (equation.nid, equation.expression)) from e

        # Now add these equations as local functions
        for nid in self.equations.keys():
            if not nid.startswith('__'):
                setattr(self, nid.lower(), functools.partial(self.equations[nid], self.equations))

    def get(self, lhs, unit):
        if lhs in self.equations:
            return self.equations[lhs](self.equations, unit)
        return 0

    def get_expression(self, expr, unit):
        # For one time use
        # Can't seem to be used with any sub equations
        equations = self.equations
        return eval(to_python(expr, self.stat_nids, self.equation_nids))

    def get_mana(self, unit):
        if hasattr(self, 'mana'):
            return self.mana(unit)
        else:
            return 0

    def get_max_fatigue(self, unit):
        if hasattr(self, 'max_fatigue'):
            return self.max_fatigue(unit)
        else:
            return 10

    def get_initiative(self, unit):
        if hasattr(self, 'initiative'):
            return self.initiative(unit)
        else:
            return 0

    def get_max_guard(self, unit):
        if hasattr(self, 'max_guard'):
            return self.max_guard(unit)
        else:
            return 10

    def get_gauge_inc(self, unit):
        if hasattr(self, 'gauge_increase'):
            return self.gauge_increase(unit)
        else:
            return 2

    def get_guard_exp(self, unit):
        if hasattr(self, 'guard_exp'):
            return self.guard_exp(unit)
        else:
            return 10

    def get_xcom_movement(self, unit):
        if hasattr(self, 'xcom_movement'):
            return self.xcom_movement(unit)
        else:
            return 0

PARSER = Parser()

def __getattr__(name):
    if name == 'parser':
        return PARSER
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

def clear():
    """
    Recreate the parser. Necessary in order to update equations after the user
    updates them in the equation editor
    """
    global PARSER
    PARSER = Parser()
