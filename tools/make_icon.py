"""Generates assets/icon.ico (dark tile with four candles) without third-party packages.

    python tools/make_icon.py
"""

import struct
import zlib
from pathlib import Path

MASTER = 512          # drawn at this size, then box-filtered down per icon size
SIZES = (16, 24, 32, 48, 64, 128, 256)
OUT = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"

BG = (0x1f, 0x23, 0x29, 255)
GREEN = (0x3f, 0xb9, 0x50, 255)
RED = (0xf8, 0x51, 0x49, 255)
# (x centre, body top, body bottom, wick top, wick bottom, colour) in 0..1 coordinates
CANDLES = [
    (0.25, 0.55, 0.76, 0.47, 0.84, RED),
    (0.42, 0.40, 0.63, 0.31, 0.71, GREEN),
    (0.59, 0.46, 0.59, 0.38, 0.67, RED),
    (0.76, 0.19, 0.46, 0.12, 0.54, GREEN),
]
BODY_W, WICK_W = 0.12, 0.03


def pixel(x: float, y: float):
    # rounded square background
    m, r = 0.03, 0.2
    if not (m <= x <= 1 - m and m <= y <= 1 - m):
        return (0, 0, 0, 0)
    cx = min(max(x, m + r), 1 - m - r)
    cy = min(max(y, m + r), 1 - m - r)
    if (x - cx) ** 2 + (y - cy) ** 2 > r * r:
        return (0, 0, 0, 0)
    for xc, bt, bb, wt, wb, col in CANDLES:
        if abs(x - xc) <= BODY_W / 2 and bt <= y <= bb:
            return col
        if abs(x - xc) <= WICK_W / 2 and wt <= y <= wb:
            return col
    return BG


def render(size: int) -> bytes:
    ss = max(1, MASTER // size)  # samples per pixel per axis
    rows = []
    for py in range(size):
        row = bytearray([0])  # PNG filter type 0
        for px in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(ss):
                for sx in range(ss):
                    c = pixel((px + (sx + 0.5) / ss) / size, (py + (sy + 0.5) / ss) / size)
                    a = c[3]
                    acc[0] += c[0] * a
                    acc[1] += c[1] * a
                    acc[2] += c[2] * a
                    acc[3] += a
            n = ss * ss
            alpha = acc[3] / n
            if acc[3]:
                row += bytes((round(acc[0] / acc[3]), round(acc[1] / acc[3]), round(acc[2] / acc[3]), round(alpha)))
            else:
                row += b"\0\0\0\0"
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def main() -> None:
    images = [render(s) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, data = b"", b""
    for size, png in zip(SIZES, images):
        dim = 0 if size == 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(header + entries + data)
    (OUT.parent / "icon.png").write_bytes(images[-1])
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
