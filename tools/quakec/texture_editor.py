#!/usr/bin/env python3
"""Generate seamless stock Quake textures from editable, seeded recipes."""
import argparse
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from hashlib import sha256
import json
import math
from pathlib import Path
import random
import re
import struct
import zlib

from preview_server import PreviewHandler
from quake_assets import encode_miptex, encode_wad, read_palette, write_file

ROOT = Path(__file__).resolve().parents[2]
STOCK_PALETTE = '6b20b5bc4ea965ef1852b05670d043ca16148a0ecad4e63028121c8aebc268fe'
PAK_NAMES = (
    Path('id1/pak0.pak'),
    ROOT / 'build/quakec/run/id1/pak0.pak',
)
SIZES = (32, 64, 128, 256)
SCALES = (1, 2, 4)
MATERIALS = {
    'stone': ('Stone blocks', 'sandstone'),
    'concrete': ('Concrete', 'steel'),
    'panel': ('Metal panels', 'steel'),
    'grate': ('Slotted grate', 'moss'),
    'hazard': ('Hazard stripes', 'amber'),
}
# Each material ramp is ordered from shadow to highlight. Ambient material
# colors stop below the fullbright range so Quake can light them normally.
RAMPS = {
    'steel': ('Steel', tuple(range(2, 14))),
    'slate': ('Slate', tuple(range(33, 45))),
    'moss': ('Moss', tuple(range(189, 177, -1))),
    'sandstone': ('Sandstone', tuple(range(174, 162, -1))),
    'rust': ('Rust', tuple(range(113, 125))),
    'amber': ('Amber', tuple(range(204, 192, -1))),
}


@dataclass(frozen=True)
class TextureRecipe:
    name: str = 'gen_panel'
    material: str = 'panel'
    ramp: str = 'steel'
    width: int = 64
    height: int = 64
    scale: int = 2
    wear: int = 45
    seed: int = 1

    def __post_init__(self):
        if not isinstance(self.name, str) or not re.fullmatch(r'[a-z0-9_]{1,15}', self.name):
            raise ValueError('use 1–15 lowercase letters, digits, or underscores for the texture name')
        if not isinstance(self.material, str) or self.material not in MATERIALS:
            raise ValueError('unknown material')
        if not isinstance(self.ramp, str) or self.ramp not in RAMPS:
            raise ValueError('unknown Quake palette ramp')
        if any(type(value) is not int or value not in SIZES for value in (self.width, self.height)):
            raise ValueError('width and height must be 32, 64, 128, or 256')
        if type(self.scale) is not int or self.scale not in SCALES:
            raise ValueError('pattern repeats must be 1, 2, or 4')
        if type(self.wear) is not int or not 0 <= self.wear <= 100:
            raise ValueError('wear must be an integer from 0 to 100')
        if type(self.seed) is not int or not 0 <= self.seed < 2**32:
            raise ValueError('seed must be an unsigned 32-bit integer')

    def updated(self, fields):
        if not isinstance(fields, dict) or fields.keys() - self.__dataclass_fields__.keys():
            raise ValueError('expected a recipe object with known fields')
        patch = fields.copy()
        material = patch.get('material', self.material)
        if isinstance(material, str) and material in MATERIALS and material != self.material:
            patch.setdefault('ramp', MATERIALS[material][1])
            if self.name == f'gen_{self.material}':
                patch.setdefault('name', f'gen_{material}')
        return replace(self, **patch)


def stock_palette(path=None):
    if path is None:
        path = next((candidate for candidate in PAK_NAMES if candidate.is_file()), None)
    if path is None:
        raise ValueError('supply Quake pak0.pak or gfx/palette.lmp with --palette')
    palette = read_palette(path)
    if sha256(bytes(channel for color in palette for channel in color)).hexdigest() != STOCK_PALETTE:
        raise ValueError(f'{path} does not contain the stock Quake palette')
    return palette


def noise_field(width, height, columns, rows, rng):
    """Sample periodic value noise at the texel centers."""
    lattice = [[rng.uniform(-1, 1) for _ in range(columns)] for _ in range(rows)]

    def axis(size, cells):
        for texel in range(size):
            pos = (texel + .5) * cells / size
            slot = int(pos)
            t = pos - slot
            yield slot, (slot + 1) % cells, t * t * (3 - 2 * t)

    xs = list(axis(width, columns))
    for top, bottom, v in axis(height, rows):
        row = [a + (b - a) * v for a, b in zip(lattice[top], lattice[bottom])]
        yield from (row[left] + (row[right] - row[left]) * u for left, right, u in xs)


def stone(x, y, scale, cloud, detail, grain, wear):
    row, v = divmod(2 * scale * y + .045 * detail, 1)
    _, u = divmod(scale * x + .5 * (int(row) % 2) + .04 * cloud, 1)
    edge = min(u, v, 1 - u, 1 - v)
    if edge < .042 + .021 * wear * detail:
        return .13 + .06 * grain
    bevel = (min(u, v) < min(1 - u, 1 - v)) - .5
    chips = -.28 * wear if grain < -.91 and detail < -.1 else 0
    return .56 + .15 * cloud + .12 * detail + .13 * wear * grain + chips + bevel * max(0, .10 - edge) * 5


def concrete(x, y, scale, cloud, detail, grain, wear):
    pitting = -.27 * wear if grain + detail * .34 < -.89 else 0
    crack = -.33 * wear if abs(detail + cloud * .4) < .026 and cloud < -.23 else 0
    return .65 + .19 * cloud + .11 * detail + .15 * wear * grain + pitting + crack


def panel(x, y, scale, cloud, detail, grain, wear):
    u, v = x * scale % 1, y * scale % 1
    edge = min(u, v, 1 - u, 1 - v)
    if edge < .042:
        return .09 + .05 * grain
    if edge < .085:
        return .81 if min(u, v) < min(1 - u, 1 - v) else .34
    dx = min(abs(u - .16), abs(u - .84))
    dy = min(abs(v - .16), abs(v - .84))
    if dx * dx + dy * dy < .0033:
        return .85 - dy * 5 + .10 * grain
    brushing = .050 * math.sin(y * math.tau * scale * 11 + detail)
    scrape = .23 * wear if grain > .94 and detail > .16 else 0
    return .55 + .12 * cloud + wear * (.12 * detail + .11 * grain) + brushing + scrape


def grate(x, y, scale, cloud, detail, grain, wear):
    row, v = divmod(y * 4 * scale, 1)
    u = (x * 2 * scale + .5 * (int(row) % 2)) % 1
    slot = ((u - .5) / .36) ** 6 + ((v - .5) / .28) ** 4
    if slot < 1:
        return .02 + .035 * grain
    if slot < 2.3:
        return (.78 if v > .5 else .29) + .08 * detail
    return .56 + .13 * cloud + wear * (.14 * grain + .13 * detail)


def hazard(x, y, scale, cloud, detail, grain, wear):
    v = y * scale % 1
    if min(v, 1 - v) < .10:
        return .28 + .13 * grain
    return .66 + .13 * cloud + .08 * detail + wear * .18 * grain


SURFACES = {'stone': stone, 'concrete': concrete, 'panel': panel, 'grate': grate, 'hazard': hazard}


def generate_pixels(recipe):
    width, height = recipe.width, recipe.height
    rng = random.Random(recipe.seed)
    coarse = noise_field(width, height, 2 * recipe.scale + 1, 2 * recipe.scale + 1, rng)
    fine = noise_field(width, height, 5 * recipe.scale + 1, 5 * recipe.scale + 1, rng)
    ramp = RAMPS[recipe.ramp][1]
    steel = RAMPS['steel'][1]
    shade = SURFACES[recipe.material]
    wear = recipe.wear / 100
    scale = recipe.scale
    pixels = bytearray(width * height)
    for i, (cloud, detail) in enumerate(zip(coarse, fine)):
        row, col = divmod(i, width)
        x, y = (col + .5) / width, (row + .5) / height
        grain = rng.uniform(-1, 1)
        colors = ramp
        if recipe.material == 'hazard':
            belt = .10 <= y * scale % 1 <= .90
            stripe = (scale * (3 * x + 2 * y)) % 1 < .48
            chipped = grain + detail * .6 < -1.48 + wear * .46
            if not (belt and stripe) or chipped:
                colors = steel
        value = shade(x, y, scale, cloud, detail, grain, wear)
        slot = min(len(colors) - 1, max(0, int(value * len(colors))))
        pixels[i] = colors[slot]
    return bytes(pixels)


def generate_mips(recipe, palette):
    base = generate_pixels(recipe)
    # Filter RGB in the set of indices actually used by the surface. Averaging
    # the index numbers would jump between unrelated parts of the Quake palette.
    colors = tuple((index, palette[index]) for index in sorted(set(base)))

    @lru_cache(maxsize=None)
    def filtered(block):
        sums = [sum(palette[index][channel] for index in block) for channel in range(3)]
        return min(colors, key=lambda color: sum((4 * value - total) ** 2
                                                for value, total in zip(color[1], sums)))[0]

    levels = [base]
    width, height = recipe.width, recipe.height
    for _ in range(3):
        previous = levels[-1]
        levels.append(bytes(
            filtered(tuple(sorted((previous[i], previous[i + 1],
                                   previous[i + width], previous[i + width + 1]))))
            for row in range(0, height, 2)
            for i in range(row * width, (row + 1) * width, 2)
        ))
        width //= 2
        height //= 2
    return tuple(levels)


def indexed_png(width, height, pixels, palette):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))

    header = struct.pack('>IIBBBBB', width, height, 8, 3, 0, 0, 0)
    colors = bytes(channel for rgb in palette for channel in rgb)
    scanlines = b''.join(b'\0' + pixels[i:i + width] for i in range(0, len(pixels), width))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'PLTE', colors)
            + chunk(b'IDAT', zlib.compress(scanlines)) + chunk(b'IEND', b''))


class TextureDocument:
    def __init__(self, recipe, palette):
        self.palette = palette
        self.recipe = recipe
        self.levels = generate_mips(recipe, palette)

    def apply(self, fields):
        recipe = self.recipe.updated(fields)
        if recipe != replace(self.recipe, name=recipe.name):
            self.levels = generate_mips(recipe, self.palette)
        self.recipe = recipe

    def png(self):
        return indexed_png(self.recipe.width, self.recipe.height, self.levels[0], self.palette)

    def wad(self):
        name = self.recipe.name.encode('ascii')
        return encode_wad({name: encode_miptex(name, self.recipe.width, self.recipe.height, self.levels)})

    def files(self):
        recipe = (json.dumps(asdict(self.recipe), indent=2) + '\n').encode('utf-8')
        return {'json': recipe, 'png': self.png(), 'wad': self.wad()}

    def export(self, directory):
        for suffix, data in self.files().items():
            write_file(directory / f'{self.recipe.name}.{suffix}', data)


class TexturePreviewHandler(PreviewHandler):
    resources = {
        '/recipe.json': ('recipe', 'application/json'),
        '/texture.png': ('png', 'image/png'),
        '/texture.wad': ('wad', 'application/octet-stream'),
    }

    def get_resource(self, url):
        if url.path == '/':
            self.respond({'materials': {key: label for key, (label, _) in MATERIALS.items()},
                          'ramps': {key: label for key, (label, _) in RAMPS.items()},
                          'sizes': SIZES, 'scales': SCALES,
                          'endpoints': ['/view', '/view.png', *self.resources]})
        elif url.path in self.resources:
            action, media = self.resources[url.path]
            self.respond(self.viewer.request(action), content_type=media)
        else:
            super().get_resource(url)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe', type=Path, nargs='?', help='open a saved texture JSON')
    parser.add_argument('--palette', type=Path, help='stock palette.lmp or pak0.pak')
    parser.add_argument('--output-dir', type=Path, default=Path('build/textures'))
    parser.add_argument('--port', type=int, help='start the localhost editor API while the window is open')
    parser.add_argument('--export', action='store_true', help='write JSON, indexed PNG, and WAD2 without opening the UI')
    args = parser.parse_args()
    if args.export and args.port is not None:
        parser.error('--port requires the editor window')
    try:
        recipe = TextureRecipe()
        if args.recipe is not None:
            recipe = recipe.updated(json.loads(args.recipe.read_text(encoding='utf-8')))
        document = TextureDocument(recipe, stock_palette(args.palette))
        if args.export:
            document.export(args.output_dir)
            print(f'Exported {recipe.name} to {args.output_dir.resolve()}')
        else:
            try:
                from texture_viewer import run_viewer
            except ModuleNotFoundError as error:
                if error.name != 'pyglet':
                    raise
                raise ValueError("Install 'pyglet>=2.1,<2.2' to open the texture editor.") from error
            run_viewer(document, args.output_dir.resolve(), args.port)
    except (ValueError, OSError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
