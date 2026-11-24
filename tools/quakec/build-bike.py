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
PALETTE = (5, 38, 181, 240, 207, 216, 249, 10)
# Indices match bike-steering-pose in examples/bike.scm.
STEERING_YAWS = (0, -12, -22, -32, 12, 22, 32)
STEERING_AXIS_X = 11
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
        normal = self.nearest_normal(cross)
        first = len(self.vertices)
        self.vertices.extend((point, normal, material) for point in points)
        # Stock alias triangles wind clockwise from the outside.
        self.triangles.extend((1, first, first + i + 1, first + i) for i in range(1, len(points) - 1))

    def nearest_normal(self, direction):
        return max(range(len(self.normals)), key=lambda i: sum(x * y for x, y in zip(direction, self.normals[i])))

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

    def steering_pose(self, yaw, steering):
        if yaw == 0:
            return self.vertices
        cosine, sine = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))

        def rotate(point):
            x, y, z = point
            return x * cosine - y * sine, x * sine + y * cosine, z

        first, last = steering
        front = self.vertices[first:last]
        normals = {index: self.nearest_normal(rotate(self.normals[index]))
                   for index in {normal for _, normal, _ in front}}
        turned = []
        for (x, y, z), normal, material in front:
            rx, ry, rz = rotate((x - STEERING_AXIS_X, y, z))
            turned.append(((rx + STEERING_AXIS_X, ry, rz), normals[normal], material))
        return self.vertices[:first] + turned + self.vertices[last:]

    def write(self, output, *, steering=None):
        poses = [self.steering_pose(yaw, steering) for yaw in STEERING_YAWS] if steering else [self.vertices]
        names = ['bike' if index == 0 else f'bike{index}' for index in range(len(poses))]
        self.write_poses(output, list(zip(names, poses)), PALETTE)

    def write_poses(self, output, named_poses, palette):
        output.write_bytes(self.encode_poses(named_poses, palette))

    def encode_poses(self, named_poses, palette, animations=None, skins=()):
        if not named_poses or not self.vertices or not 1 <= len(palette) <= 8:
            raise ValueError('stock alias model requires geometry, poses, and up to eight palette colors')
        # Extra skins recolor the same materials. Stock MDL skins share one layout.
        skins = [palette, *skins]
        if any(len(skin) != len(palette) for skin in skins) or len(skins) > 32:
            raise ValueError('each extra skin must recolor every palette entry')
        if len(self.vertices) > 2000 or len(self.triangles) > 2048:
            raise ValueError('model exceeds stock alias vertex or triangle limits')
        if any(not isinstance(color, int) or not 0 <= color <= 255 for skin in skins for color in skin):
            raise ValueError('palette colors must be byte indices')
        if any(not 0 <= material < len(palette) for _, _, material in self.vertices):
            raise ValueError('a model face refers to a missing palette color')
        poses = [pose for _, pose in named_poses]
        if any(len(pose) != len(self.vertices) for pose in poses):
            raise ValueError('animation frames must keep the same topology')
        origin = tuple(math.floor(min(point[i] for pose in poses for point, _, _ in pose)) for i in range(3))
        size = tuple(max(point[i] - origin[i] for pose in poses for point, _, _ in pose) for i in range(3))
        scales = tuple(max(.25, axis / 255) for axis in size)
        radius = max(math.sqrt(sum(coord * coord for coord in point)) for pose in poses for point, _, _ in pose)
        clips = list((animations or {}).values())
        grouped = {name for sequence, _ in clips for name in sequence}
        singles = [name for name, _ in named_poses if name not in grouped]
        data = bytearray(struct.pack('<4si3f3ff3f8if', b'IDPO', 6, *scales, *origin,
                                     radius, 0., 0., 22., len(skins), 32, 32, len(self.vertices),
                                     len(self.triangles), len(clips)+len(singles), 0, 0, 1.))
        for skin in skins:
            data += struct.pack('<i', 0)
            data += bytes(skin[min(x // 4, len(skin) - 1)] for _ in range(32) for x in range(32))
        for _, _, material in self.vertices:
            data += struct.pack('<3i', 0, 2 + 4 * material, 4)
        for triangle in self.triangles:
            data += struct.pack('<4i', *triangle)
        frames = {}
        for name, pose in named_poses:
            encoded = name.encode('ascii')
            if not 1 <= len(encoded) <= 15 or b'\0' in encoded:
                raise ValueError('frame names must contain 1–15 ASCII bytes')
            points = [tuple(round((point[i] - origin[i]) / scales[i]) for i in range(3)) + (normal,)
                      for point, normal, _ in pose]
            low = tuple(min(point[i] for point in points) for i in range(3))
            high = tuple(max(point[i] for point in points) for i in range(3))
            frame = struct.pack('<8B16s', *low, 0, *high, 0, encoded) + bytes(
                channel for point in points for channel in point)
            frames[name] = low, high, frame
        for sequence, fps in clips:
            members = [frames[name] for name in sequence]
            low = tuple(map(min, zip(*(member[0] for member in members))))
            high = tuple(map(max, zip(*(member[1] for member in members))))
            data += struct.pack('<2i8B', 1, len(members), *low, 0, *high, 0)
            # Quake stores cumulative frame end times.
            data += struct.pack(f'<{len(members)}f', *(i / fps for i in range(1, len(members)+1)))
            for _, _, frame in members:
                data += frame
        for name in singles:
            data += struct.pack('<i', 0) + frames[name][2]
        return data


def bike(normals):
    model = Model(normals)
    model.wheel(-17)
    for start, end in (((-17, -15), (-8, 0)), ((-17, -15), (0, -11)),
                       ((0, -11), (-8, 0)), ((0, -11), (12, 1)),
                       ((-8, 0), (12, 1))):
        model.strut(start, end, 1.25, 4)
    model.box((-13, -3.2, 0), (-4, 3.2, 2), 0)
    model.box((-15, -2, -.5), (-13, 2, 1.5), 3)

    first = len(model.vertices)
    model.wheel(17)
    model.strut((17, -15), (11, 6), 1.25, 4)
    model.box((9, -11, 5), (12, 11, 7), 2)
    model.box((8, -13, 4), (13, -8, 8), 3)
    model.box((8, 8, 4), (13, 13, 8), 3)
    model.box((13, -2, 2), (15, 2, 5), 6)
    return model, (first, len(model.vertices))


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
    model, steering = bike(normals)
    model.write(models / 'bike.mdl')
    model.box((-11, -4.5, 1), (-4, 4.5, 11), 5)
    model.box((-9, -5, 10), (1, 5, 21), 5)
    model.box((-2, -4.5, 21), (7, 4.5, 30), 7)
    model.box((6, -3.8, 23), (8, 3.8, 27), 3)
    model.box((0, -7, 12), (11, -4, 16), 5)
    model.box((0, 4, 12), (11, 7, 16), 5)
    model.box((-9, -7, -8), (-3, -4, 5), 5)
    model.box((-9, 4, -8), (-3, 7, 5), 5)
    model.write(models / 'r_bike.mdl', steering=steering)
    # A networked view entity needs a model index. A zero-area triangle stays invisible.
    camera = Model(normals)
    camera.face(((0, 0, 0), (0, 0, 0), (0, 0, 0)), 0)
    camera.write(models / 'bikecam.mdl')
    write_skid(directory / 'sound' / 'misc' / 'bikeskid.wav')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    build(parser.parse_args().directory)
