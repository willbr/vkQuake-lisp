# qslisp: Scheme-style source to stock Quake bytecode

This is an ahead-of-time compiler written in Python that emits version 6
`progs.dat` directly, including constant-stack tail calls between named
functions, pairs, and a bounded garbage-collected heap. It uses stock Quake's instructions and
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
Annex. Stock engine screenshots, state snapshots,
and `measurements.json` are under `build/quakec/map-boot/`. Heap-backed save and
reload remain future work.

The report samples stock `profile` counters during a jump, a hit, and both
actions in the same frame. Stock Quake displays the ten highest function
counts. The report bounds the omitted counts and uses the total for the frame
as an upper bound on any VM entry in that frame. The current combined sample
is bounded by 4,121 instructions against the 100,000-instruction watchdog. The
program uses 3,083 of 32,768 global slots and its largest individual frame uses
98 slots. The engine shares 2,048 saved-local slots across active frames.

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

### Entity and gameplay forms

The example also shows how to use the stock entity ABI. `(quake:self)`,
`(quake:other)`, and `(quake:world)` return entity values. `(quake:find start field value)` searches
a string field and returns the world entity when there is no match. Test this
with `(quake:world? entity)`. `(quake:time)` returns the engine's time global.
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
entity. Use `quake:entity=?` to compare references and `quake:remove` to remove
an entity. `(quake:precache-sound "path.wav")` runs during map loading and
`(quake:sound entity channel "path.wav" volume attenuation)` plays the sample.
`(quake:centerprint client "message")` shows a message to that client.

## Pair heap and collection

```scheme
(define (test)
  (let ((p (cons 7 9)))
    (+ (car p) (cdr p))))
```

```sh
python3 -m qslisp examples/pairs.scm -o build/pairs.dat --report
./tools/quakec/run-stock.sh build/pairs.dat test

# Force collection with a small pool while keeping a pair alive:
python3 -m qslisp examples/pairs.scm -o build/pairs-small.dat \
  --heap-pairs 8 --root-slots 32 --report
./tools/quakec/run-stock.sh build/pairs-small.dat gc-test
```

Both return `16`. The second program allocates 65 pairs in an eight-cell pool,
performing nine collections. The original interpreter and builtin table are
unchanged; allocation, accessors, roots, and collection are generated bytecode.
Programs that do not use `cons`/`car`/`cdr` do not include the heap runtime or its
pools. `pair?` alone needs only a tag comparison.

`--heap-pairs` and `--root-slots` default to 256 each. A pair occupies nine
32-bit global slots: three for its car, three for its cdr, and three for
`[allocation/mark state, free-list/work-list link, zero]`. Each shadow-root entry
occupies three slots. The default pools therefore occupy 12 KiB before ABI
storage, constants, and function locals. Larger configurations must still fit
the stock 32,768-slot bank, including all other compiler storage.

The allocator uses a free list. When empty, it runs a nonmoving, stop-the-world
mark/sweep collection and retries. If every cell is reachable, it reports a
source-located `pair heap exhausted` error. A full shadow-root stack fails
explicitly too. There is no silent overwrite, growing C allocation, or manual
free operation. Accessor trees check their leaf index, rejecting invalid,
fractional, or out-of-range handles; `car`/`cdr` also check type and allocation.

Before an allocating operation or ordinary Scheme call, the compiler saves
potentially live values on a shadow-root stack. The runtime skips numbers and
booleans, saving only pair references. Roots include lexical bindings, enclosing
expression environments (including shadowed bindings needed afterward), earlier
arguments, and parallel `let` initializers. Native VM saved-locals frames cannot
be scanned from bytecode; these snapshots preserve recursive callers' values.
The result is copied before restoring the saved root-stack pointer.

Tail calls release their current bindings rather than accumulating shadow
frames. There is no allocation between publishing a tail request and the target
copying its parameters; shared argument mailboxes therefore need no additional
roots. Collection runs only inside `cons`, with the caller's live values pinned.
Discarded temporaries are not scanned. Lexical bindings may conservatively stay
live until their scope ends; there is no last-use analysis yet.

Marking follows both fields of reachable pairs. It uses a linked work list in
pair metadata, keeping graph traversal iterative rather than recursing on the
small stock stack. Sweeping resets marks, clears dead fields, and rebuilds the
free list. Pair handles remain stable. Only pair references are traced in this
milestone; future heap types and global value definitions must extend the root
and tracing rules. Stock save/load for the pair heap is still future work.

### Measured cost

Regenerate the measurements on the original interpreter:

```sh
python3 -m qslisp.measure_heap
```

The report and generated programs are written to `build/heap-benchmark/`. The
report includes exact slot counts, instruction bytes, file sizes, execution
counts, observed collection counts, and root depth after return. Counter probes
also use stock bytecode; no special host builtin is used for inspection.

For `examples/pairs.scm`, the acceptance test constructs one pair and reads both
fields. The churn test allocates 65 pairs while preserving the first:

| Pair cells / roots | Total global slots | Runtime statements | File bytes | Acceptance instructions | Churn instructions | Collections |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 8 / 32 | 781 | 784 | 20,912 | 167 | 13,466 | 9 |
| 64 / 32 | 1,378 | 2,632 | 43,812 | 215 | 15,332 | 1 |
| 256 / 32 | 3,679 | 8,968 | 126,220 | 247 | 10,643 | 0 |
| 256 / 256 (default) | 4,354 | 11,432 | 154,416 | 247 | 11,027 | 0 |

All cases return `16` and leave root depth zero. Indexed access uses generated
balanced branch trees: access cost grows logarithmically, but code size grows
linearly with configured capacities. Collection scans the active roots, live
graph, and entire pair pool. Fewer collections do not necessarily mean fewer
instructions; a larger sweep is more expensive. The stock watchdog charges the
collector and all accessor instructions. A larger heap or a long allocation loop
can hit the watchdog before producing a result even when storage is available.
These measurements are examples, not a worst-case execution guarantee.

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
Mutable bindings use shared cells, and the collector traces captures and
boxes, including recursive closure cycles. Other normal values have a zero third word. Private tail requests use
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
- [`heap.py`](heap.py): pair pools, checked accessor trees, shadow roots, and
  iterative mark/sweep runtime generation.
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
no purchased game data. Heap tests force collections with one- and two-cell
pools, preserve pending arguments and recursive frames, trace deep/shared
graphs, check exhaustion, and observe balanced roots in the running VM.
