#!/usr/bin/env python3
"""Static checks for the stock NetQuake v6 target; not a proof of runtime bounds."""
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
BUILTINS = set(range(1, 79)) - {5, 33, 39, 42, 50, 60, 61, 62, 63, 64, 65, 66, 71}


class StockError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise StockError(message)


def validate(data):
    require(len(data) >= 60, 'truncated program header')
    h = struct.unpack_from('<15i', data)
    require(h[:2] == (6, 5927), 'expected version 6 and stock ABI CRC 5927')
    require(92 <= h[13] <= 32768, 'global storage exceeds stock signed-address range or omits ABI')
    require(105 <= h[14] <= 32768, 'invalid stock entity-field storage')
    sections = []
    for index, stride in ((2, 8), (4, 8), (6, 8), (8, 36), (10, 1), (12, 4)):
        offset, count = h[index:index + 2]
        end = offset + count * stride
        require(offset >= 60 and count > 0 and end <= len(data), 'invalid section bounds')
        require(stride == 1 or offset % 4 == 0, 'unaligned program section')
        sections.append((offset, end))
    for left, right in zip(sorted(sections), sorted(sections)[1:]):
        require(left[1] <= right[0], 'overlapping program sections')
    strings = data[h[10]:h[10] + h[11]]
    require(strings[0] == 0, 'string zero must be empty')

    def name_at(offset):
        require(0 <= offset < len(strings), 'invalid string reference')
        end = strings.find(b'\0', offset)
        require(end >= 0, 'unterminated string')
        return strings[offset:end].decode('ascii', errors='replace')

    definitions = []
    for index, size in ((4, h[13]), (6, h[14])):
        names = {}
        for row in range(h[index + 1]):
            kind, offset, name = struct.unpack_from('<HHi', data, h[index] + row * 8)
            require(index != 6 or not kind & 0x8000, 'save-global flag on entity-field definition')
            kind &= 0x7fff
            require(kind <= 7, 'nonstock value type')
            require(offset + (3 if kind == 3 else 1) <= size, 'definition outside storage')
            names.setdefault(name_at(name), (kind, offset))
        definitions.append(names)

    # Verify the layout itself, not just a CRC value supplied by the compiler.
    canonical = ROOT / 'third_party/quake/WinQuake/progdefs.q1'
    require(canonical.is_file(), 'missing stock source; run tools/quakec/setup.sh')
    layouts = re.findall(r'typedef\s+struct\s*\{(.*?)\}\s*(\w+);', canonical.read_text(), re.S)
    require([n for _, n in layouts] == ['globalvars_t', 'entvars_t'], 'unexpected stock ABI header')
    kinds = {'int': 4, 'float': 2, 'vec3_t': 3, 'string_t': 1, 'func_t': 6}
    for (body, _), names in zip(layouts, definitions):
        offset = 0
        for ctype, name, count in re.findall(r'\b(int|float|vec3_t|string_t|func_t)\s+(\w+)(?:\[(\d+)\])?\s*;', body):
            if name != 'pad':
                require(names.get(name) == (kinds[ctype], offset), f'stock ABI mismatch for {name}')
            offset += (3 if ctype == 'vec3_t' else 1) * int(count or 1)

    for row in range(1, h[9]):
        f = struct.unpack_from('<7i8B', data, h[8] + row * 36)
        first, start, locals_, _, name, file, argc, *widths = f
        label = name_at(name)
        name_at(file)
        require(0 <= argc <= 8, f'{label}: more than eight parameters or invalid arity')
        if first < 0:
            require(-first in BUILTINS, f'{label}: nonstock/unimplemented builtin #{-first}')
            continue
        require(0 < first < h[3], f'{label}: invalid function entry')
        require(0 <= locals_ <= 2048, f'{label}: local frame exceeds stock saved-locals stack')
        require(0 <= start <= start + locals_ <= h[13], f'{label}: frame outside global storage')
        require(all(1 <= width <= 3 for width in widths[:argc]), f'{label}: invalid parameter width')
        require(sum(widths[:argc]) <= locals_, f'{label}: parameters outside local frame')

    def slot(index, width, row):
        require(0 <= index and index + width <= h[13], f'statement {row}: invalid signed global operand')

    for row in range(h[3]):
        op, a, b, c = struct.unpack_from('<Hhhh', data, h[2] + row * 8)
        require(op <= 65, f'statement {row}: nonstock opcode {op}')
        if op in (49, 50, 61):
            target = row + (a if op == 61 else b)
            require(0 <= target < h[3], f'statement {row}: branch outside program')
            if op != 61:
                slot(a, 1, row)
        elif 51 <= op <= 59:
            slot(a, 1, row)
        elif op in (0, 43):
            slot(a, 3, row)  # Even scalar returns copy three words in stock Quake.
        elif 31 <= op <= 42:
            width = 3 if op in (32, 38) else 1
            slot(a, width, row)
            slot(b, width if op <= 36 else 1, row)
        elif 44 <= op <= 48:
            slot(a, 3 if op == 45 else 1, row)
            slot(c, 1, row)
        elif op == 60:
            slot(a, 1, row)
            slot(b, 1, row)
        else:
            aw = 3 if op in (2, 4, 7, 9, 11, 16) else 1
            bw = 3 if op in (2, 3, 7, 9, 11, 16) else 1
            cw = 3 if op in (3, 4, 7, 9, 25) else 1
            slot(a, aw, row)
            slot(b, bw, row)
            slot(c, cw, row)
    return h


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(f'usage: {sys.argv[0]} PROGS.DAT')
    try:
        header = validate(Path(sys.argv[1]).read_bytes())
    except (StockError, OSError) as error:
        sys.exit(f'stock check failed: {error}')
    print(f'Stock static checks passed: {header[13]:,}/32,768 slots, '
          f'{header[3]:,} statements, {header[9]:,} functions.')
