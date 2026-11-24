#!/usr/bin/env python3
"""Replace the stock status bar art with generated Lisp-mod art.

Reads gfx.wad from the player's own pak0.pak, keeps every lump the client
expects, and swaps in generated pictures for the bars, weapon slots, ammo,
face, keys, sigils, armor, and the continuation powerup. Also writes a
generated console background. Nothing from id's PAKs is committed: the output
is built next to the mod at launch time."""
import argparse
from pathlib import Path
import struct

from texture_editor import TextureRecipe, generate_pixels
from uplink_art import LETTERS

WAD_HEADER = struct.Struct('<4sii')
WAD_ENTRY = struct.Struct('<iiiBB2x16s')
QPIC = 0x42
# The software renderer draws status bar pictures opaque (Draw_Pic), so icons
# sit on a plain panel color instead of index 255.
BACKDROP = 149
DIGITS = {  # 3x5, high bit on the left.
    '1': (2, 6, 2, 2, 7), '2': (6, 1, 2, 4, 7), '3': (6, 1, 2, 1, 6), '4': (5, 5, 7, 1, 1),
    '5': (7, 4, 6, 1, 6), '6': (3, 4, 6, 5, 2), '7': (7, 1, 2, 2, 2),
}
LETTERS = {**LETTERS, 'D': (30, 17, 17, 17, 17, 17, 30), 'G': (15, 16, 16, 19, 17, 17, 15),
           'H': (17, 17, 17, 31, 17, 17, 17), 'F': (31, 16, 16, 30, 16, 16, 16),
           '-': (0, 0, 0, 31, 0, 0, 0), '&': (12, 18, 20, 8, 21, 18, 13), ' ': (0,) * 7}
# Slot lump name, glyphs, and accent color for keys 1-7.
WEAPONS = (
    ('SHOTGUN', 'S', 250), ('SSHOTGUN', 'L', 208), ('NAILGUN', 'P', 245), ('SNAILGUN', '', 4),
    ('RLAUNCH', 'B', 244), ('SRLAUNCH', 'R', 251), ('LIGHTNG', 'M&S', 192),
)


def read_pak_file(pak, wanted):
    data = pak.read_bytes()
    magic, directory, length = struct.unpack_from('<4sii', data)
    if magic != b'PACK':
        raise ValueError(f'{pak} is not a Quake PAK')
    for i in range(0, length, 64):
        name, offset, size = struct.unpack_from('<56sii', data, directory + i)
        if name.rstrip(b'\0').decode('ascii', 'replace') == wanted:
            return data[offset:offset + size]
    raise ValueError(f'{pak} does not contain {wanted}')


def read_wad(data):
    magic, count, table = WAD_HEADER.unpack_from(data)
    if magic != b'WAD2':
        raise ValueError('gfx.wad is not a WAD2 file')
    lumps = []
    for i in range(count):
        offset, disk, size, kind, compression, name = WAD_ENTRY.unpack_from(data, table + i * WAD_ENTRY.size)
        lumps.append((name.rstrip(b'\0'), kind, data[offset:offset + disk]))
    return lumps


def write_wad(lumps):
    body, directory = bytearray(), bytearray()
    for name, kind, payload in lumps:
        directory += WAD_ENTRY.pack(WAD_HEADER.size + len(body), len(payload), len(payload), kind, 0, name)
        body += payload
        body += b'\0' * (-len(body) % 4)
    return WAD_HEADER.pack(b'WAD2', len(lumps), WAD_HEADER.size + len(body)) + bytes(body) + bytes(directory)


class Picture:
    def __init__(self, width, height, fill=0):
        self.width, self.height = width, height
        self.pixels = bytearray([fill]) * (width * height)

    def put(self, x, y, color):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.pixels[y * self.width + x] = color

    def rect(self, x, y, w, h, color):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.put(xx, yy, color)

    def frame(self, x, y, w, h, color):
        for xx in range(x, x + w):
            self.put(xx, y, color)
            self.put(xx, y + h - 1, color)
        for yy in range(y, y + h):
            self.put(x, yy, color)
            self.put(x + w - 1, yy, color)

    def glyph(self, rows, x, y, color, width):
        for dy, bits in enumerate(rows):
            for dx in range(width):
                if bits & (1 << (width - 1 - dx)):
                    self.put(x + dx, y + dy, color)

    def text(self, word, x, y, color):
        for i, char in enumerate(word):
            self.glyph(LETTERS[char], x + i * 6, y, color, 5)

    def qpic(self):
        return struct.pack('<ii', self.width, self.height) + bytes(self.pixels)


def tile(recipe, width, height):
    """Fill a picture from a procedural texture recipe, tiled."""
    texture = TextureRecipe().updated(recipe)
    pixels = generate_pixels(texture)
    picture = Picture(width, height)
    for y in range(height):
        for x in range(width):
            picture.pixels[y * width + x] = pixels[(y % texture.height) * texture.width + x % texture.width]
    return picture


PANEL = {'name': 'hud_panel', 'width': 64, 'height': 64, 'seed': 77,
         'colors': list(range(155, 143, -1)),
         'stages': [{'kind': 'solid', 'amount': 100, 'blend': 'mix', 'params': {'value': 30}},
                    {'kind': 'fractal', 'amount': 18, 'blend': 'add',
                     'params': {'columns': 4, 'rows': 2, 'octaves': 3, 'gain': 40, 'seed_offset': 0}},
                    {'kind': 'grid', 'amount': 25, 'blend': 'multiply',
                     'params': {'columns': 8, 'rows': 2, 'gap': 6, 'stagger': 0}}]}
CONSOLE = {'name': 'hud_console', 'width': 64, 'height': 64, 'seed': 91,
           'colors': list(range(186, 176, -1)) + [2, 1],
           'stages': [{'kind': 'solid', 'amount': 100, 'blend': 'mix', 'params': {'value': 12}},
                      {'kind': 'bands', 'amount': 18, 'blend': 'add',
                       'params': {'across': 0, 'down': 16, 'width': 20, 'phase': 0}},
                      {'kind': 'white', 'amount': 6, 'blend': 'add', 'params': {'seed_offset': 4}}]}


def bar(name):
    picture = tile(PANEL, 320, 24)
    picture.frame(0, 0, 320, 24, 147)
    if name == b'SBAR':
        # Armor, face, and ammo wells behind the stock number positions.
        for x in (0, 112, 224):
            picture.frame(x, 0, 24, 24, 150)
    return picture


def weapon(slot, glyphs, accent, state):
    """state: 0 owned, 1 selected, 2-6 the five pickup flash frames."""
    width = 48 if slot == 7 else 24
    picture = Picture(width, 16, 145 if state == 1 else 152)
    picture.frame(0, 0, width, 16, accent if state else 147)
    flash = state >= 2
    ink = 254 if state == 1 or (flash and state % 2) else (accent if glyphs else 6)
    picture.glyph(DIGITS[str(slot)], 2, 2, 15 if state else 10, 3)
    left = width - 2 - 6 * len(glyphs)
    picture.text(glyphs, left, 5, ink) if glyphs else None
    return picture


def ammo(kind):
    picture = Picture(24, 24, BACKDROP)
    if kind == 'SHELLS':
        for x in (4, 10, 16):
            picture.rect(x, 6, 4, 12, 79)
            picture.rect(x, 16, 4, 3, 111)
    elif kind == 'NAILS':
        for x in (5, 11, 17):
            picture.rect(x, 4, 2, 16, 245)
            picture.put(x, 3, 254)
    elif kind == 'ROCKET':
        for i in range(14):
            picture.put(4 + i, 18 - i, 231)
            picture.put(5 + i, 18 - i, 228)
        picture.rect(17, 4, 3, 3, 254)
    else:
        picture.rect(5, 6, 14, 14, 192)
        picture.rect(10, 3, 4, 3, 198)
        for i, x in enumerate((13, 11, 12, 10, 11, 9)):
            picture.put(x, 8 + i * 2, 254)
            picture.put(x, 9 + i * 2, 254)
    return picture


def face(level, mode):
    """An operator's helmet. level 1 is healthy, 5 nearly gone; mode tints it."""
    picture = Picture(24, 24, BACKDROP)
    helmet = {'pain': 73, 'quad': 210}.get(mode, 9)
    picture.rect(3, 2, 18, 20, helmet)
    picture.rect(5, 0, 14, 3, helmet)
    visor = {'quad': 223, 'pain': 79, 'invis': 2, 'invuln': 253}.get(mode, 186)
    picture.rect(5, 7, 14, 6, visor)
    picture.rect(6, 8, 3, 2, 254 if mode != 'invis' else 2)
    picture.frame(3, 2, 18, 20, 4)
    for crack in range(level - 1):
        x = 6 + crack * 3
        picture.put(x, 7 + crack % 2, 0)
        picture.put(x + 1, 9, 0)
        picture.put(x + 1, 10 + crack % 3, 0)
    picture.rect(9, 16, 6, 2, 5)
    return picture


def keycard(gold, flash=0):
    picture = Picture(16, 16, BACKDROP)
    picture.rect(2, 3, 12, 10, 104 if gold else 12)
    picture.rect(2, 5, 12, 2, 0)
    picture.rect(9, 9, 3, 2, 254 if flash % 2 else 15)
    return picture


def sigil(index):
    picture = Picture(8, 16, BACKDROP)
    color = (241, 244, 237, 251)[index]
    # A small lambda: a long stroke and a short leg.
    for y in range(3, 14):
        picture.put(1 + (y - 3) * 5 // 10, y, color)
    for y in range(8, 14):
        picture.put(5 - (y - 8) * 4 // 6, y, color)
    return picture


def thermometer(level):
    picture = Picture(24, 24, BACKDROP)
    color = (184, 108, 79)[level]
    picture.rect(10, 2, 4, 16, 9)
    picture.rect(9, 17, 6, 5, color)
    fill = (2, 7, 12)[level]
    picture.rect(11, 2 + fill, 2, 16 - fill, color)
    return picture


def beacon(flash=0):
    picture = Picture(16, 16, BACKDROP)
    picture.rect(5, 4, 6, 9, 210)
    picture.rect(7, 1, 2, 3, 223 if flash % 2 == 0 else 254)
    picture.frame(4, 3, 8, 11, 215)
    return picture


def replacements():
    out = {b'SBAR': bar(b'SBAR'), b'IBAR': bar(b'IBAR'), b'SCOREBAR': bar(b'SCOREBAR')}
    for slot, (lump, glyphs, accent) in enumerate(WEAPONS, 1):
        out[f'INV_{lump}'.encode()] = weapon(slot, glyphs, accent, 0)
        out[f'INV2_{lump}'.encode()] = weapon(slot, glyphs, accent, 1)
        for frame in range(1, 6):
            out[f'INVA{frame}_{lump}'.encode()] = weapon(slot, glyphs, accent, frame + 1)
    for kind in ('SHELLS', 'NAILS', 'ROCKET', 'CELLS'):
        out[f'SB_{kind}'.encode()] = ammo(kind)
    for level in range(1, 6):
        out[f'FACE{level}'.encode()] = face(level, '')
        out[f'FACE_P{level}'.encode()] = face(level, 'pain')
    out[b'FACE_QUAD'] = face(1, 'quad')
    out[b'FACE_INVIS'] = face(1, 'invis')
    out[b'FACE_INVUL1'] = out[b'FACE_INVUL2'] = face(1, 'invuln')
    out[b'FACE_INV2'] = face(1, 'invis')
    for key, gold in ((b'KEY1', False), (b'KEY2', True)):
        out[b'SB_' + key] = keycard(gold)
        for frame in range(1, 6):
            out[f'SBA{frame}_'.encode() + key] = keycard(gold, frame)
    for index in range(4):
        out[f'SB_SIGIL{index + 1}'.encode()] = sigil(index)
    for level in range(3):
        out[f'SB_ARMOR{level + 1}'.encode()] = thermometer(level)
    out[b'SB_QUAD'] = beacon()
    for frame in range(1, 6):
        out[f'SBA{frame}_QUAD'.encode()] = beacon(frame)
    return out


def console_background():
    picture = tile(CONSOLE, 320, 200)
    picture.text('LAMBDA', 124, 150, 245)
    picture.text('QUAKE LISP', 112, 162, 244)
    return picture


def build(pak, output):
    lumps = read_wad(read_pak_file(pak, 'gfx.wad'))
    names = {name for name, _, _ in lumps}
    generated = replacements()
    missing = set(generated) - names
    if missing:
        raise ValueError(f'gfx.wad lacks {sorted(missing)}')
    merged = []
    for name, kind, payload in lumps:
        if name in generated:
            original = struct.unpack_from('<ii', payload)
            picture = generated[name]
            if kind != QPIC or original != (picture.width, picture.height):
                raise ValueError(f'{name} changed size from the stock lump')
            payload = picture.qpic()
        merged.append((name, kind, payload))
    output.mkdir(parents=True, exist_ok=True)
    (output / 'gfx.wad').write_bytes(write_wad(merged))
    (output / 'gfx').mkdir(exist_ok=True)
    (output / 'gfx/conback.lmp').write_bytes(console_background().qpic())
    return generated


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pak', type=Path, help="the player's id1/pak0.pak")
    parser.add_argument('output', type=Path, help='mod directory to receive gfx.wad and gfx/conback.lmp')
    args = parser.parse_args()
    try:
        build(args.pak, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')
