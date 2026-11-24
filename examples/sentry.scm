; The Annex sentry uses engine-scheduled callbacks and authored waypoints.
(define-saved-entity-list sentry-route remember-sentry-route! patrol-route-length
  (patrol-route-0 patrol-route-1 patrol-route-2 patrol-route-3))
(define-field patrol-count)
(define-field sentry-state)
(define-field sentry-range)
(define-field attack-time)
(define-field respawn-ready)

(define-record damage-event (victim entity) (source entity) (amount number))
(define-record patrol-leg (waypoint entity) (remaining list))
(define-record attack-state (phase number) (deadline number))

(define move-step 4)
(define flag-monster 32)
(define sentry-patrol 0)
(define sentry-alert 1)
(define sentry-chase 2)

(define (qslisp_waypoint) 0)

(define (configure-actor actor health)
  (quake:precache-model "progs/sentry.mdl")
  (quake:set-field! actor movetype move-step)
  (quake:set-field! actor solid solid-slidebox)
  (quake:set-field! actor flags flag-monster)
  (quake:set-field! actor health health)
  (quake:set-field! actor takedamage 2)
  (quake:set-model actor "progs/sentry.mdl")
  (quake:set-size actor (quake:vector -16 -16 0) (quake:vector 16 16 48))
  (quake:drop-to-floor))

(define (player-entity? actor)
  (= (quake:bit-and (quake:field actor flags) flag-client) flag-client))

(define (damage target inflictor amount)
  (if (and (> (quake:coop) 0) (player-entity? target) (player-entity? inflictor)
           (not (quake:entity=? target inflictor)))
      (quake:dprint "qslisp: co-op friendly fire blocked\n")
      (apply-damage (make-damage-event target inflictor amount))))

(define (apply-damage event)
  (match event
    ((damage-event target inflictor amount)
     (damage-entity target inflictor amount))))

(define (damage-entity target inflictor amount)
  (when (and (> (quake:field target takedamage) 0) (> (quake:field target health) 0))
    (let ((health (- (quake:field target health) amount)))
      (if (> health 0)
          (quake:set-field! target health health)
          (quake:set-field! target health 0))
      (when (player-entity? target)
        (quake:set-field! target dmg_inflictor inflictor)
        (quake:set-field! target dmg_take (+ (quake:field target dmg_take) amount)))
      (when (<= health 0)
        (if (player-entity? target)
            (begin
              (return-bike target)
              (clear-tether target)
              (drop-beacon target)
              (clear-marks target #f)
              (quake:set-field! target deadflag 2)
              (quake:set-field! target takedamage 0)
              (quake:set-field! target movetype 0)
              (quake:set-field! target velocity (quake:vector 0 0 0))
              (quake:set-field! target weaponmodel "")
              (quake:set-field! target respawn-ready 0)
              (quake:centerprint target "Sentry got you.\nRelease and press fire to respawn.")
              (quake:dprint "qslisp: player defeated\n"))
            (begin
              (quake:remove target)
              (when (player-entity? inflictor)
                (quake:centerprint inflictor "Sentry disabled."))
              (quake:dprint "qslisp: sentry defeated\n")))))))

(define (update-respawn player)
  (when (> (quake:field player deadflag) 0)
    (if (= (quake:field player button0) 0)
        (quake:set-field! player respawn-ready 1)
        (when (= (quake:field player respawn-ready) 1)
          (PutClientInServer)
          (quake:dprint "qslisp: player respawned\n")))))

(define (sentry-facing actor point)
  (quake:vector-yaw (quake:vector (- (quake:field point origin_x) (quake:field actor origin_x))
                                  (- (quake:field point origin_y) (quake:field actor origin_y))
                                  0)))

(define (sentry-step actor point stride)
  (let ((yaw (sentry-facing actor point)))
    (quake:set-field! actor angles_y yaw)
    (quake:walkmove yaw stride)))

(define (sentry-distance-squared actor point)
  (let ((x (- (quake:field point origin_x) (quake:field actor origin_x)))
        (y (- (quake:field point origin_y) (quake:field actor origin_y))))
    (+ (* x x) (* y y))))

(define (sentry-visible? actor player)
  (let ((range (quake:field actor sentry-range)))
    (and (not (quake:world? player))
         (> (quake:field player health) 0)
         (or (<= range 0) (<= (sentry-distance-squared actor player) (* range range)))
         (quake:entity=? player
           (quake:traceline (quake:vector (quake:field actor origin_x)
                                         (quake:field actor origin_y)
                                         (+ (quake:field actor origin_z) 32))
                            (quake:vector (quake:field player origin_x)
                                         (quake:field player origin_y)
                                         (+ (quake:field player origin_z) (quake:field player view_ofs_z)))
                            0 actor)))))

(define (visible-player actor cursor)
  (let ((player (quake:find cursor classname "qslisp_player")))
    (cond
      ((quake:world? player) player)
      ((sentry-visible? actor player) player)
      (else (visible-player actor player)))))

(define (finish-patrol-leg actor leg)
  (match leg
    ((patrol-leg waypoint remaining)
     (remember-sentry-route! actor (append remaining `(,waypoint)))
     (quake:set-field! actor patrol-count (+ (quake:field actor patrol-count) 1)))))

(define (collect-patrol-route first next remaining)
  (cond
    ((or (quake:world? next) (quake:entity=? first next)) ())
    ((= remaining 0) (quake:error "sentry patrol route must contain at most four waypoints\n"))
    (else (cons next (collect-patrol-route first (find-linked next) (- remaining 1))))))

(define (start-patrol-route actor)
  (let ((first (find-linked actor)))
    (when (not (quake:world? first))
      (remember-sentry-route! actor (cons first (collect-patrol-route first (find-linked first) 3))))))

(define (patrol actor)
  (when (= (quake:field actor patrol-route-length) 0) (start-patrol-route actor))
  (let ((point (quake:field actor patrol-route-0)))
    (when (not (quake:world? point))
      (if (< (sentry-distance-squared actor point) 64)
          (finish-patrol-leg actor (make-patrol-leg point (cdr (sentry-route actor))))
          (sentry-step actor point 7)))))

(define (enter-attack-state actor state)
  (match state
    ((attack-state phase deadline)
     (quake:set-field! actor sentry-state phase)
     (quake:set-field! actor attack-time deadline)
     (quake:set-field! actor effects 8)
     (quake:set-field! actor frame 1))))

(define (spot-player actor player)
  (enter-attack-state actor (make-attack-state sentry-alert (+ (quake:time) 0.65)))
  (quake:centerprint player "Sentry alert. Take cover!")
  (when (> (quake:field player colormap) 1)
    (quake:dprint "qslisp: sentry spotted co-op guest\n"))
  (quake:dprint "qslisp: sentry spotted player\n"))

(define (resume-patrol actor)
  (when (not (= (quake:field actor sentry-state) sentry-patrol))
    (quake:set-field! actor sentry-state sentry-patrol)
    (quake:set-field! actor effects 0)
    (quake:set-field! actor frame 0)
    (quake:dprint "qslisp: sentry returned to patrol\n"))
  (patrol actor))

(define (pursue actor player)
  (when (not (= (quake:field actor sentry-state) sentry-chase))
    (quake:set-field! actor sentry-state sentry-chase)
    (quake:dprint "qslisp: sentry chasing\n"))
  (if (> (sentry-distance-squared actor player) 6400)
      (sentry-step actor player 11)
      (quake:set-field! actor angles_y (sentry-facing actor player)))
  (when (and (>= (quake:time) (quake:field actor attack-time))
             (sentry-visible? actor player))
    (quake:set-field! actor attack-time (+ (quake:time) 0.55))
    (quake:sound actor 1 "weapons/sgun1.wav" 0.65 1)
    (quake:dprint "qslisp: sentry attacked\n")
    (damage player actor 20)))

(define-actor qslisp_sentry sentry-think actor sentry-state 0.1
  (spawn (configure-actor actor 45))
  (context (player (visible-player actor (quake:world)))
           (visible (not (quake:world? player))))
  (states
    (sentry-patrol (if visible (spot-player actor player) (patrol actor)))
    (sentry-alert
      (if visible
          (when (>= (quake:time) (quake:field actor attack-time)) (pursue actor player))
          (resume-patrol actor)))
    (sentry-chase (if visible (pursue actor player) (resume-patrol actor)))))

(define (guard-reset actor)
  (quake:set-field! actor sentry-state sentry-patrol)
  (quake:set-field! actor effects 0)
  (quake:set-field! actor frame 0))

(define (guard-fire actor player)
  (quake:set-field! actor angles_y (sentry-facing actor player))
  (quake:set-field! actor attack-time (+ (quake:time) 0.9))
  (quake:sound actor 1 "weapons/spike2.wav" 0.65 1)
  (quake:dprint "qslisp: guard fired\n")
  (damage player actor 12))

(define-actor qslisp_guard guard-think actor sentry-state 0.15
  (spawn (configure-actor actor 30))
  (context (player (visible-player actor (quake:world)))
           (visible (not (quake:world? player))))
  (states
    (sentry-patrol
      (when visible
        (enter-attack-state actor (make-attack-state sentry-alert (+ (quake:time) 0.75)))
        (quake:dprint "qslisp: guard alerted\n")))
    (sentry-alert
      (if visible
          (when (>= (quake:time) (quake:field actor attack-time)) (guard-fire actor player))
          (guard-reset actor)))))
