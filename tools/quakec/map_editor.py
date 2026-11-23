#!/usr/bin/env python3
"""Edit stock Quake brush maps from a CLI or a local JSON session."""
import argparse
from dataclasses import dataclass
import difflib
import hashlib
from itertools import combinations
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs
from xml.etree import ElementTree as ET

from preview_server import LocalServer, PreviewHandler

TOKEN = re.compile(r'//[^\n]*|"[^"\n]*"|[{}()]|[^\s{}()"]+')
EPSILON = 0.0001


def subtract(a, b):
    return tuple(x - y for x, y in zip(a, b))


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    x, y, z = a
    u, v, w = b
    return y*w - z*v, z*u - x*w, x*v - y*u


def point(value):
    if isinstance(value, str):
        value = value.split()
    values = tuple(float(axis) for axis in value)
    if len(values) != 3 or not all(math.isfinite(axis) for axis in values):
        raise ValueError('expected three finite coordinates')
    return values


def coordinates(value):
    return ' '.join(f'{axis:.8g}' for axis in point(value))


def quoted(text):
    if not isinstance(text, str) or any(ch in text for ch in '"\r\n\0'):
        raise ValueError('map keys and values must be single-line strings without quotes')
    return f'"{text}"'


@dataclass(frozen=True)
class Face:
    points: tuple
    texture: str
    axes: tuple = ('0', '0', '0', '1', '1')

    def plane(self):
        a, b, c = self.points
        normal = cross(subtract(b, a), subtract(c, a))
        length = math.sqrt(dot(normal, normal))
        if length < EPSILON:
            raise ValueError('collinear face points')
        normal = tuple(component / length for component in normal)
        return normal, dot(normal, a)

    def text(self):
        points = ' '.join(f'( {coordinates(p)} )' for p in self.points)
        if not re.fullmatch(r'[^\s"{}()]{1,15}', self.texture):
            raise ValueError(f'invalid stock texture name {self.texture!r}')
        return f'{points} {self.texture} {" ".join(self.axes)}'


@dataclass(frozen=True)
class Brush:
    faces: tuple
    start: int = 0
    end: int = 0

    def vertices(self):
        planes = [face.plane() for face in self.faces]
        unique = {}
        for (a, da), (b, db), (c, dc) in combinations(planes, 3):
            bc, ca, ab = cross(b, c), cross(c, a), cross(a, b)
            determinant = dot(a, bc)
            if abs(determinant) < EPSILON:
                continue
            vertex = tuple((da*x + db*y + dc*z) / determinant for x, y, z in zip(bc, ca, ab))
            if all(dot(normal, vertex) >= distance - EPSILON for normal, distance in planes):
                unique[tuple(round(axis, 4) for axis in vertex)] = vertex
        if len(unique) < 4:
            raise ValueError('brush planes do not enclose a volume')
        return tuple(unique.values())

    def polygons(self):
        """Yield each face as an outward normal, texture and ordered vertices."""
        vertices = self.vertices()
        for face in self.faces:
            inward, distance = face.plane()
            points = [p for p in vertices if abs(dot(inward, p) - distance) <= EPSILON]
            if len(points) < 3:
                continue
            normal = tuple(-axis for axis in inward)
            center = tuple(sum(axis) / len(points) for axis in zip(*points))
            u = subtract(points[0], center)
            v = cross(normal, u)
            points.sort(key=lambda p: math.atan2(dot(subtract(p, center), v),
                                                 dot(subtract(p, center), u)))
            yield normal, face.texture, points

    def text(self):
        return '{\n' + '\n'.join(face.text() for face in self.faces) + '\n}\n'


def prism(top, bottom, texture):
    """Extrude a convex, planar top polygon down to a constant elevation."""
    if len(top) < 3 or any(p[2] <= bottom for p in top):
        raise ValueError('prism needs a polygon wholly above its base')
    low = [(x, y, bottom) for x, y, _ in top]
    center = tuple(sum(axis) / (2 * len(top)) for axis in zip(*top, *low))
    planes = [top[:3], low[:3]]
    for index in range(len(top)):
        following = (index + 1) % len(top)
        planes.append((low[index], low[following], top[following]))
    faces = []
    for a, b, c in planes:
        if dot(cross(subtract(b, a), subtract(c, a)), subtract(center, a)) < 0:
            b, c = c, b
        faces.append(Face((a, b, c), texture))
    brush = Brush(tuple(faces))
    if len(brush.vertices()) != 2 * len(top):
        raise ValueError('prism top must be a planar convex polygon')
    for vertex in top:
        normal, distance = faces[0].plane()
        if abs(dot(normal, vertex) - distance) > EPSILON:
            raise ValueError('prism top must be planar')
    return brush


def box(low, high, texture):
    x, y, z = point(low)
    xx, yy, zz = point(high)
    if x >= xx or y >= yy or z >= zz:
        raise ValueError('box minimum must precede maximum on every axis')
    return prism([(x, y, zz), (xx, y, zz), (xx, yy, zz), (x, yy, zz)], z, texture)


def ramp(bounds, heights, axis, bottom, texture):
    x, y, xx, yy = map(float, bounds)
    start, end = map(float, heights)
    if x >= xx or y >= yy or axis not in ('x', 'y'):
        raise ValueError('ramp needs increasing XY bounds and an x or y axis')
    e, f = (end, start) if axis == 'x' else (start, end)
    return prism([(x, y, start), (xx, y, e), (xx, yy, end), (x, yy, f)],
                 float(bottom), texture)


def bank(center, radii, angles, rise, sectors, texture):
    x, y, z = point(center)
    inner, outer = map(float, radii)
    start, end = map(float, angles)
    if not 0 < inner < outer or not 0 < end - start <= 180 or not 1 <= sectors <= 24:
        raise ValueError('bank needs increasing radii, a turn up to 180 degrees, and 1–24 sectors')
    if not isinstance(sectors, int) or not math.isfinite(rise) or rise < 0:
        raise ValueError('invalid bank sector count or rise')
    rim, edge = [], []
    for step in range(sectors + 1):
        fraction = step / sectors
        angle = math.radians(start + fraction * (end - start))
        cosine, sine = math.cos(angle), math.sin(angle)
        rim.append((x + outer*cosine, y + outer*sine, z + rise*math.sin(math.pi*fraction)))
        edge.append((x + inner*cosine, y + inner*sine, z))
    return [prism(list(top), z - 16, texture)
            for i in range(sectors)
            for top in ((edge[i], rim[i], rim[i+1]), (edge[i], rim[i+1], edge[i+1]))]


def switchback(start, run, width, spacing, drop, legs, texture):
    """Return a continuous north-stepping set of alternating east/west ramps."""
    x, y, z = point(start)
    if not isinstance(legs, int) or not 1 <= legs <= 16:
        raise ValueError('switchback needs 1–16 ramp runs')
    if min(run, width, spacing, drop) <= 0 or spacing < width:
        raise ValueError('invalid switchback dimensions')
    brushes = []
    step = drop / legs
    for i in range(legs):
        y0 = y + i * spacing
        high = z - i * step
        low = high - step
        heights = (high, low) if i % 2 == 0 else (low, high)
        brushes.append(ramp((x, y0, x + run, y0 + width), heights, 'x', low - 16, texture))
        if i + 1 < legs:
            turn_x = x + run if i % 2 == 0 else x - width
            brushes.append(box((turn_x, y0, low - 16),
                               (turn_x + width, y0 + spacing + width, low), texture))
    return brushes


@dataclass
class Entity:
    start: int
    end: int
    properties: dict
    brushes: list


class MapDocument:
    """Parse the original .map grammar and retain unchanged source verbatim."""
    def __init__(self, text):
        self.text = text
        self.entities = []
        self._parse()

    def _parse(self):
        tokens = []
        cursor = 0
        for token in TOKEN.finditer(self.text):
            if self.text[cursor:token.start()].strip():
                raise ValueError(f'invalid map token at offset {cursor}')
            cursor = token.end()
            if not token[0].startswith('//'):
                tokens.append(token)
        if self.text[cursor:].strip():
            raise ValueError(f'invalid map token at offset {cursor}')
        index = 0

        def take(expected=None):
            nonlocal index
            if index == len(tokens):
                raise ValueError('unexpected end of map')
            token = tokens[index]
            index += 1
            if expected is not None and token[0] != expected:
                raise ValueError(f'expected {expected!r} at offset {token.start()}')
            return token

        while index < len(tokens):
            start = take('{').start()
            keys, brushes = {}, []
            while index < len(tokens) and tokens[index][0] != '}':
                if tokens[index][0] != '{':
                    key, value = take(), take()
                    if not key[0].startswith('"') or not value[0].startswith('"'):
                        raise ValueError(f'expected quoted entity key and value at offset {key.start()}')
                    keys[key[0][1:-1]] = value
                    continue
                brush_start = take('{').start()
                faces = []
                while index < len(tokens) and tokens[index][0] != '}':
                    vertices = []
                    for _ in range(3):
                        take('(')
                        vertices.append(point([take()[0] for _ in range(3)]))
                        take(')')
                    texture = take()[0]
                    axes = tuple(take()[0] for _ in range(5))
                    if not all(math.isfinite(float(axis)) for axis in axes):
                        raise ValueError('invalid texture axes')
                    faces.append(Face(tuple(vertices), texture, axes))
                brushes.append(Brush(tuple(faces), brush_start, take('}').end()))
            self.entities.append(Entity(start, take('}').end(), keys, brushes))
        if not self.entities or self.value(0, 'classname') != 'worldspawn':
            raise ValueError('first map entity must be worldspawn')

    def value(self, index, key):
        token = self.entities[index].properties.get(key)
        return token[0][1:-1] if token else None

    def _edit(self, start, end, text):
        self.text = self.text[:start] + text + self.text[end:]
        self.entities = []
        self._parse()

    def add_entity(self, properties, brushes=()):
        metadata = '\n'.join(f'{quoted(key)} {quoted(value)}' for key, value in properties.items())
        body = ''.join(brush.text() for brush in brushes)
        self._edit(len(self.text), len(self.text), f'\n{{\n{metadata}\n{body}}}\n')

    def add_brushes(self, index, brushes):
        entity = self.entities[index]
        self._edit(entity.end - 1, entity.end - 1, ''.join(brush.text() for brush in brushes))

    def set(self, index, key, value):
        entity = self.entities[index]
        literal = quoted(value)
        if key in entity.properties:
            match = entity.properties[key]
            self._edit(match.start(), match.end(), literal)
        else:
            self._edit(entity.start + 1, entity.start + 1, f'\n{quoted(key)} {literal}')

    def translate_brush(self, index, brush_index, offset):
        brush = self.entities[index].brushes[brush_index]
        offset = point(offset)
        moved = Brush(tuple(Face(tuple(tuple(a+b for a,b in zip(v, offset)) for v in face.points),
                                 face.texture, face.axes) for face in brush.faces))
        self._edit(brush.start, brush.end, moved.text().rstrip('\n'))

    def inspect(self):
        return {'revision': revision(self.text), 'entities': [
            {'index': i, 'brushes': len(entity.brushes),
             **{key: self.value(i, key) for key in ('classname', 'targetname', 'target', 'origin')}}
            for i, entity in enumerate(self.entities)]}

    def validate(self):
        vertices = []
        for index, entity in enumerate(self.entities):
            if not self.value(index, 'classname'):
                raise ValueError(f'entity {index} has no classname')
            origin = self.value(index, 'origin')
            if origin is not None:
                vertices.append(point(origin))
            for brush_index, brush in enumerate(entity.brushes):
                try:
                    vertices.extend(brush.vertices())
                except ValueError as error:
                    raise ValueError(f'entity {index}, brush {brush_index}: {error}') from error
        return {
            'entities': len(self.entities),
            'brushes': sum(len(entity.brushes) for entity in self.entities),
            'bounds': [tuple(map(f, zip(*vertices))) for f in (min, max)] if vertices else None,
        }

    def apply(self, operations):
        for operation in operations:
            kind = operation['op']
            entity = operation.get('entity', 0)
            if not isinstance(entity, int) or not 0 <= entity < len(self.entities):
                raise ValueError(f'unknown entity index {entity}')
            if kind == 'place':
                fields = dict(operation['fields'])
                if 'origin' in fields:
                    fields['origin'] = coordinates(fields['origin'])
                self.add_entity(fields)
            elif kind == 'set':
                field, value = operation['key'], operation['value']
                self.set(entity, field, coordinates(value) if field == 'origin' else value)
            elif kind == 'link':
                target = operation['to']
                if not isinstance(target, int) or not 0 <= target < len(self.entities):
                    raise ValueError(f'unknown link target {target}')
                self.set(target, 'targetname', operation['name'])
                self.set(entity, 'target', operation['name'])
            elif kind == 'translate-brush':
                brush = operation['brush']
                if not isinstance(brush, int) or not 0 <= brush < len(self.entities[entity].brushes):
                    raise ValueError(f'unknown brush index {brush}')
                self.translate_brush(entity, brush, operation['offset'])
            else:
                params = {key: value for key, value in operation.items() if key not in ('op', 'entity')}
                if kind == 'box':
                    additions = [box(**params)]
                elif kind == 'ramp':
                    additions = [ramp(**params)]
                elif kind == 'bank':
                    additions = bank(**params)
                elif kind == 'switchback':
                    additions = switchback(**params)
                else:
                    raise ValueError(f'unknown edit {kind!r}')
                self.add_brushes(entity, additions)
        return self.validate()

    def preview(self, view):
        axes = {'top': (0, 1), 'side': (0, 2), 'end': (1, 2)}[view]
        points = []
        for entity in self.entities:
            for brush in entity.brushes:
                points.append(tuple(brush.vertices()))
        markers = [(point(self.value(i, 'origin')), self.value(i, 'targetname') or self.value(i, 'classname'))
                   for i in range(len(self.entities)) if self.value(i, 'origin') is not None]
        projected = [(p[axes[0]], -p[axes[1]]) for brush in points for p in brush]
        projected += [(p[axes[0]], -p[axes[1]]) for p, _ in markers]
        if not projected:
            projected = [(0, 0), (1, 1)]
        x, y = (min(values) for values in zip(*projected))
        xx, yy = (max(values) for values in zip(*projected))
        scale = 720 / max(xx-x, yy-y, 1)

        def xy(p):
            return 28 + (p[axes[0]]-x)*scale, 28 + (-p[axes[1]]-y)*scale

        svg = ET.Element('svg', xmlns='http://www.w3.org/2000/svg',
                         viewBox=f'0 0 {(xx-x)*scale+56:g} {(yy-y)*scale+56:g}',
                         fill='none', stroke='#28465b')
        for brush in points:
            # A monotone convex hull avoids crossing projected edges on slopes.
            outline = convex_outline([xy(p) for p in brush])
            ET.SubElement(svg, 'polygon', {'points': ' '.join(f'{a:g},{b:g}' for a, b in outline),
                                          'fill': '#dae9ef', 'fill-opacity': '0.38'})
        for p, label in markers:
            a, b = xy(p)
            ET.SubElement(svg, 'circle', cx=str(a), cy=str(b), r='3', fill='#b45734')
            ET.SubElement(svg, 'text', x=str(a+5), y=str(b-5), fill='#25303a',
                          stroke='none', **{'font-size': '10'}).text = label
        return ET.tostring(svg, encoding='unicode')


def convex_outline(points):
    def edge(vertices):
        hull = []
        for p in vertices:
            while len(hull) >= 2:
                a, b = hull[-2:]
                if (b[0]-a[0])*(p[1]-a[1]) - (b[1]-a[1])*(p[0]-a[0]) > 0:
                    break
                hull.pop()
            hull.append(p)
        return hull[:-1]

    points = sorted(set(points))
    return edge(points) + edge(reversed(points))


def revision(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def edit_map(path, operations, *, expected=None, write=False):
    original = path.read_text(encoding='utf-8')
    if expected is not None and revision(original) != expected:
        raise ValueError('map revision changed; inspect again before editing')
    document = MapDocument(original)
    summary = document.apply(operations)
    diff = ''.join(difflib.unified_diff(original.splitlines(keepends=True),
                                        document.text.splitlines(keepends=True),
                                        fromfile=str(path), tofile=str(path)))
    if write and diff:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as temp:
            temp_path = Path(temp.name)
            try:
                temp.write(document.text)
                temp.flush()
                os.chmod(temp_path, path.stat().st_mode & 0o777)
                if path.read_text(encoding='utf-8') != original:
                    raise ValueError('map revision changed while preparing the write')
                temp_path.replace(path)
            finally:
                temp_path.unlink(missing_ok=True)
    return {'diff': diff, 'revision': revision(document.text if write else original), **summary}


def map_server(path, port, viewer=None):
    class Handler(PreviewHandler):
        def get_resource(self, url):
            document = MapDocument(path.read_text(encoding='utf-8'))
            if url.path == '/':
                self.respond(document.inspect())
            elif url.path == '/preview':
                self.respond(document.preview(parse_qs(url.query).get('view', ['top'])[0]))
            else:
                super().get_resource(url)

        def post_resource(self):
            if self.path != '/edit':
                return super().post_resource()
            body = self.read_json()
            if not isinstance(body.get('revision'), str) or not isinstance(body.get('operations'), list):
                raise ValueError('edit requires the inspected revision and an operation list')
            result = edit_map(path, body['operations'], expected=body['revision'], write=body.get('write') is True)
            self.respond(result)

    Handler.viewer = viewer
    return LocalServer(('127.0.0.1', port), Handler)


def serve(path, port):
    with map_server(path, port) as server:
        print(f'Editing {path} at http://127.0.0.1:{server.server_address[1]}', flush=True)
        server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('map', type=Path)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('inspect')
    sub.add_parser('validate')
    apply = sub.add_parser('apply')
    apply.add_argument('operations', type=Path)
    apply.add_argument('--write', action='store_true')
    preview = sub.add_parser('preview')
    preview.add_argument('output', type=Path)
    preview.add_argument('--view', choices=('top', 'side', 'end'), default='top')
    session = sub.add_parser('serve')
    session.add_argument('--port', type=int, default=8765)
    view3d = sub.add_parser('view3d', help='open the native 3D brush viewer')
    view3d.add_argument('--port', type=int, help='also start the localhost editor API')
    build = sub.add_parser('build')
    build.add_argument('output', type=Path)
    build.add_argument('--wad', type=Path, action='append', default=[],
                       help='include textures from an additional WAD2 (repeatable)')
    args = parser.parse_args()
    try:
        if args.command == 'serve':
            serve(args.map.resolve(), args.port)
        elif args.command == 'view3d':
            try:
                from map_viewer import run_viewer
            except ModuleNotFoundError as error:
                if error.name != 'pyglet':
                    raise
                raise ValueError("view3d requires Pyglet. Install 'pyglet>=2.1,<2.2'.") from error
            run_viewer(args.map.resolve(), args.port, map_server)
        elif args.command == 'apply':
            result = edit_map(args.map, json.loads(args.operations.read_text()), write=args.write)
            sys.stdout.write(result['diff'])
        elif args.command == 'build':
            subprocess.run([sys.executable, Path(__file__).with_name('build-signal.py'),
                            args.output, '--source', args.map,
                            *(arg for wad in args.wad for arg in ('--wad', wad))], check=True)
        else:
            document = MapDocument(args.map.read_text(encoding='utf-8'))
            if args.command == 'preview':
                args.output.write_text(document.preview(args.view), encoding='utf-8')
            else:
                print(json.dumps(document.inspect() if args.command == 'inspect' else document.validate(), indent=2))
    except (ValueError, KeyError, TypeError, IndexError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
