import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from qslisp.vm_tools import assemble, disassemble

ROOT = Path(__file__).resolve().parents[2]


class VMToolsTests(unittest.TestCase):
    def test_branch_fixture_runs_in_stock_vm(self):
        program = assemble("""
            .float zero 0
            .float a 11
            .float b 31
            .function main 3
                IFNOT zero sum
                RETURN zero
            sum:
                ADD_F a b %0
                RETURN %0
            .end
        """, 'branch.qca')
        listing = disassemble(program)
        self.assertIn('locals=3', listing)
        self.assertIn('IFNOT', listing)
        self.assertIn('L3:', listing)
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / 'fixture.dat'
            fixture.write_bytes(program)
            result = subprocess.run([ROOT / 'tools/quakec/run-stock.sh', fixture, 'main'],
                                    capture_output=True, text=True, check=True)
        self.assertIn('return: 42', result.stdout)

    def test_symbols_indicate_expressions_without_changing_game_bytecode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'test.scm'
            source.write_text('(define (test x)\n  (if (< x 4)\n      (+ x 1)\n      (- x 1)))\n')
            output = root / 'progs.dat'
            plain = root / 'plain.dat'
            for dest, option in ((output, ['--symbols']), (plain, [])):
                subprocess.run([sys.executable, '-m', 'qslisp', source, '-o', dest, *option],
                               cwd=ROOT, capture_output=True, check=True)
            data = output.read_bytes()
            self.assertEqual(data, plain.read_bytes())
            sidecar = json.loads(output.with_suffix('.sym').read_text())
            names = {item['line'] for item in sidecar['ranges'] if item['file'] == str(source)}
            self.assertTrue({2, 3, 4} <= names)
            listing = disassemble(data, sidecar)
            self.assertIn(f'{source}:3:', listing)
            with self.assertRaisesRegex(ValueError, 'do not match'):
                disassemble(data, {**sidecar, 'sha256': 'wrong'})

    def test_assembler_rejects_unresolved_branch(self):
        with self.assertRaisesRegex(ValueError, 'unknown or empty branch target'):
            assemble('.function main 0\n GOTO missing\n.end')


if __name__ == '__main__':
    unittest.main()
