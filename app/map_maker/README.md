# Steps for making a new palette for the map maker

## Your tileset png is set up similarly to how the main png is organized in monastery_outdoors palette

1. Create a folder in map_maker/palettes/ with the name of your new palette.
2. Copy the files from another palette folder to your new palette folder

> Note: If you are making an indoor palette, then you would of course copy another indoor palette's files to your new palette folder.

3. We will be overwriting the files in your new folder with the colors of your main.png
4. Navigate to app/map_maker/scripts/simple_palette_exchanger.py
5. You will see in the middle of the script, three lines of importance:

```python
color_change_these_images = ['app/map_maker/palettes/monastery_outdoors/road.png'],
original_palette = 'app/map_maker/palettes/autumn_outdoors/main.png'
new_palette = 'app/map_maker/palettes/monastery_outdoors/main.png'
```

6. Modify `original_palette` to point to the original main.png of the folder you grabbed, for instance `'app/map_maker/palettes/monastery_outdoors/main.png'`.
7. Modify `new_palette` to point to your new main.png, which should be kept in some other location for now, so it doesn't get overwritten by the script.
8. Modify `color_change_these_images` to `['app/map_maker/palettes/{your_palette}/*.png]`
9. Run the python script from the main `lt-maker` directory: `python -m app.map_maker.scripts.palette_generation.simple_palette_exchanger`
10. Check that it made the expected changes to your new palette folder
11. If it checks out, modify the metadata.json file to match the correct value for your new palette.
12. Use it in the map maker!

## Your tileset png is an FE8 tileset that shares a layout with an existing palette's main.png

FE8 tilesets with the same object set (the first byte of names like `01004C03`, `1800191A`) share a layout and differ only in their colors. `cell_palette_exchanger.py` recolors a whole palette folder onto such a tileset in one command, and needs no editing:

```
python -m app.map_maker.scripts.palette_generation.cell_palette_exchanger app/map_maker/palettes/sacred_fields path/to/01004C03.png app/map_maker/palettes/{your_palette}
```

1. Pick the base folder whose main.png has the same layout as your tileset (sacred_fields for the `01` plains set, monastery_outdoors or monastery for `6C`, gawain for the `18` castle set).
2. Run it with `--dry` first. It prints, for each sprite sheet, how much of it was copied from cells of your tileset, how much was recolored through a color map, and which colors it could not find.
   - `copied` cells take your tileset's colors exactly, even where the GBA gives one base color different values in different places. A 16x16 sprite drawn in colors of its own (the sparse forest's tufts) is copied whole from your tileset when its shape is found there just once.
   - `mapped` pixels take the color the base color most often turns into. A sheet mostly `mapped` is drawn in the base palette's shapes, which your tileset may not have: check it by eye.
   - `missing` colors were drawn by hand into a sprite sheet and are left as they are, unless the sheet is in the script's `FOLLOWS` table: then they change as the FE8 sprites of the same terrain changed (sparse forest follows forest and thicket, so its tree outlines lighten and grey where the tileset's own trees do). `--alias R,G,B=R,G,B` instead gives such a color whatever another base color maps to.
   - The desert sheets then swap color roles as the script's `ROLE_SWAPS` table says, so the desert's base is the sand's base and the two meet without a seam, as in the Autumn palette.
   - If your tileset colors some tiles in nonsense colors (a GBA sub-palette its chapter never draws with, like 6C006D6E's cyan floors), add `--repair-from OTHER_TILESET --used-in CHAPTER_MAP.png ...`: every color none of the chapter maps uses takes the other tileset's color at the same pixels (same object set, another palette), moved toward your tileset's own colors.
3. Run it without `--dry`. It writes every sprite sheet and copies your tileset in as main.png.
4. Write the metadata.json, copying the base folder's (floor settings included, for an indoor palette).

