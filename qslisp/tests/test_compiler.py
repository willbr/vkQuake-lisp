"""Compiler acceptance tests execute direct output on the original interpreter."""
import importlib.util
import itertools
import pathlib
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
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

    def execute(self, source, name='test', *arguments, seed_self=False, **options):
        path = self.program(source, **options)
        if seed_self:
            data = bytearray(path.read_bytes())
            header = STOCK.validate(data)
            # The CLI host starts with zeroed entities. Point self at its second edict.
            struct.pack_into('<i', data, header[12] + 28 * 4, header[14] * 4)
            path.write_bytes(data)
        return subprocess.run([str(ROOT / 'tools/quakec/run-stock.sh'), str(path), name,
                               *map(str, arguments)], capture_output=True, text=True, timeout=10)

    def value(self, source, expected, name='test', *arguments, **options):
        result = self.execute(source, name, *arguments, **options)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(float(re.search(r'^return: (.+)$', result.stdout, re.M)[1]), expected)
        return result


class CompilerTests(CompilerCase):

    def test_persistent_entity_list_validates_and_reconstructs_the_snapshot(self):
        library = (ROOT / 'qslisp/persistence.scm').read_text()
        source = library + """
        (define-saved-entity-list restore remember! path-length (path-a path-b))
        (define (test)
          (let* ((owner (quake:self))
                 (path (list owner (quake:world))))
            (remember! owner path)
            (let ((loaded (restore owner)))
              (if (and (equal? path loaded) (not (eq? path loaded)))
                  (begin
                    (remember! owner ())
                    (if (null? (restore owner)) 49 0))
                  0))))
        (define (bad-value) (remember! (quake:self) (list 7)))
        (define (too-long) (remember! (quake:self) (list (quake:world) (quake:world) (quake:world))))
        """
        self.value(source, 49, seed_self=True)
        for name in ('bad-value', 'too-long'):
            with self.subTest(name=name):
                result = self.execute(source, name)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('saved entity list requires a proper list', result.stdout + result.stderr)

    def test_records_check_types_and_compare_by_schema_and_value(self):
        source = """
        (define-record reading (value number))
        (define-record other (value number))
        (define-record packet (readings list) (first reading))
        (define (test)
          (let* ((a (make-reading 7))
                 (b (make-packet (list a) a)))
            (if (and (packet? b) (reading? (packet-first b))
                     (not (pair? a)) (not (reading? 7))
                     (equal? a (make-reading 7)) (not (eq? a (make-reading 7)))
                     (not (equal? a (make-other 7))))
                (reading-value (car (packet-readings b)))
                -1)))
        """
        self.value(source, 7)
        with self.assertRaisesRegex(CompileError, r'reading.value expects number, got boolean'):
            compile_source('(define-record reading (value number)) (define (test) (make-reading #f))')
        with self.assertRaisesRegex(CompileError, r'packet.first expects reading, got other'):
            compile_source(source + '(define (invalid) (make-packet () (make-other 1)))')
        wrong = self.execute(source + '(define (invalid x) (make-packet x (make-reading 1)))', 'invalid', 5)
        self.assertNotEqual(wrong.returncode, 0)
        self.assertIn('packet.readings expects list', wrong.stdout + wrong.stderr)

    def test_match_destructures_once_and_keeps_failed_bindings_local(self):
        source = """
        (define-record sample (label symbol) (items list))
        (define (test)
          (let ((head 19) (car #f))
            (+ (match (make-sample 'ready (list 3 4))
                 ((sample 'ready (list first second)) (+ first second))
                 (else -1))
               (match (list 3 'wrong)
                 ((list head 'right) head)
                 ((cons _ (cons 'missing ())) -2)
                 (else head))
               (match 10 ((cons _ _) -1) (10 1)))))
        """
        self.value(source, 27)
        with self.assertRaisesRegex(CompileError, 'duplicate pattern binding x'):
            compile_source('(define (test) (match (list 1 2) ((list x x) x)))')
        with self.assertRaisesRegex(CompileError, 'match else must be the final clause'):
            compile_source('(define (test) (match 5 (else 0) (_ 2)))')
        unmatched = self.execute('(define (test) (match 5 (1 0)))')
        self.assertNotEqual(unmatched.returncode, 0)
        self.assertIn('no matching pattern', unmatched.stdout + unmatched.stderr)

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

    def test_primitives_are_procedure_values(self):
        self.value('''
        (import "qslisp/list.scm")
        (define (apply2 f a b) (f a b))
        (define (test)
          (+ (fold + 0 (list 1 2 3 4))
             (* 100 (apply2 - 9 4))
             (* 1000 (car (map car (list (cons 7 8) (cons 9 10)))))
             (if (and (procedure? <) ((if #t < >) 1 2) (eq? cons cons)
                      (equal? (map not (list #f 1)) (list #t #f)))
                 10000 0)
             (let ((+ *)) (+ 0 5))))
        ''', 17510)
        compiler_free = compile_source('(define (apply2 f) (f 40 2)) (define (test) (apply2 +))')
        self.assertNotIn(b'__qslisp_rt_cons', compiler_free)
        for name in ('quake:dprint', 'if', 'quake:field'):
            with self.subTest(name=name):
                with self.assertRaisesRegex(CompileError, 'cannot be used as a value'):
                    compile_source(f'(define (id x) x) (define (test) (id {name}))')

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
            ('(define (test) (lambda (x x) x))', 'duplicate lambda parameter'),
            ("(define (test) '(1 . 2 3))", 'a dotted list requires'),
            ('(define (test) (let ((f 1)) (f 2)))', 'expected a procedure, got a number'),
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
            ('(define (test) "hello)', 'unterminated string literal'),
            ('(define (test) "bad\\q")', 'unsupported string escape'),
            ('(define (test) "bad\0")', 'string literals cannot contain a NUL byte'),
            ('(define (test) #unknown)', 'unsupported token'),
            ("'", 'expected a datum'),
            ('', 'at least one function'),
            ('(define x 1)', 'at least one function'),
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

    def test_stock_lightstyle_bprint_pointcontents_and_serverflags(self):
        source = '''
        (define (id x) x)
        (define (sigils) (quake:set-serverflags! (quake:bit-or (quake:serverflags) 6)) (quake:serverflags))
        (define (style n) (quake:lightstyle (id n) "az"))
        (define (constant-style) (quake:lightstyle 63 "m"))
        (define (broadcast) (quake:bprint "hello\\n"))
        (define (contents) (quake:point-contents (quake:vector 0 0 0)))
        (define (tell) (quake:sprint (quake:self) "hi\\n"))
        (define (kills n) (quake:update-stat 14 n))
        (define (zap) (quake:lightning (quake:self) (quake:vector 0 0 0) (quake:vector 1 2 3)))
        (define (flash) (quake:point-effect teleport (quake:vector 0 0 0)))
        (define (steer) (quake:move-to-goal 8))
        (define (turn) (quake:change-yaw))
        '''
        self.value(source, 6, 'sigils')
        for name, arguments, builtin in [('style', (32,), 35), ('constant-style', (), 35),
                                         ('broadcast', (), 23), ('contents', (), 41),
                                         ('tell', (), 24), ('kills', (3,), 52), ('zap', (), 52),
                                         ('flash', (), 52), ('steer', (), 67), ('turn', (), 49)]:
            with self.subTest(name=name):
                result = self.execute(source, name, *arguments)
                self.assertEqual(result.returncode, 2)
                self.assertIn(f'builtin #{builtin}', result.stderr)
        for style in (-1, 64):
            with self.subTest(style=style):
                result = self.execute(source, 'style', style)
                self.assertEqual(result.returncode, 2)
                self.assertIn('light style must be 0 to 63', result.stderr)
        data = compile_source(source, 'flags.scm')
        header = STOCK.validate(data)
        definitions = [struct.unpack_from('<HHi', data, header[4] + 8 * i) for i in range(header[5])]
        saved = {data[header[10] + name:].split(b'\0', 1)[0] for kind, _, name in definitions if kind & 0x8000}
        self.assertEqual(saved, {b'serverflags', b'total_secrets', b'total_monsters',
                                 b'found_secrets', b'killed_monsters'})

    def test_source_printer_broadcasts_each_line_of_its_file(self):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / 'printer.scm'
            source.write_text('(define-source-printer show "printer.scm")\n(define (test) (show) 7)\n')
            data = compile_source(source.read_text(), str(source))
            self.assertIn(b'(define-source-printer show "printer.scm")\n\0', data)
            self.assertIn(b'(define (test) (show) 7)\n\0', data)
            path = self.work / 'printer.dat'
            path.write_bytes(data)
            result = subprocess.run([str(ROOT / 'tools/quakec/run-stock.sh'), str(path), 'test'],
                                    capture_output=True, text=True, timeout=10)
            self.assertIn('builtin #23', result.stderr)
        with self.assertRaisesRegex(CompileError, 'cannot read'):
            compile_source('(define-source-printer show "missing.scm")\n(define (test) 1)', 'printer.scm')

    def test_print_builtins_accept_runtime_strings(self):
        result = self.execute('(define (name) "c5")\n(define (test) (quake:sprint (quake:self) (name)))')
        self.assertIn('builtin #24', result.stderr)

    def test_quake_builtin_literal_diagnostics(self):
        cases = [
            ('(quake:dprint)', 'requires one string literal'),
            ('(quake:dprint 42)', 'requires one string literal'),
            ('(quake:dprint "one" "two")', 'requires one string literal'),
            ('(quake:dprint "' + 'é' * 128 + '")', 'stock 255-byte limit'),
            ('(quake:precache-model "")', 'requires a stock model path'),
            ('(quake:precache-model "' + 'a' * 64 + '")', 'requires a stock model path'),
            ('(quake:change-level "annex; quit")', 'requires a literal map name'),
            ('(quake:bprint "' + 'é' * 128 + '")', 'stock 255-byte limit'),
            ('(quake:lightstyle 64 "a")', 'style from 0 to 63'),
            ('(quake:lightstyle 32 "aZ")', 'pattern of 1–63 letters'),
            ('(quake:lightstyle 32 "")', 'pattern of 1–63 letters'),
            ('(quake:lightstyle 32 "' + 'a' * 64 + '")', 'pattern of 1–63 letters'),
            ('(quake:set-serverflags! #t)', 'require numbers'),
            ('(quake:update-stat 3 1)', 'scoreboard stat'),
            ('(quake:point-effect sparkle (quake:vector 0 0 0))', 'effect name'),
            ('(quake:sprint (quake:self) "' + 'é' * 128 + '")', 'stock 255-byte limit'),
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
        (define-field charge)
        (define (identity x) x)
        (define (test)
          (let ((entity (quake:self)))
            (quake:set-field! entity charge (identity 100))
            (quake:set-field! entity view_ofs (quake:vector 0 0 (identity 22)))
            (quake:set-field! entity velocity (quake:field entity view_ofs))
            (+ (quake:field entity charge) (quake:field entity velocity_z))))
        ''')
        data = bytearray(path.read_bytes())
        header = STOCK.validate(data)
        self.assertEqual(header[14], 106)
        # The CLI host starts with zeroed entities. Point self at its second edict.
        struct.pack_into('<i', data, header[12] + 28 * 4, header[14] * 4)
        path.write_bytes(data)
        result = subprocess.run([str(ROOT / 'tools/quakec/run-stock.sh'), str(path), 'test'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('return: 122\n', result.stdout)

    def test_custom_fields_cannot_shadow_stock_or_scheme_names(self):
        cases = ('(define-field health)', '(define-field extra) (define-field extra)',
                 '(define-field quake:time)', '(define-field test)')
        for fields in cases:
            with self.subTest(fields=fields), self.assertRaisesRegex(CompileError, 'entity field'):
                compile_source(f'(define (test) 0) {fields}')

    def test_quake_bitwise_flags(self):
        self.value('''
        (define (test)
          (quake:bit-and (quake:bit-or 8 512) 512))
        ''', 512)

    def test_derived_forms_preserve_truth_and_tail_calls(self):
        source = '''
        (define count 1000)
        (define (add-one x) (+ x 1))
        (define (loop n)
          (cond ((= n 0) (cond ((or #f 0 (quake:error "evaluated")) => add-one)))
                (else (when (and #t n) (loop (- n 1))))))
        (define (test)
          (let* ((first (loop count)) (second (+ first 10)))
            (if (and (not (and #f (quake:error "evaluated"))) (and)) second 0)))
        '''
        self.value(source, 11)

    def test_strings_can_be_passed_through_procedures_and_pairs(self):
        self.value('''
        (define label "signal")
        (define (identity x) x)
        (define (test)
          (if (and (string=? (car (cons (identity label) #f)) "signal")
                   (not (string=? "signal" "other")))
              49 0))
        ''', 49)

    def test_quoted_data_proper_lists_and_value_equality(self):
        self.value('''
        (define (test)
          (let ((left (list 'relay "ready" #f))
                (right '(relay "ready" #f))
                (dotted '(relay . annex)))
            (if (and (list? left) (list? right) (not (list? dotted))
                     (symbol? (car left)) (string? (car (cdr left)))
                     (eq? 'relay (car dotted)) (eq? 'annex (cdr dotted))
                     (not (eq? left right)) (equal? left right)
                     (eq? 0 -0.0) (not (eq? #f 0))
                     (null? ()) (eq? '() (list)) (not (not '())))
                49 0)))
        ''', 49)

    def test_quasiquote_expands_only_active_unquotes_and_preserves_macro_bindings(self):
        self.value('''
        (define-syntax twice
          (syntax-rules () ((_ x) (+ x x))))
        (define-syntax template
          (syntax-rules ()
            ((_ value)
             (let ((hidden value))
               `(hidden ,hidden (twice 9) ,(twice hidden))))))
        (define (test)
          (let ((x 7) (hidden 19) (cons #f) (append #f))
            (if (and (equal? (template x) '(hidden 7 (twice 9) 14))
                     (equal? `(a ,x ,@(list 8 9) ,@() . ,(+ x 3)) '(a 7 8 9 . 10))
                     (equal? `(outer `(inner ,x ,,x))
                             '(outer (quasiquote (inner (unquote x) (unquote 7)))))
                     (equal? '(quasiquote (unquote x)) '`,x)
                     (= (quasiquote (unquote x)) x))
                49 0)))
        ''', 49)

    def test_quasiquote_evaluates_escapes_once_left_to_right(self):
        self.value('''
        (define (test)
          (let ((state 0))
            (let* ((next (lambda () (set! state (+ state 1))))
                   (result `(,(next) ,@(list (next) (next)) . ,(next))))
              (if (and (= state 4) (equal? result '(1 2 3 . 4))) 49 0))))
        ''', 49)

    def test_quasiquote_reports_malformed_escapes(self):
        cases = [
            (',1', 'unquote requires an enclosing quasiquote'),
            ('`,@(list 1)', 'unquote-splicing requires a list element position'),
            ('`(head . ,@(list 1))', 'unquote-splicing requires a list element position'),
            ('`(unquote 1 2)', 'unquote requires one expression'),
            ('(quasiquote)', 'quasiquote requires one datum'),
        ]
        for expression, message in cases:
            with self.subTest(expression=expression), self.assertRaisesRegex(CompileError, message):
                compile_source(f'(define (test) {expression})')
        result = self.execute('''
        (define (improper) (cons 1 2))
        (define (test) `(,@(improper) end))
        ''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unquote-splicing expects a proper list', result.stderr)

    def test_append_shares_the_final_argument_and_copies_the_rest(self):
        self.value('''
        (define (test)
          (let* ((prefix (list (list 41) 7 8)) (suffix (list 1)))
            (cons 0 0)
            (cons 0 0)
            (let ((joined (append () prefix () suffix)))
              (if (and (null? (append)) (eq? (append suffix) suffix)
                       (not (eq? joined prefix))
                       (eq? (car joined) (car prefix))
                       (eq? (cdr (cdr (cdr joined))) suffix)
                       (= (car (cdr (cdr prefix))) 8))
                  (+ (car (car joined)) (car (cdr joined)) (car suffix))
                  0))))
        ''', 49)
        self.value('''
        (define (test)
          (if (equal? (append '(1) '(2 3) 4) '(1 2 3 . 4)) 49 0))
        ''', 49)
        result = self.execute('(define (test) (append (cons 1 2) ()))')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('append expects proper lists', result.stderr)

    def test_structural_equality_does_not_recurse_on_the_vm_stack(self):
        self.value('''
        (define (nest n value)
          (if (= n 0) value (nest (- n 1) (list value))))
        (define (test)
          (let* ((a (nest 70 'left)) (b (nest 70 'left)) (c (nest 70 'right)))
            (if (and (equal? a b) (not (equal? b c))) 49 0)))
        ''', 49)

    def test_vector_values_pass_through_calls(self):
        self.value('''
        (define (identity x) x)
        (define (test)
          (let* ((vector (identity (quake:vector 20 21 8)))
                 (bag (list vector)))
            (cons 1 2)
            (cons 3 4)
            (if (and (quake:vector? (car bag)) (not (pair? vector)))
                (+ (quake:vector-x vector) (quake:vector-y (car bag))
                   (quake:vector-z (identity vector)))
                0)))
        ''', 49)

    def test_equal_compares_vector_components(self):
        self.value('''
        (define (test)
          (let ((a (quake:vector 1 -0.0 3)))
            (if (and (equal? a (quake:vector 1 0 3))
                     (not (equal? a (quake:vector 1 0 4)))
                     (not (equal? a (cons 1 (cons 0 3)))))
                49 0)))
        ''', 49)

    def test_named_procedures_are_values_and_indirect_tail_calls_release_frames(self):
        self.value('''
        (define (left peer n) (if (= n 0) 49 (peer left (- n 1))))
        (define (right peer n) (if (= n 0) 49 (peer right (- n 1))))
        (define (pick) left)
        (define (test)
          (if (and (procedure? (pick)) (eq? left (pick)))
              ((pick) right 1000)
              0))
        ''', 49)
        result = self.execute('''
        (define (one x) x)
        (define (test) (let ((f one)) (f 1 2)))
        ''')
        self.assertEqual(result.returncode, 2)
        self.assertIn('procedure does not accept 2 arguments', result.stderr)

    def test_higher_order_map_and_fold_in_the_list_library(self):
        self.value('''
        (import "../qslisp/list.scm")
        (define (square n) (* n n))
        (define (accumulate total n) (+ total n))
        (define (test) (fold accumulate 0 (map square '(2 3 6))))
        ''', 49, filename=str(ROOT / 'examples/list-test.scm'))

    def test_list_search_length_and_iteration(self):
        self.value('''
        (import "../qslisp/list.scm")
        (define (test)
          (let* ((entries '(((relay 1) . 7) ((relay 1) . 8)))
                 (items '(1 (relay 1) 3))
                 (order 0))
            (for-each (lambda (n) (set! order (+ (* 10 order) n))) '(4 2))
            (if (and (= (length items) 3) (= (length ()) 0)
                     (eq? (member '(relay 1) items) (cdr items))
                     (eq? (assoc '(relay 1) entries) (car entries))
                     (not (member 4 items)) (not (assoc 'missing entries)))
                (+ order (cdr (assoc '(relay 1) entries)))
                0)))
        ''', 49, filename=str(ROOT / 'examples/list-test.scm'))

    def test_escaping_closures_share_mutable_bindings(self):
        self.value('''
        (define (counter n)
          (cons (lambda () (set! n (+ n 1)))
                (lambda () n)))
        (define (test)
          (let* ((state (counter 40)) (step (car state)) (peek (cdr state)))
            (cons 1 2) (cons 3 4) (cons 5 6)
            (step)
            (cons 7 8) (cons 9 10) (cons 11 12)
            (step)
            (if (and (procedure? step) (not (equal? step peek))) (+ (peek) 7) 0)))
        ''', 49)

    def test_named_let_can_capture_and_preserves_initializer_scope(self):
        self.value('''
        (define (test)
          (let ((loop 49))
            (let loop ((n 300) (result loop))
              (if (= n 0) result (loop (- n 1) result)))))
        ''', 49)
        result = self.execute('(define (test) (letrec ((x x)) x))')
        self.assertEqual(result.returncode, 2)
        self.assertIn('binding used before initialization', result.stderr)

    def test_assignment_keeps_prior_argument_values_and_lexical_scopes(self):
        self.value('''
        (define (sum x y z) (+ x y z))
        (define (test)
          (let* ((n 1) (copy n))
            (+ (sum n (begin (set! n 6) 7) copy) (* n 6) 4)))
        ''', 49)

    def test_macros_rename_their_locals_without_capturing_arguments(self):
        self.value('''
        (define-syntax add-local
          (syntax-rules () ((_ value body) (let* ((temp value) (later (+ temp 1))) (+ later body)))))
        (define (test) (let ((temp 41)) (add-local 7 temp)))
        ''', 49)

    def test_macros_expand_nested_repetitions_and_top_level_definitions(self):
        self.value('''
        (define-syntax define-values-by-row
          (syntax-rules (row)
            ((_ (row name value ...) ...)
             (begin (define (name) (list value ...)) ...))))
        (define-values-by-row (row empty) (row example 20 29))
        (define (test)
          (if (and (null? (empty)) (equal? (example) '(20 29)))
              (+ (car (example)) (car (cdr (example))))
              0))
        ''', 49)

    def test_imports_are_relative_and_shared_dependencies_load_once(self):
        with tempfile.TemporaryDirectory(dir=self.work) as directory:
            root = Path(directory)
            (root / 'shared.scm').write_text('(define offset 48)', encoding='utf-8')
            (root / 'feature.scm').write_text('(import "shared.scm") (define (answer) (+ offset 1))', encoding='utf-8')
            self.value('(import "shared.scm" "feature.scm") (define (test) (answer))', 49,
                       filename=str(root / 'entry.scm'))
            (root / 'shared.scm').write_text('(import "entry.scm")', encoding='utf-8')
            with self.assertRaisesRegex(CompileError, r'shared\.scm:1:9: cyclic import'):
                compile_source('(import "feature.scm")', str(root / 'entry.scm'))

    def test_callback_context_and_entity_reference_field(self):
        path = self.program('''
        (define-field owner-ref entity)
        (define (remember)
          (cons 1 2)
          (cons 3 4)
          (quake:set-field! (quake:self) owner-ref (quake:other))
          (quake:set-field! (quake:self) count (+ (quake:field (quake:self) count) 1)))
        (define-field count)
        (define (test)
          (let ((player (quake:self)) (world (quake:world)) (live (cons 4 5)))
            (quake:set-callback! player use remember)
            (quake:call-callback player use player)
            (quake:set-callback! player use #f)
            (quake:call-callback player use world)
            (if (and (quake:entity=? (quake:field player owner-ref) player)
                     (quake:entity=? (quake:other) world))
                (+ (car live) (quake:field player count)) 0)))
        ''', heap_pairs=3)
        data = bytearray(path.read_bytes())
        header = STOCK.validate(data)
        struct.pack_into('<i', data, header[12] + 28 * 4, header[14] * 4)
        path.write_bytes(data)
        result = subprocess.run([str(ROOT / 'tools/quakec/run-stock.sh'), str(path), 'test'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('return: 5\n', result.stdout)

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
