"""Record declarations and pattern matching lowered to ordinary Lisp forms."""
from dataclasses import dataclass

from .reader import CompileError, Node, StringLiteral


@dataclass(frozen=True)
class Record:
    name: str
    fields: tuple
    location: object

    def definitions(self):
        loc = self.location

        def atom(value):
            return Node(value, loc)

        def function(name, parameters, operation, *operands):
            signature = atom(tuple(atom(word) for word in (name, *parameters)))
            body = atom(tuple(atom(word) for word in (operation, self.name, *operands)))
            return atom((atom('define'), signature, body))

        parameters = tuple(f'#record-field-{i}' for i in range(len(self.fields)))
        yield function(f'make-{self.name}', parameters, '#record-create', *parameters)
        yield function(f'{self.name}?', ('#record-value',), '#record-test', '#record-value')
        for index, (field, _) in enumerate(self.fields):
            yield function(f'{self.name}-{field}', ('#record-value',), '#record-read', '#record-value', float(index))


def record_definitions(forms, field_types):
    records, ordered = {}, []
    for node in forms:
        form = node.value
        if not isinstance(form, tuple) or not form or form[0].value != 'define-record':
            ordered.append(node)
            continue
        if len(form) < 2 or not isinstance(form[1].value, str):
            raise CompileError(node.location, 'define-record requires a name and field declarations')
        name = form[1].value
        if name in records or name in field_types:
            raise CompileError(form[1].location, f'duplicate or reserved record name {name}')
        if len(form) > 10:
            raise CompileError(node.location, 'stock VM supports at most eight record fields')
        fields = []
        for declaration in form[2:]:
            if not isinstance(declaration.value, tuple) or len(declaration.value) != 2 or any(
                    not isinstance(part.value, str) for part in declaration.value):
                raise CompileError(declaration.location, 'record field requires (name type)')
            field, kind = (part.value for part in declaration.value)
            if any(existing == field for existing, _ in fields):
                raise CompileError(declaration.location, f'duplicate record field {field}')
            fields.append((field, kind))
        record = Record(name, tuple(fields), node.location)
        records[name] = record
        ordered.extend(record.definitions())
    for record in records.values():
        for field, kind in record.fields:
            if kind not in field_types and kind not in records:
                raise CompileError(record.location, f'unknown type {kind} for {record.name}.{field}')
    return ordered, records


class Match:
    def __init__(self, records, fresh):
        self.records = records
        self.fresh = fresh

    def expand(self, args, location):
        if len(args) < 2:
            raise CompileError(location, 'match requires a value and at least one clause')

        def atom(value):
            return Node(value, location)

        def call(name, *items):
            return atom((atom(name), *items))

        def helper(name, *items):
            return call(f'#match-call:{name}', *items)

        def bind(name, value, body):
            return call('let', atom((atom((name, value)),)), body)

        def inspect(pattern, value, bindings, checks):
            def nested(part, expression):
                if part.value != '_':
                    name = self.fresh(part.location)
                    checks.append((name, call('#match-value', expression)))
                    inspect(part, name, bindings, checks)

            form = pattern.value
            if isinstance(form, str):
                if form == '_':
                    return
                if form in bindings:
                    raise CompileError(pattern.location, f'duplicate pattern binding {form}')
                bindings[form] = atom((pattern, value))
                return
            if not isinstance(form, tuple) or (form and form[0].value == 'quote'):
                checks.append((None, helper('equal?', value, pattern)))
                return
            if not form:
                checks.append((None, helper('null?', value)))
                return
            head, *parts = form
            if head.value == 'list':
                shape = atom(())
                for part in reversed(parts):
                    shape = call('cons', part, shape)
                inspect(shape, value, bindings, checks)
                return
            if head.value == 'cons' and len(parts) == 2:
                checks.append((None, helper('pair?', value)))
                nested(parts[0], helper('car', value))
                nested(parts[1], helper('cdr', value))
                return
            record = self.records.get(head.value) if isinstance(head.value, str) else None
            if record is None or len(parts) != len(record.fields):
                raise CompileError(pattern.location, 'expected a cons, list, literal, or matching record pattern')
            checks.append((None, helper(f'{record.name}?', value)))
            for part, (field, _) in zip(parts, record.fields):
                nested(part, helper(f'{record.name}-{field}', value))

        value = self.fresh(location)
        result = helper('quake:error', atom(StringLiteral('no matching pattern\n')))
        for index, clause in reversed(tuple(enumerate(args[1:]))):
            if not isinstance(clause.value, tuple) or len(clause.value) < 2:
                raise CompileError(clause.location, 'match clause requires a pattern and body')
            pattern, *body = clause.value
            success = call('begin', *body)
            if pattern.value == 'else':
                if index != len(args) - 2:
                    raise CompileError(pattern.location, 'match else must be the final clause')
                result = success
            else:
                bindings, checks = {}, []
                inspect(pattern, value, bindings, checks)
                success = call('let', atom(tuple(bindings.values())), success) if bindings else success
                plan = atom(tuple(atom((name if name else atom(False), expression)) for name, expression in checks))
                result = call('#match-branch', plan, success, result)
        return bind(value, call('#match-value', args[0]), result)
