"""S-expression reader with source locations and a deliberately small syntax."""
from dataclasses import dataclass
import math
import re


@dataclass(frozen=True)
class Location:
    filename: str
    line: int
    column: int

    def __str__(self):
        return f'{self.filename}:{self.line}:{self.column}'


class CompileError(ValueError):
    def __init__(self, location, message):
        super().__init__(f'{location}: {message}')


@dataclass(frozen=True)
class Node:
    value: object
    location: Location


@dataclass(frozen=True)
class StringLiteral:
    text: str


NUMBER = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z')
IDENTIFIER = re.compile(r'[a-zA-Z_!$%&*/:<=>?^~+\-][a-zA-Z0-9_!$%&*/:<=>?^~+.\-]*\Z')
STRING_TOKEN = re.compile(r'"(?:[^"\\\r\n]|\\[^\r\n])*"')
STRING_ESCAPE = re.compile(r'\\(.)')
STRING_ESCAPES = {'"': '"', '\\': '\\', 'n': '\n', 'r': '\r', 't': '\t'}


def decode_string(token, location):
    def unescape(match):
        code = match[1]
        if code not in STRING_ESCAPES:
            raise CompileError(location, f'unsupported string escape {match[0]!r}')
        return STRING_ESCAPES[code]

    text = STRING_ESCAPE.sub(unescape, token[1:-1])
    if '\0' in text:
        raise CompileError(location, 'string literals cannot contain a NUL byte')
    return StringLiteral(text)


def read(source, filename='<input>'):
    tokens = []
    offset, line, column = 0, 1, 1
    while offset < len(source):
        char = source[offset]
        if char.isspace():
            if char == '\n':
                line, column = line + 1, 1
            else:
                column += 1
            offset += 1
            continue
        if char == ';':
            while offset < len(source) and source[offset] != '\n':
                offset += 1
                column += 1
            continue
        location = Location(filename, line, column)
        if char == '"':
            match = STRING_TOKEN.match(source, offset)
            if match is None:
                raise CompileError(location, 'unterminated string literal')
            tokens.append((decode_string(match[0], location), location))
            column += match.end() - offset
            offset = match.end()
            continue
        if char in "()'":
            tokens.append((char, location))
            offset += 1
            column += 1
            continue
        start = offset
        while offset < len(source) and not source[offset].isspace() and source[offset] not in "();'\"":
            offset += 1
            column += 1
        tokens.append((source[start:offset], location))

    cursor = 0

    def datum(depth=0):
        nonlocal cursor
        token, location = tokens[cursor]
        cursor += 1
        if depth > 150:
            raise CompileError(location, 'source nesting limit exceeded')
        if isinstance(token, StringLiteral):
            return Node(token, location)
        if token == '(':
            items = []
            while cursor < len(tokens) and tokens[cursor][0] != ')':
                items.append(datum(depth + 1))
            if cursor == len(tokens):
                raise CompileError(location, 'unclosed parenthesis')
            cursor += 1
            return Node(tuple(items), location)
        if token == ')':
            raise CompileError(location, 'unexpected closing parenthesis')
        if token == "'":
            if cursor == len(tokens):
                raise CompileError(location, 'expected a datum after quote')
            return Node((Node('quote', location), datum(depth + 1)), location)
        if token in ('#t', '#f'):
            return Node(token == '#t', location)
        if token in ('.', '...'):
            return Node(token, location)
        if NUMBER.fullmatch(token):
            value = float(token)
            if not math.isfinite(value):
                raise CompileError(location, 'numeric literal is outside the finite float32 range')
            return Node(value, location)
        if not IDENTIFIER.fullmatch(token):
            raise CompileError(location, f'unsupported token {token!r}')
        return Node(token, location)

    forms = []
    while cursor < len(tokens):
        forms.append(datum())
    return forms
