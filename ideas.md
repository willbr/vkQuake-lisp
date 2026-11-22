# Lisp and gameplay ideas

Keep stock NetQuake compatibility and use the scripted stock-engine tests to
verify new work. [Stock Quake tests](qslisp/README.md#tests)

## Annex mission with an AI buddy

Build one short Relay Annex mission around an AI teammate. The buddy should
follow the player, wait when asked, regroup if separated, and help in one
fight. Reuse the sentry's actor states and map-authored waypoints. Play through
the mission before deciding which additional Lisp features it needs.
[Annex sentry](examples/sentry.scm)

## Opt-in gameplay tracing

Add a short diagnostic trace that can be enabled in stock Quake. Capture
steering input, ground contact, speed, and camera position around a bank stall
or landing. Use the same trace to capture the buddy's state, current waypoint,
and reason for stopping or changing behavior. Keep tracing off during normal
play.

## VM disassembly and source symbols

Build a read-only disassembler for stock `progs.dat`. Show function names,
symbolic branch targets, builtin calls, and local frame sizes. Use it to
inspect compiler output and investigate VM budget regressions.
[Stock VM limits](tools/quakec/README.md#vm-target)

Have the Lisp compiler optionally emit a `progs.sym` sidecar. Map VM statement
ranges to Lisp functions, files, and lines so listings and VM traces can point
back to source. Include a format version and the SHA-256 of the matching
`progs.dat` so tools can detect stale symbols. The disassembler can use the
names already embedded in `progs.dat` on its own. Stock Quake loads the standard
bytecode file as usual.

Add a small text assembler when a VM test needs a hand-written opcode fixture.
Reuse the existing bytecode writer, validator, and stock VM runner.
[Bytecode writer](qslisp/bytecode.py) · [Stock validator](tools/quakec/check-stock.py)

## Broader Lisp persistence

Extend heap-backed save and reload when a gameplay feature needs Lisp-owned
state beyond what ordinary Quake entity fields can represent.
[Current persistence helper](qslisp/persistence.scm)
