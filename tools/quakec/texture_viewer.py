"""Native pixel and mip preview for the procedural Quake texture editor."""
from dataclasses import asdict
from functools import partial
from random import randrange

from asset_viewer import ACCENT, EDGE, INK, MUTED, PANEL, WindowRequests, run_preview
import pyglet
from pyglet import gl, shapes
from pyglet.window import key, mouse

from preview_server import viewer_server
from texture_editor import MATERIALS, RAMPS, SCALES, SIZES, TexturePreviewHandler

BACKGROUND = (14, 21, 29)
SIDEBAR = (20, 31, 42)
CONTROL = (38, 55, 68)
SELECTED = (36, 70, 77)


class TextureWindow(WindowRequests, pyglet.window.Window):
    sidebar = 316

    def __init__(self, document, output):
        super().__init__(width=1100, height=760, caption='Quake texture generator', resizable=True)
        self.set_minimum_size(890, 700)
        self.document, self.path = document, output
        self.tiles, self.mip = 3, 0
        self.layout_size = None
        self.buttons = []
        self.editing, self.buffer = None, ''
        self.wear_drag = None
        self.status = str(output)
        self.saved = document.recipe
        self.close_pending = False
        self.images = ()
        self.refresh_images()
        self.start_requests()

    def refresh_images(self):
        self.switch_to()
        for image in self.images:
            image.delete()
        palette = tuple(bytes(rgb) for rgb in self.document.palette)
        recipe = self.document.recipe
        images = []
        for mip, pixels in enumerate(self.document.levels):
            width, height = recipe.width >> mip, recipe.height >> mip
            rgb = b''.join(palette[index] for index in pixels)
            image = pyglet.image.ImageData(width, height, 'RGB', rgb, pitch=-3 * width)
            images.append(image.get_texture())
            texture = images[-1]
            gl.glBindTexture(texture.target, texture.id)
            gl.glTexParameteri(texture.target, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
            gl.glTexParameteri(texture.target, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        self.images = tuple(images)

    def message(self, status):
        self.status = status
        self.layout_size = None

    def remote_state(self):
        return {'recipe': asdict(self.document.recipe), 'tiles': self.tiles, 'mip': self.mip}

    def update_remote(self, patch):
        if not isinstance(patch, dict) or patch.keys() - {'recipe', 'tiles', 'mip'}:
            raise ValueError('expected a JSON object with recipe, tiles, or mip')
        tiles, mip = patch.get('tiles', self.tiles), patch.get('mip', self.mip)
        if type(tiles) is not int or tiles not in (1, 3):
            raise ValueError('tiles must be 1 or 3')
        if type(mip) is not int or not 0 <= mip <= 3:
            raise ValueError('mip must be an integer from 0 to 3')
        previous = self.document.levels
        self.document.apply(patch.get('recipe', {}))
        if self.document.levels is not previous:
            self.refresh_images()
        self.tiles, self.mip = tiles, mip
        self.editing = None
        self.close_pending = False
        self.message(str(self.path))

    def remote_response(self, action, data):
        if action == 'recipe':
            return asdict(self.document.recipe)
        if action == 'png':
            return self.document.png()
        if action == 'wad':
            return self.document.wad()
        return super().remote_response(action, data)

    def set_recipe(self, **fields):
        self.update_remote({'recipe': fields})

    def step_size(self, field, direction):
        current = getattr(self.document.recipe, field)
        index = min(len(SIZES) - 1, max(0, SIZES.index(current) + direction))
        self.set_recipe(**{field: SIZES[index]})

    def begin_edit(self, field):
        self.editing, self.buffer = field, ''
        self.message(f'Type a {field} and press Return. Esc cancels.')

    def export(self):
        self.document.export(self.path)
        self.saved = self.document.recipe
        self.close_pending = False
        self.message(f'Exported {self.saved.name}.wad, .png, and .json to {self.path}')

    def on_draw(self):
        gl.glClearColor(*(c / 255 for c in BACKGROUND), 1)
        self.clear()
        if self.layout_size != self.get_size():
            self.layout()
        self.batch.draw()
        image = self.images[self.mip]
        x, y, width, height = self.well
        self.draw_tiles(image, x, y, width, height, self.tiles)
        for level, bounds in enumerate(self.thumbnails):
            self.draw_tiles(self.images[level], *bounds, 1)

    @staticmethod
    def draw_tiles(image, left, bottom, area_width, area_height, tiles):
        zoom = min(area_width / image.width, area_height / image.height) / tiles
        width, height = image.width * zoom, image.height * zoom
        x = round(left + (area_width - tiles * width) / 2)
        y = round(bottom + (area_height - tiles * height) / 2)
        for row in range(tiles):
            for column in range(tiles):
                image.blit(x + column * width, y + row * height, width=width, height=height)

    def layout(self):
        width, height = self.layout_size = self.get_size()
        sidebar = width - self.sidebar
        recipe = self.document.recipe
        self.batch = pyglet.graphics.Batch()
        base, controls, text = (pyglet.graphics.Group(order=i) for i in range(3))
        self.items, self.buttons = [], []

        def rect(x, y, w, h, color, group=base):
            self.items.append(shapes.Rectangle(x, y, w, h, color=color, batch=self.batch, group=group))

        def label(value, x, y, size=10, color=INK, *, anchor='left', bold=False, **kwargs):
            self.items.append(pyglet.text.Label(
                value, x=x, y=y, anchor_x=anchor, anchor_y='center', font_size=size, color=color,
                weight='bold' if bold else 'normal', batch=self.batch, group=text, **kwargs))

        def button(value, x, y, w, h, action, *, active=False, size=10):
            rect(x, y, w, h, SELECTED if active else CONTROL, controls)
            if value:
                label(value, x + w / 2, y + h / 2, size, ACCENT if active else INK, anchor='center')
            self.buttons.append((x, y, w, h, action))

        rect(0, height - 66, width, 66, PANEL)
        rect(sidebar, 36, self.sidebar, height - 102, SIDEBAR)
        rect(sidebar, 36, 1, height - 102, EDGE)
        rect(0, 0, width, 36, PANEL)
        label('Quake texture generator', 24, height - 24, 17, bold=True)
        dirty = '  ·  Unsaved edits' if recipe != self.saved else ''
        label(f'{recipe.name}  ·  {recipe.width} × {recipe.height}  ·  Indexed color{dirty}',
              25, height - 48, 10, MUTED)
        label(self.status, 24, 18, 9, MUTED, width=width - 48)

        label('Preview', 24, height - 97, 12, bold=True)
        button('Single', sidebar - 178, height - 111, 70, 28, partial(self.update_remote, {'tiles': 1}),
               active=self.tiles == 1)
        button('3 × 3', sidebar - 100, height - 111, 76, 28, partial(self.update_remote, {'tiles': 3}),
               active=self.tiles == 3)
        rect(24, 174, sidebar - 48, height - 296, EDGE)
        rect(25, 175, sidebar - 50, height - 298, BACKGROUND, controls)
        self.well = (34, 184, sidebar - 68, height - 316)

        label('Mip levels', 24, 151, 11, bold=True)
        self.thumbnails = []
        stride = (sidebar - 48) / 4
        for mip in range(4):
            x, w = 24 + mip * stride, stride - 8
            button('', x, 54, w, 77, partial(self.update_remote, {'mip': mip}), active=self.mip == mip)
            self.thumbnails.append((x + 8, 62, w - 16, 41))
            label(f'{recipe.width >> mip} × {recipe.height >> mip}', x + w / 2, 118, 9,
                  ACCENT if self.mip == mip else MUTED, anchor='center')

        left = sidebar + 18
        cell = 136
        label('Material', left, height - 94, 12, bold=True)
        for i, (material, (name, _)) in enumerate(MATERIALS.items()):
            row, column = divmod(i, 2)
            button(name, left + column * (cell + 8), height - 137 - row * 33, cell, 28,
                   partial(self.set_recipe, material=material), active=recipe.material == material)

        label('Palette ramp', left, height - 225, 12, bold=True)
        for i, (ramp, (name, colors)) in enumerate(RAMPS.items()):
            row, column = divmod(i, 2)
            x, y = left + column * (cell + 8), height - 267 - row * 36
            rect(x, y, cell, 31, SELECTED if ramp == recipe.ramp else CONTROL, controls)
            label(name, x + 8, y + 21, 9, ACCENT if ramp == recipe.ramp else INK)
            for j, index in enumerate(colors):
                rect(x + 8 + 10 * j, y + 5, 10, 6, self.document.palette[index], text)
            self.buttons.append((x, y, cell, 31, partial(self.set_recipe, ramp=ramp)))

        label('Texture name', left, height - 365, 10, MUTED)
        label('Seed', left + 149, height - 365, 10, MUTED)
        name = f'{self.buffer}|' if self.editing == 'name' else recipe.name
        seed = f'{self.buffer}|' if self.editing == 'seed' else str(recipe.seed)
        button(name, left, height - 404, 141, 28, partial(self.begin_edit, 'name'),
               active=self.editing == 'name', size=9)
        button(seed, left + 149, height - 404, 88, 28, partial(self.begin_edit, 'seed'),
               active=self.editing == 'seed')
        button('New', left + 245, height - 404, 35, 28, lambda: self.set_recipe(seed=randrange(2**32)))

        for i, field in enumerate(('width', 'height')):
            x, y = left + i * (cell + 8), height - 469
            label(field.title(), x, y + 39, 10, MUTED)
            button('−', x, y, 32, 28, partial(self.step_size, field, -1))
            label(str(getattr(recipe, field)), x + cell / 2, y + 14, anchor='center')
            button('+', x + cell - 32, y, 32, 28, partial(self.step_size, field, 1))

        label('Pattern repeats', left, height - 496, 10, MUTED)
        for i, scale in enumerate(SCALES):
            button(str(scale), left + 96 * i, height - 534, 88, 28,
                   partial(self.set_recipe, scale=scale), active=recipe.scale == scale)

        wear = recipe.wear if self.wear_drag is None else self.wear_drag
        label('Wear', left, height - 555, 10, MUTED)
        label(f'{wear}%', left + 280, height - 555, 10, MUTED, anchor='right')
        self.slider = (left, height - 582, 280, 15)
        x, y, w, h = self.slider
        rect(x, y + 6, w, 3, EDGE, controls)
        rect(x, y + 6, w * wear / 100, 3, ACCENT[:3], text)
        rect(x + (w - 8) * wear / 100, y + 2, 8, 11, ACCENT[:3], text)

        button('Export WAD2, PNG, and recipe', left, height - 642, 280, 34, self.export, active=True)

    @staticmethod
    def contains(x, y, bounds):
        left, bottom, w, h = bounds
        return left <= x < left + w and bottom <= y < bottom + h

    def set_wear_drag(self, x):
        left, _, width, _ = self.slider
        self.wear_drag = max(0, min(100, round((x - left) * 100 / width)))
        self.layout_size = None

    def on_mouse_press(self, x, y, button, modifiers):
        if button != mouse.LEFT:
            return
        if self.layout_size is None:
            self.layout()
        if self.contains(x, y, self.slider):
            self.set_wear_drag(x)
            return
        for *bounds, action in self.buttons:
            if self.contains(x, y, bounds):
                try:
                    action()
                except (OSError, ValueError) as error:
                    self.message(str(error))
                return

    def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
        if self.wear_drag is not None:
            self.set_wear_drag(x)

    def on_mouse_release(self, x, y, button, modifiers):
        if self.wear_drag is not None and button == mouse.LEFT:
            wear, self.wear_drag = self.wear_drag, None
            self.set_recipe(wear=wear)

    def on_text(self, text):
        if self.editing == 'name':
            if len(self.buffer + text) <= 15 and all(c in 'abcdefghijklmnopqrstuvwxyz0123456789_' for c in text):
                self.buffer += text
                self.layout_size = None
        elif self.editing == 'seed':
            if len(self.buffer + text) <= 10 and all(c in '0123456789' for c in text):
                self.buffer += text
                self.layout_size = None

    def on_key_press(self, symbol, modifiers):
        if self.editing is None:
            return super().on_key_press(symbol, modifiers)
        if symbol == key.ENTER:
            try:
                value = int(self.buffer, 10) if self.editing == 'seed' else self.buffer
                self.set_recipe(**{self.editing: value})
            except ValueError as error:
                self.message('Enter a seed from 0 to 4294967295.' if self.editing == 'seed' else str(error))
        elif symbol == key.BACKSPACE:
            self.buffer = self.buffer[:-1]
            self.layout_size = None
        elif symbol == key.ESCAPE:
            self.editing = None
            self.message(str(self.path))

    def on_close(self):
        if self.document.recipe != self.saved and not self.close_pending:
            self.close_pending = True
            self.message('Export to keep the recipe, or close the window again to discard edits.')
            return pyglet.event.EVENT_HANDLED
        return super().on_close()


def run_viewer(document, output, port):
    window = TextureWindow(document, output)
    run_preview(window, port, partial(viewer_server, handler=TexturePreviewHandler))
