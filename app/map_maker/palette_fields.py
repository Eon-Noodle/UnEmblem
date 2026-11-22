"""
Palette fields: a map's terrain drawn with several palettes at once, each
spreading out from an origin of its own and fading into the others.

Each source scores a position by its distance from the source's origin over the
source's strength. The source scoring lowest gives the tile its shape: its
palette's sheets hold the sprite the tile is drawn with. The tile's colors are a
blend of every source's palette, each weighted by
exp(-(its score - the lowest score) / transition), so a tile as far from two
origins of equal strength takes half of each palette's colors, and a tile well
inside one field takes nearly all of its palette's. Each weight is rounded to a
whole number of steps, so neighbouring tiles share a blend and the sprites of a
blend are each drawn once.

Outdoor terrain is drawn only with the outdoor sources' palettes, and indoor
terrain only with the indoor sources'.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, NamedTuple, Optional, Tuple

from app.utilities.typing import NID, Pos


class Blend(NamedTuple):
    """The palettes a tile is drawn with: the one whose sheets give it its shape,
    and how many steps of the tile's colors each palette gives, the shape's own
    palette among them. mix is in order of palette nid"""
    shape: NID
    mix: Tuple[Tuple[NID, int], ...]

    @classmethod
    def pure(cls, palette: NID) -> Blend:
        """A tile drawn with one palette alone"""
        return cls(palette, ((palette, 1),))

    def is_pure(self) -> bool:
        return len(self.mix) == 1


@dataclass
class PaletteSource:
    palette: NID
    origin: Pos  # In tiles. May lie off the map
    strength: float = 1.0

    def score(self, pos: Pos) -> float:
        return math.hypot(pos[0] - self.origin[0], pos[1] - self.origin[1]) / self.strength

    def save(self) -> dict:
        return {'palette': self.palette, 'origin': list(self.origin), 'strength': self.strength}

    @classmethod
    def restore(cls, s_dict: dict) -> PaletteSource:
        return cls(s_dict['palette'], tuple(s_dict['origin']), s_dict['strength'])


@dataclass
class PaletteFields:
    # Whether the map is drawn with its sources. Off, or with no sources for a
    # kind of terrain, that terrain is drawn with the map's one palette for it
    enabled: bool = False
    outdoor: List[PaletteSource] = field(default_factory=list)
    indoor: List[PaletteSource] = field(default_factory=list)
    # How far, in score, a palette's colors reach past the edge of its field
    transition: float = 3.0
    # How many parts a tile's colors are blended in
    steps: int = 8

    def sources(self, outdoor: bool) -> List[PaletteSource]:
        return self.outdoor if outdoor else self.indoor

    def blend_at(self, pos: Pos, outdoor: bool) -> Optional[Blend]:
        """The blend the terrain at pos is drawn with, or None when the map's one
        palette for that kind of terrain draws it"""
        sources = self.sources(outdoor)
        if not self.enabled or not sources:
            return None
        scores = [source.score(pos) for source in sources]
        lowest = min(scores)
        # The first of the sources scoring lowest gives the shape
        shape = sources[scores.index(lowest)].palette
        if self.transition <= 0:
            return Blend.pure(shape)

        weights: Dict[NID, float] = {}
        for source, score in zip(sources, scores):
            weights[source.palette] = weights.get(source.palette, 0) + math.exp(-(score - lowest) / self.transition)
        total = sum(weights.values())
        steps = {palette: round(self.steps * weight / total)
                 for palette, weight in weights.items() if palette != shape}
        # The shape's palette takes whatever steps the others leave, and at least one
        steps[shape] = max(self.steps - sum(steps.values()), 1)
        mix = tuple(sorted((palette, n) for palette, n in steps.items() if n > 0))
        # One blend for each tile drawn with its shape's palette alone, however many steps it has
        return Blend.pure(shape) if len(mix) == 1 else Blend(shape, mix)

    def shift(self, x_offset: int, y_offset: int) -> None:
        """Moves every origin along with the map's terrain, as a resize does"""
        for source in self.outdoor + self.indoor:
            source.origin = (source.origin[0] + x_offset, source.origin[1] + y_offset)

    def save(self) -> dict:
        return {
            'enabled': self.enabled,
            'outdoor': [source.save() for source in self.outdoor],
            'indoor': [source.save() for source in self.indoor],
            'transition': self.transition,
            'steps': self.steps,
        }

    @classmethod
    def restore(cls, s_dict: dict) -> PaletteFields:
        return cls(
            s_dict['enabled'],
            [PaletteSource.restore(source) for source in s_dict['outdoor']],
            [PaletteSource.restore(source) for source in s_dict['indoor']],
            s_dict['transition'],
            s_dict['steps'],
        )
