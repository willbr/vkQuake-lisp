#!/usr/bin/env python3
"""Generate the editable Relay Annex uplink blockout."""
import argparse
from pathlib import Path

from map_editor import Brush, Face, bank, box, coordinates, quoted, ramp, seal, switchback

TRIM, MARKER = 'relay_trim', 'relay_goal'
SERVICE, FREIGHT, FLOOD, SUMP, SWITCHGEAR, GANTRIES, ROOF = 0, -1280, -2560, -3840, 1280, 2560, 3840
THICKNESS = 16
LIFT_RECESS = 8
DECK_AT_FLOOR = {
    -656: 'yard', -640: 'yard', -1296: 'yard', SERVICE: 'yard',
    FREIGHT: 'freight', FREIGHT-64: 'freight', FLOOD: 'flood',
    SUMP: 'sump', SUMP-176: 'sump', SWITCHGEAR: 'switch',
    GANTRIES: 'gantry', GANTRIES-192: 'gantry', GANTRIES-384: 'gantry',
    ROOF: 'roof',
}
# Each panel pair gives the wall position, wall axis, and facing at the lower and upper landing.
LIFT_SPECS = (
    ('freight-lift', 3104, -1120, FLOOD, FREIGHT, False,
     ((3608, -1200, 0, -1), (3608, -1200, 0, -1))),
    ('sump-lift', -3880, -3488, SUMP, FLOOD, True,
     ((-3368, -3490, 1, -1), (-3878, -2940, 0, 1))),
    ('cargo-lift', -4000, -4016, SUMP, SWITCHGEAR, True,
     ((-3456, -3998, 1, 1), (-3452, -4014, 1, 1))),
    ('gantry-lift', 3440, -2800, SWITCHGEAR, GANTRIES, True,
     ((3944, -2802, 1, -1), (4014, -2260, 0, -1))),
    ('roof-lift', -4000, 3520, GANTRIES, ROOF, True,
     ((-3460, 3426, 1, 1), (-3450, 3426, 1, 1))),
)
GANTRY_RELAYS = (('east-relay', 3072), ('west-relay', -2320))


def room(x, xx, y, yy, z, ceiling=None):
    return (x, y, z), (xx, yy, z + 224 if ceiling is None else ceiling)


def seal_course(regions):
    def texture(index, axis, positive):
        low = regions[index][0]
        deck = DECK_AT_FLOOR.get(low[2])
        if deck is None:
            deck = DECK_AT_FLOOR[low[2] + LIFT_RECESS]
        return f'{deck}_deck' if axis == 2 and not positive else f'{deck}_wall'
    return seal(regions, texture, THICKNESS)


def placard(texture, x, y, z, axis, facing, *, width=180, height=42):
    """Mount one face of a shallow sign, aligned to a full texture tile."""
    low, high = [x, y, z], [x, y, z + height]
    across = 1 - axis
    low[axis] -= 2
    high[axis] += 2
    low[across] -= width // 2
    high[across] += width // 2
    brush = box(low, high, 'annex_rib')
    scale_x = width / 64 * facing * (1 if axis == 0 else -1)
    scale_y = height / 64
    start = low[across] if scale_x > 0 else high[across]
    axes = (str(round(-start / scale_x)), str(round(high[2] / scale_y)),
            '0', str(scale_x), str(scale_y))
    return Brush(tuple(Face(face.points, texture, axes) if face.plane()[0][axis] * facing < -0.99
                       else face for face in brush.faces))


def overhead_rib(x, y, ceiling, axis, width):
    low, high = [x, y, ceiling - 28], [x, y, ceiling]
    low[axis] -= width // 2
    high[axis] += width // 2
    low[1 - axis] -= 15
    high[1 - axis] += 15
    yield box(low, high, 'annex_rib')
    low[axis], high[axis] = ((x, y)[axis] - 74, (x, y)[axis] + 74)
    low[1 - axis] += 6
    high[1 - axis] -= 6
    low[2], high[2] = ceiling - 32, ceiling - 28
    yield box(low, high, 'annex_lamp')


def fixtures():
    for spec in (
        ('yard_bikes', -3248, -2508, SERVICE+164, 1, 1),
        ('freight_jump', 376, -1376, FREIGHT+148, 0, -1),
        ('flood_valve', -3650, -2658, FLOOD+148, 1, 1),
        ('sump_pumps', -2672, -3584, SUMP+154, 0, -1),
        ('switch_relay', 3180, -3240, SWITCHGEAR+152, 0, -1),
        ('gantry_array', 3680, 2840, GANTRIES+148, 1, -1),
        ('roof_exit', 3840, 3700, ROOF+126, 0, -1),
    ):
        yield placard(*spec)
    for spec in (
        (-3072, -2130, SERVICE+224, 1, 704),
        (1232, -1376, FREIGHT+224, 1, 480),
        (2960, -1376, FREIGHT+224, 1, 480),
        (-1740, -2344, FLOOD+224, 1, 480),
        (-3370, -3650, SUMP+224, 0, 400),
        (-1700, -3760, SWITCHGEAR+224, 1, 480),
        (2440, -3248, SWITCHGEAR+224, 1, 480),
        (3170, 1300, GANTRIES+224, 0, 480),
        (-2176, 3720, GANTRIES+224, 1, 544),
        (2896, 3720, 4016, 1, 544),
    ):
        yield from overhead_rib(*spec)
    # Give the back of the pump room a service manifold and vertical supports.
    yield box((-3550, -3999, SUMP+100), (-2990, -3950, SUMP+148), 'sump_wall')
    for x in (-3510, -3264, -3020):
        yield box((x-18, -3999, SUMP+50), (x+18, -3960, SUMP+180), 'annex_rib')
    # Frame the extraction panel against the end bulkhead.
    for y in (3552, 3848):
        yield box((3960, y-18, ROOF), (4016, y+18, 4016), 'annex_rib')
    yield from overhead_rib(3986, 3700, 4016, 1, 326)
    for name, x in GANTRY_RELAYS:
        # Build a lit portal around the sensor, leaving the riding lane open.
        for lo, hi in ((3424, 3472), (3968, 4016)):
            yield box((x-26, lo, GANTRIES), (x+26, hi, GANTRIES+224), 'annex_rib')
            y = (lo + hi) // 2
            for face in (-1, 1):
                lamp = x + face * 27
                yield box((lamp-1, y-11, GANTRIES+60), (lamp+1, y+11, GANTRIES+144), 'annex_lamp')
        yield box((x-22, 3472, GANTRIES+188), (x+22, 3968, GANTRIES+224), 'annex_rib')
        label = name.replace('-', '_')
        yield placard(label, x+25, 3720, GANTRIES+151, 0, 1)
        yield placard(label, x-25, 3720, GANTRIES+151, 0, -1)


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


def floor_light(x, y, floor, strength=480):
    return entity('light', (x, y, floor + 144), light=strength)


def hint(x, y, floor, code, *, width=112, length=112):
    zone = box((x-width, y-length, floor), (x+width, y+length, floor+112), TRIM)
    return entity('uplink_hint', brushes=[zone], **{'hint-code': code})


def lift(name, x, y, floor, upper, *, locked=False):
    platform = box((x+2, y+2, floor-16), (x+478, y+478, floor), 'lift_deck')
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

    # Recess the world floor below the moving brush so their top faces never overlap.
    for _, x, y, low, *_ in LIFT_SPECS:
        regions.append(room(x+2, x+478, y+2, y+478, low-LIFT_RECESS, low))
    world = list(seal_course(regions))
    descent = switchback((-3504, -3760, 0), 4576, 512, 928, 1280, 2, 'yard_deck')
    # The switchback pad is built into its room floor. Keep the two sloped runs.
    world.extend((descent[0], descent[-1]))
    world.extend((
        ramp((448, -1536, 672, -1216), (FREIGHT + 1, FREIGHT + 108), 'x', FREIGHT - 16, TRIM),
        ramp((792, -1632, 912, -1120), (-1343, FREIGHT), 'x', -1352, 'freight_deck'),
        box((-2912, -3776, -3936), (-2560, -3616, -3904), TRIM),
        box((3360, -3088, SWITCHGEAR), (3488, -3024, SWITCHGEAR+48), TRIM),
        box((3776, -3488, SWITCHGEAR), (3872, -3360, SWITCHGEAR+60), TRIM),
        ramp((-1280, 2976, -736, 3072), (GANTRIES-192, GANTRIES-384), 'x', GANTRIES-400, 'gantry_deck'),
        ramp((-1792, 2848, -1280, 3424), (GANTRIES, GANTRIES-192), 'x', GANTRIES-208, 'gantry_deck'),
        box((-352, 2900, GANTRIES+80), (-32, 3020, GANTRIES+96), TRIM),
        ramp((2960, 1896, 3312, 2176), (GANTRIES+1, GANTRIES+35), 'y', GANTRIES-12, TRIM),
    ))
    world.extend(fixtures())
    yield entity('worldspawn', brushes=world, message='Relay Annex - Restore the Uplink', wad='signal.wad')
    yield marker('info_player_start', -3750, -2096, SERVICE)
    yield marker('info_player_coop', -3816, -2192, SERVICE)
    yield marker('qslisp_bike', -3316, -2334, SERVICE, angle=270)
    yield marker('qslisp_bike', -3136, -2334, SERVICE, angle=270)
    yield marker('uplink_buddy', -3650, -2000, SERVICE)
    yield marker('uplink_journal', -3750, -1952, SERVICE, targetname='mission-journal')
    yield entity('qslisp_gate',
                 brushes=[box((-3504, -2528, SERVICE), (-2992, -2512, SERVICE+144), 'annex_gate')],
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
    for name, x, y, low, high, locked, panels in LIFT_SPECS:
        yield lift(name, x, y, low, high, locked=locked)
        for stop, (floor, (px, py, axis, facing)) in enumerate(zip((low, high), panels), start=1):
            panel = placard('lift_call', px, py, floor+30, axis, facing, width=48, height=36)
            yield entity('uplink_station', brushes=[panel], targetname=f'{name}-call-{stop}',
                         target=name, **{'lift-call-stop': stop})
        yield floor_light(x+240, y+240, low)
        yield floor_light(x+240, y+240, high)
        for height in range(low+440, high-120, 400):
            yield entity('light', (x+240, y+240, height), light=440)
    yield station('flood-valve', -3650, -2696, FLOOD, target='sump-lift')
    yield station('hold-pump', -3370, -3660, SUMP)
    yield station('pump-breaker', -2608, -3550, SUMP, target='cargo-lift')
    yield station('switch-breaker', 3940, -2960, SWITCHGEAR, target='gantry-lift')
    yield entity('uplink_pulse_relay', (3300, -3144, SWITCHGEAR+54), target='switch-breaker')
    yield marker('qslisp_guard', 3700, -3290, SWITCHGEAR, angle=180, targetname='switch-guard',
                 **{'sentry-range': 640})
    yield entity('qslisp_bike_bank', brushes=bank((-3504, -2144, FREIGHT), (80, 470), (90, 180), 60, 6, TRIM))
    yield entity('qslisp_bike_bank', brushes=bank((3424, 3424, GANTRIES), (92, 576), (0, 90), 66, 6, TRIM))
    for name, x in GANTRY_RELAYS:
        brush = box((x-20, 3432, GANTRIES), (x+20, 4008, GANTRIES+100), MARKER)
        yield entity('uplink_relay', brushes=[brush], targetname=name)
    yield entity('uplink_anchor', (-192, 3000, GANTRIES+172), targetname='gantry-pull')
    yield entity('uplink_anchor', (-864, 3120, GANTRIES+198), targetname='gantry-swing',
                 **{'tether-swing': 1})
    yield marker('uplink_recall', 3530, -1500, FREIGHT, targetname='freight-service')
    yield marker('uplink_recall', 3580, -2180, GANTRIES, targetname='gantry-service')
    yield station('roof-extract', 3890, 3700, ROOF)
    # Overlap light along the ride lines and keep side rooms and controls visible.
    for x, y, z in (
        # Service yard and the two downhill passes.
        (-3700,-2050,SERVICE),(-3050,-2150,SERVICE),(-3248,-2650,SERVICE),(-3248,-3120,SERVICE),
        (-3210,-3504,-41),(-2590,-3504,-128),(-1970,-3504,-215),(-1350,-3504,-301),
        (-730,-3504,-388),(-110,-3504,-475),(510,-3504,-561),(1100,-3504,-640),
        (1330,-3024,-640),(1100,-2560,-640),(480,-2560,-723),(-140,-2560,-810),
        (-760,-2560,-896),(-1380,-2560,-983),(-2000,-2560,-1070),
        (-2620,-2560,-1156),(-3240,-2560,-1243),
        # Freight route, bridge and flood bypass.
        (-3740,-2420,FREIGHT),(-3660,-2000,FREIGHT),(-3040,-1888,FREIGHT),
        (-2420,-1888,FREIGHT),(-1800,-1888,FREIGHT),(-1180,-1888,FREIGHT),
        (-560,-1888,FREIGHT),(40,-1650,FREIGHT),(550,-1376,FREIGHT),
        (1070,-1376,FREIGHT),(1690,-1376,FREIGHT),(2310,-1376,FREIGHT),
        (2930,-1376,FREIGHT),(3390,-1376,FREIGHT),(785,-1376,FREIGHT-64),
        (3350,-1330,FLOOD),(3330,-1840,FLOOD),(2710,-1850,FLOOD),(2090,-1850,FLOOD),
        (1470,-1850,FLOOD),(850,-1850,FLOOD),(230,-1850,FLOOD),(-370,-1920,FLOOD),
        (-610,-2350,FLOOD),(-1230,-2350,FLOOD),(-1850,-2350,FLOOD),
        (-2470,-2350,FLOOD),(-3090,-2350,FLOOD),(-3650,-2340,FLOOD),(-3650,-2690,FLOOD),
        # Pump room, switchgear aisle and guard room.
        (-3620,-3500,SUMP),(-3380,-3660,SUMP),(-3050,-3770,SUMP),
        (-2620,-3550,SUMP),(-2700,-3880,SUMP-176),
        (-3400,-3750,SWITCHGEAR),(-2780,-3750,SWITCHGEAR),(-2160,-3750,SWITCHGEAR),
        (-1540,-3750,SWITCHGEAR),(-920,-3750,SWITCHGEAR),(-300,-3750,SWITCHGEAR),
        (180,-3480,SWITCHGEAR),(660,-3240,SWITCHGEAR),(1280,-3240,SWITCHGEAR),
        (1900,-3240,SWITCHGEAR),(2520,-3240,SWITCHGEAR),(3140,-3240,SWITCHGEAR),
        (3730,-3290,SWITCHGEAR),(3790,-2920,SWITCHGEAR),
        # East gantries, tether alcove and final rooftop straight.
        (3680,-2060,GANTRIES),(3680,-1440,GANTRIES),(3680,-820,GANTRIES),(3460,-260,GANTRIES),
        (3180,270,GANTRIES),(3180,890,GANTRIES),(3180,1510,GANTRIES),(3180,2130,GANTRIES),
        (3610,2540,GANTRIES),(3680,3100,GANTRIES),(3680,3630,GANTRIES),
        (3060,3720,GANTRIES),(2440,3720,GANTRIES),(1820,3720,GANTRIES),(1200,3720,GANTRIES),
        (580,3720,GANTRIES),(-40,3720,GANTRIES),(-660,3720,GANTRIES),(-1280,3720,GANTRIES),
        (-1900,3720,GANTRIES),(-2520,3720,GANTRIES),(-3140,3720,GANTRIES),
        (-132,3180,GANTRIES),(-1510,3170,GANTRIES-192),(-880,3120,GANTRIES-384),
        (-3300,3710,ROOF),(-2680,3710,ROOF),(-2060,3710,ROOF),(-1440,3710,ROOF),
        (-820,3710,ROOF),(-200,3710,ROOF),(420,3710,ROOF),(1040,3710,ROOF),
        (1660,3710,ROOF),(2280,3710,ROOF),(2900,3710,ROOF),(3520,3710,ROOF),(3890,3700,ROOF),
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
