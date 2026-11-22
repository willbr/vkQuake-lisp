#!/usr/bin/env python3
"""Boot the Lisp example in an original DOS Quake installation via DOSBox Staging."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from challenge import SAVES, verification_commands, verify_challenge

ROOT = Path(__file__).resolve().parents[2]
BOOT_MESSAGES = ('qslisp: worldspawn', 'qslisp: StartFrame', 'qslisp: StartFrame', 'Server spawned.')
WALK_CONTROLS = '''bind w +forward
bind a +moveleft
bind s +back
bind d +moveright
bind space +jump
bind mouse1 +attack
bind r "map {level}"
+mlook
'''


def boot(dosbox, quake_dir, output, *, level, play=False, verify=False):
    program = output / 'progs.dat'
    subprocess.run([sys.executable, '-m', 'qslisp', 'examples/map-boot.scm', '-o', program],
                   cwd=ROOT, check=True)
    subprocess.run([sys.executable, 'tools/quakec/check-stock.py', program], cwd=ROOT, check=True)
    if level == 'signal':
        (output / 'maps').mkdir()
        with (output / 'map-build.log').open('w') as log:
            subprocess.run([sys.executable, 'tools/quakec/build-signal.py', output / 'maps/signal.bsp'],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)

    env = os.environ.copy()
    if not play:
        env.setdefault('SDL_VIDEODRIVER', 'dummy')
        env.setdefault('SDL_AUDIODRIVER', 'dummy')
        env.setdefault('SDL_RENDER_DRIVER', 'software')
    console = output / 'qconsole.log'
    with tempfile.TemporaryDirectory(dir=output) as staged:
        base = Path(staged)
        (base / 'id1').mkdir()
        mod = base / 'lispboot'
        mod.mkdir()
        for name in ('quake.exe', 'cwsdpmi.exe', 'id1/pak0.pak', 'id1/pak1.pak'):
            shutil.copyfile(quake_dir / name, base / name)
        shutil.copyfile(program, mod / 'progs.dat')
        if level == 'signal':
            shutil.copytree(output / 'maps', mod / 'maps')

        engine_flags = '-noudp -noipx -condebug -game lispboot'
        if play:
            (mod / 'walk.cfg').write_text(WALK_CONTROLS.format(level=level), encoding='ascii')
            engine = f'quake -nocdaudio {engine_flags} +developer 1 +map {level} +exec walk.cfg'
        elif verify:
            (mod / 'verify.cfg').write_text(verification_commands(), encoding='ascii')
            engine = f'quake -nosound -nocdaudio {engine_flags} +developer 1 +map {level} +exec verify.cfg'
        else:
            engine = f'quake -dedicated 1 {engine_flags} +developer 1 +map {level} +wait +quit'
        command = [dosbox, '--noprimaryconf', '--nolocalconf', '--noautoexec',
                   '-c', f'mount c "{base}"', '-c', 'c:', '-c', engine, '--exit']
        if play:
            print(f'Opening Quake. WASD to walk, Space to jump, click to fire, R to reset. Artifacts: {output}',
                  flush=True)
        artifacts = {'qconsole.log'}
        if verify:
            artifacts.update({f'{name}.sav' for name in SAVES} | {'quake00.pcx', 'quake01.pcx'})
        with (output / 'dosbox.log').open('w') as log:
            try:
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
        verify_challenge(output, lines)
    return console


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--play', action='store_true', help='open the map in a graphical client')
    mode.add_argument('--verify', action='store_true', help='test and profile the Signal Room in a scripted client')
    parser.add_argument('--map', choices=('start', 'signal'), help='map to load (default: start, or signal with --verify)')
    parser.add_argument('dosbox', help='DOSBox Staging executable')
    parser.add_argument('quake_dir', type=Path, help='registered DOS Quake directory containing quake.exe and id1')
    args = parser.parse_args()
    level = args.map or ('signal' if args.verify else 'start')
    if args.verify and level != 'signal':
        parser.error('--verify requires the signal map')
    dosbox = shutil.which(args.dosbox)
    if dosbox is None:
        parser.error(f'DOSBox Staging executable not found: {args.dosbox}')
    runs = ROOT / 'build/quakec/map-boot'
    runs.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='run-', dir=runs))
    try:
        console = boot(Path(dosbox).resolve(), args.quake_dir.resolve(), output,
                       level=level, play=args.play, verify=args.verify)
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as error:
        sys.exit(f'Map boot failed: {error}\nArtifacts: {output}')
    print(f'Stock Quake booted {level} and ran Lisp callbacks before and after startup. Log: {console}')


if __name__ == '__main__':
    main()
