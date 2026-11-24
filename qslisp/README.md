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
uses the stock call/local stacks; all execution remains subject to the original
instruction watchdog. Syntax keywords,
primitive function names, `__qslisp*` global names, and stock ABI global/field names
are reserved for function definitions. Stock function hooks such as `StartFrame`
can be defined with zero arguments and are wired to their ABI slots.

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
current map. Press **E** to interact and **1** or **2** to select a weapon. The
Lisp code spawns the local player at `info_player_start`, handles input,
and uses stock walking physics and collision. On `start`, Quake skips original
gameplay entities that lack a Lisp spawn function.

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
press **2** to equip the pulse carbine, which sends a delayed follow-up to the
sentry or the linked switch. On the upper gantries, press **3** after picking
up the launcher. Aim at a marked anchor and hold fire. Release fire to keep
your momentum off the swing.

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

Other tail calls publish up to eight tagged arguments in a fixed 24-word global
mailbox and return a private request. The bytecode trampoline then calls the new
target **after the requesting body's frame has returned**. It continues until
a normal value is returned. A pure tail-call chain uses one public wrapper,
one dispatcher, and at most one function-body frame, independent of chain length.
No heap, additional builtin, or VM opcode is needed.

Ordinary calls also enter the trampoline so their tail-calling callees resolve
to normal values before the caller continues. Each ordinary call therefore uses
a dispatcher frame plus a body frame. This adds instruction overhead and can
exhaust stock call depth sooner than a direct non-tail call. Pending arguments
are published only after all nested calls finish, and the dispatch target is a
VM local that is saved/restored on reentry, so nested ordinary calls can safely
reuse the mailbox. Unused argument cells are cleared when publishing.

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
converted to a Scheme number before calling through the trampoline. Calls between
Scheme functions preserve boolean tags. The
CLI prints the return payload; boolean results consequently display as `0`/`1`
and pair results display an opaque index. Numeric CLI arguments cannot be used
to forge a pair reference.
Native entry arguments are numeric, so CLI argument `0` is Scheme's number zero,
not `#f`.

Code values hold a raw function reference, and their third word holds the
arity plus two. A closure stores that code value and the captured values in
the heap. The trampoline stages captures before entering the function body.
Mutable bindings use shared cells. Other normal values have a zero third word. Private tail requests use
`[raw-function-reference, 0, 1]` instead. The dispatcher consumes this marker
before any return to a Scheme caller or native entry wrapper. Request records
are control data, not Scheme values, and internal entries are not a public CLI
or native ABI. The dispatcher stages all eight native argument areas and uses
stock `CALL8`; the callee copies its own declared number and widths of parameters.

Instructions are first emitted into a small per-function IR containing local
slot references. Constants are allocated separately, and locals are relocated
into contiguous frames afterward. This preserves the stock interpreter's
save/restore behavior, including recursive calls. The emitter diagnoses frames
over 2,048 words, total storage over 32,768 words, and out-of-range branches.
Nested frame totals, call depth, and instruction budgets remain runtime limits.

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
argument updates, varying arities, nested trampolines, large local frames,
non-tail continuations, and the unchanged instruction watchdog. They require
no purchased game data. Heap tests fill small pools exactly, keep values live
across allocating calls and recursive frames, check exhaustion, and observe
nested and outermost entries releasing their cells in the running VM.
