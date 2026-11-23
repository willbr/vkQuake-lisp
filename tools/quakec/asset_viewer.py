"""Shared native camera, drawing, and localhost bridge for the Quake editors."""
from concurrent.futures import Future
from dataclasses import asdict, dataclass, replace
from io import BytesIO
import math
from queue import Empty, SimpleQueue
from threading import Thread

import pyglet
# Keep pointer coordinates logical and scale the GL viewport for the display.
pyglet.options.dpi_scaling = 'stretch'
from pyglet import gl
from pyglet.graphics.shader import Shader, ShaderProgram
from pyglet.math import Mat4, Vec3
from pyglet.window import key, mouse

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

def clamp(value, low, high):
    return min(high, max(low, value))


def bounds(points):
    axes = list(zip(*points))
    return tuple(map(min, axes)), tuple(map(max, axes))


def midpoint(low, high):
    return tuple((a + b) / 2 for a, b in zip(low, high))


@dataclass
class Camera:
    target: tuple
    yaw: float
    pitch: float
    span: float


def number(value):
    if type(value) not in (int, float) or not -1e8 <= value <= 1e8:
        raise ValueError('expected a finite number in the viewer coordinate range')
    return value


def update_camera(view, patch):
    if not isinstance(patch, dict) or patch.keys() - asdict(view).keys():
        raise ValueError('unknown camera field')
    candidate = replace(view, **patch)
    if not isinstance(candidate.target, (list, tuple)) or len(candidate.target) != 3:
        raise ValueError('target must be [x, y, z]')
    candidate.target = tuple(map(number, candidate.target))
    candidate.yaw = number(candidate.yaw) % 360
    if not -85 <= number(candidate.pitch) <= 85:
        raise ValueError('pitch must be between -85 and 85 degrees')
    if not 1 <= number(candidate.span) <= 1e7:
        raise ValueError('span must be between 1 and 10000000 units')
    return candidate


class WindowRequests:
    def start_requests(self):
        self.requests = SimpleQueue()
        pyglet.clock.schedule(self.handle_requests)

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
            future.set_result(self.remote_response(action, data))
        except Exception as error:
            future.set_exception(error)

    def remote_response(self, action, data):
        if action == 'update':
            self.update_remote(data)
        if action == 'snapshot':
            self.switch_to()
            self.on_draw()
            stream = BytesIO()
            pyglet.image.get_buffer_manager().get_color_buffer().save('preview.png', stream)
            return stream.getvalue()
        return self.remote_state()

    def close(self):
        pyglet.clock.unschedule(self.handle_requests)
        super().close()


class OrbitWindow(WindowRequests, pyglet.window.Window):
    sidebar = 240
    header = 62
    footer = 35
    min_span = 8

    def __init__(self, caption, *, width=1200, height=780, minimum=(760, 490)):
        super().__init__(width=width, height=height, caption=caption, resizable=True,
                         config=gl.Config(double_buffer=True, depth_size=24))
        self.set_minimum_size(*minimum)
        self.program = ShaderProgram(Shader(VERTEX_SHADER, 'vertex'), Shader(FRAGMENT_SHADER, 'fragment'))
        self.drag = None
        self.layout_size = None
        self.start_requests()

    @property
    def view_size(self):
        return self.width - self.sidebar, self.height - self.header - self.footer

    def mesh(self, vertices, mode):
        if not vertices:
            return None
        positions, colors = zip(*vertices)
        return self.program.vertex_list(len(vertices), mode,
                                        position=('f', [v for p in positions for v in p]),
                                        color=('f', [v for rgb in colors for v in rgb]))

    def remote_state(self):
        return asdict(self.state)

    def update_remote(self, patch):
        self.state = update_camera(self.state, patch)

    def camera_direction(self):
        yaw, pitch = map(math.radians, (self.state.yaw, self.state.pitch))
        return Vec3(math.cos(yaw) * math.cos(pitch), math.sin(yaw) * math.cos(pitch), math.sin(pitch))

    def begin_view(self, low, high, size):
        gl.glClearColor(.055, .085, .115, 1)
        self.clear()
        width, height = self.view_size
        self.viewport = (0, self.footer, width, height)
        half = self.state.span / 2
        distance = max(size, self.state.span) * 5 + math.dist(self.state.target, midpoint(low, high))
        center = Vec3(*self.state.target)
        aspect = width / height
        self.projection = Mat4.orthogonal_projection(-half*aspect, half*aspect, -half, half, 1, 2*distance)
        self.view = Mat4.look_at(center + self.camera_direction() * distance, center, Vec3(0, 0, 1))
        return self.projection @ self.view

    def begin_hud(self):
        self.viewport = (0, 0, self.width, self.height)
        self.projection = Mat4.orthogonal_projection(0, self.width, 0, self.height, -1, 1)
        self.view = Mat4()

    def in_view(self, x, y):
        return 0 <= x < self.view_size[0] and self.footer <= y < self.height - self.header

    def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
        if self.drag is None:
            return
        if buttons & (mouse.RIGHT | mouse.MIDDLE) or modifiers & key.MOD_SHIFT:
            direction = self.camera_direction()
            right = Vec3(0, 0, 1).cross(direction).normalize()
            up = direction.cross(right)
            scale = self.state.span / self.view_size[1]
            self.state.target = tuple(Vec3(*self.state.target) - (right * dx + up * dy) * scale)
        else:
            self.state.yaw = (self.state.yaw - dx * .45) % 360
            self.state.pitch = clamp(self.state.pitch - dy * .45, -85, 85)

    def on_mouse_scroll(self, x, y, scroll_x, scroll_y):
        if x < self.view_size[0]:
            self.state.span = clamp(self.state.span * .88 ** clamp(scroll_y, -10, 10),
                                    self.min_span, self.scene.size * 8)


def run_preview(window, port, server_factory):
    if port is None:
        pyglet.app.run()
        return
    with server_factory(port, window) as server:
        worker = Thread(target=server.serve_forever)
        worker.start()
        try:
            print(f'Viewing {window.path} at http://127.0.0.1:{server.server_address[1]}', flush=True)
            pyglet.app.run()
        finally:
            server.shutdown()
            worker.join()
