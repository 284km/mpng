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


def write_png(path, width, height, colour, pixels, filters, split_idat=False,
              depth=8, plte=None):
    """`pixels` is a list of rows, each a list of channel values (bytes)."""
    bpp = bytes_per_pixel(colour, depth)
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
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, 0))
        + (chunk(b"PLTE", plte) if plte else b"")
        + idats
        + chunk(b"IEND", b"")
    )
    with open(path, "wb") as f:
        f.write(png)
    return raw


def bytes_per_pixel(colour, depth):
    return {0: 1, 2: 3, 3: 1, 6: 4}[colour] * (2 if depth == 16 else 1)


def expected_path(path):
    return path + ".expected"


def write_expected(path, width, height, colour, pixels, depth=8, plte=None):
    """The PPM mpng should produce: alpha dropped, grey expanded to three, a
    palette index looked up, and a 16-bit sample reduced to its high byte —
    which is what the high byte of a big-endian sample means."""
    bpp = bytes_per_pixel(colour, depth)
    step = 2 if depth == 16 else 1
    out = bytearray(f"P6\n{width} {height}\n255\n".encode())
    for row in pixels:
        for x in range(width):
            p = row[x * bpp : (x + 1) * bpp]
            if colour == 3:
                e = p[0] * 3
                out += bytes(plte[e : e + 3]) if e + 3 <= len(plte) else b"\0\0\0"
            elif colour in (0, 4):
                out += bytes([p[0], p[0], p[0]])
            else:
                out += bytes([p[0], p[step], p[step * 2]])
    with open(expected_path(path), "wb") as f:
        f.write(out)


def case(outdir, name, width, height, colour, filters, split_idat=False,
         depth=8, plte=None):
    bpp = bytes_per_pixel(colour, depth)
    # Something with structure in both directions, so a filter that reads the
    # wrong neighbour produces a wrong answer rather than the same one.
    pixels = [
        [((x * 37 + y * 11 + c * 53) % 256) for x in range(width) for c in range(bpp)]
        for y in range(height)
    ]
    if colour == 3:
        # Indices have to be inside the palette, so they are taken modulo it.
        pixels = [[v % (len(plte) // 3) for v in row] for row in pixels]
    path = os.path.join(outdir, name)
    write_png(path, width, height, colour, pixels, filters, split_idat, depth, plte)
    write_expected(path, width, height, colour, pixels, depth, plte)
    return path


ADAM7 = [  # (xstart, ystart, xstep, ystep)
    (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
    (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2),
]


def interlaced_case(outdir, name, width, height):
    """An Adam7 image, with the expected PPM computed from the same pixels."""
    colour, bpp = 2, 3
    pixels = [[((x * 37 + y * 11 + c * 53) % 256) for x in range(width) for c in range(bpp)]
              for y in range(height)]
    raw = b""
    for (xs, ys, xstep, ystep) in ADAM7:
        pw = (width - xs + xstep - 1) // xstep
        ph = (height - ys + ystep - 1) // ystep
        if pw <= 0 or ph <= 0:
            continue          # contributes nothing at all, not even filter bytes
        prev = None
        for py in range(ph):
            sy = ys + py * ystep
            row = bytearray()
            for px in range(pw):
                sx = xs + px * xstep
                row += bytes(pixels[sy][sx * bpp : (sx + 1) * bpp])
            # A different filter per pass, so the per-pass "first row has nothing
            # above it" rule is exercised rather than assumed.
            kind = (ADAM7.index((xs, ys, xstep, ystep)) + py) % 5
            raw += filter_scanline(kind, bytes(row), prev, bpp)
            prev = bytes(row)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, colour, 0, 0, 1))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    path = os.path.join(outdir, name)
    with open(path, "wb") as f:
        f.write(png)
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
    # A palette: the pixels are indices, so a decoder that forgets to look them
    # up produces an image that is the right size and the wrong colours.
    plte = bytes([(i * 17) % 256 for i in range(6 * 3)])
    made.append(case(outdir, "palette.png", 5, 4, 3, [0, 1, 2, 3, 4], plte=plte))
    # 16-bit samples: two bytes each, so the filters step two bytes further back.
    # This decodes as noise if `left` is computed in samples instead of bytes.
    made.append(case(outdir, "rgb16_mixed.png", 6, 4, 2, [0, 1, 2, 3, 4], depth=16))
    made.append(case(outdir, "grey16_mixed.png", 5, 3, 0, [0, 1, 2, 3, 4], depth=16))
    # Interlaced: seven passes on seven different lattices, each filtered as if it
    # were an image of its own. Three sizes, because the edge cases are all about
    # which passes are empty — an image narrower than 5 pixels has passes with no
    # columns, and one 1 pixel tall has passes with no rows, and an empty pass
    # contributes no bytes at all (not even a filter byte), which shifts every
    # pass after it if a decoder assumes otherwise.
    for (w, h, name) in [(9, 9, "interlaced_9x9.png"),
                         (4, 4, "interlaced_4x4.png"),
                         (1, 1, "interlaced_1x1.png")]:
        made.append(interlaced_case(outdir, name, w, h))

    for p in made:
        print(os.path.basename(p))


if __name__ == "__main__":
    main()
