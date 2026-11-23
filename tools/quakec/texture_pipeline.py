"""Tileable scalar sources and filters for indexed Quake textures."""
from dataclasses import dataclass, field
import math
import random


@dataclass(frozen=True)
class Parameter:
    label: str
    low: int
    high: int
    default: int
    step: int = 1


COLUMNS = Parameter('Columns', 2, 64, 8)
ROWS = Parameter('Rows', 2, 64, 8)
RADIUS = Parameter('Radius in texels', 1, 12, 1)
SEED_OFFSET = Parameter('Seed offset', 0, 65535, 0)
SOURCES = {
    'solid': ('Solid', {'value': Parameter('Value', 0, 100, 50, 5)}),
    'value': ('Value noise', {'columns': COLUMNS, 'rows': ROWS, 'seed_offset': SEED_OFFSET}),
    'fractal': ('Fractal noise', {'columns': COLUMNS, 'rows': ROWS,
                                 'octaves': Parameter('Octaves', 1, 5, 4),
                                 'gain': Parameter('Gain %', 0, 100, 50, 5),
                                 'seed_offset': SEED_OFFSET}),
    'cellular': ('Cellular noise', {'columns': COLUMNS, 'rows': ROWS,
                                   'jitter': Parameter('Jitter %', 0, 100, 100, 5),
                                   'seed_offset': SEED_OFFSET}),
    'white': ('White noise', {'seed_offset': SEED_OFFSET}),
    'bands': ('Bands', {'across': Parameter('X cycles', -32, 32, 4),
                        'down': Parameter('Y cycles', -32, 32, 4),
                        'width': Parameter('Band width %', 0, 100, 50, 5),
                        'phase': Parameter('Phase %', 0, 100, 0, 5)}),
    'grid': ('Grid', {'columns': COLUMNS, 'rows': ROWS,
                     'gap': Parameter('Gap %', 0, 100, 15, 5),
                     'stagger': Parameter('Stagger %', 0, 100, 50, 5)}),
}
FILTERS = {
    'blur': ('Blur', {'radius': RADIUS}),
    'sharpen': ('Sharpen', {'radius': RADIUS}),
    'emboss': ('Emboss', {'distance': Parameter('Distance in texels', 1, 12, 1),
                          'angle': Parameter('Angle in degrees', 0, 359, 45, 15)}),
    'threshold': ('Threshold', {'cutoff': Parameter('Cutoff %', 0, 100, 50, 5)}),
    'invert': ('Invert', {}),
}
STAGE_TYPES = {**SOURCES, **FILTERS}
BLENDS = {'mix': 'Mix', 'add': 'Add', 'multiply': 'Multiply', 'min': 'Darken', 'max': 'Lighten'}
MAX_STAGES = 12


@dataclass(frozen=True)
class Stage:
    kind: str
    amount: int = 100
    blend: str = 'mix'
    params: dict = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.kind, str) or self.kind not in STAGE_TYPES:
            raise ValueError('unknown source or filter')
        if type(self.amount) is not int or not 0 <= self.amount <= 100:
            raise ValueError('stage amount must be an integer from 0 to 100')
        modes = BLENDS if self.kind in SOURCES else ('mix',)
        if not isinstance(self.blend, str) or self.blend not in modes:
            raise ValueError('invalid blend mode for this stage')
        parameters = STAGE_TYPES[self.kind][1]
        if not isinstance(self.params, dict) or self.params.keys() - parameters.keys():
            raise ValueError(f'unknown {self.kind} parameter')
        values = {key: self.params.get(key, param.default) for key, param in parameters.items()}
        for key, param in parameters.items():
            if type(values[key]) is not int or not param.low <= values[key] <= param.high:
                raise ValueError(f'{param.label} must be an integer from {param.low} to {param.high}')
        object.__setattr__(self, 'params', values)

    @classmethod
    def parse(cls, value):
        if isinstance(value, cls):
            return value
        if not isinstance(value, dict) or 'kind' not in value or value.keys() - {'kind', 'amount', 'blend', 'params'}:
            raise ValueError('each stage needs a kind and can include amount, blend, and params')
        return cls(**value)


def value_noise(width, height, columns, rows, rng):
    lattice = [[rng.random() for _ in range(columns)] for _ in range(rows)]

    def axis(size, cells):
        for texel in range(size):
            pos = (texel + .5) * cells / size
            slot = int(pos)
            t = pos - slot
            yield slot, (slot + 1) % cells, t * t * (3 - 2 * t)

    xs = list(axis(width, columns))
    for top, bottom, v in axis(height, rows):
        row = [a + (b - a) * v for a, b in zip(lattice[top], lattice[bottom])]
        yield from (row[left] + (row[right] - row[left]) * u for left, right, u in xs)


def fractal_noise(width, height, columns, rows, octaves, gain, rng):
    values = [0.] * (width * height)
    total = 0.
    weight = 1.
    for octave in range(octaves):
        # Frequencies above the texel grid cannot add resolved detail.
        x_cells = min(width, columns << octave)
        y_cells = min(height, rows << octave)
        layer = value_noise(width, height, x_cells, y_cells, rng)
        values = [value + weight * sample for value, sample in zip(values, layer)]
        total += weight
        weight *= gain / 100
    return [value / total for value in values]


def cellular_noise(width, height, columns, rows, jitter, rng):
    spread = jitter / 100
    points = [[(.5 + (rng.random() - .5) * spread, .5 + (rng.random() - .5) * spread)
               for _ in range(columns)] for _ in range(rows)]
    xs = [(x + .5) * columns / width for x in range(width)]
    for y in range(height):
        v = (y + .5) * rows / height
        row = int(v)
        for u in xs:
            col = int(u)
            distance = 1.
            for yy in range(row - 1, row + 2):
                for xx in range(col - 1, col + 2):
                    px, py = points[yy % rows][xx % columns]
                    distance = min(distance, (xx + px - u) ** 2 + (yy + py - v) ** 2)
            yield math.sqrt(distance)


def source_field(stage, width, height, seed):
    kind, p = stage.kind, stage.params
    rng = random.Random(f'{seed}:{p.get("seed_offset", 0)}')
    if kind == 'solid':
        return [p['value'] / 100] * (width * height)
    if kind == 'white':
        return [rng.random() for _ in range(width * height)]
    if kind == 'value':
        return value_noise(width, height, p['columns'], p['rows'], rng)
    if kind == 'fractal':
        return fractal_noise(width, height, p['columns'], p['rows'], p['octaves'], p['gain'], rng)
    if kind == 'cellular':
        return cellular_noise(width, height, p['columns'], p['rows'], p['jitter'], rng)
    if kind == 'bands':
        across, down, phase = p['across'], p['down'], p['phase'] / 100
        return (float(((x + .5) * across / width + (y + .5) * down / height + phase) % 1 < p['width'] / 100)
                for y in range(height) for x in range(width))
    gap = p['gap'] / 200
    stagger = p['stagger'] / 100
    cells = [(x + .5) * p['columns'] / width for x in range(width)]
    values = []
    for y in range(height):
        row, v = divmod((y + .5) * p['rows'] / height, 1)
        shift = int(row) % 2 * stagger
        values.extend(float(gap <= (u + shift) % 1 < 1 - gap and gap <= v < 1 - gap) for u in cells)
    return values


def blur(values, width, height, radius):
    def smooth(samples):
        count = 2 * radius + 1
        size = len(samples)
        total = sum(samples[i % size] for i in range(-radius, radius + 1))
        for i in range(size):
            yield total / count
            total += samples[(i + radius + 1) % size] - samples[(i - radius) % size]

    rows = [tuple(smooth(values[i:i + width])) for i in range(0, width * height, width)]
    columns = [tuple(smooth(column)) for column in zip(*rows)]
    return [value for row in zip(*columns) for value in row]


def filter_field(stage, values, width, height):
    kind, p = stage.kind, stage.params
    if kind == 'blur':
        return blur(values, width, height, p['radius'])
    if kind == 'sharpen':
        return (2 * value - average
                for value, average in zip(values, blur(values, width, height, p['radius'])))
    if kind == 'invert':
        return (1 - value for value in values)
    if kind == 'threshold':
        cutoff = p['cutoff'] / 100
        return (float(value >= cutoff) for value in values)
    angle, distance = math.radians(p['angle']), p['distance']
    dx, dy = round(math.cos(angle) * distance), round(math.sin(angle) * distance)
    return (.5 + values[(y + dy) % height * width + (x + dx) % width]
            - values[(y - dy) % height * width + (x - dx) % width]
            for y in range(height) for x in range(width))


def render(stages, width, height, seed):
    values = [.5] * (width * height)
    for stage in stages:
        amount = stage.amount / 100
        if not amount:
            continue
        if stage.kind in SOURCES:
            changed = source_field(stage, width, height, seed)
            if stage.blend == 'add':
                changed = (value + sample - .5 for value, sample in zip(values, changed))
            elif stage.blend == 'multiply':
                changed = (value * sample for value, sample in zip(values, changed))
            elif stage.blend == 'min':
                changed = map(min, values, changed)
            elif stage.blend == 'max':
                changed = map(max, values, changed)
        else:
            changed = filter_field(stage, values, width, height)
        values = [max(0., min(1., original + (sample - original) * amount))
                  for original, sample in zip(values, changed)]
    return values
