#!/usr/bin/env python3
"""Generate the original Relay Annex sentry model in stock Quake MDL format."""
import argparse
from pathlib import Path
import struct

FACES = (
    ((0, 3, 2, 1), 84), ((4, 5, 6, 7), 5),
    ((0, 4, 7, 3), 143), ((1, 2, 6, 5), 52),
    ((0, 1, 5, 4), 104), ((3, 7, 6, 2), 32),
)
PALETTE = (175, 180, 185, 37, 236, 254)
PARTS = (
    ((-15, -15, 4), (13, 15, 12), 3),
    ((-12, -12, 12), (10, 12, 34), 0),
    ((-15, -15, 34), (12, 15, 42), 1),
    ((7, -9, 19), (15, 9, 30), 2),
    ((14, -6, 21), (17, 6, 28), 4),
    ((17, -2, 23), (18, 2, 26), 5),
)


def build(output):
    vertices, triangles, coordinates = [], [], []
    for low, high, material in PARTS:
        x, y, z = low
        xx, yy, zz = high
        corners = ((x, y, z), (xx, y, z), (xx, yy, z), (x, yy, z),
                   (x, y, zz), (xx, y, zz), (xx, yy, zz), (x, yy, zz))
        for positions, normal in FACES:
            start = len(vertices)
            for corner in positions:
                vertices.append((corners[corner], normal, material >= 4))
                coordinates.append((0, 2 + material * 4, 4))
            triangles.extend(((1, start, start + 1, start + 2), (1, start, start + 2, start + 3)))

    data = bytearray(struct.pack('<4si3f3ff3f8if', b'IDPO', 6, .25, .25, .25,
                                 -20., -20., 0., 48., 0., 0., 30., 1, 32, 32,
                                 len(vertices), len(triangles), 2, 0, 0, 1.))
    data += struct.pack('<i', 0)  # Single indexed skin.
    data += bytes(PALETTE[min(x // 4, len(PALETTE) - 1)] for _ in range(32) for x in range(32))
    for coord in coordinates:
        data += struct.pack('<3i', *coord)
    for triangle in triangles:
        data += struct.pack('<4i', *triangle)
    for frame, name in enumerate((b'patrol', b'alert')):
        points = [((x + 20 + (2 if lens and frame else 0)) * 4, (y + 20) * 4, z * 4, normal)
                  for (x, y, z), normal, lens in vertices]
        low = tuple(min(v[i] for v in points) for i in range(3))
        high = tuple(max(v[i] for v in points) for i in range(3))
        data += struct.pack('<i8B16s', 0, *low, 0, *high, 0, name)
        for point in points:
            data += struct.pack('<4B', *point)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    build(parser.parse_args().output)
