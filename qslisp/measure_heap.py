"""Measure the generated pair arena on the original interpreter, without game data."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from .bytecode import Frame, OP_CALL0, OP_STORE, OP_STORE_V, OP_RETURN
from .compiler import Compiler
from .reader import read

ROOT = Path(__file__).resolve().parents[1]


def probe(compiler, entry):
    """Add a VM-only thunk that runs entry and returns the arena's allocation pointer.

    Native host code remains unchanged. The thunk reads the runtime's existing
    counter using ordinary stock bytecode after the entry returns.
    """
    name = '__qslisp_benchmark_cells_in_use'
    index = compiler.program.function(name, '<heap-benchmark>', 0)
    frame = Frame(compiler.program, index, compiler.program.location, 0, 1)
    frame.emit(OP_CALL0, compiler.program.names[entry])
    result = frame.allocate()
    frame.emit(OP_STORE_V, compiler.zero, result)
    frame.emit(OP_STORE, compiler.heap.next, result)
    frame.emit(OP_RETURN, result)
    frame.finish()
    return compiler.program.encode(), name


def execute(path, entry):
    result = subprocess.run([str(ROOT / 'tools/quakec/run-stock.sh'), str(path), entry],
                            capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return {'return': float(re.search(r'^return: (.+)$', result.stdout, re.M)[1]),
            'instructions': int(re.search(r'^instructions: (\d+)$', result.stdout, re.M)[1])}


def measure(directory):
    directory.mkdir(parents=True, exist_ok=True)
    source = (ROOT / 'examples/pairs.scm').read_text()
    reports = []
    for pairs in (128, 512, 1024):
        compiler = Compiler(read(source, 'examples/pairs.scm'), 'examples/pairs.scm', heap_pairs=pairs)
        data = compiler.compile()
        path = directory / f'pairs-{pairs}.dat'
        path.write_bytes(data)
        report = {**compiler.statistics(), 'file_bytes': len(data),
                  'acceptance': execute(path, 'test'), 'churn': execute(path, 'churn-test')}
        image, name = probe(compiler, 'churn-test')
        probe_path = directory / f'probe-{pairs}.dat'
        probe_path.write_bytes(image)
        report['cells_in_use_after_return'] = int(execute(probe_path, name)['return'])
        if (report['acceptance']['return'] != 16 or report['churn']['return'] != 16
                or report['cells_in_use_after_return']):
            raise RuntimeError(f'incorrect heap result: {report}')
        reports.append(report)
    return reports


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'build/heap-benchmark')
    args = parser.parse_args()
    reports = measure(args.output_dir)
    output = json.dumps(reports, indent=2)
    (args.output_dir / 'report.json').write_text(output + '\n')
    print(output)
