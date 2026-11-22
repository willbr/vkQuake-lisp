"""Disassemble stock Quake v6 bytecode and assemble small VM fixtures."""
import argparse
from bisect import bisect_right
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import re
import shlex
import struct

from .bytecode import Frame, Local, Program, ROOT
from .reader import CompileError, Location


def validate(data):
    spec = spec_from_file_location('quake_stock_validator', ROOT / 'tools/quakec/check-stock.py')
    checker = module_from_spec(spec)
    spec.loader.exec_module(checker)
    return checker.validate(data)


def opcode_names():
    header = ROOT / 'third_party/quake/WinQuake/pr_comp.h'
    names = re.findall(r'\bOP_([A-Z][A-Z_0-9]*)\b', header.read_text())
    if len(names) != 66 or names[:1] != ['DONE']:
        raise ValueError('unexpected stock Quake opcode declarations')
    return names


def operands(opcode):
    if opcode == 61:
        return ('label',)
    if opcode in (49, 50):
        return 'slot', 'label'
    if opcode in (0, 43) or 51 <= opcode <= 59:
        return ('slot',)
    if 31 <= opcode <= 42 or opcode == 60:
        return 'slot', 'slot'
    if 44 <= opcode <= 48:
        return 'slot', None, 'slot'
    return 'slot', 'slot', 'slot'


def strings_at(data, header, offset):
    start = header[10] + offset
    end = data.index(b'\0', start, header[10] + header[11])
    return data[start:end].decode('utf-8', errors='replace')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def symbols(program, data):
    decoded = bytes(program.strings)

    def name(index):
        start = program.functions[index][4]
        return decoded[start:decoded.index(0, start)].decode('utf-8', errors='replace')

    return {
        'version': 1,
        'sha256': digest(data),
        'ranges': [
            {'start': start, 'end': end, 'function': name(fn),
             'file': location.filename, 'line': location.line, 'column': location.column}
            for start, end, fn, location in program.source_ranges
        ],
    }


def source_ranges(data, sidecar, size):
    if sidecar is None:
        return []
    if sidecar.get('version') != 1 or sidecar.get('sha256') != digest(data):
        raise ValueError('source symbols do not match this progs.dat')
    ranges = sidecar['ranges']
    end = 0
    for item in ranges:
        if not end <= item['start'] < item['end'] <= size:
            raise ValueError('invalid or overlapping source ranges')
        end = item['end']
    return ranges


def disassemble(data, sidecar=None, function=None):
    h = validate(data)
    names = opcode_names()
    functions = list(struct.iter_unpack('<7i8B', data[h[8]:h[8]+36*h[9]]))
    definitions = list(struct.iter_unpack('<HHi', data[h[4]:h[4]+8*h[5]]))
    statements = list(struct.iter_unpack('<Hhhh', data[h[2]:h[2]+8*h[3]]))
    source = source_ranges(data, sidecar, len(statements))
    source_starts = [entry['start'] for entry in source]
    global_names = {slot: strings_at(data, h, name) for kind, slot, name in definitions if name}
    labels = {i + slots[roles.index('label')] for i, (op, *slots) in enumerate(statements)
              if 'label' in (roles := operands(op))}
    entries = sorted((f[0], i, f) for i, f in enumerate(functions[1:], 1) if f[0] > 0)
    entries.append((len(statements), 0, None))
    lines = []
    if function is None:
        lines.append(f'progs v{h[0]}  {h[3]} statements  {h[13]} globals  {h[14]} entity fields')
        for f in functions[1:]:
            if f[0] < 0:
                lines.append(f'builtin {strings_at(data,h,f[4])} #{-f[0]} arity={f[6]}')
    for (start, _, f), (end, _, _) in zip(entries, entries[1:]):
        name = strings_at(data, h, f[4])
        if function is not None and name != function:
            continue
        lines.append(f'\n{name}  pc={start}  locals={f[2]}  arity={f[6]}')
        for pc in range(start, end):
            op, *slots = statements[pc]
            if pc in labels:
                lines.append(f'L{pc}:')
            parts = []
            for slot, role in zip(slots, operands(op)):
                if role == 'label':
                    parts.append(f'L{pc+slot}')
                elif role == 'slot':
                    if f[1] <= slot < f[1] + f[2]:
                        label = f'%{slot-f[1]}'
                    elif slot in global_names:
                        label = f'{global_names[slot]}[{slot}]'
                    else:
                        label = f'[{slot}]'
                    parts.append(label)
            trailing = ''
            index = bisect_right(source_starts, pc) - 1
            if index >= 0 and pc < source[index]['end']:
                loc = source[index]
                trailing = f"  ; {loc['file']}:{loc['line']}:{loc['column']}"
            lines.append(f" {pc:5}  {names[op]:<12} {' '.join(parts)}{trailing}")
    if function is not None and not lines:
        raise ValueError(f'bytecode function {function!r} was not found')
    return '\n'.join(lines).strip() + '\n'


def parse_assembly(text, filename):
    """Collect declarations before lowering operands, so references may be forward."""
    program = Program(Location(filename, 1, 1))
    functions = []
    current = None
    named = {}

    def add(name, slot, loc):
        if name in named:
            raise CompileError(loc, f'duplicate symbol {name!r}')
        named[name] = slot

    for line, raw in enumerate(text.splitlines(), 1):
        loc = Location(filename, line, 1)
        try:
            items = shlex.split(raw, comments=True)
            if not items:
                continue
            op, *args = items
            if current is None and op == '.float':
                name, value = args
                add(name, program.constant(float(value), location=loc), loc)
            elif current is None and op == '.builtin':
                name, number, arity = args
                add(name, program.builtin(name, int(number), int(arity)), loc)
            elif current is None and op == '.function':
                name, local_count, *parameter_sizes = args
                widths = tuple(map(int, parameter_sizes))
                locals_size = int(local_count)
                if not 0 <= locals_size <= 2048 or any(width not in (1, 2, 3) for width in widths):
                    raise CompileError(loc, 'invalid local count or parameter widths')
                index = program.function(name, filename, len(widths))
                slot = program.names.get(name)
                if slot is None:
                    slot = program.define(name, 6, [index])
                elif program.kinds[name] == 6:
                    program.globals[slot] = index
                else:
                    raise CompileError(loc, f'cannot replace stock global {name!r}')
                add(name, slot, loc)
                frame = Frame(program, index, loc, len(widths), widths)
                frame.allocate(locals_size)
                current = frame, []
            elif current is not None and op == '.end' and not args:
                functions.append(current)
                current = None
            elif current is not None:
                current[1].append((loc, op, args))
            else:
                raise CompileError(loc, 'expected .float, .builtin, or .function')
        except (ValueError, TypeError) as error:
            if isinstance(error, CompileError):
                raise
            raise CompileError(loc, str(error)) from None
    if current is not None:
        raise CompileError(current[0].location, 'missing .end')
    return program, functions, named


def assemble(text, filename='<assembly>'):
    program, functions, named = parse_assembly(text, filename)
    opcode_by_name = {name: i for i, name in enumerate(opcode_names())}
    for frame, code in functions:
        labels = {}
        pending = []
        for loc, name, args in code:
            if name.endswith(':') and not args:
                label = name[:-1]
                if label in labels:
                    raise CompileError(loc, f'duplicate label {label!r}')
                labels[label] = len(frame.code)
                continue
            if name not in opcode_by_name:
                raise CompileError(loc, f'unknown opcode {name!r}')
            op = opcode_by_name[name]
            roles = operands(op)
            if len(args) != sum(role is not None for role in roles):
                raise CompileError(loc, f'incorrect operand count for {name}')
            values = [0, 0, 0]
            arguments = iter(args)
            for i, role in enumerate(roles):
                if role is None:
                    continue
                value = next(arguments)
                if role == 'label':
                    pending.append((loc, len(frame.code), i + 1, value))
                elif value.startswith('%') and value[1:].isdigit() and int(value[1:]) < frame.words:
                    values[i] = Local(int(value[1:]))
                elif value in named:
                    values[i] = named[value]
                elif value in program.names:
                    values[i] = program.names[value]
                elif re.fullmatch(r'\[[0-9]+\]', value):
                    values[i] = int(value[1:-1])
                else:
                    raise CompileError(loc, f'unknown operand {value!r}')
            with frame.at(loc):
                frame.emit(op, *values)
        for loc, line, index, label in pending:
            if label not in labels or labels[label] >= len(frame.code):
                raise CompileError(loc, f'unknown or empty branch target {label!r}')
            frame.patch(line, index, labels[label])
        if not frame.code or frame.code[-1][0] not in (0, 43, 61):
            raise CompileError(frame.location, 'function must end in DONE, RETURN, or GOTO')
        frame.finish()
    output = program.encode()
    validate(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    listing = sub.add_parser('disassemble')
    listing.add_argument('program', type=Path)
    listing.add_argument('--symbols', type=Path)
    listing.add_argument('--function')
    fixture = sub.add_parser('assemble')
    fixture.add_argument('source', type=Path)
    fixture.add_argument('-o', '--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'assemble':
            args.output.write_bytes(assemble(args.source.read_text(), str(args.source)))
        else:
            sidecar = json.loads(args.symbols.read_text()) if args.symbols else None
            print(disassemble(args.program.read_bytes(), sidecar, args.function), end='')
    except (ValueError, IndexError, KeyError, TypeError, OverflowError, OSError, struct.error) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
