# qslisp: Scheme-style source to stock Quake bytecode

This is an ahead-of-time compiler written in Python that emits version 6
`progs.dat` directly, including constant-stack tail calls between named
functions, pairs, and a fixed per-entry pair arena. It uses stock Quake's instructions and
ABI, with no new engine builtins. FTEQCC is a reference tool and is not invoked by
this compiler.

From the repository root:

```sh
# Once, to fetch the stock ABI and build the interpreter CLI:
./tools/quakec/setup.sh

python3 -m qslisp examples/square.scm -o build/square.dat
./tools/quakec/run-stock.sh build/square.dat test
./tools/quakec/run-stock.sh build/square.dat square 7
```

Both executions return `49`. Python 3.10 or newer is required; there are no Python
package dependencies. Compiling only requires Python and the fetched stock ABI
header; executing the result also needs the built interpreter CLI.

## Language in this milestone

```scheme
(define (square x)
  (* x x))

(define (test)
  (let ((x 7)
        (threshold 50))
    (if (< (square x) threshold)
        (square x)
        0)))
```

- Top-level named function definitions: `(define (name arguments...) body...)`.
  Functions can refer to later definitions and recurse, including mutual recursion.
  Calls in tail position use constant stack space, including calls between
  different functions and different arities.
- A function name or `lambda` is a procedure value. Bind it, return it, pass it as
  an argument, or use it from a computed operator position. Indirect calls
  check argument counts and support constant-stack tail calls. `procedure?`
  checks the value kind. Import the [list library](list.scm) for `map` and
  left-to-right `fold`, whose combiner receives the accumulator and item.
  Arithmetic, comparisons, `not`, `cons`, `car`, `cdr`, the equality and type
  predicates, and the vector constructor and accessors are procedure values
  too: `(fold + 0 items)`. As values, `+`, `-`, `*`, and `/` take two
  arguments. Forms that need a literal or a field name, such as
  `quake:dprint` and `quake:field`, cannot be passed.
- Anonymous functions capture lexical bindings and can outlive their caller.
  `set!` changes a lexical binding and returns the assigned value. Closures
  that capture the same mutable binding share it. `letrec` introduces mutually
  visible bindings and checks for reads before initialization. Named `let`
  evaluates initializers in the outer scope and supports tail-recursive loops.
- Decimal numbers, scientific notation, `#t`, and `#f`. All numbers use the VM's
  inexact IEEE float32 arithmetic. Literals round to float32; out-of-range finite
  literals are diagnosed. Exact integers, rationals, and bignums are not provided.
- `+` and `*` accept zero or more operands; `-` and `/` accept one or more. Unary
  forms mean negation and reciprocal. `=`, `<`, `<=`, `>`, and `>=` take exactly
  two operands in this release. `not` takes one value.
- `(if condition consequent alternative)` evaluates one branch. **Only `#f` is
  false. Numeric `0` and `-0.0` are true**, including when passed through functions.
- Ordinary `let` has lexical scope and simultaneous bindings: initializers see
  the outer environment, not sibling bindings. Duplicate names in one binding
  group are rejected; shadowing an outer binding is supported.
- `begin` and function/let bodies evaluate expressions in order and return the
  last value. Calls evaluate arguments left to right, snapshotting return values
  before subsequent calls. There are at most eight parameters per function.
- `and` and `or` short-circuit and return the selected operand. `cond` supports
  `else`, test-only clauses, and `=>` with a named receiver. `when` returns `#f`
  when skipped. `let*` introduces sequential bindings. A top-level `(define
  name value)` binds an immutable number, boolean, or string literal.
- Top-level `(import "file.scm" ...)` reads source relative to the importing
  file. Imported files share the program namespace. The compiler loads each
  file once and diagnoses cycles.
- `(define-syntax name (syntax-rules (literal ...) (pattern template) ...))`
  expands before code generation. Rules support a wildcard `_` and nested
  ellipses with one repeating pattern per list. Template-introduced lexical
  bindings are fresh, and expansion can generate top-level definitions.
- `(define-record name (field type) ...)` declares an immutable record and
  generates `make-name`, `name?`, and `name-field` accessors. Fields can be
  numbers, booleans, entities, strings, symbols, pairs, null, lists, vectors,
  procedures, named records, any record (`record`), or any value (`any`).
  Constructors check known types at compile time and validate values on entry.
- `(match value (pattern body ...) ... (else body ...))` evaluates the value
  once and takes the first matching clause. Patterns can bind identifiers,
  ignore values with `_`, test literals or quoted data, and destructure
  `cons`, `list`, or named records. Bindings are local to their clause.
- `(define-source-printer name "file.scm")` reads that file at compile time
  and defines a zero-argument function that broadcasts each line with stock
  `bprint`. Stock QuakeC has no string concatenation, so the text cannot be
  assembled at run time. Lines must fit the 255-byte print limit.
- Semicolon line comments and ASCII Scheme-style identifiers are accepted.
- `cons`, `car`, `cdr`, and `pair?` operate on immutable pairs. Pairs can contain
  any supported value. `()` and `(list)` are empty, and `(list x ...)` builds
  a proper list. `null?` checks for the empty list and `list?` checks for a
  proper list. Quotation supports symbols, lists, nested data, and dotted
  tails. Pairs and the empty list are true in conditionals.
- Quasiquote builds data from a template. Backtick introduces the template,
  `,` evaluates an expression for one value, and `,@` splices a proper list
  into the enclosing list. Templates can nest and have dotted tails. The
  long forms are `quasiquote`, `unquote`, and `unquote-splicing`.
- `(append list ... tail)` copies each proper list and shares the final
  argument, which can be an improper tail. With zero arguments it returns
  `()`. The [list library](list.scm) adds `length`, `member`, `assoc`, and
  single-list `for-each`. `member` returns the matching tail and `assoc`
  returns the matching entry. Both use `equal?` and return `#f` on a miss.
  `for-each` visits left to right and returns `#f`.
- `eq?` compares identity and scalar values. `equal?` also compares string
  contents and walks pairs, records, and boxed vectors with an explicit work stack. It uses
  three extra global words per configured pair cell when the program needs
  structural equality on pairs. `symbol?` and `string?` check value kinds.
- `(quake:dprint "text\n")` calls stock builtin #25. It prints when `developer`
  is enabled in the game engine and accepts up to 255 UTF-8 bytes.
- `(quake:precache-model "progs/player.mdl")` calls stock builtin #20 during
  map loading. It takes a model path of up to 63 bytes and requires the game
  engine. Both Quake forms take one direct string literal and return Scheme `0`.
  Literals support `\"`, `\\`, `\n`, `\r`, and `\t` escapes.
- `(define-field name)` adds a numeric field to each entity after the stock
  fields, initially zero. `(define-field name entity)` adds an entity reference,
  initially the world entity. `(define-field name string)` adds a string,
  initially empty. Read and write them through the entity forms.

Arithmetic on a known boolean is a compile error. When a parameter or function
result has an unknown type, generated checks call stock builtin #10 (`error`) on
a nonnumeric value, with a source location. Runtime diagnostics are bounded to
fit the original engine's 256-byte error-message buffer.

This is a scoped Scheme-style language, not a conforming Scheme implementation.
Non-tail recursion
uses the stock call/local stacks, about 29 calls deep; all execution remains subject to the original
instruction watchdog. Syntax keywords,
primitive function names, `__qslisp*` global names, and stock ABI global/field names
are reserved for function definitions. Stock function hooks such as `StartFrame`
can be defined with zero arguments and are wired to their ABI slots.

## Stock VM budgets

Stock Quake gives each engine entry 100,000 instructions, 31 active frames,
and 2,048 saved-local slots shared by those frames. An entry is one call from
the engine: `StartFrame`, a `think` or `touch`, a player hook. Measured on the
original interpreter with the default 512-cell pool:

| Operation | Instructions |
| --- | ---: |
| Native entry into a function that returns | 8 |
| Ordinary call and return | 11 |
| Self tail call, per iteration of a counting loop | 15 |
| Tail call to another function, per step of `even?`/`odd?` | 19 |
| `car` or `cdr` | 31 |
| `cons` | 64 |
| Create a closure with one captured value | 131 |
| Call that closure | 146 |
| `map` with a closure, per list element | about 430 |

Pair access costs grow with the logarithm of `--heap-pairs`. As a rule of
thumb, one entry can afford about a thousand pair operations or two hundred
mapped elements. Non-tail recursion reaches a depth of about 29.

The compiler follows every call, tail request, procedure value, and entity
callback to find the costliest stack of frames an entry can build. A chain
that needs more than 2,048 saved-local slots or 31 frames fails the build and
names the functions. Recursive functions are counted once, because their depth
depends on the data. `--report` prints the worst chains and their sizes:

```sh
python3 -m qslisp examples/map-game.scm -o build/map-game.dat --report
```

`worst_local_slots` and `worst_call_depth` are the totals,
`worst_local_chain` and `worst_depth_chain` name the functions, and
`recursive_functions` lists what the totals count only once. The instruction
budget is not checked statically.

## Boot a map in stock Quake

[`examples/map-boot.scm`](../examples/map-boot.scm) precaches the required player
model from `worldspawn` and logs `worldspawn` and `StartFrame` calls. To compile
it and boot the `start` map in the original DOS Quake executable, pass a
DOSBox Staging executable and the directory of a registered DOS Quake install
containing `quake.exe`, `cwsdpmi.exe`, and `id1/pak0.pak` and `id1/pak1.pak`.

```sh
python3 tools/quakec/test-map-boot.py /path/to/dosbox /path/to/quake
```

The smoke test uses an isolated data directory and checks the Quake console log
for `worldspawn`, two startup frames, `Server spawned.`, and a subsequent
frame. It saves `progs.dat` and the logs under `build/quakec/map-boot/`.

Add `--play` to open the 3D client and explore `start`.

```sh
python3 tools/quakec/test-map-boot.py --play /path/to/dosbox /path/to/quake
```

Click the game window to capture the mouse. Use **WASD** to walk, the mouse to
look around, **Space** to jump, **left click** to fire, and **R** to restart the
current map. Press **E** to interact and **1**–**7** to select a weapon. The
Lisp code spawns the local player at `info_player_start`, handles input,
and uses stock walking physics and collision. On `start`, Quake skips original
gameplay entities that lack a Lisp spawn function.

The mod ships these bindings in [`autoexec.cfg`](../examples/autoexec.cfg).
Stock Quake runs it from the `-game` directory and saves `config.cfg` there,
so the player's normal Quake bindings stay untouched. Keys **1**–**7** send
impulses 1–7 and select the matching status bar slot; slot 4 stays empty.
**E** sends impulse 10. Stock clients transmit only the attack and jump
buttons, so **Mouse2** is bound to `+tether`, whose halves send impulses 30
and 31.

| Key | Status bar bit | Weapon | Ammo |
| --- | ---: | --- | --- |
| 1 | 1 | Shotgun | shells |
| 2 | 2 | Linker: fire at a pad or hostile, then at its new target | none |
| 3 | 4 | Pulse carbine | nails |
| 5 | 16 | Continuation beacon: fire to throw, fire again to return | one beacon |
| 6 | 32 | Tail-call ricochet: one bolt that reflects and hits harder per bounce | rockets |
| 7 | 64 | Mark-and-sweep: hold to mark up to four, release to sweep | cells |

The continuation beacon is a toss entity with the player's bounding box, so
stock physics only rests it where the player fits. While it is out, the
player carries the stock quad bit, which tints the view blue. Returning
restores the throw's view angles and leaves the world as it is.

## Play and verify the Signal Room

The original [Signal Room map](../examples/signal.map) has a lit signal plate
and a practice step. You start with three shells. Hit the plate to open the
gate and walk through the exit to complete the level. Press **E** at the exit
to continue to Relay Annex, or **R** to reset the room, player, and ammo.

```sh
python3 tools/quakec/test-map-boot.py --play --map signal /path/to/dosbox /path/to/quake
python3 tools/quakec/test-map-boot.py --verify /path/to/dosbox /path/to/quake
```

The launcher builds the BSP with the pinned Quake map tools and a native C
compiler. The room geometry and texture generator live in this repository.
The demo loads the player model, weapon model, and sounds from your Quake PAKs.
You can also build the BSP directly with
`python3 tools/quakec/build-signal.py build/signal.bsp`.

The scripted client checks walking, takeoff, landing while the jump key is
held, ammo use on a miss, gate opening on a hit, and completion through the
exit. It saves and reloads both locked and open gate states and checks that
Quake restores ammo, the target, and native entity fields. It also checks that
reset restores the original state and that the completed room leads to Relay
Annex. Stock engine screenshots, state snapshots, and `measurements.json`
are under `build/quakec/map-boot/`.

The report samples stock `profile` counters during a jump, a hit, and both
actions in the same frame. Stock Quake displays the ten highest function
counts. The report bounds the omitted counts and uses the total for the frame
as an upper bound on any VM entry in that frame. It records the generated
program's global slots and largest local frame. Stock Quake allows up to
100,000 instructions per entry, 32,768 global slots, and 2,048 saved-local
slots shared across active frames.

### Relay Annex sentry

Relay Annex has a sight screen and a sentry that follows two map-authored
waypoints. Use cover to break line of sight. Once the sentry spots you, its
sensor lights up before it chases and fires. Release and press fire to respawn
after defeat. Two hits disable the sentry. **R** restarts the encounter.
Beyond the sentry are health and ammo supplies, a pulse carbine, a respawn
checkpoint, and a switch that opens the service gate when used with **E**.

```sh
python3 tools/quakec/test-map-boot.py --play --map annex /path/to/dosbox /path/to/quake
python3 tools/quakec/test-map-boot.py --verify --map annex /path/to/dosbox /path/to/quake
```

The stock-engine test checks patrol behind cover, detection, chase, loss of
sight, player defeat and respawn, sentry defeat, supplies, weapon switching
and separate ammo pools, checkpoint respawn, switch activation, and reset. The launcher
generates the original sentry model in stock MDL format. The actor uses
`quake:vector-yaw`, `quake:drop-to-floor`, and `quake:walkmove` for movement.
`(quake:change-level "annex")` queues a stock map transition.

The sentry and stationary guard use `define-actor` from the [actor and sequence
library](actors.scm). The macro turns named states into Lisp conditionals
over an entity field and schedules a stock `think` callback.
The gate uses `define-sequence` and `after` for a short flash and lift. `after`
stores the next named callback and time on the entity. Steps can span frames
using entity fields for shared state.
Annex defines typed records for damage events, patrol legs, and attack states.
Its Lisp procedures destructure these records with `match`.

`define-actor`'s optional `(restart name retry skip)` clause gives an actor
Common Lisp style restarts. Stock Quake cannot unwind, and its `error` builtin
ends the server, so `(signal-actor actor message)` parks the actor instead.
Its think stops running states and, every two seconds, offers every player
**8** retry, **9** skip, or **0** abort (impulses 26–28). The actor's `use`
callback runs the retry or skip expression and resumes its think, or removes
the actor. A sentry route longer than four waypoints now signals rather than
stopping the server; retry reads the route again and skip keeps the first
four. The Annex verifier builds a five-waypoint variant to check all three.

### Service bicycle

Follow the service lane past the guard to the bike dock. Look at the bike
and press **E** to mount. Hold **Up** to pedal and steer with **Left** and
**Right**. Hold **Down** to brake, then keep holding it to back up after
the bike stops. **F** and **Mouse1** also pedal, **Space** brakes, and the
**mouse** can steer. Up and Down resume their walking controls on foot.

Approach the marked bend at speed, then brake while steering left. Pedal
through the relay arch to bring it online and enter the depot. Turn right
for two eastbound jump ramps. Both north turns are banked all the way from
the service island to the outer wall, and taper into the straights. Slow
down and press **E** to park and step off.

The chase camera shows the bike and rider in the world. The handlebars,
fork, and front wheel can turn while the frame stays still. Once the bike
rolls, its speed and front-wheel angle determine how fast the frame changes
heading. Brake while turning to build rear-wheel slip, carry speed through
the slide, and throw dust and smoke from the rear tire. Brake in a straight
line to stop quickly. Releasing the brake restores grip gradually. The
front wheel also turns in the air. The bike eases its pitch and lean on
landing, regains tire grip over the first 0.2 seconds of ground contact,
and kicks up a short dust trail behind the rear tire.

On a bank, pedaling keeps the bike climbing at different frame rates. If
the hull stalls at a brush join, Quake's step movement can carry it across.
Pedal and steer away from the wall to regain speed along the bank.

The raised chase camera stays centered behind the bike and eases toward its
heading with a steady downward view. In single-player stock Quake, Lisp
combines the network view angle with the stock visual view offset to make
small turns smoother. The camera moves in near walls and eases back out as
the track opens up. The stock-engine test covers slide recovery, landing
dust and grip, and restarting uphill and clearing the northeast wall at
72 Hz.

With DOSBox Staging versions that support `cpu_cycles_protected`, you can
raise the emulated CPU speed for this launch. At 180,000 cycles, the tested
Annex ride ran near stock Quake's 72 Hz cap.

```sh
python3 tools/quakec/test-map-boot.py --play --map annex --protected-cycles 180000 /path/to/dosbox /path/to/quake
```

### Saved Lisp lists

Import [persistence.scm](persistence.scm) and declare a bounded list of entity
references with `(define-saved-entity-list read write length-field (slot ...))`.
The declaration creates the stock edict fields and two Lisp procedures.
`(write owner values)` validates the entire list before storing its length and
references. `(read owner)` rebuilds a fresh Lisp list in the pair heap. The
snapshot is saved with its owner by the original engine, so references should
point to entities that remain alive. Closures and arbitrary heap objects are
transient.

The Annex sentry uses a saved Lisp list to keep the order of its authored
waypoints. When the sentry reaches a waypoint it uses `append` and a
quasiquoted list to move that waypoint to the end. The stock-engine test
saves the route, lets the sentry rotate to the next waypoint, then reloads
the old order and checks that patrol continues.

### Relay Annex uplink mission

```sh
python3 tools/quakec/test-map-boot.py --play --map uplink /path/to/dosbox /path/to/quake
python3 tools/quakec/test-map-boot.py --verify --map uplink /path/to/dosbox /path/to/quake
python3 tools/quakec/test-map-boot.py --verify-coop --map uplink /path/to/dosbox /path/to/quake
python3 tools/quakec/test-map-boot.py --verify-server /path/to/dosbox /path/to/quake
```

Recruit the buddy with **E** and take a bike through the south dock. Use
**Up** to pedal, **Down** to brake or reverse, and **Left** and **Right** to
steer. Press **E** to call lifts, travel while aboard, use stations, or
dismount when stopped. The console aliases `buddy_follow`, `buddy_wait`, and
`buddy_regroup` are available in the launcher. They send impulses 21–23.

The pump can use the buddy or a second player at the valve. At switchgear,
press **3** to equip the pulse carbine, which sends a delayed follow-up to the
sentry or the linked switch. On the upper gantries, pick up the tether
launcher. It stays ready on **Mouse2** whatever weapon is selected. Aim at a
marked anchor and hold **Mouse2**. Release it to keep your momentum off the
swing. Impulses can be overwritten or dropped, so **Jump** also lets go and a
second press re-fires at a new anchor. Within 10 degrees of the aim, the
tether snaps to the best-aligned anchor with a clear line. Brush entities of
class `uplink_anchor_rail` take the tether wherever the aim hits them.

On the roof, the probe is deadlocked: each of its two relays waits for the
other's acknowledgement, after Deep Space 1's Remote Agent, whose Lisp was
debugged live from 100 million miles. Release either relay at its station,
or aim at one and press **Q** (`buddy_use`, impulse 20) to send the buddy.
Every fourth order the buddy does what Interlisp's DWIM did and picks the
station it thinks you meant, the nearest other one, and says so. The probe
answers, and extraction then completes; use the panel again to leave for the
Lambda Lab. Switchgear and the probe each hand out a stock keycard, and
extraction sets the first sigil. Two of the seven Lisp primitives, `car` and
`cdr`, wait by the carbine and past the tether swing.

A REPL into a running stock server is impossible, but the engine registers
`scratch1`–`scratch4` and `saved1`–`saved4` for QuakeC. Set them at the
console and run `tunables_reread` (impulse 25): nonzero values then replace
the ice grip, tether pull speed, buddy stride, dog bite, Winter warmth drain
and gain, sweep damage, and ricochet base damage, in that order, until the
level ends. The `saved` cvars persist in `config.cfg`.

Use `developer 1` and `gameplay_trace` (impulse 24) for up to 12 seconds of
console samples. The trace records bike steering, ground contact, speed,
grip, and camera position, plus the buddy's goal and reason code. Buddy
reason codes 0–5 represent waiting, stepping, blocked, awaiting a service
route, in range, and arriving by the service route. Tether events include
the player's slot and attachment state. The trace starts disabled.

The mission journal uses `define-saved-record` from
[persistence.scm](persistence.scm). It takes a reader name, writer name, a
reconstruction procedure, and one `(slot type accessor)` declaration per
stored field. The writer extracts those values before updating the owner
edict. The reader reconstructs the record from Quake's restored fields.
Slots support stock number, entity, and string types.

The [map generator](../tools/quakec/build-uplink.py) writes the editable
[uplink map](../examples/uplink.map). The stock tests place the client at
authored waypoints between sections and drive each objective with real
inputs. The two-player test uses the same geometry for paired bikes, a
two-person valve interlock, and simultaneous tethers. A test-only waypoint
driver also lets both clients advance the shared mission through extraction
in one session.

The dedicated server test connects a real DOS Quake client over local IPX
and starts the rider near the freight lift. A test-only Lisp driver mounts
the bike, steers to the landing, calls the lift, and boards it using the
shared bike and interaction code. It checks the rider's height against the
moving platform on each tick of the descent to the flood deck. The server
console records each stage and the rider's position and heading on failure.
Add `--watch` to see the ride in a 3D window. The window stays open at the
flood deck after the test passes.

### Lambda Lab

```sh
python3 tools/quakec/test-map-boot.py --play --map lambda /path/to/dosbox /path/to/quake
python3 tools/quakec/test-map-boot.py --verify --map lambda /path/to/dosbox /path/to/quake
```

The [Lambda Lab](../examples/lambda.scm) turns Lisp lore into rooms. The entry
hall holds the linker, continuation beacon, tail-call ricochet, and
mark-and-sweep. A sign there prints its own source, and an illusory wall hides
a Lisp Machine shrine whose console power-cycles its lights.

The cons-cell chamber is a list of pillars over a pit. Each pad sends the
player to the cell named by its cell's `cdr`, and a beam shows every pointer.
The pointers are entity fields, so stock saves keep a rewired list. Two drones
run Floyd's tortoise and hare along it. The list starts with a cycle and a
broken cell. Use the linker on a pad, then on its new target, or on a wall for
`nil`. The tail door opens when the list from the head is proper, skips the
broken cell, and ends at the door's cell. The console prints the list after
each change.

Two `amb` rooms backtrack a wrong door to the choice point and prune it. In the
lift hall, the stack lift keeps a crate per call and overflows at depth eight;
the tail-call lift reuses one crate and rises to the arena. Dogs are a Lisp
port of id's `dog.qc`, and the linker can chain one to the coil. In the arena,
`eval` and `apply` take turns calling each other, and the one inside the call
takes no damage. North of the arena, a garbage collector marks conduits from
its root one node per think, then hides each platform whose node stayed white.
Link the loose conduits to keep the way across.

Scoreboard counts live on a `lambda_stats` entity, since stock Quake rejects
world field writes after spawning. Each spawn republishes them. The verifier
drives every room with a stock client and checks the saves. Its aiming models
stock angle transmission: `MSG_WriteAngle` truncates to whole degrees before
the byte conversion, so a sent angle can be over two degrees short. The linker
snaps to a pad or conduit within three degrees of the aim.

### AI Winter

```sh
python3 tools/quakec/test-map-boot.py --play --map winter /path/to/dosbox /path/to/quake
python3 tools/quakec/test-map-boot.py --verify --map winter /path/to/dosbox /path/to/quake
```

The Lambda Lab's exit leads to [the AI Winter](../examples/winter.scm), an
abandoned lab. Stock Quake has no per-entity friction, so ice volumes give
back most of the speed ground friction takes each frame. Warmth uses the stock
armor gauge: heaters fill it, the cold drains it, and the three armor icons
show it green, yellow, or red. At zero the cold costs health. Ceiling fans and
a radar dish are non-solid brush models spinning with `avelocity`; brush models
turn about their entity origin and stock `qbsp` has no origin brushes, so they
are authored around world (0, 0) and moved into place when they spawn.

### Seven primitives

McCarthy's `eval` needs only `quote`, `atom`, `eq`, `car`, `cdr`, `cons`, and
`cond`. Each is a rune: `car` and `cdr` in Uplink, `quote`, `cons`, and `cond`
in the Lambda Lab, and `atom` and `eq` in the AI Winter. They are
`serverflags` bits 4–10, above the four the stock HUD draws as sigils, so they
survive level changes and saves. The Winter's last gate opens when all seven
are set. Its exit prints `(define eval (lambda …))` with the primitives in the
order you found them. That order is base-8 digits on the player, carried with
the rest of the loadout in the spawn parms. Finishing Uplink, the Lambda Lab,
and the Winter set the first three sigils.

Brush entities think on `ltime`. Stock Quake runs a pusher's think only when
`nextthink` is ahead of `ltime` before the move, so a save taken as they meet
stalls that timer after loading. Periodic jobs therefore run on point
entities: the cells draw the pad beams and the Winter's cold controller checks
the rune gate.

### Greenspun benchmark

[`dog.scm`](../examples/dog.scm) ports id's `dog.qc` to one Lisp state
machine. QuakeC spends a function on each animation frame; the Lisp dog keeps
each animation as a frame range and steps through it from a single think.
[`greenspun.py`](../tools/quakec/greenspun.py) compiles the game and counts
the dog's functions in each program:

```sh
python3 tools/quakec/greenspun.py
```

| | `dog.qc` | `dog.scm` |
| --- | ---: | ---: |
| Source lines | 296 | 142 |
| Functions | 94 | 30 |
| Statements | 536 | 1,393 |
| Local slots | 10 | 511 |

The Lisp source is half the size, but its bytecode is 2.6 times larger. Each
Lisp function also gets a public wrapper, and values carry type tags that
calls and field reads check. Neither count includes shared code: `dog.qc`
calls `ai.qc` and `fight.qc`, and the Lisp dog uses the sentry's sight, damage,
and facing helpers.

### Status bar art

Stock clients draw the status bar from `gfx.wad`, and `W_LoadWadFile` runs
after `-game` sets the search path, so a mod's `gfx.wad` replaces the art.
[`build-gfx.py`](../tools/quakec/build-gfx.py) reads the player's own copy from
`pak0.pak` at launch, keeps every lump the client expects, and generates the
rest: the status and inventory bars from a procedural recipe, the seven weapon
slots numbered for their keys (normal, selected, and five pickup flashes), the
ammo icons, an operator's helmet for the face, keycards, lambda sigils,
thermometer armor icons, and the continuation beacon in place of the quad. The
software renderer draws these pictures opaque, so icons sit on a panel color
rather than palette index 255. It also writes a generated console background.

The console and menu font is an original 5×7 design in
[`lisp_font.py`](../tools/quakec/lisp_font.py). It replaces the printable
cells of the stock `CONCHARS` sheet in white with a drop shadow, and their
highlighted copies in gold; the control characters keep the stock menu
borders and cursor, except the inventory's small ammo digits. The status bar's
large numbers are the same glyphs at three times size, red when low.

Every weapon's view and pickup model is generated from a recipe in
[examples/models](../examples/models), as are the continuation beacon and the
ricochet bolt. View models sit below eye level like id's, about 35 units long
and a few wide. Pickups reuse their view model's parts, centered on the floor,
with the stock MDL flag that spins items; the beacon and bolt set trail flags.

Health, shells, rockets, cells, and the lift crates are brush models too, as
in id's game. [`build-items.py`](../tools/quakec/build-items.py) builds each as
one box with generated side and top textures, centered over its entity and
resting on its floor, and bakes its lighting with the pinned `qbsp` and
`light`. The launcher builds them into `maps/b_*.bsp` for every run.
Nothing from id's PAKs is committed. The Lambda Lab verifier takes a stock
screenshot and compares the inventory slots and face with the generated art.

| Stock indicator | Use |
| --- | --- |
| Keys | Uplink's switchgear and probe keycards |
| Sigils | Uplink, Lambda Lab, and AI Winter finished |
| Armor | AI Winter warmth |
| Quad | Continuation beacon out; the client tints the view blue |

### Two-player co-op

Signal Room and Relay Annex support a stock Quake listen server with two
players. The game chooses separate starts, blocks friendly fire, and lets
either player unlock or use the exit. Both players follow the level change.
Annex actors can target either player, and checkpoints track each player.

```sh
python3 tools/quakec/test-map-boot.py --verify-coop /path/to/dosbox /path/to/quake
```

The verifier runs two original DOS Quake clients in separate DOSBox Staging
instances over local IPX. It checks both sign-ons, the guest's alternate start,
a blocked shot at the host, the guest opening and using the exit, both clients
reaching Annex, sentry detection of the guest, and guest respawn.

### Entity and gameplay forms

The example also shows how to use the stock entity ABI. `(quake:self)`,
`(quake:other)`, and `(quake:world)` return entity values. `(quake:find start field value)` searches
a string field and returns the world entity when there is no match. Test this
with `(quake:world? entity)`. `(quake:time)`, `(quake:frametime)`, and
`(quake:coop)` read the stock time, frame duration, and co-op globals.
`(quake:spawn)` allocates an entity. `(quake:set-view client viewpoint)`
assigns a networked view entity to a client through the stock protocol.
`(quake:set-view-angles! client pitch yaw roll)` sets the client's view
orientation in degrees. `(quake:cvar "name")` reads an engine variable as a
number, and `(quake:floor number)` rounds down using the stock VM builtin.
`(quake:client-command client "text")` sends a literal console command to a
client. End each command with a newline.
`(quake:field entity field)` reads numeric, string, and entity fields, including
vector components such as `origin_z`. `(quake:set-field! entity field value)`
also supports vector fields. Strings can be bound, passed through functions,
stored in pairs, and compared by content with `string=?`. `(quake:vector x y z)`
and vector field reads produce vectors that can be bound, passed, returned, and
stored in pairs. `quake:vector?` checks the kind and `quake:vector-x`,
`quake:vector-y`, and `quake:vector-z` read components. When a constructor or
field is used directly as a native vector operand, the compiler emits three
raw words with zero heap allocation. Use
`quake:set-origin`, `quake:set-size`, and `quake:set-model` for changes that
must update the engine's collision links or model index. `quake:error` reports
a literal string through the stock runtime error builtin.

`(quake:set-callback! entity field name)` installs a named zero-argument
function in a stock function field such as `think`, `touch`, or `use`. Pass
`#f` to clear it. `(quake:call-callback entity field activator)` runs an
installed callback with the entity and activator as `self` and `other` and
restores the caller's values afterward. The stock engine can also invoke these
callbacks directly. Signal Room reads brush models and `target`/`targetname`
links from the map entities.

`quake:bit-and` and `quake:bit-or` take two integers representable in stock VM
float slots. `quake:make-vectors` takes a stock angle vector and sets the
components read by `quake:forward-x`, `quake:forward-y`, and `quake:forward-z`.
`(quake:traceline start end mode ignore)` returns the hit entity or the world
entity. `(quake:trace-fraction)` reads how far the last trace traveled, with
`1` indicating a clear path. `quake:trace-normal-x`, `quake:trace-normal-y`,
and `quake:trace-normal-z` read the hit plane's normal. `(quake:trace-end-z)`
reads the endpoint's height. Use `quake:entity=?` to compare references and
`quake:remove` to remove an entity.
`(quake:precache-sound "path.wav")` runs during map loading and
`(quake:sound entity channel "path.wav" volume attenuation)` plays the sample.
`(quake:particle origin direction color count)` emits stock palette particles.
`(quake:centerprint client "message")` shows a message to that client.
`(quake:bprint "message")` prints a literal to every client's console.
`(quake:point-contents vector)` returns the stock contents number at a point:
`-1` empty, `-2` solid, `-3` water, `-4` slime, `-5` lava, `-6` sky.
`(quake:lightstyle style "pattern")` sets a light style for the server and all
clients, and stock saves record it. Patterns are 1–63 letters `a`–`z`, where
`a` is dark, `m` normal, and `z` brightest; the engine steps through them ten
times a second. Styles run from 0 to 63; a computed style outside that range
stops with a source location before the call, because the stock engine does
not check it. The map light tool gives switchable lights styles from 32.
`(quake:serverflags)` reads and `(quake:set-serverflags! number)` writes the
stock global that survives level changes and, as in id's progs, saved games.
The stock HUD draws its low four bits as episode sigils.
`(quake:sprint client "message")` prints to one client's console. `sprint`,
`bprint`, and `centerprint` also accept runtime strings, such as a target name
read from a field; only literals have their length checked at compile time.
`(quake:update-stat stat number)` sets a scoreboard stat for every client:
11 total secrets, 12 total monsters, 13 found secrets, or 14 killed monsters.
It also stores the matching stock global, which Quake resends to joining
clients and, like `serverflags`, writes to saved games.
`(quake:parm n)` and `(quake:set-parm! n number)` read and write the stock
spawn parms `parm1`–`parm16`, and `(quake:set-spawn-parms client)` reloads one
client's parms into them. The [persistence library](persistence.scm)'s
`carry!` and `carried` move a list of up to 15 numbers through them; the game
carries the player's weapons, health, ammo, tether, and rune order between
levels that way, since entity fields do not survive a level change.
`(quake:lightning entity start end)` draws a stock lightning bolt the way
`quake:beam` draws the tether beam. `(quake:point-effect name position)` sends
a stock temp entity: `spike`, `gunshot`, `explosion`, `tar-explosion`,
`lava-splash`, or `teleport`. `quake:trace-end-x` and `quake:trace-end-y`
complete the last trace's endpoint. `(quake:move-to-goal distance)` and
`(quake:change-yaw)` call the stock monster steering builtins on `self`, using
its `goalentity`, `ideal_yaw`, and `yaw_speed` fields.

## Pair arena

```scheme
(define (test)
  (let ((p (cons 7 9)))
    (+ (car p) (cdr p))))
```

```sh
python3 -m qslisp examples/pairs.scm -o build/pairs.dat --report
./tools/quakec/run-stock.sh build/pairs.dat test
./tools/quakec/run-stock.sh build/pairs.dat churn-test

# A pool smaller than one entry's allocations fails explicitly:
python3 -m qslisp examples/pairs.scm -o build/pairs-small.dat --heap-pairs 8
./tools/quakec/run-stock.sh build/pairs-small.dat churn-test
```

The first two return `16`. The last reports `pair heap exhausted (8 cells)`
with a source location, because `churn-test` allocates 65 pairs in one entry.
The original interpreter and builtin table are unchanged; allocation and
accessors are generated bytecode. Programs that do not use the heap do not
include its runtime or pool. `pair?` alone needs only a tag comparison.

**Heap values live for one engine entry.** An entry is one call from the engine
into compiled code: `StartFrame`, a `think` or `touch` callback, a player
hook, or a CLI invocation. There are no mutable globals, and entity fields hold
only numbers, entities, and strings, so nothing allocated during an entry is
reachable after it returns. The runtime therefore has no collector. Allocation
bumps one index. Each native entry wrapper saves that index on entry and
restores it on exit. An entry that runs inside another one, such as a `touch`
callback fired by `quake:walkmove` or a `quake:call-callback`, releases only
its own cells and leaves its caller's in place.

State that must outlive an entry belongs in entity fields. They are also the
only storage stock Quake writes to a saved game. The
[persistence library](persistence.scm) projects lists and records onto typed
fields and rebuilds them in the arena on demand.

`--heap-pairs` defaults to 512 and bounds what **one entry** can allocate; there
is no reclamation within an entry. A pair occupies six 32-bit global slots,
three for each field. Programs that use `equal?` on pairs reserve three more
per cell for its work stack. Larger pools must still fit the stock 32,768-slot
bank with all other compiler storage. Exhaustion reports a source-located
`pair heap exhausted` error. Accessor trees check their leaf index, rejecting
invalid, fractional, or out-of-range handles; `car`/`cdr` also check the type.

### Measured cost

Regenerate the measurements on the original interpreter:

```sh
python3 -m qslisp.measure_heap
```

The report and generated programs are written to `build/heap-benchmark/`. The
report includes exact slot counts, instruction bytes, file sizes, execution
counts, and the cells in use after the entry returns. The probe also uses stock
bytecode; no special host builtin is used for inspection.

For `examples/pairs.scm`, the acceptance test constructs one pair and reads both
fields. The churn test allocates 65 pairs:

| Pair cells | Total global slots | Runtime statements | File bytes | Acceptance instructions | Churn instructions |
| --- | ---: | ---: | ---: | ---: | ---: |
| 128 | 1,551 | 2,853 | 48,052 | 143 | 4,843 |
| 512 (default) | 5,007 | 11,301 | 162,884 | 159 | 5,371 |
| 1,024 | 9,615 | 22,565 | 316,048 | 167 | 5,635 |

All cases return `16` and leave no cells in use. Indexed access uses generated
balanced branch trees: access cost grows logarithmically with the pool, but
code size grows linearly. The stock watchdog charges every accessor
instruction, so a long allocation loop can still reach the 100,000-instruction
limit before it fills the pool.

## Tail calls

```scheme
(define (sum n acc)
  (if (= n 0)
      acc
      (sum (- n 1) (+ acc n))))

(define (test)
  (sum 1000 0))
```

Compile and run the self-recursive and mutually recursive examples:

```sh
python3 -m qslisp examples/tail-calls.scm -o build/tail-calls.dat
./tools/quakec/run-stock.sh build/tail-calls.dat test
./tools/quakec/run-stock.sh build/tail-calls.dat mutual-test
```

`test` returns `500500`; `mutual-test` returns `49` after 1,000 steps of
`even?`/`odd?`. These run on the original interpreter without changing its
stack or instruction limits.

A function body's final expression is in tail position. Both branches of a
tail-position `if`, and the final body expression in a tail-position `let` or
`begin`, are also tail positions. Conditions, argument expressions, binding
initializers, and earlier body expressions are ordinary calls when they contain
function applications. For example, `(+ n (sum (- n 1)))` must retain a
continuation and is not a tail call.

Self tail calls evaluate all new arguments first, copy them through the VM's
argument registers, update the parameters, and jump to the body's start. The
two-stage copy preserves swaps and permutations such as `(loop n b a)`.

Other tail calls copy their tagged arguments straight into the VM's parameter
registers and return a private request. The caller's call site then calls the
requested function **after the requesting body's frame has returned**, and
repeats until a normal value comes back. A pure tail-call chain uses one public
wrapper and at most one function-body frame, independent of chain length. No
heap, additional builtin, or VM opcode is needed.

An ordinary call is one stock `CALL` and one VM frame, followed by a two
instruction check for a request. Nothing runs between a callee staging its
tail arguments and the call site reading them, and arguments are staged only
after all nested calls finish, so nested calls can share the registers. Stock
Quake allows 32 active frames: non-tail recursion reaches a depth of about 29
from a native entry.

Tail calls do not bypass the watchdog. Long or infinite tail loops still fail
at the stock instruction budget; they do not gain another budget per iteration.

## Value and call representation

Inside compiled Scheme code, each value uses three VM words:

```text
[payload, type-tag, metadata]
```

The tag is float32 `0` for a number, `1` for a boolean, `2` for a pair, or `3`
for an entity, `4` for a string, `5` for the empty list, `6` for a symbol,
`7` for a vector, `8` for code without captures, or `9` for a closure.
Numbers and booleans use float32 payloads. Pairs, vectors, and closures use
opaque cell indices,
entities use the raw edict reference, and strings and interned symbols use
stock string offsets. These values
fit the VM's three-word parameter and return areas. Entity references use
engine-managed storage and can be passed through Scheme functions and pairs.

Internal function-body names start with `__qslisp_fn_` and accept these tagged values.
Public names are native entry wrappers: each CLI argument is a scalar float,
converted to a Scheme number before calling the body. Calls between
Scheme functions preserve boolean tags. The
CLI prints the return payload; boolean results consequently display as `0`/`1`
and pair results display an opaque index. Numeric CLI arguments cannot be used
to forge a pair reference.
Native entry arguments are numeric, so CLI argument `0` is Scheme's number zero,
not `#f`.

Code values hold a raw function reference, and their third word holds the
arity plus two. A closure stores that code value and the captured values in
the heap. The call site stages captures before entering the function body.
Mutable bindings use shared cells. Other normal values have a zero third word. Private tail requests use
`[raw-function-reference, 0, 1]` instead. Every call site consumes this marker
before its result reaches a Scheme caller or native entry wrapper. Request
records are control data, not Scheme values, and internal entries are not a
public CLI or native ABI. The callee copies its own declared number and widths
of parameters from the registers.

Instructions are first emitted into a small per-function IR containing local
slot references. Constants are allocated separately, and locals are relocated
into contiguous frames afterward. This preserves the stock interpreter's
save/restore behavior, including recursive calls. A frame reuses the slots of
values nothing reads again: the temporaries of a discarded body expression, a
condition once it has been branched on, and the other arm of an `if`, `cond`,
or `match`. Operands of one expression and `let` bindings keep their own slots. The emitter diagnoses frames
over 2,048 words, total storage over 32,768 words, and out-of-range branches.
It also rejects [call chains](#stock-vm-budgets) whose nested frames exceed the
saved-locals stack or the call depth. Recursion depth and instruction budgets
remain runtime limits.

Source layout:

- [`reader.py`](reader.py): S-expressions and source locations.
- [`compiler.py`](compiler.py): declarations, lexical resolution, tagged values,
  control flow, calls, and primitive operations.
- [`bytecode.py`](bytecode.py): stock ABI definitions, slot allocation,
  relocation, and binary records.
- [`heap.py`](heap.py): the pair pool, checked accessor trees, and bump
  allocation runtime generation.
- [`measure_heap.py`](measure_heap.py): repeatable size and execution measurements.
- [`__main__.py`](__main__.py): compiler CLI.

## Tests

```sh
python3 -m unittest discover -s qslisp/tests -v
python3 -m unittest discover -s tools/quakec/tests -v
```

Acceptance tests validate each generated image and execute it using the original
interpreter. They cover float32 arithmetic, Scheme truth semantics, lexical
bindings, nested and eight-argument calls, recursion, source diagnostics, and
stock compatibility. Tail-call tests exercise deep self/mutual loops, parallel
argument updates, varying arities, nested tail requests, large local frames,
non-tail continuations, and the unchanged instruction watchdog. They require
no purchased game data. Heap tests fill small pools exactly, keep values live
across allocating calls and recursive frames, check exhaustion, and observe
nested and outermost entries releasing their cells in the running VM.
