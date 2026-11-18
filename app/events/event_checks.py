'''
Mistakes in an event written in the event language that the engine would
pass over without a word, or crash on: a line it can't read as a command runs
as a comment, an if without its end runs to the end of the event, and an
argument naming an item, skill, class or the like that the project does not
have finds nothing. Found by reading the source against the database, so that
validation can name them before the game is played
'''
from __future__ import annotations

from typing import List, Optional, Tuple

from app.data.database.database import Database
from app.data.resources.resources import Resources
from app.events import event_commands, event_validators
from app.events.event_version import EventVersion
from app.utilities import str_utils

# Each command that opens a block, and the command that closes it
BLOCKS = {'if': 'end', 'for': 'endf'}

# The argument types whose value must be the nid of a record in one of the
# project's catalogs, with what that record is. Others are left out: those that
# look in the event's own level (a unit, a position, a region) are wrong about
# an event that runs in another one
CATALOG_TYPES = {
    'Item': 'an item',
    'ItemList': 'a list of items',
    'Skill': 'a skill',
    'Ability': 'an item or a skill',
    'Klass': 'a class',
    'KlassList': 'a list of classes',
    'WeaponType': 'a weapon type',
    'SupportRank': 'a support rank',
    'Affinity': 'an affinity',
    'StatList': 'a list of stats and changes',
    'Party': 'a party',
    'Faction': 'a faction',
    'Lore': 'a lore entry',
    'Team': 'a team',
    'AI': 'an AI',
    'Tag': 'a tag',
    'TagList': 'a list of tags',
    'DifficultyMode': 'a difficulty mode',
    'Music': 'a song',
    'Sound': 'a sound',
    'PortraitNid': 'a portrait',
    'MapAnim': 'a map animation',
    'Tilemap': 'a tilemap',
}

def command_problem(line: str) -> Optional[str]:
    '''What keeps one line from being read as the command it names, if anything'''
    command, bad_idx = event_commands.parse_text_to_command(line, strict=True)
    if command:
        return None
    command_nid = event_commands.get_command_arguments(line.strip())[0].string
    command_type = event_commands.get_all_event_commands(EventVersion.EVENT).get(command_nid)
    if not command_type:
        return '"%s" is not an event command' % command_nid
    usage = ';'.join([command_type.nid] + command_type.keywords + ['[%s]' % keyword for keyword in command_type.optional_keywords])
    return 'The arguments do not fit %s, which takes %s' % (command_type.nid, usage)

def argument_problems(command: event_commands.EventCommand, db: Database, resources: Resources) -> List[str]:
    '''Each argument of a command that names a record the project does not have'''
    problems = []
    for keyword, value in command.parameters.items():
        var_type = str_utils.remove_prefix(command.get_validator_from_keyword(keyword) or '', '*')
        # An empty argument takes the default, and one with {} is filled in as the event runs
        if var_type not in CATALOG_TYPES or not value or '{' in value:
            continue
        # An item or skill argument takes the uid of one the unit holds as well as its nid
        if var_type in ('Item', 'Skill') and str_utils.is_int(value):
            continue
        if event_validators.validate(var_type, value, None, db, resources) is None:
            problems.append('%s "%s" is not %s in this project' % (keyword, value, CATALOG_TYPES[var_type]))
    return problems

def event_problems(source: str, db: Database, resources: Resources) -> List[Tuple[int, str, str]]:
    '''Each problem in an event's source, as its line number (from 1), the line, and what is wrong'''
    problems: List[Tuple[int, str, str]] = []
    lines = source.split('\n')
    # The blocks open at this point, as the line number and command that opened each
    open_blocks: List[Tuple[int, str]] = []
    for line_num, line in enumerate(lines, 1):
        problem = command_problem(line)
        if problem:
            problems.append((line_num, line, problem))
            continue
        command, _ = event_commands.parse_text_to_command(line, strict=True)
        for problem in argument_problems(command, db, resources):
            problems.append((line_num, line, problem))
        nid = command.nid
        if nid in BLOCKS:
            open_blocks.append((line_num, nid))
        elif nid in ('elif', 'else'):
            if not open_blocks or open_blocks[-1][1] != 'if':
                problems.append((line_num, line, '%s has no if before it' % nid))
        elif nid in BLOCKS.values():
            if not open_blocks or BLOCKS[open_blocks[-1][1]] != nid:
                problems.append((line_num, line, '%s has no %s before it to close' % (nid, 'if' if nid == 'end' else 'for')))
            else:
                open_blocks.pop()
    for line_num, nid in open_blocks:
        problems.append((line_num, lines[line_num - 1], '%s has no %s to close it' % (nid, BLOCKS[nid])))
    return sorted(problems)
