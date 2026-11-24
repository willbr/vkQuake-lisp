; Compile with: python3 -m qslisp examples/pairs.scm -o build/pairs.dat --report
(define (test)
  (let ((p (cons 7 9)))
    (+ (car p) (cdr p))))

; Pairs live in a fixed arena that is released when the engine entry returns.
; This entry needs 65 cells: with --heap-pairs 8 it reports an exhausted heap.
(define (churn n p)
  (if (= n 0)
      (+ (car p) (cdr p))
      (begin
        (cons n n)
        (churn (- n 1) p))))

(define (churn-test)
  (churn 64 (cons 7 9)))
