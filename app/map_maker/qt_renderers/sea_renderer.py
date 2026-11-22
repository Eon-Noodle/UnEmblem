from app.map_maker.qt_renderers.qt_palette import QtPalette

from app.map_maker.qt_renderers import SimpleRenderer8

class SeaRenderer(SimpleRenderer8):
    def use_palette(self, palette: QtPalette):
        self.painter.set_limit({k: palette.limit16(k) for k in range(16)})
        self.painter.sand_limit = {k: palette.limit16(k, self.painter.sand_start_px) for k in range(16)}
