"""Stock v6 records, global storage, and relocation of function-local operands."""
from dataclasses import dataclass
from pathlib import Path
import re
import struct

from .reader import CompileError

ROOT = Path(__file__).resolve().parents[1]
OP_MUL, OP_DIV, OP_ADD, OP_SUB = 1, 5, 6, 8
OP_EQ, OP_LE, OP_GE, OP_LT, OP_GT = 10, 20, 21, 22, 23
OP_EQ_STR, OP_EQ_ENT = 12, 13
OP_LOAD_F, OP_LOAD_V, OP_ADDRESS, OP_STOREP_F, OP_STOREP_V = 24, 25, 30, 37, 38
OP_LOAD_S, OP_LOAD_ENT, OP_LOAD_FNC = 26, 27, 29
OP_STOREP_S, OP_STOREP_ENT, OP_STOREP_FNC = 39, 40, 42
OP_STORE, OP_STORE_V, OP_RETURN, OP_NOT = 31, 32, 43, 44
OP_NOT_ENT = 47
OP_IF, OP_IFNOT, OP_CALL0, OP_GOTO, OP_AND = 49, 50, 51, 61, 62
OP_BITAND, OP_BITOR = 64, 65
TAGS = {'number': 0, 'boolean': 1, 'pair': 2, 'entity': 3, 'string': 4,
        'null': 5, 'symbol': 6}


@dataclass(frozen=True)
class Local:
    offset: int


def advance(slot, words):
    return Local(slot.offset + words) if isinstance(slot, Local) else slot + words


class Program:
    def __init__(self, location):
        self.location = location
        self.strings = bytearray(b'\0')
        self.string_offsets = {'': 0}
        self.globals = []
        self.globaldefs = [(0, 0, 0)]
        self.fielddefs = [(0, 0, 0)]
        self.statements = [(0, 0, 0, 0)]
        self.functions = [(0,) * 15]
        self.names = {}
        self.kinds = {}
        self.field_kinds = {}
        self.constants = {}
        self.entityfields = self.load_abi()
        self.error_function = self.builtin('__qslisp_error', 10, 1)

    def builtin(self, name, number, arity):
        if name not in self.names:
            index = self.function(name, '', arity)
            self.functions[index] = (-number, 0, 0, 0, self.string(name), 0, arity, *([0] * 8))
            self.define(name, 6, [index])
        return self.names[name]

    def string(self, text):
        if '\0' in text:
            raise CompileError(self.location, 'strings cannot contain a NUL byte')
        if text not in self.string_offsets:
            self.string_offsets[text] = len(self.strings)
            self.strings.extend(text.encode('utf-8') + b'\0')
        return self.string_offsets[text]

    def allocate(self, words):
        start = len(self.globals)
        if start + words > 32768:
            raise CompileError(self.location, 'stock global storage limit exceeded (32,768 slots)')
        self.globals.extend([0] * words)
        return start

    def define(self, name, kind, words):
        offset = self.allocate(len(words))
        self.globals[offset:offset + len(words)] = words
        self.globaldefs.append((kind, offset, self.string(name)))
        self.names[name] = offset
        self.kinds[name] = kind
        return offset

    def load_abi(self):
        header = ROOT / 'third_party/quake/WinQuake/progdefs.q1'
        if not header.is_file():
            raise CompileError(self.location, 'missing stock ABI; run ./tools/quakec/setup.sh first')
        layouts = re.findall(r'typedef\s+struct\s*\{(.*?)\}\s*(\w+);', header.read_text(), re.S)
        if [name for _, name in layouts] != ['globalvars_t', 'entvars_t']:
            raise CompileError(self.location, 'unexpected stock ABI header')
        kinds = {'int': 4, 'float': 2, 'vec3_t': 3, 'string_t': 1, 'func_t': 6}
        entityfields = 0
        for body, layout in layouts:
            offset = 0
            for ctype, name, count in re.findall(r'\b(int|float|vec3_t|string_t|func_t)\s+(\w+)(?:\[(\d+)\])?\s*;', body):
                width = (3 if ctype == 'vec3_t' else 1) * int(count or 1)
                if layout == 'globalvars_t':
                    self.allocate(width)
                if name != 'pad':
                    entries = [(name, kinds[ctype], offset)]
                    if ctype == 'vec3_t':
                        entries.extend((name + '_' + axis, 2, offset + i) for i, axis in enumerate('xyz'))
                    for label, kind, field_offset in entries:
                        if layout == 'globalvars_t':
                            self.globaldefs.append((kind, field_offset, self.string(label)))
                            self.names[label] = field_offset
                            self.kinds[label] = kind
                        else:
                            self.fielddefs.append((kind, field_offset, self.string(label)))
                            self.field_kinds[label] = kind
                            self.define(label, 5, [field_offset])
                offset += width
            if layout == 'entvars_t':
                entityfields = offset
        return entityfields

    def constant(self, number, boolean=False, location=None):
        try:
            raw = struct.pack('<f', number)
        except (OverflowError, struct.error):
            raise CompileError(location or self.location, 'numeric literal is outside the finite float32 range') from None
        key = (raw, boolean)
        if key not in self.constants:
            payload = struct.unpack('<I', raw)[0]
            tag = struct.unpack('<I', struct.pack('<f', float(boolean)))[0]
            self.constants[key] = self.define(f'__qslisp_const_{len(self.constants)}', 3, [payload, tag, 0])
        return self.constants[key]

    def message(self, text):
        # Stock PF_error concatenates into a 256-byte buffer. Keep our single
        # diagnostic argument within that limit even with a very long path.
        encoded = text.encode('utf-8')
        if len(encoded) > 240:
            text = '...' + encoded[-240:].decode('utf-8', errors='ignore')
        return self.define(f'__qslisp_message_{len(self.globaldefs)}', 1, [self.string(text)])

    def literal_string(self, text):
        return self.define(f'__qslisp_string_{len(self.globaldefs)}', 1, [self.string(text)])

    def tagged_literal(self, name, payload, tag):
        if name not in self.names:
            raw_tag = struct.unpack('<I', struct.pack('<f', TAGS[tag]))[0]
            return self.define(name, 3, [payload, raw_tag, 0])
        return self.names[name]

    def define_field(self, name, kind, location):
        if self.entityfields == 32768:
            raise CompileError(location, 'stock entity field storage limit exceeded')
        self.fielddefs.append((kind, self.entityfields, self.string(name)))
        self.field_kinds[name] = kind
        self.define(name, 5, [self.entityfields])
        self.entityfields += 1

    def function(self, name, filename, arity):
        index = len(self.functions)
        self.functions.append((0, 0, 0, 0, self.string(name), self.string(filename), arity, *([0] * 8)))
        return index

    def encode(self):
        sections = (
            b''.join(struct.pack('<Hhhh', *s) for s in self.statements),
            b''.join(struct.pack('<HHi', *d) for d in self.globaldefs),
            b''.join(struct.pack('<HHi', *d) for d in self.fielddefs),
            b''.join(struct.pack('<7i8B', *f) for f in self.functions),
            bytes(self.strings),
            b''.join(struct.pack('<I', word) for word in self.globals),
        )
        counts = (len(self.statements), len(self.globaldefs), len(self.fielddefs),
                  len(self.functions), len(self.strings), len(self.globals))
        data = bytearray(60)
        header = [6, 5927]
        for section, count in zip(sections, counts):
            data.extend(b'\0' * (-len(data) % 4))
            header.extend((len(data), count))
            data.extend(section)
        struct.pack_into('<15i', data, 0, *header, self.entityfields)
        return bytes(data)


class Frame:
    """Small instruction IR: locals remain relative until the frame is placed."""
    def __init__(self, program, index, location, arity, parameter_width):
        self.program, self.index, self.location = program, index, location
        self.arity = arity
        self.parameter_sizes = ((parameter_width,) * arity if isinstance(parameter_width, int)
                                else tuple(parameter_width))
        if not 0 <= arity <= 8 or len(self.parameter_sizes) != arity or any(w not in (1, 2, 3) for w in self.parameter_sizes):
            raise CompileError(location, 'invalid VM parameter layout')
        self.words = sum(self.parameter_sizes)
        self.code = []

    def allocate(self, words=3):
        slot = Local(self.words)
        self.words += words
        if self.words > 2048:
            raise CompileError(self.location, 'function exceeds stock saved-locals limit (2,048 slots)')
        return slot

    def emit(self, opcode, a=0, b=0, c=0):
        self.code.append((opcode, a, b, c))
        return len(self.code) - 1

    def patch(self, instruction, operand, target):
        statement = list(self.code[instruction])
        statement[operand] = target - instruction
        self.code[instruction] = tuple(statement)

    def finish(self):
        start = self.program.allocate(self.words)
        first = len(self.program.statements)
        for op, *args in self.code:
            resolved = [start + a.offset if isinstance(a, Local) else a for a in args]
            if any(a < -32768 or a > 32767 for a in resolved):
                raise CompileError(self.location, 'operand or branch exceeds stock signed 16-bit range')
            self.program.statements.append((op, *resolved))
        old = self.program.functions[self.index]
        sizes = list(self.parameter_sizes) + [0] * (8 - self.arity)
        self.program.functions[self.index] = (first, start, self.words, 0, old[4], old[5], self.arity, *sizes)


def emit_shallow_equality(frame, left, right, result, *, compare_strings):
    program = frame.program
    tag, right_tag = advance(left, 1), advance(right, 1)
    check = frame.allocate(1)
    frame.emit(OP_STORE, program.constant(0), result)
    frame.emit(OP_EQ, tag, right_tag, check)
    different = frame.emit(OP_IFNOT, check)

    frame.emit(OP_LE, tag, program.constant(TAGS['boolean']), check)
    numeric = frame.emit(OP_IF, check)
    if compare_strings:
        frame.emit(OP_EQ, tag, program.constant(TAGS['string']), check)
        string = frame.emit(OP_IF, check)
    frame.emit(OP_EQ_ENT, left, right, result)  # Identity of raw references or handles.
    raw_done = frame.emit(OP_GOTO)
    frame.patch(numeric, 2, len(frame.code))
    frame.emit(OP_EQ, left, right, result)
    if compare_strings:
        numeric_done = frame.emit(OP_GOTO)
        frame.patch(string, 2, len(frame.code))
        frame.emit(OP_EQ_STR, left, right, result)
        frame.patch(numeric_done, 1, len(frame.code))
    frame.patch(raw_done, 1, len(frame.code))
    frame.patch(different, 2, len(frame.code))
