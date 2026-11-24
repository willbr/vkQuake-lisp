# Lisp and gameplay ideas

Keep stock NetQuake compatibility and use the scripted stock-engine tests to
verify new work. [Stock Quake tests](qslisp/README.md#tests)

Stock limits that shape these ideas: brushes come from the BSP and only move in
straight lines (rotating pushers and rotated BSP collision are `QUAKE2`-only in
`sv_phys.c` and `world.c`); there is no runtime code generation or string
concatenation; entity fields and flagged globals survive saves, but only
`serverflags` and the spawn parms cross a level change;
each entry gets 100,000 instructions and 31 frames; 600 entities and a
1,024-byte unreliable datagram are shared with everything else.
[VM target](tools/quakec/README.md#vm-target)

## Lisp compiler and VM

### Actor restarts

A Common Lisp style condition system scoped to actors. The stock `error`
builtin ends the server and the VM cannot unwind, so a failing
`define-actor` or `define-sequence` step parks its actor instead: clear
`think`, store a condition code in a field, and offer `1 retry / 2 skip /
3 abort` by centerprint. The chosen impulse resumes the actor on its next
think. `use-value` restarts that return to the signal point within one entry
need nothing more. [Actors](qslisp/actors.scm)

### Live tunables

A REPL into a running stock server is impossible, but the registered stock
cvars `scratch1`–`scratch4` and `saved1`–`saved4` can carry eight tunable
numbers. An impulse rereads them through `quake:cvar`; the `saved` cvars
persist in the config. Useful for tuning bike, buddy, and sentry constants
without rebuilding.
