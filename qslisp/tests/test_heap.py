"""Pair arena acceptance tests, with tiny pools to reach their limits."""
import json
import re
import struct
import subprocess
import sys
import unittest

from qslisp.compiler import Compiler, compile_source
from qslisp.reader import CompileError, read
from qslisp.measure_heap import probe
from qslisp.tests.test_compiler import CompilerCase, ROOT, STOCK


class HeapTests(CompilerCase):
    def program(self, source, filename='case.scm', **options):
        options.setdefault('heap_pairs', 8)
        return super().program(source, filename, **options)

    def test_pair_acceptance_example(self):
        self.value((ROOT / 'examples/pairs.scm').read_text(), 16)

    def test_pair_predicate_types_and_truth(self):
        self.value('''
        (define (id x) x)
        (define (test)
          (let ((p (cons #f 0)))
            (+ (if (pair? p) 1 100)
               (if (pair? (id p)) 2 200)
               (if (pair? 0) 300 3)
               (if (pair? #f) 400 4)
               (if (id p) 5 500)
               (if (not p) 600 6)
               (if (car p) 700 7)
               (if (cdr p) 8 800))))
        ''', 36)

    def test_nested_pairs_and_read_results_keep_tags(self):
        self.value('''
        (define (test)
          (let ((p (cons (cons 7 #f) (cons 9 #t))))
            (+ (car (car p)) (car (cdr p))
               (if (cdr (car p)) 100 1)
               (if (cdr (cdr p)) 2 200))))
        ''', 19, heap_pairs=3)

    def test_values_stay_live_across_calls_that_allocate(self):
        self.value('''
        (define (id x) x)
        (define (make-right)
          (cons 0 0)
          (cons 0 0)
          (cons 3 4))
        (define (test)
          (let ((p (cons (id (cons 7 9)) (make-right))))
            (+ (car (car p)) (cdr (car p))
               (car (cdr p)) (cdr (cdr p)))))
        ''', 23, heap_pairs=5)

    def test_cells_survive_recursive_vm_frame_save_restore(self):
        self.value('''
        (define (deep n)
          (let ((p (cons n 1)))
            (if (= n 0) (car p) (+ (deep (- n 1)) (car p)))))
        (define (test) (deep 5))
        ''', 15, heap_pairs=6)

    def test_nested_entries_release_their_cells_and_keep_the_callers(self):
        source = '''
        (define (scratch)
          (cons 1 2)
          (cons 3 4))
        (define (repeat n live)
          (if (= n 0)
              (+ (car live) (cdr live))
              (begin
                (quake:call-callback (quake:self) use (quake:self))
                (repeat (- n 1) live))))
        (define (test)
          (quake:set-callback! (quake:self) use scratch)
          (repeat 20 (cons 7 9)))
        '''
        self.value(source, 16, seed_self=True, heap_pairs=3)
        result = self.execute(source, seed_self=True, heap_pairs=2)
        self.assertEqual(result.returncode, 2)
        self.assertIn('pair heap exhausted (2 cells)', result.stderr)

    def test_entry_wrapper_releases_the_arena(self):
        compiler = Compiler(read((ROOT / 'examples/pairs.scm').read_text()), '<input>', heap_pairs=65)
        compiler.compile()
        image, name = probe(compiler, 'churn-test')
        STOCK.validate(image)
        path = self.work / 'arena-probe.dat'
        path.write_bytes(image)
        result = subprocess.run([str(ROOT / 'tools/quakec/run-stock.sh'), str(path), name],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(float(re.search(r'^return: (.+)$', result.stdout, re.M)[1]), 0)

    def test_one_entry_cannot_allocate_more_than_the_pool(self):
        source = (ROOT / 'examples/pairs.scm').read_text()
        self.value(source, 16, 'churn-test', heap_pairs=65)
        result = self.execute(source, 'churn-test', heap_pairs=64)
        self.assertEqual(result.returncode, 2)
        self.assertIn('pair heap exhausted (64 cells)', result.stderr)

    def test_pair_heap_exhaustion_reports_location(self):
        result = self.execute('''(define (build n tail)
  (if (= n 0) tail (build (- n 1) (cons n tail))))
(define (test) (build 3 #f))''', heap_pairs=2)
        self.assertEqual(result.returncode, 2)
        self.assertIn('case.scm:2:', result.stderr)
        self.assertIn('pair heap exhausted (2 cells)', result.stderr)
        self.assertNotIn('runaway loop', result.stdout)

    def test_default_pool_fills_within_watchdog_then_fails_explicitly(self):
        source = '''
        (define (build n tail)
          (if (= n 0) (car tail) (build (- n 1) (cons n tail))))
        (define (fill) (build 512 #f))
        (define (test) (build 513 #f))
        '''
        self.value(source, 1, 'fill', heap_pairs=512)
        result = self.execute(source, heap_pairs=512)
        self.assertEqual(result.returncode, 2)
        self.assertIn('pair heap exhausted (512 cells)', result.stderr)
        self.assertNotIn('runaway loop', result.stdout)

    def test_type_errors_are_not_numeric_handle_coercions(self):
        for primitive in ('car', 'cdr'):
            with self.subTest(primitive=primitive):
                result = self.execute(f'(define (read-pair x) ({primitive} x)) (define (test) (read-pair 0))')
                self.assertEqual(result.returncode, 2)
                self.assertIn(f'{primitive} requires an allocated pair', result.stderr)
        result = self.execute('(define (add x) (+ x 1)) (define (test) (add (cons 1 2)))')
        self.assertEqual(result.returncode, 2)
        self.assertIn('expected a number', result.stderr)

    def test_heap_primitive_compile_diagnostics(self):
        for source, message in (
            ('(define (test) (cons 1))', 'cons requires 2'),
            ('(define (test) (car))', 'car requires 1'),
            ('(define (test) (pair? 1 2))', 'pair? requires 1'),
            ('(define (test) (car #f))', 'car requires a pair'),
            ('(define (test) (+ (cons 1 2) 1))', 'require numbers'),
        ):
            with self.subTest(source=source):
                with self.assertRaisesRegex(CompileError, re.escape(message)):
                    compile_source(source, 'pair-error.scm')
        for options in ({'heap_pairs': 0}, {'heap_pairs': -1}, {'heap_pairs': True}):
            with self.subTest(options=options):
                with self.assertRaisesRegex(CompileError, 'positive integer'):
                    compile_source('(define (test) 1)', **options)
        with self.assertRaisesRegex(CompileError, 'stock global storage'):
            compile_source('(define (test) (cons 1 2))', heap_pairs=6000)

    def test_unused_heaps_are_not_emitted(self):
        for source in ('(define (test) 49)', '(define (test) (pair? 0))',
                       '(define (test) (let ((cons 49)) cons))'):
            compiler = Compiler(read(source), '<input>')
            STOCK.validate(compiler.compile())
            self.assertEqual(compiler.statistics()['pair_capacity'], 0)
            self.assertEqual(compiler.statistics()['heap_runtime_statements'], 0)

    def test_mixed_runtime_parameter_widths_and_static_profile(self):
        data = self.program('(define (test) (cons 7 9))').read_bytes()
        header = STOCK.validate(data)
        strings = data[header[10]:header[10] + header[11]]
        for i in range(header[9]):
            function = struct.unpack_from('<7i8B', data, header[8] + i * 36)
            if strings[function[4]:].split(b'\0')[0] == b'__qslisp_rt_cons':
                self.assertEqual(function[7:10], (3, 3, 1))
                break
        else:
            self.fail('missing bytecode cons runtime')

    def test_cli_pool_configuration_and_report(self):
        path = self.work / 'pairs.dat'
        result = subprocess.run([sys.executable, '-m', 'qslisp', 'examples/pairs.scm', '-o', str(path),
                                 '--heap-pairs', '8', '--report'],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout[result.stdout.index('{'):])
        self.assertEqual(report['pair_capacity'], 8)
        self.assertEqual(report['pair_storage_slots'], 48)
        self.assertGreater(report['heap_runtime_statements'], 0)
        STOCK.validate(path.read_bytes())


if __name__ == '__main__':
    unittest.main()
