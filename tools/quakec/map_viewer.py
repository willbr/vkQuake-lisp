"""Native Pyglet preview of the editor's stock Quake brush geometry."""
from concurrent.futures import Future
from dataclasses import asdict, dataclass, replace
from io import BytesIO
import math
from queue import Empty, SimpleQueue
from threading import Thread

import pyglet
# Use logical window and pointer coordinates with a pixel-scaled GL viewport.
pyglet.options.dpi_scaling = 'stretch'
from pyglet import gl, shapes
from pyglet.graphics.shader import Shader, ShaderProgram
from pyglet.math import Mat4, Vec3, Vec4
from pyglet.window import key, mouse

from map_editor import MapDocument, dot, point
from uplink_art import DECKS, SIGNS

VERTEX_SHADER = """#version 150 core
in vec3 position;
in vec3 color;
out vec3 surface_color;
out float height;

uniform WindowBlock {
    mat4 projection;
    mat4 view;
} window;

void main() {
    gl_Position = window.projection * window.view * vec4(position, 1.0);
    gl_PointSize = 9.0;
    surface_color = color;
    height = position.z;
}
"""

FRAGMENT_SHADER = """#version 150 core
in vec3 surface_color;
in float height;
out vec4 pixel;
uniform vec2 slab;

void main() {
    if (height < slab.x || height > slab.y) {
        discard;
    }
    pixel = vec4(surface_color, 1.0);
}
"""

INK = (226, 236, 242, 255)
MUTED = (156, 177, 194, 255)
ACCENT = (87, 208, 187, 255)
PANEL = (25, 38, 49)
EDGE = (52, 73, 89)
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


def clamp(value, low, high):
    return min(high, max(low, value))


def bounds(points):
    axes = list(zip(*points))
    return tuple(map(min, axes)), tuple(map(max, axes))


def midpoint(low, high):
    return tuple((a + b) / 2 for a, b in zip(low, high))


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
class View:
    target: tuple
    yaw: float
    pitch: float
    span: float
    slice: tuple | None = None
    entities: bool = True


def number(value):
    if type(value) not in (int, float) or not -1e8 <= value <= 1e8:
        raise ValueError('expected a finite number in the viewer coordinate range')
    return value


def update_view(view, patch):
    if not isinstance(patch, dict) or patch.keys() - asdict(view).keys():
        raise ValueError('expected view fields: target, yaw, pitch, span, slice, entities')
    next_view = replace(view, **patch)
    if not isinstance(next_view.target, (list, tuple)) or len(next_view.target) != 3:
        raise ValueError('target must be [x, y, z]')
    next_view.target = tuple(map(number, next_view.target))
    next_view.yaw = number(next_view.yaw) % 360
    if not -85 <= number(next_view.pitch) <= 85:
        raise ValueError('pitch must be between -85 and 85 degrees')
    if not 8 <= number(next_view.span) <= 1e7:
        raise ValueError('span must be between 8 and 10000000 units')
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


class MapWindow(pyglet.window.Window):
    sidebar = 240
    header = 62
    footer = 35

    def __init__(self, path, scene):
        super().__init__(width=1200, height=780, caption=f'{path.name} · Quake map viewer',
                         resizable=True, config=gl.Config(double_buffer=True, depth_size=24))
        self.set_minimum_size(760, 490)
        self.path = path
        self.scene = scene
        self.timestamp = path.stat().st_mtime_ns
        self.requests = SimpleQueue()
        self.program = ShaderProgram(Shader(VERTEX_SHADER, 'vertex'), Shader(FRAGMENT_SHADER, 'fragment'))
        self.meshes = ()
        self.upload_scene(scene)
        self.state = View((0, 0, 0), -50, 36, 128)
        self.fit()
        self.drag = None
        self.selected = None
        self.marker_hits = []
        self.load_error = ''
        self.layout_size = None
        pyglet.clock.schedule(self.handle_requests)
        pyglet.clock.schedule_interval(self.reload_map, .5)

    @property
    def view_size(self):
        return self.width - self.sidebar, self.height - self.header - self.footer

    def fit(self):
        low, high = self.scene.visible_bounds(self.state.slice)
        self.state.target = midpoint(low, high)
        width, height = self.view_size
        self.state.span = max(32, math.dist(low, high) * 1.08 / min(1, width / height))

    def mesh(self, vertices, mode):
        if not vertices:
            return None
        positions, colors = zip(*vertices)
        return self.program.vertex_list(len(vertices), mode,
                                        position=('f', [v for p in positions for v in p]),
                                        color=('f', [v for rgb in colors for v in rgb]))

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

    def request(self, action, data=None):
        future = Future()
        self.requests.put((action, data, future))
        try:
            return future.result(timeout=3)
        except TimeoutError as error:
            future.cancel()
            raise TimeoutError('viewer is busy') from error

    def handle_requests(self, _):
        try:
            action, data, future = self.requests.get_nowait()
        except Empty:
            return
        if not future.set_running_or_notify_cancel():
            return
        try:
            if action == 'update':
                self.state = update_view(self.state, data)
                if self.selected and not self.visible(self.selected):
                    self.selected = None
            if action == 'snapshot':
                self.switch_to()
                self.on_draw()
                stream = BytesIO()
                pyglet.image.get_buffer_manager().get_color_buffer().save('map.png', stream)
                future.set_result(stream.getvalue())
            else:
                future.set_result(asdict(self.state))
        except Exception as error:
            future.set_exception(error)

    def camera_direction(self):
        yaw, pitch = map(math.radians, (self.state.yaw, self.state.pitch))
        return Vec3(math.cos(yaw) * math.cos(pitch), math.sin(yaw) * math.cos(pitch), math.sin(pitch))

    def visible(self, marker):
        slab = self.state.slice or self.scene.z_range
        return self.state.entities and slab[0] <= marker.position[2] <= slab[1]

    def on_draw(self):
        gl.glClearColor(.055, .085, .115, 1)
        self.clear()
        width, height = self.view_size
        self.viewport = (0, self.footer, width, height)
        half = self.state.span / 2
        distance = max(self.scene.size, self.state.span) * 5 + math.dist(self.state.target, midpoint(self.scene.low, self.scene.high))
        center = Vec3(*self.state.target)
        self.projection = Mat4.orthogonal_projection(-half*width/height, half*width/height,
                                                      -half, half, 1, 2*distance)
        self.view = Mat4.look_at(center + self.camera_direction() * distance, center, Vec3(0, 0, 1))
        camera = self.projection @ self.view
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

        self.viewport = (0, 0, self.width, self.height)
        self.projection = Mat4.orthogonal_projection(0, self.width, 0, self.height, -1, 1)
        self.view = Mat4()
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
        elif self.drag is not None:
            if buttons & (mouse.RIGHT | mouse.MIDDLE) or modifiers & key.MOD_SHIFT:
                direction = self.camera_direction()
                right = Vec3(0, 0, 1).cross(direction).normalize()
                up = direction.cross(right)
                scale = self.state.span / self.view_size[1]
                self.state.target = tuple(Vec3(*self.state.target) - (right * dx + up * dy) * scale)
            else:
                self.state.yaw = (self.state.yaw - dx * .45) % 360
                self.state.pitch = clamp(self.state.pitch - dy * .45, -85, 85)

    def on_mouse_release(self, x, y, button, modifiers):
        if button == mouse.LEFT and isinstance(self.drag, tuple) and math.dist(self.drag, (x, y)) < 3:
            near = [(math.hypot(px-x, py-y), marker) for px, py, marker in self.marker_hits]
            distance, marker = min(near, key=lambda item: item[0], default=(math.inf, None))
            self.selected = marker if distance < 11 else None
        self.drag = None

    def on_mouse_scroll(self, x, y, scroll_x, scroll_y):
        if x < self.view_size[0]:
            self.state.span = clamp(self.state.span * .88 ** clamp(scroll_y, -10, 10), 8, self.scene.size * 8)

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
    if port is None:
        pyglet.app.run()
        return
    with map_server(path, port, window) as server:
        worker = Thread(target=server.serve_forever)
        worker.start()
        try:
            print(f'Viewing {path} at http://127.0.0.1:{server.server_address[1]}', flush=True)
            pyglet.app.run()
        finally:
            server.shutdown()
            worker.join()
