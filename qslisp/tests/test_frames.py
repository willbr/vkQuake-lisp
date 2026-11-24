"""Local-slot reuse: frames stay small and reused slots never hold a live value."""
import struct
import unittest

from qslisp.compiler import Compiler, compile_source
from qslisp.reader import CompileError, read
from qslisp.tests.test_compiler import CompilerCase, STOCK


def frame_words(data, name):
    header = STOCK.validate(data)
    strings = data[header[10]:header[10] + header[11]]
    for i in range(header[9]):
        function = struct.unpack_from('<7i8B', data, header[8] + i * 36)
        if strings[function[4]:].split(b'\0')[0] == name.encode():
            return function[2]
    raise KeyError(name)


class FrameTests(CompilerCase):
    def test_discarded_statements_share_slots(self):
        statement = '(+ ' + ' '.join(['1'] * 30) + ')'
        one = frame_words(compile_source(f'(define (test) {statement} 49)'), '__qslisp_fn_test')
        many = frame_words(compile_source(f'(define (test) {statement * 40} 49)'), '__qslisp_fn_test')
        self.assertEqual(one, many)
        self.value(f'(define (test) {statement * 40} 49)', 49)

    def test_branch_arms_share_slots(self):
        arm = '(+ ' + ' '.join(['n'] * 30) + ')'
        clauses = ' '.join(f'((= n {i}) {arm})' for i in range(40))
        source = f'''
        (define (pick n) (cond {clauses} (else 0)))
        (define (pick-value n) (+ 1 (cond {clauses} (else 0))))
        (define (test) (+ (pick 3) (pick-value 39)))
        '''
        data = compile_source(source)
        self.assertLess(frame_words(data, '__qslisp_fn_pick'), 150)
        # A value-producing arm adds one three-word result per nesting level.
        self.assertLess(frame_words(data, '__qslisp_fn_pick-value'), 150 + 3 * 40)
        self.value(source, 3 * 30 + 1 + 39 * 30)

    def test_earlier_operands_stay_live_across_reusing_expressions(self):
        self.value('''
        (define (id x) x)
        (define (busy) (+ 100 200 300) (* 7 8 9) 0)
        (define (test)
          (+ (id 1)
             (if (= (id 2) 2) (begin (busy) (* 10 (id 2))) (* 99 (id 9)))
             (id 300)
             (let ((a (id 4000)))
               (busy)
               (if (> a 0) (begin (busy) a) 0))
             (begin (busy) (busy) (id 50000))))
        ''', 54321)

    def test_condition_slots_are_reused_only_after_the_branch(self):
        self.value('''
        (define (id x) x)
        (define (choose a b c)
          (if (if (> (+ a b c) 5) (< a b) (> a b))
              (+ (id a) (if (= c 3) (id b) (id c)))
              (- (id a) (id b))))
        (define (test) (+ (* 100 (choose 1 2 3)) (* 10 (choose 2 1 0)) (choose 3 2 1)))
        ''', 300 + 20 + 1)

    def test_match_clauses_share_slots_and_keep_outer_operands(self):
        self.value('''
        (define-record point (x number) (y number))
        (define (id x) x)
        (define (measure v)
          (+ (id 1000)
             (match v
               ((point x y) (+ x y))
               ((cons a (cons b ())) (* (id a) (id b)))
               ((list a b c) (+ a (* 10 b) (* 100 c)))
               (else 7))
             (id 1)))
        (define (test)
          (+ (measure (make-point 3 4)) (measure (list 5 6)) (measure '(1 2 3)) (measure 0)))
        ''', 4 * 1001 + 7 + 30 + 321 + 7)

    def test_self_tail_loop_with_reused_slots(self):
        self.value('''
        (define (step n acc)
          (+ n n n)
          (if (= n 0)
              acc
              (step (- n 1) (if (> n 5) (+ acc n) (- acc 1)))))
        (define (test) (step 10 0))
        ''', 6 + 7 + 8 + 9 + 10 - 5)

    def test_report_names_the_worst_call_chain(self):
        compiler = Compiler(read('''
        (define (leaf x) (+ x 1))
        (define (middle x) (+ 1 (leaf x)))
        (define (test) (+ 1 (middle 1)))
        (define (loop n) (if (= n 0) 0 (+ 1 (loop (- n 1)))))
        '''), '<input>')
        compiler.compile()
        report = compiler.statistics()
        self.assertEqual(report['worst_depth_chain'],
                         ['test', '__qslisp_fn_test', '__qslisp_fn_middle', '__qslisp_fn_leaf'])
        self.assertEqual(report['worst_call_depth'], 4)
        self.assertEqual(report['recursive_functions'], ['__qslisp_fn_loop'])
        frames = compiler.program.frames
        names = compiler.program.function_names
        self.assertEqual(report['worst_local_slots'],
                         sum(frames[names.index(name)][0] for name in report['worst_local_chain']))

    def test_nested_frames_beyond_the_saved_locals_stack_fail_the_build(self):
        large = '(+ ' + ' '.join(['1'] * 400) + ')'
        with self.assertRaisesRegex(CompileError, r'call chain needs [\d,]+ saved-local slots.*outer > .*inner'):
            compile_source(f'(define (inner) {large}) (define (outer) (+ (inner) {large}))')
        # A tail call replaces the caller's frame instead of nesting under it.
        self.value(f'(define (inner) {large}) (define (test) {large} (inner))', 400)

    def test_call_chains_deeper_than_the_native_stack_fail_the_build(self):
        chain = ' '.join(f'(define (f{i}) (+ 1 (f{i + 1})))' for i in range(31))
        with self.assertRaisesRegex(CompileError, 'call chain needs 33 frames'):
            compile_source(f'{chain} (define (f31) 0)')
        chain = ' '.join(f'(define (f{i}) (+ 1 (f{i + 1})))' for i in range(29))
        self.value(f'{chain} (define (f29) 0) (define (test) (f0))', 29)

    def test_chains_follow_procedure_values_and_entity_callbacks(self):
        large = '(+ ' + ' '.join(['1'] * 400) + ')'
        for source in (
            f'(define (apply-it f) (+ (f) {large})) (define (test) (apply-it (lambda () {large})))',
            f'''(define (used) {large})
                (define (test)
                  (quake:set-callback! (quake:self) use used)
                  (+ {large} (begin (quake:call-callback (quake:self) use (quake:self)) 0)))''',
        ):
            with self.subTest(source=source[:40]):
                with self.assertRaisesRegex(CompileError, 'call chain needs'):
                    compile_source(source)


if __name__ == '__main__':
    unittest.main()
