#!/usr/bin/env python3
"""Generate the editable Relay Annex uplink blockout."""
import argparse
from itertools import product
from pathlib import Path

from map_editor import bank, box, coordinates, quoted, ramp, switchback

FLOOR, WALL, TRIM, MARKER = 'relay_floor', 'relay_wall', 'relay_trim', 'relay_goal'
SERVICE, FREIGHT, FLOOD, SUMP, SWITCHGEAR, GANTRIES, ROOF = 0, -1280, -2560, -3840, 1280, 2560, 3840
THICKNESS = 16


def room(x, xx, y, yy, z, ceiling=None):
    return (x, y, z), (xx, yy, z + 224 if ceiling is None else ceiling)


def cut(rect, opening):
    """Subtract an overlapping rectangle, returning the remaining strips."""
    a, b, c, d = rect
    x, y, xx, yy = opening
    x, y, xx, yy = max(a, x), max(b, y), min(c, xx), min(d, yy)
    if x >= xx or y >= yy:
        return [rect]
    return [(p, q, r, s) for p, q, r, s in
            ((a, b, x, d), (xx, b, c, d), (x, b, xx, y), (x, yy, xx, d)) if p < r and q < s]


def seal(regions):
    """Build the boundary of joined rectilinear volumes as world brushes."""
    for current, (low, high) in enumerate(regions):
        for axis, positive in product(range(3), (False, True)):
            a, b = (i for i in range(3) if i != axis)
            boundary = high[axis] if positive else low[axis]
            plates = [(low[a], low[b], high[a], high[b])]
            for other, (lo, hi) in enumerate(regions):
                reaches = lo[axis] <= boundary < hi[axis] if positive else lo[axis] < boundary <= hi[axis]
                if current != other and reaches:
                    opening = lo[a], lo[b], hi[a], hi[b]
                    plates = [part for rect in plates for part in cut(rect, opening)]
            for x, y, xx, yy in plates:
                start, end = [0, 0, 0], [0, 0, 0]
                start[axis], end[axis] = ((boundary, boundary + THICKNESS) if positive
                                           else (boundary - THICKNESS, boundary))
                start[a], start[b], end[a], end[b] = x, y, xx, yy
                texture = FLOOR if axis == 2 and not positive else WALL
                yield box(start, end, texture)


def entity(classname, origin=None, brushes=(), **keys):
    fields = {'classname': classname, **keys}
    if origin is not None:
        fields['origin'] = coordinates(origin)
    return ('{\n' + ''.join(f'{quoted(key)} {quoted(str(value))}\n' for key, value in fields.items())
            + ''.join(brush.text() for brush in brushes) + '}\n')


def marker(classname, x, y, floor, **keys):
    return entity(classname, (x, y, floor + 24), **keys)


def station(name, x, y, floor, **keys):
    brush = box((x-24, y-8, floor), (x+24, y+8, floor+48), MARKER)
    return entity('uplink_station', brushes=[brush], targetname=name, **keys)


def floor_light(x, y, floor, strength=350):
    return entity('light', (x, y, floor + 144), light=strength)


def hint(x, y, floor, code, *, width=112, length=112):
    zone = box((x-width, y-length, floor), (x+width, y+length, floor+112), TRIM)
    return entity('uplink_hint', brushes=[zone], **{'hint-code': code})


def lift(name, x, y, floor, upper, *, locked=False):
    platform = box((x+2, y+2, floor-16), (x+478, y+478, floor), TRIM)
    return entity('uplink_lift', brushes=[platform], targetname=name,
                  **{'lift-travel': upper - floor, 'lift-locked': int(locked),
                     'lift-floor': floor, 'lift-x': x+240, 'lift-y': y+240})


def course():
    regions = [
        # The yard and two long downhill runs joined at the east end.
        room(-4016, -2528, -2500, -1760, SERVICE),
        room(-3504, -2992, -3248, -2500, SERVICE),
        room(-3504, 1072, -3760, -3248, -656, 224),
        room(1072, 1584, -3760, -2320, -640, -416),
        room(-3504, 1072, -2832, -2320, -1296, -416),
        # West landing and a dogleg across the freight deck to the east lift.
        room(-3984, -3504, -2832, -1632, FREIGHT),
        room(-3504, -256, -2144, -1632, FREIGHT),
        room(-256, 320, -2144, -1120, FREIGHT),
        room(320, 3616, -1632, -1120, FREIGHT),
        room(672, 912, -1632, -1120, -1344, FREIGHT),
        room(3104, 3584, -1120, -640, FLOOD, -1056),
        room(3104, 3616, -1632, -1120, FLOOD),
        # The lower bypass, separate lower lift and pump room.
        room(0, 3104, -2112, -1600, FLOOD),
        room(3104, 3616, -2112, -1632, FLOOD),
        room(-544, 0, -2624, -1600, FLOOD),
        room(-3400, -544, -2624, -2112, FLOOD),
        room(-3880, -3400, -3008, -2112, FLOOD),
        room(-3880, -3400, -3488, -3008, SUMP, -2336),
        room(-4000, -2496, -4000, -3488, SUMP),
        room(-4000, -3520, -4016, -3600, SUMP, 1504),
        # Upper cargo landing and switchgear aisle across the footprint.
        room(-3520, -160, -4016, -3504, SWITCHGEAR),
        room(-160, 384, -4016, -2992, SWITCHGEAR),
        room(384, 3200, -3504, -2992, SWITCHGEAR),
        room(3200, 4016, -3504, -2800, SWITCHGEAR),
        room(3440, 3920, -2800, -2320, SWITCHGEAR, 2784),
        # East ascent, full-width northeast turn and north gantries.
        room(3424, 4016, -2320, -512, GANTRIES),
        room(2912, 4016, -512, 64, GANTRIES),
        room(2912, 3424, 64, 2176, GANTRIES),
        room(2912, 4016, 2176, 2752, GANTRIES),
        room(3424, 4016, 2752, 3424, GANTRIES),
        room(3424, 4016, 3424, 4016, GANTRIES),
        room(-3424, 3424, 3424, 4016, GANTRIES),
        room(-448, 64, 2848, 3424, GANTRIES),
        room(-1792, -1280, 2848, 3424, GANTRIES - 192, GANTRIES + 224),
        room(-1280, -448, 2976, 3264, GANTRIES - 384, GANTRIES + 224),
        room(-4016, -3424, 3424, 4016, GANTRIES),
        room(-4000, -3520, 3520, 4000, GANTRIES, 4016),
        room(-3520, 4016, 3424, 4016, ROOF, 4016),
        # Lower service pit gives the sump a floor near the bottom boundary.
        room(-2912, -2560, -3968, -3616, -4016, SUMP),
    ]

    world = list(seal(regions))
    descent = switchback((-3504, -3760, 0), 4576, 512, 928, 1280, 2, FLOOR)
    # The switchback pad is built into its room floor. Keep the two sloped runs.
    world.extend((descent[0], descent[-1]))
    world.extend((
        ramp((448, -1536, 672, -1216), (FREIGHT + 1, FREIGHT + 108), 'x', FREIGHT - 16, TRIM),
        ramp((792, -1632, 912, -1120), (-1343, FREIGHT), 'x', -1352, FLOOR),
        box((-2912, -3776, -3936), (-2560, -3616, -3904), TRIM),
        box((3360, -3088, SWITCHGEAR), (3488, -3024, SWITCHGEAR+48), TRIM),
        box((3776, -3488, SWITCHGEAR), (3872, -3360, SWITCHGEAR+60), TRIM),
        ramp((-1280, 2976, -736, 3072), (GANTRIES-192, GANTRIES-384), 'x', GANTRIES-400, FLOOR),
        ramp((-1792, 2848, -1280, 3424), (GANTRIES, GANTRIES-192), 'x', GANTRIES-208, FLOOR),
        box((-352, 2900, GANTRIES+80), (-32, 3020, GANTRIES+96), TRIM),
        ramp((2960, 1896, 3312, 2176), (GANTRIES+1, GANTRIES+35), 'y', GANTRIES-12, TRIM),
    ))
    yield entity('worldspawn', brushes=world, message='Relay Annex - Restore the Uplink', wad='signal.wad')
    yield marker('info_player_start', -3750, -2096, SERVICE)
    yield marker('info_player_coop', -3816, -2192, SERVICE)
    yield marker('qslisp_bike', -3316, -2334, SERVICE, angle=270)
    yield marker('qslisp_bike', -3136, -2334, SERVICE, angle=270)
    yield marker('uplink_buddy', -3650, -2000, SERVICE)
    yield marker('uplink_journal', -3750, -1952, SERVICE, targetname='mission-journal')
    yield entity('qslisp_gate', brushes=[box((-3504, -2528, SERVICE), (-2992, -2512, SERVICE+144), MARKER)],
                 targetname='bike-dock')
    yield marker('uplink_waypoint', -3460, -2490, SERVICE, targetname='dock-rendezvous')
    yield marker('uplink_waypoint', -3376, -2000, FREIGHT, targetname='freight-rendezvous')
    yield marker('uplink_waypoint', -3072, -3640, SUMP, targetname='sump-rendezvous')
    # Keep the buddy on the approach side of the solid valve console.
    yield marker('uplink_waypoint', -3430, -3608, SUMP, targetname='pump-hold')
    yield marker('uplink_waypoint', -3290, -3730, SWITCHGEAR, targetname='switch-rendezvous')
    yield marker('uplink_waypoint', 3250, -3100, SWITCHGEAR, targetname='switch-cover')
    yield marker('uplink_waypoint', 3590, -2230, GANTRIES, targetname='gantry-rendezvous')
    yield marker('qslisp_checkpoint', -3190, -3770, SUMP)
    yield marker('qslisp_checkpoint', 3220, -3270, SWITCHGEAR)
    yield marker('qslisp_health', -3280, -3630, SUMP)
    yield marker('qslisp_ammo', 3152, -3316, SWITCHGEAR)
    yield marker('qslisp_pulse', -3200, -3750, SWITCHGEAR)
    yield marker('uplink_tether_supply', 3600, 2850, GANTRIES)
    yield hint(-3750, -2110, SERVICE, 1)
    yield hint(-3744, -2070, FREIGHT, 2, width=220)
    yield hint(3356, -1366, FLOOD, 4, width=240)
    yield hint(-3650, -3580, SUMP, 8, width=200)
    yield hint(-3232, -3760, SWITCHGEAR, 16, length=224)
    yield hint(3680, -2144, GANTRIES, 32, width=215)
    lift_specs = (
        ('freight-lift', 3104, -1120, FLOOD, FREIGHT, False),
        ('sump-lift', -3880, -3488, SUMP, FLOOD, True),
        ('cargo-lift', -4000, -4016, SUMP, SWITCHGEAR, True),
        ('gantry-lift', 3440, -2800, SWITCHGEAR, GANTRIES, True),
        ('roof-lift', -4000, 3520, GANTRIES, ROOF, True),
    )
    for name, x, y, low, high, locked in lift_specs:
        yield lift(name, x, y, low, high, locked=locked)
    yield station('flood-valve', -3650, -2696, FLOOD, target='sump-lift')
    yield station('hold-pump', -3370, -3660, SUMP)
    yield station('pump-breaker', -2608, -3550, SUMP, target='cargo-lift')
    yield station('switch-breaker', 3940, -2960, SWITCHGEAR, target='gantry-lift')
    yield entity('uplink_pulse_relay', (3300, -3144, SWITCHGEAR+54), target='switch-breaker')
    yield marker('qslisp_guard', 3700, -3290, SWITCHGEAR, angle=180, targetname='switch-guard',
                 **{'sentry-range': 640})
    yield entity('qslisp_bike_bank', brushes=bank((-3504, -2144, FREIGHT), (80, 470), (90, 180), 60, 6, TRIM))
    yield entity('qslisp_bike_bank', brushes=bank((3424, 3424, GANTRIES), (92, 576), (0, 90), 66, 6, TRIM))
    for name, x in (('east-relay', 3072), ('west-relay', -2320)):
        brush = box((x-20, 3432, GANTRIES), (x+20, 4008, GANTRIES+100), MARKER)
        yield entity('uplink_relay', brushes=[brush], targetname=name)
    yield entity('uplink_anchor', (-192, 3000, GANTRIES+172), targetname='gantry-pull')
    yield entity('uplink_anchor', (-864, 3120, GANTRIES+198), targetname='gantry-swing',
                 **{'tether-swing': 1})
    yield marker('uplink_recall', 3530, -1500, FREIGHT, targetname='freight-service')
    yield marker('uplink_recall', 3580, -2180, GANTRIES, targetname='gantry-service')
    yield station('roof-extract', 3890, 3700, ROOF)
    # Small regularly spaced pools reveal bends and inter-floor destinations.
    for x, y, z in (
        (-3700,-2050,0),(-3060,-3080,0),(-3210,-3500,-48),(-1650,-3500,-258),
        (0,-3500,-484),(1280,-3024,-640),(500,-2570,-720),(-1000,-2570,-934),
        (-2450,-2570,-1136),(-3740,-2420,FREIGHT),(-2100,-1888,FREIGHT),
        (-200,-1840,FREIGHT),(800,-1400,FREIGHT),(2400,-1400,FREIGHT),(3320,-1400,FREIGHT),
        (3320,-1400,FLOOD),(2300,-1830,FLOOD),(1100,-1830,FLOOD),(-210,-1900,FLOOD),
        (-1300,-2350,FLOOD),(-2630,-2350,FLOOD),(-3650,-2630,FLOOD),(-3650,-2870,FLOOD),
        (-3620,-3230,SUMP),(-3750,-3790,SUMP),(-3180,-3690,SUMP),(-2580,-3730,SUMP),
        (-3350,-3730,SWITCHGEAR),(-2100,-3740,SWITCHGEAR),(-900,-3740,SWITCHGEAR),
        (210,-3420,SWITCHGEAR),(1450,-3240,SWITCHGEAR),(2770,-3240,SWITCHGEAR),
        (3400,-3315,SWITCHGEAR),(3840,-2920,SWITCHGEAR),(3660,-2060,GANTRIES),
        (3660,-1070,GANTRIES),(3190,-120,GANTRIES),(3190,900,GANTRIES),(3190,1900,GANTRIES),
        (3660,2550,GANTRIES),(3670,3450,GANTRIES),(2500,3720,GANTRIES),
        (950,3720,GANTRIES),(-550,3720,GANTRIES),(-2030,3720,GANTRIES),
        (-132,3180,GANTRIES),(-1570,3160,GANTRIES),
        (-3250,3720,GANTRIES),(-3750,3700,GANTRIES),(-3400,3710,ROOF),
        (-1800,3710,ROOF),(-350,3710,ROOF),(1140,3710,ROOF),(2300,3710,ROOF),(3620,3710,ROOF),
    ):
        yield floor_light(x, y, z)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(''.join(course()), encoding='ascii')


if __name__ == '__main__':
    main()
