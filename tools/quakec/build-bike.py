#!/usr/bin/env python3
"""Build the Annex bicycle models and skid sound for stock Quake."""
import argparse
import math
from pathlib import Path
import random
import re
import struct
import wave


NORMALS = Path(__file__).resolve().parents[2] / 'third_party/quake/WinQuake/anorms.h'
PALETTE = (18, 38, 181, 233, 207, 110, 249, 15)
BOX_FACES = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 4, 7, 3),
             (1, 2, 6, 5), (0, 1, 5, 4), (3, 7, 6, 2))


class Model:
    def __init__(self, normals):
        self.normals = normals
        self.vertices = []
        self.triangles = []

    def face(self, points, material):
        start, second, third = points[:3]
        a, b = [tuple(later[i] - start[i] for i in range(3)) for later in (second, third)]
        cross = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
        normal = max(range(len(self.normals)), key=lambda i: sum(x * y for x, y in zip(cross, self.normals[i])))
        first = len(self.vertices)
        self.vertices.extend((point, normal, material) for point in points)
        self.triangles.extend((1, first, first + i, first + i + 1) for i in range(1, len(points) - 1))

    def box(self, low, high, material):
        x, y, z = low
        xx, yy, zz = high
        self.box_faces(((x, y, z), (xx, y, z), (xx, yy, z), (x, yy, z),
                        (x, y, zz), (xx, y, zz), (xx, yy, zz), (x, yy, zz)), material)

    def box_faces(self, corners, material):
        for indices in BOX_FACES:
            self.face(tuple(corners[i] for i in indices), material)

    def strut(self, start, end, thickness, material):
        x, z = start
        xx, zz = end
        distance = math.hypot(xx - x, zz - z)
        dx, dz = (z - zz) * thickness / distance, (xx - x) * thickness / distance
        self.box_faces(((x-dx, -thickness, z-dz), (xx-dx, -thickness, zz-dz),
                        (xx-dx, thickness, zz-dz), (x-dx, thickness, z-dz),
                        (x+dx, -thickness, z+dz), (xx+dx, -thickness, zz+dz),
                        (xx+dx, thickness, zz+dz), (x+dx, thickness, z+dz)), material)

    def wheel(self, x):
        z = -15
        spokes = [(math.cos(i * math.tau / 12), math.sin(i * math.tau / 12)) for i in range(12)]
        outer = [(x + 9 * dx, z + 9 * dz) for dx, dz in spokes]
        inner = [(x + 6.6 * dx, z + 6.6 * dz) for dx, dz in spokes]

        def edge(point, side):
            return point[0], side * 2.1, point[1]

        for i in range(12):
            j = (i + 1) % 12
            a, b, c, d = outer[i], outer[j], inner[i], inner[j]
            self.face((edge(a, -1), edge(a, 1), edge(b, 1), edge(b, -1)), 0 if i % 2 else 1)
            self.face((edge(a, -1), edge(b, -1), edge(d, -1), edge(c, -1)), 1)
            self.face((edge(a, 1), edge(c, 1), edge(d, 1), edge(b, 1)), 1)
            self.face((edge(c, -1), edge(d, -1), edge(d, 1), edge(c, 1)), 2)
        for point in inner[::3]:
            self.strut((x, z), point, 0.48, 2)
        self.box((x-1.7, -2.5, z-1.7), (x+1.7, 2.5, z+1.7), 3)

    def write(self, output):
        origin = tuple(math.floor(min(point[i] for point, _, _ in self.vertices)) for i in range(3))
        points = [tuple(round((point[i] - origin[i]) * 4) for i in range(3)) + (normal,)
                  for point, normal, _ in self.vertices]
        low = tuple(min(point[i] for point in points) for i in range(3))
        high = tuple(max(point[i] for point in points) for i in range(3))
        radius = max(math.sqrt(sum(coord * coord for coord in point)) for point, _, _ in self.vertices)
        data = bytearray(struct.pack('<4si3f3ff3f8if', b'IDPO', 6, .25, .25, .25, *origin,
                                     radius, 0., 0., 22., 1, 32, 32, len(points),
                                     len(self.triangles), 1, 0, 0, 1.))
        data += struct.pack('<i', 0)
        data += bytes(PALETTE[x // 4] for _ in range(32) for x in range(32))
        for _, _, material in self.vertices:
            data += struct.pack('<3i', 0, 2 + 4 * material, 4)
        for triangle in self.triangles:
            data += struct.pack('<4i', *triangle)
        data += struct.pack('<i8B16s', 0, *low, 0, *high, 0, b'bike')
        for point in points:
            data += struct.pack('<4B', *point)
        output.write_bytes(data)


def bike(normals):
    model = Model(normals)
    model.wheel(-17)
    model.wheel(17)
    for start, end in (((-17, -15), (-8, 0)), ((-17, -15), (0, -11)),
                       ((0, -11), (-8, 0)), ((0, -11), (12, 1)),
                       ((-8, 0), (12, 1)), ((17, -15), (11, 6))):
        model.strut(start, end, 1.25, 4)
    model.box((-13, -3.2, 0), (-4, 3.2, 2), 0)
    model.box((9, -8, 5), (12, 8, 7), 2)
    model.box((8, -9, 4), (13, -5, 8), 0)
    model.box((8, 5, 4), (13, 9, 8), 0)
    model.box((13, -2, 2), (15, 2, 5), 6)
    model.box((-15, -2, -.5), (-13, 2, 1.5), 3)
    return model


def handlebars(normals):
    model = Model(normals)
    model.box((18, -11, -10), (21, 11, -8), 2)
    model.box((17, -12, -11), (22, -7, -7), 0)
    model.box((17, 7, -11), (22, 12, -7), 0)
    model.box((18, -2.5, -20), (21, 2.5, -9), 4)
    model.box((20, -3.4, -10), (24, 3.4, -7.5), 5)
    model.box((21, -1.2, -7.5), (23, 1.2, -7), 6)
    return model


def write_skid(output):
    output.parent.mkdir(parents=True, exist_ok=True)
    rate = 11025
    source = random.Random(41)
    smoothed, last = 0, 0
    samples = bytearray()
    for i in range(rate // 3):
        t = i / rate
        smoothed = 0.75 * smoothed + 0.25 * source.uniform(-1, 1)
        grain = smoothed - last
        last = smoothed
        envelope = min(t * 62, 1) * (1 - 3 * t) ** 0.8
        chirp = math.sin(math.tau * (710 * t - 230 * t * t))
        samples.append(round(128 + envelope * (120 * grain + 24 * chirp * (0.6 + smoothed))))
    with wave.open(str(output), 'wb') as sound:
        sound.setparams((1, 1, rate, 0, 'NONE', 'not compressed'))
        sound.writeframes(samples)


def build(directory):
    normals = [tuple(map(float, point.split(','))) for point in re.findall(r'\{([\d., -]+)\}', NORMALS.read_text())]
    models = directory / 'progs'
    models.mkdir(parents=True, exist_ok=True)
    model = bike(normals)
    model.write(models / 'bike.mdl')
    model.box((-11, -4.5, 1), (-4, 4.5, 11), 5)
    model.box((-9, -5, 10), (1, 5, 21), 5)
    model.box((-2, -4.5, 21), (7, 4.5, 30), 7)
    model.box((6, -3.8, 23), (8, 3.8, 27), 3)
    model.box((0, -7, 12), (11, -4, 16), 5)
    model.box((0, 4, 12), (11, 7, 16), 5)
    model.box((-9, -7, -8), (-3, -4, 5), 5)
    model.box((-9, 4, -8), (-3, 7, 5), 5)
    model.write(models / 'r_bike.mdl')
    handlebars(normals).write(models / 'v_bike.mdl')
    write_skid(directory / 'sound' / 'misc' / 'bikeskid.wav')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    build(parser.parse_args().directory)
