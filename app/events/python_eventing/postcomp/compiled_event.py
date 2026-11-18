from dataclasses import dataclass
import traceback
from typing import Generator
from app.engine.evaluate import get_context
from app.engine.game_state import GameState
from app.events.python_eventing.errors import InvalidPythonError
from app.events.python_eventing.utils import EVENT_GEN_NAME, create_null_event
from app.utilities.typing import NID

@dataclass
class CompiledEvent():
    event: NID          # event nid
    source: str         # original source code of event
    compiled: str       # pythonic source code of event

    @property
    def filename(self) -> str:
        """What the compiled event runs as, so its frames can be told from any other exec'd code's"""
        return '<event %s>' % self.event

    def get_runnable(self, game: GameState, context: dict=None) -> Generator:
        exec_context = get_context(game=game, local_args=context)
        exec(compile(self.compiled, self.filename, 'exec'), exec_context)
        # possibility that there are some errors in python script
        try:
            gen = exec_context[EVENT_GEN_NAME]()
            if not gen: # for some reason, a python event contains no real event commands
                return create_null_event()
        except Exception as e:
            raise self.python_error(e) from e
        return gen

    def python_error(self, e: Exception) -> InvalidPythonError:
        """
        The error naming the line of the event's own source that e passed
        through last, which may have been raised deeper, in the engine
        """
        event_frames = [frame for frame in traceback.extract_tb(e.__traceback__) if frame.filename == self.filename]
        true_lineno = event_frames[-1].lineno - self._num_diff_lines()
        failing_line = self.source.split('\n')[true_lineno - 1]
        exc = InvalidPythonError(self.event, true_lineno, failing_line)
        exc.what = '%s: %s' % (type(e).__name__, e)
        return exc

    def _num_diff_lines(self):
        generator_idx = self.compiled.index(EVENT_GEN_NAME)
        return self.compiled[:generator_idx].count('\n') + 1