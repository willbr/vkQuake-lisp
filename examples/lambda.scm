; The Lambda Lab: Lisp lore puzzles built from stock entities.
(import "quine.scm" "dog.scm" "winter.scm")

(define-field cell-next string)
(define-field cell-cdr entity)
(define-field cell-pad entity)
(define-field broken)
(define-field lambda-head)
(define-field pad-time)
(define-field pad-pending entity)
(define-field door-open)
(define-field floyd-tortoise entity)
(define-field floyd-hare entity)
(define-field floyd-cycle)
(define-field rune)
(define-field style)
(define-field lambda-tail)
(define-field lift-depth)
(define-field lift-running)
(define-field lift-base)
(define-field lift-crate entity)
(define-field boss-partner entity)
(define-field boss-called)
(define-field boss-swap)
(define-field gc-color)
(define-field gc-root)
(define-field gc-platform string)
(define-field gc-phase)
(define-field gc-safe-until)
(define-field lambda-secrets)
(define-field lambda-monsters)
(define-field lambda-found)
(define-field lambda-killed)

(define (lambda-named name)
  (quake:find (quake:world) targetname name))

(define (lambda-other)
  (let ((player (quake:other)))
    (and (active-player? player) player)))

(define (lambda-brush entity)
  (quake:set-field! entity movetype move-push)
  (quake:set-field! entity solid solid-brush)
  (quake:set-model entity (quake:field entity model)))

(define (lambda-trigger entity)
  (quake:set-field! entity solid solid-trigger)
  (quake:set-model entity (quake:field entity model))
  (quake:set-field! entity modelindex 0))

(define (lambda-teleport player destination)
  (quake:point-effect teleport (quake:field player origin))
  (quake:set-origin player destination)
  (quake:set-field! player velocity (quake:vector 0 0 0))
  (quake:set-field! player flags (- (quake:field player flags) (quake:bit-and (quake:field player flags) flag-ground)))
  (quake:point-effect teleport destination))

; Stock PAK assets only. Generated models are precached by the spawn
; functions that use them, so maps built without them still load.
(define (lambda-precache)
  (quake:precache-model "progs/end1.mdl")
  (quake:precache-model "progs/g_shot.mdl")
  (quake:precache-model "progs/g_rock.mdl")
  (quake:precache-model "progs/g_rock2.mdl")
  (quake:precache-model "progs/g_light.mdl")
  (quake:precache-model "maps/b_rock0.bsp")
  (quake:precache-model "maps/b_batt0.bsp")
  (quake:precache-model "maps/b_explob.bsp")
  (quake:precache-sound "misc/secret.wav")
  (quake:precache-sound "misc/runekey.wav")
  (quake:precache-sound "misc/power.wav")
  (quake:precache-sound "items/r_item2.wav"))

;; Scoreboard totals live on the world entity so saves keep them. Quake
;; resends the stat globals to each client as it spawns.
; Stock Quake rejects world field writes once the level runs, so the
; counters live on an entity spawned with the world.
(define (spawn-stats)
  (quake:set-field! (quake:spawn) classname "lambda_stats"))

(define (stats)
  (quake:find (quake:world) classname "lambda_stats"))

(define (publish-scoreboard)
  (let ((counts (stats)))
    (quake:update-stat 11 (quake:field counts lambda-secrets))
    (quake:update-stat 12 (quake:field counts lambda-monsters))
    (quake:update-stat 13 (quake:field counts lambda-found))
    (quake:update-stat 14 (quake:field counts lambda-killed))))

(define (count-monster)
  (quake:set-field! (stats) lambda-monsters (+ 1 (quake:field (stats) lambda-monsters))))

;; Weapon and ammo pickups.
(define-syntax define-pickup
  (syntax-rules ()
    ((define-pickup classname collect model (player) action ...)
     (begin
       (define (classname)
         (set-pickup-model (quake:self) model)
         (quake:set-callback! (quake:self) touch collect))
       (define (collect)
         (let ((player (lambda-other)))
           (when player
             action ...
             (refresh-ammo player)
             (quake:remove (quake:self))
             (quake:sound player 2 "weapons/pkup.wav" 1 1))))))))

(define-pickup lambda_linker take-linker "progs/g_shot.mdl" (player)
  (give-weapon player linker-weapon)
  (quake:centerprint player "Linker. Press 2.\nFire at a pad or hostile, then at its new target.")
  (quake:dprint "lambda: linker collected\n"))
(define-pickup lambda_beacon_launcher take-beacon "progs/g_rock.mdl" (player)
  (give-weapon player beacon-weapon)
  (quake:centerprint player "Continuation beacon. Press 5.\nFire to throw, fire again to return.")
  (quake:dprint "lambda: beacon collected\n"))
(define-pickup lambda_ricochet_launcher take-ricochet "progs/g_rock2.mdl" (player)
  (give-weapon player ricochet-weapon)
  (quake:set-field! player ammo_rockets (+ (quake:field player ammo_rockets) 5))
  (quake:centerprint player "Tail-call ricochet. Press 6.\nEach bounce reuses the bolt and hits harder.")
  (quake:dprint "lambda: ricochet collected\n"))
(define-pickup lambda_sweeper_gun take-sweeper "progs/g_light.mdl" (player)
  (give-weapon player sweep-weapon)
  (quake:set-field! player ammo_cells (+ (quake:field player ammo_cells) 8))
  (quake:centerprint player "Mark-and-sweep. Press 7.\nHold fire to mark up to four, release to sweep.")
  (quake:dprint "lambda: sweeper collected\n"))
(define-pickup lambda_rockets take-rockets "maps/b_rock0.bsp" (player)
  (quake:set-field! player ammo_rockets (+ (quake:field player ammo_rockets) 5))
  (quake:centerprint player "Picked up 5 rockets."))
(define-pickup lambda_cells take-cells "maps/b_batt0.bsp" (player)
  (quake:set-field! player ammo_cells (+ (quake:field player ammo_cells) 6))
  (quake:centerprint player "Picked up 6 cells."))

;; Runes: the seven primitives are serverflags bits 4-10, above the HUD sigils.
(define (lambda_rune)
  (set-pickup-model (quake:self) "progs/end1.mdl")
  (quake:set-field! (quake:self) effects 8)
  (quake:set-callback! (quake:self) touch take-rune))

(define (rune-count flags bit total)
  (if (> bit 1024) total
      (rune-count flags (* bit 2) (if (= (quake:bit-and flags bit) bit) (+ total 1) total))))

(define (rune-index bit index)
  (if (<= bit 16) index (rune-index (/ bit 2) (+ index 1))))

(define (take-rune)
  (let ((player (lambda-other)) (rune (quake:self)))
    (when player
      (when (= (quake:bit-and (quake:serverflags) (quake:field rune rune)) 0)
        ; Remember the order for the ending; the parms carry it between levels.
        (quake:set-field! player rune-order
          (+ (* 8 (quake:field player rune-order)) (rune-index (quake:field rune rune) 1))))
      (quake:set-serverflags! (quake:bit-or (quake:serverflags) (quake:field rune rune)))
      (quake:sound player 2 "misc/runekey.wav" 1 1)
      (quake:sprint player "Primitive collected: ")
      (quake:sprint player (quake:field rune message))
      (quake:sprint player "\n")
      (quake:centerprint player (if (= (rune-count (quake:serverflags) 16 0) 7)
                                    "All seven primitives.\nEval can now be defined."
                                    "A Lisp primitive.\nCollect all seven."))
      (quake:dprint "lambda: rune collected\n")
      (quake:remove rune))))

;; The hidden Lisp Machine shrine.
(define (lambda_illusion)
  (let ((wall (quake:self)))
    (quake:set-model wall (quake:field wall model))
    (quake:set-field! wall solid 0)))

(define (lambda_secret)
  (lambda-trigger (quake:self))
  (quake:set-field! (stats) lambda-secrets (+ 1 (quake:field (stats) lambda-secrets)))
  (quake:set-callback! (quake:self) touch find-secret))

(define (find-secret)
  (let ((player (lambda-other)))
    (when player
      (quake:set-field! (stats) lambda-found (+ 1 (quake:field (stats) lambda-found)))
      (quake:update-stat 13 (quake:field (stats) lambda-found))
      (quake:sound player 2 "misc/secret.wav" 1 1)
      (quake:centerprint player "You found a secret area!")
      (quake:dprint "lambda: secret found\n")
      (quake:remove (quake:self)))))

(define (lambda_shrine)
  (lambda-brush (quake:self))
  (quake:set-callback! (quake:self) use power-cycle))

(define-sequence
  (step power-cycle
    (let* ((console (quake:self)) (light (find-linked console)) (player (quake:other)))
      (quake:centerprint player "A novice tried to fix a broken Lisp machine\nby turning the power off and on.\nKnight: \"You cannot fix a machine by just\npower-cycling it with no understanding\nof what is going wrong.\"\nKnight turned the machine off and on.\nThe machine worked.")
      (when (not (quake:world? light))
        (quake:lightstyle (quake:field light style) "a"))
      (quake:sound console 1 "misc/power.wav" 1 1)
      (quake:dprint "lambda: shrine power cycled\n")
      (after 1.2 power-restored)))
  (step power-restored
    (let ((light (find-linked (quake:self))))
      (when (not (quake:world? light))
        (quake:lightstyle (quake:field light style) "m")))))

;; Cons cells. Each pad teleports to the cell its cell's cdr names. The cdr
;; pointers are entity fields, so stock saves keep the rewired list.
; Marker entities such as respawn points keep their place for find.
(define (info_null) 0)

; Every cell names its cdr in the map. The head resolves them all once the
; level has spawned, then a save keeps the entity references.
(define (lambda_cell)
  (if (> (quake:field (quake:self) lambda-head) 0)
      (quake:set-callback! (quake:self) think resolve-cells)
      (quake:set-callback! (quake:self) think cell-think))
  (quake:set-field! (quake:self) nextthink (+ (quake:time) 0.2)))

(define (resolve-cell cursor)
  (let ((cell (quake:find cursor classname "lambda_cell")))
    (when (not (quake:world? cell))
      (quake:set-field! cell cell-cdr (lambda-named (quake:field cell cell-next)))
      (quake:set-field! cell cell-next "")
      (resolve-cell cell))))

(define (resolve-cells)
  (resolve-cell (quake:world))
  (lambda-list-check #f)
  (quake:set-callback! (quake:self) think cell-think)
  (cell-think))

(define (lambda_pad)
  (lambda-brush (quake:self))
  (quake:set-callback! (quake:self) touch use-pad))

(define (pad-cell pad) (find-linked pad))

(define (pad-top pad)
  (quake:vector (* 0.5 (+ (quake:field pad absmin_x) (quake:field pad absmax_x)))
                (* 0.5 (+ (quake:field pad absmin_y) (quake:field pad absmax_y)))
                (quake:field pad absmax_z)))

; Cells are point entities, whose thinks run on level time; they draw the
; pointer beams. A pad's brush model would think on ltime, which a save can stall.
(define (cell-pad-of cell cursor)
  (let ((pad (quake:find cursor classname "lambda_pad")))
    (cond ((quake:world? pad) pad)
          ((quake:entity=? (pad-cell pad) cell) pad)
          (else (cell-pad-of cell pad)))))

(define (cell-think)
  (let* ((cell (quake:self)) (next (quake:field cell cell-cdr)))
    (quake:set-field! cell nextthink (+ (quake:time) 0.25))
    (when (quake:world? (quake:field cell cell-pad))
      (quake:set-field! cell cell-pad (cell-pad-of cell (quake:world))))
    (when (not (quake:world? next))
      (let ((pad (quake:field cell cell-pad))
            (target (if (quake:world? (quake:field next cell-pad))
                        (cell-pad-of next (quake:world))
                        (quake:field next cell-pad))))
        (when (and (not (quake:world? pad)) (not (quake:world? target)))
          (quake:beam pad (pad-top pad) (pad-top target)))))))

(define (use-pad)
  (let* ((player (lambda-other)) (pad (quake:self)) (next (quake:field (pad-cell pad) cell-cdr)))
    (when (and player (> (quake:time) (quake:field player pad-time)))
      (quake:set-field! player pad-time (+ (quake:time) 0.6))
      (if (quake:world? next)
          (quake:centerprint player "nil: the end of the list.")
          ; A solid touch runs inside stock walk physics, which can restore the
          ; old origin afterwards. Jump on the player's next think instead.
          (quake:set-field! player pad-pending next)))))

(define (follow-pending-pad player)
  (let ((next (quake:field player pad-pending)))
    (when (not (quake:world? next))
      (quake:set-field! player pad-pending (quake:world))
      (lambda-teleport player (quake:field next origin))
      (when (> (quake:field next broken) 0) (quake:centerprint player "A broken cell! Splice it out."))
      (quake:dprint "lambda: followed cdr\n"))))

(define (lambda-relink player pad target)
  (let ((cell (pad-cell pad))
        (next (if (string=? (quake:field target classname) "lambda_pad") (pad-cell target) (quake:world))))
    (quake:set-field! cell cell-cdr next)
    (quake:dprint "lambda: cdr rewired\n")
    (print-list player)
    (lambda-list-check player)))

(define (head-cell cursor)
  (let ((cell (quake:find cursor classname "lambda_cell")))
    (if (or (quake:world? cell) (> (quake:field cell lambda-head) 0)) cell (head-cell cell))))

(define (print-cells player cell steps)
  (cond
    ((quake:world? cell) (quake:sprint player ")\n"))
    ((= steps 0) (quake:sprint player " ...)\n"))
    (else
     (quake:sprint player " ")
     (quake:sprint player (quake:field cell targetname))
     (print-cells player (quake:field cell cell-cdr) (- steps 1)))))

(define (print-list player)
  (quake:sprint player "list:")
  (print-cells player (head-cell (quake:world)) 7))

; Floyd's tortoise and hare, on the cells themselves: #t for a cycle.
(define (cdr-cell cell) (if (quake:world? cell) cell (quake:field cell cell-cdr)))

(define (floyd-cycle? tortoise hare)
  (let ((hare (cdr-cell (cdr-cell hare))) (tortoise (cdr-cell tortoise)))
    (cond ((quake:world? hare) #f)
          ((quake:entity=? tortoise hare) #t)
          (else (floyd-cycle? tortoise hare)))))

(define (list-tail-cell cell)
  (if (quake:world? (quake:field cell cell-cdr)) cell (list-tail-cell (quake:field cell cell-cdr))))

(define (list-has-broken? cell)
  (and (not (quake:world? cell))
       (or (> (quake:field cell broken) 0) (list-has-broken? (quake:field cell cell-cdr)))))

; The tail door opens when the list from the head is proper, skips the
; broken cell, and ends at the door's cell.
(define (lambda-list-check player)
  (let* ((head (head-cell (quake:world)))
         (door (lambda-named "tail-door"))
         (proper (not (floyd-cycle? head head))))
    (when (and proper (not (list-has-broken? head)) (not (quake:world? door))
               (string=? (quake:field (list-tail-cell head) target) "tail-door")
               (= (quake:field door door-open) 0))
      (open-tail-door door player))))

(define (lambda_list_door)
  (lambda-brush (quake:self)))

(define (open-tail-door door player)
  (quake:set-field! door door-open 1)
  (quake:set-field! door velocity_z -128)
  (quake:set-callback! door think stop-door)
  (quake:set-field! door nextthink (+ (quake:field door ltime) 1))
  (when player (quake:centerprint player "A proper list ending here.\nThe tail door opens."))
  (quake:sound door 1 "misc/power.wav" 1 1)
  (quake:dprint "lambda: tail door open\n"))

(define (stop-door)
  (let ((door (quake:self)))
    (quake:set-field! door velocity_z 0)
    (quake:set-field! door solid 0)
    (quake:set-field! door modelindex 0)
    (quake:set-origin door (quake:field door origin))))

; Two drones run Floyd's algorithm along the live list. When they meet, the
; list has a cycle.
(define (lambda_floyd)
  (quake:precache-model "progs/tethanch.mdl")
  (let ((floyd (quake:self)))
    (quake:set-field! floyd floyd-tortoise (floyd-drone 0))
    (quake:set-field! floyd floyd-hare (floyd-drone 8))
    (quake:set-callback! floyd think floyd-think)
    (quake:set-field! floyd nextthink (+ (quake:time) 1))))

(define (floyd-drone effects)
  (let ((drone (quake:spawn)))
    (quake:set-field! drone classname "lambda_drone")
    (quake:set-model drone "progs/tethanch.mdl")
    (quake:set-field! drone effects effects)
    drone))

(define (place-drone drone cell height)
  (quake:set-field! drone cell-cdr cell)
  (when (not (quake:world? cell))
    (quake:set-origin drone (quake:vector (quake:field cell origin_x) (quake:field cell origin_y)
                                         (+ (quake:field cell origin_z) height)))))

(define (floyd-restart floyd)
  (let ((head (find-linked floyd)))
    (place-drone (quake:field floyd floyd-tortoise) head 72)
    (place-drone (quake:field floyd floyd-hare) head 104)))

(define (floyd-think)
  (let* ((floyd (quake:self)) (tortoise (quake:field floyd floyd-tortoise))
         (hare (quake:field floyd floyd-hare))
         (t-next (cdr-cell (quake:field tortoise cell-cdr)))
         (h-next (cdr-cell (cdr-cell (quake:field hare cell-cdr)))))
    (quake:set-field! floyd nextthink (+ (quake:time) 0.6))
    (cond
      ((or (quake:world? (quake:field tortoise cell-cdr)) (quake:world? h-next))
       (when (= (quake:field floyd floyd-cycle) 1) (quake:dprint "lambda: floyd found no cycle\n"))
       (quake:set-field! floyd floyd-cycle 0)
       (floyd-restart floyd))
      ((quake:entity=? t-next h-next)
       (when (= (quake:field floyd floyd-cycle) 0) (quake:dprint "lambda: floyd found a cycle\n"))
       (quake:set-field! floyd floyd-cycle 1)
       (quake:particle (quake:field t-next origin) (quake:vector 0 0 1) 79 40)
       (floyd-restart floyd))
      (else
       (place-drone tortoise t-next 72)
       (place-drone hare h-next 104)))))

(define (lambda_pit)
  (lambda-trigger (quake:self))
  (quake:set-callback! (quake:self) touch fall-out))

(define (fall-out)
  (let ((player (lambda-other)) (spot (find-linked (quake:self))))
    (when (and player (not (quake:world? spot)))
      (lambda-teleport player (quake:field spot origin))
      (damage player (quake:world) 10)
      (quake:centerprint player "You fell out of the list.")
      (quake:dprint "lambda: fell out\n"))))

;; amb rooms: a wrong choice backtracks to the choice point and prunes that door.
(define (lambda_barrier)
  (let ((barrier (quake:self)))
    (quake:set-field! barrier movetype move-push)
    (quake:set-model barrier (quake:field barrier model))
    (quake:set-field! barrier solid 0)
    (quake:set-field! barrier modelindex 0)))

(define (lambda_amb)
  (lambda-trigger (quake:self))
  (quake:set-callback! (quake:self) touch amb-fail))

(define (amb-fail)
  (let* ((player (lambda-other)) (choice (quake:self))
         (barrier (find-linked choice)) (spot (lambda-named (quake:field choice message))))
    (when (and player (not (quake:world? spot)))
      (lambda-teleport player (quake:field spot origin))
      (quake:set-field! choice solid 0)
      (quake:set-origin choice (quake:field choice origin))
      (when (not (quake:world? barrier))
        (quake:set-field! barrier solid solid-brush)
        (quake:set-model barrier (quake:field barrier model)))
      (quake:centerprint player "(amb) failed: backtracking.\nThat branch is pruned.")
      (quake:dprint "lambda: amb backtracked\n"))))

;; Tail-call lifts. Each call rises one floor. The stack lift keeps a crate
;; per frame and overflows; the tail lift reuses one crate and returns on top.
(define (lambda_lift)
  (let ((lift (quake:self)))
    (lambda-brush lift)
    (quake:set-field! lift lift-base (quake:field lift origin_z))))

(define (lambda-lift-input player)
  (let ((lift (quake:field player groundentity)))
    (and (> (quake:bit-and (quake:field player flags) flag-ground) 0)
         (string=? (quake:field lift classname) "lambda_lift")
         (begin
           (if (= (quake:field lift lift-running) 0)
               (begin
                 (quake:set-field! lift lift-running 1)
                 (quake:set-field! lift lift-depth 0)
                 (quake:centerprint player (if (> (quake:field lift lambda-tail) 0)
                                               "(lift 12) in tail position."
                                               "(+ 1 (lift 12)): every call keeps a frame."))
                 (quake:dprint "lambda: lift called\n")
                 (lift-call-step lift))
               (quake:centerprint player "Lift is running."))
           #t))))

(define (crate-at lift index)
  (let ((crate (quake:spawn)))
    (quake:set-field! crate classname "lambda_crate")
    (quake:set-field! crate owner lift)
    (quake:set-model crate "maps/b_explob.bsp")
    (quake:set-field! crate movetype move-noclip)
    (quake:set-origin crate (quake:vector (+ (quake:field lift absmin_x) 4 (* 30 (quake:bit-and index 3)))
                                         (- (quake:field lift absmax_y) 36)
                                         (+ (quake:field lift absmax_z) (* 32 (quake:floor (/ index 4))))))
    crate))

(define (move-crates lift cursor speed)
  (let ((crate (quake:find cursor classname "lambda_crate")))
    (when (not (quake:world? crate))
      (when (quake:entity=? (quake:field crate owner) lift)
        (quake:set-field! crate velocity_z speed))
      (move-crates lift crate speed))))

(define (remove-crates lift cursor)
  (let ((crate (quake:find cursor classname "lambda_crate")))
    (when (not (quake:world? crate))
      (if (quake:entity=? (quake:field crate owner) lift)
          (begin (quake:remove crate) (remove-crates lift (quake:world)))
          (remove-crates lift crate)))))

(define (lift-call-step lift)
  (let ((depth (quake:field lift lift-depth)) (tail (> (quake:field lift lambda-tail) 0)))
    (cond
      ((and (not tail) (>= depth 8))
       (quake:bprint "Stack overflow at depth 8. A tail call would reuse its frame.\n")
       (quake:dprint "lambda: stack lift overflowed\n")
       (move-crates lift (quake:world) 0)
       (quake:set-field! lift velocity_z 0)
       (quake:set-callback! lift think lift-unwind)
       (quake:set-field! lift nextthink (+ (quake:field lift ltime) 2)))
      ((>= depth 12)
       (quake:set-field! lift velocity_z 0)
       (move-crates lift (quake:world) 0)
       (quake:set-field! lift lift-running 0)
       (quake:bprint "The tail call returned at the top.\n")
       (quake:dprint "lambda: tail lift arrived\n"))
      (else
       (when (or (not tail) (= depth 0)) (crate-at lift depth))
       (quake:set-field! lift lift-depth (+ depth 1))
       (quake:set-field! lift velocity_z 128)
       (move-crates lift (quake:world) 128)
       (quake:set-callback! lift think lift-next)
       (quake:set-field! lift nextthink (+ (quake:field lift ltime) 0.5))))))

(define (lift-next) (lift-call-step (quake:self)))

(define (lift-unwind)
  (let ((lift (quake:self)))
    (remove-crates lift (quake:world))
    (quake:set-field! lift velocity_z -256)
    (quake:set-callback! lift think lift-rest)
    (quake:set-field! lift nextthink
      (+ (quake:field lift ltime) (/ (- (quake:field lift origin_z) (quake:field lift lift-base)) 256)))))

(define (lift-rest)
  (let ((lift (quake:self)))
    (quake:set-field! lift velocity_z 0)
    (quake:set-origin lift (quake:vector 0 0 (quake:field lift lift-base)))
    (quake:set-field! lift lift-running 0)))

;; A coil zaps hostiles the linker has chained to it.
(define (lambda_coil)
  (quake:precache-model "progs/tethanch.mdl")
  (let ((coil (quake:self)))
    (quake:set-model coil "progs/tethanch.mdl")
    (quake:set-field! coil solid 2)
    (quake:set-size coil (quake:vector -12 -12 -12) (quake:vector 12 12 12))
    (quake:set-field! coil effects 4)
    (quake:set-callback! coil think coil-think)
    (quake:set-field! coil nextthink (+ (quake:time) 0.4))))

(define (coil-zap coil cursor class)
  (let ((hostile (quake:find cursor classname class)))
    (when (not (quake:world? hostile))
      (when (and (quake:entity=? (quake:field hostile link-next) coil) (> (quake:field hostile health) 0))
        (quake:lightning coil (quake:field coil origin) (quake:field hostile origin))
        (damage hostile (quake:world) 8))
      (coil-zap coil hostile class))))

(define (coil-think)
  (let ((coil (quake:self)))
    (quake:set-field! coil nextthink (+ (quake:time) 0.4))
    (coil-zap coil (quake:world) "lambda_dog")
    (coil-zap coil (quake:world) "lambda_boss")))

;; eval and apply. Each calls the other in turn; the one being called is
;; inside the call and takes no damage until the call returns.
(define-actor lambda_boss boss-think actor sentry-state 0.15
  (spawn (begin (configure-actor actor 150)
                (count-monster)
                (quake:set-field! actor boss-swap (+ (quake:time) 3))
                (quake:set-field! actor boss-called (if (string=? (quake:field actor targetname) "eval") 0 1))))
  (context (player (visible-player actor (quake:world)))
           (visible (not (quake:world? player))))
  (states
    (sentry-patrol
      (begin
        (boss-turn actor)
        (when visible
          (enter-attack-state actor (make-attack-state sentry-alert (+ (quake:time) 0.8))))))
    (sentry-alert
      (begin
        (boss-turn actor)
        (when (and visible (>= (quake:time) (quake:field actor attack-time)))
          (guard-fire actor player)
          (quake:set-field! actor attack-time (+ (quake:time) 1.1)))))))

(define (boss-turn actor)
  (when (quake:world? (quake:field actor boss-partner))
    (quake:set-field! actor boss-partner (find-linked actor)))
  (let ((partner (quake:field actor boss-partner)))
    (quake:set-field! actor effects (if (> (quake:field actor boss-called) 0) 4 8))
    (when (and (>= (quake:time) (quake:field actor boss-swap))
               (string=? (quake:field actor targetname) "eval"))
      (quake:set-field! actor boss-swap (+ (quake:time) 3))
      (if (or (quake:world? partner) (<= (quake:field partner health) 0))
          (quake:set-field! actor boss-called 0)
          (let ((calling (= (quake:field actor boss-called) 0)))
            (quake:set-field! actor boss-called (if calling 1 0))
            (quake:set-field! partner boss-called (if calling 0 1))
            (quake:lightning actor (quake:field actor origin) (quake:field partner origin))
            (quake:dprint "lambda: eval and apply swapped\n"))))))

(define (lambda_boss_door)
  (lambda-brush (quake:self)))

(define (bosses-left cursor)
  (let ((boss (quake:find cursor classname "lambda_boss")))
    (cond ((quake:world? boss) 0)
          ((> (quake:field boss health) 0) (+ 1 (bosses-left boss)))
          (else (bosses-left boss)))))

; Called by damage-entity before it removes a defeated hostile.
(define (defeat-monster target inflictor)
  (let ((class (quake:field target classname)))
    (when (or (string=? class "lambda_dog") (string=? class "lambda_boss"))
      (quake:set-field! (stats) lambda-killed (+ 1 (quake:field (stats) lambda-killed)))
      (quake:update-stat 14 (quake:field (stats) lambda-killed)))
    (cond
      ((string=? class "lambda_boss")
       (let ((partner (find-linked target)))
         (when (not (quake:world? partner)) (quake:set-field! partner boss-called 0)))
       (quake:dprint "lambda: boss defeated\n")
       (when (= (bosses-left (quake:world)) 0)
         (let ((door (quake:find (quake:world) classname "lambda_boss_door")))
           (when (player-entity? inflictor)
             (quake:centerprint inflictor "eval and apply are gone.\nThe arena door opens."))
           (when (not (quake:world? door))
             (quake:set-field! door solid 0)
             (quake:set-field! door modelindex 0)
             (quake:set-origin door (quake:field door origin))))))
      ((string=? class "lambda_dog")
       (dog-corpse target)
       (when (player-entity? inflictor) (quake:centerprint inflictor "Dog down."))
       (quake:dprint "lambda: dog defeated\n"))
      ((player-entity? inflictor) (quake:centerprint inflictor "Sentry disabled.")))))

;; The garbage collector. A sweeper marks conduits reachable from the root,
;; one node per think, then hides every platform whose node stayed white.
(define gc-white 0)
(define gc-gray 1)
(define gc-black 2)

(define (lambda_conduit)
  (quake:precache-model "progs/gcnode.mdl")
  (let ((node (quake:self)))
    (quake:set-model node "progs/gcnode.mdl")
    (quake:set-field! node solid 2)
    (quake:set-size node (quake:vector -14 -14 -14) (quake:vector 14 14 14))))

(define (lambda_gc_platform)
  (lambda-brush (quake:self)))

(define (lambda_gc_safe)
  (lambda-trigger (quake:self))
  (quake:set-callback! (quake:self) touch gc-safe-touch))

(define (gc-safe-touch)
  (let ((player (lambda-other)))
    (when player (quake:set-field! player gc-safe-until (+ (quake:time) 0.25)))))

(define (gc-paint node color)
  (quake:set-field! node gc-color color)
  (quake:set-field! node skin color))

(define (gc-reset cursor)
  (let ((node (quake:find cursor classname "lambda_conduit")))
    (when (not (quake:world? node))
      (gc-paint node (if (> (quake:field node gc-root) 0) gc-gray gc-white))
      (gc-reset node))))

(define (gc-find-gray cursor)
  (let ((node (quake:find cursor classname "lambda_conduit")))
    (if (or (quake:world? node) (= (quake:field node gc-color) gc-gray)) node (gc-find-gray node))))

(define (gc-shade node)
  (when (and (not (quake:world? node)) (= (quake:field node gc-color) gc-white))
    (gc-paint node gc-gray)))

(define (gc-sweep cursor)
  (let ((node (quake:find cursor classname "lambda_conduit")))
    (when (not (quake:world? node))
      (let ((deck (lambda-named (quake:field node gc-platform))))
        (when (not (quake:world? deck))
          (if (= (quake:field node gc-color) gc-black)
              (when (= (quake:field deck solid) 0)
                (quake:set-field! deck solid solid-brush)
                (quake:set-model deck (quake:field deck model)))
              (when (> (quake:field deck solid) 0)
                (quake:set-field! deck solid 0)
                (quake:set-field! deck modelindex 0)
                (quake:set-origin deck (quake:field deck origin))
                (quake:dprint "lambda: platform collected\n")))))
      (gc-sweep node))))

(define (gc-safe? player)
  (let ((ground (quake:field player groundentity)))
    (or (> (quake:field player gc-safe-until) (quake:time))
        (and (string=? (quake:field ground classname) "lambda_gc_platform")
             (> (quake:field ground solid) 0)))))

(define (gc-zap sweeper cursor)
  (let ((player (quake:find cursor classname "qslisp_player")))
    (when (not (quake:world? player))
      (when (and (active-player? player) (not (gc-safe? player))
                 (> (quake:field player origin_y) 600) (< (quake:field player origin_y) 1450)
                 (> (quake:field player origin_z) 500))
        (quake:lightning sweeper (quake:field sweeper origin) (quake:field player origin))
        (damage player sweeper 15))
      (gc-zap sweeper player))))

(define (lambda_sweeper)
  (quake:precache-model "progs/sentry.mdl")
  (let ((sweeper (quake:self)))
    (quake:set-model sweeper "progs/sentry.mdl")
    (quake:set-field! sweeper effects 4)
    (count-monster)
    (quake:set-callback! sweeper think sweeper-think)
    (quake:set-field! sweeper nextthink (+ (quake:time) 2))))

(define (sweeper-think)
  (let* ((sweeper (quake:self)) (phase (quake:field sweeper gc-phase)))
    (cond
      ((= phase 0)
       (gc-reset (quake:world))
       (quake:set-field! sweeper gc-phase 1)
       (quake:set-field! sweeper nextthink (+ (quake:time) 0.4))
       (quake:dprint "lambda: mark phase\n"))
      ((= phase 1)
       (let ((node (gc-find-gray (quake:world))))
         (if (quake:world? node)
             (begin
               (quake:set-field! sweeper gc-phase 2)
               (quake:set-field! sweeper nextthink (+ (quake:time) 0.6)))
             (begin
               (gc-paint node gc-black)
               (gc-shade (find-linked node))
               (gc-shade (quake:field node link-next))
               (quake:set-origin sweeper (quake:vector (- (quake:field node origin_x) 96) (quake:field node origin_y)
                                                      (quake:field node origin_z)))
               (quake:lightning sweeper (quake:field sweeper origin) (quake:field node origin))
               (quake:set-field! sweeper nextthink (+ (quake:time) 0.4))))))
      (else
       (gc-sweep (quake:world))
       (gc-zap sweeper (quake:world))
       (quake:dprint "lambda: sweep phase\n")
       (quake:set-field! sweeper gc-phase 0)
       (quake:set-field! sweeper nextthink (+ (quake:time) 4))))))

(define (lambda_exit)
  (lambda-trigger (quake:self))
  (quake:set-callback! (quake:self) touch leave-lab))

(define (leave-lab)
  (let ((player (lambda-other)))
    (when player
      (quake:set-serverflags! (quake:bit-or (quake:serverflags) 2))
      (quake:centerprint player "Leaving the Lambda Lab.")
      (quake:dprint "lambda: exit\n")
      (quake:change-level "winter"))))

(define (lambda-shot-contact player hit) #f)
