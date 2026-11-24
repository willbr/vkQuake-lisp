; A compile-time quine: the sign prints this file, including the line below.
(define-source-printer print-quine "quine.scm")

(define (lambda_quine)
  (lambda-brush (quake:self))
  (quake:set-callback! (quake:self) use read-quine))

(define (read-quine)
  (print-quine)
  (quake:centerprint (quake:other) "The sign printed its own source.\nOpen the console to read it.")
  (quake:dprint "lambda: quine printed\n"))
