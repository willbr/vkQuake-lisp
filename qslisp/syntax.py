"""Lower derived forms to the core expressions shared by both call paths."""
from .reader import CompileError, Node

DERIVED_FORMS = {'and', 'or', 'when', 'cond', 'let*'}


class DerivedForms:
    def __init__(self):
        self.temporary = 0

    def expand(self, name, args, location):
        def atom(value):
            return Node(value, location)

        def form(head, *items):
            return Node((atom(head), *items), location)

        def binding(value, body):
            # The reader rejects this prefix, so the generated name cannot
            # capture or be shadowed by a source identifier.
            self.temporary += 1
            temp = atom(f'#temporary-{self.temporary}')
            return form('let', atom((atom((temp, value)),)), body(temp))

        false = atom(False)
        if name == 'when':
            if len(args) < 2:
                raise CompileError(location, 'when requires a condition and body')
            return form('if', args[0], form('begin', *args[1:]), false)
        if name == 'let*':
            if len(args) < 2 or not isinstance(args[0].value, tuple):
                raise CompileError(location, 'let* requires a binding list and body')
            result = form('begin', *args[1:])
            for entry in reversed(args[0].value):
                result = form('let', atom((entry,)), result)
            return result
        if name in ('and', 'or'):
            if not args:
                return atom(name == 'and')
            result = args[-1]
            for test in reversed(args[:-1]):
                if name == 'and':
                    result = form('if', test, result, false)
                else:
                    result = binding(test, lambda temp: form('if', temp, temp, result))
            return result

        result = false
        for index, clause in reversed(tuple(enumerate(args))):
            if not isinstance(clause.value, tuple) or not clause.value:
                raise CompileError(clause.location, 'cond requires nonempty clauses')
            test, *body = clause.value
            if test.value == 'else':
                if index != len(args) - 1 or not body:
                    raise CompileError(test.location, 'cond else must be the final clause and have a body')
                result = form('begin', *body)
            elif not body:
                result = binding(test, lambda temp: form('if', temp, temp, result))
            elif body[0].value == '=>':
                if len(body) != 2:
                    raise CompileError(clause.location, 'cond => requires one procedure')
                result = binding(test, lambda temp: form('if', temp, atom((body[1], temp)), result))
            else:
                result = form('if', test, form('begin', *body), result)
        return result
