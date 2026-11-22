# Lisp and gameplay ideas

Signal Room and Relay Annex run in original DOS Quake. The roadmap below
started with a single-room walking, jumping, and shooting demo. Its Lisp and
gameplay milestones are implemented. The final Signal Room profile bounded the
busiest sampled frame at 7,678 VM instructions. Keep stock NetQuake and the
scripted engine tests as the baseline for new work.
[Signal Room and measurements](qslisp/README.md#play-and-verify-the-signal-room)

## Lisp milestones

| Area | Delivered |
| --- | --- |
| Everyday syntax | `cond`, short-circuit `and` and `or`, `when`, `let*`, named `let`, and top-level constants. Signal Room's jump handler uses the new conditional forms. |
| Data | `()`, proper lists, quoted symbols and data, and structural equality. Strings and Quake vectors bind and pass through functions as values. |
| Functions and state | Named procedure values, `lambda`, escaping closures, `map`, `fold`, and mutable lexical bindings with `set!`. |
| Quake interop | Entity-reference fields and named functions assigned to `think`, `touch`, and `use`. The plate reads its brush model from the map and activates its authored gate link. |
| Larger programs | Relative source imports, compile-time macros, and stock save and reload for Lisp-owned lists of entity references. |

[Language reference](qslisp/README.md#language-in-this-milestone) · [Entity forms](qslisp/README.md#entity-and-gameplay-forms) · [Signal Room Lisp](examples/map-boot.scm)

## Game milestones

- **Level progression.** Signal Room's target opens its gate. Walking through
  the exit and pressing E takes the player to Relay Annex, which adds a
  service switch, a second gate, pickups, and a checkpoint.
- **Enemies and AI.** The Annex sentry patrols two authored waypoints, checks
  line of sight, signals an attack, chases, and returns to patrol when cover
  breaks sight. A stationary guard defends the service gate.
- **Combat and player state.** Both sides can deal damage and be defeated.
  Players respawn, collect health and ammo, and switch between two weapons
  with separate ammo pools.
- **Persistence and multiplayer.** Save and reload restore Signal Room before
  and after the gate opens and restore the Annex sentry's ordered route.
  Two-player co-op adds separate starts, friendly fire protection, shared
  progression, and enemies that can target either player.

## Lisp ideas in use

1. **An actor DSL.** `define-actor` expands the sentry's patrol, alert, and
   chase states into named handlers and entity fields. The guard uses the
   same macro with stationary behavior.
2. **Resumable sequences.** `define-sequence` and `after` let the gate flash,
   wait, lift, and stop across scheduled `think` callbacks.
3. **Pattern matching and typed records.** `define-record` and `match` describe
   patrol legs, damage events, and attack states in the Annex source.

## Original implementation order

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

## Verification

- The compiler and stock VM suites cover the language changes and runtime
  type checks.
- Signal Room's scripted client verifies its gate, exit, reset, locked and
  open save states, and transition to Annex.
  [Signal Room test](tools/quakec/challenge.py)
- Relay Annex's scripted client covers patrol and detection, combat,
  pickups, the checkpoint, the guard, and restoration of the patrol route.
  [Relay Annex test](tools/quakec/annex.py)
- Two original DOS Quake clients verify separate starts, friendly fire
  protection, the shared transition, sentry detection, and guest respawn.
  [Co-op test](tools/quakec/coop.py)
