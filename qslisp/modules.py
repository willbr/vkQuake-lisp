"""Read source files and their top-level imports into one program."""
from pathlib import Path

from .reader import CompileError, StringLiteral, read


def load_forms(source, filename):
    loaded = set()
    active = {Path(filename).resolve()}

    def visit(contents, name):
        for node in read(contents, name):
            form = node.value
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
