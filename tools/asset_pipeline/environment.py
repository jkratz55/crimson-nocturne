"""
Castle environment art: a 16x16 tileset atlas, two parallax layers
(moonlit sky + gothic hall with arched windows) and a 5x7 bitmap font
exported in BMFont text format (Godot imports .fnt natively).

Tileset atlas layout (8 x 2 tiles of 16px):
    row 0: brick_a, brick_b, floor_top, ledge(one-way), bg_brick, pillar, pillar_cap, pillar_base
    row 1: bg_brick_b, window_sill, carpet_top, ceiling, (unused...)
"""
from __future__ import annotations

import math
import os
import random

from PIL import Image, ImageDraw

from common import (
    BACKGROUNDS, CARPET, CARPET_HI, CAPE_IN, FONTS, MORTAR, MOSS, STONE, STONE_BG, STONE_BG_HI,
    STONE_BG_SH, STONE_HI, STONE_SH, TILES, TRIM, TRIM_SH, new_canvas, poly, px, rect, rgba,
)

T = 16


def brick_tile(seed: int, offsets: tuple[int, int], pal=(STONE, STONE_HI, STONE_SH)) -> Image.Image:
    """Two courses of bricks, each 8px tall; `offsets` shift the vertical joints."""
    base, hi, sh = pal
    rng = random.Random(seed)
    img, d = new_canvas(T, T)
    rect(d, 0, 0, T - 1, T - 1, MORTAR)
    for course, off in enumerate(offsets):
        y0 = course * 8
        for bx in range(-16, 32, 8 if course else 16):
            x0 = bx + off
            x1 = x0 + (7 if course else 15)
            cx0, cx1 = max(0, x0), min(T - 1, x1 - 1)
            if cx0 > cx1:
                continue
            rect(d, cx0, y0, cx1, y0 + 6, base)
            rect(d, cx0, y0, cx1, y0, hi)
            rect(d, cx0, y0 + 6, cx1, y0 + 6, sh)
            if x0 >= 0:
                rect(d, x0, y0, x0, y0 + 5, hi)
    for _ in range(10):
        x, y = rng.randrange(T), rng.randrange(T)
        if img.getpixel((x, y))[:3] == base:
            px(img, x, y, sh if rng.random() < 0.6 else hi)
    return img


def build_tileset() -> None:
    atlas = Image.new("RGBA", (T * 8, T * 2), (0, 0, 0, 0))
    bg_pal = (STONE_BG, STONE_BG_HI, STONE_BG_SH)

    brick_a = brick_tile(1, (0, 4))
    brick_b = brick_tile(2, (8, 12))
    # crack detail on variant B
    for x, y in ((3, 2), (4, 3), (4, 4), (5, 5)):
        px(brick_b, x, y, MORTAR)

    floor_top = brick_tile(3, (0, 4))
    fd = ImageDraw.Draw(floor_top)
    rect(fd, 0, 0, T - 1, 1, STONE_HI)
    rect(fd, 0, 2, T - 1, 2, STONE)
    for x in (2, 3, 9, 13):
        px(floor_top, x, 3, MOSS)

    ledge, ld = new_canvas(T, T)
    rect(ld, 0, 0, T - 1, 4, STONE)
    rect(ld, 0, 0, T - 1, 0, STONE_HI)
    rect(ld, 0, 4, T - 1, 4, STONE_SH)
    poly(ld, [(5, 5), (11, 5), (8, 9)], STONE_SH)          # corbel
    px(ledge, 8, 6, STONE)

    bg_a = brick_tile(4, (0, 8), bg_pal)

    pillar, pd = new_canvas(T, T)
    rect(pd, 2, 0, 13, T - 1, STONE_BG_HI)
    for x in (4, 7, 10):
        rect(pd, x, 0, x, T - 1, STONE_BG_SH)
    rect(pd, 2, 0, 2, T - 1, STONE_HI)
    rect(pd, 13, 0, 13, T - 1, STONE_BG_SH)

    cap, cd = new_canvas(T, T)
    rect(cd, 2, 8, 13, T - 1, STONE_BG_HI)
    rect(cd, 0, 3, T - 1, 7, STONE_BG_HI)
    rect(cd, 0, 3, T - 1, 3, STONE_HI)
    rect(cd, 1, 6, 14, 6, TRIM_SH)
    for x in (4, 7, 10):
        rect(cd, x, 8, x, T - 1, STONE_BG_SH)

    base = cap.transpose(Image.FLIP_TOP_BOTTOM)

    bg_b = brick_tile(5, (4, 12), bg_pal)

    sill, sd = new_canvas(T, T)
    rect(sd, 0, 10, T - 1, T - 1, STONE_BG_HI)
    rect(sd, 0, 10, T - 1, 10, STONE_HI)

    carpet = brick_tile(6, (0, 4))
    cp = ImageDraw.Draw(carpet)
    rect(cp, 0, 0, T - 1, 3, CARPET)
    rect(cp, 0, 0, T - 1, 0, CARPET_HI)
    rect(cp, 0, 4, T - 1, 4, TRIM_SH)
    for x in range(1, T, 4):
        px(carpet, x, 2, TRIM)

    ceiling = brick_tile(7, (0, 4))
    ce = ImageDraw.Draw(ceiling)
    rect(ce, 0, T - 2, T - 1, T - 1, STONE_SH)

    tiles = [brick_a, brick_b, floor_top, ledge, bg_a, pillar, cap, base,
             bg_b, sill, carpet, ceiling]
    for i, t in enumerate(tiles):
        atlas.paste(t, ((i % 8) * T, (i // 8) * T))
    atlas.save(os.path.join(TILES, "castle_tiles.png"))


# ---------------------------------------------------------------------------
# Parallax backgrounds
# ---------------------------------------------------------------------------
def build_sky() -> None:
    w, h = 480, 288
    img = Image.new("RGBA", (w, h))
    d = ImageDraw.Draw(img)
    top, bottom = (10, 8, 30), (58, 30, 78)
    for y in range(h):
        t = (y / h) ** 1.3
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        d.line([(0, y), (w, y)], fill=c + (255,))
    rng = random.Random(11)
    for _ in range(90):
        x, y = rng.randrange(w), rng.randrange(int(h * 0.6))
        b = rng.choice((140, 180, 230))
        px(img, x, y, (b, b, min(255, b + 20)))
    # moon + halo
    mx, my, r = 360, 64, 26
    for rr, a in ((r + 18, 26), (r + 10, 46), (r + 4, 70)):
        halo = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(halo).ellipse([mx - rr, my - rr, mx + rr, my + rr], fill=(210, 200, 255, a))
        img.alpha_composite(halo)
    d.ellipse([mx - r, my - r, mx + r, my + r], fill=(236, 232, 214, 255))
    d.ellipse([mx - r + 6, my - r, mx + r + 4, my + r - 2], fill=(214, 208, 190, 255))
    d.ellipse([mx - r, my - r, mx + r - 6, my + r - 4], fill=(240, 236, 222, 255))
    for cx, cy, cr in ((352, 56, 5), (368, 74, 4), (346, 76, 3), (372, 52, 2)):
        d.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=(206, 200, 184, 255))
    # drifting cloud bands
    for y0, col in ((96, (40, 26, 64, 200)), (118, (34, 22, 56, 220))):
        for x in range(0, w, 3):
            yy = y0 + int(4 * math.sin(x / 23.0) + 3 * math.sin(x / 7.0))
            d.line([(x, yy), (x + 3, yy)], fill=col, width=5)
    # distant castle silhouette
    sil = (22, 14, 36, 255)
    ground = [(0, 230)] + [(x, 230 - int(6 * math.sin(x / 40))) for x in range(0, w + 1, 8)] + [(w, h), (0, h)]
    d.polygon(ground, fill=sil)
    for tx, tw, th in ((40, 16, 70), (70, 10, 50), (150, 22, 110), (190, 12, 64), (300, 14, 80), (420, 18, 96)):
        d.rectangle([tx, 230 - th, tx + tw, 240], fill=sil)
        d.polygon([(tx - 2, 230 - th), (tx + tw // 2, 230 - th - tw * 1.6), (tx + tw + 2, 230 - th)], fill=sil)
        for wy in range(230 - th + 8, 226, 14):
            if (tx + wy) % 3 == 0:
                d.rectangle([tx + tw // 2 - 1, wy, tx + tw // 2, wy + 2], fill=(230, 170, 70, 255))
    img.save(os.path.join(BACKGROUNDS, "sky.png"))


def build_hall() -> None:
    """Interior wall with a tall arched window (transparent so the sky
    layer shows through) framed by columns and crimson drapes."""
    w, h = 256, 288
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rng = random.Random(21)
    # mortar base: the wall itself must be fully opaque — only the window
    # opening may reveal the sky layer behind it.
    d.rectangle([0, 0, w, h], fill=rgba(MORTAR))
    # wall: large ashlar blocks
    for y in range(0, h, 12):
        off = 0 if (y // 12) % 2 == 0 else 12
        for x in range(-24, w, 24):
            x0 = x + off
            c = STONE_BG if rng.random() > 0.2 else STONE_BG_SH
            d.rectangle([x0, y, x0 + 22, y + 10], fill=rgba(c))
            d.line([(x0, y), (x0 + 22, y)], fill=rgba(STONE_BG_HI))
    # window opening
    wx0, wx1, wy0, wy1 = 92, 164, 40, 200
    cxw, rad = (wx0 + wx1) // 2, (wx1 - wx0) // 2
    frame = (86, 90, 128, 255)
    d.rectangle([wx0 - 6, wy0 + rad - 6, wx1 + 6, wy1 + 6], fill=frame)
    d.ellipse([wx0 - 6, wy0 - 6, wx1 + 6, wy0 + 2 * rad + 6], fill=frame)
    d.rectangle([wx0, wy0 + rad, wx1, wy1], fill=(0, 0, 0, 0))
    d.ellipse([wx0, wy0, wx1, wy0 + 2 * rad], fill=(0, 0, 0, 0))
    # mullions and tracery
    mull = (60, 58, 90, 255)
    d.line([(cxw, wy0), (cxw, wy1)], fill=mull, width=3)
    for y in range(wy0 + rad + 10, wy1, 30):
        d.line([(wx0, y), (wx1, y)], fill=mull, width=2)
    d.arc([wx0 + 6, wy0 + 10, cxw, wy0 + rad + 20], 180, 360, fill=mull, width=2)
    d.arc([cxw, wy0 + 10, wx1 - 6, wy0 + rad + 20], 180, 360, fill=mull, width=2)
    # sill
    d.rectangle([wx0 - 10, wy1 + 4, wx1 + 10, wy1 + 10], fill=rgba(STONE_HI))
    d.line([(wx0 - 10, wy1 + 10), (wx1 + 10, wy1 + 10)], fill=rgba(STONE_SH))
    # drapes
    for side in (-1, 1):
        x_edge = wx0 - 4 if side < 0 else wx1 + 4
        pts = [(x_edge, wy0 + 16), (x_edge - 10 * side, wy0 + 14),
               (x_edge - 11 * side, wy1 + 8), (x_edge + 2 * side, wy1 + 8), (x_edge + 5 * side, wy0 + 70)]
        d.polygon(pts, fill=rgba(CAPE_IN))
        for k in range(2):
            fx = x_edge - (3 + 4 * k) * side
            d.line([(fx, wy0 + 30), (fx - 2 * side, wy1 + 6)], fill=(110, 14, 34, 255))
    d.rectangle([wx0 - 22, wy0 + 10, wx1 + 22, wy0 + 14], fill=rgba(TRIM_SH))
    # columns at tile edges (wrap seamlessly)
    for cx in (0, w):
        d.rectangle([cx - 12, 0, cx + 11, h], fill=(66, 70, 104, 255))
        for fx in (-8, -3, 2, 7):
            d.line([(cx + fx, 0), (cx + fx, h)], fill=rgba(STONE_BG_SH))
        d.line([(cx - 12, 0), (cx - 12, h)], fill=rgba(STONE_HI))
    # wainscot shadow near floor. Drawn on a separate layer and alpha-
    # composited: ImageDraw *replaces* RGBA values, which would punch
    # semi-transparent holes into the wall instead of darkening it.
    shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(236, h):
        a = int(160 * (y - 236) / (h - 236))
        sd.line([(0, y), (w, y)], fill=(8, 6, 16, a))
    img.alpha_composite(shade)
    img.save(os.path.join(BACKGROUNDS, "hall.png"))


# ---------------------------------------------------------------------------
# 5x7 bitmap font -> BMFont (.fnt text) + page png
# ---------------------------------------------------------------------------
GLYPHS: dict[str, list[str]] = {
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00110", "01000", "10000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01110", "10001", "10000", "10111", "10001", "10001", "01111"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["01110", "00100", "00100", "00100", "00100", "00100", "01110"],
    "J": ["00111", "00010", "00010", "00010", "00010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "10101", "01010"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    ".": ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    ",": ["00000", "00000", "00000", "00000", "01100", "00100", "01000"],
    "!": ["00100", "00100", "00100", "00100", "00100", "00000", "00100"],
    "?": ["01110", "10001", "00001", "00010", "00100", "00000", "00100"],
    ":": ["00000", "01100", "01100", "00000", "01100", "01100", "00000"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    "/": ["00001", "00010", "00010", "00100", "01000", "01000", "10000"],
    "+": ["00000", "00100", "00100", "11111", "00100", "00100", "00000"],
    "'": ["00100", "00100", "01000", "00000", "00000", "00000", "00000"],
    "(": ["00010", "00100", "01000", "01000", "01000", "00100", "00010"],
    ")": ["01000", "00100", "00010", "00010", "00010", "00100", "01000"],
}


def build_font() -> None:
    """White glyphs with a 1px dark drop shadow baked in (cell 7x9)."""
    chars = [" "] + list(GLYPHS.keys())
    # lowercase letters render as uppercase glyphs (keeps the font small)
    lower = [c.lower() for c in GLYPHS if c.isalpha()]
    cell_w, cell_h, cols = 7, 9, 16
    order = chars + lower
    rows = math.ceil(len(order) / cols)
    page = Image.new("RGBA", (cols * cell_w, rows * cell_h), (0, 0, 0, 0))
    lines = [
        'info face="NocturnePixel" size=8 bold=0 italic=0 charset="" unicode=1 stretchH=100 smooth=0 aa=1 padding=0,0,0,0 spacing=0,0',
        f"common lineHeight=10 base=7 scaleW={page.width} scaleH={page.height} pages=1 packed=0",
        'page id=0 file="nocturne_pixel.png"',
        f"chars count={len(order)}",
    ]
    for i, ch in enumerate(order):
        gx, gy = (i % cols) * cell_w, (i // cols) * cell_h
        glyph = GLYPHS.get(ch.upper())
        if glyph:
            for y, row in enumerate(glyph):
                for x, bit in enumerate(row):
                    if bit == "1":
                        page.putpixel((gx + x + 1, gy + y + 1), (20, 10, 26, 255))
            for y, row in enumerate(glyph):
                for x, bit in enumerate(row):
                    if bit == "1":
                        page.putpixel((gx + x, gy + y), (255, 255, 255, 255))
        adv = 6 if ch != " " else 4
        lines.append(
            f"char id={ord(ch)} x={gx} y={gy} width={cell_w - 1} height={cell_h - 1} "
            f"xoffset=0 yoffset=0 xadvance={adv} page=0 chnl=15"
        )
    page.save(os.path.join(FONTS, "nocturne_pixel.png"))
    with open(os.path.join(FONTS, "nocturne_pixel.fnt"), "w") as fh:
        fh.write("\n".join(lines) + "\n")


def build() -> None:
    build_tileset()
    build_sky()
    build_hall()
    build_font()


if __name__ == "__main__":
    build()
