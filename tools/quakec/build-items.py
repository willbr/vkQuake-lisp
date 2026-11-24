#!/usr/bin/env python3
"""Build the mod's pickup and crate BSP models with the pinned map tools.

Each item is one box brush, centered over its entity and resting on the
entity's floor 24 units below the origin, with generated side and top
textures. Lights around the box bake its lightmap; vis is skipped because a
lone model has nothing to cull."""
import argparse
from importlib import import_module
from pathlib import Path
import shutil
import subprocess
import tempfile

from map_editor import Brush, Face, box, coordinates, quoted
from quake_assets import encode_wad

signal = import_module('build-signal')


def stripes(base, ink, x, y, period, width):
    return ink if (x + y) % period < width else base


def frame(pixel):
    def framed(x, y):
        return 4 if min(x, y, 63 - x, 63 - y) < 3 else pixel(x, y)
    return framed


def health_side(x, y):
    if 26 <= x < 38 and 14 <= y < 50 or 14 <= x < 50 and 26 <= y < 38:
        return 73
    return 12 + ((x * 3 + y * 5) % 23 == 0)


def shells_side(x, y):
    band = y // 8 % 2
    return 104 if 6 <= y % 16 < 10 else (114 if band else 116)


def shells_top(x, y):
    cx, cy = x % 16 - 8, y % 16 - 8
    return 111 if cx * cx + cy * cy < 30 else (4 if cx * cx + cy * cy < 42 else 6)


def rockets_side(x, y):
    return 231 if 28 <= y < 36 else 7 + (x // 16) % 2


def cells_side(x, y):
    bolt = abs((x - 32) - (y % 32 - 16) // 2) < 3 and 8 < y < 56
    return 2 if bolt else 196 - (y // 16) % 2


def crate_side(x, y):
    if min(x, y, 63 - x, 63 - y) < 5 or abs(x - y) < 4 or abs(x + y - 63) < 4:
        return 122
    return 117 + (y // 8) % 2


TEXTURES = {
    'item_med': frame(health_side), 'item_medt': frame(health_side),
    'item_shl': frame(shells_side), 'item_shlt': shells_top,
    'item_rkt': frame(rockets_side), 'item_rktt': lambda x, y: 231 if (x - 32) ** 2 + (y - 32) ** 2 < 200 else 6,
    'item_cel': frame(cells_side), 'item_celt': frame(lambda x, y: 194),
    'item_box': crate_side, 'item_boxt': crate_side,
}
# File name, half width, height, side texture, top texture.
ITEMS = (
    ('b_health', 16, 16, 'item_med', 'item_medt'),
    ('b_shells', 12, 24, 'item_shl', 'item_shlt'),
    ('b_rocket', 8, 32, 'item_rkt', 'item_rktt'),
    ('b_cells', 12, 24, 'item_cel', 'item_celt'),
    ('b_crate', 16, 32, 'item_box', 'item_boxt'),
)


def item_map(half, height, side, top):
    brush = box((-half, -half, -24), (half, half, -24 + height), side)
    brush = Brush(tuple(Face(face.points, top, face.axes) if face.plane()[0][2] > 0.99 else face
                        for face in brush.faces))
    lights = ''.join('{\n"classname" "light"\n"origin" "%s"\n"light" "260"\n}\n' % coordinates(spot)
                     for spot in ((0, 0, 64), (96, 48, 24), (-96, -48, 24), (48, -96, 0), (-48, 96, 0)))
    return ('{\n' + f'{quoted("classname")} {quoted("worldspawn")}\n{quoted("wad")} {quoted("items.wad")}\n'
            + brush.text() + '}\n' + lights)


def build(directory):
    directory = Path(directory).resolve()
    (directory / 'maps').mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='qslisp-', dir='/tmp') as scratch:
        work = Path(scratch)
        binaries = signal.compile_tools(work)
        maps = work / 'quake/id1/maps'
        maps.mkdir(parents=True)
        lumps = {name.encode(): signal.texture(name.encode(), pixel) for name, pixel in TEXTURES.items()}
        (work / 'quake/id1/items.wad').write_bytes(encode_wad(lumps))
        for name, half, height, side, top in ITEMS:
            source = maps / f'{name}.map'
            source.write_text(item_map(half, height, side, top), encoding='ascii')
            with (work / f'{name}.log').open('w') as log:
                # A lone box with lights around it leaks by design; qbsp still writes it.
                subprocess.run([binaries / 'qbsp', source], cwd=work, stdout=log, stderr=subprocess.STDOUT, check=True)
                subprocess.run([binaries / 'light', '-extra', source.with_suffix('.bsp')], cwd=work,
                               stdout=log, stderr=subprocess.STDOUT, check=True)
            shutil.copyfile(source.with_suffix('.bsp'), directory / 'maps' / f'{name}.bsp')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='mod directory to receive maps/b_*.bsp')
    build(parser.parse_args().directory)
