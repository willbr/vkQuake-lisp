"""Original indexed materials and lettering for the Relay Annex."""
from functools import partial

# Each metal ramp runs from recess to highlight in the stock Quake palette.
DECKS = {
    'yard': ((4, 7, 8, 10), (188, 185, 181, 178), 237, (.47, .55, .48)),
    'freight': ((38, 40, 42, 46), (41, 43, 45, 46), 235, (.40, .47, .67)),
    'flood': ((190, 187, 184, 181), (188, 185, 181, 177), 246, (.35, .58, .51)),
    'sump': ((115, 117, 119, 122), (118, 121, 123, 126), 237, (.65, .44, .29)),
    'switch': ((5, 7, 8, 10), (217, 216, 214, 212), 241, (.40, .53, .70)),
    'gantry': ((163, 162, 161, 160), (186, 184, 180, 177), 244, (.60, .56, .42)),
    'roof': ((6, 8, 10, 12), (39, 42, 44, 46), 254, (.56, .65, .77)),
}

SIGNS = {
    'yard_bikes': ('BIKES', 237),
    'freight_jump': ('JUMP', 235),
    'flood_valve': ('VALVE', 246),
    'sump_pumps': ('PUMPS', 237),
    'switch_relay': ('RELAY', 241),
    'gantry_array': ('ARRAY', 244),
    'roof_exit': ('EXIT', 254),
}

# Five columns, seven rows, with the low bit at the right side of each row.
LETTERS = {
    'A': (14, 17, 17, 31, 17, 17, 17),
    'B': (30, 17, 17, 30, 17, 17, 30),
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
    'X': (17, 17, 10, 4, 10, 17, 17),
    'Y': (17, 17, 10, 4, 4, 4, 4),
}


def deck_plate(metal, x, y):
    edge = min(x % 32, y % 32, 31 - x % 32, 31 - y % 32)
    if edge == 0:
        return metal[0]
    if edge == 1:
        return metal[2]
    if x % 8 in (2, 3) and (y + x // 8 * 4) % 8 in (1, 2, 3):
        return metal[2]
    return metal[1 + ((x * 13 + y * 17) % 37 == 0)]


def bulkhead(metal, accent, x, y):
    edge = min(x, 63 - x)
    if edge < 2 or y in (0, 63):
        return metal[0]
    if edge < 4:
        return metal[2]
    if y in (5, 58) and edge in (5, 6):
        return metal[3]
    if 9 <= y <= 15:
        if 22 <= x <= 41 and y in (11, 12) and x % 6 < 4:
            return accent
        return metal[0]
    if 22 <= y <= 51 and 10 <= x <= 53:
        bevel = min(x - 10, 53 - x, y - 22, 51 - y)
        if bevel == 0:
            return metal[0]
        if bevel == 1:
            return metal[3]
        return metal[1 + ((x * 19 + y * 23) % 29 == 0)]
    return metal[2]


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


def materials():
    for name, (floor, wall, accent, _) in DECKS.items():
        yield f'{name}_deck', partial(deck_plate, floor)
        yield f'{name}_wall', partial(bulkhead, wall, accent)
    for name, (word, ink) in SIGNS.items():
        yield name, partial(sign, word, ink)
    yield 'annex_rib', rib
    yield 'annex_lamp', lambda x, y: 246 if 7 <= y <= 55 and x % 16 < 13 else 7
    yield 'annex_gate', dock_gate
