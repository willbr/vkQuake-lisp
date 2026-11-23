"""Interactive editing and preview of stock Quake MDL recipes."""
from dataclasses import asdict
from functools import partial
import math

from asset_viewer import (
    ACCENT, EDGE, INK, MUTED, PANEL, Camera, OrbitWindow,
    bounds, clamp, midpoint, run_preview, update_camera,
)
import pyglet
from pyglet import gl, shapes
from pyglet.math import Vec4
from pyglet.window import key, mouse

from map_editor import dot
from preview_server import viewer_server

ACCENT_RGB = tuple(channel / 255 for channel in ACCENT[:3])
PANEL_BUTTON = (38, 55, 68)
SIDEBAR = (20, 31, 42)
SELECTED = (39, 70, 79)


class ModelScene:
    def __init__(self, document, frame, selected, palette):
        self.triangles, self.edges, self.faces = [], [], []
        vertices = document.model.vertices if frame is None else document.frames[frame]
        owner = {i: name for name, (start, end) in document.parts.items() for i in range(start, end)}
        for _, *indices in document.model.triangles:
            name = owner[indices[0]]
            points = [vertices[i][0] for i in indices]
            self.faces.append((name, points))
            for i in indices:
                position, normal, material = vertices[i]
                rgb = palette[document.recipe['palette'][material]]
                intensity = .57 + .43 * max(0, dot(document.model.normals[normal], (.67, -.35, .65)))
                self.triangles.append((position, tuple(.06 + .94 * channel * intensity / 255
                                                       for channel in rgb)))
            line_color = ACCENT_RGB if name == selected else (.15, .23, .29)
            for a, b in zip(points, points[1:] + points[:1]):
                self.edges.extend(((a, line_color), (b, line_color)))
        self.low, self.high = bounds([point for point, _, _ in vertices])
        self.size = max(1, math.dist(self.low, self.high))
        self.grid = self.floor_grid()

    def floor_grid(self):
        x, y, _ = midpoint(self.low, self.high)
        z = self.low[2] - .05
        spacing = 2 ** math.floor(math.log2(self.size / 8))
        radius = 7 * spacing
        color = (.16, .24, .30)
        lines = []
        for i in range(-7, 8):
            t = i * spacing
            lines.extend((((x+t, y-radius, z), color), ((x+t, y+radius, z), color),
                          ((x-radius, y+t, z), color), ((x+radius, y+t, z), color)))
        return lines


def hit_depth(point, triangle):
    x, y = point
    a, b, c = triangle
    denominator = (b.y-c.y)*(a.x-c.x) + (c.x-b.x)*(a.y-c.y)
    if abs(denominator) < 1e-8:
        return math.inf
    u = ((b.y-c.y)*(x-c.x) + (c.x-b.x)*(y-c.y)) / denominator
    v = ((c.y-a.y)*(x-c.x) + (a.x-c.x)*(y-c.y)) / denominator
    w = 1-u-v
    return u*a.z + v*b.z + w*c.z if min(u, v, w) >= -1e-6 else math.inf


class ModelWindow(OrbitWindow):
    sidebar = 302
    footer = 42
    min_span = 1

    def __init__(self, document, output, palette):
        self.document, self.path, self.output = document, document.path, output
        super().__init__(f'{self.path.name} · Quake model editor', width=1160, height=750,
                         minimum=(780, 660))
        self.palette = palette
        self.part = next(iter(document.parts))
        self.frame = None
        self.size_mode = False
        self.first_part = 0
        self.rows = 1
        self.part_list_top = 0
        self.buttons = []
        self.editing = None
        self.text = ''
        self.status = ''
        self.close_pending = False
        self.meshes = ()
        self.state = Camera((0, 0, 0), -35, 20, 64)
        self.rebuild()
        self.fit()

    def rebuild(self):
        self.switch_to()
        self.scene = ModelScene(self.document, self.frame, self.part, self.palette)
        for model in self.meshes:
            model.delete()
        self.meshes = (self.mesh(self.scene.triangles, gl.GL_TRIANGLES),
                       self.mesh(self.scene.edges, gl.GL_LINES),
                       self.mesh(self.scene.grid, gl.GL_LINES))
        self.close_pending = False
        self.layout_size = None

    def fit(self):
        self.state.target = midpoint(self.scene.low, self.scene.high)
        width, height = self.view_size
        self.state.span = max(1, self.scene.size * 1.19 / min(1, width/height))

    def on_draw(self):
        self.matrix = self.begin_view(self.scene.low, self.scene.high, self.scene.size)
        triangles, edges, grid = self.meshes
        gl.glEnable(gl.GL_DEPTH_TEST)
        with self.program:
            self.program['slab'] = (-1e8, 1e8)
            grid.draw(gl.GL_LINES)
            gl.glEnable(gl.GL_POLYGON_OFFSET_FILL)
            gl.glPolygonOffset(2, 2)
            triangles.draw(gl.GL_TRIANGLES)
            gl.glDisable(gl.GL_POLYGON_OFFSET_FILL)
            edges.draw(gl.GL_LINES)
        gl.glDisable(gl.GL_DEPTH_TEST)
        self.begin_hud()
        if self.layout_size != self.get_size():
            self.layout()
        self.hud.draw()

    def layout(self):
        self.layout_size = self.get_size()
        width, height = self.layout_size
        left = width - self.sidebar + 18
        right = width - 18
        self.hud = pyglet.graphics.Batch()
        backgrounds, controls, text = (pyglet.graphics.Group(order=i) for i in range(3))
        self.items, self.buttons = [], []

        def rectangle(x, y, w, h, color, group=backgrounds):
            self.items.append(shapes.Rectangle(x, y, w, h, color=color, batch=self.hud, group=group))

        def label(value, x, y, size=10, color=INK, **kwargs):
            self.items.append(pyglet.text.Label(value, x=x, y=y, anchor_y='center', font_size=size,
                                                color=color, batch=self.hud, group=text, **kwargs))

        def button(value, x, y, w, h, action, *, color=PANEL_BUTTON, ink=INK, size=10):
            rectangle(x, y, w, h, color, controls)
            label(value, x+9, y+h/2, size, ink)
            self.buttons.append((x, y, w, h, action))

        rectangle(0, height-self.header, width, self.header, PANEL)
        rectangle(0, 0, width, self.footer, PANEL)
        rectangle(width-self.sidebar, self.footer, self.sidebar, self.view_size[1], SIDEBAR)
        rectangle(width-self.sidebar, self.footer, 1, self.view_size[1], EDGE)
        name = self.document.recipe.get('name', self.path.stem)
        label(name, 22, height-24, 17, weight='bold')
        model = self.document.model
        flag = '  ·  Unsaved edits' if self.document.dirty else ''
        label(f'{self.path.name}  ·  {len(model.vertices)} vertices  ·  {len(model.triangles)} triangles{flag}',
              23, height-47, 9, MUTED)
        button('Fit view', right-89, height-44, 89, 28, self.fit)

        label('Pose', left, height-84, 12, weight='bold')
        y = height-129
        button('‹', left, y, 30, 28, partial(self.cycle_pose, -1), size=14)
        label(self.frame or 'Base mesh', left+44, y+14, 11)
        button('›', right-119, y, 30, 28, partial(self.cycle_pose, 1), size=14)
        button('+ Pose', right-79, y, 79, 28, self.add_pose)

        label('Parts', left, y-26, 12, weight='bold')
        button('+ Box', right-79, y-39, 79, 25, self.add_box)
        names = list(self.document.parts)
        rows = min(len(names), 7, max(4, (height-528)//28))
        self.first_part = min(self.first_part, max(0, len(names)-rows))
        self.rows = rows
        self.part_list_top = y-54
        parts = names[self.first_part:self.first_part+rows]
        for i, name in enumerate(parts):
            button(name[:32], left, self.part_list_top-27*(i+1), right-left, 24,
                   partial(self.select, name), color=SELECTED if name == self.part else PANEL_BUTTON)
        if rows < len(names):
            label(f'{self.first_part+1}–{self.first_part+len(parts)} of {len(names)}', left,
                  self.part_list_top-27*rows-12, 9, MUTED)

        start = self.part_list_top-27*rows-40
        caption = 'Pose offset' if self.frame else 'Box size' if self.size_mode else 'Position'
        label(caption, left, start, 12, weight='bold')
        if self.frame is None and 'low' in self.document.recipe['parts'][self.part]:
            button('Position' if self.size_mode else 'Size', right-79, start-13, 79, 25, self.toggle_size)
        coordinates = self.document.coordinates(self.part, self.frame, self.size_mode)
        for i, (axis, value) in enumerate(zip('XYZ', coordinates)):
            y = start-43-33*i
            label(axis, left+1, y+13, 10, MUTED)
            button('−', left+29, y, 32, 26, partial(self.nudge, i, -1))
            active = self.editing == i
            display = self.text+'│' if active else f'{value:.5g}'
            button(display[:22], left+66, y, right-left-103, 26, partial(self.edit_value, i),
                   color=SELECTED if active else PANEL_BUTTON)
            button('+', right-32, y, 32, 26, partial(self.nudge, i, 1))

        y = start-171
        label('Palette', left, y, 12, weight='bold')
        current = self.document.recipe['parts'][self.part].get('material', 0)
        for slot, index in enumerate(self.document.recipe['palette']):
            x = left + 33*slot
            rgb = self.palette[index]
            if current == slot:
                rectangle(x-1, y-40, 31, 29, ACCENT, controls)
            ink = (20, 31, 42, 255) if max(rgb) > 180 else INK
            button(str(index), x, y-38, 29, 25, partial(self.apply_material, slot),
                   color=rgb, ink=ink, size=8)

        label(self.status or 'Drag to orbit  ·  Right or Shift-drag to pan  ·  Scroll to zoom',
              22, 21, 9, MUTED)
        button('Save recipe', right-258, 7, 125, 28, self.save)
        button('Export MDL', right-125, 7, 125, 28, self.export, color=ACCENT, ink=(16, 29, 34, 255))

    def message(self, status):
        self.status = status
        self.layout_size = None

    def select(self, part):
        self.part, self.size_mode, self.editing = part, False, None
        self.rebuild()

    def keep_part_visible(self):
        index = list(self.document.parts).index(self.part)
        self.first_part = clamp(self.first_part, max(0, index-self.rows+1), index)

    def cycle_pose(self, direction):
        options = (None, *self.document.frames)
        self.frame = options[(options.index(self.frame)+direction) % len(options)]
        self.size_mode, self.editing = False, None
        self.rebuild()

    def add_pose(self):
        self.frame = self.document.add_frame(self.frame)
        self.size_mode, self.editing = False, None
        self.rebuild()

    def add_box(self):
        self.frame = None
        self.select(self.document.add_box())
        self.keep_part_visible()
        self.fit()

    def toggle_size(self):
        self.size_mode = not self.size_mode
        self.editing = None
        self.layout_size = None

    def apply_material(self, slot):
        self.document.set_material(self.part, slot)
        self.rebuild()

    def change_value(self, index, value):
        values = list(self.document.coordinates(self.part, self.frame, self.size_mode))
        values[index] = value
        self.document.set_coordinates(self.part, self.frame, values, self.size_mode)
        self.editing = None
        self.close_pending = False
        self.rebuild()

    def nudge(self, index, direction):
        value = self.document.coordinates(self.part, self.frame, self.size_mode)[index]
        self.change_value(index, value+direction)

    def edit_value(self, index):
        self.editing = index
        self.text = ''
        self.message('Type a coordinate and press Return · Esc cancels')

    def save(self):
        self.document.save()
        self.close_pending = False
        self.message(f'Saved {self.path.name}')

    def export(self):
        self.document.export(self.output)
        self.message(f'Exported {self.output.name}')

    def on_mouse_press(self, x, y, button, modifiers):
        if button == mouse.LEFT:
            for left, bottom, w, h, action in self.buttons:
                if left <= x < left+w and bottom <= y < bottom+h:
                    try:
                        action()
                    except (OSError, ValueError, TypeError) as error:
                        self.message(str(error))
                    return
        if self.in_view(x, y):
            self.drag = (x, y)

    def on_mouse_release(self, x, y, button, modifiers):
        if button == mouse.LEFT and self.drag and math.dist(self.drag, (x, y)) < 3:
            width, height = self.view_size
            plane = (2*x/width-1, 2*(y-self.footer)/height-1)
            hits = ((hit_depth(plane, [self.matrix @ Vec4(*p, 1) for p in points]), name)
                    for name, points in self.scene.faces)
            depth, name = min(hits, default=(math.inf, None))
            if math.isfinite(depth):
                self.select(name)
                self.keep_part_visible()
        self.drag = None

    def on_mouse_scroll(self, x, y, scroll_x, scroll_y):
        if x >= self.view_size[0] and self.part_list_top-27*self.rows <= y <= self.part_list_top:
            self.first_part = clamp(self.first_part-int(scroll_y), 0, max(0, len(self.document.parts)-self.rows))
            self.layout_size = None
        else:
            super().on_mouse_scroll(x, y, scroll_x, scroll_y)

    def on_text(self, text):
        if self.editing is not None and len(self.text) + len(text) < 22 and all(
            char in '0123456789.eE+-' for char in text
        ):
            self.text += text
            self.layout_size = None

    def on_key_press(self, symbol, modifiers):
        if self.editing is not None:
            if symbol == key.ENTER:
                try:
                    self.change_value(self.editing, float(self.text))
                    self.message('')
                except (ValueError, TypeError) as error:
                    self.message(str(error))
            elif symbol == key.BACKSPACE:
                self.text = self.text[:-1]
                self.layout_size = None
            elif symbol == key.ESCAPE:
                self.editing = None
                self.message('')
            return
        if symbol == key.F:
            self.fit()
        elif symbol == key.S and modifiers & (key.MOD_CTRL | key.MOD_COMMAND):
            try:
                self.save()
            except (OSError, ValueError) as error:
                self.message(str(error))
        else:
            return super().on_key_press(symbol, modifiers)

    def on_close(self):
        if self.document.dirty and not self.close_pending:
            self.close_pending = True
            self.message('Unsaved edits. Save the recipe or close the window again to discard.')
            return pyglet.event.EVENT_HANDLED
        return super().on_close()

    def remote_state(self):
        return {**asdict(self.state), 'part': self.part, 'pose': self.frame,
                'parts': list(self.document.parts), 'poses': list(self.document.frames),
                'position': self.document.coordinates(self.part, self.frame), 'dirty': self.document.dirty}

    def update_remote(self, patch):
        if not isinstance(patch, dict):
            raise ValueError('expected a JSON object with view fields')
        if patch.keys() - {'target', 'yaw', 'pitch', 'span', 'pose', 'part', 'position'}:
            raise ValueError('unknown model view field')
        part = patch.get('part', self.part)
        frame = patch.get('pose', self.frame)
        if part not in self.document.parts or (frame is not None and frame not in self.document.frames):
            raise ValueError('unknown part or pose')
        state = update_camera(self.state, {k: v for k, v in patch.items() if k in asdict(self.state)})
        if 'position' in patch:
            self.document.set_coordinates(part, frame, patch['position'])
        if part != self.part or frame != self.frame or 'position' in patch:
            self.part, self.frame = part, frame
            self.size_mode, self.editing = False, None
            self.rebuild()
            self.keep_part_visible()
        self.state = state


def run_viewer(document, output, palette, port):
    run_preview(ModelWindow(document, output, palette), port, viewer_server)
