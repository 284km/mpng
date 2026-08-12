# mpng

A PNG decoder in [Mere](https://merelang.org/) — chunks, zlib, and the five
scanline filters — with the inflating done by [mgz](https://github.com/284km/mgz),
this project's gzip implementation, used as a package.

```sh
mere mpng.mere info app.png          # 736x724 8-bit rgba +tRNS gamma 45455
mere mpng.mere ppm app.png out.ppm   # the pixels, as a PPM

mere -c mpng.mere > mpng.c && clang -O2 mpng.c -o mpng   # for real images
```

PPM out because it is the format with no format: a header and the bytes. That
makes the output something another tool can check rather than something you have
to take on trust.

## What it reads, and writes

PNGs at 8 or 16 bits a sample, interlaced or not, in colour types 0 (grey),
2 (RGB), 3 (palette) and 6 (RGBA). The zlib stream is reassembled across IDAT chunks first,
which is not optional — encoders split it at arbitrary points, and a decoder that
inflates each chunk on its own works on small files and fails on large ones.

Filters operate on *bytes*, so a 16-bit sample means `left` is two bytes further
back. That distinction decodes 8-bit images perfectly and 16-bit ones into noise
if you get it wrong, which is why there are 16-bit cases in the tests.

`mpng encode` writes 8-bit PNGs, making the two decisions an encoder has to. A
**filter per scanline**, the way the spec suggests: try all five, keep the one whose
bytes have the smallest absolute sum, because DEFLATE does better on numbers near
zero. And a **colour type**: grey when every pixel is grey, which is a third of the
samples. PNG's colour types are not a description of the data but a claim about it,
and the cheapest true claim is the right one. Compression is `mgz`'s
deflate, the chunk CRCs are `mgz`'s crc32, and the zlib Adler-32 is here — a PNG
carries two different checksums and they are not interchangeable.

**Interlaced (Adam7) files decode.** An interlaced PNG is not one image but seven,
each a subsampling on a different lattice, stored one after another and each
filtered as if it were an image of its own — so the passes have different widths,
which means different strides, which means the filters read different neighbours.
The scatter back into one image is the only part that knows the file is
interlaced; everything before it is the ordinary decoder, run seven times.

The tests cover 9×9, 4×4 and 1×1, because the edge cases are all about **empty
passes**: an image narrower than five pixels has passes with no columns, one a
single pixel tall has passes with no rows, and an empty pass contributes no bytes
at all — not even a filter byte — which shifts every later pass if a decoder
assumes otherwise.

16-bit output is reduced to the high byte of each sample. Since PNG samples are
big-endian, that byte *is* the 8-bit value; doing better would mean choosing a
colour space.

`info` also reports what the ancillary chunks say — the ones a decoder may ignore
and a reader may want: `gAMA`, whether there is a `tRNS`, and every `tEXt` as
`keyword: text`. The zero byte inside a `tEXt` is a separator and not a terminator,
which is a small reminder of why this language needed a `bytes` type.

## Checking it

```sh
MERE=/path/to/mere sh verify.sh              # nine images
MERE=/path/to/mere CC_CHECK=1 sh verify.sh   # and again, compiled
```

`test/make_pngs.py` *computes* the images, so the expected answer is computed from
the same numbers the PNG was built from rather than from a previous run of this
decoder. One case per filter, so a broken filter names itself; filters mixed down
an image, because a row is reconstructed against the row above it, itself already
reconstructed; and a zlib stream split across two IDATs, which a decoder that
inflates each chunk separately passes everything else and fails.

`CC_CHECK=1` runs the interpreter *and* the compiled binary and compares. That is
not thoroughness for its own sake: it has now found three things — one where the
two backends produced different files, and two where the C backend emitted
programs a C compiler rejects. [PAIN.md](PAIN.md) has all three, each reduced to
something small.

## Why this exists

To find out what Mere makes hard. See [PAIN.md](PAIN.md): a two-line program the
backends disagree about, and what it says about the language's string type.
