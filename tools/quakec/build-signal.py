#!/usr/bin/env python3
"""Build the original Lisp maps and their indexed textures for stock Quake."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from quake_assets import encode_miptex, encode_wad, read_wad_textures
from uplink_art import fixtures

ROOT = Path(__file__).resolve().parents[2]
QUTILS = ROOT / 'third_party/quake-tools/qutils'
UPLINK_WAD = ROOT / 'examples/textures/uplink.wad'


def texture(name, pixel):
    size = 64
    base = bytes(pixel(x, y) for y in range(size) for x in range(size))
    levels = [base]
    for stride in (2, 4, 8):
        levels.append(bytes(base[y * size + x]
                            for y in range(stride // 2, size, stride)
                            for x in range(stride // 2, size, stride)))
    return encode_miptex(name, size, size, levels)


def floor_pixel(x, y):
    if x % 32 < 2 or y % 32 < 2:
        return 37
    return 42 + ((x ^ y) & 1)


def wall_pixel(x, y):
    if y < 4 or y >= 60:
        return 240 if x % 16 < 12 else 175
    if x < 3 or x >= 61 or y in (4, 59):
        return 175
    if 24 <= x < 40 and 24 <= y < 40:
        return 183 if (x + y) % 5 else 179
    return 181 + ((x * 7 + y * 3) % 29 == 0)


def trim_pixel(x, y):
    if min(x, y, 63 - x, 63 - y) < 4:
        return 170
    return 173 if (x + y) % 12 < 4 else 175


def goal_pixel(x, y):
    distance = max(abs(x - 32), abs(y - 32))
    if distance < 8:
        return 254
    if distance < 12 or 22 <= distance < 28:
        return 236
    return 97 if distance < 28 else 227


def write_wad(path, extra_wads=()):
    textures = {b'relay_floor': floor_pixel, b'relay_wall': wall_pixel,
                b'relay_trim': trim_pixel, b'relay_goal': goal_pixel}
    textures.update((name.encode('ascii'), pixel) for name, pixel in fixtures())
    lumps = {name: texture(name, pixel) for name, pixel in textures.items()}
    lumps.update(read_wad_textures(UPLINK_WAD))
    for wad in extra_wads:
        lumps.update(read_wad_textures(wad))
    path.write_bytes(encode_wad(lumps))


def build(output, level, source=None, extra_wads=()):
    if not QUTILS.is_dir():
        raise SystemExit('Missing map tools. Run ./tools/quakec/setup.sh first.')
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # Keep the scratch path outside the checkout. qbsp uses the first "quake"
    # in the absolute path to locate the mod's WAD.
    with tempfile.TemporaryDirectory(prefix='qslisp-', dir='/tmp') as directory:
        work = Path(directory)
        for group in ('COMMON', 'QBSP', 'LIGHT', 'VIS'):
            dest = work / group.lower()
            dest.mkdir()
            for tool_source in (QUTILS / group).iterdir():
                if tool_source.suffix in ('.C', '.H'):
                    shutil.copyfile(tool_source, dest / tool_source.name.lower())

        binaries = work / 'bin'
        binaries.mkdir()
        common = ['common/bspfile.c', 'common/cmdlib.c', 'common/mathlib.c']
        for name in ('qbsp', 'light', 'vis'):
            sources = sorted(str(path.relative_to(work)) for path in (work / name).glob('*.c'))
            subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu89', '-O2', '-fcommon',
                            '-include', 'unistd.h', '-Icommon', '-o', binaries / name,
                            *sources, *common, '-lm'], cwd=work, check=True)

        # qbsp locates the mod directory from the absolute .../quake/<mod>/ path.
        map_path = work / 'quake/id1/maps' / f'{level}.map'
        map_path.parent.mkdir(parents=True)
        shutil.copyfile(source or ROOT / 'examples' / map_path.name, map_path)
        write_wad(work / 'quake/id1/signal.wad', extra_wads)
        subprocess.run([binaries / 'qbsp', map_path], cwd=work, check=True)
        bsp = map_path.with_suffix('.bsp')
        subprocess.run([binaries / 'vis', bsp], cwd=work, check=True)
        subprocess.run([binaries / 'light', '-extra', bsp], cwd=work, check=True)
        shutil.copyfile(bsp, output)
    print(f'Built {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='output BSP file')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--map', choices=('signal', 'annex', 'uplink'))
    source.add_argument('--source', type=Path, help='stock .map file to compile')
    parser.add_argument('--wad', type=Path, action='append', default=[],
                        help='include textures from an additional WAD2 (repeatable)')
    args = parser.parse_args()
    try:
        build(args.output, args.source.stem if args.source else args.map or 'signal', args.source, args.wad)
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')
