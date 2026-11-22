"""Drive the uplink blockout with the stock DOS client and inspect its saves."""
import json
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import sys

from challenge import read_edicts, require
import coop
from map_editor import MapDocument, coordinates

MAP_SOURCE = Path(__file__).resolve().parents[2] / 'examples/uplink.map'
TOUR_STOPS = (
    ((-3650, -2780, -2560, 90), (-3750, -2780, -2560, 90)),
    ((-2693, -3550, -3840, 0), (-3370, -3770, -3840, 0)),
    ((3220, -3290, 1280, 0), (3268, -3410, 1280, 0)),
    ((3840, -2960, 1280, 0), (3700, -3100, 1280, 0)),
    ((3250, 3850, 2560, 180), (-2150, 3590, 2560, 180)),
    ((-3800, 3720, 2560, 0), (-3696, 3830, 2560, 0)),
    ((3890, 3622, 3840, 90), (3790, 3715, 3840, 90)),
)


def level_measurements(bsp):
    source = MapDocument(MAP_SOURCE.read_text(encoding='ascii')).validate()
    lower, upper = source['bounds']
    require(all(abs(axis + 4032) < 0.01 for axis in lower) and
            all(abs(axis - 4032) < 0.01 for axis in upper), 'uplink lost its full map envelope')
    header = struct.unpack('<31i', bsp.read_bytes()[:124])
    require(header[0] == 29, 'uplink must use stock BSP version 29')
    lengths = header[2::2]
    vis, light, models = lengths[4], lengths[8], lengths[14] // 64
    require(0 < models < 256 and vis > 0 and light > 0, 'uplink BSP requires models, visibility, and lighting')
    return {**source, 'brush_models': models, 'vis_bytes': vis, 'light_bytes': light}


def wait(frames):
    return ['wait'] * frames


def look_up(degrees):
    return [f'cl_pitchspeed {degrees * 40}', '+lookup', 'wait', '-lookup']


def named(path, value, field='targetname'):
    return next((entry for entry in read_edicts(path) if entry.get(field) == value), {})


def player(path):
    return named(path, 'qslisp_player', 'classname')


def origin(path):
    return tuple(map(float, player(path)['origin'].split()))


def number(entry, field):
    return float(entry.get(field, '0'))


def edit(source, destination, changes):
    """Stage a save at a route waypoint, preserving every other edict."""
    def replace(match):
        body = match[0]
        values = dict(re.findall(r'^"([^"]*)"\s+"([^"]*)"', body, re.M))
        for field, expected, fields in changes:
            if values.get(field) == expected:
                for key, value in fields.items():
                    line = f'"{key}" "{value}"'
                    body, count = re.subn(rf'^"{re.escape(key)}"[^\n]*', line, body, flags=re.M)
                    if not count:
                        body = body[:-1] + line + '\n}'
        return body

    destination.write_text(re.sub(r'^\{\s*\n.*?^\}', replace, source.read_text(encoding='cp437'),
                                  flags=re.M | re.S), encoding='cp437')


class Client:
    def __init__(self, dosbox, output, env, base, mod):
        self.output, self.mod, self.base, self.env = output, mod, base, env
        self.dosbox = dosbox

    def save(self, name):
        return self.mod / f'{name}.sav'

    def place(self, source, destination, x, y, z, yaw, pitch=0, **fields):
        at = f'{x} {y} {z}'
        edit(self.save(source), self.save(destination), [('classname', 'qslisp_player', {
            'origin': at, 'oldorigin': at, 'angles': f'{pitch} {yaw} 0', 'v_angle': f'{pitch} {yaw} 0',
            'velocity': '0 0 0', 'bike-vx': 0, 'bike-vy': 0, 'bike-heading': yaw,
            'bike-steer-yaw': yaw, 'bike-view-yaw': yaw, 'bike-camera-yaw': yaw, **fields,
        })])

    def run(self, label, load, commands):
        config = self.mod / 'verify.cfg'
        config.write_text('\n'.join(['host_framerate 0.05', 'con_notifytime 0',
                                    *wait(18), *commands, 'toggleconsole', 'quit', '']), encoding='ascii')
        log = self.mod / 'qconsole.log'
        log.unlink(missing_ok=True)
        start = f'+load {load}' if load else '+map uplink'
        engine = ('quake -nosound -nocdaudio -noudp -noipx -condebug -game lispboot '
                  f'+developer 1 {start} +exec verify.cfg')
        command = [self.dosbox, '--noprimaryconf', '--nolocalconf', '--noautoexec',
                   '-c', f'mount c "{self.base}"', '-c', 'c:', '-c', engine, '--exit']
        with (self.output / f'{label}-dosbox.log').open('w') as out:
            subprocess.run(command, cwd=self.base, env=self.env, stdout=out, stderr=subprocess.STDOUT,
                           timeout=60, check=True)
        lines = log.read_text(encoding='cp437')
        (self.output / f'{label}.log').write_text(lines, encoding='utf-8')
        for command in commands:
            if command.startswith('save '):
                path = self.save(command.split()[1])
                require(path.is_file(), f'{label} did not write {path.name}')
                (self.output / path.name).write_bytes(path.read_bytes())
        require('CL_SignonReply: 4' in lines and 'Host_Error' not in lines, f'{label} failed to sign on')
        return lines


def verify(dosbox, output, env, base, mod):
    measurements = level_measurements(output / 'maps/uplink.bsp')
    client = Client(dosbox, output, env, base, mod)
    boot = client.run('boot', None, ['save start'])
    require(not re.search(r'^bike +[-\d.]', boot, re.M) and 'trace buddy:' not in boot,
            'trace was enabled at spawn')
    client.place('start', 'atdock', -3316, -2258, 24, 270)
    dock = client.run('dock', 'atdock', ['impulse 21', 'wait', 'impulse 3', *wait(8),
                      'save mounted', 'impulse 24', '+attack', *wait(70), '-attack', 'save entered'])
    require('qslisp: bike mounted' in dock, 'E did not mount the bike')
    require(re.search(r'^bike( +[-\d.]+){13}$', dock, re.M), 'invalid bike trace')
    require(re.search(r'^buddy( +[-\d.]+){6}$', dock, re.M), 'invalid buddy trace')
    require(origin(client.save('entered'))[1] < -3250, 'the bike missed the south perimeter entrance')

    client.place('mounted', 'atdes1', -3410, -3504, 20, 0)
    client.run('descent', 'atdes1', ['+attack', *wait(221), 'save desc1',
               'cl_yawspeed 52.5', '+left', *wait(40), 'save turnmid',
               *wait(25), '-left', *wait(237), '-attack', 'save desc2'])
    x, _, z = origin(client.save('desc1'))
    require(x > 1000 and z < -605, f'first downhill run stopped at {(x, z)}')
    tx, ty, _ = origin(client.save('turnmid'))
    require(tx > 1300 and -3350 < ty < -2750, 'the rider did not arc through the switchback')
    x, _, z = origin(client.save('desc2'))
    require(x < -3504 and z < -1230, f'second downhill run stopped at {(x, z)}')
    client.place('desc2', 'atbridge', 0, -1376, -1255, 0)
    client.run('freight-jump', 'atbridge', ['+attack', *wait(48), 'save airborne',
               *wait(29), '-attack', 'save crossing'])
    gap_x, _, gap_z = origin(client.save('airborne'))
    end_x, _, end_z = origin(client.save('crossing'))
    require(672 < gap_x < 912 and gap_z > -1215 and end_x > 960 and end_z >= -1257,
            f'freight jump stalled or went into the catch lane: {(gap_x, gap_z, end_x, end_z)}')

    # Exercise travel from the freight platform while mounted, then pick up
    # the remaining interlocks at authored waypoints on the same save chain.
    client.place('desc2', 'atfreigh', 3344, -1180, -1255, 90)
    freight = client.run('freight-lift', 'atfreigh',
                         ['impulse 3', *wait(95), '+attack', *wait(17), '-attack',
                          '+jump', *wait(20), '-jump', 'save aboard',
                          'impulse 3', *wait(95), 'save flooded'])
    require(freight.count('uplink: lift arrived') == 2 and origin(client.save('flooded'))[2] < -2500,
            'freight lift did not carry the rider down')

    client.place('start', 'atvalve', -3650, -2780, -2535, 90)
    client.run('flood-valve', 'atvalve', ['impulse 21', 'wait', 'impulse 3', *wait(5), 'save drained'])
    require(number(named(client.save('drained'), 'flood-valve'), 'uplink-active') == 1,
            'flood valve did not power the sump lift')
    client.place('drained', 'athold', -3370, -3574, -3815, 270)
    pump = client.run('pump-assist', 'athold', ['impulse 3', *wait(90), 'save holding'])
    require('uplink: buddy arrived by service route' in pump and
            number(named(client.save('holding'), 'uplink_buddy', 'classname'), 'buddy-state') == 3,
            'buddy did not take the sump service route')
    client.place('holding', 'atpump', -2693, -3550, -3815, 0)
    pump = client.run('pump-breaker', 'atpump', ['impulse 3', *wait(8), 'save pumped'])
    require('uplink: pumps online' in pump and
            number(named(client.save('pumped'), 'mission-journal'), 'uplink-saved-flags') == 3,
            'buddy did not hold the valve or the mission journal lost the flood event')
    client.place('pumped', 'atcheck', -3190, -3770, -3815, 0)
    recovery = client.run('checkpoint', 'atcheck', ['impulse 22', 'wait', 'kill', *wait(10),
                          '+attack', 'wait', '-attack', *wait(28), 'save regained'])
    require('qslisp: player respawned' in recovery and origin(client.save('regained'))[:2] == (-3190, -3770)
            and number(named(client.save('regained'), 'uplink_buddy', 'classname'), 'buddy-state') == 0,
            'checkpoint did not restore the player and regroup the buddy')

    client.place('pumped', 'atcargo', -3760, -3776, -3815, 0)
    cargo = client.run('cargo-lift', 'atcargo', ['impulse 3', *wait(335), 'save switch'])
    require('uplink: lift arrived' in cargo and origin(client.save('switch'))[2] > 1280,
            'cargo lift did not reach switchgear')
    client.place('switch', 'atpulse', -3200, -3750, 1305, 0)
    client.run('pulse-pickup', 'atpulse', ['impulse 21', 'wait', 'impulse 2', *wait(4), 'save armed'])
    client.place('armed', 'atguard', 3220, -3290, 1305, 0)
    fight = client.run('switch-room', 'atguard', ['+attack', 'wait', '-attack', *wait(120), 'save cleared'])
    require('uplink: pulse resolved' in fight and 'uplink: buddy fired' in fight
            and not named(client.save('cleared'), 'switch-guard'),
            'the pulse and buddy did not assist against the switchgear sentry')
    client.place('cleared', 'atswitch', 3300, -3228, 1305, 90)
    pulse = client.run('pulse-relay', 'atswitch',
                       ['+attack', 'wait', '-attack', *wait(22), 'save powered'])
    require('uplink: pulse resolved' in pulse and 'uplink: switchgear online' in pulse and
            number(named(client.save('powered'), 'mission-journal'), 'uplink-saved-flags') == 7,
            'pulse did not energize the switchgear relay')

    client.place('powered', 'atpick', 3600, 2850, 2585, 90)
    client.run('tether-pickup', 'atpick', ['impulse 6', *wait(5), 'save tether'])
    require(number(player(client.save('tether')), 'weapon') == 8, 'the gantry launcher did not equip')

    client.place('tether', 'atpull', -300, 3296, 2585, 292)
    pull = client.run('tether-pull', 'atpull', [*look_up(23), 'cl_shownet 2', '+attack',
                      *wait(9), 'save pulled', *wait(20), '-attack', 'cl_shownet 0',
                      *wait(16), 'save pullend'])
    require('uplink: tether attached' in pull and 'svc_temp_entity' in pull
            and origin(client.save('pullend'))[2] >= 2670, 'tether pull did not reach the landing ledge')
    client.place('tether', 'atblock', 150, 3500, 2585, 236)
    blocked = client.run('blocked-pull', 'atblock', [*look_up(12), '+attack', *wait(12),
                         '-attack', 'save blocked'])
    require('uplink: tether attached' not in blocked and origin(client.save('blocked'))[:2] == (150, 3500),
            'tether attached through a wall')
    client.place('tether', 'atswing', -410, 3127, 2585, 181)
    swing = client.run('tether-swing', 'atswing', [*look_up(19), '+attack', '+forward', *wait(10),
                       'save affixed', *wait(18), 'save swung', '-attack', '-forward',
                       *wait(4), 'save letgo', *wait(30), 'save landed'])
    require('uplink: tether attached' in swing and 'uplink: tether released' in swing
            and number(player(client.save('swung')), 'tether-anchor') > 0
            and number(player(client.save('letgo')), 'tether-anchor') == 0
            and origin(client.save('letgo'))[0] < origin(client.save('swung'))[0] - 35,
            'tether swing did not preserve momentum through release')
    require(2176 < origin(client.save('landed'))[2] < 2368, 'early release missed the catch lane')
    client.run('swing-landing', 'atswing', [*look_up(19), '+attack', '+forward', *wait(46),
               '-attack', *wait(28), '-forward', *wait(14), 'save farside'])
    fx, _, fz = origin(client.save('farside'))
    require(fx < -1300 and fz >= 2392, 'late release did not reach the far landing ramp')

    client.place('powered', 'atrecall', 3580, -2262, 2585, 90)
    recall = client.run('bike-recovery', 'atrecall', ['impulse 3', *wait(4), 'save recalled'])
    require('uplink: bike recalled' in recall, 'gantry service bay did not recover a bike')
    client.place('recalled', 'atbike', 3508, -2264, 2585, 90)
    client.run('gantry-dock', 'atbike', ['impulse 3', *wait(12), 'save ride'])
    require(number(player(client.save('ride')), 'riding') > 0, 'recovered bike would not mount')
    client.place('ride', 'atgantry', 3240, 3730, 2585, 180)
    gantry = client.run('gantry-relays', 'atgantry', ['+attack', *wait(290), '-attack', 'save relays'])
    require(gantry.count('uplink: gantry relay online') == 2 and
            number(named(client.save('relays'), 'mission-journal'), 'uplink-saved-flags') == 31,
            'riding through the gantries did not power both relays')
    client.place('relays', 'atroof', -3760, 3780, 2585, 0)
    roof = client.run('roof-lift', 'atroof', ['impulse 3', *wait(95), 'save rooftop'])
    require('uplink: lift arrived' in roof and origin(client.save('rooftop'))[2] > 3840,
            'roof lift did not reach the roof')
    client.place('rooftop', 'rooflane', -3456, 3720, 3865, 0)
    client.run('roof-ride', 'rooflane', ['+attack', *wait(357), '-attack', '+jump',
               *wait(30), '-jump', 'impulse 3', *wait(12), 'save endride'])
    client.place('endride', 'atextrac', 3890, 3622, 3865, 90)
    extract = client.run('extraction', 'atextrac', ['impulse 3', *wait(6), 'save finish'])
    require('uplink: mission complete' in extract and
            number(named(client.save('finish'), 'mission-journal'), 'uplink-saved-flags') == 63,
            'the restored mission journal did not permit roof extraction')
    snapshots = [read_edicts(path) for path in output.glob('*.sav')]
    measurements['max_saved_edicts'] = max(map(len, snapshots))
    measurements['max_saved_model_index'] = int(max(number(entry, 'modelindex')
                                                    for state in snapshots for entry in state))
    require(measurements['max_saved_edicts'] < 600 and measurements['max_saved_model_index'] < 256,
            'a stock save snapshot exceeded the edict or model budget')
    (output / 'measurements.json').write_text(json.dumps(measurements, indent=2) + '\n', encoding='ascii')
    return output / 'boot.log'


def coop_maps(output):
    stock_map = MAP_SOURCE.read_text(encoding='ascii')
    layouts = {
        'updock': ((-3316, -2258, 0, 270), (-3136, -2258, 0, 270)),
        'uppump': ((-2693, -3550, -3840, 0), (-3370, -3770, -3840, 0)),
        'uprope': ((-410, 3127, 2560, 181), (-342, 3154, 2560, 185)),
        'uptour': ((-3316, -2258, 0, 270), (-3136, -2258, 0, 270)),
    }
    with (output / 'coop-map-build.log').open('w') as log:
        for level, positions in layouts.items():
            source = output / f'{level}.map'
            document = MapDocument(stock_map)
            for kind, (x, y, z, yaw) in zip(('start', 'coop'), positions):
                index = next(i for i in range(len(document.entities))
                             if document.value(i, 'classname') == f'info_player_{kind}')
                position = coordinates((x, y, z + 24))
                document.set(index, 'origin', position)
                document.set(index, 'angle', str(yaw))
                if level == 'uprope':
                    document.add_entity({'classname': 'uplink_tether_supply', 'origin': position})
            if level == 'uptour':
                document.add_entity({'classname': 'uplink_tour_driver', 'origin': '-3750 -2000 24'})
                for command, stops in enumerate(TOUR_STOPS, 50):
                    for player_slot, (x, y, z, yaw) in enumerate(stops, 1):
                        document.add_entity({
                            'classname': 'uplink_tour_stop', 'origin': coordinates((x, y, z + 25)),
                            'angle': str(yaw), 'tour-command': str(command),
                            'tour-player': str(player_slot), 'tour-roof': str(int(command == 56)),
                            'tour-bike': str({54: 1, 55: 2}.get(command, 0)),
                        })
            source.write_text(document.text, encoding='ascii')
            subprocess.run([sys.executable, Path(__file__).with_name('build-signal.py'), '--source',
                            source, output / 'maps' / f'{level}.bsp'], stdout=log,
                           stderr=subprocess.STDOUT, check=True)


def run_coop(dosbox, output, env, host, guest, level, *rounds):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    def poll(round_index):
        return f'alias poll "exec go{round_index}.cfg; wait; wait; wait; wait; poll"'

    startup = poll(0) + '\npoll\n'
    host_cfg = f'hostname qsuplink\nname Host\ncoop 1\nhost_framerate 0.05\nmap {level}\n'
    (host / 'host.cfg').write_text(host_cfg + startup, encoding='ascii')
    (guest / 'guest.cfg').write_text('host_framerate 0.05\n' + startup, encoding='ascii')
    for mod in (host, guest):
        log = coop.console_file(mod)
        if log:
            log.unlink()
        for index in range(len(rounds) + 1):
            (mod / f'go{index}.cfg').write_text('', encoding='ascii')
    with coop.client(dosbox, output, env, host, f'{level}-host', f'ipxnet startserver {port}',
                     '-listen 2 +exec host.cfg') as server:
        coop.wait_for(server, host, lambda log: 'CL_SignonReply: 4' in log, f'{level} host did not sign on')
        with coop.client(dosbox, output, env, guest, f'{level}-guest', f'ipxnet connect 127.0.0.1 {port}',
                         '+name Guest +connect qsuplink +exec guest.cfg') as player:
            coop.wait_for(player, guest, lambda log: 'CL_SignonReply: 4' in log,
                          f'{level} guest did not sign on')
            for index, inputs in enumerate(rounds):
                marker = f'input-complete-{index:02d}'
                for mod, commands in zip((host, guest), inputs):
                    command = mod / 'next.cfg'
                    command.write_text('\n'.join([*commands, poll(index + 1), f'echo {marker}', '']),
                                       encoding='ascii')
                    command.replace(mod / f'go{index}.cfg')
                for process, mod, role in ((server, host, 'host'), (player, guest, 'guest')):
                    coop.wait_for(process, mod, lambda log: marker in log,
                                  f'{level} {role} did not finish input round {index}')
            return coop.read_console(host), coop.read_console(guest)


def verify_coop(dosbox, output, env, host, guest):
    ride = ['impulse 3', *wait(8), 'impulse 24', '+attack', *wait(20), '-attack']
    dock, _ = run_coop(dosbox, output, env, host, guest, 'updock',
                       (['impulse 21', *wait(12), *ride], [*wait(10), *ride]))
    bike_samples = [line.split() for line in dock.splitlines() if line.startswith('bike ')]
    require(dock.count('qslisp: bike mounted') == 2 and
            {sample[2] for sample in bike_samples if float(sample[6]) > 60} == {'1', '2'},
            'both co-op riders did not mount and ride separate bikes')
    pump, _ = run_coop(dosbox, output, env, host, guest, 'uppump',
                       (['impulse 3', *wait(8)], wait(10)))
    require('uplink: pumps online' in pump, 'the other client did not satisfy the valve interlock')
    equip = ['impulse 6', *wait(6), 'impulse 24']
    rope, _ = run_coop(dosbox, output, env, host, guest, 'uprope', (
        [*equip, *look_up(19), '+attack', '+forward', *wait(18), '-attack', '-forward', *wait(4)],
        [*equip, *look_up(16), '+attack', '+forward', *wait(35), '-attack', '-forward', *wait(4)],
    ))
    events = [tuple(map(float, line.split()[1:])) for line in rope.splitlines() if line.startswith('tether ')]
    require({(rider, attached) for _, rider, attached in events} == {(1, 1), (2, 1), (1, 0), (2, 0)}
            and max(time for time, _, attached in events if attached)
            < min(time for time, _, attached in events if not attached)
            and [rider for _, rider, attached in events if not attached] == [1, 2],
            f'co-op tethers did not attach simultaneously and release independently: {events}')
    verify_coop_tour(dosbox, output, env, host, guest)
    return output / 'uptour-host-qconsole.log'


def verify_coop_tour(dosbox, output, env, host, guest):
    # Only the test map receives the staging callback. Progression, lifts,
    # relay touches, and firing still run through the normal gameplay code.
    fixture = output / 'tour.dat'
    subprocess.run([sys.executable, '-m', 'qslisp', Path(__file__).with_name('uplink-tour.scm'),
                    '-o', fixture], cwd=MAP_SOURCE.parents[1], check=True)
    for mod in (host, guest):
        shutil.copyfile(fixture, mod / 'progs.dat')
    drive = ['impulse 3', *wait(8), '+attack', *wait(28), '-attack', *wait(12)]
    segments = [
        (['impulse 3', *wait(20)], wait(20)),
        (['impulse 3', *wait(20)], wait(20)),
        (['+attack', *wait(75), '-attack'], wait(75)),
        (['impulse 3', *wait(20)], wait(20)),
        (drive, drive),
        (['impulse 3', *wait(101)], wait(101)),
        (['impulse 3', *wait(10)], wait(10)),
    ]
    rounds = [(['impulse 21', *wait(12), 'impulse 3', *wait(12)],
               [*wait(12), 'impulse 3', *wait(12)])]
    for command, actions in enumerate(segments, 50):
        move = [f'impulse {command}', *wait(14)]
        rounds.extend(((move, move), actions))
    log, _ = run_coop(dosbox, output, env, host, guest, 'uptour', *rounds)
    reached = {tuple(map(int, line.split()[1:])) for line in log.splitlines() if line.startswith('tour ')}
    require(reached == {(command, slot) for command in range(50, 57) for slot in (1, 2)},
            f'co-op tour missed waypoints or the roof lift: {sorted(reached)}')
    require(log.count('uplink: gantry relay online') == 2 and 'uplink: mission complete' in log,
            'co-op tour did not complete the shared journal and extraction')
    return output / 'boot.log'
