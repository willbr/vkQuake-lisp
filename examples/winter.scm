; The AI Winter: a frozen Lisp lab where the seven primitives define eval.
(define-field ice-until)
(define-field ice-vx)
(define-field ice-vy)
(define-field warm-until)
(define-field cold-warned)
(define-field spin)
(define-field winter-dx)
(define-field winter-dy)
(define all-runes 2032)

; Ice: stock Quake has no per-entity friction, so an ice volume gives back
; most of the speed that ground friction took this frame.
(define (winter_ice)
  (lambda-trigger (quake:self))
  (quake:set-callback! (quake:self) touch touch-ice))

(define (touch-ice)
  (let ((player (lambda-other)))
    (when player (quake:set-field! player ice-until (+ (quake:time) 0.1)))))

(define (ice-step player)
  (let* ((vx (quake:field player velocity_x)) (vy (quake:field player velocity_y))
         (px (quake:field player ice-vx)) (py (quake:field player ice-vy))
         (on-ice (and (> (quake:field player ice-until) (quake:time))
                      (> (quake:bit-and (quake:field player flags) flag-ground) 0))))
    (when (and on-ice (< (+ (* vx vx) (* vy vy)) (+ (* px px) (* py py))))
      (let ((give-back (tunable 1 0.85)))
        (quake:set-field! player velocity_x (+ vx (* give-back (- px vx))))
        (quake:set-field! player velocity_y (+ vy (* give-back (- py vy))))))
    (quake:set-field! player ice-vx (quake:field player velocity_x))
    (quake:set-field! player ice-vy (quake:field player velocity_y))))

; Cold: outside heater volumes, players lose health every second.
(define (winter_heat)
  (lambda-trigger (quake:self))
  (quake:set-callback! (quake:self) touch touch-heat))

(define (touch-heat)
  (let ((player (lambda-other)))
    (when player (quake:set-field! player warm-until (+ (quake:time) 0.3)))))

; Warmth uses the stock armor gauge: heaters fill it, the cold drains it, and
; the status bar's three armor icons show it as green, yellow, and red.
(define armor-bits 57344)

(define (winter_cold)
  (quake:set-callback! (quake:self) think cold-think)
  (quake:set-field! (quake:self) nextthink (+ (quake:time) 0.5)))

(define (warmth-icon warmth)
  (cond ((> warmth 66) 8192) ((> warmth 33) 16384) (else 32768)))

(define (chill cursor)
  (let ((player (quake:find cursor classname "qslisp_player")))
    (when (not (quake:world? player))
      (when (active-player? player)
        (let* ((heated (> (quake:field player warm-until) (quake:time)))
               (warmth (bike-clamp (+ (quake:field player armorvalue) (if heated (tunable 6 20) (- (tunable 5 5))))
                                   0 100))
               (items (quake:field player items)))
          (quake:set-field! player armorvalue warmth)
          (quake:set-field! player items (+ (- items (quake:bit-and items armor-bits)) (warmth-icon warmth)))
          (when (<= warmth 0)
            (damage player (quake:world) 3)
            (when (< (quake:field player cold-warned) (quake:time))
              (quake:set-field! player cold-warned (+ (quake:time) 6))
              (quake:centerprint player "Freezing. Find a heater.")
              (quake:dprint "winter: player freezing\n")))))
      (chill player))))

(define (cold-think)
  (quake:set-field! (quake:self) nextthink (+ (quake:time) 0.5))
  (check-rune-gate)
  (chill (quake:world)))

; Fans and the dish spin as non-solid brush models; stock rotates them visually.
(define (winter_fan)
  (let ((fan (quake:self)))
    (quake:set-model fan (quake:field fan model))
    (quake:set-field! fan solid 0)
    (quake:set-field! fan movetype move-noclip)
    (quake:set-origin fan (quake:vector (quake:field fan winter-dx) (quake:field fan winter-dy) 0))
    (quake:set-field! fan avelocity (quake:vector 0 (quake:field fan spin) 0))))

; The rune gate opens once all seven primitives are in serverflags. Brush
; models think on ltime, and a save taken as ltime reaches nextthink stalls
; that timer after loading, so the cold controller checks the gate instead.
(define (winter_gate)
  (lambda-brush (quake:self)))

(define (check-rune-gate)
  (let ((gate (lambda-named "rune-gate")))
    (when (and (not (quake:world? gate)) (> (quake:field gate solid) 0)
               (= (quake:bit-and (quake:serverflags) all-runes) all-runes))
      (quake:set-field! gate solid 0)
      (quake:set-field! gate modelindex 0)
      (quake:set-origin gate (quake:field gate origin))
      (quake:bprint "The seven primitives are complete. The gate to eval opens.\n")
      (quake:dprint "winter: rune gate open\n"))))

(define (winter_exit)
  (lambda-trigger (quake:self))
  (quake:set-callback! (quake:self) touch finish-episode))

(define (rune-name index)
  (cond ((= index 1) " quote") ((= index 2) " atom") ((= index 3) " eq") ((= index 4) " car")
        ((= index 5) " cdr") ((= index 6) " cons") (else " cond")))

; rune-order holds base-8 digits, oldest first.
(define (print-rune-order player order)
  (when (> order 0)
    (let ((rest (quake:floor (/ order 8))))
      (print-rune-order player rest)
      (quake:sprint player (rune-name (- order (* rest 8)))))))

(define (finish-episode)
  (let ((player (lambda-other)) (exit (quake:self)))
    (when player
      (quake:sprint player "(define eval (lambda")
      (print-rune-order player (quake:field player rune-order))
      (quake:sprint player "))\n")
      (quake:centerprint player "The AI Winter thaws.\nEval is defined from seven primitives.\nEpisode complete.")
      (quake:set-serverflags! (quake:bit-or (quake:serverflags) 4))
      (quake:dprint "winter: episode complete\n")
      (quake:set-field! exit solid 0)
      (quake:set-origin exit (quake:field exit origin)))))
