# What this hurt

A dogfood's job is to name what the language made hard. In order of how much it
cost.

## P1 — `print_no_nl (chr 0)` writes nothing in the compiled backends — **fixed upstream**

Two lines are enough:

```mere
let _ = print_no_nl (chr 65);
let _ = print_no_nl (chr 0);
let _ = print_no_nl (chr 66);
exit 0
```

The interpreter writes `41 00 42`. Compiled with `-c`, the same program writes
`41 42`.

This is not a bug in `print_no_nl` so much as a consequence of what `str` is: in
the compiled backends it is a NUL-terminated C string, so `"\0"` and `""` are the
same value and no implementation of printing can tell them apart. The interpreter
holds an OCaml string, which carries its length, so it can.

It cost an hour and it cost it twice. The first version of `mpng` wrote its PPM
with `print_no_nl`, and the output was seven bytes short of the expected 47 — the
test image happened to contain exactly seven zero bytes. Under the C backend, that
is. The interpreter's output was correct, which is the part that makes this worth
writing down: **the two backends disagreed about the program's output**, and a
check that ran only one of them would have called it correct.

The workaround is to not put bytes in a `str` at all: build a `vec` of ints and
hand it to `write_file_bytes`. That is what `mpng` does now, and it is why
`verify.sh` runs both the interpreter and the compiled binary and compares.

This is the case Mere's own open question Q-015 is about — whether to add a
first-class `bytes` type or make `str` length-carrying. This program is a vote
that it is not academic: the workaround exists, works, and means a program that
handles binary cannot use the language's string type for any part of it.

**Resolved in mere v0.1.216.** The `bytes` type turned out to already exist, with
a complete in-memory API; what it had no way to do was *leave the program*. So the
answer was three builtins at the boundary rather than a new type:

    read_bytes  : str -> bytes            interp + C
    write_bytes : str -> bytes -> unit    interp + C
    print_bytes : bytes -> unit           interp + C + LLVM

A `bytes` carries its length in every backend, which is what makes them correct
where `print_no_nl` could not be. `mpng` reads and writes through them now, and
`verify.sh` still compares the interpreter against the compiled binary — the check
that found this in the first place stays.

## P2 — a byte costs eight, in the middle

Half fixed by the same change. The file now arrives as a `bytes` (one byte per
byte) and leaves as one, but the decoder converts to `Vec[int]` on the way in
because it needs random access *and mutation*: reconstructing a scanline writes
into the middle of a buffer, and `bytes` is immutable.

So the boundary is cheap now and the middle still costs eight bytes a byte. What
is missing is a mutable byte buffer — `StrBuf` is the shape, but it is a string
builder, with the NUL problem that implies. That is a design question rather than
an oversight, and it is the one this program would ask next.

## P3 — the interpreter cannot run this on a real image

A 736×724 RGBA PNG decodes in about two seconds compiled and does not finish in
two minutes interpreted. That is a fair cost for a tree-walking interpreter and
not a complaint — but it means `mere mpng.mere` is for the test images and the
compiled binary is for real work, and a reader should be told which is which.

An aside from measuring it: the first version spent 1.95s of *system* time on a
2.3s run, because `print_no_nl` per byte is a `write` syscall per byte — 1.6
million of them. Writing the vec in one call took that to nothing.

## P4 — `new_vec` is not a builtin, again

Every program that needs a fixed-size mutable buffer writes its own:

```mere
let new_vec = fn (n: int) -> fn (x: int) -> ...
```

`vec_new` grows by pushing, and a scanline reconstruction has to write into the
middle of a buffer. This is the fourth dogfood in this project to open with those
four lines (`memu`, `mkv`, `mgz`, this one).

## P5 — the C backend emits a closure type name it never defines

Twelve lines:

```mere
let f = fn data ->
  let rec go = fn (i: int) -> fn (a: int) -> fn (b: int) -> fn (c: int) -> fn acc ->
    if i >= 3 then acc
    else
      let _ = vec_push acc (vec_get data i + a + b + c) in
      go (i + 1) a b c acc in
  go 0 1 2 3 (vec_new ());
let v = vec_new ();
let _ = vec_push v 5;
let _ = vec_push v 6;
let _ = vec_push v 7;
let _ = print_int (vec_get (f v) 0);
```

Runs on the interpreter. `mere -c` emits C that clang refuses:

```
error: unknown type name
  'closure_int_closure_int_closure_int_closure_Vec_int_int_Vec_int_int';
did you mean 'closure_int_closure_int_closure_int_closure_Vec___heap_int_unit'?
```

Both names come from the same mangler, so the *types* differ: the one in the
forward declaration contains `Vec_int` — a `Vec` with one type argument — while
`Vec` is internally two, a region marker and an element (`Vec___heap_int`). So
something on the inner-function lifting path is building a `Vec` type that has
lost its region, and only the declaration sees it.

An inner `let rec` with five curried parameters ending in a vec is what triggers
it; the same shape at top level is fine, and so is the same arity without a vec.

The workaround is to capture the accumulator instead of threading it through the
recursion, which is better code anyway — it is a mutable buffer, not a value being
passed along. `read_ppm` in `mpng.mere` says so where it does it.

## P6 — a lifted inner function loses a capture when the name is used elsewhere

Found immediately after P5, in the same file. `filter_row` takes a parameter
called `row`; so do `row_cost` and `best_filter`, and `encode_rgb8` has a local
called `row`. With four of them, the C backend lifted `filter_row`'s inner `go`
with a capture list of *five* variables and left out `row` — then emitted a body
that reads `mu_row`:

```
error: use of undeclared identifier 'mu_row'
```

Renaming the parameter to `line` fixes it, which is what identifies the cause:
capture resolution is keyed by name, and four `row`s in one file are enough to
confuse it. This is the same family as the 2048 dogfood's P3 (nested fns with the
same name colliding in name-keyed lift resolution), which was fixed by α-renaming
inner fns — evidently *parameters* of sibling functions were not covered.

Both of these were found by `CC_CHECK=1`, which compiles the program and runs the
result. Neither is visible on the interpreter, and neither is visible from reading
the emitted C without a compiler.
\n## What went well, and is worth saying

**`mgz` as a package worked on the first try.** `mere install` fetched it at a
pinned revision, and `import "mgz/inflate.mere"` resolved — zlib is DEFLATE with
two bytes in front, so `inflate data 2` was the whole of the integration. This is
the first time a dogfood in this project has consumed another one as a dependency
rather than copying it.

**The multi-error type checking earned its keep immediately.** The first compile
of `png.mere` reported two unbound names at once (`vec_of_list`, `new_vec`) rather
than one, which is a day-old feature of the compiler being used by the next thing
written after it.
