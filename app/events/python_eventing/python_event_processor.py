from __future__ import annotations
from functools import lru_cache

from typing import Optional
from app.engine.game_state import GameState

from app.events import event_commands
from app.events.python_eventing.compiler import Compiler
from app.events.python_eventing.utils import DO_NOT_EXECUTE_SENTINEL
from app.utilities.typing import NID

class PythonEventProcessor():
    def __init__(self, nid: NID, source: str, game: GameState, curr_cmd_idx: int = 0, context: dict = None):
        self.nid = nid
        self.source = source
        self.curr_cmd_idx = curr_cmd_idx
        self.is_finished = False
        self._compiled_script = Compiler.compile(nid, source, 0)
        self._executable = self._compiled_script.get_runnable(game, context)

    @lru_cache()
    def get_source_line(self, line: int) -> str:
        as_lines = self.source.split('\n')
        return as_lines[line]

    def get_current_line(self) -> int:
        return self._executable.gi_frame.f_lineno - self._executable.gi_code.co_firstlineno - 1

    def fetch_next_command(self) -> Optional[event_commands.EventCommand]:
        try:
            command_idx, next_command = next(self._executable)
            while command_idx is DO_NOT_EXECUTE_SENTINEL:
                command_idx, next_command = next(self._executable)
            self.curr_cmd_idx = command_idx
            return next_command
        except StopIteration:
            self.is_finished = True
            return None
        except Exception as e:
            # exception occured in python script
            raise self._compiled_script.python_error(e) from e

    def finished(self):
        return self.is_finished

    def save(self):
        s_dict = {}
        s_dict['nid'] = self.nid
        s_dict['source'] = self.source
        s_dict['is_finished'] = self.is_finished
        s_dict['curr_cmd_idx'] = self.curr_cmd_idx
        return s_dict

    @classmethod
    def restore(cls, s_dict, game: GameState) -> PythonEventProcessor:
        source = s_dict['source']
        nid = s_dict['nid']
        self = cls(nid, source, game)
        self.curr_cmd_idx = s_dict['curr_cmd_idx']
        self._compiled_script = Compiler.compile(nid, source, self.curr_cmd_idx)
        self._executable = self._compiled_script.get_runnable(game)
        return self
