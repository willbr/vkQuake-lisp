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

## Gameplay

### Remote Agent finale

Deep Space 1's Lisp was debugged live from 100 million miles. Uplink's final
objective is a deadlocked probe: two relays each wait on the other's state
field. The player sets their delays at stations, or sends the buddy, so one
fires first. Uses only state fields, think timers, and `use`.
[Uplink](examples/uplink.scm)

### DWIM buddy

Interlisp's Do What I Mean, applied to orders. Occasionally the buddy picks
the switch nearest the one aimed at, found with a traceline and one
`quake:find` pass, and announces it by centerprint. Keep it rare or it reads
as a bug.

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

## HUD

The stock client draws the HUD in `sbar.c`. A mod controls its art through
`gfx.wad` and its data through player fields: `items`, `weapon`,
`currentammo`, the four ammo pools, `armorvalue`, and `health`.

### Generated gfx.wad

`W_LoadWadFile` runs after `-game` sets the search path, so a mod
`gfx.wad` replaces the status bar art. Add a WAD2 tool that reads the
player's PAK copy at build time, replaces chosen lumps, and keeps every other
lump, since the client errors on a missing one. Never commit id's art. Draw
with the procedural texture tool in the Quake palette. Replace the status and
inventory bars, the seven weapon icons with their selected and flash
variants, the four ammo icons, the face as an operator portrait, and the key,
sigil, and armor icons. Menu and console art are loose `gfx/*.lmp` files.
[Procedural textures](tools/quakec/README.md#procedural-textures)

### Stock indicators

- Keys (`IT_KEY1`, `IT_KEY2`) become mission keycards.
- Sigils are the low four `serverflags` bits: episode progress.
- Armor icon and value could show tether or bike integrity, only if wanted.
- Powerup bits tint the view (`view.c`), and the ring also hides the weapon
  model (`r_main.c`). Use them deliberately, such as the quad tint while a
  continuation beacon is out, never as plain status icons.
