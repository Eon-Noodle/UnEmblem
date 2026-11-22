"""
The map maker's palette fields (app/map_maker/palette_fields.py): the sources
each kind of terrain is drawn with, and how their palettes blend.
"""
from __future__ import annotations
from typing import TYPE_CHECKING, List

from PyQt5.QtWidgets import QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, \
    QSpinBox, QTabWidget, QToolButton, QVBoxLayout, QWidget
from PyQt5.QtGui import QIcon

from app import dark_theme
from app.extensions.custom_gui import ComboBox, PropertyBox
from app.utilities.typing import Pos

from app.map_maker.editor.palette_model import PaletteModel
from app.map_maker.palette_collection import PALETTES
from app.map_maker.palette_fields import PaletteFields, PaletteSource
if TYPE_CHECKING:
    from app.map_maker.editor.map_editor import MapEditor

# How far off the map an origin may lie
ORIGIN_RANGE = 999

class SourceRow(QWidget):
    """One source: its palette, origin and strength"""
    def __init__(self, sources_widget: SourcesWidget, index: int):
        super().__init__(sources_widget)
        self.sources_widget = sources_widget
        self.index = index
        icon_folder = dark_theme.get_theme().icon_dir()

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self.palette_box = ComboBox(self)
        self.palette_box.setModel(PaletteModel(sources_widget.palettes(), self))
        self.palette_box.activated.connect(self.palette_changed)
        layout.addWidget(self.palette_box)

        self.x_box, self.y_box = QSpinBox(self), QSpinBox(self)
        for label, box in (("X", self.x_box), ("Y", self.y_box)):
            box.setRange(-ORIGIN_RANGE, ORIGIN_RANGE)
            box.valueChanged.connect(self.origin_changed)
            layout.addWidget(QLabel(label, self))
            layout.addWidget(box)

        self.strength_box = QDoubleSpinBox(self)
        self.strength_box.setRange(0.1, 10)
        self.strength_box.setSingleStep(0.1)
        self.strength_box.setDecimals(1)
        self.strength_box.setToolTip("How far the field reaches: twice as strong reaches twice as far")
        self.strength_box.valueChanged.connect(self.strength_changed)
        layout.addWidget(QLabel("Strength", self))
        layout.addWidget(self.strength_box)

        self.pick_button = QPushButton("Pick", self)
        self.pick_button.setToolTip("Click the map to place this source's origin")
        self.pick_button.clicked.connect(self.pick)
        layout.addWidget(self.pick_button)

        self.remove_button = QToolButton(self)
        self.remove_button.setIcon(QIcon(f"{icon_folder}/minus.png"))
        self.remove_button.setToolTip("Remove this source")
        self.remove_button.clicked.connect(self.remove)
        layout.addWidget(self.remove_button)

    def source(self) -> PaletteSource:
        return self.sources_widget.sources()[self.index]

    def show_source(self):
        source = self.source()
        for box, value in ((self.x_box, source.origin[0]), (self.y_box, source.origin[1]),
                           (self.strength_box, source.strength)):
            box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(False)
        self.palette_box.setCurrentIndex(self.sources_widget.palettes().index(source.palette))

    def palette_changed(self, idx: int):
        self.source().palette = self.sources_widget.palettes()[idx].nid
        self.sources_widget.fields_widget.changed('Change Palette Source')

    def origin_changed(self, _):
        self.source().origin = (self.x_box.value(), self.y_box.value())
        self.sources_widget.fields_widget.changed('Move Palette Origin', merge=True)

    def strength_changed(self, value: float):
        self.source().strength = value
        self.sources_widget.fields_widget.changed('Change Palette Strength', merge=True)

    def pick(self):
        self.sources_widget.fields_widget.window.pick_palette_origin(self.sources_widget.outdoor, self.index)

    def remove(self):
        self.sources_widget.sources().pop(self.index)
        self.sources_widget.fields_widget.changed('Remove Palette Source')
        self.sources_widget.show_sources()

class SourcesWidget(QWidget):
    """The sources outdoor or indoor terrain is drawn with"""
    def __init__(self, fields_widget: PaletteFieldsWidget, outdoor: bool):
        super().__init__(fields_widget)
        self.fields_widget = fields_widget
        self.outdoor = outdoor
        icon_folder = dark_theme.get_theme().icon_dir()

        layout = QVBoxLayout()
        self.setLayout(layout)
        self.rows_layout = QVBoxLayout()
        layout.addLayout(self.rows_layout)
        self.rows: List[SourceRow] = []

        self.add_button = QPushButton(QIcon(f"{icon_folder}/plus.png"), "Add Source", self)
        self.add_button.clicked.connect(self.add)
        layout.addWidget(self.add_button)
        layout.addStretch()

    def palettes(self):
        return PALETTES.outdoor_palettes() if self.outdoor else PALETTES.indoor_palettes()

    def sources(self) -> List[PaletteSource]:
        return self.fields_widget.fields().sources(self.outdoor)

    def show_sources(self):
        sources = self.sources()
        while len(self.rows) > len(sources):
            self.rows.pop().deleteLater()
        while len(self.rows) < len(sources):
            self.rows.append(SourceRow(self, len(self.rows)))
            self.rows_layout.addWidget(self.rows[-1])
        for row in self.rows:
            row.show_source()

    def add(self):
        """A source of the map's one palette for this kind of terrain, at the middle of the map"""
        tilemap = self.fields_widget.window.current
        palette = tilemap.current_outdoor_palette if self.outdoor else tilemap.current_indoor_palette
        self.sources().append(PaletteSource(palette, (tilemap.width // 2, tilemap.height // 2)))
        self.fields_widget.changed('Add Palette Source')
        self.show_sources()

class PaletteFieldsWidget(QWidget):
    def __init__(self, window: MapEditor):
        super().__init__(window)
        self.window = window

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.tabs = QTabWidget(self)
        self.outdoor_sources = SourcesWidget(self, True)
        self.indoor_sources = SourcesWidget(self, False)
        self.tabs.addTab(self.outdoor_sources, "Outdoor Sources")
        self.tabs.addTab(self.indoor_sources, "Indoor Sources")
        layout.addWidget(self.tabs)

        self.transition_box = PropertyBox("Transition", QDoubleSpinBox, self)
        self.transition_box.edit.setRange(0, 50)
        self.transition_box.edit.setSingleStep(0.5)
        self.transition_box.edit.setDecimals(1)
        self.transition_box.setToolTip("How far a palette's colors reach past the edge of its field. 0 blends nothing")
        self.transition_box.edit.valueChanged.connect(self.transition_changed)
        self.steps_box = PropertyBox("Blend Steps", QSpinBox, self)
        self.steps_box.edit.setRange(1, 64)
        self.steps_box.setToolTip("How many parts a tile's colors are blended in")
        self.steps_box.edit.valueChanged.connect(self.steps_changed)
        boxes = QHBoxLayout()
        boxes.addWidget(self.transition_box)
        boxes.addWidget(self.steps_box)
        layout.addLayout(boxes)

    def fields(self) -> PaletteFields:
        return self.window.current.palette_fields

    def show_fields(self):
        """Shows the map's palette fields, as after an undo"""
        fields = self.fields()
        for box, value in ((self.transition_box, fields.transition), (self.steps_box, fields.steps)):
            box.edit.blockSignals(True)
            box.edit.setValue(value)
            box.edit.blockSignals(False)
        self.outdoor_sources.show_sources()
        self.indoor_sources.show_sources()

    def changed(self, label: str, merge: bool = False):
        """Draws the map again with its palette fields as they are now, and records the change"""
        self.window.current.reset_all()
        self.window.show_palettes()
        self.window.update_view()
        self.window.commit(label, merge)

    def transition_changed(self, value: float):
        self.fields().transition = value
        self.changed('Change Palette Transition', merge=True)

    def steps_changed(self, value: int):
        self.fields().steps = value
        self.changed('Change Blend Steps', merge=True)

    def set_origin(self, outdoor: bool, index: int, pos: Pos):
        """Places a source's origin where the map was clicked"""
        self.fields().sources(outdoor)[index].origin = pos
        (self.outdoor_sources if outdoor else self.indoor_sources).show_sources()
        self.changed('Move Palette Origin')
