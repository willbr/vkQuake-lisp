#!/usr/bin/env python3
"""Boot the Lisp example in an original DOS Quake installation via DOSBox Staging."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BOOT_MESSAGES = ('SpawnServer: start', 'qslisp: worldspawn', 'qslisp: StartFrame',
                 'qslisp: StartFrame', 'Server spawned.', 'qslisp: StartFrame')
WALK_CONTROLS = '''bind w +forward
bind a +moveleft
bind s +back
bind d +moveright
+mlook
'''


def boot(dosbox, quake_dir, output, *, play=False):
    program = output / 'progs.dat'
    subprocess.run([sys.executable, '-m', 'qslisp', 'examples/map-boot.scm', '-o', program],
                   cwd=ROOT, check=True)
    subprocess.run([sys.executable, 'tools/quakec/check-stock.py', program], cwd=ROOT, check=True)

    env = os.environ.copy()
    if not play:
        env.setdefault('SDL_VIDEODRIVER', 'dummy')
        env.setdefault('SDL_AUDIODRIVER', 'dummy')
    console = output / 'qconsole.log'
    with tempfile.TemporaryDirectory(dir=output) as staged:
        base = Path(staged)
        (base / 'id1').mkdir()
        mod = base / 'lispboot'
        mod.mkdir()
        for name in ('quake.exe', 'cwsdpmi.exe', 'id1/pak0.pak', 'id1/pak1.pak'):
            shutil.copyfile(quake_dir / name, base / name)
        shutil.copyfile(program, mod / 'progs.dat')

        engine_flags = '-noudp -noipx -condebug -game lispboot'
        if play:
            (mod / 'walk.cfg').write_text(WALK_CONTROLS, encoding='ascii')
            engine = f'quake -nocdaudio {engine_flags} +developer 1 +map start +exec walk.cfg'
        else:
            engine = f'quake -dedicated 1 {engine_flags} +developer 1 +map start +wait +quit'
        command = [dosbox, '--noprimaryconf', '--nolocalconf', '--noautoexec',
                   '-c', f'mount c "{base}"', '-c', 'c:', '-c', engine, '--exit']
        if play:
            print(f'Opening Quake. Click the window for mouse look and use WASD. Artifacts: {output}', flush=True)
        with (output / 'dosbox.log').open('w') as log:
            try:
                subprocess.run(command, cwd=base, env=env, stdout=log, stderr=subprocess.STDOUT,
                               timeout=None if play else 60, check=True)
            finally:
                for path in mod.iterdir():
                    if path.name.lower() == 'qconsole.log':
                        shutil.copyfile(path, console)
                        break

    if not console.is_file():
        raise RuntimeError('Quake did not write a console log')
    lines = console.read_text(encoding='cp437').splitlines()
    messages = (BOOT_MESSAGES[:-1] + ('qslisp: ClientConnect', 'qslisp: player spawned')
                if play else BOOT_MESSAGES)
    position = 0
    for message in messages:
        try:
            position = lines.index(message, position) + 1
        except ValueError:
            raise RuntimeError(f'expected {message!r} after line {position} in the Quake console log') from None
    return console


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--play', action='store_true', help='open the map in a graphical client with WASD and mouse look')
    parser.add_argument('dosbox', help='DOSBox Staging executable')
    parser.add_argument('quake_dir', type=Path, help='registered DOS Quake directory containing quake.exe and id1')
    args = parser.parse_args()
    dosbox = shutil.which(args.dosbox)
    if dosbox is None:
        parser.error(f'DOSBox Staging executable not found: {args.dosbox}')
    runs = ROOT / 'build/quakec/map-boot'
    runs.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='run-', dir=runs))
    try:
        console = boot(Path(dosbox).resolve(), args.quake_dir.resolve(), output, play=args.play)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        sys.exit(f'Map boot failed: {error}\nArtifacts: {output}')
    print(f'Stock Quake booted start and ran Lisp callbacks before and after startup. Log: {console}')


if __name__ == '__main__':
    main()
