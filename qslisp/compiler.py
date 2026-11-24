"""Lexical resolution and direct emission for a small, dynamically tagged core."""
from dataclasses import dataclass

from .bytecode import (Program, Frame, Local, TAGS, advance, OP_MUL, OP_DIV, OP_ADD, OP_SUB,
                       OP_EQ, OP_LE, OP_GE, OP_LT, OP_GT, OP_STORE, OP_STORE_V,
                       OP_RETURN, OP_NOT, OP_NOT_ENT, OP_IF, OP_IFNOT, OP_CALL0, OP_GOTO, OP_AND, OP_OR,
                       OP_LOAD_F, OP_LOAD_V, OP_ADDRESS, OP_STOREP_F, OP_STOREP_V,
                       OP_STOREP_S, OP_EQ_ENT, OP_EQ_STR, OP_BITAND, OP_BITOR,
                       OP_LOAD_S, OP_LOAD_ENT, OP_LOAD_FNC, OP_STOREP_ENT, OP_STOREP_FNC,
                       emit_shallow_equality)
from .reader import CompileError, Location, StringLiteral, split_dotted
from .heap import PairHeap
from .macros import Macros
from .modules import load_forms
from .quasiquote import BUILD, QUASIQUOTE_FORMS, SPLICE
from .records import Match, record_definitions
from .syntax import DERIVED_FORMS, DerivedForms

SYNTAX = DERIVED_FORMS | set(QUASIQUOTE_FORMS) | {
    'define', 'define-field', 'import', 'if', 'let', 'begin', 'lambda', 'quote', 'set!', 'letrec',
    'define-syntax', 'syntax-rules', 'define-record', 'match',
}
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
    'quake:vector-length': (12, ('vector',)),
    'quake:vector-yaw': (13, ('vector',)),
    'quake:spawn': (14, ()),
    'quake:remove': (15, ('entity',)),
    'quake:traceline': (16, ('vector', 'vector', 'number', 'entity')),
    'quake:find': (18, ('entity', 'string-field', 'string-value')),
    'quake:precache-sound': (19, ('sample',)),
    'quake:precache-model': (20, ('model',)),
    'quake:client-command': (21, ('entity', 'command')),
    'quake:dprint': (25, ('string',)),
    'quake:walkmove': (32, ('number', 'number')),
    'quake:drop-to-floor': (34, ()),
    'quake:floor': (37, ('number',)),
    'quake:cvar': (45, ('string',)),
    'quake:particle': (48, ('vector', 'vector', 'number', 'number')),
    'quake:change-level': (70, ('level',)),
    'quake:centerprint': (73, ('entity', 'string')),
}
ENGINE_GLOBALS = {'quake:self': ('self', 'entity'), 'quake:other': ('other', 'entity'),
                  'quake:world': ('world', 'entity'),
                  'quake:time': ('time', 'number'), 'quake:frametime': ('frametime', 'number'),
                  'quake:coop': ('coop', 'number'), 'quake:trace-fraction': ('trace_fraction', 'number'),
                  'quake:trace-normal-x': ('trace_plane_normal_x', 'number'),
                  'quake:trace-normal-y': ('trace_plane_normal_y', 'number'),
                  'quake:trace-normal-z': ('trace_plane_normal_z', 'number'),
                  'quake:trace-end-z': ('trace_endpos_z', 'number'),
                  'quake:forward-x': ('v_forward_x', 'number'),
                  'quake:forward-y': ('v_forward_y', 'number'), 'quake:forward-z': ('v_forward_z', 'number')}
ENTITY_RESULTS = {'quake:spawn': 1, 'quake:find': 1, 'quake:traceline': 'trace_ent'}
NUMERIC_RESULTS = {'quake:vector-length', 'quake:vector-yaw', 'quake:walkmove', 'quake:drop-to-floor',
                   'quake:floor', 'quake:cvar'}
PRIMITIVES = (ARITHMETIC.keys() | COMPARISONS.keys() | BITWISE.keys() |
              ENGINE_CALLS.keys() | ENGINE_GLOBALS.keys()) | {
    'not', 'cons', 'car', 'cdr', 'pair?', 'list', 'append', 'list?', 'null?', 'symbol?', 'string?', 'eq?', 'equal?',
    'procedure?',
    'quake:world?', 'quake:entity?', 'quake:entity=?',
    'quake:field', 'quake:set-field!', 'quake:vector', 'quake:vector?', 'string=?',
    'quake:vector-x', 'quake:vector-y', 'quake:vector-z',
    'quake:set-callback!', 'quake:call-callback', 'quake:set-view', 'quake:set-view-angles!', 'quake:beam',
    'quake:dprint-number',
}
VALUE_PREDICATES = {'pair?': 'pair', 'null?': 'null', 'symbol?': 'symbol', 'string?': 'string',
                    'quake:vector?': 'vector', 'quake:entity?': 'entity', 'procedure?': 'procedure'}
VECTOR_COMPONENTS = {'quake:vector-x': 0, 'quake:vector-y': 1, 'quake:vector-z': 2}
FIELD_TYPES = {1: 'string', 2: 'numeric', 3: 'vector', 4: 'entity', 6: 'function'}
CUSTOM_FIELDS = {'number': 2, 'entity': 4, 'string': 1}
FIELD_READS = {1: ('string', OP_LOAD_S), 2: ('number', OP_LOAD_F), 4: ('entity', OP_LOAD_ENT)}
FIELD_WRITES = {1: OP_STOREP_S, 2: OP_STOREP_F, 3: OP_STOREP_V, 4: OP_STOREP_ENT}
RECORD_TYPES = (TAGS.keys() - {'uninitialized', 'closure'}) | {'any', 'list'}


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
    schema: str | None = None


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
    def __init__(self, forms, filename, *, heap_pairs=512):
        forms = Macros().program(forms)
        location = forms[0].location if forms else Location(filename, 1, 1)
        if type(heap_pairs) is not int or heap_pairs < 1:
            raise CompileError(location, 'heap-pairs must be a positive integer')
        self.program = Program(location)
        self.functions = {}
        self.constants = {}
        self.derived_forms = DerivedForms()
        forms, self.records = record_definitions(forms, RECORD_TYPES)
        self.match = Match(self.records, self.derived_forms.fresh)
        self.constructors = {f'make-{name}': record for name, record in self.records.items()}
        self.getters = {f'{name}-{field}': kind for name, record in self.records.items() for field, kind in record.fields}
        self.lambdas = []
        self.zero = self.program.constant(0)
        self.one = self.program.constant(1)
        for form in forms:
            self.declare(form)
        if not self.functions:
            raise CompileError(location, 'expected at least one function definition')
        bodies = [node for function in self.functions.values() for node in function.body]
        features = set().union(*(self.heap_features(node) for node in bodies))
        self.mutable_names = {name for node in bodies for name in expression_names(node, mutations=True)}
        self.closure_mailbox = (self.program.define('__qslisp_captured_values', 3, [0, 0, 0])
                                if 'closure' in features else None)
        kinds = tuple(kind for kind in ('vector', 'closure', 'record') if kind in features)
        self.heap = (PairHeap(self.program, heap_pairs, deep_equal='equal' in features,
                              append='append' in features, boxed_kinds=kinds)
                     if 'pair' in features or kinds else None)

    def heap_features(self, node, *, native=False):
        if not isinstance(node.value, tuple) or not node.value:
            return {'vector'} if native else set()
        form = node.value
        name = form[0].value if isinstance(form[0].value, str) else None
        if name == 'match':
            return self.heap_features(self.match.expand(form[1:], node.location), native=native)
        if name == '#match-branch':
            children = (*(entry.value[1] for entry in form[1].value), *form[2:])
            return set().union(*(self.heap_features(child) for child in children)) | ({'vector'} if native else set())
        if name and name.startswith('#match-call:'):
            name = name.removeprefix('#match-call:')
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
        if name == BUILD:
            result.add('pair')
        if name == SPLICE or (name == 'append' and len(form) > 2):
            result.update(('pair', 'append'))
        if name == 'set!':
            result.add('pair')
        if name in ('lambda', 'letrec') or (name == 'let' and len(form) > 1 and isinstance(form[1].value, str)):
            result.add('closure')
        if name in ('#record-create', '#record-read', '#record-test'):
            result.add('record')
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
        # Keep body symbols separate from request/error symbols,
        # even when a user function is named error or request_leaf.
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
            # Nothing allocated during an engine entry is reachable after it.
            if self.heap:
                arena = wrapper.allocate(1)
                wrapper.emit(OP_STORE, self.heap.next, arena)
            result = self.call(wrapper, function, args)
            if self.heap:
                wrapper.emit(OP_STORE, arena, self.heap.next)
            wrapper.emit(OP_RETURN, result.slot)
            wrapper.finish()
        for function in self.lambdas:
            self.compile_lambda(function)
        if self.heap:
            self.heap.compile()
        return self.program.encode()

    def frame_environment(self, frame, parameters, captures):
        environment = captures.copy()
        for i, name in enumerate(parameters):
            environment[name] = self.bind_local(frame, name, Value(Local(i * 3)), frame.location)
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
            'pair_storage_slots': 6 * self.heap.capacity if self.heap else 0,
            'heap_runtime_statements': self.heap.generated_statements if self.heap else 0,
        }

    def values(self, frame, nodes, environment):
        return [self.expression(frame, node, environment) for node in nodes]

    def discard(self, frame, nodes, environment):
        # A value nobody reads leaves nothing live: its temporaries, and any
        # bindings scoped inside it, can be reused by what follows.
        for node in nodes:
            words = frame.words
            self.expression(frame, node, environment)
            frame.release(words)

    def sequence(self, frame, nodes, environment):
        self.discard(frame, nodes[:-1], environment)
        return self.expression(frame, nodes[-1], environment)

    def tail_sequence(self, frame, nodes, environment, function):
        self.discard(frame, nodes[:-1], environment)
        self.tail_expression(frame, nodes[-1], environment, function)

    def application(self, node, environment):
        form = node.value
        if not form:
            raise CompileError(node.location, 'empty application; list values are not supported yet')
        name = form[0].value
        if isinstance(name, str) and name.startswith('#match-call:'):
            return name.removeprefix('#match-call:'), form[1:]
        direct = isinstance(name, str) and name not in environment
        return name if direct else None, form[1:]

    def let_environment(self, frame, node, args, environment):
        if len(args) < 2 or not isinstance(args[0].value, tuple):
            raise CompileError(node.location, 'let requires a binding list and body')
        bindings = {}
        for binding in args[0].value:
            pair = binding.value
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise CompileError(binding.location, 'let binding requires (name expression)')
            label = binding_name(pair[0])
            if label in bindings:
                raise CompileError(pair[0].location, f'duplicate let binding {label}')
            value = self.expression(frame, pair[1], environment)
            bindings[label] = self.bind_local(frame, label, value, binding.location)
        return environment | bindings

    def bind_local(self, frame, name, value, location):
        if name not in self.mutable_names:
            return value
        pair = self.make_pair(frame, value, self.empty_list(), location)
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
            box = self.make_pair(frame, uninitialized, self.empty_list(), name.location)
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
        if name in self.constructors:
            record = self.constructors[name]
            for (field, kind), argument, value in zip(record.fields, args, values):
                acceptable = {'list': ('pair', 'null'), 'procedure': ('procedure', 'closure')}.get(kind, (kind,))
                if kind in self.records:
                    acceptable = ('record',)
                wrong_schema = kind in self.records and value.schema not in (None, kind)
                if kind != 'any' and value.kind != 'unknown' and (value.kind not in acceptable or wrong_schema):
                    raise CompileError(argument.location, f'{record.name}.{field} expects {kind}, got {value.schema or value.kind}')
        return function, values

    def tail_expression(self, frame, node, environment, function):
        with frame.at(node.location):
            return self.tail_expression_body(frame, node, environment, function)

    def tail_expression_body(self, frame, node, environment, function):
        if isinstance(node.value, tuple) and node.value:
            name, args = self.application(node, environment)
            if name is None:
                self.call_indirect(frame, node, args, environment, tail=True)
                return
            if name in DERIVED_FORMS:
                self.tail_expression(frame, self.derived_forms.expand(name, args, node.location), environment, function)
                return
            if name == 'match':
                self.tail_expression(frame, self.match.expand(args, node.location), environment, function)
                return
            if name == '#match-branch':
                self.match_branch(frame, args, environment, function=function)
                return
            if name == 'if':
                if len(args) != 3:
                    raise CompileError(node.location, 'if requires a condition and two branches')
                # The test is dead once branched on, and only one arm runs.
                words = frame.words
                condition = self.expression(frame, args[0], environment)
                to_else = frame.emit(OP_IF, self.false_test(frame, condition))
                frame.release(words)
                self.tail_expression(frame, args[1], environment, function)
                frame.release(words)
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
                    self.stage(frame, values)
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

    def call(self, frame, function, args):
        return self.invoke(frame, function.reference, args)

    def stage(self, frame, args):
        # Arguments go straight into the VM's parameter registers, and only
        # after ALL of them are evaluated: nested calls use the same registers.
        for i, value in enumerate(args):
            frame.emit(OP_STORE_V, value.slot, 4 + i * 3)

    def invoke(self, frame, target, args):
        self.stage(frame, args)
        frame.emit(OP_CALL0 + len(args), target)
        # A callee in tail position returns a request instead of a value, with
        # its arguments already staged. Call the requested function from here,
        # after that callee's frame is gone, until a normal value comes back.
        # Only a request has float32 one in its third word.
        loop = len(frame.code)
        pending = frame.allocate(1)
        frame.emit(OP_EQ, 3, self.one, pending)
        done = frame.emit(OP_IFNOT, pending)
        requested = frame.allocate(1)
        frame.emit(OP_STORE, 1, requested)
        frame.emit(OP_CALL0, requested)
        again = frame.emit(OP_GOTO)
        frame.patch(again, 1, loop)
        frame.patch(done, 2, len(frame.code))
        result = Value(frame.allocate())
        frame.emit(OP_STORE_V, 1, result.slot)
        return result

    def named_procedure(self, function):
        return self.procedure_value(function.private, len(function.parameters))

    def procedure_value(self, index, arity):
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
            chain = self.make_pair(frame, value, chain, node.location)
        storage = self.make_pair(frame, procedure, chain, node.location)
        return self.retag(frame, storage, 'closure')

    def call_indirect(self, frame, node, args, environment, *, tail=False):
        if len(args) > 8:
            raise CompileError(node.location, 'stock VM supports at most eight arguments')
        target = node.value[0]
        callable_value = self.expression(frame, target, environment)
        procedure, captures = self.resolve_procedure(frame, callable_value, target)
        values = self.values(frame, args, environment)

        arity = frame.allocate(1)
        frame.emit(OP_EQ, advance(procedure.slot, 2), self.program.constant(len(args) + 2), arity)
        valid = frame.emit(OP_IF, arity)
        message = self.program.message(f'{node.location}: procedure does not accept {len(args)} arguments\n')
        frame.emit(OP_STORE, message, 4)
        frame.emit(OP_CALL0 + 1, self.program.error_function)
        frame.patch(valid, 2, len(frame.code))

        if self.closure_mailbox is not None:
            frame.emit(OP_STORE_V, captures.slot, self.closure_mailbox)
        if not tail:
            return self.invoke(frame, procedure.slot, values)
        request = frame.allocate()
        frame.emit(OP_STORE, procedure.slot, request)
        frame.emit(OP_STORE, self.zero, advance(request, 1))
        frame.emit(OP_STORE, self.one, advance(request, 2))
        self.stage(frame, values)
        frame.emit(OP_RETURN, request)
        return None

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

    def empty_list(self):
        return Value(self.program.tagged_literal('__qslisp_null', 0, 'null'), 'null')

    def make_list(self, frame, items, location):
        result = self.empty_list()
        for item in reversed(items):
            result = self.make_pair(frame, item, result, location)
        return result

    def make_pair(self, frame, head, tail, location):
        message = self.program.message(f'{location}: pair heap exhausted ({self.heap.capacity} cells)\n')
        result = self.heap.call(frame, 'cons', [head.slot, tail.slot, message])
        return Value(result, 'pair')

    def append_list(self, frame, prefix, tail, location, diagnostic):
        if prefix.kind == 'null':
            return tail
        if prefix.kind not in ('unknown', 'pair'):
            raise CompileError(location, diagnostic)
        bad_list = self.program.message(f'{location}: {diagnostic}\n')
        no_space = self.program.message(f'{location}: pair heap exhausted ({self.heap.capacity} cells)\n')
        result = self.heap.call(frame, 'append', [prefix.slot, tail.slot, bad_list, no_space])
        return Value(result, 'unknown' if prefix.kind == 'unknown' else 'pair')

    def build_list(self, frame, name, args, environment):
        if not args:
            return self.empty_list()
        prefixes, tail = args[:-1], args[-1]
        copies = [name == 'append' or (
            isinstance(node.value, tuple) and bool(node.value) and node.value[0].value == SPLICE)
            for node in prefixes]
        inputs = [node.value[1] if copy and name == BUILD else node for node, copy in zip(prefixes, copies)]
        items = self.values(frame, (*inputs, tail), environment)
        result = items.pop()
        for node, copy in reversed(tuple(zip(prefixes, copies))):
            value = items.pop()
            if copy:
                diagnostic = ('unquote-splicing expects a proper list' if name == BUILD
                              else 'append expects proper lists before its final argument')
                result = self.append_list(frame, value, result, node.location, diagnostic)
            else:
                result = self.make_pair(frame, value, result, node.location)
        return result

    def quoted(self, frame, datum, environment):
        value = datum.value
        if isinstance(value, tuple):
            head, tail_datum = split_dotted(datum)
            tail = self.empty_list() if tail_datum is None else self.quoted(frame, tail_datum, environment)
            for item in reversed(head):
                tail = self.make_pair(frame, self.quoted(frame, item, environment), tail, item.location)
            return tail
        if isinstance(value, str):
            if value == '.':
                raise CompileError(datum.location, 'unexpected dotted-list marker')
            return self.symbol_literal(value)
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

    def symbol_literal(self, name):
        name_id = self.program.string(name)
        slot = self.program.tagged_literal(f'__qslisp_symbol_{name_id}', name_id, 'symbol')
        return Value(slot, 'symbol')

    def record_type(self, frame, value, name, location):
        result = self.tagged(frame, 'boolean')
        frame.emit(OP_EQ, advance(value.slot, 1), self.program.constant(TAGS['record']), result.slot)
        fail = frame.emit(OP_IFNOT, result.slot)
        pair = self.retag(frame, value, 'pair')
        message = self.program.message(f'{location}: invalid record\n')
        schema = self.heap.call(frame, 'car', [pair.slot, message])
        frame.emit(OP_EQ_ENT, schema, self.symbol_literal(name).slot, result.slot)
        frame.patch(fail, 2, len(frame.code))
        return result

    def check_field_type(self, frame, value, kind, field, record):
        if kind == 'any':
            return
        if kind == 'list':
            valid = self.proper_list(frame, value, record.location).slot
        elif kind in self.records:
            valid = self.record_type(frame, value, kind, record.location).slot
        else:
            valid = frame.allocate(1)
            frame.emit(OP_EQ, advance(value.slot, 1), self.program.constant(TAGS[kind]), valid)
            if kind == 'procedure' and self.closure_mailbox is not None:
                closed = frame.allocate(1)
                frame.emit(OP_EQ, advance(value.slot, 1), self.program.constant(TAGS['closure']), closed)
                frame.emit(OP_OR, valid, closed, valid)
        self.heap.guard(frame, valid, self.program.message(
            f'{record.location}: {record.name}.{field} expects {kind}\n'))

    def field_value(self, slot, kind):
        if kind in self.records:
            return Value(slot, 'record', schema=kind)
        return Value(slot, kind if kind not in ('any', 'list', 'procedure') else 'unknown')

    def record_operation(self, frame, name, args, environment):
        record = self.records[args[0].value]
        if name == '#record-create':
            items = self.values(frame, args[1:], environment)
            for (field, kind), value in zip(record.fields, items):
                self.check_field_type(frame, value, kind, field, record)
            fields = self.make_list(frame, items, record.location)
            pair = self.make_pair(frame, self.symbol_literal(record.name), fields, record.location)
            return self.retag(frame, pair, 'record')
        value = self.expression(frame, args[1], environment)
        correct = self.record_type(frame, value, record.name, record.location)
        if name == '#record-test':
            return correct
        message = self.program.message(f'{record.location}: expected a {record.name} record\n')
        self.heap.guard(frame, correct.slot, message)
        pair = self.retag(frame, value, 'pair')
        fields = self.heap.call(frame, 'cdr', [pair.slot, message])
        index = int(args[2].value)
        for _ in range(index):
            fields = self.heap.call(frame, 'cdr', [fields, message])
        slot = self.heap.call(frame, 'car', [fields, message])
        return self.field_value(slot, record.fields[index][1])

    def match_branch(self, frame, args, environment, *, function=None):
        plan, success, failure = args
        scope = environment.copy()
        misses = []
        result = frame.allocate() if function is None else None
        words = frame.words  # Checks and bindings are dead once this clause is decided.
        for check in plan.value:
            name, expression = check.value
            value = self.expression(frame, expression, scope)
            if name.value is False:
                misses.append(frame.emit(OP_IF, self.false_test(frame, value)))
            else:
                scope[name.value] = value
        if function is not None:
            self.tail_expression(frame, success, scope, function)
        else:
            yes = self.expression(frame, success, scope)
            frame.emit(OP_STORE_V, yes.slot, result)
            done = frame.emit(OP_GOTO)
        frame.release(words)
        for branch in misses:
            frame.patch(branch, 2, len(frame.code))
        if function is not None:
            self.tail_expression(frame, failure, environment, function)
            return None
        no = self.expression(frame, failure, environment)
        frame.emit(OP_STORE_V, no.slot, result)
        frame.release(words)
        frame.patch(done, 1, len(frame.code))
        return Value(result, yes.kind if yes.kind == no.kind else 'unknown',
                     schema=yes.schema if yes.schema == no.schema else None)

    def engine_string(self, name, literal, kind):
        if not isinstance(literal.value, StringLiteral):
            raise CompileError(literal.location, f'{name} requires a string literal here')
        text = literal.value.text
        encoded = text.encode('utf-8')
        if name in ('quake:dprint', 'quake:error', 'quake:centerprint', 'quake:client-command') and len(encoded) > 255:
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

    def box_vector(self, frame, raw, location):
        coordinates = []
        for i in range(3):
            scalar = self.tagged(frame, 'number')
            frame.emit(OP_STORE, advance(raw, i), scalar.slot)
            coordinates.append(scalar)
        x, y, z = coordinates
        tail = self.make_pair(frame, y, z, location)
        storage = self.make_pair(frame, x, tail, location)
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
            return result if vector else self.box_vector(frame, result, node.location)
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
        frame.emit(OP_STORE, entity, self_slot)
        frame.emit(OP_STORE, other, other_slot)
        frame.emit(OP_CALL0, reference)
        frame.emit(OP_STORE, saved_self, self_slot)
        frame.emit(OP_STORE, saved_other, other_slot)
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
            return result
        return Value(self.zero, 'number')

    def view_message(self, frame, node, name, args, environment):
        angles = name == 'quake:set-view-angles!'
        if len(args) != (4 if angles else 2):
            raise CompileError(node.location, f'{name} requires a client and ' +
                               ('pitch, yaw, and roll' if angles else 'viewpoint'))
        client = self.entity(frame, args[0], environment)
        if angles:
            payload = []
            for arg in args[1:]:
                value = self.expression(frame, arg, environment)
                self.number(frame, value, arg)
                payload.append(value.slot)
        else:
            payload = [self.entity(frame, args[1], environment)]
        recipient = self.program.names['msg_entity']
        previous = frame.allocate(1)
        frame.emit(OP_STORE, recipient, previous)
        frame.emit(OP_STORE, client, recipient)
        # NetQuake view messages start with a service byte, then three
        # WriteAngles for svc_setangle or a WriteEntity for svc_setview.
        frame.emit(OP_STORE, self.one, 4)  # MSG_ONE
        frame.emit(OP_STORE, self.program.constant(10 if angles else 5), 7)
        frame.emit(OP_CALL0 + 2, self.program.builtin('__qslisp_builtin_52', 52, 2))
        writer = 57 if angles else 59
        for value in payload:
            frame.emit(OP_STORE, self.one, 4)
            frame.emit(OP_STORE, value, 7)
            frame.emit(OP_CALL0 + 2, self.program.builtin(f'__qslisp_builtin_{writer}', writer, 2))
        frame.emit(OP_STORE, previous, recipient)
        return Value(self.zero, 'number')

    def beam(self, frame, node, args, environment):
        if len(args) != 3:
            raise CompileError(node.location, 'quake:beam requires an entity, start, and end')
        source = self.entity(frame, args[0], environment)
        start, end = (self.vector(frame, arg, environment) for arg in args[1:])
        # svc_temp_entity TE_BEAM uses one entity number and six stock coordinates.
        payload = [(52, self.program.constant(23)), (52, self.program.constant(13)), (59, source)]
        payload.extend((56, advance(vector, i)) for vector in (start, end) for i in range(3))
        for writer, slot in payload:
            frame.emit(OP_STORE, self.zero, 4)  # MSG_BROADCAST
            frame.emit(OP_STORE, slot, 7)
            frame.emit(OP_CALL0 + 2, self.program.builtin(f'__qslisp_builtin_{writer}', writer, 2))
        return Value(self.zero, 'number')

    def expression(self, frame, node, environment):
        with frame.at(node.location):
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
        if name == 'match':
            return self.expression(frame, self.match.expand(args, node.location), environment)
        if name == '#match-value':
            return Value(self.expression(frame, args[0], environment).slot)
        if name == '#match-branch':
            return self.match_branch(frame, args, environment)
        if name in ('#record-create', '#record-test', '#record-read'):
            return self.record_operation(frame, name, args, environment)
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
        if name in ('unquote', 'unquote-splicing'):
            raise CompileError(node.location, f'{name} requires an enclosing quasiquote')
        if name in (BUILD, 'append'):
            return self.build_list(frame, name, args, environment)
        if name == 'list':
            items = self.values(frame, args, environment)
            return self.make_list(frame, items, node.location)
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
        if name in ('quake:set-view', 'quake:set-view-angles!'):
            return self.view_message(frame, node, name, args, environment)
        if name == 'quake:beam':
            return self.beam(frame, node, args, environment)
        if name == 'quake:dprint-number':
            if len(args) != 1:
                raise CompileError(node.location, 'quake:dprint-number requires one number')
            value = self.expression(frame, args[0], environment)
            self.number(frame, value, args[0])
            formatted = self.program.builtin('__qslisp_builtin_26', 26, 1)
            printer = self.program.builtin('__qslisp_builtin_25', 25, 1)
            frame.emit(OP_STORE, value.slot, 4)
            frame.emit(OP_CALL0 + 1, formatted)
            frame.emit(OP_STORE, 1, 4)
            frame.emit(OP_CALL0 + 1, printer)
            return Value(self.zero, 'number')
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
            return self.box_vector(frame, self.vector(frame, node, environment), node.location)
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
            # The test is dead once branched on, and only one arm runs: both
            # arms share the slots after the result.
            words = frame.words
            condition = self.expression(frame, args[0], environment)
            to_else = frame.emit(OP_IF, self.false_test(frame, condition))
            frame.release(words)
            result = frame.allocate()
            words = frame.words
            yes = self.expression(frame, args[1], environment)
            frame.emit(OP_STORE_V, yes.slot, result)
            frame.release(words)
            to_end = frame.emit(OP_GOTO)
            frame.patch(to_else, 2, len(frame.code))
            no = self.expression(frame, args[2], environment)
            frame.emit(OP_STORE_V, no.slot, result)
            frame.release(words)
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
            return self.make_pair(frame, *values, node.location)
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
        result = self.call(frame, function, values)
        if name in self.constructors:
            return self.field_value(result.slot, self.constructors[name].name)
        if name in self.getters:
            return self.field_value(result.slot, self.getters[name])
        return result


def compile_source(source, filename='<input>', *, heap_pairs=512):
    return Compiler(load_forms(source, filename), filename, heap_pairs=heap_pairs).compile()
