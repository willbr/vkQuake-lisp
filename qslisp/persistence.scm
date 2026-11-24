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

; Project a Lisp record onto typed saveable slots. Supply an accessor for each
; slot and a constructor that accepts those same values in declaration order.
(define-syntax define-saved-record
  (syntax-rules ()
    ((define-saved-record read write construct (slot type access) ...)
     (begin
       (define-field slot type) ...
       (define (read owner)
         (construct (quake:field owner slot) ...))
       (define (write owner value)
         (let ((snapshot (list (access value) ...)))
           (write-record-slots owner snapshot slot ...)
           value))))))

(define-syntax write-record-slots
  (syntax-rules ()
    ((write-record-slots owner snapshot) #f)
    ((write-record-slots owner snapshot first rest ...)
     (begin
       (quake:set-field! owner first (car snapshot))
       (write-record-slots owner (cdr snapshot) rest ...)))))

; Carry a Lisp list of up to 15 numbers across a level change. Entity fields
; do not survive changelevel; the stock engine copies parm1-parm16 between
; SetChangeParms and the next level's PutClientInServer, and saves them.
; parm16 holds the length.
(define (set-parm-slot! index value)
  (cond ((= index 1) (quake:set-parm! 1 value)) ((= index 2) (quake:set-parm! 2 value))
        ((= index 3) (quake:set-parm! 3 value)) ((= index 4) (quake:set-parm! 4 value))
        ((= index 5) (quake:set-parm! 5 value)) ((= index 6) (quake:set-parm! 6 value))
        ((= index 7) (quake:set-parm! 7 value)) ((= index 8) (quake:set-parm! 8 value))
        ((= index 9) (quake:set-parm! 9 value)) ((= index 10) (quake:set-parm! 10 value))
        ((= index 11) (quake:set-parm! 11 value)) ((= index 12) (quake:set-parm! 12 value))
        ((= index 13) (quake:set-parm! 13 value)) ((= index 14) (quake:set-parm! 14 value))
        (else (quake:set-parm! 15 value))))

(define (parm-slot index)
  (cond ((= index 1) (quake:parm 1)) ((= index 2) (quake:parm 2)) ((= index 3) (quake:parm 3))
        ((= index 4) (quake:parm 4)) ((= index 5) (quake:parm 5)) ((= index 6) (quake:parm 6))
        ((= index 7) (quake:parm 7)) ((= index 8) (quake:parm 8)) ((= index 9) (quake:parm 9))
        ((= index 10) (quake:parm 10)) ((= index 11) (quake:parm 11)) ((= index 12) (quake:parm 12))
        ((= index 13) (quake:parm 13)) ((= index 14) (quake:parm 14)) (else (quake:parm 15))))

(define (carry-slots! values index)
  (cond
    ((null? values) (quake:set-parm! 16 (- index 1)))
    ((> index 15) (quake:error "carried list holds at most 15 numbers\n"))
    (else (set-parm-slot! index (car values)) (carry-slots! (cdr values) (+ index 1)))))

(define (carry! values) (carry-slots! values 1))

(define (carried-slots index count)
  (if (> index count) () (cons (parm-slot index) (carried-slots (+ index 1) count))))

(define (carried) (carried-slots 1 (quake:parm 16)))
