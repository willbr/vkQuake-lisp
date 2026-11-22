#!/usr/bin/env python3
"""Build stock Quake MDL assets from a small JSON mesh and pose description."""
import argparse
from importlib import import_module
import json
from pathlib import Path
import re

from map_editor import point

bike = import_module('build-bike')


def model_from_recipe(recipe):
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
    for name, changes in recipe.get('frames', {'idle': {}}).items():
        vertices = model.vertices.copy()
        for part, offset in changes.items():
            first, last = parts[part]
            offset = point(offset)
            for i in range(first, last):
                position, normal, material = vertices[i]
                vertices[i] = (tuple(a+b for a,b in zip(position, offset)), normal, material)
        poses.append((name, vertices))
    return model, poses


def build(recipe, output):
    model, poses = model_from_recipe(recipe)
    output.parent.mkdir(parents=True, exist_ok=True)
    model.write_poses(output, poses, recipe['palette'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        build(json.loads(args.recipe.read_text(encoding='utf-8')), args.output)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
