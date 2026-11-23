#!/usr/bin/env python3
"""Build stock Quake MDL assets from a small JSON mesh and pose description."""
import argparse
from copy import deepcopy
from importlib import import_module
import json
from pathlib import Path
import re
import struct
import tempfile

from map_editor import point

bike = import_module('build-bike')


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
            offset = point(offset)
            for i in range(first, last):
                position, normal, material = vertices[i]
                vertices[i] = (tuple(a+b for a,b in zip(position, offset)), normal, material)
        poses.append((name, vertices))
    return model, poses, parts


def model_from_recipe(recipe):
    model, poses, _ = recipe_geometry(recipe)
    return model, poses


def build(recipe, output):
    model, poses = model_from_recipe(recipe)
    output.parent.mkdir(parents=True, exist_ok=True)
    model.write_poses(output, poses, recipe['palette'])


def write_file(path, data, expected=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = tempfile.NamedTemporaryFile(dir=path.parent, delete=False)
    staged = Path(stream.name)
    try:
        with stream:
            stream.write(data)
        if expected is not None and path.read_bytes() != expected:
            raise ValueError('recipe changed on disk. Reopen it before saving.')
        if path.exists():
            staged.chmod(path.stat().st_mode & 0o777)
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def preview_palette(path):
    if path is None:
        return tuple((i, i, i) for i in range(256))
    if path.suffix.lower() == '.pak':
        with path.open('rb') as pak:
            header = pak.read(12)
            if len(header) != 12:
                raise ValueError('incomplete PAK header')
            magic, directory, length = struct.unpack('<4sII', header)
            if magic != b'PACK' or length % 64 or directory + length > path.stat().st_size:
                raise ValueError('invalid PAK directory')
            pak.seek(directory)
            records = pak.read(length)
            for name, offset, size in struct.iter_unpack('<56sII', records):
                if name.rstrip(b'\0') == b'gfx/palette.lmp' and size == 768:
                    pak.seek(offset)
                    palette = pak.read(size)
                    break
            else:
                raise ValueError('PAK does not contain gfx/palette.lmp')
    else:
        palette = path.read_bytes()
    if len(palette) != 768:
        raise ValueError('the palette must contain 256 RGB colors')
    return tuple(struct.iter_unpack('3B', palette))


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
        try:
            data = model.encode_poses(frames, recipe['palette'])
        except (OverflowError, struct.error) as error:
            raise ValueError('a model value is outside the stock MDL format') from error
        self.recipe, self.model, self.parts = recipe, model, parts
        self.frames, self.binary = dict(frames), data

    def coordinates(self, part_name, frame, size=False):
        part = self.recipe['parts'][part_name]
        if frame is not None:
            return point(self.recipe.get('frames', {'idle': {}})[frame].get(part_name, (0, 0, 0)))
        if 'low' in part:
            low, high = point(part['low']), point(part['high'])
            return tuple(b-a for a, b in zip(low, high)) if size else low
        return tuple(map(min, zip(*(point(vertex) for face in part['faces'] for vertex in face['points']))))

    def set_coordinates(self, part_name, frame, values, size=False):
        values = point(values)
        candidate = deepcopy(self.recipe)
        part = candidate['parts'][part_name]
        if frame is not None:
            moves = candidate.setdefault('frames', {'idle': {}})[frame]
            if any(values):
                moves[part_name] = list(values)
            else:
                moves.pop(part_name, None)
        elif size:
            part['high'] = [a + b for a, b in zip(point(part['low']), values)]
        else:
            offset = tuple(a-b for a, b in zip(values, self.coordinates(part_name, None)))
            if 'low' in part:
                for bound in ('low', 'high'):
                    part[bound] = [a+b for a, b in zip(point(part[bound]), offset)]
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
