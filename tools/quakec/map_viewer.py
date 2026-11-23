"""Native Pyglet preview of the editor's stock Quake brush geometry."""
from dataclasses import dataclass
import math

from asset_viewer import (
    ACCENT, EDGE, INK, MUTED, PANEL, Camera, OrbitWindow,
    bounds, clamp, midpoint, number, run_preview, update_camera,
)
import pyglet
from pyglet import gl, shapes
from pyglet.math import Vec4
from pyglet.window import key, mouse

from map_editor import MapDocument, dot, point
from uplink_art import DECKS, SIGNS

SURFACE_COLORS = {
    'relay_floor': (.29, .48, .53),
    'relay_wall': (.31, .40, .50),
    'relay_trim': (.48, .52, .56),
    'relay_goal': (.95, .68, .31),
    'annex_rib': (.47, .50, .53),
    'annex_lamp': (.66, .92, .90),
    'annex_gate': (.63, .48, .29),
    'lift_deck': (.64, .54, .30),
    **{sign: (.95, .69, .32) for sign in SIGNS},
}
for deck, (_, _, color) in DECKS.items():
    SURFACE_COLORS[f'{deck}_deck'] = color
    SURFACE_COLORS[f'{deck}_wall'] = tuple(channel * .75 for channel in color)


def surface_color(texture, normal, classname):
    if classname in ('uplink_hint', 'uplink_relay') or classname.startswith('trigger_'):
        return None
    rgb = SURFACE_COLORS.get(texture.lower(), (.36, .56, .62))
    shade = .66 + .34 * max(0, dot(normal, (-.36, -.38, .85)))
    return tuple(component * shade for component in rgb)


@dataclass
class Marker:
    index: int
    position: tuple
    classname: str
    name: str | None

    @property
    def color(self):
        if self.classname == 'light':
            return (1, .75, .37)
        if self.classname.startswith('info_player'):
            return (.58, .98, .59)
        return (.38, .93, .87)


class Scene:
    def __init__(self, document):
        self.title = document.value(0, 'message') or 'Quake map'
        self.entity_count = len(document.entities)
        self.brush_count = sum(len(entity.brushes) for entity in document.entities)
        self.solids, self.edges, self.markers, self.boxes = [], [], [], []
        for index, entity in enumerate(document.entities):
            classname = document.value(index, 'classname') or 'entity'
            entity_points = []
            for brush in entity.brushes:
                vertices = []
                for normal, texture, polygon in brush.polygons():
                    vertices.extend(polygon)
                    color = surface_color(texture, normal, classname)
                    if color is not None:
                        for i in range(1, len(polygon) - 1):
                            self.solids.extend((p, color) for p in (polygon[0], polygon[i], polygon[i + 1]))
                        for a, b in zip(polygon, polygon[1:] + polygon[:1]):
                            self.edges.extend(((a, (.12, .21, .28)), (b, (.12, .21, .28))))
                if vertices:
                    self.boxes.append(bounds(vertices))
                    entity_points.extend(vertices)
            origin = document.value(index, 'origin')
            if index and (origin is not None or entity_points):
                position = point(origin) if origin is not None else midpoint(*bounds(entity_points))
                self.markers.append(Marker(index, position, classname, document.value(index, 'targetname')))
        points = [p for box in self.boxes for p in box] + [marker.position for marker in self.markers]
        self.low, self.high = bounds(points or [(-64, -64, -64), (64, 64, 64)])
        self.z_range = (math.floor(self.low[2]), max(math.ceil(self.high[2]), math.floor(self.low[2]) + 1))
        self.size = max(128, *(b - a for a, b in zip(self.low, self.high)))

    def visible_bounds(self, slab):
        if slab is None:
            return self.low, self.high
        lo, hi = slab
        corners = [(p[0], p[1], clamp(p[2], lo, hi))
                   for a, b in self.boxes if a[2] <= hi and b[2] >= lo for p in (a, b)]
        corners.extend(m.position for m in self.markers if lo <= m.position[2] <= hi)
        return bounds(corners) if corners else (self.low, self.high)


@dataclass
class View(Camera):
    slice: tuple | None = None
    entities: bool = True


def update_view(view, patch):
    next_view = update_camera(view, patch)
    if next_view.span < 8:
        raise ValueError('span must be at least 8 units')
    if next_view.slice is not None:
        if not isinstance(next_view.slice, (list, tuple)) or len(next_view.slice) != 2:
            raise ValueError('slice must be [lower, upper] or null')
        lo, hi = map(number, next_view.slice)
        if lo >= hi:
            raise ValueError('slice lower limit must precede upper limit')
        next_view.slice = (lo, hi)
    if not isinstance(next_view.entities, bool):
        raise ValueError('entities must be true or false')
    return next_view


class MapWindow(OrbitWindow):
    def __init__(self, path, scene):
        super().__init__(f'{path.name} · Quake map viewer')
        self.path = path
        self.scene = scene
        self.timestamp = path.stat().st_mtime_ns
        self.meshes = ()
        self.upload_scene(scene)
        self.state = View((0, 0, 0), -50, 36, 128)
        self.fit()
        self.selected = None
        self.marker_hits = []
        self.load_error = ''
        pyglet.clock.schedule_interval(self.reload_map, .5)

    def close(self):
        pyglet.clock.unschedule(self.reload_map)
        super().close()

    def fit(self):
        low, high = self.scene.visible_bounds(self.state.slice)
        self.state.target = midpoint(low, high)
        width, height = self.view_size
        self.state.span = max(32, math.dist(low, high) * 1.08 / min(1, width / height))

    def upload_scene(self, scene):
        meshes = (self.mesh(scene.solids, gl.GL_TRIANGLES),
                  self.mesh(scene.edges, gl.GL_LINES),
                  self.mesh([(m.position, m.color) for m in scene.markers], gl.GL_POINTS))
        for mesh in self.meshes:
            if mesh is not None:
                mesh.delete()
        self.meshes = meshes

    def reload_map(self, _):
        try:
            stamp = self.path.stat().st_mtime_ns
            if stamp == self.timestamp:
                return
            scene = Scene(MapDocument(self.path.read_text(encoding='utf-8')))
        except (OSError, ValueError) as error:
            self.load_error = f'Map reload failed · {error}'
            return
        self.switch_to()
        self.upload_scene(scene)
        self.scene, self.timestamp = scene, stamp
        self.selected = None
        self.load_error = ''
        self.layout_size = None

    def update_remote(self, patch):
        self.state = update_view(self.state, patch)
        if self.selected and not self.visible(self.selected):
            self.selected = None

    def visible(self, marker):
        slab = self.state.slice or self.scene.z_range
        return self.state.entities and slab[0] <= marker.position[2] <= slab[1]

    def on_draw(self):
        camera = self.begin_view(self.scene.low, self.scene.high, self.scene.size)
        width, height = self.view_size
        triangles, edges, markers = self.meshes
        gl.glEnable(gl.GL_DEPTH_TEST)
        with self.program:
            self.program['slab'] = self.state.slice or self.scene.z_range
            if triangles is not None:
                gl.glEnable(gl.GL_POLYGON_OFFSET_FILL)
                gl.glPolygonOffset(1, 1)
                triangles.draw(gl.GL_TRIANGLES)
                gl.glDisable(gl.GL_POLYGON_OFFSET_FILL)
                edges.draw(gl.GL_LINES)
            gl.glDisable(gl.GL_DEPTH_TEST)
            if markers is not None and self.state.entities:
                gl.glEnable(gl.GL_PROGRAM_POINT_SIZE)
                markers.draw(gl.GL_POINTS)
                gl.glDisable(gl.GL_PROGRAM_POINT_SIZE)
        self.marker_hits = []
        for marker in self.scene.markers:
            if self.visible(marker):
                p = camera @ Vec4(*marker.position, 1)
                x, y = (p.x + 1) * width / 2, self.footer + (p.y + 1) * height / 2
                if 0 <= x < width and self.footer <= y < self.height - self.header:
                    self.marker_hits.append((x, y, marker))

        self.begin_hud()
        if self.layout_size != self.get_size():
            self.layout()
        self.refresh_labels()
        self.hud.draw()

    def layout(self):
        self.layout_size = self.get_size()
        w, h = self.layout_size
        self.hud = pyglet.graphics.Batch()
        background, controls, text = [pyglet.graphics.Group(order=i) for i in range(3)]
        self.drawables = []

        def rect(x, y, width, height, color, group=background):
            shape = shapes.Rectangle(x, y, width, height, color=color, batch=self.hud, group=group)
            self.drawables.append(shape)
            return shape

        def label(value, x, y, size=11, color=INK, **kwargs):
            item = pyglet.text.Label(value, x=x, y=y, anchor_y='center', font_size=size,
                                    color=color, batch=self.hud, group=text, **kwargs)
            self.drawables.append(item)
            return item

        panel = w - self.sidebar
        left = panel + 19
        rect(0, h - self.header, w, self.header, PANEL)
        rect(panel, self.footer, self.sidebar, h - self.header - self.footer, (20, 31, 42))
        rect(0, 0, w, self.footer, PANEL)
        rect(panel, self.footer, 1, h - self.header - self.footer, EDGE)
        label(self.scene.title, 22, h - 25, 17, weight='bold')
        label(f'{self.path.name}  ·  {self.scene.brush_count} brushes  ·  {self.scene.entity_count} entities',
              23, h - 47, 9, MUTED)
        self.status = label('', 22, 17, 10, MUTED)
        label('Height slice', left, h - 88, 13, weight='bold')
        self.slider_x, self.slider_width = left + 6, self.sidebar - 50
        self.slider_y = (h - 148, h - 204)
        self.slider_labels, self.slider_knobs = [], []
        for y in self.slider_y:
            self.slider_labels.append(label('', left, y + 20, 11))
            rect(self.slider_x, y - 2, self.slider_width, 4, EDGE, controls)
            knob = shapes.Circle(self.slider_x, y, 6, color=ACCENT, batch=self.hud, group=controls)
            self.slider_knobs.append(knob)
        self.buttons = []
        for i, caption in enumerate(('Full height', 'Fit view', 'Hide entities')):
            y = h - 253 - 36*i
            rect(left, y, self.sidebar - 38, 28, (38, 55, 68), controls)
            self.buttons.append(label(caption, left + 10, y + 14, 10))
        label('Entity details', left, h - 359, 12, weight='bold')
        self.detail = label('', left, h - 419, 10, MUTED,
                            width=self.sidebar - 38, multiline=True)

    def refresh_labels(self):
        bottom, top = self.scene.z_range
        lower, upper = self.state.slice or (bottom, top)
        for label, knob, title, height in zip(self.slider_labels, self.slider_knobs,
                                              ('Lower Z', 'Upper Z'), (lower, upper)):
            label.text = f'{title}   {height:+,.0f}'
            knob.x = self.slider_x + self.slider_width * clamp((height - bottom) / (top - bottom), 0, 1)
        self.buttons[2].text = 'Hide entities' if self.state.entities else 'Show entities'
        if self.selected:
            m = self.selected
            name = f'{m.name}\n' if m.name else ''
            coords = '  '.join(f'{axis:g}' for axis in m.position)
            self.detail.text = f'{name}#{m.index}  {m.classname}\n{coords}'
        else:
            self.detail.text = 'Click a marker to inspect it.'
        self.status.text = self.load_error or 'Drag to orbit  ·  Right or Shift-drag to pan  ·  Scroll to zoom'

    def set_slider(self, index, x):
        bottom, top = self.scene.z_range
        lo, hi = self.state.slice or (bottom, top)
        height = round(bottom + (top - bottom) * clamp((x-self.slider_x) / self.slider_width, 0, 1))
        self.state.slice = (min(height, hi - 1), hi) if index == 0 else (lo, max(height, lo + 1))
        self.state.target = (*self.state.target[:2], sum(self.state.slice)/2)
        if self.selected and not self.visible(self.selected):
            self.selected = None

    def toggle_entities(self):
        self.state.entities = not self.state.entities
        if not self.state.entities:
            self.selected = None

    def full_height(self):
        self.state.slice = None
        self.fit()

    def on_mouse_press(self, x, y, button, modifiers):
        if button == mouse.LEFT and x >= self.view_size[0]:
            for index, track in enumerate(self.slider_y):
                if abs(y - track) <= 12:
                    self.drag = index
                    self.set_slider(index, x)
                    return
            for label, action in zip(self.buttons, (self.full_height, self.fit, self.toggle_entities)):
                if abs(y - label.y) <= 14:
                    action()
                    return
        elif self.footer <= y < self.height - self.header and x < self.view_size[0]:
            self.drag = (x, y)

    def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
        if isinstance(self.drag, int):
            self.set_slider(self.drag, x)
        else:
            super().on_mouse_drag(x, y, dx, dy, buttons, modifiers)

    def on_mouse_release(self, x, y, button, modifiers):
        if button == mouse.LEFT and isinstance(self.drag, tuple) and math.dist(self.drag, (x, y)) < 3:
            near = [(math.hypot(px-x, py-y), marker) for px, py, marker in self.marker_hits]
            distance, marker = min(near, key=lambda item: item[0], default=(math.inf, None))
            self.selected = marker if distance < 11 else None
        self.drag = None

    def on_key_press(self, symbol, modifiers):
        if symbol == key.F:
            self.fit()
        elif symbol == key.H:
            self.full_height()
        elif symbol == key.E:
            self.toggle_entities()
        else:
            return super().on_key_press(symbol, modifiers)


def run_viewer(path, port, map_server):
    window = MapWindow(path, Scene(MapDocument(path.read_text(encoding='utf-8'))))
    run_preview(window, port, lambda number, viewer: map_server(path, number, viewer))
