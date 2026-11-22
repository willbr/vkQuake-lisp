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

## Broader Lisp persistence

Extend heap-backed save and reload when a gameplay feature needs Lisp-owned
state beyond what ordinary Quake entity fields can represent.
[Current persistence helper](qslisp/persistence.scm)
