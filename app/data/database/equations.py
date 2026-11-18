from __future__ import annotations

import ast
import builtins
import re
from dataclasses import dataclass
from typing import Collection, Optional

from app.utilities.data import Data, Prefab

@dataclass
class Equation(Prefab):
    nid: str = None
    expression: str = None

class EquationCatalog(Data[Equation]):
    datatype = Equation

# The names an equation's Python runs with besides the builtins, as the engine
# defines each one: def NID(equations, unit)
EQUATION_ARGS = ('equations', 'unit')

def to_python(expression: str, stat_nids: Collection[str], equation_nids: Collection[str]) -> str:
    '''
    The Python an equation runs as: each stat named in it reads the unit's
    stat, and each equation calls that equation. Its result is an int,
    unless it mentions float
    '''
    def replace(token: str) -> str:
        if token in stat_nids:
            return "(unit.stats['%s'] + unit.stat_bonus('%s'))" % (token, token)
        if token in equation_nids:
            return "equations['%s'](equations, unit)" % token
        return token
    python = ''.join(replace(token) for token in re.split('([^a-zA-Z_])', expression))
    if 'float' in python:
        return python
    return 'int(%s)' % python

def expression_problem(expression: str, stat_nids: Collection[str], equation_nids: Collection[str]) -> Optional[str]:
    '''What keeps an equation's expression from running, if anything: bad syntax, or a name that is not a stat or an equation'''
    try:
        tree = ast.parse(to_python(expression, stat_nids, equation_nids), mode='eval')
    except SyntaxError as e:
        return 'Not a valid expression: %s' % e.msg
    names = [node for node in ast.walk(tree) if isinstance(node, ast.Name)]
    # Names the expression binds itself, in a comprehension or a lambda
    bound = {node.id for node in names if isinstance(node.ctx, ast.Store)} | \
        {node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)}
    unknown = sorted({node.id for node in names if node.id not in bound
                      and node.id not in EQUATION_ARGS and not hasattr(builtins, node.id)})
    if unknown:
        return 'Not a stat or an equation: %s' % ', '.join(unknown)
    return None
