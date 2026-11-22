"""Compiler acceptance tests execute direct output on the original interpreter."""
import importlib.util
import itertools
from pathlib import Path
import re
import struct
import subprocess
import sys
import unittest

from qslisp.compiler import compile_source
from qslisp.reader import CompileError

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('stock', ROOT / 'tools/quakec/check-stock.py')
STOCK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STOCK)


class CompilerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT / 'build/quakec/bin/stock-vm').is_file():
            raise RuntimeError('Run ./tools/quakec/setup.sh before the compiler tests')
        cls.work = ROOT / 'build/lisp-tests' / cls.__name__
        cls.work.mkdir(parents=True, exist_ok=True)
        cls.counter = itertools.count()

    def program(self, source, filename='case.scm', **options):
        data = compile_source(source, filename, **options)
        STOCK.validate(data)
        path = self.work / f'case-{next(self.counter)}.dat'
        path.write_bytes(data)
        return path

    def execute(self, source, name='test', *arguments, **options):
        path = self.program(source, **options)
        return subprocess.run([str(ROOT / 'tools/quakec/run-stock.sh'), str(path), name,
                               *map(str, arguments)], capture_output=True, text=True, timeout=10)

    def value(self, source, expected, name='test', *arguments, **options):
        result = self.execute(source, name, *arguments, **options)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(float(re.search(r'^return: (.+)$', result.stdout, re.M)[1]), expected)
        return result


class CompilerTests(CompilerCase):

    def test_square_example_and_native_numeric_entry(self):
        source = (ROOT / 'examples/square.scm').read_text()
        self.value(source, 49)
        self.value(source, 81, 'square', 9)

    def test_arithmetic_and_float32(self):
        for expression, expected in [
            ('(+)', 0), ('(*)', 1), ('(+ 1 2 3 4)', 10), ('(* 2 3 4)', 24),
            ('(- 10 3 2)', 5), ('(/ 24 2 3)', 4), ('(- 7)', -7), ('(/ 4)', .25),
            ('(+ .5 -2.5e1)', -24.5), ('(+ 16777216 1)', 16777216),
        ]:
            with self.subTest(expression=expression):
                self.value(f'(define (test) {expression})', expected)

    def test_boolean_truth_is_distinct_from_numeric_zero(self):
        for expression, expected in [
            ('(if #f 1 2)', 2), ('(if #t 1 2)', 1),
            ('(if 0 1 2)', 1), ('(if -0.0 1 2)', 1),
            ('(if (not 0) 1 2)', 2), ('(if (not #f) 1 2)', 1),
            ('(if (not #t) 1 2)', 2), ('(if (not (not #f)) 1 2)', 2),
            ('(if (< 2 3) 1 2)', 1), ('(if (= 2 3) 1 2)', 2),
            ('(if (<= 3 3) 1 2)', 1), ('(if (> 2 3) 1 2)', 2),
            ('(if (>= 3 3) 1 2)', 1),
        ]:
            with self.subTest(expression=expression):
                self.value(f'(define (test) {expression})', expected)

    def test_dynamic_boolean_arguments_and_mixed_branch_results(self):
        source = '''
        (define (identity x) x)
        (define (choose flag) (if flag #f 0))
        (define (test)
          (+ (if (identity #f) 10 1)
             (if (identity 0) 2 20)
             (if (choose #t) 30 3)
             (if (choose #f) 4 40)))
        '''
        self.value(source, 10)

    def test_let_is_simultaneous_and_lexical(self):
        self.value('''(define (test)
          (let ((x 10))
            (+ (let ((x 2) (y x)) (+ x y)) x)))''', 22)
        self.value('(define (test) (let ((+ 42)) +))', 42)
        with self.assertRaisesRegex(CompileError, 'unbound variable x'):
            compile_source('(define (f) x) (define (test) (let ((x 42)) (f)))')
        with self.assertRaisesRegex(CompileError, 'unbound variable x'):
            compile_source('(define (test) (let ((x 1) (y x)) y))')

    def test_nested_calls_do_not_clobber_argument_or_return_registers(self):
        self.value('''
        (define (square x) (* x x))
        (define (combine a b c) (+ (* a 100) (* b 10) c))
        (define (test) (+ (combine (square 2) (square 3) (square 4)) (square 5)))
        ''', 531)

    def test_eight_argument_boundary(self):
        self.value('''
        (define (id x) x)
        (define (sum a b c d e f g h) (+ a b c d e f g h))
        (define (test) (sum (id 1) (id 2) (id 3) (id 4) (id 5) (id 6) (id 7) (id 8)))
        ''', 36)

    def test_recursion_preserves_parameters_and_temporaries(self):
        self.value('''
        (define (fact n) (if (= n 0) 1 (* n (fact (- n 1)))))
        (define (test) (fact 6))
        ''', 720)

    def test_forward_and_mutually_recursive_functions(self):
        self.value('''
        (define (test) (if (even? 12) 49 0))
        (define (even? n) (if (= n 0) #t (odd? (- n 1))))
        (define (odd? n) (if (= n 0) #f (even? (- n 1))))
        ''', 49)

    def test_dead_branches_are_not_executed(self):
        self.value('''
        (define (bad x) (+ x 1))
        (define (test) (if #f (bad #t) 42))
        ''', 42)

    def test_begin_and_multiple_body_expressions(self):
        self.value('(define (test) 1 (begin 2 (let ((x 7)) (* x x))))', 49)

    def test_runtime_type_errors_include_source_location(self):
        result = self.execute('''(define (add x)
  (+ x 1))
(define (test) (add #f))''')
        self.assertEqual(result.returncode, 2)
        self.assertIn('case.scm:2:6: expected a number', result.stderr)

    def test_argument_evaluation_is_left_to_right(self):
        result = self.execute('''
        (define (left x) (+ x 1))
        (define (right x) (+ 1 x))
        (define (consume a b) 0)
        (define (test) (consume (left #f) (right #f)))
        ''')
        self.assertEqual(result.returncode, 2)
        self.assertIn('case.scm:2:', result.stderr)

    def test_compile_errors_have_locations(self):
        cases = [
            ('(define (test)\n  (+ missing 1))', 'error.scm:2:6: unbound variable missing'),
            ('(define (f x x) x)', 'duplicate function parameter'),
            ('(define (f) 1) (define (f) 2)', 'duplicate function'),
            ('(define (f a b c d e f g h i) 1)', 'at most eight arguments'),
            ('(define (f x) x) (define (test) (f))', 'expects 1 arguments'),
            ('(define (test) (missing 1))', 'undefined function'),
            ('(define (test) (let ((x 1) (x 2)) x))', 'duplicate let binding'),
            ('(define (test) (let ((x)) x))', 'let binding requires'),
            ('(define (test) (if #t 1))', 'two branches'),
            ('(define (test) (+ #t 1))', 'require numbers'),
            ('(define (test) (lambda (x) x))', 'lambda is not supported'),
            ("(define (test) '(1 2))", 'quote is not supported'),
            ('(define (test) (let ((f 1)) (f 2)))', 'calling local values'),
            ('(define (test) (begin))', 'begin requires'),
            ('(define (test) (< 1 2 3))', 'exactly two arguments'),
            ('(define (test) (/))', 'at least one argument'),
            ('(define (time) 1)', 'reserved by the stock Quake ABI'),
            ('(define (StartFrame x) x)', 'entry functions require zero arguments'),
            ('(define (__qslisp_x) 1)', 'reserved function name'),
            ('(define (test) 1e100)', 'finite float32 range'),
        ]
        for source, message in cases:
            with self.subTest(source=source):
                with self.assertRaisesRegex(CompileError, re.escape(message)):
                    compile_source(source, 'error.scm')

    def test_reader_errors_and_comments(self):
        self.value('; comment\n(define (test) ; another\n  49) ; trailing', 49)
        for source, message in [
            ('(define (test) 1', 'unclosed parenthesis'),
            (')', 'unexpected closing parenthesis'),
            ('(define (test) "hello")', 'string literals'),
            ('(define (test) "hello)', 'unterminated string literal'),
            ('(define (test) "bad\\q")', 'unsupported string escape'),
            ('(define (test) "bad\0")', 'string literals cannot contain a NUL byte'),
            ('(define (test) #unknown)', 'unsupported token'),
            ("'", 'expected a datum'),
            ('', 'at least one function'),
            ('(define x 1)', 'named function definitions'),
        ]:
            with self.subTest(source=source):
                with self.assertRaisesRegex(CompileError, message):
                    compile_source(source, 'reader.scm')

    def test_quake_dprint_passes_a_native_string_and_returns_zero(self):
        source = r'''(define (test) (quake:dprint "say \"hello\"; one\\two\n"))'''
        result = self.value(source, 0)
        self.assertIn('say "hello"; one\\two\n', result.stdout)

    def test_quake_precache_model_calls_stock_builtin(self):
        result = self.execute('(define (test) (quake:precache-model "progs/player.mdl"))')
        self.assertEqual(result.returncode, 2)
        self.assertIn('builtin #20', result.stderr)
        self.assertIn('requires the game engine', result.stderr)

    def test_quake_builtin_literal_diagnostics(self):
        cases = [
            ('(quake:dprint)', 'requires one string literal'),
            ('(quake:dprint 42)', 'requires one string literal'),
            ('(quake:dprint "one" "two")', 'requires one string literal'),
            ('(quake:dprint "' + 'é' * 128 + '")', 'stock 255-byte limit'),
            ('(quake:precache-model "")', 'requires a stock model path'),
            ('(quake:precache-model "' + 'a' * 64 + '")', 'requires a stock model path'),
        ]
        for call, message in cases:
            with self.subTest(call=call):
                with self.assertRaisesRegex(CompileError, message):
                    compile_source(f'(define (test) {call})', 'builtin.scm')

    def test_entity_tags_survive_scheme_calls_and_pairs(self):
        self.value('''
        (define (identity x) x)
        (define (test)
          (let ((entity (identity (car (cons (quake:self) #f)))))
            (if (quake:world? entity) 49 0)))
        ''', 49)
        result = self.execute('(define (test x) (quake:world? x))', 'test', 0)
        self.assertEqual(result.returncode, 2)
        self.assertIn('expected an entity', result.stderr)

    def test_native_field_writes_and_vector_component_reads(self):
        path = self.program('''
        (define (identity x) x)
        (define (test)
          (let ((entity (quake:self)))
            (quake:set-field! entity health (identity 100))
            (quake:set-field! entity view_ofs (quake:vector 0 0 (identity 22)))
            (quake:set-field! entity velocity (quake:field entity view_ofs))
            (+ (quake:field entity health) (quake:field entity velocity_z))))
        ''')
        data = bytearray(path.read_bytes())
        header = STOCK.validate(data)
        # The CLI host starts with zeroed entities. Point self at its second edict.
        struct.pack_into('<i', data, header[12] + 28 * 4, header[14] * 4)
        path.write_bytes(data)
        result = subprocess.run([str(ROOT / 'tools/quakec/run-stock.sh'), str(path), 'test'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('return: 122\n', result.stdout)

    def test_stock_frame_and_reader_depth_limits_are_diagnostics(self):
        with self.assertRaisesRegex(CompileError, 'saved-locals limit'):
            compile_source('(define (test) (+ ' + ' '.join(['1'] * 800) + '))', 'large.scm')
        with self.assertRaisesRegex(CompileError, 'source nesting limit'):
            compile_source('(' * 200 + '1' + ')' * 200, 'deep.scm')

    def test_engine_entry_global_points_to_public_wrapper(self):
        data = compile_source('(define (StartFrame) 49)')
        h = STOCK.validate(data)
        strings = data[h[10]:h[10] + h[11]]
        for i in range(h[5]):
            kind, offset, name = struct.unpack_from('<HHi', data, h[4] + i * 8)
            if strings[name:].split(b'\0')[0] == b'StartFrame':
                self.assertEqual(kind, 6)
                index = struct.unpack_from('<I', data, h[12] + offset * 4)[0]
                self.assertGreater(index, 0)
                function = struct.unpack_from('<7i8B', data, h[8] + index * 36)
                self.assertEqual(strings[function[4]:].split(b'\0')[0], b'StartFrame')
                break
        else:
            self.fail('missing StartFrame ABI definition')

    def test_cli_compiles_example_and_reports_errors_without_tracebacks(self):
        output = self.work / 'cli.dat'
        result = subprocess.run([sys.executable, '-m', 'qslisp', 'examples/square.scm', '-o', str(output)],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        STOCK.validate(output.read_bytes())
        bad = self.work / 'bad.scm'
        bad.write_text('(define (test) missing)')
        before = output.read_bytes()
        result = subprocess.run([sys.executable, '-m', 'qslisp', str(bad), '-o', str(output)],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertIn('bad.scm:1:16: unbound variable', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(output.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
