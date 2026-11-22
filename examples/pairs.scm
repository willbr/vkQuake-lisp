; Compile with: python3 -m qslisp examples/pairs.scm -o build/pairs.dat --report
(define (test)
  (let ((p (cons 7 9)))
    (+ (car p) (cdr p))))

; With --heap-pairs 8 this allocates far more pairs than the pool can hold,
; collecting discarded cells while keeping p alive across every tail call.
(define (churn n p)
  (if (= n 0)
      (+ (car p) (cdr p))
      (begin
        (cons n n)
        (churn (- n 1) p))))

(define (gc-test)
  (churn 64 (cons 7 9)))
