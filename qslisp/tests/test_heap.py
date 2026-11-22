"""Pair/GC acceptance tests, with tiny heaps to force collection frequently."""
import json
import re
import struct
import subprocess
import sys
import unittest

from qslisp.compiler import Compiler, compile_source
from qslisp.reader import CompileError, read
from qslisp.measure_heap import probes
from qslisp.tests.test_compiler import CompilerCase, ROOT, STOCK


class HeapTests(CompilerCase):
    def program(self, source, filename='case.scm', **options):
        options.setdefault('heap_pairs', 8)
        options.setdefault('root_slots', 32)
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

    def test_pending_arguments_survive_collection_in_a_later_argument(self):
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
        ''', 23, heap_pairs=3)

    def test_parallel_let_initializers_are_shadow_roots(self):
        self.value('''
        (define (test)
          (let ((a (cons 7 9))
                (b (begin (cons 0 0) (cons 0 0) (cons 3 4))))
            (+ (car a) (cdr a) (car b) (cdr b))))
        ''', 23, heap_pairs=2)

    def test_shadowed_binding_is_kept_for_an_outer_continuation(self):
        self.value('''
        (define (test)
          (let ((p (cons 7 9)))
            (+ (let ((p (cons 3 4)))
                 (cons 0 0)
                 (cons 0 0)
                 (car p))
               (car p))))
        ''', 10, heap_pairs=3)

    def test_gc_reclaims_discarded_body_values(self):
        self.value('''
        (define (test)
          (cons 1 2)
          (cons 3 4)
          (let ((p (cons 7 9))) (+ (car p) (cdr p))))
        ''', 16, heap_pairs=1)

    def test_tail_loop_collects_without_retaining_old_temporary_slots(self):
        result = self.value((ROOT / 'examples/pairs.scm').read_text(), 16, 'gc-test',
                            heap_pairs=2, root_slots=2)
        self.assertLess(int(re.search(r'instructions: (\d+)', result.stdout)[1]), 100000)

    def test_roots_survive_recursive_vm_frame_save_restore(self):
        self.value('''
        (define (deep n)
          (let ((p (cons n 1)))
            (cons 0 0)
            (cons 0 0)
            (if (= n 0) (car p) (+ (deep (- n 1)) (car p)))))
        (define (test) (deep 5))
        ''', 15, heap_pairs=8, root_slots=16)

    def test_collector_traces_shared_children_in_both_pair_fields(self):
        self.value('''
        (define (churn n p)
          (if (= n 0)
              (+ (car (car p)) (cdr (cdr p)))
              (begin (cons 0 0) (churn (- n 1) p))))
        (define (test)
          (let ((child (cons 7 9)))
            (churn 20 (cons child child))))
        ''', 16, heap_pairs=3)

    def test_gc_uses_an_iterative_work_list_for_a_deep_graph(self):
        self.value('''
        (define (build n tail)
          (if (= n 0) tail (build (- n 1) (cons n tail))))
        (define (churn n p)
          (if (= n 0) (car p) (begin (cons 0 0) (churn (- n 1) p))))
        (define (test) (churn 2 (build 64 #f)))
        ''', 1, heap_pairs=65)

    def test_pair_heap_exhaustion_reports_location_when_every_cell_is_live(self):
        result = self.execute('''(define (build n tail)
  (if (= n 0) tail (build (- n 1) (cons n tail))))
(define (test) (build 3 #f))''', heap_pairs=2)
        self.assertEqual(result.returncode, 2)
        self.assertIn('case.scm:2:', result.stderr)
        self.assertIn('pair heap exhausted (2 cells)', result.stderr)
        self.assertNotIn('runaway loop', result.stdout)

    def test_shadow_root_capacity_fails_explicitly(self):
        result = self.execute('''
        (define (test)
          (let ((a (cons 1 2)) (b (cons 3 4)) (c (cons 5 6)))
            (+ (car a) (car b) (car c))))
        ''', heap_pairs=4, root_slots=1)
        self.assertEqual(result.returncode, 2)
        self.assertIn('shadow root stack exhausted (1 values)', result.stderr)

    def test_default_pool_exhaustion_finishes_collection_within_watchdog(self):
        result = self.execute('''
        (define (build n tail)
          (if (= n 0) tail (build (- n 1) (cons n tail))))
        (define (test) (build 257 #f))
        ''', heap_pairs=256, root_slots=256)
        self.assertEqual(result.returncode, 2)
        self.assertIn('pair heap exhausted (256 cells)', result.stderr)
        self.assertNotIn('runaway loop', result.stdout)

    def test_repeated_collection_does_not_bypass_original_watchdog(self):
        result = self.execute('(define (test) (begin (cons 1 2) (test)))',
                              heap_pairs=1, root_slots=1)
        self.assertEqual(result.returncode, 2)
        self.assertIn('runaway loop error', result.stdout)
        self.assertNotIn('stack overflow', result.stdout)
        self.assertNotIn('heap exhausted', result.stderr)

    def test_numeric_unknowns_do_not_consume_shadow_root_slots(self):
        self.value('''
        (define (combine a b c d e f g h)
          (let ((p (cons a h))) (+ (car p) (cdr p))))
        (define (test) (combine 1 2 3 4 5 6 7 8))
        ''', 9, heap_pairs=1, root_slots=1)

    def test_ordinary_call_root_pop_does_not_discard_a_returned_pair(self):
        self.value('''
        (define (make x) (cons x x))
        (define (read-two a b) (+ (car a) (cdr b)))
        (define (make-garbage)
          (cons 0 0)
          (cons 0 0)
          (make 9))
        (define (test) (read-two (make 7) (make-garbage)))
        ''', 16, heap_pairs=2)

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
        for options in ({'heap_pairs': 0}, {'root_slots': -1}, {'heap_pairs': True}):
            with self.subTest(options=options):
                with self.assertRaisesRegex(CompileError, 'positive integers'):
                    compile_source('(define (test) 1)', **options)
        with self.assertRaisesRegex(CompileError, 'stock global storage'):
            compile_source('(define (test) (cons 1 2))', heap_pairs=4000)

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
                                 '--heap-pairs', '8', '--root-slots', '32', '--report'],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout[result.stdout.index('{'):])
        self.assertEqual(report['pair_capacity'], 8)
        self.assertEqual(report['pair_storage_slots'], 72)
        self.assertEqual(report['root_capacity'], 32)
        self.assertGreater(report['heap_runtime_statements'], 0)
        STOCK.validate(path.read_bytes())

    def test_collection_counter_and_balanced_roots_observed_in_vm(self):
        compiler = Compiler(read((ROOT / 'examples/pairs.scm').read_text()), '<input>',
                            heap_pairs=8, root_slots=32)
        compiler.compile()
        image, names = probes(compiler, 'gc-test')
        STOCK.validate(image)
        path = self.work / 'gc-probes.dat'
        path.write_bytes(image)
        for label, name in names.items():
            result = subprocess.run([str(ROOT / 'tools/quakec/run-stock.sh'), str(path), name],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            count = float(re.search(r'^return: (.+)$', result.stdout, re.M)[1])
            if label == 'collections':
                self.assertGreater(count, 0)
            else:
                self.assertEqual(count, 0)


if __name__ == '__main__':
    unittest.main()
