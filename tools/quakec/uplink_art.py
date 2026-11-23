"""Original indexed fixtures and lettering for the Relay Annex."""
from functools import partial

SIGNS = {
    'yard_bikes': ('BIKES', 237),
    'freight_jump': ('JUMP', 235),
    'flood_valve': ('VALVE', 246),
    'sump_pumps': ('PUMPS', 237),
    'switch_relay': ('RELAY', 241),
    'gantry_array': ('ARRAY', 244),
    'roof_exit': ('EXIT', 254),
    'lift_call': ('CALL', 244),
    'east_relay': ('EAST', 244),
    'west_relay': ('WEST', 244),
}

# Five columns, seven rows, with the low bit at the right side of each row.
LETTERS = {
    'A': (14, 17, 17, 31, 17, 17, 17),
    'B': (30, 17, 17, 30, 17, 17, 30),
    'C': (15, 16, 16, 16, 16, 16, 15),
    'E': (31, 16, 16, 30, 16, 16, 31),
    'I': (14, 4, 4, 4, 4, 4, 14),
    'J': (7, 2, 2, 2, 18, 18, 12),
    'K': (17, 18, 20, 24, 20, 18, 17),
    'L': (16, 16, 16, 16, 16, 16, 31),
    'M': (17, 27, 21, 21, 17, 17, 17),
    'P': (30, 17, 17, 30, 16, 16, 16),
    'R': (30, 17, 17, 30, 20, 18, 17),
    'S': (15, 16, 16, 14, 1, 1, 30),
    'T': (31, 4, 4, 4, 4, 4, 4),
    'U': (17, 17, 17, 17, 17, 17, 14),
    'V': (17, 17, 17, 17, 17, 10, 4),
    'W': (17, 17, 17, 21, 21, 27, 17),
    'X': (17, 17, 10, 4, 10, 17, 17),
    'Y': (17, 17, 10, 4, 4, 4, 4),
}


def sign(word, ink, x, y):
    if min(x, y, 63 - x, 63 - y) < 3:
        return 8
    if y in (8, 9, 54, 55) and 4 <= x <= 59:
        return ink
    left = (64 - (12 * len(word) - 2)) // 2
    if left <= x < 64 - left and 14 <= y < 49:
        char, column = divmod((x - left) // 2, 6)
        if column < 5 and LETTERS[word[char]][(y - 14) // 5] & (16 >> column):
            return ink
    return 17 + ((x * 7 + y * 11) % 43 == 0)


def rib(x, y):
    if y < 4 or y >= 60:
        return 235 if (x + y) % 16 < 8 else 9
    if x % 32 < 2:
        return 3
    if 24 <= y <= 39 and x % 16 in (4, 5):
        return 10
    return 6 + ((x ^ y) % 11 == 0)


def dock_gate(x, y):
    if y in (7, 8, 55, 56):
        return 10
    if 9 <= y <= 19:
        return 108 if (x - y) % 16 < 8 else 5
    if x in (0, 31, 32, 63) or y in (0, 63):
        return 4
    if x % 32 in (5, 6, 25, 26) and y in (25, 49):
        return 238
    return 7 + ((x * 13 + y * 17) % 37 == 0)


def fixtures():
    for name, (word, ink) in SIGNS.items():
        yield name, partial(sign, word, ink)
    yield 'annex_rib', rib
    yield 'annex_lamp', lambda x, y: 246 if 7 <= y <= 55 and x % 16 < 13 else 7
    yield 'annex_gate', dock_gate
