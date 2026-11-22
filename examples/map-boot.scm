; Explore stock Quake and play the original Signal Room challenge.
(define-field next-shot)

(define (worldspawn)
  (quake:precache-model "progs/player.mdl")
  (quake:precache-model "progs/v_shot.mdl")
  (quake:precache-sound "weapons/sgun1.wav")
  (quake:precache-sound "misc/medkey.wav")
  (quake:dprint "qslisp: worldspawn\n"))

(define (StartFrame)
  ; Record the startup frames without flooding the console during play.
  (if (< (quake:time) 1.4)
      (quake:dprint "qslisp: StartFrame\n")
      0))

(define (SetNewParms) 0)
(define (SetChangeParms) 0)
(define (ClientDisconnect) 0)
(define (ClientKill) 0)
(define (info_player_start) 0)
(define (light) 0)

(define (qslisp_target)
  (let ((plate (quake:self)))
    ; The room has one brush entity and qbsp assigns it inline model *1.
    (quake:set-field! plate movetype 7) ; MOVETYPE_PUSH
    (quake:set-field! plate solid 4)    ; SOLID_BSP
    (quake:set-model plate "*1")))

(define (ClientConnect)
  (quake:dprint "qslisp: ClientConnect\n"))

(define (update-ammo player rounds)
  (quake:set-field! player ammo_shells rounds)
  (quake:set-field! player currentammo rounds))

(define (update-jump player)
  (let ((flags (quake:field player flags))
        (ground 512)
        (ready 4096))
    (if (= (quake:field player button2) 0)
        (if (= (quake:bit-and flags ready) 0)
            (quake:set-field! player flags (quake:bit-or flags ready))
            0)
        (if (= (quake:bit-and flags ready) 0)
            0
            (let ((remaining (- flags ready)))
              (if (= (quake:bit-and flags ground) 0)
                  (quake:set-field! player flags remaining)
                  (begin
                    (quake:set-field! player flags (- remaining ground))
                    (quake:set-field! player velocity_z 270)
                    (quake:dprint "qslisp: jump\n"))))))))

(define (finish-challenge player plate)
  (quake:remove plate)
  (quake:sound player 2 "misc/medkey.wav" 1 1)
  (quake:centerprint player "Signal restored!\n\nPress R to reset.")
  (quake:dprint "qslisp: target hit\n"))

(define (fire player rounds)
  (update-ammo player (- rounds 1))
  (quake:set-field! player weaponframe 1)
  (quake:set-field! player punchangle_x -2)
  (quake:sound player 1 "weapons/sgun1.wav" 1 1)
  (quake:dprint "qslisp: fired\n")
  (quake:make-vectors (quake:field player v_angle))
  (let ((x (quake:field player origin_x))
        (y (quake:field player origin_y))
        (z (+ (quake:field player origin_z) (quake:field player view_ofs_z)))
        (range 800))
    (let ((hit (quake:traceline (quake:vector x y z)
                                (quake:vector (+ x (* range (quake:forward-x)))
                                              (+ y (* range (quake:forward-y)))
                                              (+ z (* range (quake:forward-z))))
                                0 player)))
      (if (quake:world? hit)
          0
          (if (quake:entity=? hit (quake:find (quake:world) classname "qslisp_target"))
              (finish-challenge player hit)
              0)))))

(define (update-weapon player)
  (let ((now (quake:time))
        (next (quake:field player next-shot)))
    (if (> next now)
        0
        (if (= (quake:field player button0) 0)
            (if (= (quake:field player weaponframe) 0)
                0
                (quake:set-field! player weaponframe 0))
            (let ((rounds (quake:field player ammo_shells)))
              (quake:set-field! player next-shot (+ now 0.35))
              (if (> rounds 0)
                  (fire player rounds)
                  (quake:centerprint player "Out of shells.\nPress R to reset.")))))))

(define (PlayerPreThink)
  (let ((player (quake:self)))
    (if (> (quake:field player health) 0)
        (begin
          (update-jump player)
          (update-weapon player))
        0)))

(define (PlayerPostThink) 0)

(define (PutClientInServer)
  (let ((player (quake:self))
        (spot (quake:find (quake:world) classname "info_player_start"))
        (walk 3)
        (slidebox 3)
        (client 8))
    (if (quake:world? spot)
        (quake:error "qslisp: map has no info_player_start\n")
        (begin
          (quake:set-field! player health 100)
          (quake:set-field! player movetype walk)
          (quake:set-field! player solid slidebox)
          (quake:set-field! player flags client)
          (quake:set-field! player fixangle 1)
          (quake:set-field! player items 257) ; IT_SHOTGUN | IT_SHELLS
          (quake:set-field! player weapon 1)
          (quake:set-field! player weaponmodel "progs/v_shot.mdl")
          (update-ammo player 3)
          (quake:set-field! player angles (quake:field spot angles))
          (quake:set-field! player view_ofs (quake:vector 0 0 22))
          (quake:set-model player "progs/player.mdl")
          (quake:set-size player (quake:vector -16 -16 -24) (quake:vector 16 16 32))
          (quake:set-origin player (quake:vector (quake:field spot origin_x)
                                                (quake:field spot origin_y)
                                                (+ (quake:field spot origin_z) 1)))
          (quake:dprint "qslisp: player spawned\n")))))
