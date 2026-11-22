#!/usr/bin/env python3
"""Boot the Lisp example in an original DOS Quake installation via DOSBox Staging."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import annex
import challenge
import coop
import uplink

ROOT = Path(__file__).resolve().parents[2]
BOOT_MESSAGES = ('qslisp: worldspawn', 'qslisp: StartFrame', 'qslisp: StartFrame', 'Server spawned.')
WALK_CONTROLS = '''bind w +forward
bind a +moveleft
bind s +back
bind d +moveright
bind leftarrow +left
bind rightarrow +right
bind f +attack
bind space +jump
bind mouse1 +attack
bind 1 "impulse 1"
bind 2 "impulse 2"
bind 3 "impulse 6"
bind e "impulse 3"
alias buddy_follow "impulse 21"
alias buddy_wait "impulse 22"
alias buddy_regroup "impulse 23"
alias gameplay_trace "impulse 24"
bind r restart
+mlook
'''


def wait_for_annex(command, base, mod, env, log):
    # Quake appends changelevel to its command buffer. Let the cfg finish and
    # observe the new map's signon before closing the emulator.
    with subprocess.Popen(command, cwd=base, env=env, stdout=log, stderr=subprocess.STDOUT) as engine:
        deadline = time.monotonic() + 60
        try:
            while engine.poll() is None and time.monotonic() < deadline:
                console = next((path for path in mod.iterdir() if path.name.lower() == 'qconsole.log'), None)
                if console:
                    _, separator, tail = console.read_bytes().partition(b'SpawnServer: annex')
                    if separator and b'CL_SignonReply: 4' in tail:
                        return
                time.sleep(0.1)
            raise RuntimeError('the scripted client did not finish signing on to Relay Annex')
        finally:
            if engine.poll() is None:
                engine.terminate()
                try:
                    engine.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    engine.kill()


def prepare(output, maps):
    program = output / 'progs.dat'
    subprocess.run([sys.executable, '-m', 'qslisp', 'examples/map-boot.scm', '-o', program],
                   cwd=ROOT, check=True)
    subprocess.run([sys.executable, 'tools/quakec/check-stock.py', program], cwd=ROOT, check=True)
    if maps:
        (output / 'maps').mkdir()
        with (output / 'map-build.log').open('w') as log:
            for name in maps:
                subprocess.run([sys.executable, 'tools/quakec/build-signal.py', '--map', name,
                                output / 'maps' / f'{name}.bsp'],
                               cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    if 'annex' in maps or 'uplink' in maps:
        subprocess.run([sys.executable, 'tools/quakec/build-sentry.py', output / 'progs/sentry.mdl'],
                       cwd=ROOT, check=True)
        subprocess.run([sys.executable, 'tools/quakec/build-bike.py', output], cwd=ROOT, check=True)
    if 'uplink' in maps:
        subprocess.run([sys.executable, 'tools/quakec/build-uplink-assets.py', output], cwd=ROOT, check=True)


def stage(quake_dir, output, base):
    (base / 'id1').mkdir(parents=True)
    mod = base / 'lispboot'
    mod.mkdir()
    for name in ('quake.exe', 'cwsdpmi.exe', 'id1/pak0.pak', 'id1/pak1.pak'):
        shutil.copyfile(quake_dir / name, base / name)
    shutil.copyfile(output / 'progs.dat', mod / 'progs.dat')
    for name in ('maps', 'progs', 'sound'):
        if (output / name).is_dir():
            shutil.copytree(output / name, mod / name)
    return mod


def engine_env(play):
    env = os.environ.copy()
    if not play:
        env.setdefault('SDL_VIDEODRIVER', 'dummy')
        env.setdefault('SDL_AUDIODRIVER', 'dummy')
        env.setdefault('SDL_RENDER_DRIVER', 'software')
    return env


def boot(dosbox, quake_dir, output, *, level, play=False, verify=False, protected_cycles=None):
    maps = {'start': (), 'signal': ('signal', 'annex'), 'annex': ('annex',), 'uplink': ('uplink',)}[level]
    prepare(output, maps)
    env = engine_env(play)
    console = output / 'qconsole.log'
    with tempfile.TemporaryDirectory(dir=output) as staged:
        base = Path(staged)
        mod = stage(quake_dir, output, base)
        if verify and level == 'uplink':
            return uplink.verify(dosbox, output, env, base, mod)

        engine_flags = '-noudp -noipx -condebug -game lispboot'
        if play:
            (mod / 'walk.cfg').write_text(WALK_CONTROLS, encoding='ascii')
            engine = f'quake -nocdaudio {engine_flags} +developer 1 +map {level} +exec walk.cfg'
        elif verify:
            scenario = annex if level == 'annex' else challenge
            (mod / 'verify.cfg').write_text(scenario.verification_commands(), encoding='ascii')
            engine = f'quake -nosound -nocdaudio {engine_flags} +developer 1 +map {level} +exec verify.cfg'
        else:
            engine = f'quake -dedicated 1 {engine_flags} +developer 1 +map {level} +wait +quit'
        command = [dosbox, '--noprimaryconf', '--nolocalconf', '--noautoexec']
        if protected_cycles:
            command += ['--set', f'cpu_cycles_protected={protected_cycles}']
        command += ['-c', f'mount c "{base}"', '-c', 'c:', '-c', engine, '--exit']
        if play:
            print(f'Opening Quake. WASD to walk, Space to jump, click to fire, E to use, R to reset. Artifacts: {output}',
                  flush=True)
        artifacts = {'qconsole.log'}
        if verify:
            artifacts.update({f'{name}.sav' for name in scenario.SAVES} | {f'quake{i:02d}.pcx' for i in range(6)})
        with (output / 'dosbox.log').open('w') as log:
            try:
                if verify and level == 'signal':
                    wait_for_annex(command, base, mod, env, log)
                else:
                    subprocess.run(command, cwd=base, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   timeout=None if play else 60, check=True)
            finally:
                for path in mod.iterdir():
                    name = path.name.lower()
                    if name in artifacts:
                        shutil.copyfile(path, output / name)

    if not console.is_file():
        raise RuntimeError('Quake did not write a console log')
    lines = [line.strip() for line in console.read_text(encoding='cp437').splitlines()]
    callbacks = ('qslisp: ClientConnect', 'qslisp: player spawned', 'CL_SignonReply: 4') if play or verify else (
        'qslisp: StartFrame',)
    messages = (f'SpawnServer: {level}', *BOOT_MESSAGES, *callbacks)
    position = 0
    for message in messages:
        try:
            position = lines.index(message, position) + 1
        except ValueError:
            raise RuntimeError(f'expected {message!r} after line {position} in the Quake console log') from None
    if verify:
        if level == 'annex':
            annex.verify_annex(output, lines)
        else:
            challenge.verify_challenge(output, lines)
    return console


def boot_coop(dosbox, quake_dir, output, level):
    new_mission = level == 'uplink'
    prepare(output, ('uplink',) if new_mission else ('signal', 'annex'))
    if new_mission:
        uplink.coop_maps(output)
    with tempfile.TemporaryDirectory(dir=output) as staged:
        base = Path(staged)
        host = stage(quake_dir, output, base / 'host')
        guest = stage(quake_dir, output, base / 'guest')
        scenario = uplink.verify_coop if new_mission else coop.verify
        return scenario(dosbox, output, engine_env(False), host, guest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--play', action='store_true', help='open the map in a graphical client')
    mode.add_argument('--verify', action='store_true', help='test a Lisp map in a scripted client')
    mode.add_argument('--verify-coop', action='store_true', help='test the campaign or uplink with two IPX clients')
    parser.add_argument('--protected-cycles', type=int, help='set DOSBox Staging protected-mode cycles for --play')
    parser.add_argument('--map', choices=('start', 'signal', 'annex', 'uplink'),
                        help='map to load (default: start, or signal with --verify)')
    parser.add_argument('dosbox', help='DOSBox Staging executable')
    parser.add_argument('quake_dir', type=Path, help='registered DOS Quake directory containing quake.exe and id1')
    args = parser.parse_args()
    level = args.map or ('signal' if args.verify else 'start')
    if args.verify and level == 'start':
        parser.error('--verify requires signal, annex, or uplink')
    if args.verify_coop and args.map not in (None, 'uplink'):
        parser.error('--verify-coop runs the campaign by default or the uplink with --map uplink')
    if args.protected_cycles is not None and (not args.play or args.protected_cycles <= 0):
        parser.error('--protected-cycles requires a positive value and --play')
    dosbox = shutil.which(args.dosbox)
    if dosbox is None:
        parser.error(f'DOSBox Staging executable not found: {args.dosbox}')
    runs = ROOT / 'build/quakec/map-boot'
    runs.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='run-', dir=runs))
    try:
        if args.verify_coop:
            console = boot_coop(Path(dosbox).resolve(), args.quake_dir.resolve(), output, level)
        else:
            console = boot(Path(dosbox).resolve(), args.quake_dir.resolve(), output,
                           level=level, play=args.play, verify=args.verify,
                           protected_cycles=args.protected_cycles)
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as error:
        sys.exit(f'Map boot failed: {error}\nArtifacts: {output}')
    if args.verify_coop and level == 'uplink':
        print(f'Two stock Quake clients tested the uplink bikes, pump, and tethers. Logs: {console.parent}')
    elif args.verify_coop:
        print(f'Two stock Quake clients completed Signal Room and reached Relay Annex. Logs: {console.parent}')
    elif args.verify and level == 'uplink':
        print(f'Stock Quake reached uplink extraction and verified the save chain. Logs: {console.parent}')
    else:
        print(f'Stock Quake booted {level} and ran Lisp callbacks before and after startup. Log: {console}')


if __name__ == '__main__':
    main()
