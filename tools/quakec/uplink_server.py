"""Run the Lisp freight lift driver with a dedicated DOS Quake server over IPX."""
import re
import socket

import coop
from challenge import require
from map_editor import MapDocument
from uplink import MAP_SOURCE


def write_fixture(destination):
    document = MapDocument(MAP_SOURCE.read_text(encoding='ascii'))
    for classname, origin, yaw in (
        ('info_player_start', '3275 -1472 -1256', '80'),
        ('qslisp_bike', '3290 -1390 -1256', '75'),
    ):
        index = next(i for i in range(len(document.entities))
                     if document.value(i, 'classname') == classname)
        document.set(index, 'origin', origin)
        document.set(index, 'angle', yaw)
    destination.write_text(document.text, encoding='ascii')


def verify(dosbox, output, env, host, guest, *, watch_env=None):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    (host / 'driver.cfg').write_text(
        'hostname uplinktest\nsys_ticrate 0.05\nhost_framerate 0.05\nmap uplink\n', encoding='ascii')
    with coop.client(dosbox, output, env, host, 'server', f'ipxnet startserver {port}',
                     '-dedicated 2 +exec driver.cfg') as server:
        coop.wait_for(server, host, lambda log: 'Server spawned.' in log, 'dedicated server did not spawn')
        with coop.client(dosbox, output, watch_env if watch_env is not None else env,
                         guest, 'rider', f'ipxnet connect 127.0.0.1 {port}',
                         '+name TestRider +connect uplinktest') as rider:
            coop.wait_for(rider, guest, lambda log: 'CL_SignonReply: 4' in log, 'rider did not sign on')
            coop.wait_for(server, host, lambda log: 'lift-test: passed' in log or 'lift-test failure' in log,
                          'server did not report a freight lift result')
            server_log, rider_log = coop.read_console(host), coop.read_console(guest)
            require(rider.poll() is None and 'CL_EstablishConnection: connected to uplinktest' in rider_log,
                    'rider did not stay connected over IPX')
            check_lift(server_log)
            if watch_env is not None:
                (output / 'server-qconsole.log').write_text(server_log, encoding='cp437')
                (output / 'rider-qconsole.log').write_text(rider_log, encoding='cp437')
                print('Freight lift test passed. The 3D client is open at the flood deck.', flush=True)
                rider.wait()
    return output / 'server-qconsole.log'


def check_lift(server_log):
    failure = next((line for line in server_log.splitlines() if line.startswith('lift-test failure')), None)
    require(failure is None, failure)
    order = ('qslisp: ClientConnect', 'lift-test: mounting', 'qslisp: bike mounted',
             'lift-test called', 'uplink: lift departing', 'uplink: lift arrived',
             'lift-test: platform at freight landing', 'lift-test: rider standing on platform',
             'uplink: lift departing', 'uplink: lift arrived', 'lift-test: passed')
    offset = 0
    for marker in order:
        index = server_log.find(marker, offset)
        require(index >= 0, f'expected server event {marker!r} after offset {offset}')
        offset = index + len(marker)
    called = re.search(r'^lift-test called x/y/heading +([^\r\n]+)', server_log, re.M)
    arrived = re.search(r'^lift-test arrived rider-z/platform-z/samples +([^\r\n]+)', server_log, re.M)
    require(called is not None and arrived is not None, 'server omitted measured positions')
    x, y, heading = map(float, called[1].split())
    require(abs(x - 3344) < 24 and abs(y + 1245) < 24 and abs(heading - 75) > 5,
            'rider did not steer from the angled start to the lift landing')
    rider_z, platform_z, samples = map(float, arrived[1].split())
    require(abs(rider_z + 2536) < 2 and abs(platform_z + 2560) < 1 and samples > 20,
            'rider did not travel from freight to the flood deck on the platform')
    parked = re.findall(r'^lift-test parked camera-z/client-pitch +([^\r\n]+)', server_log, re.M)
    require(len(parked) >= 15, 'server omitted parked camera samples')
    heights, pitches = zip(*(map(float, sample.split()) for sample in parked))
    require(max(heights) - min(heights) < 0.3, f'parked camera height moved: {min(heights)} to {max(heights)}')
    require(min(pitches) >= 16.8 and max(pitches) - min(pitches) < 0.2,
            f'parked client pitch drifted: {min(pitches)} to {max(pitches)} degrees')
