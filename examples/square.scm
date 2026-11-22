; Compile with: python3 -m qslisp examples/square.scm -o build/square.dat
(define (square x)
  (* x x))

(define (test)
  (square 7))
