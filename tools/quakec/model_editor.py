#!/usr/bin/env python3
"""Build stock Quake MDL assets from a small JSON mesh and pose description."""
import argparse
from copy import deepcopy
from importlib import import_module
import json
import math
from pathlib import Path
import re
import struct

from map_editor import point
from quake_assets import read_palette, write_file

bike = import_module('build-bike')


def ring_mesh(model, part):
    x, y, z = point(part.get('origin', (0, 0, 0)))
    sides = part.get('sides', 8)
    if type(sides) is not int or not 3 <= sides <= 32:
        raise ValueError('a ring needs 3 to 32 sides')
    angle = math.radians(float(part.get('angle', 0)))
    circle = [(math.cos(angle + i*math.tau/sides), math.sin(angle + i*math.tau/sides))
              for i in range(sides)]
    sections = list(map(point, part['rings']))
    if (len(sections) < 2 or any(rx <= 0 or ry <= 0 for _, rx, ry in sections)
            or any(a[0] >= b[0] for a, b in zip(sections, sections[1:]))):
        raise ValueError('rings need positive radii at increasing heights')
    rings = [[(x + rx*u, y + ry*v, z + height) for u, v in circle] for height, rx, ry in sections]
    material = part['material']
    model.face(rings[0][::-1], material)
    for lower, upper in zip(rings, rings[1:]):
        for i in range(sides):
            j = (i+1) % sides
            model.face([lower[i], lower[j], upper[j], upper[i]], material)
    model.face(rings[-1], material)


def pose_values(value):
    if isinstance(value, dict):
        return point(value.get('offset', (0, 0, 0))), point(value.get('rotate', (0, 0, 0)))
    return point(value), (0, 0, 0)


def rotation(angles):
    x, y, z = map(math.radians, angles)
    sx, sy, sz = map(math.sin, (x, y, z))
    cx, cy, cz = map(math.cos, (x, y, z))

    def transform(vector):
        a, b, c = vector
        b, c = cx*b - sx*c, sx*b + cx*c
        a, c = cy*a + sy*c, -sy*a + cy*c
        return cz*a - sz*b, sz*a + cz*b, c

    return transform


def recipe_geometry(recipe):
    if not isinstance(recipe, dict) or not isinstance(recipe.get('parts'), dict):
        raise ValueError('a recipe needs a parts object')
    normals = [tuple(map(float, match)) for match in re.findall(
        r'\{\s*(-?[0-9.]+),\s*(-?[0-9.]+),\s*(-?[0-9.]+)\s*\}', bike.NORMALS.read_text())]
    model = bike.Model(normals)
    parts = {}
    for name, part in recipe['parts'].items():
        start = len(model.vertices)
        if 'low' in part:
            low, high = point(part['low']), point(part['high'])
            if any(a >= b for a, b in zip(low, high)):
                raise ValueError(f'{name}: box minimum must precede maximum')
            model.box(low, high, part['material'])
        elif 'rings' in part:
            ring_mesh(model, part)
        else:
            for face in part['faces']:
                points = [point(p) for p in face['points']]
                if len(points) < 3:
                    raise ValueError(f'{name}: a triangle or polygon needs at least three points')
                model.face(points, face.get('material', part.get('material', 0)))
        parts[name] = (start, len(model.vertices))
    poses = []
    frame_offsets = recipe.get('frames', {'idle': {}})
    if not isinstance(frame_offsets, dict):
        raise ValueError('frames must be an object of named poses')
    for name, changes in frame_offsets.items():
        vertices = model.vertices.copy()
        for part, offset in changes.items():
            first, last = parts[part]
            offset, angles = pose_values(offset)
            rotate = rotation(angles) if any(angles) else None
            pivot = model_part_origin(recipe['parts'][part], model.vertices[first:last]) if rotate else None
            normals = {}
            for i in range(first, last):
                position, normal, material = vertices[i]
                if rotate is not None:
                    relative = rotate(tuple(a-b for a, b in zip(position, pivot)))
                    position = tuple(a+b for a, b in zip(relative, pivot))
                    if normal not in normals:
                        normals[normal] = model.nearest_normal(rotate(model.normals[normal]))
                    normal = normals[normal]
                vertices[i] = (tuple(a+b for a,b in zip(position, offset)), normal, material)
        poses.append((name, vertices))
    return model, poses, parts


def model_part_origin(part, vertices):
    if 'pivot' in part:
        return point(part['pivot'])
    if 'rings' in part:
        return point(part.get('origin', (0, 0, 0)))
    return tuple((min(axis)+max(axis))/2 for axis in zip(*(p for p, _, _ in vertices)))


def recipe_animations(recipe, names):
    animations = {}
    for name, clip in recipe.get('animations', {}).items():
        frames = clip['frames']
        fps = clip['fps']
        if not isinstance(frames, list) or not frames or any(frame not in names for frame in frames):
            raise ValueError(f'{name}: animation needs existing frame names')
        if type(fps) not in (int, float) or not .1 <= fps <= 120:
            raise ValueError(f'{name}: animation FPS must be between 0.1 and 120')
        animations[name] = frames, fps
    return animations


def model_from_recipe(recipe):
    model, poses, _ = recipe_geometry(recipe)
    return model, poses


def build(recipe, output):
    model, poses = model_from_recipe(recipe)
    output.parent.mkdir(parents=True, exist_ok=True)
    animations = recipe_animations(recipe, dict(poses))
    output.write_bytes(model.encode_poses(poses, recipe['palette'], animations, recipe.get('skins', ())))


def preview_palette(path):
    if path is None:
        return tuple((i, i, i) for i in range(256))
    return read_palette(path)


class RecipeDocument:
    def __init__(self, path):
        self.path = path
        self.source = path.read_bytes()
        self.apply(json.loads(self.source))
        self.saved = deepcopy(self.recipe)

    @property
    def dirty(self):
        return self.recipe != self.saved

    def apply(self, recipe):
        model, frames, parts = recipe_geometry(recipe)
        animations = recipe_animations(recipe, dict(frames))
        try:
            data = model.encode_poses(frames, recipe['palette'], animations)
        except (OverflowError, struct.error) as error:
            raise ValueError('a model value is outside the stock MDL format') from error
        self.recipe, self.model, self.parts = recipe, model, parts
        self.frames, self.binary = dict(frames), data
        self.animations = animations

    def coordinates(self, part_name, frame, size=False, rotation=False):
        part = self.recipe['parts'][part_name]
        if frame is not None:
            move = self.recipe.get('frames', {'idle': {}})[frame].get(part_name, (0, 0, 0))
            offset, angles = pose_values(move)
            return angles if rotation else offset
        if 'rings' in part:
            return point(part.get('origin', (0, 0, 0)))
        if 'low' in part:
            low, high = point(part['low']), point(part['high'])
            return tuple(b-a for a, b in zip(low, high)) if size else low
        return tuple(map(min, zip(*(point(vertex) for face in part['faces'] for vertex in face['points']))))

    def set_coordinates(self, part_name, frame, values, size=False, rotation=False):
        values = point(values)
        candidate = deepcopy(self.recipe)
        part = candidate['parts'][part_name]
        if frame is not None:
            moves = candidate.setdefault('frames', {'idle': {}})[frame]
            if rotation:
                offset, _ = pose_values(moves.get(part_name, (0, 0, 0)))
                moves[part_name] = {'offset': list(offset), 'rotate': list(values)}
            elif isinstance(moves.get(part_name), dict):
                moves[part_name]['offset'] = list(values)
            elif any(values):
                moves[part_name] = list(values)
            else:
                moves.pop(part_name, None)
        elif size:
            part['high'] = [a + b for a, b in zip(point(part['low']), values)]
        else:
            offset = tuple(a-b for a, b in zip(values, self.coordinates(part_name, None)))
            if 'pivot' in part:
                part['pivot'] = [a+b for a, b in zip(point(part['pivot']), offset)]
            if 'low' in part:
                for bound in ('low', 'high'):
                    part[bound] = [a+b for a, b in zip(point(part[bound]), offset)]
            elif 'rings' in part:
                part['origin'] = list(values)
            else:
                for face in part['faces']:
                    face['points'] = [[a+b for a, b in zip(point(p), offset)] for p in face['points']]
        self.apply(candidate)

    def set_material(self, part_name, material):
        candidate = deepcopy(self.recipe)
        part = candidate['parts'][part_name]
        part['material'] = material
        for face in part.get('faces', ()):
            face.pop('material', None)
        self.apply(candidate)

    def add_box(self):
        candidate = deepcopy(self.recipe)
        parts = candidate['parts']
        name = next(f'box{i}' for i in range(1, len(parts)+2) if f'box{i}' not in parts)
        x = max(vertex[0][0] for vertex in self.model.vertices) + 2
        parts[name] = {'low': [x, -4, 0], 'high': [x+8, 4, 8], 'material': 0}
        self.apply(candidate)
        return name

    def add_frame(self, source):
        candidate = deepcopy(self.recipe)
        frames = candidate.setdefault('frames', {'idle': {}})
        name = next(f'pose{i}' for i in range(1, len(frames)+2) if f'pose{i}' not in frames)
        frames[name] = deepcopy(frames.get(source, {}))
        self.apply(candidate)
        return name

    def save(self):
        if not self.dirty:
            return
        data = (json.dumps(self.recipe, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
        write_file(self.path, data, expected=self.source)
        self.source, self.saved = data, deepcopy(self.recipe)

    def export(self, output):
        if output.resolve() == self.path.resolve():
            raise ValueError('the MDL output must be separate from the recipe')
        write_file(output, self.binary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe', type=Path)
    parser.add_argument('output', type=Path, nargs='?')
    parser.add_argument('--view', action='store_true', help='open the native model editor')
    parser.add_argument('--port', type=int, help='start the localhost preview API while editing')
    parser.add_argument('--palette', type=Path, help='stock palette.lmp or pak0.pak for preview colors')
    args = parser.parse_args()
    try:
        if args.view:
            try:
                from model_viewer import run_viewer
            except ModuleNotFoundError as error:
                if error.name != 'pyglet':
                    raise
                raise ValueError("view requires Pyglet. Install 'pyglet>=2.1,<2.2'.") from error
            output = args.output or Path('build') / args.recipe.with_suffix('.mdl').name
            run_viewer(RecipeDocument(args.recipe.resolve()), output.resolve(),
                       preview_palette(args.palette), args.port)
        else:
            if args.output is None:
                parser.error('output is required when exporting from the CLI')
            if args.port is not None or args.palette is not None:
                parser.error('--port and --palette require --view')
            build(json.loads(args.recipe.read_text(encoding='utf-8')), args.output)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
