#!/usr/bin/env python3
"""Generate the editable Lambda Lab: Lisp lore puzzles for stock Quake."""
import argparse
from pathlib import Path

from map_editor import box, coordinates, quoted, seal

LAB, PIT, UPPER = 0, -256, 768
TRIM = 'relay_trim'
# Cell name, pillar centre, whether a floor exists, and the initial cdr.
CELLS = (
    ('c5', (192, 0), True, 'c1'),
    ('c4', (480, 416), True, 'c2'),
    ('c3', (480, -416), False, 'c4'),
    ('c2', (832, -416), True, 'c3'),
    ('c1', (1104, 0), True, 'c2'),
)
AMB_ROOMS = (
    # Room x range, alcove ys, and the alcove that continues.
    ((1536, 2048), (-160, 0, 160), 160),
    ((2304, 2816), (-160, 0, 160), -160),
)
LIFTS = (('stack-lift', 3200, 0), ('tail-lift', 3392, 1))
GC_NODES = (
    # Name, position on the east wall, platform y, and the authored edge.
    ('gc-root', 3800, 640, 'gc-1'),
    ('gc-1', 3800, 800, 'gc-2'),
    ('gc-2', 3800, 960, ''),
    ('gc-3', 3800, 1120, ''),
    ('gc-4', 3800, 1280, ''),
)


def room(x, xx, y, yy, z, ceiling):
    return (x, y, z), (xx, yy, ceiling)


def entity(classname, origin=None, brushes=(), **keys):
    fields = {'classname': classname, **keys}
    if origin is not None:
        fields['origin'] = coordinates(origin)
    return ('{\n' + ''.join(f'{quoted(key)} {quoted(str(value))}\n' for key, value in fields.items())
            + ''.join(brush.text() for brush in brushes) + '}\n')


def surface(regions):
    def texture(index, axis, positive):
        low, high = regions[index]
        if axis == 2 and not positive:
            return 'lambda_pit' if low[2] == PIT else 'lambda_floor'
        if axis == 2:
            return 'lambda_ceiling'
        return 'lambda_wall'
    return texture


def regions():
    rooms = [
        # Entry hall, the hidden passage, and the Lisp Machine shrine.
        room(-1024, -256, -384, 384, LAB, 256),
        room(-736, -608, -640, -384, LAB, 128),
        room(-928, -416, -1024, -640, LAB, 192),
        # The cons-cell chamber over its pit and the corridor behind the tail door.
        room(-256, 1280, -768, 768, PIT, 512),
        room(1280, 1536, -64, 64, LAB, 128),
    ]
    for (x, xx), alcoves, keep in AMB_ROOMS:
        rooms.append(room(x, xx, -256, 256, LAB, 192))
        for y in alcoves:
            rooms.append(room(xx, xx + 128, y - 32, y + 32, LAB, 128))
        rooms.append(room(xx + 128, xx + 256, keep - 32, keep + 32, LAB, 128))
    rooms += [
        # The lift hall, both shafts, and the boss arena above.
        room(3072, 3584, -384, 384, LAB, 256),
        room(3200, 3328, -64, 64, 256, UPPER),
        room(3392, 3520, -64, 64, 256, UPPER),
        room(3072, 3840, -512, 512, UPPER, UPPER + 320),
        # The collector's conduit room north of the arena, with its exit ledge.
        room(3328, 3584, 512, 528, UPPER, UPPER + 160),
        room(3072, 3840, 528, 1536, UPPER - 256, UPPER + 320),
        room(3328, 3584, 1536, 1792, UPPER, UPPER + 192),
    ]
    for _, x, _ in LIFTS:
        rooms.append(room(x + 2, x + 126, -62, 62, LAB - 8, LAB))
    return rooms


def sign(texture, x, y, z, facing_axis, facing, width=128, height=48):
    low, high = [x, y, z], [x, y, z + height]
    across = 1 - facing_axis
    low[facing_axis] -= 2
    high[facing_axis] += 2
    low[across] -= width // 2
    high[across] += width // 2
    return box(low, high, texture)


def world():
    rooms = regions()
    brushes = list(seal(rooms, surface(rooms)))
    # Balcony from the hall into the chamber, with a bridge to the head cell.
    brushes.append(box((-256, -384, PIT), (0, 384, LAB), 'lambda_floor'))
    brushes.append(box((0, -48, LAB - 16), (96, 48, LAB), TRIM))
    for name, (x, y), floor, _ in CELLS:
        if floor:
            east = 1280 if name == 'c1' else x + 96
            brushes.append(box((x - 96, y - 96, PIT), (east, y + 96, LAB), 'lambda_floor'))
    # Pillars under the lift landings and the conduit room's entry and exit ledges.
    brushes.append(box((3072, 528, UPPER - 256), (3840, 608, UPPER), 'lambda_floor'))
    brushes.append(box((3072, 1440, UPPER - 256), (3840, 1536, UPPER), 'lambda_floor'))
    for (x, xx), alcoves, keep in AMB_ROOMS:
        brushes.append(sign('amb_sign', x + 4, 0, LAB + 120, 0, 1))
    brushes.append(sign('cons_sign', -240, 0, LAB + 150, 0, 1, width=160))
    brushes.append(sign('tail_sign', 3460, -380, LAB + 150, 1, 1))
    brushes.append(sign('quine_sign', -1020, 200, LAB + 96, 0, 1, width=96))
    # The shrine's console wall and keyboard plinth.
    brushes.append(box((-880, -1020, LAB), (-464, -1000, LAB + 160), 'lisp_console'))
    brushes.append(box((-800, -1000, LAB), (-544, -936, LAB + 36), 'lisp_keys'))
    return brushes


def cell_entities():
    for name, (x, y), _, cdr in CELLS:
        keys = {'targetname': name, 'cell-next': cdr}
        if name == 'c5':
            keys['lambda-head'] = 1
        if name == 'c3':
            keys['broken'] = 1
        if name == 'c1':
            keys['target'] = 'tail-door'
        yield entity('lambda_cell', (x, y - 40, LAB + 24), **keys)
        # Each pad stands on the north edge, clear of the walk to the tail door.
        post = box((x - 16, y + 40, LAB), (x + 16, y + 72, LAB + 56), 'lambda_pad')
        yield entity('lambda_pad', brushes=[post], target=name)
        yield entity('light', (x, y, LAB + 160), light=300)


def amb_entities():
    for index, ((x, xx), alcoves, keep) in enumerate(AMB_ROOMS):
        choice = f'amb-{index}'
        yield entity('info_null', ((x + xx) // 2, 0, LAB + 24), targetname=choice)
        yield entity('light', ((x + xx) // 2, 0, LAB + 150), light=350)
        for y in alcoves:
            yield entity('light', (xx + 64, y, LAB + 96), light=150)
            if y == keep:
                continue
            barrier = f'{choice}-{y}'
            yield entity('lambda_barrier', brushes=[box((xx, y - 32, LAB), (xx + 16, y + 32, LAB + 128), 'lambda_door')],
                         targetname=barrier)
            zone = box((xx + 24, y - 32, LAB), (xx + 128, y + 32, LAB + 112), TRIM)
            yield entity('lambda_amb', brushes=[zone], target=barrier, message=choice)


def lift_entities():
    for name, x, tail in LIFTS:
        platform = box((x + 2, -62, LAB - 16), (x + 126, 62, LAB), 'lift_deck')
        yield entity('lambda_lift', brushes=[platform], targetname=name, **{'lambda-tail': tail})
        yield entity('light', (x + 64, 0, LAB + 200), light=300)
        for z in range(LAB + 400, UPPER, 200):
            yield entity('light', (x + 64, 0, z), light=260)


def gc_entities():
    for name, x, y, edge in GC_NODES:
        keys = {'targetname': name}
        if edge:
            keys['target'] = edge
        if name == 'gc-root':
            keys['gc-root'] = 1
        else:
            platform = box((3200, y - 64, UPPER - 16), (3712, y + 64, UPPER), 'gc_platform')
            yield entity('lambda_gc_platform', brushes=[platform], targetname=f'{name}-deck')
            keys['gc-platform'] = f'{name}-deck'
        yield entity('lambda_conduit', (x, y, UPPER + 64), **keys)
        yield entity('light', (3456, y, UPPER + 220), light=320)
    for low, high in (((3072, 528, UPPER), (3840, 608, UPPER + 96)),
                      ((3072, 1440, UPPER), (3840, 1536, UPPER + 96))):
        yield entity('lambda_gc_safe', brushes=[box(low, high, TRIM)])
    yield entity('lambda_sweeper', (3456, 576, UPPER + 32), target='gc-root')
    yield entity('lambda_pit', brushes=[box((3072, 608, UPPER - 256), (3840, 1440, UPPER - 208), TRIM)],
                 target='gc-return')
    yield entity('info_null', (3456, 560, UPPER + 24), targetname='gc-return')


def course():
    yield entity('worldspawn', brushes=world(), message='The Lambda Lab', wad='signal.wad')
    yield entity('info_player_start', (-900, 0, LAB + 24), angle=0)
    yield entity('info_player_coop', (-900, 96, LAB + 24), angle=0)
    yield entity('qslisp_checkpoint', (-120, 0, LAB + 24))
    # Weapons along the hall, each with its first ammo.
    for classname, x in (('lambda_linker', -760), ('lambda_beacon_launcher', -620),
                         ('lambda_ricochet_launcher', -480), ('lambda_sweeper_gun', -340)):
        yield entity(classname, (x, -240, LAB + 24))
    yield entity('lambda_rockets', (-480, 240, LAB + 24))
    yield entity('lambda_cells', (-340, 240, LAB + 24))
    yield entity('qslisp_health', (-760, 240, LAB + 24))
    quine = box((-1022, 168, LAB), (-1006, 232, LAB + 64), 'quine_sign')
    yield entity('lambda_quine', brushes=[quine])
    for x in (-900, -640, -380):
        yield entity('light', (x, 0, LAB + 200), light=350)
    # The hidden shrine behind an illusory wall.
    yield entity('lambda_illusion', brushes=[box((-736, -400, LAB), (-608, -384, LAB + 128), 'lambda_wall')])
    yield entity('lambda_secret', brushes=[box((-736, -560, LAB), (-608, -480, LAB + 96), TRIM)])
    console = box((-560, -1000, LAB), (-512, -968, LAB + 48), 'lisp_keys')
    yield entity('lambda_shrine', brushes=[console], target='shrine-lights')
    yield entity('light', (-672, -830, LAB + 140), light=300, targetname='shrine-lights')
    yield entity('light', (-820, -830, LAB + 140), light=250, targetname='shrine-lights')
    yield entity('lambda_rune', (-672, -760, LAB + 24), rune=16, message='quote')
    # Cons cells, Floyd's drones, the tail door, and the pit return.
    yield from cell_entities()
    yield entity('lambda_floyd', (192, 0, LAB + 96), target='c5')
    door = box((1264, -64, LAB), (1280, 64, LAB + 128), 'lambda_door')
    yield entity('lambda_list_door', brushes=[door], targetname='tail-door')
    yield entity('lambda_pit', brushes=[box((-256, -768, PIT), (1280, 768, PIT + 48), TRIM)],
                 target='pit-return')
    yield entity('info_null', (-120, 0, LAB + 24), targetname='pit-return')
    yield entity('lambda_rune', (1420, 0, LAB + 24), rune=512, message='cons')
    for x, y in ((-128, -600), (-128, 600), (640, 0), (1180, -600), (1180, 600), (1000, 0)):
        yield entity('light', (x, y, LAB + 280), light=420)
    yield from amb_entities()
    yield entity('lambda_rune', (2940, -160, LAB + 24), rune=1024, message='cond')
    # Tail-call lifts, dogs, and the linker coil in the lift hall.
    yield from lift_entities()
    yield entity('lambda_coil', (3500, 300, LAB + 48))
    yield entity('lambda_dog', (3150, 300, LAB + 24), angle=270, targetname='dog-west')
    yield entity('lambda_dog', (3500, -300, LAB + 24), angle=90, targetname='dog-east')
    yield entity('qslisp_health', (3110, -340, LAB + 24))
    yield entity('lambda_rockets', (3150, -340, LAB + 24))
    yield entity('lambda_cells', (3190, -340, LAB + 24))
    for x, y in ((3150, 250), (3500, 250), (3150, -250), (3500, -250)):
        yield entity('light', (x, y, LAB + 200), light=320)
    # The eval and apply bosses guard the arena's north door.
    yield entity('lambda_boss', (3300, 360, UPPER + 24), targetname='eval', target='apply', angle=270)
    yield entity('lambda_boss', (3612, 360, UPPER + 24), targetname='apply', target='eval', angle=270)
    door = box((3328, 512, UPPER), (3584, 528, UPPER + 160), 'lambda_door')
    yield entity('lambda_boss_door', brushes=[door])
    yield entity('qslisp_health', (3700, -400, UPPER + 24))
    yield entity('lambda_cells', (3740, -400, UPPER + 24))
    for x, y in ((3200, -300), (3700, -300), (3200, 300), (3700, 300), (3456, 0)):
        yield entity('light', (x, y, UPPER + 250), light=420)
    # The conduit room and the exit to the AI Winter.
    yield from gc_entities()
    yield entity('qslisp_checkpoint', (3456, 560, UPPER + 24))
    exit_zone = box((3392, 1640, UPPER), (3520, 1780, UPPER + 128), TRIM)
    yield entity('lambda_exit', brushes=[exit_zone], message='winter')
    yield entity('light', (3456, 1660, UPPER + 150), light=300)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(''.join(course()), encoding='ascii')


if __name__ == '__main__':
    main()
