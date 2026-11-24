"""Original indexed signs and Lisp Machine panels for the Lambda Lab and AI Winter."""
from functools import partial

from uplink_art import sign

SIGNS = {
    'amb_sign': ('AMB', 244),
    'cons_sign': ('CONS', 241),
    'tail_sign': ('TAIL', 237),
    'quine_sign': ('QUINE', 254),
    'eval_sign': ('EVAL', 251),
    'winter_sign': ('LAB', 246),
}


def console(x, y):
    """A tall Lisp Machine display: a dark screen of green text lines."""
    if min(x, y, 63 - x) < 3 or y >= 60:
        return 4
    if 6 <= x <= 57 and 6 <= y <= 47:
        line, column = (y - 8) // 5, x - 8
        if (y - 8) % 5 < 3 and 0 <= column < 46 and (column * 7 + line * 13) % 9 < 5 + line % 3:
            return 250 if line == 0 else 186
        return 1
    return 6 + ((x + y) % 9 == 0)


def keys(x, y):
    """Rows of keycaps with the wide space-cadet shift keys."""
    row, inner = divmod(y, 16)
    width = 16 if row == 3 and 16 <= x < 48 else 8
    key = x % width
    if inner < 2 or inner > 13 or key < 1 or key == width - 1:
        return 2
    if row == 0 and x // 8 in (0, 7):
        return 104
    return 12 - (inner > 10)


def fixtures():
    for name, (word, ink) in SIGNS.items():
        yield name, partial(sign, word, ink)
    yield 'lisp_console', console
    yield 'lisp_keys', keys
