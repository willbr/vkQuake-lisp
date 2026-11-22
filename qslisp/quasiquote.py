"""Lower quasiquote templates before macro expansion and lexical analysis."""
from .reader import CompileError, Node, split_dotted


QUASIQUOTE_FORMS = ('quasiquote', 'unquote', 'unquote-splicing')
BUILD = '#quasiquote-build'
SPLICE = '#quasiquote-splice'


def expand_quasiquote(form, identifier):
    if len(form.value) != 2:
        raise CompileError(form.location, 'quasiquote requires one datum')

    def call(name, datum, *args):
        return Node((Node(name, datum.location), *args), datum.location)

    def head(datum):
        items = datum.value
        return identifier(items[0]) if isinstance(items, tuple) and items else None

    def operand(datum, name):
        if len(datum.value) != 2:
            raise CompileError(datum.location, f'{name} requires one expression')
        return datum.value[1]

    def elements(datum, items, tail, depth):
        values = []
        for item in items:
            if depth == 1 and head(item) == 'unquote-splicing':
                values.append(call(SPLICE, item, operand(item, 'unquote-splicing')))
            else:
                values.append(lower(item, depth))
        return call(BUILD, datum, *values, lower(tail, depth))

    def lower(datum, depth):
        items = datum.value
        if not isinstance(items, tuple) or not items:
            return call('quote', datum, datum)
        name = head(datum)
        if name in QUASIQUOTE_FORMS:
            argument = operand(datum, name)
            if depth == 1 and name == 'unquote':
                return argument
            if depth == 1 and name == 'unquote-splicing':
                raise CompileError(datum.location, 'unquote-splicing requires a list element position')
            nested_depth = depth + 1 if name == 'quasiquote' else depth - 1
            return elements(datum, (items[0], argument), Node((), datum.location), nested_depth)
        prefix, tail = split_dotted(datum, identifier)
        return elements(datum, prefix, tail or Node((), datum.location), depth)

    return lower(form.value[1], 1)
