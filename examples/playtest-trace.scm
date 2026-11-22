; Developer-only samples. Console commands keep normal play silent.
(define-field trace-until)
(define-field trace-next)
(define-field buddy-trace-goal entity)

(define-syntax trace-numbers
  (syntax-rules ()
    ((trace-numbers label value ...)
     (begin
       (quake:dprint label)
       (begin (quake:dprint " ") (quake:dprint-number value)) ...
       (quake:dprint "\n")))))

(define (trace-command player)
  (when (= (quake:field player impulse) 24)
    (quake:set-field! player impulse 0)
    (if (> (quake:field player trace-until) (quake:time))
        (quake:set-field! player trace-until 0)
        (begin
          (quake:set-field! player trace-until (+ (quake:time) 12))
          (quake:set-field! player trace-next 0)
          (quake:dprint "trace bike: time player steer ground bank speed grip x y z cam-x cam-y cam-z\n")
          (quake:dprint "trace buddy: time state reason goal-x goal-y goal-z\n")
          (quake:dprint "trace tether: time player attached\n")
          (quake:dprint "trace tether-aim: player x y z pitch yaw hit\n")))))

(define (trace-tether-event player attached)
  (when (< (quake:time) (quake:field player trace-until))
    (trace-numbers "tether" (quake:time) (quake:field player colormap) attached)))

(define (trace-tether-aim player hit)
  (when (< (quake:time) (quake:field player trace-until))
    (trace-numbers "tether-aim" (quake:field player colormap)
      (quake:field player origin_x) (quake:field player origin_y) (quake:field player origin_z)
      (quake:field player v_angle_x) (quake:field player v_angle_y) hit)))

(define (sample-bike player)
  (let ((camera (quake:field player bike-camera)))
    (trace-numbers "bike" (quake:time) (quake:field player colormap)
      (quake:field player bike-front-angle)
      (if (> (quake:bit-and (quake:field player flags) flag-ground) 0) 1 0)
      (quake:field player bike-bank-contact)
      (quake:vector-length (quake:vector (quake:field player bike-vx) (quake:field player bike-vy) 0))
      (quake:field player bike-contact-grip)
      (quake:field player origin_x) (quake:field player origin_y) (quake:field player origin_z)
      (quake:field camera origin_x) (quake:field camera origin_y) (quake:field camera origin_z))))

(define (sample-buddy buddy)
  (let ((goal (quake:field buddy buddy-trace-goal)))
    (trace-numbers "buddy" (quake:time)
      (quake:field buddy buddy-state) (quake:field buddy buddy-trace-reason)
      (quake:field goal origin_x) (quake:field goal origin_y) (quake:field goal origin_z))))

(define (sample-gameplay player riding)
  (let ((now (quake:time)))
    (when (and (< now (quake:field player trace-until)) (>= now (quake:field player trace-next)))
      (quake:set-field! player trace-next (+ now 0.1))
      (when riding (sample-bike player))
      (let ((buddy (uplink-teammate)))
        (when (not (quake:world? buddy)) (sample-buddy buddy))))))
