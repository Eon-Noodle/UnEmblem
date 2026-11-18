'''
Mistakes in an event written in the event language that the engine would
pass over without a word: a line it can't read as a command runs as a comment,
and an if without its end runs to the end of the event. Found by reading the
source alone, so that validation can name them before the game is played
'''
from __future__ import annotations

from typing import List, Optional, Tuple

from app.events import event_commands
from app.events.event_version import EventVersion

# Each command that opens a block, and the command that closes it
BLOCKS = {'if': 'end', 'for': 'endf'}

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

def event_problems(source: str) -> List[Tuple[int, str, str]]:
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
