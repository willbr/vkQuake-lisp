#!/usr/bin/env python3
"""Generate seamless stock Quake textures from editable, seeded recipes."""
import argparse
from dataclasses import asdict, dataclass, field, replace
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re
import struct
import zlib

from preview_server import PreviewHandler
from quake_assets import encode_miptex, encode_wad, read_palette, write_file
from texture_pipeline import BLENDS, FILTERS, MAX_STAGES, SOURCES, STAGE_TYPES, Stage, render

ROOT = Path(__file__).resolve().parents[2]
STOCK_PALETTE = '6b20b5bc4ea965ef1852b05670d043ca16148a0ecad4e63028121c8aebc268fe'
PAK_NAMES = (
    Path('id1/pak0.pak'),
    ROOT / 'build/quakec/run/id1/pak0.pak',
)
SIZES = (32, 64, 128, 256)
# Each stock ramp is ordered from shadow to highlight. Ambient material
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
    name: str = 'gen_texture'
    ramp: str = 'steel'
    width: int = 64
    height: int = 64
    seed: int = 1
    colors: tuple[int, ...] = ()
    stages: tuple[Stage, ...] = field(default_factory=lambda: (Stage('fractal'),))

    def __post_init__(self):
        if not isinstance(self.name, str) or not re.fullmatch(r'[a-z0-9_]{1,15}', self.name):
            raise ValueError('use 1–15 lowercase letters, digits, or underscores for the texture name')
        if not isinstance(self.ramp, str) or self.ramp not in RAMPS:
            raise ValueError('unknown Quake palette ramp')
        if any(type(value) is not int or value not in SIZES for value in (self.width, self.height)):
            raise ValueError('width and height must be 32, 64, 128, or 256')
        if type(self.seed) is not int or not 0 <= self.seed < 2**32:
            raise ValueError('seed must be an unsigned 32-bit integer')
        if (not isinstance(self.colors, (tuple, list)) or len(self.colors) > 256
                or any(type(index) is not int or not 0 <= index <= 255 for index in self.colors)
                or len(set(self.colors)) != len(self.colors)):
            raise ValueError('colors must be an array of distinct Quake palette indices from 0 to 255')
        if not isinstance(self.stages, (list, tuple)) or len(self.stages) > MAX_STAGES:
            raise ValueError(f'stages must be an array of up to {MAX_STAGES} sources or filters')
        object.__setattr__(self, 'colors', tuple(self.colors))
        object.__setattr__(self, 'stages', tuple(map(Stage.parse, self.stages)))

    def updated(self, fields):
        if not isinstance(fields, dict):
            raise ValueError('expected a texture recipe object')
        if fields.keys() & {'material', 'wear', 'scale'}:
            raise ValueError('material preset recipes use the original texture editor format')
        if fields.keys() - self.__dataclass_fields__.keys():
            raise ValueError('unknown texture recipe field')
        return replace(self, **fields)

    @property
    def indices(self):
        return self.colors or RAMPS[self.ramp][1]


def stock_palette(path=None):
    if path is None:
        path = next((candidate for candidate in PAK_NAMES if candidate.is_file()), None)
    if path is None:
        raise ValueError('supply Quake pak0.pak or gfx/palette.lmp with --palette')
    palette = read_palette(path)
    if sha256(bytes(channel for color in palette for channel in color)).hexdigest() != STOCK_PALETTE:
        raise ValueError(f'{path} does not contain the stock Quake palette')
    return palette


def generate_pixels(recipe):
    values = render(recipe.stages, recipe.width, recipe.height, recipe.seed)
    colors = recipe.indices
    return bytes(colors[min(len(colors) - 1, int(value * len(colors)))] for value in values)


def generate_mips(recipe, palette):
    base = generate_pixels(recipe)
    # Filter RGB in the set of indices actually used by the surface. Averaging
    # the index numbers would jump between unrelated parts of the Quake palette.
    colors = tuple((index, 4 * red, 4 * green, 4 * blue)
                   for index in sorted(set(base)) for red, green, blue in (palette[index],))

    @lru_cache(maxsize=None)
    def filtered(block):
        red = green = blue = 0
        for index in block:
            r, g, b = palette[index]
            red, green, blue = red + r, green + g, blue + b

        def distance(color):
            _, r, g, b = color
            dr, dg, db = r - red, g - green, b - blue
            return dr * dr + dg * dg + db * db

        return min(colors, key=distance)[0]

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
            stages = {kind: {'label': label, 'parameters': {key: asdict(param) for key, param in params.items()}}
                      for kind, (label, params) in STAGE_TYPES.items()}
            self.respond({'sources': list(SOURCES), 'filters': list(FILTERS), 'stages': stages,
                          'blends': BLENDS, 'max_stages': MAX_STAGES,
                          'ramps': {key: {'label': label, 'indices': indices}
                                    for key, (label, indices) in RAMPS.items()},
                          'sizes': SIZES, 'palette': self.viewer.request('palette'),
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
