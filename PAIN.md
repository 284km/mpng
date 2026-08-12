# What this hurt

A dogfood's job is to name what the language made hard. In order of how much it
cost.

## P1 — `print_no_nl (chr 0)` writes nothing in the compiled backends

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

## P2 — a byte costs eight

`read_file_bytes` returns `Vec[int]`, and an `int` is 64 bits, so a 46KB PNG
occupies 370KB before anything is decoded, and its inflated scanlines another
2MB. Nothing failed because of it at this size. It is the same missing type as P1
seen from the other side: there is no way to say "a sequence of bytes".

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

## What went well, and is worth saying

**`mgz` as a package worked on the first try.** `mere install` fetched it at a
pinned revision, and `import "mgz/inflate.mere"` resolved — zlib is DEFLATE with
two bytes in front, so `inflate data 2` was the whole of the integration. This is
the first time a dogfood in this project has consumed another one as a dependency
rather than copying it.

**The multi-error type checking earned its keep immediately.** The first compile
of `png.mere` reported two unbound names at once (`vec_of_list`, `new_vec`) rather
than one, which is a day-old feature of the compiler being used by the next thing
written after it.
