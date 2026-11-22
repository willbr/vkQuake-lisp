"""Lexical resolution and direct emission for a small, dynamically tagged core."""
from dataclasses import dataclass
from contextlib import contextmanager

from .bytecode import (Program, Frame, Local, TAGS, advance, OP_MUL, OP_DIV, OP_ADD, OP_SUB,
                       OP_EQ, OP_LE, OP_GE, OP_LT, OP_GT, OP_STORE, OP_STORE_V,
                       OP_RETURN, OP_NOT, OP_NOT_ENT, OP_IF, OP_IFNOT, OP_CALL0, OP_GOTO, OP_AND, OP_OR,
                       OP_LOAD_F, OP_LOAD_V, OP_ADDRESS, OP_STOREP_F, OP_STOREP_V,
                       OP_STOREP_S, OP_EQ_ENT, OP_EQ_STR, OP_BITAND, OP_BITOR,
                       OP_LOAD_S, OP_LOAD_ENT, OP_LOAD_FNC, OP_STOREP_ENT, OP_STOREP_FNC,
                       emit_shallow_equality)
from .reader import CompileError, Location, StringLiteral
from .heap import PairHeap
from .modules import load_forms
from .syntax import DERIVED_FORMS, DerivedForms

SYNTAX = DERIVED_FORMS | {'define', 'define-field', 'import', 'if', 'let', 'begin', 'lambda', 'quote', 'set!', 'letrec',
                          'define-syntax', 'syntax-rules', 'quasiquote'}
ARITHMETIC = {'+': OP_ADD, '-': OP_SUB, '*': OP_MUL, '/': OP_DIV}
COMPARISONS = {'=': OP_EQ, '<': OP_LT, '<=': OP_LE, '>': OP_GT, '>=': OP_GE}
BITWISE = {'quake:bit-and': OP_BITAND, 'quake:bit-or': OP_BITOR}
ENGINE_CALLS = {
    'quake:make-vectors': (1, ('vector',)),
    'quake:set-origin': (2, ('entity', 'vector')),
    'quake:set-model': (3, ('entity', 'precache-name')),
    'quake:set-size': (4, ('entity', 'vector', 'vector')),
    'quake:sound': (8, ('entity', 'number', 'sample', 'number', 'number')),
    'quake:error': (10, ('string',)),
    'quake:vector-yaw': (13, ('vector',)),
    'quake:remove': (15, ('entity',)),
    'quake:traceline': (16, ('vector', 'vector', 'number', 'entity')),
    'quake:find': (18, ('entity', 'string-field', 'string-value')),
    'quake:precache-sound': (19, ('sample',)),
    'quake:precache-model': (20, ('model',)),
    'quake:dprint': (25, ('string',)),
    'quake:walkmove': (32, ('number', 'number')),
    'quake:drop-to-floor': (34, ()),
    'quake:change-level': (70, ('level',)),
    'quake:centerprint': (73, ('entity', 'string')),
}
ENGINE_GLOBALS = {'quake:self': ('self', 'entity'), 'quake:other': ('other', 'entity'),
                  'quake:world': ('world', 'entity'),
                  'quake:time': ('time', 'number'), 'quake:forward-x': ('v_forward_x', 'number'),
                  'quake:forward-y': ('v_forward_y', 'number'), 'quake:forward-z': ('v_forward_z', 'number')}
ENTITY_RESULTS = {'quake:find': 1, 'quake:traceline': 'trace_ent'}
NUMERIC_RESULTS = {'quake:vector-yaw', 'quake:walkmove', 'quake:drop-to-floor'}
PRIMITIVES = (ARITHMETIC.keys() | COMPARISONS.keys() | BITWISE.keys() |
              ENGINE_CALLS.keys() | ENGINE_GLOBALS.keys()) | {
    'not', 'cons', 'car', 'cdr', 'pair?', 'list', 'list?', 'null?', 'symbol?', 'string?', 'eq?', 'equal?', 'procedure?',
    'quake:world?', 'quake:entity=?',
    'quake:field', 'quake:set-field!', 'quake:vector', 'quake:vector?', 'string=?',
    'quake:vector-x', 'quake:vector-y', 'quake:vector-z',
    'quake:set-callback!', 'quake:call-callback',
}
VALUE_PREDICATES = {'pair?': 'pair', 'null?': 'null', 'symbol?': 'symbol', 'string?': 'string',
                    'quake:vector?': 'vector', 'procedure?': 'procedure'}
VECTOR_COMPONENTS = {'quake:vector-x': 0, 'quake:vector-y': 1, 'quake:vector-z': 2}
FIELD_TYPES = {1: 'string', 2: 'numeric', 3: 'vector', 4: 'entity', 6: 'function'}
CUSTOM_FIELDS = {'number': 2, 'entity': 4, 'string': 1}
FIELD_READS = {1: ('string', OP_LOAD_S), 2: ('number', OP_LOAD_F), 4: ('entity', OP_LOAD_ENT)}
FIELD_WRITES = {1: OP_STOREP_S, 2: OP_STOREP_F, 3: OP_STOREP_V, 4: OP_STOREP_ENT}


def expression_names(node, *, mutations=False):
    form = node.value
    if isinstance(form, str) and not mutations:
        yield form
    if not isinstance(form, tuple) or not form or form[0].value == 'quote':
        return
    if mutations and form[0].value == 'set!' and len(form) == 3 and isinstance(form[1].value, str):
        yield form[1].value
    for child in form:
        yield from expression_names(child, mutations=mutations)


@dataclass(frozen=True)
class Value:
    slot: object
    kind: str = 'unknown'
    boxed: bool = False


@dataclass
class Function:
    name: str
    parameters: tuple
    body: tuple
    location: Location
    public: int
    private: int
    reference: int
    request: int


@dataclass(frozen=True)
class LambdaBody:
    index: int
    parameters: tuple
    captures: dict
    body: tuple
    location: Location


def symbol(node, purpose):
    if not isinstance(node.value, str):
        raise CompileError(node.location, f'expected an identifier for {purpose}')
    return node.value


def binding_name(node):
    name = symbol(node, 'binding')
    if name in SYNTAX:
        raise CompileError(node.location, f'{name} is reserved syntax in this dialect')
    return name


class Compiler:
    def __init__(self, forms, filename, *, heap_pairs=256, root_slots=256):
        location = forms[0].location if forms else Location(filename, 1, 1)
        if any(type(n) is not int or n < 1 for n in (heap_pairs, root_slots)):
            raise CompileError(location, 'heap-pairs and root-slots must be positive integers')
        self.program = Program(location)
        self.functions = {}
        self.constants = {}
        self.derived_forms = DerivedForms()
        self.uses_procedures = False
        self.lambdas = []
        self.zero = self.program.constant(0)
        self.one = self.program.constant(1)
        for form in forms:
            self.declare(form)
        if not self.functions:
            raise CompileError(location, 'expected at least one function definition')
        # A bytecode trampoline drains tail requests without retaining the
        # requesting function's frame. The mailbox is published only after all
        # arguments have been evaluated; nested ordinary calls may reuse it.
        self.mailbox = [self.program.define(f'__qslisp_argument_{i}', 3, [0, 0, 0])
                        for i in range(8)]
        self.dispatch = self.program.function('__qslisp_dispatch', filename, 1)
        self.dispatch_reference = self.program.define('__qslisp_dispatch', 6, [self.dispatch])
        bodies = [node for function in self.functions.values() for node in function.body]
        features = set().union(*(self.heap_features(node) for node in bodies))
        self.mutable_names = {name for node in bodies for name in expression_names(node, mutations=True)}
        self.closure_mailbox = (self.program.define('__qslisp_captured_values', 3, [0, 0, 0])
                                if 'closure' in features else None)
        kinds = tuple(kind for kind in ('vector', 'closure') if kind in features)
        self.heap = (PairHeap(self.program, heap_pairs, root_slots, deep_equal='equal' in features, boxed_kinds=kinds)
                     if 'pair' in features or kinds else None)
        self.pending = []

    def heap_features(self, node, *, native=False):
        if not isinstance(node.value, tuple) or not node.value:
            return {'vector'} if native else set()
        form = node.value
        name = form[0].value if isinstance(form[0].value, str) else None
        if name == 'quote':
            if len(form) == 2 and isinstance(form[1].value, tuple) and form[1].value:
                return {'pair'}
            return {'vector'} if native else set()
        if name in ('let', 'let*') and len(form) >= 3 and isinstance(form[1].value, tuple):
            initializers = [binding.value[1] for binding in form[1].value
                            if isinstance(binding.value, tuple) and len(binding.value) == 2]
            result = set().union(*(self.heap_features(n) for n in (*initializers, *form[2:])))
            return result | ({'vector'} if native else set())

        kinds = ENGINE_CALLS[name][1] if name in ENGINE_CALLS else ()
        if name in VECTOR_COMPONENTS:
            kinds = ('vector',)
        if name == 'quake:set-field!' and len(form) == 4 and self.vector_field(form[2]):
            kinds = ('entity', 'field', 'vector')
        result = set().union(*(self.heap_features(arg, native=i < len(kinds) and kinds[i] == 'vector')
                               for i, arg in enumerate(form[1:])))
        if name is None:
            result.update(self.heap_features(form[0]))
        raw_source = name == 'quake:vector' or (name == 'quake:field' and len(form) == 3 and self.vector_field(form[2]))
        if native != raw_source:
            result.add('vector')
        if name in ('cons', 'car', 'cdr') or (name == 'list' and len(form) > 1):
            result.add('pair')
        if name == 'set!':
            result.add('pair')
        if name in ('lambda', 'letrec') or (name == 'let' and len(form) > 1 and isinstance(form[1].value, str)):
            result.add('closure')
        if name == 'equal?':
            result.add('equal')
        return result

    def vector_field(self, node):
        return isinstance(node.value, str) and self.program.field_kinds.get(node.value) == 3

    def declare(self, node):
        form = node.value
        if isinstance(form, tuple) and form and form[0].value == 'define-field':
            if len(form) not in (2, 3):
                raise CompileError(node.location, 'define-field requires a name and optional number, entity, or string type')
            name = binding_name(form[1])
            kind = symbol(form[2], 'entity field type') if len(form) == 3 else 'number'
            if kind not in CUSTOM_FIELDS:
                raise CompileError(form[2].location, f'unsupported entity field type {kind}')
            if name.startswith('__qslisp') or name in self.program.names or name in self.constants or name in PRIMITIVES:
                raise CompileError(form[1].location, f'duplicate or reserved entity field {name}')
            self.program.define_field(name, CUSTOM_FIELDS[kind], form[1].location)
            return
        if not isinstance(form, tuple) or len(form) < 3 or form[0].value != 'define':
            raise CompileError(node.location, 'top level requires (define (name arguments...) body...)')
        signature = form[1].value
        if isinstance(signature, str):
            name = binding_name(form[1])
            if name.startswith('__qslisp') or name in self.program.names or name in self.constants or name in PRIMITIVES:
                raise CompileError(form[1].location, f'duplicate or reserved constant {name}')
            if len(form) != 3 or not isinstance(form[2].value, (bool, float, StringLiteral)):
                raise CompileError(form[2].location, 'top-level constants require one number, boolean, or string literal')
            self.constants[name] = form[2]
            return
        if not isinstance(signature, tuple) or not signature:
            raise CompileError(form[1].location, 'only named function definitions are supported yet')
        name = binding_name(signature[0])
        if name.startswith('__qslisp') or name in PRIMITIVES or name in self.constants:
            raise CompileError(signature[0].location, f'reserved function name {name}')
        if name in self.functions:
            raise CompileError(signature[0].location, f'duplicate function {name}')
        abi = self.program.kinds.get(name)
        if name in self.program.names and abi != 6:
            raise CompileError(signature[0].location, f'{name} is reserved by the stock Quake ABI')
        parameters = tuple(binding_name(p) for p in signature[1:])
        if len(parameters) > 8:
            raise CompileError(form[1].location, 'stock VM supports at most eight arguments')
        if len(set(parameters)) != len(parameters):
            raise CompileError(form[1].location, 'duplicate function parameter')
        if name in self.program.names and parameters:
            raise CompileError(form[1].location, 'stock engine entry functions require zero arguments')
        public = self.program.function(name, node.location.filename, len(parameters))
        # Keep body symbols separate from dispatcher/request/error symbols,
        # even when a user function is named dispatch, error, or request_leaf.
        private_name = '__qslisp_fn_' + name
        private = self.program.function(private_name, node.location.filename, len(parameters))
        if name in self.program.names:
            self.program.globals[self.program.names[name]] = public
        else:
            self.program.define(name, 6, [public])
        reference = self.program.define(private_name, 6, [private])
        # Normal values have a zero third word. A request instead carries a raw
        # function reference in word 0 and float32 one in word 2. It is private
        # control data, never a Scheme value or an argument to a Scheme function.
        request = self.program.define('__qslisp_request_' + name, 3,
                                      [private, 0, self.program.globals[self.one]])
        self.functions[name] = Function(name, parameters, form[2:], node.location,
                                        public, private, reference, request)

    def compile(self):
        for function in self.functions.values():
            frame = Frame(self.program, function.private, function.location, len(function.parameters), 3)
            environment = self.frame_environment(frame, function.parameters, {})
            self.tail_sequence(frame, function.body, environment, function)
            frame.finish()

            # Native entry wrappers preserve the CLI/engine ABI. Internal calls
            # use three-word values; native callers supply ordinary float args.
            wrapper = Frame(self.program, function.public, function.location, len(function.parameters), 1)
            args = []
            for i in range(len(function.parameters)):
                value = wrapper.allocate()
                wrapper.emit(OP_STORE, Local(i), value)
                wrapper.emit(OP_STORE, self.zero, advance(value, 1))
                wrapper.emit(OP_STORE, self.zero, advance(value, 2))
                args.append(Value(value, 'number'))
            result = self.call(wrapper, function, args)
            wrapper.emit(OP_RETURN, result.slot)
            wrapper.finish()
        for function in self.lambdas:
            self.compile_lambda(function)
        self.compile_dispatch()
        if self.heap:
            self.heap.compile()
        return self.program.encode()

    def frame_environment(self, frame, parameters, captures):
        environment = captures.copy()
        arguments = {name: Value(Local(i * 3)) for i, name in enumerate(parameters)}
        with self.keep(arguments.values()):
            for name, argument in arguments.items():
                environment[name] = self.bind_local(frame, name, argument, frame.location, environment)
        return environment

    def compile_lambda(self, function):
        frame = Frame(self.program, function.index, function.location, len(function.parameters), 3)
        environment = {}
        if function.captures:
            chain = frame.allocate()
            frame.emit(OP_STORE_V, self.closure_mailbox, chain)
            message = self.program.message(f'{function.location}: invalid closure environment\n')
            for name, original in function.captures.items():
                value = self.heap.call(frame, 'car', [chain, message])
                environment[name] = Value(value, original.kind, original.boxed)
                chain = self.heap.call(frame, 'cdr', [chain, message])
        scope = self.frame_environment(frame, function.parameters, environment)
        self.tail_sequence(frame, function.body, scope, function)
        frame.finish()

    def statistics(self):
        return {
            'global_slots': len(self.program.globals),
            'statements': len(self.program.statements),
            'instruction_bytes': len(self.program.statements) * 8,
            'pair_capacity': self.heap.capacity if self.heap else 0,
            'pair_storage_slots': 9 * self.heap.capacity if self.heap else 0,
            'root_capacity': self.heap.root_capacity if self.heap else 0,
            'root_storage_slots': 3 * self.heap.root_capacity if self.heap else 0,
            'heap_runtime_statements': self.heap.generated_statements if self.heap else 0,
        }

    @contextmanager
    def keep(self, values):
        self.pending.append(values)
        try:
            yield
        finally:
            self.pending.pop()

    def values(self, frame, nodes, environment):
        values = []
        with self.keep(values):
            for node in nodes:
                values.append(self.expression(frame, node, environment))
        return values

    def roots(self, environment, arguments):
        return [*environment.values(), *arguments,
                *(value for context in self.pending for value in context)]

    def compile_dispatch(self):
        # The sole parameter is a three-word request so the CLI cannot mistake
        # its raw function reference for an ordinary numeric argument. The VM
        # saves the target local during nested trampoline invocations.
        frame = Frame(self.program, self.dispatch, self.program.location, 1, 3)
        loop = len(frame.code)
        for i, source in enumerate(self.mailbox):
            frame.emit(OP_STORE_V, source, 4 + i * 3)
        # Stock calls copy the callee's declared parameter widths, independently
        # of the CALL opcode's argument count. All internal functions take <=8.
        frame.emit(OP_CALL0 + 8, Local(0))
        pending_slot = 3  # OFS_RETURN + 2: request flag or callable arity.
        if self.uses_procedures:
            pending_slot = frame.allocate(1)
            frame.emit(OP_EQ, 3, self.one, pending_slot)
        pending = frame.emit(OP_IF, pending_slot)
        frame.emit(OP_RETURN, 1)
        frame.patch(pending, 2, len(frame.code))
        frame.emit(OP_STORE, 1, Local(0))  # New raw target from request payload.
        again = frame.emit(OP_GOTO)
        frame.patch(again, 1, loop)
        frame.finish()

    def sequence(self, frame, nodes, environment):
        result = None
        for node in nodes:
            result = self.expression(frame, node, environment)
        return result

    def tail_sequence(self, frame, nodes, environment, function):
        for node in nodes[:-1]:
            self.expression(frame, node, environment)
        self.tail_expression(frame, nodes[-1], environment, function)

    def application(self, node, environment):
        form = node.value
        if not form:
            raise CompileError(node.location, 'empty application; list values are not supported yet')
        name = form[0].value
        direct = isinstance(name, str) and name not in environment
        return name if direct else None, form[1:]

    def let_environment(self, frame, node, args, environment):
        if len(args) < 2 or not isinstance(args[0].value, tuple):
            raise CompileError(node.location, 'let requires a binding list and body')
        bindings = {}
        with self.keep(bindings.values()):
            for binding in args[0].value:
                pair = binding.value
                if not isinstance(pair, tuple) or len(pair) != 2:
                    raise CompileError(binding.location, 'let binding requires (name expression)')
                label = binding_name(pair[0])
                if label in bindings:
                    raise CompileError(pair[0].location, f'duplicate let binding {label}')
                value = self.expression(frame, pair[1], environment)
                bindings[label] = self.bind_local(frame, label, value, binding.location, environment)
        return environment | bindings

    def bind_local(self, frame, name, value, location, environment):
        if name not in self.mutable_names:
            return value
        pair = self.make_pair(frame, value, self.empty_list(), location, environment)
        return Value(pair.slot, 'pair', boxed=True)

    def recursive_environment(self, frame, node, args, environment):
        if len(args) < 2 or not isinstance(args[0].value, tuple):
            raise CompileError(node.location, 'letrec requires a binding list and body')
        scope = environment.copy()
        entries = []
        names = set()
        uninitialized = Value(self.program.tagged_literal('__qslisp_uninitialized', 0, 'uninitialized'), 'uninitialized')
        for binding in args[0].value:
            if not isinstance(binding.value, tuple) or len(binding.value) != 2:
                raise CompileError(binding.location, 'letrec binding requires (name expression)')
            name, initializer = binding.value
            label = binding_name(name)
            if label in names:
                raise CompileError(name.location, f'duplicate letrec binding {label}')
            names.add(label)
            box = self.make_pair(frame, uninitialized, self.empty_list(), name.location, scope)
            scope[label] = Value(box.slot, 'pair', boxed=True)
            entries.append((box.slot, initializer))
        for box, initializer in entries:
            value = self.expression(frame, initializer, scope)
            self.heap.call(frame, 'car_set', [box, value.slot])
        return scope

    def local_value(self, frame, value, location):
        if not value.boxed:
            return value
        message = self.program.message(f'{location}: invalid lexical binding\n')
        result = self.heap.call(frame, 'car', [value.slot, message])
        pending = frame.allocate(1)
        frame.emit(OP_EQ, advance(result, 1), self.program.constant(TAGS['uninitialized']), pending)
        ready = frame.emit(OP_IFNOT, pending)
        self.heap.error(frame, self.program.message(f'{location}: binding used before initialization\n'))
        frame.patch(ready, 2, len(frame.code))
        return Value(result)

    def arguments(self, frame, node, name, args, environment):
        function = self.functions[name]
        if len(args) != len(function.parameters):
            raise CompileError(node.location, f'{name} expects {len(function.parameters)} arguments, got {len(args)}')
        values = self.values(frame, args, environment)
        return function, values

    def tail_expression(self, frame, node, environment, function):
        if isinstance(node.value, tuple) and node.value:
            name, args = self.application(node, environment)
            if name is None:
                self.call_indirect(frame, node, args, environment, tail=True)
                return
            if name in DERIVED_FORMS:
                self.tail_expression(frame, self.derived_forms.expand(name, args, node.location), environment, function)
                return
            if name == 'if':
                if len(args) != 3:
                    raise CompileError(node.location, 'if requires a condition and two branches')
                condition = self.expression(frame, args[0], environment)
                to_else = frame.emit(OP_IF, self.false_test(frame, condition))
                self.tail_expression(frame, args[1], environment, function)
                frame.patch(to_else, 2, len(frame.code))
                self.tail_expression(frame, args[2], environment, function)
                return
            if name == 'let':
                if args and isinstance(args[0].value, str):
                    lowered = self.derived_forms.named_let(args, node.location)
                    self.tail_expression(frame, lowered, environment, function)
                    return
                scope = self.let_environment(frame, node, args, environment)
                self.tail_sequence(frame, args[1:], scope, function)
                return
            if name == 'letrec':
                scope = self.recursive_environment(frame, node, args, environment)
                self.tail_sequence(frame, args[1:], scope, function)
                return
            if name == 'begin':
                if not args:
                    raise CompileError(node.location, 'begin requires at least one expression')
                self.tail_sequence(frame, args, environment, function)
                return
            if name in self.functions:
                target, values = self.arguments(frame, node, name, args, environment)
                if target is function:
                    # Argument registers provide a parallel-copy staging area:
                    # (loop n b a) must not overwrite a before it is copied.
                    for i, value in enumerate(values):
                        frame.emit(OP_STORE_V, value.slot, 4 + i * 3)
                    for i in range(len(values)):
                        frame.emit(OP_STORE_V, 4 + i * 3, Local(i * 3))
                    again = frame.emit(OP_GOTO)
                    frame.patch(again, 1, 0)
                else:
                    self.publish(frame, values)
                    frame.emit(OP_RETURN, target.request)
                return
        result = self.expression(frame, node, environment)
        frame.emit(OP_RETURN, result.slot)

    def tagged(self, frame, kind):
        value = Value(frame.allocate(), kind)
        frame.emit(OP_STORE, self.program.constant(TAGS[kind]), advance(value.slot, 1))
        frame.emit(OP_STORE, self.zero, advance(value.slot, 2))
        return value

    def false_test(self, frame, value):
        if value.kind not in ('boolean', 'unknown'):
            return self.zero  # Only booleans can be false, including for pair index zero.
        result = frame.allocate(1)
        frame.emit(OP_NOT, value.slot, 0, result)
        if value.kind != 'boolean':
            boolean = frame.allocate(1)
            frame.emit(OP_EQ, advance(value.slot, 1), self.one, boolean)
            frame.emit(OP_AND, result, boolean, result)
        return result

    def number(self, frame, value, node):
        if value.kind not in ('unknown', 'number'):
            raise CompileError(node.location, f'arithmetic and comparisons require numbers, got a {value.kind}')
        self.require_tag(frame, value, node, 'number')

    def require_tag(self, frame, value, node, kind):
        if value.kind == 'unknown':
            tag = advance(value.slot, 1)
            matches = frame.allocate(1)
            if kind == 'number':
                frame.emit(OP_NOT, tag, 0, matches)
            else:
                frame.emit(OP_EQ, tag, self.program.constant(TAGS[kind]), matches)
            skip = frame.emit(OP_IF, matches)
            article = 'an' if kind == 'entity' else 'a'
            message = self.program.message(f'{node.location}: expected {article} {kind}\n')
            frame.emit(OP_STORE, message, 4)
            frame.emit(OP_CALL0 + 1, self.program.error_function)
            frame.patch(skip, 2, len(frame.code))

    def call(self, frame, function, args, environment=None):
        return self.invoke(frame, function.request, args, environment)

    def invoke(self, frame, request, args, environment):
        # Stage arguments only after evaluating ALL of them. Nested calls also
        # use the shared argument/return registers and must not clobber siblings.
        base = self.heap.pin(frame, self.roots(environment or {}, args)) if self.heap else None
        self.publish(frame, args)
        frame.emit(OP_STORE_V, request, 4)
        frame.emit(OP_CALL0 + 1, self.dispatch_reference)
        result = Value(frame.allocate())
        frame.emit(OP_STORE_V, 1, result.slot)
        if self.heap:
            self.heap.unpin(frame, base)
        return result

    def named_procedure(self, function):
        return self.procedure_value(function.private, len(function.parameters))

    def procedure_value(self, index, arity):
        self.uses_procedures = True
        slot = self.program.tagged_literal(f'__qslisp_procedure_{index}', index, 'procedure', arity + 2)
        return Value(slot, 'procedure')

    def make_lambda(self, frame, node, args, environment):
        if len(args) < 2 or not isinstance(args[0].value, tuple):
            raise CompileError(node.location, 'lambda requires a parameter list and body')
        parameters = tuple(binding_name(parameter) for parameter in args[0].value)
        if len(parameters) > 8:
            raise CompileError(args[0].location, 'stock VM supports at most eight arguments')
        if len(parameters) != len(set(parameters)):
            raise CompileError(args[0].location, 'duplicate lambda parameter')
        used = {name for item in args[1:] for name in expression_names(item)}
        captures = {name: value for name, value in environment.items() if name in used and name not in parameters}
        label = f'__qslisp_lambda_{len(self.lambdas)}'
        index = self.program.function(label, node.location.filename, len(parameters))
        self.lambdas.append(LambdaBody(index, parameters, captures, args[1:], node.location))
        procedure = self.procedure_value(index, len(parameters))
        if not captures:
            return procedure
        chain = self.empty_list()
        for value in reversed(captures.values()):
            chain = self.make_pair(frame, value, chain, node.location, environment)
        storage = self.make_pair(frame, procedure, chain, node.location, environment)
        return self.retag(frame, storage, 'closure')

    def call_indirect(self, frame, node, args, environment, *, tail=False):
        if len(args) > 8:
            raise CompileError(node.location, 'stock VM supports at most eight arguments')
        self.uses_procedures = True
        target = node.value[0]
        callable_value = self.expression(frame, target, environment)
        procedure, captures = self.resolve_procedure(frame, callable_value, target)
        with self.keep((callable_value, captures)):
            values = self.values(frame, args, environment)

        arity = frame.allocate(1)
        frame.emit(OP_EQ, advance(procedure.slot, 2), self.program.constant(len(args) + 2), arity)
        valid = frame.emit(OP_IF, arity)
        message = self.program.message(f'{node.location}: procedure does not accept {len(args)} arguments\n')
        frame.emit(OP_STORE, message, 4)
        frame.emit(OP_CALL0 + 1, self.program.error_function)
        frame.patch(valid, 2, len(frame.code))

        request = frame.allocate()
        frame.emit(OP_STORE, procedure.slot, request)
        frame.emit(OP_STORE, self.zero, advance(request, 1))
        frame.emit(OP_STORE, self.one, advance(request, 2))
        if self.closure_mailbox is not None:
            frame.emit(OP_STORE_V, captures.slot, self.closure_mailbox)
        if tail:
            self.publish(frame, values)
            frame.emit(OP_RETURN, request)
            return None
        return self.invoke(frame, request, values, environment)

    def closure_parts(self, frame, value, location):
        pair = self.retag(frame, value, 'pair')
        message = self.program.message(f'{location}: invalid closure\n')
        procedure = self.heap.call(frame, 'car', [pair.slot, message])
        captures = self.heap.call(frame, 'cdr', [pair.slot, message])
        return Value(procedure, 'procedure'), Value(captures, 'pair')

    def resolve_procedure(self, frame, value, target):
        if value.kind not in ('procedure', 'closure', 'unknown'):
            raise CompileError(target.location, f'expected a procedure, got a {value.kind}')
        if value.kind == 'closure':
            return self.closure_parts(frame, value, target.location)
        empty = self.empty_list()
        if value.kind == 'procedure' or self.closure_mailbox is None:
            self.require_tag(frame, value, target, 'procedure')
            return value, empty

        check = frame.allocate(1)
        code, captures = frame.allocate(), frame.allocate()
        frame.emit(OP_EQ, advance(value.slot, 1), self.program.constant(TAGS['procedure']), check)
        plain = frame.emit(OP_IF, check)
        frame.emit(OP_EQ, advance(value.slot, 1), self.program.constant(TAGS['closure']), check)
        self.heap.guard(frame, check, self.program.message(f'{target.location}: expected a procedure\n'))
        closed_code, closed_captures = self.closure_parts(frame, value, target.location)
        frame.emit(OP_STORE_V, closed_code.slot, code)
        frame.emit(OP_STORE_V, closed_captures.slot, captures)
        done = frame.emit(OP_GOTO)
        frame.patch(plain, 2, len(frame.code))
        frame.emit(OP_STORE_V, value.slot, code)
        frame.emit(OP_STORE_V, empty.slot, captures)
        frame.patch(done, 1, len(frame.code))
        return Value(code, 'procedure'), Value(captures)

    def publish(self, frame, args):
        for i, destination in enumerate(self.mailbox):
            frame.emit(OP_STORE_V, args[i].slot if i < len(args) else self.zero, destination)

    def empty_list(self):
        return Value(self.program.tagged_literal('__qslisp_null', 0, 'null'), 'null')

    def make_pair(self, frame, head, tail, location, environment):
        message = self.program.message(f'{location}: pair heap exhausted ({self.heap.capacity} cells)\n')
        base = self.heap.pin(frame, self.roots(environment, (head, tail)))
        result = self.heap.call(frame, 'cons', [head.slot, tail.slot, message])
        self.heap.unpin(frame, base)
        return Value(result, 'pair')

    def quoted(self, frame, datum, environment):
        value = datum.value
        if isinstance(value, tuple):
            dots = [i for i, item in enumerate(value) if item.value == '.']
            if dots:
                if len(dots) != 1 or dots[0] == 0 or dots[0] != len(value) - 2:
                    raise CompileError(datum.location, 'a dotted list requires preceding items and one tail datum')
                head, tail_datum = value[:dots[0]], value[-1]
                tail = self.quoted(frame, tail_datum, environment)
            else:
                head, tail = value, self.empty_list()
            for item in reversed(head):
                with self.keep((tail,)):
                    first = self.quoted(frame, item, environment)
                tail = self.make_pair(frame, first, tail, item.location, environment)
            return tail
        if isinstance(value, str):
            if value == '.':
                raise CompileError(datum.location, 'unexpected dotted-list marker')
            name_id = self.program.string(value)
            slot = self.program.tagged_literal(f'__qslisp_symbol_{name_id}', name_id, 'symbol')
            return Value(slot, 'symbol')
        return self.expression_body(frame, datum, environment)

    def proper_list(self, frame, value, location):
        result = self.tagged(frame, 'boolean')
        current = value.slot
        if self.heap:
            current = frame.allocate()
            frame.emit(OP_STORE_V, value.slot, current)
            loop = len(frame.code)
            pair = frame.allocate(1)
            frame.emit(OP_EQ, advance(current, 1), self.program.constant(TAGS['pair']), pair)
            done = frame.emit(OP_IFNOT, pair)
            message = self.program.message(f'{location}: invalid list tail\n')
            tail = self.heap.call(frame, 'cdr', [current, message])
            frame.emit(OP_STORE_V, tail, current)
            again = frame.emit(OP_GOTO)
            frame.patch(again, 1, loop)
            frame.patch(done, 2, len(frame.code))
        frame.emit(OP_EQ, advance(current, 1), self.program.constant(TAGS['null']), result.slot)
        return result

    def engine_string(self, name, literal, kind):
        if not isinstance(literal.value, StringLiteral):
            raise CompileError(literal.location, f'{name} requires a string literal here')
        text = literal.value.text
        encoded = text.encode('utf-8')
        if name in ('quake:dprint', 'quake:error', 'quake:centerprint') and len(encoded) > 255:
            raise CompileError(literal.location, f'{name} text exceeds the stock 255-byte limit')
        if kind in ('model', 'sample') and (not encoded or encoded[0] <= 32 or len(encoded) > 63):
            raise CompileError(literal.location, f'{name} requires a stock {kind} path of 1–63 bytes')
        if kind == 'level' and (not 1 <= len(text) <= 63 or not text.isascii() or
                                not all(char.isalnum() or char in '_-' for char in text)):
            raise CompileError(literal.location, 'change-level requires a literal map name using letters, digits, _ or -')
        return self.program.literal_string(text)

    def engine_field(self, node, kinds):
        name = symbol(node, 'stock entity field')
        kind = self.program.field_kinds.get(name)
        if kind not in kinds:
            expected = ' or '.join(FIELD_TYPES[k] for k in kinds)
            raise CompileError(node.location, f'expected a {expected} stock entity field, got {name}')
        return self.program.names[name], kind

    def entity(self, frame, node, environment):
        value = self.expression(frame, node, environment)
        if value.kind not in ('unknown', 'entity'):
            raise CompileError(node.location, f'expected an entity, got a {value.kind}')
        self.require_tag(frame, value, node, 'entity')
        return value.slot

    def string_value(self, frame, node, environment):
        value = self.expression(frame, node, environment)
        if value.kind not in ('unknown', 'string'):
            raise CompileError(node.location, f'expected a string, got a {value.kind}')
        self.require_tag(frame, value, node, 'string')
        return value.slot

    def retag(self, frame, value, kind):
        result = self.tagged(frame, kind)
        frame.emit(OP_STORE, value.slot, result.slot)
        return result

    def box_vector(self, frame, raw, location, environment):
        coordinates = []
        for i in range(3):
            scalar = self.tagged(frame, 'number')
            frame.emit(OP_STORE, advance(raw, i), scalar.slot)
            coordinates.append(scalar)
        x, y, z = coordinates
        tail = self.make_pair(frame, y, z, location, environment)
        storage = self.make_pair(frame, x, tail, location, environment)
        return self.retag(frame, storage, 'vector')

    def vector(self, frame, node, environment):
        if isinstance(node.value, tuple):
            name, args = self.application(node, environment)
            if name == 'quake:field':
                return self.read_field(frame, node, args, environment, vector=True)
            if name == 'quake:vector' and len(args) == 3:
                result = frame.allocate()
                for i, arg in enumerate(args):
                    value = self.expression(frame, arg, environment)
                    self.number(frame, value, arg)
                    frame.emit(OP_STORE, value.slot, advance(result, i))
                return result
        value = self.expression(frame, node, environment)
        if value.kind not in ('unknown', 'vector'):
            raise CompileError(node.location, f'expected a vector, got a {value.kind}')
        self.require_tag(frame, value, node, 'vector')
        storage = self.retag(frame, value, 'pair')
        message = self.program.message(f'{node.location}: invalid vector storage\n')
        x = self.heap.call(frame, 'car', [storage.slot, message])
        tail = self.heap.call(frame, 'cdr', [storage.slot, message])
        y = self.heap.call(frame, 'car', [tail, message])
        z = self.heap.call(frame, 'cdr', [tail, message])
        result = frame.allocate()
        for i, coordinate in enumerate((x, y, z)):
            frame.emit(OP_STORE, coordinate, advance(result, i))
        return result

    def read_field(self, frame, node, args, environment, *, vector=False):
        if len(args) != 2:
            raise CompileError(node.location, 'quake:field requires an entity and a field name')
        field, kind = self.engine_field(args[1], (3,) if vector else (*FIELD_READS, 3))
        entity = self.entity(frame, args[0], environment)
        if kind == 3:
            result = frame.allocate()
            frame.emit(OP_LOAD_V, entity, field, result)
            return result if vector else self.box_vector(frame, result, node.location, environment)
        tag, opcode = FIELD_READS[kind]
        result = self.tagged(frame, tag)
        frame.emit(opcode, entity, field, result.slot)
        return result

    def write_field(self, frame, node, args, environment):
        if len(args) != 3:
            raise CompileError(node.location, 'quake:set-field! requires an entity, a field name, and a value')
        field, kind = self.engine_field(args[1], tuple(FIELD_WRITES))
        entity = self.entity(frame, args[0], environment)
        if kind == 1:
            value_slot = self.string_value(frame, args[2], environment)
        elif kind == 3:
            value_slot = self.vector(frame, args[2], environment)
        elif kind == 4:
            value_slot = self.entity(frame, args[2], environment)
        else:
            value = self.expression(frame, args[2], environment)
            self.number(frame, value, args[2])
            value_slot = value.slot
        address = frame.allocate(1)
        frame.emit(OP_ADDRESS, entity, field, address)
        frame.emit(FIELD_WRITES[kind], value_slot, address)
        return Value(self.zero, 'number')

    def callback(self, frame, node, name, args, environment):
        if len(args) != 3:
            raise CompileError(node.location, f'{name} requires an entity, function field, and callback argument')
        field, _ = self.engine_field(args[1], (6,))
        entity = self.entity(frame, args[0], environment)
        if name == 'quake:set-callback!':
            target = args[2]
            if target.value is False:
                reference = self.zero
            else:
                label = symbol(target, 'named callback or #f')
                function = self.functions.get(label) if label not in environment else None
                if function is None or function.parameters:
                    raise CompileError(target.location, 'expected an unshadowed, zero-argument callback name')
                reference = self.program.names[label]
            address = frame.allocate(1)
            frame.emit(OP_ADDRESS, entity, field, address)
            frame.emit(OP_STOREP_FNC, reference, address)
            return Value(self.zero, 'number')

        other = self.entity(frame, args[2], environment)
        reference = frame.allocate(1)
        frame.emit(OP_LOAD_FNC, entity, field, reference)
        missing = frame.emit(OP_IFNOT, reference)
        self_slot, other_slot = (self.program.names[key] for key in ('self', 'other'))
        saved_self, saved_other = frame.allocate(1), frame.allocate(1)
        frame.emit(OP_STORE, self_slot, saved_self)
        frame.emit(OP_STORE, other_slot, saved_other)
        # A named callback can allocate on the shared Scheme heap.
        base = self.heap.pin(frame, self.roots(environment, ())) if self.heap else None
        frame.emit(OP_STORE, entity, self_slot)
        frame.emit(OP_STORE, other, other_slot)
        frame.emit(OP_CALL0, reference)
        frame.emit(OP_STORE, saved_self, self_slot)
        frame.emit(OP_STORE, saved_other, other_slot)
        if self.heap:
            self.heap.unpin(frame, base)
        frame.patch(missing, 2, len(frame.code))
        return Value(self.zero, 'number')

    def engine_call(self, frame, node, name, args, environment):
        number, kinds = ENGINE_CALLS[name]
        if kinds in (('string',), ('model',), ('sample',)) and (len(args) != 1 or not isinstance(args[0].value, StringLiteral)):
            raise CompileError(node.location, f'{name} requires one string literal')
        if len(args) != len(kinds):
            raise CompileError(node.location, f'{name} requires {len(kinds)} arguments')
        operands = []
        for arg, kind in zip(args, kinds):
            if kind == 'entity':
                slot = self.entity(frame, arg, environment)
            elif kind == 'vector':
                slot = self.vector(frame, arg, environment)
            elif kind == 'string-field':
                slot, _ = self.engine_field(arg, (1,))
            elif kind == 'number':
                value = self.expression(frame, arg, environment)
                self.number(frame, value, arg)
                slot = value.slot
            elif kind == 'precache-name' and isinstance(arg.value, StringLiteral):
                slot = self.engine_string(name, arg, 'model')
            elif kind in ('precache-name', 'string-value'):
                slot = self.string_value(frame, arg, environment)
            else:
                slot = self.engine_string(name, arg, kind)
            operands.append(slot)
        # The stock step mover may run touch callbacks before it returns.
        base = self.heap.pin(frame, self.roots(environment, ())) if self.heap and name == 'quake:walkmove' else None
        for i, (slot, kind) in enumerate(zip(operands, kinds)):
            frame.emit(OP_STORE_V if kind == 'vector' else OP_STORE, slot, 4 + 3 * i)
        builtin = (self.program.error_function if number == 10 else
                   self.program.builtin(f'__qslisp_builtin_{number}', number, len(kinds)))
        frame.emit(OP_CALL0 + len(kinds), builtin)
        if name in ENTITY_RESULTS:
            source = ENTITY_RESULTS[name]
            if isinstance(source, str):
                source = self.program.names[source]
            result = self.tagged(frame, 'entity')
            frame.emit(OP_STORE, source, result.slot)
            return result
        if name in NUMERIC_RESULTS:
            result = self.tagged(frame, 'number')
            frame.emit(OP_STORE, 1, result.slot)
            if base is not None:
                self.heap.unpin(frame, base)
            return result
        return Value(self.zero, 'number')

    def expression(self, frame, node, environment):
        # An inner let may shadow a binding still needed by the enclosing
        # expression's continuation. Keep those outer environments as well as
        # already evaluated arguments; scanning only the innermost scope loses
        # such pairs during collection.
        with self.keep(environment.values()):
            return self.expression_body(frame, node, environment)

    def expression_body(self, frame, node, environment):
        form = node.value
        if form == ():
            return self.empty_list()
        if isinstance(form, bool):
            return Value(self.program.constant(float(form), True), 'boolean')
        if isinstance(form, float):
            return Value(self.program.constant(form, location=node.location), 'number')
        if isinstance(form, StringLiteral):
            result = self.tagged(frame, 'string')
            frame.emit(OP_STORE, self.program.literal_string(form.text), result.slot)
            return result
        if isinstance(form, str):
            if form in self.constants and form not in environment:
                return self.expression_body(frame, self.constants[form], environment)
            if form not in environment:
                if form in self.functions:
                    return self.named_procedure(self.functions[form])
                raise CompileError(node.location, f'unbound variable {form}')
            return self.local_value(frame, environment[form], node.location)
        name, args = self.application(node, environment)
        if name is None:
            return self.call_indirect(frame, node, args, environment)
        if name in DERIVED_FORMS:
            return self.expression(frame, self.derived_forms.expand(name, args, node.location), environment)
        if name == 'lambda':
            return self.make_lambda(frame, node, args, environment)
        if name == 'set!':
            if len(args) != 2:
                raise CompileError(node.location, 'set! requires a binding name and value')
            label = symbol(args[0], 'assignment target')
            binding = environment.get(label)
            if binding is None or not binding.boxed:
                raise CompileError(args[0].location, f'set! requires a mutable lexical binding, got {label}')
            value = self.expression(frame, args[1], environment)
            self.heap.call(frame, 'car_set', [binding.slot, value.slot])
            return value
        if name == 'quote':
            if len(args) != 1:
                raise CompileError(node.location, 'quote requires one datum')
            return self.quoted(frame, args[0], environment)
        if name == 'list':
            items = self.values(frame, args, environment)
            result = self.empty_list()
            with self.keep(items):
                for item in reversed(items):
                    result = self.make_pair(frame, item, result, node.location, environment)
            return result
        if name == 'list?' or name in VALUE_PREDICATES:
            if len(args) != 1:
                raise CompileError(node.location, f'{name} requires 1 argument')
            value = self.expression(frame, args[0], environment)
            if name == 'list?':
                return self.proper_list(frame, value, node.location)
            result = self.tagged(frame, 'boolean')
            tag = self.program.constant(TAGS[VALUE_PREDICATES[name]])
            frame.emit(OP_EQ, advance(value.slot, 1), tag, result.slot)
            if name == 'procedure?' and self.closure_mailbox is not None:
                closed = frame.allocate(1)
                frame.emit(OP_EQ, advance(value.slot, 1), self.program.constant(TAGS['closure']), closed)
                frame.emit(OP_OR, result.slot, closed, result.slot)
            return result
        if name in ('eq?', 'equal?'):
            if len(args) != 2:
                raise CompileError(node.location, f'{name} requires two arguments')
            left, right = self.values(frame, args, environment)
            if name == 'equal?' and self.heap:
                return Value(self.heap.call(frame, 'equal', [left.slot, right.slot]), 'boolean')
            result = self.tagged(frame, 'boolean')
            emit_shallow_equality(frame, left.slot, right.slot, result.slot, compare_strings=name == 'equal?')
            return result
        if name in ENGINE_CALLS:
            return self.engine_call(frame, node, name, args, environment)
        if name in ENGINE_GLOBALS:
            if args:
                raise CompileError(node.location, f'{name} takes no arguments')
            global_name, kind = ENGINE_GLOBALS[name]
            result = self.tagged(frame, kind)
            frame.emit(OP_STORE, self.program.names[global_name], result.slot)
            return result
        if name == 'quake:world?':
            if len(args) != 1:
                raise CompileError(node.location, 'quake:world? requires one entity')
            entity = self.entity(frame, args[0], environment)
            result = self.tagged(frame, 'boolean')
            frame.emit(OP_NOT_ENT, entity, 0, result.slot)
            return result
        if name == 'quake:entity=?':
            if len(args) != 2:
                raise CompileError(node.location, 'quake:entity=? requires two entities')
            left, right = (self.entity(frame, arg, environment) for arg in args)
            result = self.tagged(frame, 'boolean')
            frame.emit(OP_EQ_ENT, left, right, result.slot)
            return result
        if name == 'string=?':
            if len(args) != 2:
                raise CompileError(node.location, 'string=? requires two strings')
            left, right = (self.string_value(frame, arg, environment) for arg in args)
            result = self.tagged(frame, 'boolean')
            frame.emit(OP_EQ_STR, left, right, result.slot)
            return result
        if name == 'quake:field':
            return self.read_field(frame, node, args, environment)
        if name == 'quake:set-field!':
            return self.write_field(frame, node, args, environment)
        if name in ('quake:set-callback!', 'quake:call-callback'):
            return self.callback(frame, node, name, args, environment)
        if name == 'quake:vector':
            if len(args) != 3:
                raise CompileError(node.location, 'quake:vector requires three coordinates')
            return self.box_vector(frame, self.vector(frame, node, environment), node.location, environment)
        if name in VECTOR_COMPONENTS:
            if len(args) != 1:
                raise CompileError(node.location, f'{name} requires one vector')
            raw = self.vector(frame, args[0], environment)
            result = self.tagged(frame, 'number')
            frame.emit(OP_STORE, advance(raw, VECTOR_COMPONENTS[name]), result.slot)
            return result
        if name == 'if':
            if len(args) != 3:
                raise CompileError(node.location, 'if requires a condition and two branches')
            condition = self.expression(frame, args[0], environment)
            to_else = frame.emit(OP_IF, self.false_test(frame, condition))
            result = frame.allocate()
            yes = self.expression(frame, args[1], environment)
            frame.emit(OP_STORE_V, yes.slot, result)
            to_end = frame.emit(OP_GOTO)
            frame.patch(to_else, 2, len(frame.code))
            no = self.expression(frame, args[2], environment)
            frame.emit(OP_STORE_V, no.slot, result)
            frame.patch(to_end, 1, len(frame.code))
            return Value(result, yes.kind if yes.kind == no.kind else 'unknown')
        if name == 'let':
            if args and isinstance(args[0].value, str):
                return self.expression(frame, self.derived_forms.named_let(args, node.location), environment)
            scope = self.let_environment(frame, node, args, environment)
            return self.sequence(frame, args[1:], scope)
        if name == 'letrec':
            scope = self.recursive_environment(frame, node, args, environment)
            return self.sequence(frame, args[1:], scope)
        if name == 'begin':
            if not args:
                raise CompileError(node.location, 'begin requires at least one expression')
            return self.sequence(frame, args, environment)
        if name == 'not':
            if len(args) != 1:
                raise CompileError(node.location, 'not requires one argument')
            value = self.expression(frame, args[0], environment)
            result = self.tagged(frame, 'boolean')
            frame.emit(OP_STORE, self.false_test(frame, value), result.slot)
            return result
        if name in ('cons', 'car', 'cdr'):
            arity = 2 if name == 'cons' else 1
            if len(args) != arity:
                raise CompileError(node.location, f'{name} requires {arity} argument(s)')
            values = self.values(frame, args, environment)
            if name in ('car', 'cdr'):
                if values[0].kind not in ('unknown', 'pair'):
                    raise CompileError(node.location, f'{name} requires a pair, got a {values[0].kind}')
                message = self.program.message(f'{node.location}: {name} requires an allocated pair\n')
                slot = self.heap.call(frame, name, [values[0].slot, message])
                return Value(slot)
            return self.make_pair(frame, *values, node.location, environment)
        if name in ARITHMETIC or name in COMPARISONS or name in BITWISE:
            if name in (COMPARISONS.keys() | BITWISE.keys()) and len(args) != 2:
                raise CompileError(node.location, f'{name} requires exactly two arguments in this release')
            if name in ('-', '/') and not args:
                raise CompileError(node.location, f'{name} requires at least one argument')
            values = self.values(frame, args, environment)
            for value, argument in zip(values, args):
                self.number(frame, value, argument)
            if name in COMPARISONS:
                result = self.tagged(frame, 'boolean')
                frame.emit(COMPARISONS[name], values[0].slot, values[1].slot, result.slot)
                return result
            if name in BITWISE:
                result = self.tagged(frame, 'number')
                frame.emit(BITWISE[name], values[0].slot, values[1].slot, result.slot)
                return result
            if not values:
                return Value(self.zero if name == '+' else self.one, 'number')
            if len(values) == 1 and name in ('-', '/'):
                values.insert(0, Value(self.zero if name == '-' else self.one, 'number'))
            result = values[0]
            for value in values[1:]:
                temporary = self.tagged(frame, 'number')
                frame.emit(ARITHMETIC[name], result.slot, value.slot, temporary.slot)
                result = temporary
            return result
        if name in SYNTAX:
            raise CompileError(node.location, f'{name} is not supported here yet')
        if name not in self.functions:
            raise CompileError(form[0].location, f'undefined function {name}')
        function, values = self.arguments(frame, node, name, args, environment)
        return self.call(frame, function, values, environment)


def compile_source(source, filename='<input>', *, heap_pairs=256, root_slots=256):
    return Compiler(load_forms(source, filename), filename,
                    heap_pairs=heap_pairs, root_slots=root_slots).compile()
