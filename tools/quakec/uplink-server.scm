; Closed-loop freight lift test, compiled only by the dedicated verifier.
(import "../../examples/map-game.scm")

(define-field driver-phase)
(define-field driver-deadline)
(define-field driver-ride-samples)

(define (driver-enter player phase timeout)
  (quake:set-field! player driver-phase phase)
  (quake:set-field! player driver-deadline (+ (quake:time) timeout)))

(define-syntax driver-fail
  (syntax-rules ()
    ((driver-fail player reason)
     (begin (quake:dprint reason) (driver-stop player)))))

(define (driver-stop player)
  (trace-numbers "lift-test failure state/x/y/z/heading" (quake:field player driver-phase)
    (quake:field player origin_x) (quake:field player origin_y) (quake:field player origin_z)
    (quake:field player bike-heading))
  (driver-enter player -1 0))

(define (driver-distance player x y)
  (quake:vector-length
    (quake:vector (- x (quake:field player origin_x)) (- y (quake:field player origin_y)) 0)))

(define (driver-speed player)
  (quake:vector-length
    (quake:vector (quake:field player bike-vx) (quake:field player bike-vy) 0)))

(define (driver-at? player x y radius)
  (and (< (driver-distance player x y) radius) (< (driver-speed player) 9)))

(define (driver-steer player x y)
  (let* ((distance (driver-distance player x y))
         (speed (driver-speed player))
         (target (bike-clamp (* (- distance 14) 2) 0 200)))
    (if (and (> target 0) (< speed target))
        (quake:set-field! player button0 1)
        (quake:set-field! player button2 1))
    (if (> distance 14)
        (quake:vector-yaw
          (quake:vector (- x (quake:field player origin_x)) (- y (quake:field player origin_y)) 0))
        (quake:field player bike-heading))))

(define (driver-control player lift phase)
  (let ((x (quake:field lift lift-x))
        (y (quake:field lift lift-y))
        (heading (quake:field player bike-heading)))
    (cond
      ((= phase 0)
       (when (string=? (quake:field (aimed-entity player 96) classname) "qslisp_bike")
         (quake:dprint "lift-test: mounting\n")
         (quake:set-field! player impulse 3)
         (driver-enter player 1 8))
       #f)
      ((not (riding-bike? player))
       (driver-fail player "lift-test: rider lost the bike\n") #f)
      ((= phase 1)
       (let ((landing (- y 365)))
         (if (driver-at? player x landing 24)
             (begin
               (trace-numbers "lift-test called x/y/heading" (quake:field player origin_x)
                 (quake:field player origin_y) heading)
               (quake:set-field! player impulse 3)
               (driver-enter player 2 7)
               heading)
             (driver-steer player x landing))))
      ((= phase 2)
       (when (and (= (quake:field lift lift-up) 1) (= (quake:field lift lift-moving) 0))
         (quake:dprint "lift-test: platform at freight landing\n")
         (driver-enter player 3 8))
       heading)
      ((= phase 3)
       (if (and (driver-at? player x y 25)
                (quake:entity=? (quake:field player groundentity) lift))
           (begin
             (quake:dprint "lift-test: rider standing on platform\n")
             (quake:set-field! player impulse 3)
             (driver-enter player 4 7)
             heading)
           (driver-steer player x y)))
      (else
       (let* ((height (quake:field lift origin_z))
              (expected (+ (quake:field lift lift-floor) height 24))
              (actual (quake:field player origin_z))
              (samples (quake:field player driver-ride-samples)))
         (cond
           ((> (bike-abs (- expected actual)) 10)
            (driver-fail player "lift-test: rider separated from platform\n"))
           ((= (quake:field lift lift-moving) 1)
            (quake:set-field! player driver-ride-samples (+ samples 1)))
           ((and (< height 1) (> samples 20)
                 (quake:entity=? (quake:field player groundentity) lift))
            (trace-numbers "lift-test arrived rider-z/platform-z/samples" actual
              (+ (quake:field lift lift-floor) height) samples)
            (driver-enter player 5 1.7)))
         heading)))))

(define (driver-camera-sample player)
  (let ((remaining (- (quake:field player driver-deadline) (quake:time)))
        (camera (quake:field player bike-camera)))
    (cond
      ((<= remaining 0)
       (quake:dprint "lift-test: passed\n")
       (driver-enter player 6 0))
      ((< remaining 1)
       (trace-numbers "lift-test parked camera-z/client-pitch"
         (quake:field camera origin_z) (quake:field player v_angle_x))))
    (quake:field player bike-heading)))

(define (PlayerPreThink)
  (let* ((player (quake:self)) (phase (quake:field player driver-phase)))
    (quake:set-field! player button0 0)
    (quake:set-field! player button2 0)
    (quake:set-field! player impulse 0)
    (when (and (= phase 0) (= (quake:field player driver-deadline) 0))
      (driver-enter player 0 5))
    (let ((steering
            (cond
              ((or (< phase 0) (= phase 6)) (quake:field player bike-heading))
              ((= phase 5) (driver-camera-sample player))
              ((> (quake:time) (quake:field player driver-deadline))
               (driver-fail player "lift-test: timed out waiting for progress\n") #f)
              (else (driver-control player (uplink-named "freight-lift") phase)))))
      (player-prethink player steering))))
