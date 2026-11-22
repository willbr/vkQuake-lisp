"""python3 -m qslisp SOURCE.scm -o progs.dat"""
import argparse
import json
from pathlib import Path
import sys

from .compiler import Compiler
from .modules import load_forms
from .reader import CompileError


def main():
    parser = argparse.ArgumentParser(description='Compile a small Scheme-style Lisp to stock Quake v6 bytecode.')
    parser.add_argument('source', type=Path)
    parser.add_argument('-o', '--output', type=Path, required=True)
    parser.add_argument('--heap-pairs', type=int, default=256, help='fixed pair capacity (default: 256)')
    parser.add_argument('--root-slots', type=int, default=256, help='shadow root capacity (default: 256)')
    parser.add_argument('--report', action='store_true', help='print storage and bytecode statistics as JSON')
    args = parser.parse_args()
    try:
        compiler = Compiler(load_forms(args.source.read_text(encoding='utf-8'), str(args.source)), str(args.source),
                            heap_pairs=args.heap_pairs, root_slots=args.root_slots)
        data = compiler.compile()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(data)
    except (CompileError, OSError, UnicodeError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f'Wrote {args.output} ({len(data):,} bytes, stock Quake v6)')
    if args.report:
        print(json.dumps(compiler.statistics(), indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
