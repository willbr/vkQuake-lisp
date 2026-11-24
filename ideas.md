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

## Weapons

The stock HUD has seven weapon slots (`items` bits 1–64) and four ammo pools.
The shotgun (bit 1, shells), pulse carbine (bit 4, nails), and tether (bit 8)
leave four slots and the rocket and cell pools. Proposed layout:

| Key | Bit | Weapon | Ammo |
| --- | ---: | --- | --- |
| 1 | 1 | Shotgun | shells |
| 2 | 2 | Linker | none |
| 3 | 4 | Pulse carbine | nails |
| 4 | 8 | Free (tether moves to Mouse2) | — |
| 5 | 16 | Continuation beacon | one beacon |
| 6 | 32 | Tail-call ricochet | rockets |
| 7 | 64 | Mark-and-sweep | cells |

### Match keys to HUD slots

Key `1` now selects the shotgun shown in HUD position 2. Remap impulses to
the layout above and draw each icon's number to match its key.
[Progression](examples/progression.scm)

### Mouse2 tether

Make the tether always ready on Mouse2 instead of a weapon slot. Stock
clients send only the attack and jump button bits (`cl_input.c`), so Mouse2
sends impulses through a `+` alias, whose `-` half runs on release:

```
alias +tether "impulse 30"
alias -tether "impulse 31"
bind mouse2 +tether
```

Impulses are one per move and can be overwritten or dropped, so press
attaches, release or jump lets go (jump is a held bit and cannot be lost),
and a press while attached re-fires at a new anchor. Ship the binding in the
mod's `autoexec.cfg`; stock Quake runs it and writes `config.cfg` in the
`-game` directory, leaving the player's normal bindings alone.

Keep attachment to authored anchors: stock traces report the entity, not the
texture, and free grappling would bypass lifts, gantries, and puzzles. Add
anchorable brush entities so whole girders and rails work, snap to the
nearest anchor within an aim cone when the trace misses, and mark anchor
surfaces with a procedural texture. Mouse2 does nothing on the bike. Leave
slot 4 empty rather than invent a weapon, and skip per-weapon alt-fire: the
planned weapons each work with one button. Test a fast click, a dropped
release, jump release mid-swing, and two co-op players tethering.
[Uplink tools](examples/uplink-tools.scm)

### Linker

Fire at one entity, then another, and store the second in the first's link
field; a refreshed `quake:beam` shows the pointer. It rewires `cdr` pads in
the cons-cell puzzles and elsewhere chains a sentry to a relay, an enemy to a
hazard, or a lift to a switch.

### Tail-call ricochet

One bolt that reflects off walls using the trace normal, hitting harder on
each bounce while staying one entity: a tail call that never grows. Cut the
splitting rocket idea, which doubles entities and plays like a rocket.

### Mark-and-sweep

Hold fire to beam-mark up to four targets in entity fields; release to damage
everything marked at once. Pairs with the garbage collector monster.

### Continuation beacon

`call/cc` as a weapon, replacing the rune pickup. Throw a beacon, then fire
again to return to it with `set-origin` and `fixangle` while the world keeps
its state. The beacon is a toss entity with the player's bounding box, so it
only rests where the player hull fits; stock has no builtin to test that
otherwise. Keep the owner's return state in a per-player
`define-saved-record`. A one-shot beacon is an escape continuation; a
reusable one is re-entrant. Build it last: save/load and co-op tests carry
most of the risk. [Saved records](qslisp/persistence.scm)

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

### Scoreboard and messages

The tab scoreboard shows the worldspawn `message` as the level title and
fixed `Monsters` and `Secrets` labels; keep their meanings literal (hostiles
disabled, secrets found). Use centerprint for objectives, `bprint` for shared
events, and `sprint` for one co-op player. Do not send `viewsize` or
`crosshair` changes: they persist in the player's config after the mod.
