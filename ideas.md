# Lisp and gameplay ideas

Keep stock NetQuake compatibility and use the scripted stock-engine tests to
verify new work. [Stock Quake tests](qslisp/README.md#tests)

## Relay Annex: Restore the Uplink

Build one continuous mission with a bike and an AI buddy. Use a blockout
envelope from −4032 to +4032 on X, Y, and Z, for 8,064 units per axis. Stock
NetQuake can transmit positions from −4096 to +4095.875 per axis. Use both
ends of the footprint and stack the route from the sump to the roof.
Verify the envelope in stock DOS Quake before detailing the map.
[Stock coordinate encoding](third_party/quake/WinQuake/common.c#L584)

| Deck | Floor Z | Mission beat |
| --- | ---: | --- |
| West service yard | 0 | Find the buddy, open the bike dock, and take the south perimeter switchback descent. |
| Southeast freight | −1280 | Ride the full southern span through banked turns. Jump the broken loading bridge or use the lower catch lane. Take the east freight lift. |
| Flood controls | −2560 | Ride the maintenance bypass back west. Park at the valve room and open the route into the sump. |
| Southwest sump | −3840 | Have the buddy hold the valve station while you restart the pumps. Unlock a checkpoint and the cargo lift. |
| Switchgear | +1280 | Ride the eastbound aisle, then dismount for the main fight. The buddy takes cover and engages the sentry while you reach the second breaker. |
| Upper gantries | +2560 | Activate two ride-through relays along the east and north perimeter. Use full-width banks, an optional jump with a clear landing straight, and a northwest roof approach. |
| Relay roof | +3840 | Ride the final straight from the northwest approach to the northeast extraction gate. |

Plan the south descent at about 14% grade. A 1,280-unit drop needs about
9,150 units of run, so route it through switchbacks. Use bike-sized freight
lifts for the other major elevation changes. At the current 408 units per
second top speed, crossing the map takes about 20 seconds on a clear straight.
[Bike physics](examples/bike.scm)

Give the buddy **follow**, **wait**, **regroup**, and **assist** states with
authored waypoints. On long bike sections, send the buddy through a shorter
service route or lift to a marked rendezvous. In two-player co-op, provide a
bike for each player and let either player work either station. A service bay
can recover a lost bike. Checkpoint recovery should bring the buddy back into
the mission. [Annex actor logic](examples/sentry.scm)

Graybox the full route first. Use solid bends and staggered lift landings to
break sightlines. Check BSP budgets and the stock 600-edict and 256-model
limits, then test the busiest views and the complete route in stock DOS Quake
with one and two players.
[Stock engine budgets](third_party/quake/WinQuake/quakedef.h#L101)
· [BSP limits](third_party/quake/WinQuake/bspfile.h#L24)

## Lisp-driven weapons and tether traversal

- **Relay pulse.** Let an impact start a short authored Lisp sequence. A pulse
  could chain once to a linked relay or sentry, or schedule a delayed second
  hit. Give it a clear visual cue and use the same behavior in combat and
  switch puzzles. Build on damage events and `define-sequence` with `after`.
  [Annex damage events](examples/sentry.scm) · [Sequence macros](qslisp/actors.scm)
- **Tether launcher.** Start with a Hookshot-style pull to clearly marked
  anchors and a safe landing ledge. Add an Uncharted-inspired swing as a
  second use of the same tool. A fixed-length tether constrains motion while
  attached, and releasing it carries momentum into the landing. Try it as
  an optional upper-gantry shortcut with the bike route available below.
- **Stock Quake prototype.** Keep the anchor, tether length, and release
  state in Lisp entity fields. Check movement against stock collision and
  prototype the visible tether with a stock beam message and a rope model.
  Test blocked pulls, missed releases, and two clients swinging independently.
  [Stock beam handling](third_party/quake/WinQuake/cl_tent.c#L62)

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
