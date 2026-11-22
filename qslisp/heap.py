"""A nonmoving pair heap, shadow roots, and mark/sweep in stock VM bytecode.

Only compiler-generated code calls this runtime. Collection happens exclusively
in cons; its callers have already pinned their live values. Accessor decision
trees replace the general indexed global loads/stores missing from stock Quake.
"""
import struct

from .bytecode import (Frame, Local, advance, OP_ADD, OP_SUB, OP_EQ, OP_LT, OP_GE,
                       OP_GT, OP_STORE, OP_STORE_V, OP_RETURN, OP_IF, OP_IFNOT,
                       OP_CALL0, OP_GOTO)
from .reader import CompileError


def bits(number):
    return struct.unpack('<I', struct.pack('<f', number))[0]


class PairHeap:
    def __init__(self, program, capacity, root_capacity):
        self.program, self.capacity, self.root_capacity = program, capacity, root_capacity
        if 9 * capacity + 3 * root_capacity + len(program.globals) > 32768:
            raise CompileError(program.location, 'pair/root pools exceed stock global storage (32,768 slots)')
        self.zero, self.one, self.two = (program.constant(i) for i in range(3))
        self.minus_one = program.constant(-1)
        self.car, self.cdr, self.meta = [], [], []
        for i in range(capacity):
            self.car.append(program.define(f'__qslisp_heap_car_{i}', 3, [0, 0, 0]))
            self.cdr.append(program.define(f'__qslisp_heap_cdr_{i}', 3, [0, 0, 0]))
            # [state, next, zero]: state 0=free, 1=allocated, 2=marked.
            next_free = i + 1 if i + 1 < capacity else -1
            self.meta.append(program.define(f'__qslisp_heap_meta_{i}', 3, [0, bits(next_free), 0]))
        self.roots = [program.define(f'__qslisp_root_{i}', 3, [0, 0, 0])
                      for i in range(root_capacity)]
        self.free_head = program.define('__qslisp_heap_free_head', 2, [0])
        self.work_head = program.define('__qslisp_heap_work_head', 2, [bits(-1)])
        self.root_sp = program.define('__qslisp_root_sp', 2, [0])
        self.collections = program.define('__qslisp_heap_collections', 2, [0])
        self.functions = {}
        for name, widths in (
            ('car_get', (1,)), ('car_set', (1, 3)),
            ('cdr_get', (1,)), ('cdr_set', (1, 3)),
            ('meta_get', (1,)), ('meta_set', (1, 3)),
            ('root_get', (1,)), ('root_set', (1, 3)),
            ('root_push', (3,)), ('mark', (3,)), ('collect', ()),
            ('cons', (3, 3, 1)), ('car', (3, 1)), ('cdr', (3, 1)),
        ):
            label = '__qslisp_rt_' + name
            index = program.function(label, '<pair-runtime>', len(widths))
            reference = program.define(label, 6, [index])
            self.functions[name] = (index, reference, widths)
        self.generated_statements = 0

    def frame(self, name):
        index, _, widths = self.functions[name]
        return Frame(self.program, index, self.program.location, len(widths), widths)

    def call(self, frame, name, arguments):
        _, reference, widths = self.functions[name]
        for i, (argument, width) in enumerate(zip(arguments, widths)):
            frame.emit(OP_STORE_V if width == 3 else OP_STORE, argument, 4 + i * 3)
        frame.emit(OP_CALL0 + len(widths), reference)
        result = frame.allocate()
        frame.emit(OP_STORE_V, 1, result)
        return result

    def error(self, frame, message):
        frame.emit(OP_STORE, message, 4)
        frame.emit(OP_CALL0 + 1, self.program.error_function)

    def guard(self, frame, predicate, message):
        skip = frame.emit(OP_IF, predicate)
        self.error(frame, message)
        frame.patch(skip, 2, len(frame.code))

    def compare(self, frame, opcode, a, b):
        predicate = frame.allocate(1)
        frame.emit(opcode, a, b, predicate)
        return predicate

    def go(self, frame, target):
        instruction = frame.emit(OP_GOTO)
        frame.patch(instruction, 1, target)

    def pin(self, frame, values):
        # Values are snapshots, not addresses into the VM's hidden saved-locals
        # stack. RootPush skips numeric/boolean values dynamically. Pop restores
        # a saved pointer, so recursive invocations and duplicates are safe.
        unique = {}
        for value in values:
            if value.kind in ('unknown', 'pair'):
                unique.setdefault(value.slot, value)
        if not unique:
            return None
        base = frame.allocate(1)
        frame.emit(OP_STORE, self.root_sp, base)
        for value in unique.values():
            self.call(frame, 'root_push', [value.slot])
        return base

    def unpin(self, frame, base):
        if base is not None:
            frame.emit(OP_STORE, base, self.root_sp)

    def compile(self):
        before = len(self.program.statements)
        for name, entries in (('car', self.car), ('cdr', self.cdr),
                              ('meta', self.meta), ('root', self.roots)):
            self.compile_accessor(name + '_get', entries, False)
            self.compile_accessor(name + '_set', entries, True)
        self.compile_root_push()
        self.compile_mark()
        self.compile_collect()
        self.compile_cons()
        self.compile_read('car')
        self.compile_read('cdr')
        self.generated_statements = len(self.program.statements) - before

    def compile_accessor(self, name, entries, write):
        frame = self.frame(name)
        predicate = frame.allocate(1)
        invalid = []

        def tree(lo, hi):
            if hi - lo == 1:
                # Equality at the leaf rejects fractions, NaNs, negative and
                # out-of-range indices without a linear scan or unsafe access.
                frame.emit(OP_EQ, Local(0), self.program.constant(lo), predicate)
                invalid.append(frame.emit(OP_IFNOT, predicate))
                if write:
                    frame.emit(OP_STORE_V, Local(1), entries[lo])
                frame.emit(OP_RETURN, self.zero if write else entries[lo])
                return
            mid = (lo + hi) // 2
            frame.emit(OP_LT, Local(0), self.program.constant(mid), predicate)
            left = frame.emit(OP_IF, predicate)
            tree(mid, hi)
            frame.patch(left, 2, len(frame.code))
            tree(lo, mid)

        tree(0, len(entries))
        for branch in invalid:
            frame.patch(branch, 2, len(frame.code))
        message = self.program.message(f'qslisp runtime: invalid {name} index\n')
        self.error(frame, message)
        frame.emit(OP_RETURN, self.zero)
        frame.finish()

    def compile_root_push(self):
        frame = self.frame('root_push')
        pair = self.compare(frame, OP_EQ, Local(1), self.two)
        body = frame.emit(OP_IF, pair)
        frame.emit(OP_RETURN, self.zero)
        frame.patch(body, 2, len(frame.code))
        room = self.compare(frame, OP_LT, self.root_sp, self.program.constant(self.root_capacity))
        message = self.program.message(f'qslisp: shadow root stack exhausted ({self.root_capacity} values)\n')
        self.guard(frame, room, message)
        self.call(frame, 'root_set', [self.root_sp, Local(0)])
        frame.emit(OP_ADD, self.root_sp, self.one, self.root_sp)
        frame.emit(OP_RETURN, self.zero)
        frame.finish()

    def compile_mark(self):
        frame = self.frame('mark')
        pair = self.compare(frame, OP_EQ, Local(1), self.two)
        body = frame.emit(OP_IF, pair)
        frame.emit(OP_RETURN, self.zero)
        frame.patch(body, 2, len(frame.code))
        meta = self.call(frame, 'meta_get', [Local(0)])
        allocated = self.compare(frame, OP_GT, meta, self.zero)
        self.guard(frame, allocated, self.program.message('qslisp: invalid pair reference during collection\n'))
        white = self.compare(frame, OP_EQ, meta, self.one)
        unmarked = frame.emit(OP_IF, white)
        frame.emit(OP_RETURN, self.zero)
        frame.patch(unmarked, 2, len(frame.code))
        frame.emit(OP_STORE, self.two, meta)
        frame.emit(OP_STORE, self.work_head, advance(meta, 1))
        self.call(frame, 'meta_set', [Local(0), meta])
        frame.emit(OP_STORE, Local(0), self.work_head)
        frame.emit(OP_RETURN, self.zero)
        frame.finish()

    def compile_collect(self):
        frame = self.frame('collect')
        cursor = frame.allocate(1)
        current = frame.allocate(1)
        frame.emit(OP_ADD, self.collections, self.one, self.collections)
        frame.emit(OP_STORE, self.minus_one, self.work_head)
        frame.emit(OP_STORE, self.zero, cursor)
        root_loop = len(frame.code)
        available = self.compare(frame, OP_LT, cursor, self.root_sp)
        roots_done = frame.emit(OP_IFNOT, available)
        root = self.call(frame, 'root_get', [cursor])
        self.call(frame, 'mark', [root])
        frame.emit(OP_ADD, cursor, self.one, cursor)
        self.go(frame, root_loop)
        frame.patch(roots_done, 2, len(frame.code))

        work_loop = len(frame.code)
        available = self.compare(frame, OP_GE, self.work_head, self.zero)
        work_done = frame.emit(OP_IFNOT, available)
        frame.emit(OP_STORE, self.work_head, current)
        meta = self.call(frame, 'meta_get', [current])
        frame.emit(OP_STORE, advance(meta, 1), self.work_head)
        car = self.call(frame, 'car_get', [current])
        self.call(frame, 'mark', [car])
        cdr = self.call(frame, 'cdr_get', [current])
        self.call(frame, 'mark', [cdr])
        self.go(frame, work_loop)
        frame.patch(work_done, 2, len(frame.code))

        frame.emit(OP_STORE, self.minus_one, self.free_head)
        frame.emit(OP_STORE, self.program.constant(self.capacity - 1), cursor)
        sweep_loop = len(frame.code)
        available = self.compare(frame, OP_GE, cursor, self.zero)
        sweep_done = frame.emit(OP_IFNOT, available)
        meta = self.call(frame, 'meta_get', [cursor])
        marked = self.compare(frame, OP_EQ, meta, self.two)
        live = frame.emit(OP_IF, marked)
        frame.emit(OP_STORE, self.zero, meta)
        frame.emit(OP_STORE, self.free_head, advance(meta, 1))
        self.call(frame, 'meta_set', [cursor, meta])
        self.call(frame, 'car_set', [cursor, self.zero])
        self.call(frame, 'cdr_set', [cursor, self.zero])
        frame.emit(OP_STORE, cursor, self.free_head)
        after_free = frame.emit(OP_GOTO)
        frame.patch(live, 2, len(frame.code))
        frame.emit(OP_STORE, self.one, meta)
        self.call(frame, 'meta_set', [cursor, meta])
        frame.patch(after_free, 1, len(frame.code))
        frame.emit(OP_SUB, cursor, self.one, cursor)
        self.go(frame, sweep_loop)
        frame.patch(sweep_done, 2, len(frame.code))
        frame.emit(OP_RETURN, self.zero)
        frame.finish()

    def compile_cons(self):
        frame = self.frame('cons')
        room = self.compare(frame, OP_GE, self.free_head, self.zero)
        skip_gc = frame.emit(OP_IF, room)
        self.call(frame, 'collect', [])
        frame.patch(skip_gc, 2, len(frame.code))
        room = self.compare(frame, OP_GE, self.free_head, self.zero)
        self.guard(frame, room, Local(6))  # Source-location diagnostic from caller.
        index = frame.allocate(1)
        frame.emit(OP_STORE, self.free_head, index)
        meta = self.call(frame, 'meta_get', [index])
        frame.emit(OP_STORE, advance(meta, 1), self.free_head)
        frame.emit(OP_STORE, self.one, meta)
        self.call(frame, 'meta_set', [index, meta])
        self.call(frame, 'car_set', [index, Local(0)])
        self.call(frame, 'cdr_set', [index, Local(3)])
        result = frame.allocate()
        frame.emit(OP_STORE, index, result)
        frame.emit(OP_STORE, self.two, advance(result, 1))
        frame.emit(OP_STORE, self.zero, advance(result, 2))
        frame.emit(OP_RETURN, result)
        frame.finish()

    def compile_read(self, name):
        frame = self.frame(name)
        pair = self.compare(frame, OP_EQ, Local(1), self.two)
        self.guard(frame, pair, Local(3))
        meta = self.call(frame, 'meta_get', [Local(0)])
        allocated = self.compare(frame, OP_GT, meta, self.zero)
        self.guard(frame, allocated, Local(3))
        value = self.call(frame, name + '_get', [Local(0)])
        frame.emit(OP_RETURN, value)
        frame.finish()
