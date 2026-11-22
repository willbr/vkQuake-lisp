; Stock-engine actor and sequence declarations.
(define-syntax define-actor
  (syntax-rules (spawn context states)
    ((define-actor classname tick actor state-field interval
        (spawn initial)
        (context binding ...)
        (states (state action) ...))
     (begin
       (define (classname)
         (let ((actor (quake:self)))
           initial
           (quake:set-callback! actor think tick)
           (quake:set-field! actor nextthink (+ (quake:time) interval))))
       (define (tick)
         (let* ((actor (quake:self)) binding ...)
           (quake:set-field! actor nextthink (+ (quake:time) interval))
           (cond ((= (quake:field actor state-field) state) action) ...)))))))

(define-syntax define-sequence
  (syntax-rules (step)
    ((define-sequence (step name action ...) ...)
     (begin (define (name) action ...) ...))))

(define-syntax after
  (syntax-rules ()
    ((after duration callback)
     (let* ((subject (quake:self))
            (clock (if (= (quake:field subject movetype) 7)
                       (quake:field subject ltime)
                       (quake:time))))
       (quake:set-callback! subject think callback)
       (quake:set-field! subject nextthink (+ clock duration))))))
