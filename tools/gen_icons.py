#!/usr/bin/env python3
"""Generate the PWA icons. Stdlib only (zlib + struct write the PNG), so the
dashboard has no build step and no image dependency.

The mark is a set of growth rings — cambium is the layer a tree grows from, and
the rings are what a store of accumulated decisions looks like. The rings stay
inside the middle 60% of the canvas so the maskable variant survives Android's
circular crop.

    python tools/gen_icons.py
"""

import math
import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "icons")

BG = (0x12, 0x16, 0x1c)
INK = (0x6f, 0xd3, 0x9b)
DIM = (0x2f, 0x6f, 0x4f)


def _write_png(path, size, rows):
    raw = b"".join(b"\x00" + bytes(c for px in row for c in px) for row in rows)
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", header)
                + chunk(b"IDAT", zlib.compress(raw, 9))
                + chunk(b"IEND", b""))


def _blend(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def build(size):
    c = (size - 1) / 2.0
    # Four rings inside the safe radius, alternating bright/dim so the mark
    # reads at 48px as well as 512.
    radii = [0.14, 0.24, 0.34, 0.44]
    width = size * 0.028
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            d = math.hypot(x - c, y - c)
            px = BG
            for i, r in enumerate(radii):
                target = r * size
                # Distance from the ring's centre line, in pixels; feather over
                # one pixel so the curve is not a staircase.
                edge = abs(d - target)
                if edge < width:
                    colour = INK if i % 2 == 0 else DIM
                    px = _blend(px, colour, 1.0 - (edge / width) ** 2)
            if d < radii[0] * size * 0.45:
                px = INK  # solid core
            row.append(px)
        rows.append(row)
    return rows


def main():
    os.makedirs(OUT, exist_ok=True)
    for size in (192, 512):
        path = os.path.join(OUT, f"icon-{size}.png")
        _write_png(path, size, build(size))
        print(f"wrote {path} ({os.path.getsize(path)} bytes)")


if __name__ == "__main__":
    main()
