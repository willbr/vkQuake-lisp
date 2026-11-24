# Lisp and gameplay ideas

Keep stock NetQuake compatibility and use the scripted stock-engine tests to
verify new work. [Stock Quake tests](qslisp/README.md#tests)

Stock limits that shape these ideas: brushes come from the BSP and only move in
straight lines (rotating pushers and rotated BSP collision are `QUAKE2`-only in
`sv_phys.c` and `world.c`); there is no runtime code generation or string
concatenation; only entity fields and globals survive saves and level changes;
each entry gets 100,000 instructions and 31 frames; 600 entities and a
1,024-byte unreliable datagram are shared with everything else.
[VM target](tools/quakec/README.md#vm-target)

## Lisp compiler and VM

### Broader Lisp persistence

Extend save and reload when a gameplay feature needs Lisp-owned state beyond
what ordinary Quake entity fields can represent. The pair arena lasts for one
engine entry, so such state must still be projected onto typed entity fields.
[Current persistence helper](qslisp/persistence.scm) · [Pair arena](qslisp/README.md#pair-arena)

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

### Greenspun benchmark

Port id's `dog.qc` to Lisp against the PAK's `dog.mdl` and compare statement
count, globals, and peak locals with `--report` against the FTEQCC build.

### Compile-time quine sign

A host macro embeds the program's source lines as string literals and a sign
prints them with sequential `bprint` calls, each under 255 bytes. Stock has no
string concatenation, so a runtime quine would need a piecewise data printer.
Document it as compile-time. Low priority.

## Gameplay

### Physical cons cells

Lists the player walks. Each cell is a platform with a `car` pad holding an
item or switch and a `cdr` pad that teleports or launches the player to the
cell named by its `cdr` entity field. Pads give arbitrary pointers without
prebuilt bridge geometry, and stock saves keep the list because it lives in
edict fields. `quake:beam` from each pad to its target, refreshed every 0.2
seconds, shows the pointers; keep a list to 6–8 cells. Rewire by using a pad
and then a destination. `nil` is a pad over a pit.

Puzzles: reverse a list to reach a tail-only door, splice past a broken cell,
and break a circular list. Floyd's cycle detection runs as two drones, one
twice as fast; when they meet, the alarm trips. Where only two or three fixed
choices exist, a `cdr` can instead be a sliding pusher bridge between preset
docks.

### Remote Agent finale

Deep Space 1's Lisp was debugged live from 100 million miles. Uplink's final
objective is a deadlocked probe: two relays each wait on the other's state
field. The player sets their delays at stations, or sends the buddy, so one
fires first. Uses only state fields, think timers, and `use`.
[Uplink](examples/uplink.scm)

### Garbage collector monster

A sweeper marks reachable conduits from a powered root, one node per think,
with white, gray, and black skins on a generated MDL. Incremental tri-color
marking is the real technique and keeps each entry within the instruction
budget. The conduit graph uses map-authored `target`/`targetname` links.
The sweep hides unreachable platforms (non-solid, model name kept in a field)
rather than removing them, so reset and save keep working. A player outside
any trigger linked to a marked node takes damage.

### call/cc rune

Picking up the rune captures a continuation: origin, angles, health, ammo,
items, and weapon in a per-player `define-saved-record`. Invoking it restores
the player with `set-origin` and `fixangle`, but the world keeps its state.
One use is an escape continuation; a reusable rune is re-entrant. Co-op safe.
[Saved records](qslisp/persistence.scm)

### amb rooms

McCarthy's nondeterministic choice as rooms. A wrong door's trigger teleports
the player back to the choice point and closes that door through a
map-authored field, pruning the branch for the rest of the run.

### eval and apply bosses

Two generated-MDL bosses built with `define-actor`. Each sets a "calling"
field on the other and takes damage only while its own field is clear, so the
player breaks the loop between calls.

### Tail-call lift

Two lifts show call frames as crates. The non-tail lift spawns a crate per
floor, capped at about 8 for entity and network headroom, and jams when full;
its sign reads 31 to match the VM. The tail-call lift reuses one crate and
runs forever. Never recurse for real: a stock VM overflow ends the server.

### DWIM buddy

Interlisp's Do What I Mean, applied to orders. Occasionally the buddy picks
the switch nearest the one aimed at, found with a traceline and one
`quake:find` pass, and announces it by centerprint. Keep it rare or it reads
as a bug.

### Lisp Machine shrine

A secret room with procedural console and space-cadet keyboard textures. The
Tom Knight koan appears by centerprint, and the power-cycle switch sets a
baked light style to `"a"` and back with `quake:lightstyle`.
[Procedural textures](tools/quakec/README.md#procedural-textures)

### AI Winter map

A frozen, abandoned Lisp lab. Stock has no per-entity friction, so ice
volumes restore part of the player's previous horizontal velocity in
`PlayerPostThink`, like the bike's grip blending. Cold damages players
outside heat triggers. Decorative fans and dishes can spin as non-solid
`MOVETYPE_NOCLIP` brushes with `avelocity`.

### Seven primitives

Hide `quote`, `atom`, `eq`, `car`, `cdr`, `cons`, and `cond` runes across an
episode as bits in `serverflags`, which survives level changes and saves.
Use bits 4 and up: the stock HUD draws the low four as episode sigils. Show
the count by centerprint. Needs more than one map.
