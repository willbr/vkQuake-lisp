"""Check the generated status bar art in a stock Quake screenshot."""
from importlib import import_module
from pathlib import Path
import struct

from challenge import require

gfx = import_module('build-gfx')


def read_pcx(path):
    """Decode the 8-bit run-length PCX that stock WritePCXfile writes."""
    data = path.read_bytes()
    xmin, ymin, xmax, ymax = struct.unpack_from('<4H', data, 4)
    width, height = xmax - xmin + 1, ymax - ymin + 1
    stride = struct.unpack_from('<H', data, 66)[0]
    pixels, at = bytearray(), 128
    while len(pixels) < stride * height:
        byte = data[at]
        at += 1
        if byte & 0xC0 == 0xC0:
            pixels += bytes([data[at]]) * (byte & 0x3F)
            at += 1
        else:
            pixels.append(byte)
    rows = [pixels[y * stride:y * stride + width] for y in range(height)]
    return width, height, rows


def region(rows, x, y, width, height):
    return [bytes(rows[y + dy][x:x + width]) for dy in range(height)]


def picture_rows(picture, x=0, y=0, width=None, height=None):
    width, height = width or picture.width, height or picture.height
    return [bytes(picture.pixels[(y + dy) * picture.width + x:(y + dy) * picture.width + x + width])
            for dy in range(height)]


def verify_status_bar(screenshot: Path):
    """The inventory bar sits 48 rows above the bottom at viewsize 100. Slot 1
    holds the selected shotgun; empty slot 4 shows the bar's own background."""
    width, height, rows = read_pcx(screenshot)
    art = gfx.replacements()
    top = height - 48
    require(region(rows, 0, top + 8, 24, 16) == picture_rows(art[b'INV2_SHOTGUN']),
            'the screenshot does not show the generated selected shotgun slot')
    require(region(rows, 72, top + 8, 24, 16) == picture_rows(art[b'IBAR'], 72, 8, 24, 16),
            'the screenshot does not show the generated inventory bar')
    require(region(rows, 112, top + 24, 24, 24) == picture_rows(art[b'FACE1']),
            'the screenshot does not show the generated face at full health')
