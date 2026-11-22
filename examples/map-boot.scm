; Load as a dedicated-server smoke test with the original Quake data.
(define (worldspawn)
  (quake:precache-model "progs/player.mdl")
  (quake:dprint "qslisp: worldspawn\n"))

(define (StartFrame)
  (quake:dprint "qslisp: StartFrame\n"))
