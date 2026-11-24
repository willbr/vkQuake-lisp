# Lisp and gameplay ideas

Keep stock NetQuake compatibility and use the scripted stock-engine tests to
verify new work. [Stock Quake tests](qslisp/README.md#tests)

## Lisp compiler and VM

### Broader Lisp persistence

Extend save and reload when a gameplay feature needs Lisp-owned state beyond
what ordinary Quake entity fields can represent. The pair arena lasts for one
engine entry, so such state must still be projected onto typed entity fields.
[Current persistence helper](qslisp/persistence.scm) · [Pair arena](qslisp/README.md#pair-arena)
