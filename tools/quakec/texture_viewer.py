"""Native pixel and mip preview for the procedural Quake texture editor."""
from dataclasses import asdict, replace
from functools import partial
from random import randrange

from asset_viewer import ACCENT, EDGE, INK, MUTED, PANEL, WindowRequests, run_preview
import pyglet
from pyglet import gl, shapes
from pyglet.window import key, mouse

from preview_server import viewer_server
from texture_editor import RAMPS, SIZES, TexturePreviewHandler
from texture_pipeline import BLENDS, FILTERS, MAX_STAGES, SOURCES, STAGE_TYPES, Stage

BACKGROUND = (14, 21, 29)
SIDEBAR = (20, 31, 42)
CONTROL = (38, 55, 68)
SELECTED = (36, 70, 77)


TABS = ('Pipeline', 'Texture', 'Palette')
VISIBLE_STAGES = 5


class TextureWindow(WindowRequests, pyglet.window.Window):
    sidebar = 316
    request_timeout = 8

    def __init__(self, document, output):
        super().__init__(width=1100, height=760, caption='Quake texture pipeline', resizable=True)
        self.set_minimum_size(890, 700)
        self.document, self.path = document, output
        self.tiles, self.mip = 3, 0
        self.layout_size = None
        self.buttons = []
        self.editing, self.buffer = None, ''
        self.tab = 'pipeline'
        self.selected = 0
        self.first = 0
        self.adding = None
        self.palette_hover = None
        self.palette_bounds = None
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
        return {'recipe': asdict(self.document.recipe), 'tiles': self.tiles, 'mip': self.mip, 'tab': self.tab}

    def update_remote(self, patch):
        if not isinstance(patch, dict) or patch.keys() - {'recipe', 'tiles', 'mip', 'tab'}:
            raise ValueError('expected a JSON object with recipe, tiles, mip, or tab')
        tiles, mip = patch.get('tiles', self.tiles), patch.get('mip', self.mip)
        if type(tiles) is not int or tiles not in (1, 3):
            raise ValueError('tiles must be 1 or 3')
        if type(mip) is not int or not 0 <= mip <= 3:
            raise ValueError('mip must be an integer from 0 to 3')
        tab = patch.get('tab', self.tab)
        if tab not in ('pipeline', 'texture', 'palette'):
            raise ValueError('tab must be pipeline, texture, or palette')
        previous = self.document.levels
        self.document.apply(patch.get('recipe', {}))
        if self.document.levels is not previous:
            self.refresh_images()
        self.tiles, self.mip, self.tab = tiles, mip, tab
        self.select_stage(self.selected)
        self.adding = None
        self.editing = None
        self.close_pending = False
        self.message(str(self.path))

    def remote_response(self, action, data):
        if action == 'palette':
            return self.document.palette
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

    def select_stage(self, index):
        count = len(self.document.recipe.stages)
        self.selected = max(0, min(index, count - 1))
        self.first = max(0, min(self.first, count - VISIBLE_STAGES, self.selected))
        self.first = max(self.first, self.selected - VISIBLE_STAGES + 1)
        self.editing = None
        self.layout_size = None

    def add_stage(self, kind):
        stages = self.document.recipe.stages
        index = self.selected + 1 if stages else 0
        self.set_recipe(stages=stages[:index] + (Stage(kind),) + stages[index:])
        self.select_stage(index)

    def remove_stage(self):
        stages = self.document.recipe.stages
        self.set_recipe(stages=stages[:self.selected] + stages[self.selected + 1:])

    def move_stage(self, direction):
        stages = list(self.document.recipe.stages)
        index = self.selected
        other = index + direction
        if 0 <= other < len(stages):
            stages[index], stages[other] = stages[other], stages[index]
            self.set_recipe(stages=stages)
            self.select_stage(other)

    def change_stage(self, **changes):
        stages = list(self.document.recipe.stages)
        stages[self.selected] = replace(stages[self.selected], **changes)
        self.set_recipe(stages=stages)

    def change_parameter(self, key, value):
        stage = self.document.recipe.stages[self.selected]
        self.change_stage(params={**stage.params, key: value})

    def toggle_add(self, category):
        self.adding = None if self.adding == category else category
        self.editing = None
        self.layout_size = None

    def begin_edit(self, field, title, change, initial=''):
        self.editing, self.buffer = (field, change), initial
        self.message(f'Enter {title.lower()} and press Return. Esc cancels.')

    def edit(self, field, value):
        return f'{self.buffer}|' if self.editing and self.editing[0] == field else str(value)

    def toggle_index(self, index):
        colors = self.document.recipe.colors
        self.set_recipe(colors=tuple(value for value in colors if value != index)
                        if index in colors else colors + (index,))

    def set_indices(self, text):
        values = tuple(int(value.strip(), 10) for value in text.split(',')) if text.strip() else ()
        self.set_recipe(colors=values)

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
        self.palette_bounds = None

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
        label('Quake texture pipeline', 24, height - 24, 17, bold=True)
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
        for i, tab in enumerate(TABS):
            button(tab, left + 96 * i, height - 111, 88, 28, partial(self.update_remote, {'tab': tab.lower()}),
                   active=self.tab == tab.lower())
        top = height - 129
        if self.tab == 'pipeline':
            self.layout_pipeline(left, top, label, button)
        elif self.tab == 'texture':
            self.layout_texture(left, top, label, button)
        else:
            self.layout_palette(left, top, label, button, partial(rect, group=controls))
        button('Export WAD2, PNG, and recipe', left, 52, 280, 34, self.export, active=True)

    def number(self, x, y, key, title, value, low, high, step, change, label, button):
        label(title, x, y + 38, 9, MUTED)
        button('−', x, y, 26, 26, partial(change, max(low, value - step)))
        button(self.edit(key, value), x + 30, y, 76, 26,
               partial(self.begin_edit, key, title, lambda text: change(int(text, 10))),
               active=self.editing is not None and self.editing[0] == key, size=9)
        button('+', x + 110, y, 26, 26, partial(change, min(high, value + step)))

    def layout_pipeline(self, left, top, label, button):
        recipe = self.document.recipe
        stages = recipe.stages
        if len(stages) < MAX_STAGES:
            button('Add source', left, top - 29, 136, 28, partial(self.toggle_add, 'source'),
                   active=self.adding == 'source')
            button('Add filter', left + 144, top - 29, 136, 28, partial(self.toggle_add, 'filter'),
                   active=self.adding == 'filter')
        else:
            label(f'{MAX_STAGES} stages', left, top - 15, 10, MUTED)
        if self.adding:
            kinds = SOURCES if self.adding == 'source' else FILTERS
            for i, (kind, (name, _)) in enumerate(kinds.items()):
                row, col = divmod(i, 2)
                button(name, left + col * 144, top - 67 - row * 32, 136, 27, partial(self.add_stage, kind))
            return

        label('Stages run from top to bottom', left, top - 49, 9, MUTED)
        for i, stage in enumerate(stages[self.first:self.first + VISIBLE_STAGES], self.first):
            name = STAGE_TYPES[stage.kind][0]
            mode = BLENDS[stage.blend] if stage.kind in SOURCES else 'Filter'
            button(f'{i + 1}. {name} · {mode}', left, top - 92 - (i - self.first) * 29, 280, 25,
                   partial(self.select_stage, i), active=i == self.selected)
        if not stages:
            label('Add a source to start a texture.', left, top - 84)
            return

        if len(stages) > VISIBLE_STAGES:
            more = top - 231
            button('Prev', left, more, 56, 24, partial(self.select_stage, self.selected - 1))
            label(f'{self.first + 1}–{min(self.first + VISIBLE_STAGES, len(stages))} of {len(stages)}',
                  left + 140, more + 12, 9, MUTED, anchor='center')
            button('Next', left + 224, more, 56, 24, partial(self.select_stage, self.selected + 1))

        stage = stages[self.selected]
        name, params = STAGE_TYPES[stage.kind]
        y = top - 246 if len(stages) > VISIBLE_STAGES else top - 100 - 29 * len(stages)
        label(name, left, y, 11, bold=True)
        button('↑', left + 178, y - 12, 27, 24, partial(self.move_stage, -1))
        button('↓', left + 211, y - 12, 27, 24, partial(self.move_stage, 1))
        button('×', left + 244, y - 12, 36, 24, self.remove_stage)
        if stage.kind in SOURCES:
            modes = tuple(BLENDS)
            next_mode = modes[(modes.index(stage.blend) + 1) % len(modes)]
            label('Blend', left + 144, y - 19, 9, MUTED)
            button(f'{BLENDS[stage.blend]} ›', left + 144, y - 57, 136, 26,
                   partial(self.change_stage, blend=next_mode))
        self.number(left, y - 57, 'amount', 'Amount %', stage.amount, 0, 100, 5,
                    lambda value: self.change_stage(amount=value), label, button)
        for i, (key, param) in enumerate(params.items()):
            row, col = divmod(i, 2)
            self.number(left + 144 * col, y - 110 - row * 51, key, param.label, stage.params[key],
                        param.low, param.high, param.step, partial(self.change_parameter, key), label, button)

    def layout_texture(self, left, top, label, button):
        recipe = self.document.recipe
        for i, (field, title, change) in enumerate((
                ('name', 'Texture name', lambda text: self.set_recipe(name=text)),
                ('seed', 'Seed', lambda text: self.set_recipe(seed=int(text, 10))))):
            y = top - 53 - 65 * i
            label(title, left, y + 38, 9, MUTED)
            width = 280 if field == 'name' else 212
            button(self.edit(field, getattr(recipe, field)), left, y, width, 28,
                   partial(self.begin_edit, field, title, change))
        button('New', left + 220, top - 118, 60, 28, lambda: self.set_recipe(seed=randrange(2**32)))
        for i, field in enumerate(('width', 'height')):
            x, y = left + i * 144, top - 183
            label(field.title(), x, y + 39, 9, MUTED)
            button('−', x, y, 32, 28, partial(self.step_size, field, -1))
            label(str(getattr(recipe, field)), x + 68, y + 14, anchor='center')
            button('+', x + 104, y, 32, 28, partial(self.step_size, field, 1))

    def layout_palette(self, left, top, label, button, rect):
        recipe = self.document.recipe
        label('Click palette colors in ramp order', left, top - 7, 9, MUTED)
        bottom = top - 285
        self.palette_bounds = (left, bottom, 272, 256)
        for index, rgb in enumerate(self.document.palette):
            row, column = divmod(index, 16)
            x, y = left + 17 * column, bottom + 16 * (15 - row)
            if index in recipe.colors:
                rect(x, y, 17, 16, ACCENT[:3])
                rect(x + 2, y + 2, 13, 12, rgb)
            else:
                rect(x, y, 16, 15, rgb)
        if self.palette_hover is not None:
            index = self.palette_hover
            red, green, blue = self.document.palette[index]
            label(f'Index {index}  ·  RGB {red}, {green}, {blue}', left, bottom - 14, 9, MUTED)

        name = f'Custom ramp · {len(recipe.colors)} colors' if recipe.colors else RAMPS[recipe.ramp][0]
        label(name, left, bottom - 43, 10, bold=True)
        indices = ','.join(map(str, recipe.indices))
        button('Edit indices', left + 186, bottom - 56, 94, 25,
               partial(self.begin_edit, 'colors', 'comma-separated palette indices', self.set_indices, indices))
        if self.editing is not None and self.editing[0] == 'colors':
            label(f'{self.buffer[-39:]}|', left, bottom - 67, 9, MUTED)
        for i, index in enumerate(recipe.indices):
            x, end = round(left + 280 * i / len(recipe.indices)), round(left + 280 * (i + 1) / len(recipe.indices))
            rect(x, bottom - 88, end - x, 13, self.document.palette[index])

        for i, (ramp, (name, _)) in enumerate(RAMPS.items()):
            row, col = divmod(i, 3)
            button(name, left + 96 * col, bottom - 127 - row * 32, 88, 26,
                   partial(self.set_recipe, ramp=ramp, colors=()), active=ramp == recipe.ramp and not recipe.colors)

    @staticmethod
    def contains(x, y, bounds):
        left, bottom, w, h = bounds
        return left <= x < left + w and bottom <= y < bottom + h

    def palette_index(self, x, y):
        if self.palette_bounds and self.contains(x, y, self.palette_bounds):
            left, bottom, _, _ = self.palette_bounds
            return (15 - int((y - bottom) // 16)) * 16 + int((x - left) // 17)
        return None

    def on_mouse_press(self, x, y, button, modifiers):
        if button != mouse.LEFT:
            return
        if self.layout_size is None:
            self.layout()
        index = self.palette_index(x, y)
        if index is not None:
            self.toggle_index(index)
            return
        for *bounds, action in self.buttons:
            if self.contains(x, y, bounds):
                try:
                    action()
                except (OSError, ValueError) as error:
                    self.message(str(error))
                return

    def on_mouse_motion(self, x, y, dx, dy):
        index = self.palette_index(x, y)
        if index != self.palette_hover:
            self.palette_hover = index
            self.layout_size = None

    def on_mouse_scroll(self, x, y, scroll_x, scroll_y):
        if self.tab == 'pipeline' and self.adding is None and x >= self.width - self.sidebar:
            self.select_stage(self.selected - int(scroll_y))

    def on_text(self, text):
        if self.editing is None:
            return
        field, _ = self.editing
        limit, alphabet = {
            'name': (15, 'abcdefghijklmnopqrstuvwxyz0123456789_'),
            'colors': (1023, '0123456789, '),
        }.get(field, (11, '-0123456789'))
        if len(self.buffer + text) <= limit and all(c in alphabet for c in text):
            self.buffer += text
            self.layout_size = None

    def on_key_press(self, symbol, modifiers):
        if self.editing is None:
            return super().on_key_press(symbol, modifiers)
        if symbol == key.ENTER:
            try:
                self.editing[1](self.buffer)
            except ValueError as error:
                self.message(str(error))
        elif symbol == key.BACKSPACE:
            self.buffer = self.buffer[:-1]
            self.layout_size = None
        elif symbol == key.A and modifiers & (key.MOD_CTRL | key.MOD_COMMAND):
            self.buffer = ''
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
