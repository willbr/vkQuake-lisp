"""Tail-call behavior measured by executing on the unchanged stock interpreter."""
import re
import struct
import unittest

from qslisp.tests.test_compiler import CompilerCase, ROOT


class TailCallTests(CompilerCase):
    def test_self_tail_sum_beyond_native_stack_depth(self):
        result = self.value((ROOT / 'examples/tail-calls.scm').read_text(), 500500)
        instructions = int(re.search(r'instructions: (\d+)', result.stdout)[1])
        self.assertLess(instructions, 100000)

    def test_mutual_tail_calls_beyond_native_stack_depth(self):
        result = self.value((ROOT / 'examples/tail-calls.scm').read_text(), 49, 'mutual-test')
        self.assertLess(int(re.search(r'instructions: (\d+)', result.stdout)[1]), 100000)

    def test_self_tail_arguments_are_updated_in_parallel(self):
        self.value('''
        (define (swap n a b)
          (if (= n 0) (+ (* a 10) b) (swap (- n 1) b a)))
        (define (test) (swap 1001 1 2))
        ''', 21)

    def test_eight_argument_self_tail_permutation(self):
        self.value('''
        (define (rotate n a b c d e f g)
          (if (= n 0)
              (+ (* a 100) (* b 10) c)
              (rotate (- n 1) b c d e f g a)))
        (define (test) (rotate 1000 1 2 3 4 5 6 7))
        ''', 712)

    def test_self_tail_binding_aliases_and_nested_argument_calls(self):
        self.value('''
        (define (id x) x)
        (define (swap n a b)
          (let ((x a) (y b))
            (if (= n 0)
                (+ (* x 10) y)
                (swap (- n 1) (id y) (id x)))))
        (define (test) (swap 101 1 2))
        ''', 21)

    def test_tail_positions_in_begin_let_and_both_if_branches(self):
        self.value('''
        (define (id x) x)
        (define (walk n)
          (id n)
          (begin
            (+ 1 2)
            (let ((next (- n 1)))
              (if (> n 500)
                  (walk next)
                  (if (> n 0) (walk next) 49)))))
        (define (test) (walk 1000))
        ''', 49)

    def test_mutual_tail_calls_with_eight_two_and_zero_parameters(self):
        self.value('''
        (define (few n flag)
          (if (= n 0)
              (finish)
              (many (- n 1) flag 2 3 4 5 6 7)))
        (define (many n flag a b c d e f)
          (if flag 0 (few n (not #t))))
        (define (finish) 49)
        (define (test) (few 1000 #f))
        ''', 49)

    def test_tail_call_chain_longer_than_the_native_stack(self):
        functions = [f'(define (chain-{i}) (chain-{i + 1}))' for i in range(80)]
        source = '\n'.join(functions) + '\n(define (chain-80) 49)\n(define (test) (chain-0))'
        self.value(source, 49)

    def test_internal_control_names_do_not_collide_with_user_functions(self):
        source = '''
        (define (dispatch x) (request_leaf x))
        (define (request_leaf x) (leaf x))
        (define (leaf x) x)
        (define (error) 49)
        (define (test) (+ (dispatch 1) (error)))
        '''
        self.value(source, 50)
        data = self.program(source).read_bytes()
        header = struct.unpack_from('<15i', data)
        strings = data[header[10]:header[10] + header[11]]
        for section, count, stride, name_offset in (
            (header[8], header[9], 36, 16),
            (header[4], header[5], 8, 4),
        ):
            names = [strings[struct.unpack_from('<i', data, section + i * stride + name_offset)[0]:]
                     .split(b'\0')[0] for i in range(count)]
            self.assertEqual(len(names), len(set(names)))

    def test_nested_tail_requests_do_not_clobber_arguments_or_target(self):
        self.value('''
        (define (id x) x)
        (define (forward x) (id x))
        (define (left n acc)
          (if (= n 0)
              acc
              (right (- n 1) (+ acc (forward 1)))))
        (define (right n acc) (left n acc))
        (define (test) (+ (left 100 7) (left 100 9)))
        ''', 216)

    def test_pending_requests_do_not_escape_into_values(self):
        self.value('''
        (define (even? n) (if (= n 0) #t (odd? (- n 1))))
        (define (odd? n) (if (= n 0) #f (even? (- n 1))))
        (define (zero n) (if (= n 0) 0 (zero (- n 1))))
        (define (test)
          (+ (if (even? 1000) 1 10)
             (if (odd? 1000) 20 2)
             (if (zero 100) 3 30)))
        ''', 6)

    def test_type_tags_survive_self_tail_parameter_updates(self):
        self.value('''
        (define (toggle n flag)
          (if (= n 0) (if flag 1 2) (toggle (- n 1) (not flag))))
        (define (test) (toggle 1001 #f))
        ''', 1)
        result = self.execute('''
        (define (loop n x) (if (= n 0) (+ x 1) (loop (- n 1) #f)))
        (define (test) (loop 1000 0))
        ''')
        self.assertEqual(result.returncode, 2)
        self.assertIn('expected a number', result.stderr)

    def test_mutual_tail_calls_release_large_local_frames(self):
        expression = '(+ ' + ' '.join(['1'] * 300) + ')'
        self.value(f'''
        (define (large n)
          {expression}
          (if (= n 0) 49 (small (- n 1))))
        (define (small n) (large n))
        (define (test) (large 50))
        ''', 49)

    def test_non_tail_calls_keep_their_continuations(self):
        self.value('''
        (define (sum n) (if (= n 0) 0 (+ n (sum (- n 1)))))
        (define (test) (sum 10))
        ''', 55)
        for body in ('(+ 1 (test))', '(if (test) 1 2)',
                     '(let ((x (test))) x)', '(begin (test) 49)'):
            with self.subTest(body=body):
                result = self.execute(f'(define (test) {body})')
                self.assertEqual(result.returncode, 2)
                self.assertIn('stack overflow', result.stdout)
                self.assertNotIn('runaway loop error', result.stdout)

    def test_ordinary_calls_use_one_native_frame_each(self):
        source = '''
        (define (count n) (if (= n 0) 0 (+ 1 (count (- n 1)))))
        (define (test) (count 28))
        (define (too-deep) (count 40))
        '''
        self.value(source, 28)
        result = self.execute(source, 'too-deep')
        self.assertEqual(result.returncode, 2)
        self.assertIn('stack overflow', result.stdout + result.stderr)

    def test_infinite_tail_loops_still_hit_stock_watchdog(self):
        for source in (
            '(define (test) (test))',
            '(define (test) (peer)) (define (peer) (test))',
        ):
            with self.subTest(source=source):
                result = self.execute(source)
                self.assertEqual(result.returncode, 2)
                self.assertIn('runaway loop error', result.stdout)
                self.assertNotIn('stack overflow', result.stdout)


if __name__ == '__main__':
    unittest.main()
