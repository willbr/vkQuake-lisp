"""python3 -m qslisp SOURCE.scm -o progs.dat"""
import argparse
import json
from pathlib import Path
import sys

from .compiler import Compiler
from .modules import load_forms
from .reader import CompileError
from .vm_tools import symbols


def main():
    parser = argparse.ArgumentParser(description='Compile a small Scheme-style Lisp to stock Quake v6 bytecode.')
    parser.add_argument('source', type=Path)
    parser.add_argument('-o', '--output', type=Path, required=True)
    parser.add_argument('--heap-pairs', type=int, default=512,
                        help='pair cells available to one engine entry (default: 512)')
    parser.add_argument('--report', action='store_true', help='print storage and bytecode statistics as JSON')
    parser.add_argument('--symbols', action='store_true', help='write a matching .sym source map alongside the bytecode')
    args = parser.parse_args()
    try:
        compiler = Compiler(load_forms(args.source.read_text(encoding='utf-8'), str(args.source)), str(args.source),
                            heap_pairs=args.heap_pairs)
        data = compiler.compile()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(data)
        if args.symbols:
            args.output.with_suffix('.sym').write_text(
                json.dumps(symbols(compiler.program, data), ensure_ascii=False, indent=2) + '\n',
                encoding='utf-8')
    except (CompileError, OSError, UnicodeError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f'Wrote {args.output} ({len(data):,} bytes, stock Quake v6)')
    if args.report:
        print(json.dumps(compiler.statistics(), indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
