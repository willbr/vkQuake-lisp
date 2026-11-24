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

No open ideas: everything recorded here has been built.
