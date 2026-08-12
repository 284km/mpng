# mpng

A PNG decoder in [Mere](https://merelang.org/) — chunks, zlib, and the five
scanline filters — with the inflating done by [mgz](https://github.com/284km/mgz),
this project's gzip implementation, used as a package.

```sh
mere mpng.mere info app.png          # 736x724 8-bit rgba
mere mpng.mere ppm app.png out.ppm   # the pixels, as a PPM

mere -c mpng.mere > mpng.c && clang -O2 mpng.c -o mpng   # for real images
```

PPM out because it is the format with no format: a header and the bytes. That
makes the output something another tool can check rather than something you have
to take on trust.

## What it reads

8-bit non-interlaced PNGs: colour types 0 (grey), 2 (RGB), 6 (RGBA). The zlib
stream is reassembled across IDAT chunks first, which is not optional — encoders
split it at arbitrary points, and a decoder that inflates each chunk on its own
works on small files and fails on large ones.

Not yet: palette (colour type 3), 16-bit samples, interlacing, and every ancillary
chunk. Encoding is not here either; `mgz` can deflate, so it is a matter of
choosing filters.

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
not thoroughness for its own sake — they disagreed once, and [PAIN.md](PAIN.md)
explains why.

## Why this exists

To find out what Mere makes hard. See [PAIN.md](PAIN.md): a two-line program the
backends disagree about, and what it says about the language's string type.
