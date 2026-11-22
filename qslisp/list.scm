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

(define (length items)
  (list-length-from items 0))

(define (list-length-from items count)
  (if (null? items)
      count
      (list-length-from (cdr items) (+ count 1))))

(define (member key items)
  (cond
    ((null? items) #f)
    ((equal? key (car items)) items)
    (else (member key (cdr items)))))

(define (assoc key entries)
  (if (null? entries)
      #f
      (let ((entry (car entries)))
        (if (equal? key (car entry))
            entry
            (assoc key (cdr entries))))))

(define (for-each visit items)
  (if (null? items)
      #f
      (begin
        (visit (car items))
        (for-each visit (cdr items)))))
