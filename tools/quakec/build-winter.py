#!/usr/bin/env python3
"""Generate the editable AI Winter: a frozen Lisp lab for stock Quake."""
import argparse
from importlib import import_module
from pathlib import Path

from map_editor import box, seal

lab = import_module('build-lambda')
entity, room = lab.entity, lab.room
TRIM = 'relay_trim'
ICE_ROOMS = (1, 5)


def regions():
    return [
        room(-1024, -512, -256, 256, 0, 256),   # warm hall and start
        room(-512, 1024, -384, 384, 0, 320),    # ice field
        room(0, 512, 384, 896, 0, 256),         # server room with the dish
        room(1024, 1536, -64, 64, 0, 128),      # cold corridor
        room(1536, 2560, -512, 512, 0, 384),    # reactor hall
        room(1856, 2240, -480, -160, -40, 0),   # frozen sump: slide in, jump out
        room(2560, 2816, -128, 128, 0, 192),    # exit beyond the rune gate
    ]


def surface(rooms):
    def texture(index, axis, positive):
        if axis == 2 and not positive:
            return 'winter_ice' if index in ICE_ROOMS else 'winter_snow'
        return 'winter_metal' if axis == 2 else 'winter_wall'
    return texture


def world():
    rooms = regions()
    brushes = list(seal(rooms, surface(rooms)))
    # Pillars on the ice field to slide around.
    for x, y in ((0, -200), (300, 160), (600, -120)):
        brushes.append(box((x - 32, y - 32, 0), (x + 32, y + 32, 192), 'winter_metal'))
    brushes.append(box((-1020, -200, 0), (-1004, 200, 160), 'winter_heater'))
    brushes.append(box((1880, 160, 0), (1896, 400, 160), 'winter_heater'))
    brushes.append(box((40, 860, 0), (472, 892, 120), 'lisp_console'))
    brushes.append(lab.sign('winter_sign', -508, 0, 150, 0, 1))
    brushes.append(lab.sign('eval_sign', 2556, 0, 150, 0, -1))
    return brushes


def spinner(name, offset, spin, parts):
    """Brush models turn about their entity origin. Author them around world
    (0, 0) and move them into place when they spawn."""
    return entity('winter_fan', brushes=[box(low, high, 'winter_metal') for low, high in parts],
                  targetname=name, spin=spin, **{'winter-dx': offset[0], 'winter-dy': offset[1]})


def course():
    yield entity('worldspawn', brushes=world(), message='The AI Winter', wad='signal.wad')
    yield entity('info_player_start', (-900, 0, 24), angle=0)
    yield entity('info_player_coop', (-900, 96, 24), angle=0)
    yield entity('winter_heat', brushes=[box((-1024, -256, 0), (-512, 256, 128), TRIM)])
    yield entity('winter_heat', brushes=[box((1536, 128, 0), (1920, 448, 128), TRIM)])
    yield entity('winter_heat', brushes=[box((0, 640, 0), (512, 896, 128), TRIM)])
    yield entity('winter_ice', brushes=[box((-512, -384, 0), (1024, 384, 48), TRIM)])
    yield entity('winter_ice', brushes=[box((1856, -480, -40), (2240, -160, -8), TRIM)])
    yield entity('winter_cold', (-800, 0, 64))
    # Two ceiling fans over the ice and the radar dish in the server room.
    blade = ((-96, -8, 280), (96, 8, 284)), ((-8, -96, 280), (8, 96, 284)), ((-12, -12, 270), (12, 12, 300))
    yield spinner('fan-west', (100, 0, 0), 90, blade)
    yield spinner('fan-east', (700, 200, 0), -120, blade)
    dish = ((-64, -8, 80), (64, 8, 140)), ((-8, -8, 0), (8, 8, 80))
    yield spinner('dish', (256, 720, 0), 30, dish)
    yield entity('qslisp_health', (-800, 200, 24))
    yield entity('lambda_cells', (-760, 200, 24))
    yield entity('lambda_rockets', (-720, 200, 24))
    yield entity('lambda_rune', (256, 600, 24), rune=32, message='atom')
    yield entity('lambda_rune', (2048, -320, -16), rune=64, message='eq')
    yield entity('lambda_dog', (800, -250, 24), angle=180, targetname='dog-ice')
    yield entity('lambda_dog', (2000, 300, 24), angle=180, targetname='dog-reactor')
    gate = box((2544, -64, 0), (2560, 64, 128), 'lambda_door')
    yield entity('winter_gate', brushes=[gate], targetname='rune-gate')
    yield entity('winter_exit', brushes=[box((2640, -96, 0), (2800, 96, 128), TRIM)])
    yield from lab.light_grid(regions())
    for x, y, z in ((-800, 0, 200), (-300, 0, 260), (250, 0, 260), (800, 0, 260), (256, 650, 200),
                    (1280, 0, 100), (1700, 300, 300), (2100, 0, 320), (2048, -320, 100), (2700, 0, 150)):
        yield entity('light', (x, y, z), light=330)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(''.join(course()), encoding='ascii')


if __name__ == '__main__':
    main()
