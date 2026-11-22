"""Recolors every sprite sheet of a palette folder onto a new tileset.

Works in 8x8 cells, the unit a GBA tileset assigns its 16-color palettes to:

0. A 16x16 tile of a sprite sheet none of whose cells is in the base palette's
   main image, and whose shape (its pixels as indices into its colors) is that
   of exactly one tile of the new tileset, is that tile: it is copied whole. A sheet drawn from FE8 sprites in colors of its own (the
   sparse forest's tufts) takes a tileset's own sprites this way.
1. A cell of a sprite sheet that is found exactly in the base palette's main
   image, at a position where the new tileset has a cell of the same shape,
   takes that new cell's colors whole. A color the new tileset splits into
   several (one per GBA palette) keeps the right one in each place.
2. Every other cell is recolored pixel by pixel through a color map, each
   base color taking the new color it most often sits under: first among
   cells of the same shape at the same position in both images, else among
   cells whose shape appears only once in the new tileset.
3. A color neither finds (a color drawn by hand into a sprite sheet and not in
   the main image) is left as it is, and reported, unless the sheet is in
   FOLLOWS: then it follows the sheets named there (the FE8 sprites of the
   same terrain). It takes the color of those sheets nearest it in lightness
   and changes as that color changed: by as much in lightness, and losing
   saturation (never gaining it) in the same proportion, keeping its own hue.
   So hand-drawn tree outlines lighten and grey where the tileset lightens
   and greys its own trees.
4. Last, the sheets of a ROLE_SWAPS entry give each of its colors the new
   color another color took: the desert's base takes the sand's base, so the
   two meet without a seam (as in the Autumn palette).

The base folder's main image and new tileset should share a layout (the same
FE8 object set: compare the cell counts it prints). Sheets whose cells are
mostly recolored by the color map rather than copied are drawn in the base
palette's shapes, which the new tileset may not have.

python -m app.map_maker.scripts.palette_generation.cell_palette_exchanger BASE_FOLDER NEW_TILESET OUT_FOLDER
    [--main main.png] [--alias R,G,B=R,G,B ...] [--repair-from DONOR --used-in MAP ...] [--dry]

--alias gives a hand-drawn color the new color another base color maps to.
--repair-from DONOR --used-in MAP ... first recolors each color of the new tileset that none
of the maps uses (a sub-palette its chapter never draws with, which may hold placeholder
colors) in the color DONOR, a tileset of the same object set, has at the same pixels, moved
toward the new tileset's colors as the donor's nearest color the maps use moved.
--dry prints what would change without writing anything.
"""
import argparse
import glob
import math
import os
from collections import Counter, defaultdict
from typing import Dict, List, NamedTuple, Optional, Tuple

from PIL import Image

from app.map_maker.palette_blending import ColorMap, oklab_to_rgb, rgb_to_oklab

CELL = 8
TILE = 16
# A tile of fewer colors is too plain for its shape alone to find it
MIN_TILE_COLORS = 4
BLACK = (0, 0, 0)

# Key: a sheet with colors drawn by hand, Value: the sheets its hand-drawn colors follow
FOLLOWS: Dict[str, Tuple[str, ...]] = {
    'sparse_forest.png': ('forest.png', 'thicket.png'),
}

# Key: sheets, Value: {base color: the base color whose new color it takes}.
# The Sacred Fields family's desert colors are its sand's, in other roles: the
# desert's base is the sand's cream, its ripples the sand's yellow and light.
ROLE_SWAPS: Dict[Tuple[str, ...], Dict[Tuple[int, int, int], Tuple[int, int, int]]] = {
    ('desert.png', 'desert_cliff.png', 'desert_rock.png'): {
        (248, 232, 216): (240, 240, 128),  # base takes the sand's base
        (240, 240, 128): (248, 248, 216),
        (248, 248, 216): (248, 232, 216),
        (224, 232, 112): (224, 232, 112),
        (224, 223, 105): (160, 240, 160),  # ripple shadow, drawn by hand
    },
}

Color = Tuple[int, int, int]
CellPos = Tuple[int, int]

def read_cells(image: Image.Image) -> Dict[CellPos, List[Color]]:
    """Each whole CELLxCELL cell's colors, row by row"""
    image = image.convert('RGB')
    px = image.load()
    width, height = image.size
    cells = {}
    for ty in range(height // CELL):
        for tx in range(width // CELL):
            cells[(tx, ty)] = [px[tx * CELL + x, ty * CELL + y] for y in range(CELL) for x in range(CELL)]
    return cells

def read_tiles(image: Image.Image) -> Dict[CellPos, List[Color]]:
    """Each whole TILE x TILE tile's colors, row by row"""
    image = image.convert('RGB')
    px = image.load()
    width, height = image.size
    tiles = {}
    for ty in range(height // TILE):
        for tx in range(width // TILE):
            tiles[(tx, ty)] = [px[tx * TILE + x, ty * TILE + y] for y in range(TILE) for x in range(TILE)]
    return tiles

def shape(colors: List[Color]) -> Tuple[int, ...]:
    """The cell's pixels as indices into its colors in order of appearance"""
    index = {}
    return tuple(index.setdefault(c, len(index)) for c in colors)

class Exchange(NamedTuple):
    new_cells: Dict[CellPos, List[Color]]
    new_shapes: Dict[CellPos, Tuple[int, ...]]
    positions_by_shape: Dict[Tuple[int, ...], List[CellPos]]
    base_positions: Dict[Tuple[Color, ...], List[CellPos]]  # a base cell's exact colors -> where it is
    color_map: Dict[Color, Color]
    tiles_by_shape: Dict[Tuple[int, ...], List[List[Color]]]  # the new tileset's 16x16 tiles

def build_exchange(base_main: str, new_tileset: Image.Image) -> Exchange:
    base_cells = read_cells(Image.open(base_main))
    new_cells = read_cells(new_tileset)
    new_shapes = {pos: shape(c) for pos, c in new_cells.items()}
    positions_by_shape = defaultdict(list)
    for pos, s in new_shapes.items():
        positions_by_shape[s].append(pos)

    position_votes = defaultdict(Counter)
    shape_votes = defaultdict(Counter)
    base_positions = defaultdict(list)
    for pos, colors in base_cells.items():
        base_positions[tuple(colors)].append(pos)
        if len(set(colors)) <= 1:
            continue
        s = shape(colors)
        if new_shapes.get(pos) == s:
            for a, b in zip(colors, new_cells[pos]):
                position_votes[a][b] += 1
        elif len(positions_by_shape.get(s, ())) == 1:
            for a, b in zip(colors, new_cells[positions_by_shape[s][0]]):
                shape_votes[a][b] += 1
    color_map = {}
    for color in set(position_votes) | set(shape_votes):
        votes = position_votes[color] or shape_votes[color]
        color_map[color] = votes.most_common(1)[0][0]

    tiles_by_shape = defaultdict(list)
    for tile in read_tiles(new_tileset).values():
        if tile not in tiles_by_shape[shape(tile)]:
            tiles_by_shape[shape(tile)].append(tile)
    return Exchange(new_cells, new_shapes, positions_by_shape, base_positions, color_map, tiles_by_shape)

def _matching_cell(colors: List[Color], exchange: Exchange) -> Optional[List[Color]]:
    """The new tileset's colors for a cell found in the base main image, if it has the same shape there"""
    if tuple(colors) not in exchange.base_positions:
        return None
    s = shape(colors)
    for pos in exchange.base_positions[tuple(colors)]:
        if exchange.new_shapes.get(pos) == s:
            return exchange.new_cells[pos]
    # The same shape elsewhere in the new tileset, if it mostly agrees with the color map
    best, score = None, -1
    for pos in exchange.positions_by_shape.get(s, ()):
        agree = sum(1 for a, b in zip(colors, exchange.new_cells[pos]) if exchange.color_map.get(a) == b)
        if agree > score:
            best, score = pos, agree
    if best is not None and score >= 0.75 * len(colors):
        return exchange.new_cells[best]
    return None

def recolor_sheet(image: Image.Image, exchange: Exchange, stats: Counter, missing: Counter) -> Image.Image:
    rgba = image.convert('RGBA')
    px = rgba.load()
    width, height = rgba.size
    done = set()  # Pixels of tiles copied whole
    for ty in range(height // TILE):
        for tx in range(width // TILE):
            coords = [(tx * TILE + x, ty * TILE + y) for y in range(TILE) for x in range(TILE)]
            if any(px[c][3] != 255 for c in coords):
                continue
            colors = [px[c][:3] for c in coords]
            if len(set(colors)) < MIN_TILE_COLORS:
                continue
            # A tile any cell of which is in the base main image is found there instead
            cells = [[px[tx * TILE + cx + x, ty * TILE + cy + y][:3] for y in range(CELL) for x in range(CELL)]
                     for cy in (0, CELL) for cx in (0, CELL)]
            if any(tuple(cell) in exchange.base_positions for cell in cells):
                continue
            matches = exchange.tiles_by_shape.get(shape(colors), [])
            if len(matches) == 1:
                stats['copied'] += len(coords)
                for c, t in zip(coords, matches[0]):
                    px[c] = t + (255,)
                done.update(coords)
    for ty in range((height + CELL - 1) // CELL):
        for tx in range((width + CELL - 1) // CELL):
            coords = [(tx * CELL + x, ty * CELL + y) for y in range(CELL) for x in range(CELL)
                      if tx * CELL + x < width and ty * CELL + y < height]
            if coords[0] in done:
                continue
            colors = [px[c][:3] for c in coords]
            alphas = [px[c][3] for c in coords]
            if not any(alphas):
                continue
            target = None
            if len(coords) == CELL * CELL and len(set(colors)) > 1:
                target = _matching_cell(colors, exchange)
            if target is not None:
                stats['copied'] += len(coords)
                for c, t, a in zip(coords, target, alphas):
                    px[c] = t + (a,)
                continue
            for c, color, a in zip(coords, colors, alphas):
                if not a:
                    continue
                if color == BLACK:
                    continue
                new_color = exchange.color_map.get(color)
                if new_color is not None and new_color != BLACK:
                    px[c] = new_color + (a,)
                    stats['mapped'] += 1
                else:
                    stats['missing'] += 1
                    missing[color] += 1
    return rgba

def _lch(color: Color) -> Tuple[float, float, float]:
    """Oklab lightness, chroma and hue"""
    L, a, b = rgb_to_oklab(color[0] << 16 | color[1] << 8 | color[2])
    return L, math.hypot(a, b), math.atan2(b, a)

def sheet_changes(sheets: List[Tuple[Image.Image, Image.Image]]) -> Dict[Color, Color]:
    """The color each color of the old sheets most often became in their new sheets, at the same places"""
    votes = defaultdict(Counter)
    for old, new in sheets:
        for p, q in zip(old.convert('RGBA').get_flattened_data(), new.convert('RGBA').get_flattened_data()):
            if p[3] and q[3] and p[:3] != BLACK:
                votes[p[:3]][q[:3]] += 1
    return {color: v.most_common(1)[0][0] for color, v in votes.items()}

def follow(color: Color, changes: Dict[Color, Color]) -> Color:
    """color changed as the color of changes nearest it in lightness changed (see the module docstring)"""
    L, C, hue = _lch(color)
    anchor = min(changes, key=lambda c: (abs(_lch(c)[0] - L), c))
    anchor_L, anchor_C, _ = _lch(anchor)
    new_L, new_C, _ = _lch(changes[anchor])
    if anchor_C > 0.02:  # A grey anchor has no saturation to lose
        C *= min(1.0, new_C / anchor_C)
    rgb = oklab_to_rgb((L + new_L - anchor_L, C * math.cos(hue), C * math.sin(hue)))
    return (rgb >> 16, rgb >> 8 & 0xFF, rgb & 0xFF)

def follow_hand_colors(base: Image.Image, recolored: Image.Image, missing: Counter, changes: Dict[Color, Color]) -> Dict[Color, Color]:
    """Recolors in place the pixels of recolored left in a hand-drawn color of base"""
    followed = {color: follow(color, changes) for color in missing}
    base_px, px = base.convert('RGBA').load(), recolored.load()
    for y in range(recolored.height):
        for x in range(recolored.width):
            # A pixel left as it was, in a color nothing found
            if px[x, y] == base_px[x, y] and px[x, y][3] and px[x, y][:3] in followed:
                px[x, y] = followed[px[x, y][:3]] + (px[x, y][3],)
    return followed

def swap_roles(base: Image.Image, recolored: Image.Image, swaps: Dict[Color, Color], color_map: Dict[Color, Color]):
    """Recolors in place each pixel of recolored whose color in base is swapped, in the color its swap took"""
    new_colors = {color: color_map[other] for color, other in swaps.items() if other in color_map}
    base_px, px = base.convert('RGBA').load(), recolored.load()
    for y in range(recolored.height):
        for x in range(recolored.width):
            color = base_px[x, y]
            if color[3] and color[:3] in new_colors:
                px[x, y] = new_colors[color[:3]] + (color[3],)

def repair_unused_colors(tileset: Image.Image, donor: Image.Image, maps: List[Image.Image]) -> Dict[Color, Color]:
    """Recolors in place each color of tileset that none of maps uses. A GBA tileset's
    sub-palettes that its chapter never draws with may hold placeholder colors; donor, another
    palette of the same object set, colors them for real. Each takes the donor's color at its
    pixels, moved toward the tileset's own colors: as far as the donor's nearest color the maps
    use moved to become the tileset's (palette_blending.ColorMap's guess)."""
    assert maps, '--repair-from needs the maps drawn with the tileset (--used-in)'
    used = set()
    for m in maps:
        used.update(m.convert('RGB').get_flattened_data())
    unused_votes = defaultdict(Counter)  # Key: unused color, Value: the donor's colors at its pixels
    used_votes = defaultdict(Counter)  # Key: the donor's color, Value: the used colors at its pixels
    for p, q in zip(tileset.get_flattened_data(), donor.convert('RGB').get_flattened_data()):
        if p == BLACK or q == BLACK:
            continue
        if p in used:
            used_votes[q][p] += 1
        else:
            unused_votes[p][q] += 1
    donor_to_tileset = ColorMap({_rgb(q): _rgb(v.most_common(1)[0][0]) for q, v in used_votes.items()})
    repairs = {}
    for color, v in unused_votes.items():
        donor_color = v.most_common(1)[0][0]
        repairs[color] = _color(donor_to_tileset[_rgb(donor_color)])
    px = tileset.load()
    for y in range(tileset.height):
        for x in range(tileset.width):
            if px[x, y] in repairs:
                px[x, y] = repairs[px[x, y]]
    return repairs

def _rgb(color: Color) -> int:
    return color[0] << 16 | color[1] << 8 | color[2]

def _color(rgb: int) -> Color:
    return (rgb >> 16, rgb >> 8 & 0xFF, rgb & 0xFF)

def _parse_color(text: str) -> Color:
    return tuple(int(v) for v in text.split(','))

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('base_folder')
    parser.add_argument('new_tileset')
    parser.add_argument('out_folder')
    parser.add_argument('--main', default='main.png', help="the base folder's main image")
    parser.add_argument('--alias', action='append', default=[], help='HAND_COLOR=BASE_COLOR, each as R,G,B')
    parser.add_argument('--repair-from', help='a tileset of the same layout to take colors no map uses from')
    parser.add_argument('--used-in', nargs='+', default=[], help='the FE8 maps drawn with the new tileset')
    parser.add_argument('--dry', action='store_true')
    args = parser.parse_args()

    new_tileset = Image.open(args.new_tileset).convert('RGB')
    if args.repair_from:
        repaired = repair_unused_colors(new_tileset, Image.open(args.repair_from), [Image.open(m) for m in args.used_in])
        print('Repaired', repaired)
    exchange = build_exchange(os.path.join(args.base_folder, args.main), new_tileset)
    for alias in args.alias:
        hand, base = alias.split('=')
        exchange.color_map[_parse_color(hand)] = exchange.color_map[_parse_color(base)]
    if not args.dry:
        os.makedirs(args.out_folder, exist_ok=True)

    names = [os.path.basename(path) for path in sorted(glob.glob(os.path.join(args.base_folder, '*.png')))]
    names.remove(args.main)
    # Sheets that follow others go after them
    names.sort(key=lambda name: name in FOLLOWS)
    recolored: Dict[str, Tuple[Image.Image, Image.Image]] = {}  # Key: name, Value: (image, new image)

    total = Counter()
    for name in names:
        stats, missing = Counter(), Counter()
        image = Image.open(os.path.join(args.base_folder, name))
        new_image = recolor_sheet(image, exchange, stats, missing)
        recolored[name] = (image, new_image)
        n = max(1, sum(stats.values()))
        print(f"{name:22s} copied={stats['copied'] / n:.2f} mapped={stats['mapped'] / n:.2f} "
              f"missing={stats['missing'] / n:.3f} {[c for c, _ in missing.most_common(5)]}")
        if name in FOLLOWS and missing:
            changes = sheet_changes([recolored[reference] for reference in FOLLOWS[name]])
            followed = follow_hand_colors(image, new_image, missing, changes)
            print(f"{'':22s} followed {', '.join(FOLLOWS[name])}: {followed}")
        for sheets, swaps in ROLE_SWAPS.items():
            if name in sheets:
                swap_roles(image, new_image, swaps, exchange.color_map)
        total.update(stats)
        if not args.dry:
            if image.mode != 'RGBA' and new_image.getchannel('A').getextrema()[0] == 255:
                new_image = new_image.convert('RGB')
            new_image.save(os.path.join(args.out_folder, name))
    n = max(1, sum(total.values()))
    print('Total', {k: round(v / n, 3) for k, v in total.items()})
    if not args.dry:
        new_tileset.save(os.path.join(args.out_folder, 'main.png'))

if __name__ == '__main__':
    main()
