#!/usr/bin/env python3
"""Compare the Lisp dog with id's dog.qc in stock bytecode.

Greenspun's tenth rule says any sufficiently complicated C program contains
an ad hoc, informally-specified, bug-ridden, slow implementation of half of
Common Lisp. This counts what one Quake monster costs in each language."""
import argparse
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FUNCTION = struct.Struct('<7i8B')


def functions(data):
    header = struct.unpack_from('<15i', data)
    statements_offset, statement_count = header[2:4]
    offset, count = header[8:10]
    strings = data[header[10]:header[10] + header[11]]

    def name(at):
        return strings[at:strings.index(b'\0', at)].decode('ascii', 'replace')

    records = [FUNCTION.unpack_from(data, offset + i * FUNCTION.size) for i in range(count)]
    starts = sorted(first for first, *_ in records if first > 0) + [statement_count]
    for first, _, local_count, _, s_name, s_file, *_ in records:
        if first > 0:
            end = next(start for start in starts if start > first)
            yield name(s_name), name(s_file), end - first, local_count


def measure(data, source_suffix):
    rows = [row for row in functions(data) if row[1].endswith(source_suffix)]
    return {'functions': len(rows), 'statements': sum(row[2] for row in rows),
            'locals': sum(row[3] for row in rows)}


def source_lines(path, comment):
    return sum(1 for line in path.read_text(encoding='utf-8', errors='replace').splitlines()
               if line.strip() and not line.strip().startswith(comment))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, default=ROOT / 'build/quakec/reference/progs.dat')
    parser.add_argument('--qc', type=Path, default=ROOT / 'build/quakec/reference/progs/dog.qc')
    args = parser.parse_args()
    if not args.reference.is_file():
        parser.exit(1, 'Missing the reference progs.dat. Run ./tools/quakec/setup.sh first.\n')
    lisp_program = ROOT / 'build/greenspun.dat'
    subprocess.run([sys.executable, '-m', 'qslisp', 'examples/map-boot.scm', '-o', lisp_program],
                   cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    lisp = measure(lisp_program.read_bytes(), 'dog.scm')
    quakec = measure(args.reference.read_bytes(), 'dog.qc')
    lisp['source lines'] = source_lines(ROOT / 'examples/dog.scm', ';')
    quakec['source lines'] = source_lines(args.qc, '//')
    print(f"{'':16}{'dog.qc':>10}{'dog.scm':>10}")
    for key in ('source lines', 'functions', 'statements', 'locals'):
        print(f'{key:16}{quakec[key]:>10}{lisp[key]:>10}')


if __name__ == '__main__':
    main()
