; Both loops run well beyond stock Quake's native call-stack depth.
(define (sum n acc)
  (if (= n 0)
      acc
      (sum (- n 1) (+ acc n))))

(define (test)
  (sum 1000 0))

(define (even? n)
  (if (= n 0) #t (odd? (- n 1))))

(define (odd? n)
  (if (= n 0) #f (even? (- n 1))))

(define (mutual-test)
  (if (even? 1000) 49 0))
