"""Expand top-level syntax-rules before lexical or heap analysis."""
from dataclasses import dataclass

from .reader import CompileError, Node


@dataclass(frozen=True)
class Introduced:
    name: str


def identifier(node):
    return node.value.name if isinstance(node.value, Introduced) else node.value


def form_name(node):
    return identifier(node.value[0]) if isinstance(node.value, tuple) and node.value else None


def segments(items):
    index = 0
    while index < len(items):
        node = items[index]
        if node.value == '...':
            raise CompileError(node.location, 'ellipsis requires a preceding pattern or template')
        repeat = index + 1 < len(items) and items[index + 1].value == '...'
        yield node, repeat
        index += 2 if repeat else 1


@dataclass(frozen=True)
class Rule:
    pattern: Node
    template: Node
    literals: frozenset
    ranks: dict

    def variables(self, node):
        if isinstance(node.value, tuple):
            for child in node.value:
                yield from self.variables(child)
        elif isinstance(node.value, str) and node.value in self.ranks:
            yield node.value

    def match(self, form):
        captures = {name: {} for name in self.ranks}
        lengths = {}

        def capture(pattern, datum, path):
            value = pattern.value
            if isinstance(value, tuple):
                if not isinstance(datum.value, tuple):
                    return False
                patterns = tuple(segments(value))
                repetitions = sum(repeat for _, repeat in patterns)
                fixed = len(patterns) - repetitions
                size = len(datum.value)
                if size < fixed or (repetitions == 0 and size != fixed):
                    return False
                offset = 0
                for child, repeat in patterns:
                    if repeat:
                        for name in self.variables(child):
                            lengths[name, path] = size - fixed
                        for i in range(size - fixed):
                            if not capture(child, datum.value[offset], (*path, i)):
                                return False
                            offset += 1
                    else:
                        if not capture(child, datum.value[offset], path):
                            return False
                        offset += 1
                return True
            if value == '_':
                return True
            if isinstance(value, str):
                if value in self.literals:
                    return identifier(datum) == value
                captures[value][path] = datum
                return True
            return type(value) is type(datum.value) and value == datum.value

        return (captures, lengths) if capture(self.pattern, form, ()) else None

    def expand(self, match, invocation):
        captures, lengths = match

        def render(node, path):
            if isinstance(node.value, tuple):
                items = []
                for child, repeat in segments(node.value):
                    if not repeat:
                        items.append(render(child, path))
                        continue
                    names = {name for name in self.variables(child) if self.ranks[name] > len(path)}
                    if not names:
                        raise CompileError(child.location, 'template ellipsis needs a repeated pattern variable')
                    counts = {lengths[name, path] for name in names}
                    if len(counts) != 1:
                        raise CompileError(invocation, 'repeated pattern variables have different lengths')
                    items.extend(render(child, (*path, i)) for i in range(counts.pop()))
                return Node(tuple(items), invocation)
            if isinstance(node.value, str):
                if node.value in self.ranks:
                    rank = self.ranks[node.value]
                    if rank > len(path):
                        raise CompileError(node.location, f'{node.value} needs a template ellipsis')
                    return captures[node.value][path[:rank]]
                return Node(Introduced(node.value), invocation)
            return Node(node.value, invocation)

        return render(self.template, ())


class Macros:
    def __init__(self):
        self.rules = {}
        self.serial = 0

    def define(self, node):
        parts = node.value
        if len(parts) != 3 or not isinstance(parts[1].value, str) or form_name(parts[2]) != 'syntax-rules':
            raise CompileError(node.location, 'define-syntax requires a name and syntax-rules')
        name = parts[1].value
        if name in self.rules:
            raise CompileError(parts[1].location, f'duplicate macro {name}')
        spec = parts[2].value
        if len(spec) < 3 or not isinstance(spec[1].value, tuple) or any(
                not isinstance(item.value, str) for item in spec[1].value):
            raise CompileError(parts[2].location, 'syntax-rules requires a literal identifier list and rules')
        literals = frozenset([name, *(item.value for item in spec[1].value)])
        rules = []
        for clause in spec[2:]:
            if not isinstance(clause.value, tuple) or len(clause.value) != 2 or form_name(clause.value[0]) not in (name, '_'):
                raise CompileError(clause.location, 'macro rule requires (pattern template) with the macro as pattern head')
            pattern, template = clause.value
            ranks = {}

            def collect(node, rank):
                value = node.value
                if isinstance(value, tuple):
                    children = tuple(segments(value))
                    if sum(repeat for _, repeat in children) > 1:
                        raise CompileError(node.location, 'use at most one repeating pattern per list')
                    for child, repeat in children:
                        collect(child, rank + repeat)
                elif isinstance(value, str) and value != '_' and value not in literals:
                    if value in ranks:
                        raise CompileError(node.location, f'duplicate pattern variable {value}')
                    ranks[value] = rank

            collect(pattern, 0)
            rules.append(Rule(pattern, template, literals, ranks))
        self.rules[name] = tuple(rules)

    def hygienic_locals(self, node, scope=None):
        scope = {} if scope is None else scope

        def bindings(names, environment):
            extended = environment.copy()
            converted = []
            for name in names:
                if isinstance(name.value, Introduced):
                    self.serial += 1
                    label = f'#macro-{self.serial}-{name.value.name}'
                    extended[name.value.name] = label
                    converted.append(Node(label, name.location))
                else:
                    converted.append(name)
            return tuple(converted), extended

        value = node.value
        if isinstance(value, Introduced):
            return Node(scope.get(value.name, value.name), node.location)
        if not isinstance(value, tuple) or not value:
            return node
        head = form_name(node)
        if head == 'quote':
            # Quoted data contains symbols rather than lexical references.
            def quoted(item):
                contents = item.value
                if isinstance(contents, tuple):
                    return Node(tuple(quoted(child) for child in contents), item.location)
                return Node(identifier(item), item.location)
            return quoted(node)
        if head in ('define', 'lambda') and len(value) >= 3 and isinstance(value[1].value, tuple):
            prefix = value[1].value[:1] if head == 'define' else ()
            args = value[1].value[len(prefix):]
            names, extended = bindings(args, scope)
            signature = Node((*tuple(self.hygienic_locals(name, {}) for name in prefix), *names), value[1].location)
            return Node((self.hygienic_locals(value[0], scope), signature,
                         *(self.hygienic_locals(child, extended) for child in value[2:])), node.location)
        if head in ('let', 'let*', 'letrec') and len(value) >= 3:
            named = head == 'let' and isinstance(identifier(value[1]), str)
            index = 2 if named else 1
            entries = value[index].value
            if isinstance(entries, tuple) and all(isinstance(entry.value, tuple) and len(entry.value) == 2 for entry in entries):
                names = [entry.value[0] for entry in entries]
                loop, extended = bindings((value[1],), scope) if named else ((), scope)
                result = []
                if head == 'let*':
                    for entry in entries:
                        initial = self.hygienic_locals(entry.value[1], extended)
                        binding, extended = bindings((entry.value[0],), extended)
                        result.append(Node((binding[0], initial), entry.location))
                else:
                    targets, extended = bindings(names, extended)
                    initial_scope = extended if head == 'letrec' else scope
                    result = [Node((label, self.hygienic_locals(entry.value[1], initial_scope)), entry.location)
                              for label, entry in zip(targets, entries)]
                return Node((self.hygienic_locals(value[0], scope), *loop, Node(tuple(result), value[index].location),
                             *(self.hygienic_locals(child, extended) for child in value[index+1:])), node.location)
        return Node(tuple(self.hygienic_locals(child, scope) for child in value), node.location)

    def invocation(self, node):
        name = form_name(node)
        if not isinstance(name, str) or name not in self.rules:
            return None
        for rule in self.rules[name]:
            match = rule.match(node)
            if match is not None:
                return self.hygienic_locals(rule.expand(match, node.location))
        raise CompileError(node.location, f'no matching rule for {name}')

    def expression(self, node, depth=0):
        if depth > 150:
            raise CompileError(node.location, 'macro expansion nesting limit exceeded')
        expanded = self.invocation(node)
        if expanded is not None:
            return self.expression(expanded, depth + 1)
        if not isinstance(node.value, tuple) or not node.value or form_name(node) == 'quote':
            return node
        head = form_name(node)
        visit = lambda child: self.expression(child, depth)
        if head in ('define', 'lambda') and len(node.value) >= 2:
            return Node((*node.value[:2], *(visit(child) for child in node.value[2:])), node.location)
        if head == 'define-record':
            return node
        if head == 'match' and len(node.value) >= 2:
            clauses = (Node((child.value[0], *(visit(part) for part in child.value[1:])), child.location)
                       if isinstance(child.value, tuple) and child.value else child for child in node.value[2:])
            return Node((node.value[0], visit(node.value[1]), *clauses), node.location)
        if head in ('let', 'let*', 'letrec') and len(node.value) >= 3:
            index = 2 if head == 'let' and isinstance(node.value[1].value, str) else 1
            entries = node.value[index]
            if isinstance(entries.value, tuple) and all(isinstance(entry.value, tuple) and len(entry.value) == 2
                                                       for entry in entries.value):
                converted = tuple(Node((entry.value[0], visit(entry.value[1])), entry.location) for entry in entries.value)
                return Node((*node.value[:index], Node(converted, entries.location),
                             *(visit(child) for child in node.value[index+1:])), node.location)
        if head == 'cond':
            return Node((node.value[0], *(Node(tuple(visit(part) for part in child.value), child.location)
                                         if isinstance(child.value, tuple) else child for child in node.value[1:])), node.location)
        return Node(tuple(visit(child) for child in node.value), node.location)

    def top(self, node, depth=0):
        if depth > 150:
            raise CompileError(node.location, 'macro expansion nesting limit exceeded')
        expanded = self.invocation(node)
        if expanded is not None:
            yield from self.top(expanded, depth + 1)
        elif form_name(node) == 'define-syntax':
            self.define(node)
        elif form_name(node) == 'begin':
            for form in node.value[1:]:
                yield from self.top(form, depth)
        else:
            yield self.expression(node, depth)

    def program(self, forms):
        return [item for form in forms for item in self.top(form)]
