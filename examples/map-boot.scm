; Stock client input entry point for the Lisp maps.
(import "map-game.scm")

(define (PlayerPreThink)
  (player-prethink (quake:self) #f))
