# Lisp and gameplay ideas

Signal Room is the current milestone. Lisp drives player spawning, walking,
jumping, shooting, ammo, target removal, and reset in original DOS Quake. The
review reran all 71 tests and the scripted room verification. The busiest
sampled frame had a conservative bound of 746 VM instructions. Keep stock
NetQuake compatibility and the scripted engine test as the baseline for new
work. [Signal Room and measurements](qslisp/README.md#play-and-verify-the-signal-room)

## Lisp features we are missing

| Area | Ideas |
| --- | --- |
| Everyday syntax | Add `cond`, short-circuit `and` and `or`, `when`, `let*`, named `let`, and top-level constants. Use the jump handler's nested conditionals as an early example. |
| Data | Build on immutable pairs and garbage collection with `()`, proper lists, quoted symbols and data, and general equality. Make strings and Quake vectors bindable values that can be passed to functions. Strings currently work in specific engine forms, and vectors work in native operand positions. |
| Functions and state | Add named procedure values, `lambda`, closures, higher-order helpers such as `map` and `fold`, and binding mutation with `set!`. |
| Quake interop | Extend numeric entity fields with entity-reference fields and let Lisp assign named functions to `think`, `touch`, and `use`. Replace the plate's hardcoded brush model `*1` and the shot handler's first-matching-target lookup with links authored in the map. |
| Larger programs | Grow from one source file to modules or imports. Add compile-time macros and verify persistence for Lisp-owned state. |

[Language reference](qslisp/README.md#language-in-this-milestone) · [Entity forms](qslisp/README.md#entity-and-gameplay-forms) · [Signal Room Lisp](examples/map-boot.scm)

## Game features we are missing

- **Level progression.** Add doors, switches, triggers, pickups, checkpoints, and
  an exit. The current target ends the round with a message and a map reset.
- **Enemies and AI.** Start with one sentry and two mapper-placed patrol points.
  Let it spot the player with a line-of-sight trace, telegraph an attack, and
  chase or return to patrol. Test that walls block detection and that the sentry
  responds to losing sight of the player. Expose the stock movement builtins
  and scheduled `think` callbacks needed for this behavior.
- **Combat and player state.** Add damage, player and enemy death, respawn, and
  health and ammo pickups. Add weapon switching after the single-weapon loop
  supports a full encounter.
- **Persistence and multiplayer.** Test a save–reload round trip. The scripted
  room currently writes saves to observe state. Add Lisp game rules and tests
  for co-op or deathmatch when we take on multiplayer.

## Lisp features worth exploring

1. **An actor DSL.** A `define-actor` macro could describe states such as
   `patrol`, `alert`, and `chase` and expand them into named handlers and entity
   fields. A second enemy would be a chance to reuse the same vocabulary with
   different Lisp behavior.
2. **Resumable sequences.** Write “flash the light, wait half a second, open the
   gate” as one script. Compile each pause into a scheduled `think` so the
   sequence can resume on a later frame.
3. **Pattern matching and typed records.** Give patrol routes, damage events,
   and actor states names and shapes that the compiler can check. Use those
   shapes to make behavior code easier to read where it currently uses numeric
   flags.

## Proposed order

1. Add named entity callbacks and entity-reference fields. Add `cond`, `when`,
   and short-circuit logic as gameplay code needs them.
2. Give Signal Room a gate and an exit. The stock-engine test should show that
   the gate starts locked, a miss leaves it locked, a hit opens it, walking
   through the exit completes the level, and reset locks the gate again.
3. Build the sentry encounter with damage and respawn. Verify patrol, detection,
   loss of sight, and the encounter reset in stock Quake.
4. Save and reload before and after unlocking the gate. Verify ammo and gate
   state through ordinary entity fields before adding heap-backed persistence.
5. Use the sentry code to design the actor macro. Add escaping closures and
   heap-backed persistence when a gameplay feature needs them.

[Stock VM limits](tools/quakec/README.md#vm-target) · [Existing engine verification](tools/quakec/challenge.py)
