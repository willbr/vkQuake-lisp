"""Read source files and their top-level imports into one program."""
from pathlib import Path

from .reader import CompileError, Node, StringLiteral, read


def load_forms(source, filename):
    loaded = set()
    active = {Path(filename).resolve()}

    def visit(contents, name):
        for node in read(contents, name):
            form = node.value
            if isinstance(form, tuple) and form and form[0].value == 'define-source-printer':
                yield source_printer(node, name)
                continue
            if not isinstance(form, tuple) or not form or form[0].value != 'import':
                yield node
                continue
            if len(form) == 1:
                raise CompileError(node.location, 'import requires at least one source path')
            for arg in form[1:]:
                if not isinstance(arg.value, StringLiteral) or not arg.value.text:
                    raise CompileError(arg.location, 'import paths must be nonempty string literals')
                path = (Path(name).parent / arg.value.text).resolve()
                if path in active:
                    raise CompileError(arg.location, f'cyclic import of {path}')
                if path in loaded:
                    continue
                try:
                    imported = path.read_text(encoding='utf-8')
                except (OSError, UnicodeError) as error:
                    raise CompileError(arg.location, f'cannot read import {path}: {error}') from error
                active.add(path)
                yield from visit(imported, str(path))
                active.remove(path)
                loaded.add(path)

    return list(visit(source, filename))


def source_printer(node, name):
    """Expand (define-source-printer printer "file.scm") into a function that
    broadcasts each line of that file with stock bprint. The text is read at
    compile time; stock QuakeC has no string concatenation to build it later."""
    form = node.value
    if (len(form) != 3 or not isinstance(form[1].value, str)
            or not isinstance(form[2].value, StringLiteral) or not form[2].value.text):
        raise CompileError(node.location, 'define-source-printer requires a name and a source path')
    path = (Path(name).parent / form[2].value.text).resolve()
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError) as error:
        raise CompileError(form[2].location, f'cannot read {path}: {error}') from error
    location = node.location
    calls = []
    for line in lines or ['']:
        if len(line.encode('utf-8')) > 254:
            raise CompileError(form[2].location, f'{path.name} has a line over the stock 255-byte print limit')
        calls.append(Node((Node('quake:bprint', location), Node(StringLiteral(line + '\n'), location)), location))
    header = Node((form[1],), location)
    return Node((Node('define', location), header, *calls), location)
