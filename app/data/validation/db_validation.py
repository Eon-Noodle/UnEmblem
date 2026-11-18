from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from app.data.database import references
from app.data.database.components import Component, ComponentType
from app.data.database.database import Database
from app.data.database.database_types import DatabaseType as DType
from app.data.database.database_validator import DatabaseValidatorEngine
from app.data.database import equations
from app.data.database.item_components import ItemTags
from app.data.database.level_units import GenericUnit, UniqueUnit
from app.data.database.levels import OBJECTIVE_KEYS, LevelPrefab
from app.data.database.skill_components import SkillTags
from app.data.resources.resource_types import ResourceType
from app.data.resources.resources import Resources
from app.data.resources.tiles import TileMapPrefab
from app.data.validation.utils import LTType
import app.data.validation.validation_errors as ltdb
from app.events.event_version import EventVersion
from app.events.python_eventing.analyzer import PyEventAnalyzer
from app.events import event_checks, event_commands
from app.events.regions import Region
from app.utilities.typing import NID

# The references the checks below report as errors, by owner type and path, so a
# reference to nothing there is not reported again as a warning
CHECKED_REFERENCES = {
    (DType.ITEMS, 'components'),
    (DType.SKILLS, 'components'),
    (DType.UNITS, 'klass'),
    (DType.UNITS, 'alternate_classes[*]'),
    (DType.UNITS, 'starting_items[*][0]'),
    (DType.UNITS, 'learned_skills[*][1]'),
    (DType.LEVELS, 'tilemap'),
    (DType.LEVELS, 'bg_tilemap'),
    (DType.LEVELS, 'party'),
    (DType.LEVELS, 'music{*}'),
    (DType.LEVELS, 'roam_unit'),
    (DType.LEVELS, 'units[*].ai'),
    (DType.LEVELS, 'units[*].roam_ai'),
    (DType.LEVELS, 'units[*].starting_items[*][0]'),
    (DType.LEVELS, 'units[*].starting_skills[*]'),
    (DType.LEVELS, 'units[*].starting_traveler'),
}

@dataclass
class ValidationResult():
    errors: List = field(default_factory=list)
    warnings: List = field(default_factory=list)

    def __add__(self, other: ValidationResult):
        return ValidationResult(self.errors + other.errors, self.warnings + other.warnings)

class DBChecker():
    def __init__(self, db: Database, resources: Resources) -> None:
        self.db = db
        self.resources = resources
        self.dve = DatabaseValidatorEngine(db, resources)

    def _validate_level_unit(self, unit: UniqueUnit | GenericUnit, level: LevelPrefab, level_units: Set[NID], travelers: Dict[NID, NID], l_err: ltdb.Error) -> ValidationResult:
        res = ValidationResult()
        u_err = l_err.field("Units").prop(DType.UNITS, unit.nid)

        res.errors += self._val_or_err(unit.ai, DType.AI, u_err.field("AI"))
        res.errors += self._val_or_err(unit.roam_ai, DType.AI, u_err.field("Roam AI"))

        tilemap_prefab = self.resources.tilemaps.get(level.tilemap)
        if unit.starting_position and tilemap_prefab and not tilemap_prefab.check_bounds(unit.starting_position):
            res.errors.append(u_err.msg("Starting Position %s is out of bounds" % (unit.starting_position,)))

        if travelers.get(unit.nid):
            traveler = travelers.get(unit.nid)
            if traveler not in level_units:
                res.errors.append(u_err.msg("Traveler %s is not loaded into level" % traveler))
            elif traveler == unit.nid:
                res.errors.append(u_err.msg("Unit is its own traveler"))
            elif level.units.get(traveler).starting_position:
                res.errors.append(u_err.msg("Traveler %s already has position on map" % traveler))
            elif traveler in [v for k, v in travelers.items() if k != unit.nid]:
                res.errors.append(u_err.msg("Multiple units have identical traveler %s" % traveler))

        return res

    def _validate_generic_unit(self, unit: GenericUnit, level: LevelPrefab, level_units: Set[NID], travelers: Dict[NID, NID], l_err: ltdb.Error) -> ValidationResult:
        res = ValidationResult()
        u_err = l_err.field("Units").prop(DType.UNITS, unit.nid)
        res.errors += self._val_or_err(unit.get_items(), DType.ITEMS, u_err.field("Items"))
        res.errors += self._val_or_err(unit.get_skills(), DType.SKILLS, u_err.field("Skills"))
        res += self._validate_level_unit(unit, level, level_units, travelers, l_err)
        return res

    def _validate_region(self, region: Region, level_tilemap: Optional[TileMapPrefab], l_err: ltdb.Error) -> ValidationResult:
        res = ValidationResult()
        r_err = l_err.prop("Region", region.nid)
        r_warn = r_err.to_warn()
        if not level_tilemap:
            res.warnings.append(r_warn.msg("Region exists but no tilemap exists in level"))
            return res
        # @TODO(mag): determine if all regions should have positions/it's warning-worthy
        # if not region.position: append "Region has no position"
        if region.position:
            rx, ry = region.position
            rxb, ryb = rx + region.size[0], ry + region.size[1]
            if rx < 0 or ry < 0 or rxb > level_tilemap.width or ryb > level_tilemap.height:
                res.warnings.append(r_warn.msg("Region bounds exceed tilemap size or region not in tilemap"))
        return res

    def validate_levels(self) -> ValidationResult:
        res = ValidationResult()
        for level in self.db.levels:
            l_err = ltdb.Error(DType.LEVELS, level.nid)
            l_warn = l_err.to_warn()

            res.errors += self._val_or_err(level.tilemap, ResourceType.TILEMAPS, l_err.field("tilemap"))
            res.errors += self._val_or_err(level.bg_tilemap, ResourceType.TILEMAPS, l_err.field("bg_tilemap"))
            res.errors += self._val_or_err(level.party, DType.PARTIES, l_err.field("party"))

            # music
            for music_key in self.db.music_keys:
                track = level.music.get(music_key)
                res.errors += self._val_or_err(track, ResourceType.MUSIC, l_err.field("Music:%s" % music_key))

            # objective, warning only
            res.warnings += [l_warn.tmplt.null_f("objective:%s" % objtv) for objtv in OBJECTIVE_KEYS if not level.objective.get(objtv)]

            # roam
            if level.roam:
                res.errors += self._val_or_err(level.roam_unit, DType.UNITS, l_err.field("roam_unit"), False)

            all_level_units = set(level.units.keys())
            travelers: Dict[NID, NID] = {unit.nid: unit.starting_traveler for unit in level.units}
            for unit in level.units:
                if isinstance(unit, UniqueUnit):
                    res += self._validate_level_unit(unit, level, all_level_units, travelers, l_err)
                elif isinstance(unit, GenericUnit):
                    res += self._validate_generic_unit(unit, level, all_level_units, travelers, l_err)

            for region in level.regions:
                res += self._validate_region(region, self.resources.tilemaps.get(level.tilemap), l_err)

            # level.groups: if any warnings or errors pop up, we can add them here; can't think of any right now
            # level.ai_groups: ditto to the above
        return res

    # in short, iterates through every component on the item, and verifies that
    # the component's value matches its type.
    def validate_items_and_skills(self) -> ValidationResult:
        def _val_comp_t(ctype: ComponentType | Tuple[ComponentType, ComponentType], cval, c_err: ltdb.Error) -> List[ltdb.Error]:
            types_and_values = []
            if isinstance(ctype, tuple):
                container = ctype[0]
                value_type = ctype[1]
                if container == ComponentType.List:
                    # list of nids
                    types_and_values = [(value_type, value) for value in cval]
                elif container in (ComponentType.Dict, ComponentType.FloatDict, ComponentType.StringDict):
                    # see elsewhere for usages: always dict of 'nid: value'
                    types_and_values = [(value_type, key) for key, _ in cval]
                elif container == ComponentType.MultipleChoice:
                    # short-circuit. we don't use DB validation for this
                    if not cval in value_type:
                        return [c_err.msg("Choice %s is not any of [%s]" % (cval, ','.join(value_type)))]
            else:
                types_and_values = [(ctype, cval)]
            errors = []
            for cctype, cvalue in types_and_values:
                errors += self._val_or_err(cvalue, cctype, c_err)
            return errors

        def _val_comp(component: Component, s_err: ltdb.Error) -> ValidationResult:
            c_err = s_err.prop("Component", component.nid)
            c_warn = c_err.to_warn()
            errors: List[ltdb.Error] = []
            warnings: List[ltdb.Warning] = []
            if not component.expose:
                pass  # holds no value to check
            elif component.expose == ComponentType.NewMultipleOptions:
                for option in component.options.keys():
                    errors += _val_comp_t(component.options[option], component.value[option], c_err)
            else:
                errors += _val_comp_t(component.expose, component.value, c_err)
            if component.tag in (SkillTags.DEPRECATED, ItemTags.DEPRECATED):
                warnings.append(c_warn.msg("Deprecated Component. Consider using a newer version of this component. Engine updates may cause this to break."))
            return ValidationResult(errors, warnings)

        res = ValidationResult()
        for skill in self.db.skills:
            s_err = ltdb.Error(DType.SKILLS, skill.nid)
            for component in skill.components:
                res += _val_comp(component, s_err)
        for item in self.db.items:
            i_err = ltdb.Error(DType.ITEMS, item.nid)
            for component in item.components:
                res += _val_comp(component, i_err)
        return res

    def validate_units(self) -> ValidationResult:
        res = ValidationResult()
        for unit in self.db.units:
            u_err = ltdb.Error(DType.UNITS, unit.nid)
            res.errors += self._val_or_err(unit.get_items(), DType.ITEMS, u_err.field("Starting Items"))
            res.errors += self._val_or_err(unit.get_skills(), DType.SKILLS, u_err.field("Learned Skills"))
            res.errors += self._val_or_err(unit.klass, DType.CLASSES, u_err.field("Class"))
            res.errors += self._val_or_err(unit.alternate_classes, DType.CLASSES, u_err.field("Alternate Classes"))
        return res

    def validate_equations(self) -> ValidationResult:
        stat_nids = [stat.nid for stat in self.db.stats]
        equation_nids = [equation.nid for equation in self.db.equations if equation.expression]
        all_errors = []
        for equation in self.db.equations:
            if equation.expression:
                problem = equations.expression_problem(equation.expression, stat_nids, equation_nids)
                if problem:
                    all_errors.append(ltdb.Error(DType.EQUATIONS, equation.nid).msg('%s\n    %s' % (equation.expression, problem)))
        return ValidationResult(all_errors)

    def validate_events(self) -> ValidationResult:
        alz = PyEventAnalyzer(self.db.events)
        all_errors = []
        all_warnings = []
        for event in self.db.events:
            if event.version() != EventVersion.EVENT:
                all_errors += alz.verify_event(event.nid, event.source)
            else:
                # Warnings, not errors: a line the engine can't read runs as a
                # comment, as one left behind by an older engine version does
                e_err = ltdb.Error(DType.EVENTS, event.nid).to_warn()
                for line_num, line, problem in event_checks.event_problems(event.source):
                    all_warnings.append(e_err.msg('Line %d: %s\n    %s' % (line_num, line.strip(), problem)))
        return ValidationResult(all_errors, all_warnings)

    def validate_references(self) -> ValidationResult:
        """Every reference the reference schema declares that names nothing, as a
        warning, except those the checks above report as errors"""
        res = ValidationResult()
        for site in references.dangling(self.db, self.resources):
            if (site.owner_type, site.where) in CHECKED_REFERENCES:
                continue
            if site.owner is not None:
                warn = ltdb.Error(site.owner_type, site.owner.nid).to_warn().field(site.where)
            else:
                # A reference the catalog holds itself, as the teams hold their alliances
                warn = ltdb.Error(site.owner_type, site.where).to_warn()
            res.warnings.append(warn.tmplt.not_type(site.target, site.value))
        return res

    def validate_resource_references(self) -> ValidationResult:
        """Every reference a resource holds that names nothing, as a warning. The
        reference schema covers only the database's records, so these are read here:
        the palettes and the effects and sounds of combat animations and effects,
        and the tilesets and terrain of tilemaps and tilesets."""
        res = ValidationResult()

        def warn(rtype: ResourceType, nid: NID, where: str, target: LTType, value) -> None:
            res.warnings.append(ltdb.Error(rtype, nid).to_warn().field(where).tmplt.not_type(target, value))

        def check_anim(rtype: ResourceType, anim, poses_by_where) -> None:
            for palette_name, palette_nid in anim.palettes:
                # A palette entry without a palette is left by deleting the project's last palette
                if palette_nid not in self.resources.combat_palettes:
                    warn(rtype, anim.nid, 'palettes:%s' % palette_name, ResourceType.COMBAT_PALETTES, palette_nid)
            for where, poses in poses_by_where:
                for pose in poses:
                    for command in pose.timeline:
                        # An effect deleted from under a command leaves None, which plays nothing
                        if command.has_effect() and command.value[0] is not None and \
                                command.value[0] not in self.resources.combat_effects:
                            warn(rtype, anim.nid, '%s:%s' % (where, pose.nid), ResourceType.COMBAT_EFFECTS, command.value[0])
                        if command.has_sound() and command.value[0] not in self.resources.sfx:
                            warn(rtype, anim.nid, '%s:%s' % (where, pose.nid), ResourceType.SFX, command.value[0])

        for combat_anim in self.resources.combat_anims:
            check_anim(ResourceType.COMBAT_ANIMS, combat_anim,
                       [(weapon_anim.nid, weapon_anim.poses) for weapon_anim in combat_anim.weapon_anims])
        for effect_anim in self.resources.combat_effects:
            check_anim(ResourceType.COMBAT_EFFECTS, effect_anim, [('poses', effect_anim.poses)])
        for tilemap in self.resources.tilemaps:
            for tileset_nid in tilemap.tilesets:
                if tileset_nid not in self.resources.tilesets:
                    warn(ResourceType.TILEMAPS, tilemap.nid, 'tilesets', ResourceType.TILESETS, tileset_nid)
            for layer in tilemap.layers:
                for tileset_nid in sorted({tile.tileset_nid for tile in layer.sprite_grid.values()} -
                                          set(self.resources.tilesets.keys())):
                    warn(ResourceType.TILEMAPS, tilemap.nid, 'layer %s' % layer.nid, ResourceType.TILESETS, tileset_nid)
                for terrain_nid in sorted(set(layer.terrain_grid.values()) - set(self.db.terrain.keys())):
                    warn(ResourceType.TILEMAPS, tilemap.nid, 'layer %s' % layer.nid, DType.TERRAIN, terrain_nid)
        for tileset in self.resources.tilesets:
            for terrain_nid in sorted(set(tileset.terrain_grid.values()) - set(self.db.terrain.keys())):
                warn(ResourceType.TILESETS, tileset.nid, 'terrain_grid', DType.TERRAIN, terrain_nid)
        return res

    def _val_or_err(self, nids: List[NID] | NID, dtype: LTType, parent_error: ltdb.Error, optional=True) -> List[ltdb.Error]:
        if not isinstance(nids, list):
            nids = [nids]
        if optional:
            nids = [nid for nid in nids if nid]
        return [parent_error.tmplt.not_type(dtype, nid) for nid in nids if not self.dve.validate(dtype, nid)]

    def validate_for_errors(self) -> List:
        all_errors = self.validate_events().errors
        all_errors += self.validate_equations().errors
        all_errors += self.validate_items_and_skills().errors
        all_errors += self.validate_levels().errors
        all_errors += self.validate_units().errors
        return all_errors

    def validate_for_warnings(self) -> List:
        all_warnings = self.validate_events().warnings
        all_warnings += self.validate_items_and_skills().warnings
        all_warnings += self.validate_levels().warnings
        all_warnings += self.validate_units().warnings
        all_warnings += self.validate_references().warnings
        all_warnings += self.validate_resource_references().warnings
        return all_warnings

    def repair(self):
        self.dve.repair()