"""Drive two stock DOS Quake clients over DOSBox's local IPX tunnel."""
from contextlib import contextmanager
import shutil
import socket
import subprocess
import time

from challenge import require


def guest_commands():
    commands = ['host_framerate 0.05', 'con_notifytime 0'] + ['wait'] * 40
    commands += ['+attack'] + ['wait'] * 4 + ['-attack'] + ['wait'] * 12
    # The spawn faces the host. Turn 180 degrees to face the target; the
    # first key-down frame in the stock client contributes half its angle.
    commands += ['cl_yawspeed 1028.5714', '+left'] + ['wait'] * 4 + ['-left', 'cl_yawspeed 140']
    commands += ['wait'] * 6 + ['+attack'] + ['wait'] * 4 + ['-attack'] + ['wait'] * 15
    commands += ['+forward'] + ['wait'] * 65 + ['-forward'] + ['wait'] * 5 + ['impulse 3']
    commands += ['wait'] * 60 + ['+moveleft'] + ['wait'] * 14 + ['-moveleft']
    commands += ['wait'] * 28 + ['kill'] + ['wait'] * 15
    commands += ['+attack'] + ['wait'] * 4 + ['-attack'] + ['wait'] * 10 + ['echo coop-client-finished']
    return '\n'.join(commands) + '\n'


def console_file(mod):
    return next((path for path in mod.iterdir() if path.name.lower() == 'qconsole.log'), None)


def read_console(mod):
    path = console_file(mod)
    return path.read_text(encoding='cp437') if path else ''


def wait_for(process, mod, predicate, failure):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if predicate(read_console(mod)):
            return
        if process.poll() is not None:
            break
        time.sleep(0.05)
    raise RuntimeError(failure)


@contextmanager
def client(dosbox, output, env, mod, role, ipx, arguments):
    command = [dosbox, '--noprimaryconf', '--nolocalconf', '--noautoexec', '--set', 'ipx=true',
               '-c', ipx, '-c', f'mount c "{mod.parent}"', '-c', 'c:', '-c',
               f'quake -nosound -nocdaudio -noudp -condebug -game lispboot +developer 1 {arguments}', '--exit']
    with (output / f'{role}-dosbox.log').open('w') as log:
        with subprocess.Popen(command, cwd=mod.parent, env=env, stdout=log, stderr=subprocess.STDOUT) as process:
            try:
                yield process
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                console = console_file(mod)
                if console:
                    shutil.copyfile(console, output / f'{role}-qconsole.log')


def verify(dosbox, output, env, host, guest):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    (host / 'host.cfg').write_text('hostname lispcoop\nname Host\ncoop 1\nhost_framerate 0.05\nmap signal\n',
                                   encoding='ascii')
    (guest / 'coop.cfg').write_text(guest_commands(), encoding='ascii')
    host_command = '-listen 2 +exec host.cfg'
    guest_command = '+name Guest +connect lispcoop +exec coop.cfg'
    with client(dosbox, output, env, host, 'host', f'ipxnet startserver {port}', host_command) as server:
        wait_for(server, host, lambda log: 'CL_SignonReply: 4' in log.partition('SpawnServer: signal')[2],
                 'co-op host did not enter Signal Room')
        with client(dosbox, output, env, guest, 'guest', f'ipxnet connect 127.0.0.1 {port}', guest_command) as player:
            wait_for(player, guest, lambda log: 'coop-client-finished' in log, 'co-op guest input script did not finish')
            host_log, guest_log = read_console(host), read_console(guest)
    require('CL_EstablishConnection: connected to lispcoop' in guest_log, 'guest did not connect over IPX')
    require(guest_log.count('CL_SignonReply: 4') == 2, 'guest did not enter both levels')
    require(host_log.count('CL_SignonReply: 4') == 2, 'host did not enter both levels')
    after = 0
    for marker in ('qslisp: player spawned at co-op start', 'qslisp: co-op friendly fire blocked',
                   'qslisp: target hit', 'qslisp: gate open', 'qslisp: level complete',
                   'qslisp: changing to Relay Annex', 'SpawnServer: annex',
                   'qslisp: player spawned at co-op start', 'qslisp: sentry spotted co-op guest',
                   'qslisp: player defeated', 'qslisp: player spawned at co-op start', 'qslisp: player respawned'):
        index = host_log.find(marker, after)
        require(index >= 0, f'co-op host did not log {marker!r} after the preceding event')
        after = index + len(marker)
    return output / 'host-qconsole.log'
