; Higher-order operations on proper lists.
(define (fold combine state items)
  (if (null? items)
      state
      (fold combine (combine state (car items)) (cdr items))))

(define (list-reverse-onto items result)
  (if (null? items)
      result
      (list-reverse-onto (cdr items) (cons (car items) result))))

(define (map-reversed transform items result)
  (if (null? items)
      (list-reverse-onto result ())
      (map-reversed transform (cdr items) (cons (transform (car items)) result))))

(define (map transform items)
  (map-reversed transform items ()))
