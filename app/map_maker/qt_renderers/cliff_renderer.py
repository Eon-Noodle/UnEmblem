from typing import Dict

from app.map_maker.qt_renderers.qt_palette import QtPalette
from app.map_maker.qt_renderers import SimpleRenderer

class CliffRenderer(SimpleRenderer):
    """
    The specific renderer used from CliffPainter
    """
    def use_palette(self, palette: QtPalette):
        limit: Dict[int, int] = {i: palette.limit16(i) for i in range(16)}
        self.painter.set_limit(limit)
        second_limit: Dict[int, int] = {i: palette.limit16(i, self.painter.second_start_px) for i in range(16)}
        self.painter.set_second_limit(second_limit)
