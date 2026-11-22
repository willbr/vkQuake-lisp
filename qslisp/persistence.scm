; Snapshot a Lisp list of entity references into stock saveable edict fields.
(define-syntax define-saved-entity-list
  (syntax-rules ()
    ((define-saved-entity-list read write length-field (slot ...))
     (begin
       (define-field length-field)
       (define-field slot entity) ...
       (define (read owner)
         (let ((length (quake:field owner length-field)))
           (read-entity-slots owner length slot ...)))
       (define (write owner values)
         (let ((length (saved-entity-list-length values (entity-slot-count slot ...) 0)))
           (write-entity-slots owner values slot ...)
           (quake:set-field! owner length-field length)
           values))))))

(define-syntax entity-slot-count
  (syntax-rules ()
    ((entity-slot-count) 0)
    ((entity-slot-count first rest ...) (+ 1 (entity-slot-count rest ...)))))

(define-syntax read-entity-slots
  (syntax-rules ()
    ((read-entity-slots owner remaining) ())
    ((read-entity-slots owner remaining first rest ...)
     (if (> remaining 0)
         (let ((next (- remaining 1)))
           (cons (quake:field owner first) (read-entity-slots owner next rest ...)))
         ()))))

(define-syntax write-entity-slots
  (syntax-rules ()
    ((write-entity-slots owner values) #f)
    ((write-entity-slots owner values first rest ...)
     (let ((head (if (null? values) (quake:world) (car values)))
           (tail (if (null? values) () (cdr values))))
       (quake:set-field! owner first head)
       (write-entity-slots owner tail rest ...)))))

(define (saved-entity-list-length values limit length)
  (cond
    ((null? values) length)
    ((and (< length limit) (pair? values) (quake:entity? (car values)))
     (saved-entity-list-length (cdr values) limit (+ length 1)))
    (else (quake:error "saved entity list requires a proper list within its slot limit\n"))))
