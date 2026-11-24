"""A fixed pair arena with bump allocation in stock VM bytecode.

Only compiler-generated code calls this runtime. No heap value outlives the
engine entry that allocated it: there are no mutable globals, and entity fields
hold only numbers, entities, and strings. Native entry wrappers therefore save
the allocation pointer on entry and restore it on exit, and nothing is traced.
Accessor decision trees replace the general indexed global loads/stores missing
from stock Quake.
"""
from .bytecode import (Frame, Local, TAGS, advance, OP_ADD, OP_SUB, OP_EQ, OP_LT,
                       OP_STORE, OP_STORE_V, OP_RETURN, OP_IF, OP_IFNOT,
                       OP_CALL0, OP_GOTO, OP_OR, emit_shallow_equality)
from .reader import CompileError


class PairHeap:
    def __init__(self, program, capacity, *, deep_equal=False, append=False, boxed_kinds=()):
        self.program, self.capacity = program, capacity
        self.boxed_kinds = ('pair', *boxed_kinds)
        cell_words = 9 if deep_equal else 6
        if cell_words * capacity + len(program.globals) > 32768:
            raise CompileError(program.location, 'pair pool exceeds stock global storage (32,768 slots)')
        self.zero, self.one, self.two = (program.constant(i) for i in range(3))
        self.minus_one = program.constant(-1)
        self.car = [program.define(f'__qslisp_heap_car_{i}', 3, [0, 0, 0]) for i in range(capacity)]
        self.cdr = [program.define(f'__qslisp_heap_cdr_{i}', 3, [0, 0, 0]) for i in range(capacity)]
        self.equal_stack = ([program.define(f'__qslisp_equal_stack_{i}', 3, [0, 0, 0])
                             for i in range(capacity)] if deep_equal else [])
        # Index of the next unused cell. Everything below it is allocated.
        self.next = program.define('__qslisp_heap_next', 2, [0])
        self.functions = {}
        functions = (
            ('car_get', (1,)), ('car_set', (1, 3)),
            ('cdr_get', (1,)), ('cdr_set', (1, 3)),
            ('cons', (3, 3, 1)), ('car', (3, 1)), ('cdr', (3, 1)),
        )
        if deep_equal:
            functions += (('equal_get', (1,)), ('equal_set', (1, 3)), ('equal', (3, 3)))
        if append:
            functions += (('append', (3, 3, 1, 1)),)
        for name, widths in functions:
            label = '__qslisp_rt_' + name
            index = program.function(label, '<pair-runtime>', len(widths))
            reference = program.define(label, 6, [index])
            self.functions[name] = (index, reference, widths)
        self.generated_statements = 0

    def frame(self, name):
        index, _, widths = self.functions[name]
        return Frame(self.program, index, self.program.location, len(widths), widths)

    def call(self, frame, name, arguments):
        index, reference, widths = self.functions[name]
        frame.calls.add(index)
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

    def compile(self):
        before = len(self.program.statements)
        for name, entries in (('car', self.car), ('cdr', self.cdr)):
            self.compile_accessor(name + '_get', entries, False)
            self.compile_accessor(name + '_set', entries, True)
        self.compile_cons()
        self.compile_read('car')
        self.compile_read('cdr')
        if 'append' in self.functions:
            self.compile_append()
        if self.equal_stack:
            self.compile_accessor('equal_get', self.equal_stack, False)
            self.compile_accessor('equal_set', self.equal_stack, True)
            self.compile_equal()
        self.generated_statements = len(self.program.statements) - before

    def compile_append(self):
        frame = self.frame('append')
        source, suffix, bad_list, no_space = Local(0), Local(3), Local(6), Local(7)
        empty = self.program.tagged_literal('__qslisp_null', 0, 'null')
        head = frame.allocate()
        last = frame.allocate(1)
        frame.emit(OP_STORE, self.minus_one, last)

        loop = len(frame.code)
        done = frame.emit(OP_IF, self.compare(frame, OP_EQ, advance(source, 1), advance(empty, 1)))
        item = self.call(frame, 'car', [source, bad_list])
        next_source = self.call(frame, 'cdr_get', [source])
        cell = self.call(frame, 'cons', [item, empty, no_space])
        first = frame.emit(OP_IF, self.compare(frame, OP_LT, last, self.zero))
        self.call(frame, 'cdr_set', [last, cell])
        linked = frame.emit(OP_GOTO)
        frame.patch(first, 2, len(frame.code))
        frame.emit(OP_STORE_V, cell, head)
        frame.patch(linked, 1, len(frame.code))
        frame.emit(OP_STORE, cell, last)
        frame.emit(OP_STORE_V, next_source, source)
        self.go(frame, loop)

        frame.patch(done, 2, len(frame.code))
        have_copy = frame.emit(OP_IFNOT, self.compare(frame, OP_LT, last, self.zero))
        frame.emit(OP_RETURN, suffix)
        frame.patch(have_copy, 2, len(frame.code))
        self.call(frame, 'cdr_set', [last, suffix])
        frame.emit(OP_RETURN, head)
        frame.finish()

    def compile_equal(self):
        frame = self.frame('equal')
        left, right = Local(0), Local(3)
        depth = frame.allocate(1)
        pending = frame.allocate()
        same = frame.allocate(1)
        frame.emit(OP_STORE, self.zero, depth)

        loop = len(frame.code)
        emit_shallow_equality(frame, left, right, same, compare_strings=True)
        matched = frame.emit(OP_IF, same)
        left_kind, right_kind = advance(left, 1), advance(right, 1)
        same_kind = self.compare(frame, OP_EQ, left_kind, right_kind)
        mismatch_kind = frame.emit(OP_IFNOT, same_kind)
        structural_kinds = tuple(kind for kind in self.boxed_kinds if kind != 'closure')
        aggregate = self.has_heap_tag(frame, left_kind, structural_kinds)
        mismatch_atom = frame.emit(OP_IFNOT, aggregate)
        # The pairs are immutable. Store both handles to revisit their cdrs
        # after the car comparison. Pending depth cannot exceed the pool size.
        frame.emit(OP_STORE, left, pending)
        frame.emit(OP_STORE, right, advance(pending, 1))
        frame.emit(OP_STORE, self.zero, advance(pending, 2))
        self.call(frame, 'equal_set', [depth, pending])
        frame.emit(OP_ADD, depth, self.one, depth)
        left_car = self.call(frame, 'car_get', [left])
        right_car = self.call(frame, 'car_get', [right])
        frame.emit(OP_STORE_V, left_car, left)
        frame.emit(OP_STORE_V, right_car, right)
        self.go(frame, loop)

        frame.patch(matched, 2, len(frame.code))
        complete = self.compare(frame, OP_EQ, depth, self.zero)
        matched_all = frame.emit(OP_IF, complete)
        frame.emit(OP_SUB, depth, self.one, depth)
        handles = self.call(frame, 'equal_get', [depth])
        left_cdr = self.call(frame, 'cdr_get', [handles])
        right_cdr = self.call(frame, 'cdr_get', [advance(handles, 1)])
        frame.emit(OP_STORE_V, left_cdr, left)
        frame.emit(OP_STORE_V, right_cdr, right)
        self.go(frame, loop)
        frame.patch(matched_all, 2, len(frame.code))
        frame.emit(OP_RETURN, self.program.constant(1, boolean=True))
        for branch in (mismatch_kind, mismatch_atom):
            frame.patch(branch, 2, len(frame.code))
        frame.emit(OP_RETURN, self.program.constant(0, boolean=True))
        frame.finish()

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

    def has_heap_tag(self, frame, tag, kinds):
        matched = self.compare(frame, OP_EQ, tag, self.program.constant(TAGS[kinds[0]]))
        for kind in kinds[1:]:
            other = self.compare(frame, OP_EQ, tag, self.program.constant(TAGS[kind]))
            frame.emit(OP_OR, matched, other, matched)
        return matched

    def compile_cons(self):
        frame = self.frame('cons')
        room = self.compare(frame, OP_LT, self.next, self.program.constant(self.capacity))
        self.guard(frame, room, Local(6))  # Source-location diagnostic from caller.
        self.call(frame, 'car_set', [self.next, Local(0)])
        self.call(frame, 'cdr_set', [self.next, Local(3)])
        result = frame.allocate()
        frame.emit(OP_STORE, self.next, result)
        frame.emit(OP_STORE, self.two, advance(result, 1))
        frame.emit(OP_STORE, self.zero, advance(result, 2))
        frame.emit(OP_ADD, self.next, self.one, self.next)
        frame.emit(OP_RETURN, result)
        frame.finish()

    def compile_read(self, name):
        # The accessor tree rejects any index that is not a whole cell number.
        frame = self.frame(name)
        pair = self.compare(frame, OP_EQ, Local(1), self.two)
        self.guard(frame, pair, Local(3))
        value = self.call(frame, name + '_get', [Local(0)])
        frame.emit(OP_RETURN, value)
        frame.finish()
