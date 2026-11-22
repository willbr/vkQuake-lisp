"""Run with python3 -m unittest discover -s tools/quakec/tests -v after setup."""
import importlib.util
from pathlib import Path
import shutil
import struct
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('stock', ROOT / 'tools/quakec/check-stock.py')
STOCK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STOCK)


class StockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = ROOT / 'build/quakec/stock-tests'
        sources = cls.work / 'progs'
        shutil.copytree(ROOT / 'third_party/quake-tools/qcc/v101qc', sources, dirs_exist_ok=True)
        shutil.copy(ROOT / 'tools/quakec/tests/smoke.qc', sources / 'smoke.qc')
        manifest = sources / 'progs.src'
        manifest.write_text(manifest.read_text() + '\nsmoke.qc\n')
        result = subprocess.run([str(ROOT / 'build/quakec/bin/fteqcc'), '-Tq1', '-O0'],
                                cwd=sources, capture_output=True, text=True, timeout=30)
        (cls.work / 'compile.log').write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.program = cls.work / 'progs.dat'
        cls.data = cls.program.read_bytes()
        cls.header = STOCK.validate(cls.data)

    def run_vm(self, function, *args):
        return subprocess.run([str(ROOT / 'tools/quakec/run-stock.sh'), str(self.program),
                               function, *args], capture_output=True, text=True, timeout=10)

    def test_arithmetic_vectors_branches_calls_and_print(self):
        result = self.run_vm('stock_smoke')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('stock CLI smoke ok', result.stdout)
        self.assertIn('return: 42\n', result.stdout)
        self.assertRegex(result.stdout, r'instructions: [1-9]\d*')

    def test_float_arguments(self):
        result = self.run_vm('stock_twice', '21')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('return: 42\n', result.stdout)

    def test_original_instruction_watchdog(self):
        result = self.run_vm('stock_watchdog')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('runaway loop error', result.stdout)

    def test_original_stack_limit(self):
        result = self.run_vm('stock_overflow')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('stack overflow', result.stdout)

    def test_engine_builtin_is_not_silently_stubbed(self):
        result = self.run_vm('stock_engine_builtin')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('builtin #20', result.stderr)
        self.assertIn('requires the game engine', result.stderr)

    def test_cli_errors(self):
        for function, args, expected in [
            ('missing_function', (), 'function not found'),
            ('stock_twice', (), 'expects 1 arguments'),
            ('stock_twice', ('abc',), 'invalid float'),
            ('random', (), 'entry must be a bytecode function'),
        ]:
            with self.subTest(function=function, args=args):
                result = self.run_vm(function, *args)
                self.assertEqual(result.returncode, 2)
                self.assertIn(expected, result.stderr)

    def test_rejects_nonstock_or_malformed_output(self):
        h = self.header
        self_definition = next(i for i in range(h[5])
                               if struct.unpack_from('<HHi', self.data, h[4] + i * 8)[1] == 28)
        ordinary = next(i for i in range(1, h[9])
                        if struct.unpack_from('<i', self.data, h[8] + i * 36)[0] > 0)
        cases = [
            (0, '<i', (7,), 'version 6'),
            (4, '<i', (0,), 'ABI CRC'),
            (52, '<i', (32769,), 'signed-address'),
            (h[2] + 8, '<Hhhh', (66, 0, 0, 0), 'nonstock opcode'),
            (h[2] + 8, '<Hhhh', (6, -32768, 0, 0), 'signed global operand'),
            (h[2] + 8, '<Hhhh', (7, h[13] - 1, 0, 0), 'signed global operand'),
            (h[2] + 8, '<Hhhh', (61, 32767, 0, 0), 'branch outside'),
            (h[8] + 36, '<i', (-100,), 'nonstock/unimplemented builtin'),
            (h[8] + 36, '<i', (-60,), 'nonstock/unimplemented builtin'),
            (h[8] + ordinary * 36 + 8, '<i', (2049,), 'local frame exceeds'),
            (h[8] + ordinary * 36 + 24, '<i', (9,), 'more than eight parameters'),
            (h[4] + self_definition * 8 + 2, '<H', (29,), 'ABI mismatch'),
        ]
        for offset, fmt, values, expected in cases:
            with self.subTest(expected=expected, values=values):
                data = bytearray(self.data)
                struct.pack_into(fmt, data, offset, *values)
                with self.assertRaisesRegex(STOCK.StockError, expected):
                    STOCK.validate(data)
        with self.assertRaises(STOCK.StockError):
            STOCK.validate(self.data[:30])

    def test_last_positive_signed_global_address(self):
        h = self.header
        data = bytearray(self.data)
        data.extend(b'\0' * (-len(data) % 4))
        offset = len(data)
        data.extend(self.data[h[12]:h[12] + 4 * h[13]])
        data.extend(b'\0' * (4 * (32768 - h[13])))
        struct.pack_into('<ii', data, 48, offset, 32768)
        strings = self.data[h[10]:h[10] + h[11]]
        function = next(struct.unpack_from('<7i8B', data, h[8] + i * 36)
                        for i in range(1, h[9])
                        if strings[struct.unpack_from('<i', data, h[8] + i * 36 + 16)[0]:]
                        .split(b'\0')[0] == b'stock_smoke')
        struct.pack_into('<f', data, offset + 32767 * 4, 42)
        struct.pack_into('<Hhhh', data, h[2] + function[0] * 8, 6, 32767, 0, 1)
        struct.pack_into('<Hhhh', data, h[2] + (function[0] + 1) * 8, 43, 1, 0, 0)
        STOCK.validate(data)
        path = self.work / 'last-slot.dat'
        path.write_bytes(data)
        result = subprocess.run([str(ROOT / 'tools/quakec/run-stock.sh'), str(path), 'stock_smoke'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('return: 42\n', result.stdout)


if __name__ == '__main__':
    unittest.main()
