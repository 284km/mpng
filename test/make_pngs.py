#!/usr/bin/env python3
"""Write PNGs whose contents are known exactly, for verify.sh to decode.

The point of generating them here rather than checking in files: the pixels are
computed, so the expected answer is computed too, and the test can cover the
cases a real encoder would never happen to produce — every filter type on the
same image, a zlib stream split across two IDAT chunks, a scanline whose filter
refers to a row above it that was itself filtered differently.

Python's zlib does the compression; the PNG filters are applied here by hand,
because that is the part being tested and an encoder that applied them for us
would be deciding what to test.
"""

import os
import struct
import sys
import zlib


def chunk(tag, data):
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def filter_scanline(kind, row, prev, bpp):
    """Apply one PNG filter. `row` and `prev` are the raw (unfiltered) bytes."""
    out = bytearray()
    for i, cur in enumerate(row):
        left = row[i - bpp] if i >= bpp else 0
        up = prev[i] if prev else 0
        upleft = prev[i - bpp] if (prev and i >= bpp) else 0
        if kind == 0:
            v = cur
        elif kind == 1:
            v = cur - left
        elif kind == 2:
            v = cur - up
        elif kind == 3:
            v = cur - (left + up) // 2
        elif kind == 4:
            v = cur - paeth(left, up, upleft)
        out.append(v & 0xFF)
    return bytes([kind]) + bytes(out)


def write_png(path, width, height, colour, pixels, filters, split_idat=False):
    """`pixels` is a list of rows, each a list of channel values."""
    bpp = {0: 1, 2: 3, 6: 4}[colour]
    raw = b""
    prev = None
    for y, row in enumerate(pixels):
        flat = bytes(row)
        raw += filter_scanline(filters[y % len(filters)], flat, prev, bpp)
        prev = flat
    z = zlib.compress(raw)
    idats = (
        chunk(b"IDAT", z[: len(z) // 2]) + chunk(b"IDAT", z[len(z) // 2 :])
        if split_idat
        else chunk(b"IDAT", z)
    )
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, colour, 0, 0, 0))
        + idats
        + chunk(b"IEND", b"")
    )
    with open(path, "wb") as f:
        f.write(png)
    return raw


def expected_path(path):
    return path + ".expected"


def write_expected(path, width, height, colour, pixels):
    """The PPM mpng should produce: alpha dropped, grey expanded to three."""
    bpp = {0: 1, 2: 3, 6: 4}[colour]
    out = bytearray(f"P6\n{width} {height}\n255\n".encode())
    for row in pixels:
        for x in range(width):
            p = row[x * bpp : (x + 1) * bpp]
            if bpp == 1:
                out += bytes([p[0], p[0], p[0]])
            else:
                out += bytes(p[:3])
    with open(expected_path(path), "wb") as f:
        f.write(out)


def case(outdir, name, width, height, colour, filters, split_idat=False):
    bpp = {0: 1, 2: 3, 6: 4}[colour]
    # Something with structure in both directions, so a filter that reads the
    # wrong neighbour produces a wrong answer rather than the same one.
    pixels = [
        [((x * 37 + y * 11 + c * 53) % 256) for x in range(width) for c in range(bpp)]
        for y in range(height)
    ]
    path = os.path.join(outdir, name)
    write_png(path, width, height, colour, pixels, filters, split_idat)
    write_expected(path, width, height, colour, pixels)
    return path


def main():
    outdir = sys.argv[1]
    os.makedirs(outdir, exist_ok=True)
    made = []
    # One case per filter, so a broken filter names itself.
    for kind in range(5):
        made.append(case(outdir, f"rgb_filter{kind}.png", 7, 5, 2, [kind]))
    # Filters mixed down the image, which is what a real encoder does: each row
    # is reconstructed against the row above it, already reconstructed.
    made.append(case(outdir, "rgb_mixed.png", 9, 6, 2, [0, 1, 2, 3, 4]))
    made.append(case(outdir, "grey_mixed.png", 8, 4, 0, [0, 1, 2, 3, 4]))
    made.append(case(outdir, "rgba_mixed.png", 6, 4, 6, [0, 1, 2, 3, 4]))
    # The zlib stream split across two chunks: a decoder that inflates each IDAT
    # separately passes every test above and fails this one.
    made.append(case(outdir, "rgb_split_idat.png", 10, 8, 2, [0, 1, 2, 3, 4], True))
    for p in made:
        print(os.path.basename(p))


if __name__ == "__main__":
    main()
