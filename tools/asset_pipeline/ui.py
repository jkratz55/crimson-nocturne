"""
Interface art, SotN pass: fonts, HUD, menu windows, cursor and markers, the
area-name banner and the title-screen backdrop.

Fonts (BMFont text format; Godot imports .fnt natively). A bitmap font is
only drawn 1:1 when the Label's font size equals the `info size` written
here, so every scene that uses one of the special fonts also sets
`theme_override_font_sizes/font_size` to the size listed:

    nocturne_pixel   size 8   menu / body text: proportional, mixed case,
                              cap height 7, x-height 5, descender 2,
                              line height 10, 1 px drop shadow baked in
    nocturne_title   size 16  Roman inscriptional capitals, cap height 12,
                              2/1 px stroke contrast, bracketed serifs,
                              1 px outline, banded silver-white gradient
    nocturne_hp      size 13  HUD hit-point digits, 5x11 + outline, 6 px advance
    nocturne_small   size 7   HUD heart-count digits, 3x5 + outline, 4 px advance
    nocturne_damage  size 9   damage numbers, chunky 5x7 + outline, 6 px advance

Glyphs are white (or a light gradient) with dark shadows/outlines, because
Labels tint them with `font_color`, which multiplies.

Windows: SotN-style translucent navy windows (a 5-band vertical gradient,
4x4 Bayer-dithered between bands) with a thin silver border and a dark outer
line; corners are square and plain (no rivets). A NinePatchRect stretches its centre,
which would smear the dither, so every window the scenes use is generated
at its exact on-screen size (see WINDOWS); a NinePatchRect whose rect equals
its texture draws it 1:1. `menu_frame.png` stays as a generic nine-patch
(6 px margins, banded but undithered centre) for anything new.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, distance_transform_edt, label

from common import (
    COLORS, FONTS, LIGHT_ENV, RAMPS, RGB, UI,
    bayer, fbm, mix, quantize_to_ramp, shade_normals,
)

RGBA = tuple[int, int, int, int]
Pt = tuple[float, float]


def _rgba(c: Sequence[int], a: int = 255) -> RGBA:
    return (int(c[0]), int(c[1]), int(c[2]), int(c[3]) if len(c) > 3 else a)


# ===========================================================================
# Palette (all from the shared registry so the UI matches the world)
# ===========================================================================
GOLD = RAMPS["gold"]          # 6 tones, G5 specular only
STEEL = RAMPS["steel"]        # 6 tones
WINDOW = RAMPS["ui_window"]   # 5 bands, top -> bottom
CRIMSON = RAMPS["crimson"]
HEART_R = RAMPS["heart"]
MANA = RAMPS["mana"]

BORDER_LIT: RGB = COLORS["ui_border"]            # (226, 226, 240)
BORDER_SHADE: RGB = (150, 152, 190)              # bottom/right of the border ring
BORDER_OUTER: RGB = COLORS["ui_border_shadow"]   # (4, 4, 20)
BORDER_INNER: RGB = (10, 10, 40)                 # 1 px seat between border and fill
TEXT_SHADOW: RGB = COLORS["ui_text_shadow"]      # (6, 6, 24)
GLYPH_OUTLINE: RGB = (10, 6, 26)
STUD: RGB = (246, 246, 255)
VOID_OUTLINE: RGB = COLORS["void"]               # (6, 4, 12) outer HUD outline

WINDOW_ALPHA = 232            # translucent over the dimmed game, like PS1 average blend


# ===========================================================================
# Bitmap helpers
# ===========================================================================
def _mask(rows: Sequence[str]) -> np.ndarray:
    """'#' rows -> bool array (h, w). Every row must be the same width."""
    w = len(rows[0])
    for r in rows:
        if len(r) != w:
            raise ValueError(f"ragged glyph rows: {rows}")
    return np.array([[ch == "#" for ch in r] for r in rows], dtype=bool)


def _dilate(m: np.ndarray, diagonal: bool = True) -> np.ndarray:
    out = m.copy()
    h, w = m.shape
    offs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    if diagonal:
        offs += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
    for dy, dx in offs:
        sl_dst = (slice(max(0, dy), h + min(0, dy)), slice(max(0, dx), w + min(0, dx)))
        sl_src = (slice(max(0, -dy), h + min(0, -dy)), slice(max(0, -dx), w + min(0, -dx)))
        out[sl_dst] |= m[sl_src]
    return out


def _paint(img: np.ndarray, m: np.ndarray, color: Sequence[int], ox: int = 0, oy: int = 0) -> None:
    """Write `color` (RGB or RGBA) into the RGBA array wherever `m` is set."""
    h, w = m.shape
    region = img[oy:oy + h, ox:ox + w]
    region[m[:region.shape[0], :region.shape[1]]] = _rgba(color)


def _to_image(a: np.ndarray) -> Image.Image:
    return Image.fromarray(a.astype(np.uint8), "RGBA")


# ===========================================================================
# BMFont writer
# ===========================================================================
@dataclass
class Glyph:
    char: str
    image: Image.Image     # RGBA, drawn with its top-left at (pen + xoffset, line top + yoffset)
    xadvance: int
    xoffset: int = 0
    yoffset: int = 0


def write_bmfont(stem: str, face: str, size: int, line_height: int, base: int,
                 glyphs: Sequence[Glyph], page_width: int = 128) -> tuple[int, int]:
    """Shelf-pack `glyphs` into one page (1 px gutters) and write
    assets/fonts/<stem>.png + <stem>.fnt. Returns the page size."""
    placed: list[tuple[Glyph, int, int]] = []
    seen: dict[int, tuple[int, int]] = {}      # aliases share one bitmap in the page
    x, y, shelf = 0, 0, 0
    for g in glyphs:
        if id(g.image) in seen:
            placed.append((g, *seen[id(g.image)]))
            continue
        gw, gh = g.image.size
        if x + gw > page_width:
            x, y, shelf = 0, y + shelf + 1, 0
        placed.append((g, x, y))
        seen[id(g.image)] = (x, y)
        x += gw + 1
        shelf = max(shelf, gh)
    page_h = y + shelf
    page = Image.new("RGBA", (page_width, page_h), (0, 0, 0, 0))
    lines = [
        f'info face="{face}" size={size} bold=0 italic=0 charset="" unicode=1 stretchH=100 '
        'smooth=0 aa=1 padding=0,0,0,0 spacing=0,0',
        f"common lineHeight={line_height} base={base} scaleW={page_width} scaleH={page_h} "
        "pages=1 packed=0",
        f'page id=0 file="{stem}.png"',
        f"chars count={len(placed)}",
    ]
    drawn: set[int] = set()
    for g, gx, gy in placed:
        if id(g.image) not in drawn:
            page.alpha_composite(g.image, (gx, gy))
            drawn.add(id(g.image))
        gw, gh = g.image.size
        lines.append(
            f"char id={ord(g.char)} x={gx} y={gy} width={gw} height={gh} "
            f"xoffset={g.xoffset} yoffset={g.yoffset} xadvance={g.xadvance} page=0 chnl=15")
    page.save(os.path.join(FONTS, f"{stem}.png"))
    with open(os.path.join(FONTS, f"{stem}.fnt"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return page_width, page_h


def _alias(glyphs: list[Glyph], mapping: dict[str, str]) -> None:
    """Add glyph entries that reuse another character's bitmap."""
    by_char = {g.char: g for g in glyphs}
    for new, old in mapping.items():
        if new not in by_char and old in by_char:
            src = by_char[old]
            glyphs.append(Glyph(new, src.image, src.xadvance, src.xoffset, src.yoffset))


# ===========================================================================
# 1. Menu / body font: proportional, mixed case, 1 px drop shadow
#    Cell rows 0..8: caps and ascenders 0-6 (baseline under row 6), x-height
#    rows 2-6, descenders 7-8; the shadow adds row 9 -> line height 10.
#    Each entry is (top_row, rows).
# ===========================================================================
GLYPHS: dict[str, tuple[int, list[str]]] = {
    # --- capitals: light serifs on the left-stem letters (B D E F L P R) and I, J
    "A": (0, ["..#..", ".#.#.", ".#.#.", "#...#", "#####", "#...#", "#...#"]),
    "B": (0, ["####.", ".#..#", ".#..#", ".###.", ".#..#", ".#..#", "####."]),
    "C": (0, [".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."]),
    "D": (0, ["####.", ".#..#", ".#..#", ".#..#", ".#..#", ".#..#", "####."]),
    "E": (0, ["#####", ".#...", ".#...", ".###.", ".#...", ".#...", "#####"]),
    "F": (0, ["#####", ".#...", ".#...", ".###.", ".#...", ".#...", "###.."]),
    "G": (0, [".###.", "#...#", "#....", "#..##", "#...#", "#...#", ".###."]),
    "H": (0, ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"]),
    "I": (0, ["###", ".#.", ".#.", ".#.", ".#.", ".#.", "###"]),
    "J": (0, [".###", "..#.", "..#.", "..#.", "..#.", "#.#.", ".#.."]),
    "K": (0, ["#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"]),
    "L": (0, ["###..", ".#...", ".#...", ".#...", ".#...", ".#..#", "#####"]),
    "M": (0, ["#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"]),
    "N": (0, ["#...#", "##..#", "#.#.#", "#.#.#", "#..##", "#...#", "#...#"]),
    "O": (0, [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."]),
    "P": (0, ["####.", ".#..#", ".#..#", ".###.", ".#...", ".#...", "###.."]),
    "Q": (0, [".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"]),
    "R": (0, ["####.", ".#..#", ".#..#", ".###.", ".#.#.", ".#..#", "##..#"]),
    "S": (0, [".###.", "#...#", "#....", ".###.", "....#", "#...#", ".###."]),
    "T": (0, ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."]),
    "U": (0, ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."]),
    "V": (0, ["#...#", "#...#", "#...#", ".#.#.", ".#.#.", ".#.#.", "..#.."]),
    "W": (0, ["#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"]),
    "X": (0, ["#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"]),
    "Y": (0, ["#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."]),
    "Z": (0, ["#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"]),
    # --- lowercase
    "a": (2, [".##.", "...#", ".###", "#..#", ".###"]),
    "b": (0, ["#...", "#...", "###.", "#..#", "#..#", "#..#", "###."]),
    "c": (2, [".###", "#...", "#...", "#...", ".###"]),
    "d": (0, ["...#", "...#", ".###", "#..#", "#..#", "#..#", ".###"]),
    "e": (2, [".##.", "#..#", "####", "#...", ".###"]),
    "f": (0, [".##", ".#.", "###", ".#.", ".#.", ".#.", ".#."]),
    "g": (2, [".###", "#..#", "#..#", "#..#", ".###", "...#", ".##."]),
    "h": (0, ["#...", "#...", "###.", "#..#", "#..#", "#..#", "#..#"]),
    "i": (0, ["#", ".", "#", "#", "#", "#", "#"]),
    "j": (0, [".#", "..", ".#", ".#", ".#", ".#", ".#", ".#", "#."]),
    "k": (0, ["#...", "#...", "#..#", "#.#.", "##..", "#.#.", "#..#"]),
    "l": (0, ["#.", "#.", "#.", "#.", "#.", "#.", ".#"]),
    "m": (2, ["####.", "#.#.#", "#.#.#", "#.#.#", "#.#.#"]),
    "n": (2, ["###.", "#..#", "#..#", "#..#", "#..#"]),
    "o": (2, [".##.", "#..#", "#..#", "#..#", ".##."]),
    "p": (2, ["###.", "#..#", "#..#", "#..#", "###.", "#...", "#..."]),
    "q": (2, [".###", "#..#", "#..#", "#..#", ".###", "...#", "...#"]),
    "r": (2, ["#.##", "##..", "#...", "#...", "#..."]),
    "s": (2, [".###", "#...", ".##.", "...#", "###."]),
    "t": (1, [".#.", "###", ".#.", ".#.", ".#.", "..#"]),
    "u": (2, ["#..#", "#..#", "#..#", "#..#", ".###"]),
    "v": (2, ["#...#", "#...#", ".#.#.", ".#.#.", "..#.."]),
    "w": (2, ["#...#", "#...#", "#.#.#", "#.#.#", ".#.#."]),
    "x": (2, ["#...#", ".#.#.", "..#..", ".#.#.", "#...#"]),
    "y": (2, ["#..#", "#..#", "#..#", "#..#", ".###", "...#", ".##."]),
    "z": (2, ["####", "..#.", ".#..", "#...", "####"]),
    # --- digits: tabular (all 5 wide, 6 px advance) so stat columns line up
    "0": (0, [".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."]),
    "1": (0, ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."]),
    "2": (0, [".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"]),
    "3": (0, [".###.", "#...#", "....#", "..##.", "....#", "#...#", ".###."]),
    "4": (0, ["...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "..###"]),
    "5": (0, ["#####", "#....", "####.", "....#", "....#", "#...#", ".###."]),
    "6": (0, ["..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."]),
    "7": (0, ["#####", "#...#", "....#", "...#.", "..#..", "..#..", "..#.."]),
    "8": (0, [".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."]),
    "9": (0, [".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."]),
    # --- punctuation and symbols (full printable ASCII, so no hex boxes)
    ".": (6, ["#"]),
    ",": (6, [".#", "#."]),
    "!": (0, ["#", "#", "#", "#", "#", ".", "#"]),
    "?": (0, [".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."]),
    ":": (2, ["#", ".", ".", "#"]),
    ";": (2, [".#", "..", "..", ".#", "#."]),
    "-": (3, ["###"]),
    "/": (0, ["...#", "...#", "..#.", "..#.", ".#..", ".#..", "#..."]),
    "\\": (0, ["#...", "#...", ".#..", ".#..", "..#.", "..#.", "...#"]),
    "+": (1, ["..#..", "..#..", "#####", "..#..", "..#.."]),
    "'": (0, ["#", "#"]),
    '"': (0, ["#.#", "#.#"]),
    "`": (0, ["#.", ".#"]),
    "(": (0, ["..#", ".#.", "#..", "#..", "#..", ".#.", "..#"]),
    ")": (0, ["#..", ".#.", "..#", "..#", "..#", ".#.", "#.."]),
    "[": (0, ["##", "#.", "#.", "#.", "#.", "#.", "##"]),
    "]": (0, ["##", ".#", ".#", ".#", ".#", ".#", "##"]),
    "{": (0, [".##", ".#.", ".#.", "#..", ".#.", ".#.", ".##"]),
    "}": (0, ["##.", ".#.", ".#.", "..#", ".#.", ".#.", "##."]),
    "%": (0, ["##..#", "##..#", "...#.", "..#..", ".#...", "#..##", "#..##"]),
    "|": (0, ["#", "#", "#", "#", "#", "#", "#"]),
    ">": (1, ["#..", "##.", "###", "##.", "#.."]),
    "<": (1, ["..#", ".##", "###", ".##", "..#"]),
    "=": (2, ["####", "....", "####"]),
    "#": (1, [".#.#.", "#####", ".#.#.", "#####", ".#.#."]),
    "_": (8, ["#####"]),
    "*": (1, ["#.#", ".#.", "#.#"]),
    "&": (0, [".##..", "#..#.", "#.#..", ".#...", "#.#.#", "#..#.", ".##.#"]),
    "@": (0, [".###.", "#...#", "#.###", "#.#.#", "#.###", "#....", ".###."]),
    "$": (0, ["..#..", ".####", "#.#..", ".###.", "..#.#", "####.", "..#.."]),
    "^": (0, [".#.", "#.#"]),
    "~": (2, [".#.#", "#.#."]),
    # --- the few non-ASCII characters the game text uses or may use
    "—": (3, ["#######"]),        # em dash (leap_stone.tres)
    "–": (3, ["#####"]),          # en dash
    "×": (2, ["#.#", ".#.", "#.#"]),  # multiplication sign
    "…": (6, ["#.#.#"]),          # ellipsis
    "·": (3, ["#"]),              # middle dot
    "°": (0, [".#.", "#.#", ".#."]),  # degree
}
MENU_SPACE_ADVANCE = 3
MENU_CELL_ROWS = 9            # 0..8, plus the shadow row


def _menu_glyph(char: str, top: int, rows: list[str]) -> Glyph:
    m = _mask(rows)
    h, w = m.shape
    cell = np.zeros((MENU_CELL_ROWS + 1, w + 1, 4), np.uint8)
    full = np.zeros((MENU_CELL_ROWS, w), bool)
    full[top:top + h] = m
    _paint(cell, full, TEXT_SHADOW, 1, 1)
    _paint(cell, full, (255, 255, 255), 0, 0)
    return Glyph(char, _to_image(cell), w + 1)


def build_font() -> None:
    glyphs: list[Glyph] = [Glyph(" ", Image.new("RGBA", (1, 1), (0, 0, 0, 0)), MENU_SPACE_ADVANCE)]
    for ch, (top, rows) in GLYPHS.items():
        glyphs.append(_menu_glyph(ch, top, rows))
    _alias(glyphs, {"‘": "'", "’": "'", "“": '"', "”": '"', " ": " "})
    write_bmfont("nocturne_pixel", "NocturnePixel", 8, 10, 7, glyphs, page_width=128)


# ===========================================================================
# 2. Title font: Roman inscriptional capitals, cap height 12.
#    Thick strokes 2 px, thin 1 px (down-strokes thick, as cut with a
#    broad brush), bracketed serifs. Outline 1 px (8-connected); the fill is
#    a banded white -> silver-lavender gradient that a gold font_color turns
#    into gilt.
# ===========================================================================
TITLE_GLYPHS: dict[str, list[str]] = {
    "A": [".....##.....", ".....###....", "....#.##....", "....#.##....",
          "...#...##...", "...#...##...", "...#....##..", "..########..",
          "..#.....##..", ".#.......##.", ".#.......##.", "###.....####"],
    "B": ["#######...", ".##...##..", ".##....##.", ".##....##.", ".##...##..", ".######...",
          ".##....##.", ".##.....##", ".##.....##", ".##.....##", ".##....##.", "########.."],
    "C": ["...#####..", "..##....#.", ".##.....##", "##........", "##........", "##........",
          "##........", "##........", "##........", ".##.....##", "..##....#.", "...#####.."],
    "D": ["########...", ".##....##..", ".##.....##.", ".##......##", ".##......##", ".##......##",
          ".##......##", ".##......##", ".##......##", ".##.....##.", ".##....##..", "########..."],
    "E": ["#########", ".##.....#", ".##......", ".##......", ".##...#..", ".######..",
          ".##...#..", ".##......", ".##......", ".##......", ".##.....#", "#########"],
    "F": ["#########", ".##.....#", ".##......", ".##......", ".##...#..", ".######..",
          ".##...#..", ".##......", ".##......", ".##......", ".##......", "####....."],
    "G": ["...#####...", "..##....#..", ".##.....##.", "##.........", "##.........", "##.........",
          "##....#####", "##......##.", "##......##.", ".##.....##.", "..##....##.", "...######.."],
    "H": ["####..####", ".##....##.", ".##....##.", ".##....##.", ".##....##.", ".########.",
          ".##....##.", ".##....##.", ".##....##.", ".##....##.", ".##....##.", "####..####"],
    "I": ["####", ".##.", ".##.", ".##.", ".##.", ".##.", ".##.", ".##.", ".##.", ".##.", ".##.", "####"],
    "J": ["..####", "...##.", "...##.", "...##.", "...##.", "...##.", "...##.", "...##.",
          "...##.", "#..##.", "##.##.", ".###.."],
    "K": ["####...####", ".##.....#..", ".##....#...", ".##...#....", ".##..#.....", ".####......",
          ".####......", ".##.##.....", ".##..##....", ".##...##...", ".##....##..", "####..#####"],
    "L": ["####.....", ".##......", ".##......", ".##......", ".##......", ".##......",
          ".##......", ".##......", ".##......", ".##......", ".##.....#", "#########"],
    "M": ["###......####", ".##.......##.", ".##.......##.", ".###.....###.", ".###.....###.",
          ".#.##...#.##.", ".#.##...#.##.", ".#..##.#..##.", ".#..##.#..##.", ".#...##...##.",
          ".#...##...##.", "###..##..####"],
    "N": ["###.....###", ".##......#.", ".###.....#.", ".#.##....#.", ".#.##....#.", ".#..##...#.",
          ".#...##..#.", ".#....##.#.", ".#....##.#.", ".#.....###.", ".#......##.", "###.....##."],
    "O": ["...#####...", "..##...##..", ".##.....##.", "##.......##", "##.......##", "##.......##",
          "##.......##", "##.......##", "##.......##", ".##.....##.", "..##...##..", "...#####..."],
    "P": ["########..", ".##....##.", ".##.....##", ".##.....##", ".##.....##", ".##....##.",
          ".#######..", ".##.......", ".##.......", ".##.......", ".##.......", "####......"],
    "Q": ["...#####....", "..##...##...", ".##.....##..", "##.......##.", "##.......##.", "##.......##.",
          "##.......##.", "##.......##.", "##.......##.", ".##.....##..", "..##..####..", "...#####.###"],
    "R": ["########...", ".##....##..", ".##.....##.", ".##.....##.", ".##....##..", ".######....",
          ".##..##....", ".##...##...", ".##...##...", ".##....##..", ".##.....##.", "####.....##"],
    "S": ["..######.", ".##....##", "##......#", "##.......", ".###.....", "..#####..",
          ".....###.", ".......##", ".......##", "#......##", "##....##.", ".######.."],
    "T": ["##########", "#...##...#", "....##....", "....##....", "....##....", "....##....",
          "....##....", "....##....", "....##....", "....##....", "....##....", "...####..."],
    "U": ["####...###", ".##.....#.", ".##.....#.", ".##.....#.", ".##.....#.", ".##.....#.",
          ".##.....#.", ".##.....#.", ".##.....#.", ".##.....#.", "..##...##.", "...####..."],
    "V": ["####....###", ".##......#.", ".##......#.", "..##....#..", "..##....#..", "...##...#..",
          "...##..#...", "...##..#...", "....##.#...", "....###....", ".....##....", ".....##...."],
    "W": ["####..###...###", ".##....##....#.", ".##....##....#.", "..##...###...#.",
          "..##..#.##..#..", "..##..#.##..#..", "...##.#..##.#..", "...##.#..##.#..",
          "...###...###...", "....##....##...", "....##....##...", "....##....##..."],
    "X": ["####...####", ".##.....#..", "..##....#..", "...##..#...", "...##.#....", "....##.....",
          "....###....", "...#..##...", "...#..##...", "..#....##..", ".#......##.", "###....####"],
    "Y": ["####...###", ".##.....#.", "..##....#.", "..##...#..", "...##.#...", "....###...",
          "....##....", "....##....", "....##....", "....##....", "....##....", "..######.."],
    "Z": ["##########", "#......##.", "......##..", ".....##...", ".....##...", "....##....",
          "...##.....", "...##.....", "..##......", ".##.......", "##.......#", "##########"],
    "0": ["..####..", ".##..##.", "##....##", "##....##", "##....##", "##....##",
          "##....##", "##....##", "##....##", "##....##", ".##..##.", "..####.."],
    "1": ["..##..", "####..", "..##..", "..##..", "..##..", "..##..",
          "..##..", "..##..", "..##..", "..##..", "..##..", "######"],
    "2": [".#####..", "##...##.", "##....##", "......##", ".....##.", "....##..",
          "...##...", "..##....", ".##.....", "##......", "##.....#", "########"],
    "3": [".#####..", "##...##.", ".....##.", ".....##.", "....##..", "..####..",
          ".....##.", "......##", "......##", "##....##", "##...##.", ".#####.."],
    "4": [".....##..", "....###..", "...#.##..", "..#..##..", ".#...##..", "#....##..",
          "#########", ".....##..", ".....##..", ".....##..", ".....##..", "...######"],
    "5": ["########", "##......", "##......", "##.###..", "###..##.", "......##",
          "......##", "......##", "......##", "##....##", "##...##.", ".#####.."],
    "6": ["...####.", "..##....", ".##.....", "##......", "##.###..", "###..##.",
          "##....##", "##....##", "##....##", "##....##", ".##..##.", "..####.."],
    "7": ["########", "#.....##", ".....##.", ".....##.", "....##..", "....##..",
          "...##...", "...##...", "...##...", "..##....", "..##....", "..##...."],
    "8": ["..####..", ".##..##.", "##....##", "##....##", ".##..##.", "..####..",
          ".##..##.", "##....##", "##....##", "##....##", ".##..##.", "..####.."],
    "9": ["..####..", ".##..##.", "##....##", "##....##", "##....##", "##....##",
          ".##..###", "..###.##", "......##", ".....##.", "....##..", ".####..."],
    "'": ["##", "##", ".#", "#.", "..", "..", "..", "..", "..", "..", "..", ".."],
    "-": [".....", ".....", ".....", ".....", ".....", ".....",
          "#####", ".....", ".....", ".....", ".....", "....."],
    ".": ["..", "..", "..", "..", "..", "..", "..", "..", "..", "..", "##", "##"],
    ",": ["..", "..", "..", "..", "..", "..", "..", "..", "..", "..", "##", ".#"],
    "!": ["##", "##", "##", "##", "##", "##", "##", "##", "..", "..", "##", "##"],
    "?": [".#####.", "##...##", ".....##", "....##.", "...##..", "...##..",
          "...##..", ".......", ".......", "...##..", "...##..", "......."],
    ":": ["..", "..", "..", "##", "##", "..", "..", "..", "..", "##", "##", ".."],
}
TITLE_CAP = 12
TITLE_SPACE_ADVANCE = 6
TITLE_TRACKING = 1            # clear pixels between two letters' outlines
TITLE_BANDS: list[RGB] = [(255, 255, 255), (240, 240, 252), (222, 222, 244), (204, 204, 236)]
TITLE_BAND_ROWS = [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3]   # per cap row -> band


def _title_glyph(char: str, rows: list[str]) -> Glyph:
    m = _mask(rows)
    h, w = m.shape
    pad = np.zeros((h + 2, w + 2), bool)
    pad[1:-1, 1:-1] = m
    a = np.zeros((h + 2, w + 2, 4), np.uint8)
    _paint(a, _dilate(pad, diagonal=True), GLYPH_OUTLINE)
    for r in range(h):
        row = np.zeros_like(pad)
        row[r + 1, 1:-1] = m[r]
        _paint(a, row, TITLE_BANDS[TITLE_BAND_ROWS[r]])
    return Glyph(char, _to_image(a), w + 2 + TITLE_TRACKING)


def build_title_font() -> None:
    glyphs: list[Glyph] = [Glyph(" ", Image.new("RGBA", (1, 1), (0, 0, 0, 0)), TITLE_SPACE_ADVANCE)]
    for ch, rows in TITLE_GLYPHS.items():
        if len(rows) != TITLE_CAP:
            raise ValueError(f"title glyph {ch!r} has {len(rows)} rows")
        glyphs.append(_title_glyph(ch, rows))
    # Area and boss names come in mixed case; render lowercase as capitals.
    _alias(glyphs, {c.lower(): c for c in TITLE_GLYPHS if c.isalpha()})
    _alias(glyphs, {"’": "'", "—": "-", "–": "-"})
    # Glyph cell = outline row + 12 cap rows + outline row; base 13 puts the
    # baseline right under the cap rows.
    write_bmfont("nocturne_title", "NocturneTitle", 16, 16, 13, glyphs, page_width=128)


# ===========================================================================
# 3. HUD digit fonts and 4. damage digits
# ===========================================================================
HP_DIGITS: dict[str, list[str]] = {
    "0": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "1": ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "2": [".###.", "#...#", "....#", "....#", "....#", "...#.", "..#..", ".#...", "#....", "#....", "#####"],
    "3": [".###.", "#...#", "....#", "....#", "....#", "..##.", "....#", "....#", "....#", "#...#", ".###."],
    "4": ["...#.", "..##.", "..##.", ".#.#.", ".#.#.", "#..#.", "#####", "...#.", "...#.", "...#.", "...#."],
    "5": ["#####", "#....", "#....", "#....", "####.", "....#", "....#", "....#", "....#", "#...#", ".###."],
    "6": ["..##.", ".#...", "#....", "#....", "####.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "7": ["#####", "....#", "....#", "...#.", "...#.", "..#..", "..#..", "..#..", ".#...", ".#...", ".#..."],
    "8": [".###.", "#...#", "#...#", "#...#", ".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "9": [".###.", "#...#", "#...#", "#...#", "#...#", ".####", "....#", "....#", "....#", "...#.", ".##.."],
}
# Vertical gradient (250,250,255) -> (196,200,232), banded per row.
HP_BANDS: list[RGB] = [(250, 250, 255), (250, 250, 255), (238, 238, 250), (238, 238, 250),
                       (228, 230, 246), (228, 230, 246), (218, 220, 242), (212, 214, 240),
                       (206, 208, 238), (200, 204, 234), (196, 200, 232)]
HP_BEVEL: RGB = (92, 96, 150)     # engraved right side of each stroke
HP_ADVANCE = 7                    # 5 px stroke + bevel + 1 px shared outline

SMALL_DIGITS: dict[str, list[str]] = {
    "0": ["###", "#.#", "#.#", "#.#", "###"],
    "1": [".#.", "##.", ".#.", ".#.", "###"],
    "2": ["###", "..#", "###", "#..", "###"],
    "3": ["###", "..#", ".##", "..#", "###"],
    "4": ["#.#", "#.#", "###", "..#", "..#"],
    "5": ["###", "#..", "###", "..#", "###"],
    "6": ["###", "#..", "###", "#.#", "###"],
    "7": ["###", "..#", "..#", ".#.", ".#."],
    "8": ["###", "#.#", "###", "#.#", "###"],
    "9": ["###", "#.#", "###", "..#", "###"],
    "/": ["..#", "..#", ".#.", "#..", "#.."],
    "-": ["...", "...", "###", "...", "..."],
    # "LV n" on the HUD plate (LevelLabel) uses the same 3x5 cell
    "L": ["#..", "#..", "#..", "#..", "###"],
    "V": ["#.#", "#.#", "#.#", ".#.", ".#."],
}
SMALL_SPACE_ADVANCE = 3           # "LV 12": a 2 px clear gap between the word and the number

DAMAGE_DIGITS: dict[str, list[str]] = {
    "0": [".###.", "##.##", "##.##", "##.##", "##.##", "##.##", ".###."],
    "1": ["..##.", ".###.", "..##.", "..##.", "..##.", "..##.", ".####"],
    "2": [".###.", "##.##", "...##", "..##.", ".##..", "##...", "#####"],
    "3": ["####.", "...##", "...##", ".###.", "...##", "...##", "####."],
    "4": ["...##", "..###", ".#.##", "#..##", "#####", "...##", "...##"],
    "5": ["#####", "##...", "####.", "...##", "...##", "##.##", ".###."],
    "6": [".###.", "##...", "##...", "####.", "##.##", "##.##", ".###."],
    "7": ["#####", "...##", "..##.", "..##.", ".##..", ".##..", ".##.."],
    "8": [".###.", "##.##", "##.##", ".###.", "##.##", "##.##", ".###."],
    "9": [".###.", "##.##", "##.##", ".####", "...##", "...##", ".###."],
    "-": [".....", ".....", ".....", "####.", ".....", ".....", "....."],
    "+": [".....", "..#..", "..#..", "#####", "..#..", "..#..", "....."],
}
DAMAGE_TOP: RGB = (255, 255, 255)
DAMAGE_BOTTOM: RGB = COLORS["dmg_enemy_edge"]     # (255, 236, 150)
DAMAGE_MID: RGB = (255, 248, 206)
DAMAGE_OUTLINE: RGB = (30, 8, 22)


def _outlined_glyph(char: str, rows: list[str], bands: Sequence[RGB], outline_rgb: RGB,
                    advance: int, diagonal: bool = True, bevel: RGB | None = None) -> Glyph:
    """Glyph with a 1 px outline and a per-row fill gradient. `bevel` adds a
    1 px shaded side to the right of every stroke (inside the outline), which
    gives thin digits an engraved, metallic weight."""
    m = _mask(rows)
    h, w = m.shape
    extra = 1 if bevel is not None else 0
    pad = np.zeros((h + 2, w + 2 + extra), bool)
    pad[1:-1, 1:w + 1] = m
    shade = np.zeros_like(pad)
    if bevel is not None:
        shade[:, 1:] = pad[:, :-1]
        shade &= ~pad
    a = np.zeros((h + 2, w + 2 + extra, 4), np.uint8)
    _paint(a, _dilate(pad | shade, diagonal=diagonal), outline_rgb)
    if bevel is not None:
        _paint(a, shade, bevel)
    for r in range(h):
        row = np.zeros_like(pad)
        row[r + 1, 1:w + 1] = m[r]
        _paint(a, row, bands[min(r, len(bands) - 1)])
    return Glyph(char, _to_image(a), advance)


def build_digit_fonts() -> None:
    hp = [Glyph(" ", Image.new("RGBA", (1, 1), (0, 0, 0, 0)), HP_ADVANCE)]
    hp += [_outlined_glyph(c, r, HP_BANDS, GLYPH_OUTLINE, HP_ADVANCE, bevel=HP_BEVEL)
           for c, r in HP_DIGITS.items()]
    write_bmfont("nocturne_hp", "NocturneHP", 13, 13, 12, hp, page_width=64)

    small = [Glyph(" ", Image.new("RGBA", (1, 1), (0, 0, 0, 0)), SMALL_SPACE_ADVANCE)]
    small += [_outlined_glyph(c, r, [(255, 255, 255)], GLYPH_OUTLINE, 4) for c, r in SMALL_DIGITS.items()]
    write_bmfont("nocturne_small", "NocturneSmall", 7, 7, 6, small, page_width=64)

    dmg_bands = [DAMAGE_TOP, DAMAGE_TOP, DAMAGE_TOP, DAMAGE_MID, DAMAGE_MID, DAMAGE_BOTTOM, DAMAGE_BOTTOM]
    dmg = [Glyph(" ", Image.new("RGBA", (1, 1), (0, 0, 0, 0)), 4)]
    dmg += [_outlined_glyph(c, r, dmg_bands, DAMAGE_OUTLINE, 6) for c, r in DAMAGE_DIGITS.items()]
    write_bmfont("nocturne_damage", "NocturneDamage", 9, 9, 8, dmg, page_width=64)


# ===========================================================================
# Windows
# ===========================================================================
def _window_fill(w: int, h: int, alpha: int, *, offset: tuple[int, int] = (0, 0),
                 ramp: Sequence[RGB] = WINDOW, dither: bool = True) -> np.ndarray:
    t = np.tile(((np.arange(h) + 0.5) / h)[:, None], (1, w))
    idx = quantize_to_ramp(t, len(ramp), dither="bayer4" if dither else None, offset=offset)
    cols = np.array([_rgba(c, alpha) for c in ramp], np.uint8)
    return cols[idx]


def _corner_studs(a: np.ndarray) -> None:
    """Silver rivets just inside each corner of the border: a 2x2 head lit
    from the top-left, mirrored into every corner, plus a bright corner
    pixel on the border ring itself."""
    h, w = a.shape[:2]
    head = ((0, 0, STUD), (1, 0, BORDER_LIT), (0, 1, BORDER_LIT), (1, 1, BORDER_SHADE))
    for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        bx = 4 if sx > 0 else w - 5
        by = 4 if sy > 0 else h - 5
        for dx, dy, c in head:
            # keep the light top-left on every corner (do not mirror the shading)
            x = bx + (dx if sx > 0 else dx - 1)
            y = by + (dy if sy > 0 else dy - 1)
            a[y, x] = _rgba(c)
        cx = 1 if sx > 0 else w - 2
        cy = 1 if sy > 0 else h - 2
        a[cy, cx] = _rgba(STUD)


def _hairline(a: np.ndarray, y: int, x0: int, x1: int) -> None:
    """Ornamental divider: a shaded silver rule with dotted tips and a small
    lit diamond at its centre."""
    cx = (x0 + x1) // 2
    for x in range(x0 + 4, x1 - 3):
        a[y, x] = _rgba(BORDER_SHADE)
        a[y + 1, x] = _rgba(BORDER_OUTER)
    for x in (x0, x0 + 2, x1 - 2, x1):
        a[y, x] = _rgba(BORDER_SHADE)
    for x in range(cx - 8, cx + 9):
        a[y, x] = _rgba(BORDER_LIT)
    for dx, dy, c in ((0, -2, BORDER_LIT), (-1, -1, BORDER_LIT), (0, -1, STUD), (1, -1, BORDER_LIT),
                      (-2, 0, BORDER_LIT), (-1, 0, STUD), (0, 0, STUD), (1, 0, BORDER_LIT), (2, 0, BORDER_SHADE),
                      (-1, 1, BORDER_LIT), (0, 1, BORDER_SHADE), (1, 1, BORDER_SHADE), (0, 2, BORDER_SHADE)):
        a[y + dy, cx + dx] = _rgba(c)


def window(w: int, h: int, *, alpha: int = WINDOW_ALPHA, dividers: Sequence[tuple[int, int, int]] = (),
           studs: bool = False, offset: tuple[int, int] = (0, 0), dither: bool = True) -> Image.Image:
    """A SotN-style menu window at its exact size.

    Rings from the outside: 1 px dark line (4,4,20), 1 px silver border
    (lit top/left, shaded bottom/right), 1 px dark seat, then the dithered
    5-band navy gradient. Corners are square and plain, as in SotN (see
    docs/art_style.md, UI windows); `studs` adds the area banner's corner
    rivets for anything that wants them. `dividers` are (y, x0, x1)
    ornamental rules.
    `offset` anchors the dither to screen space (pass the window's screen
    position so neighbouring windows share one pattern)."""
    a = np.zeros((h, w, 4), np.uint8)
    a[:] = _window_fill(w, h, alpha, offset=offset, dither=dither)
    a[0, :] = a[-1, :] = a[:, 0] = a[:, -1] = _rgba(BORDER_OUTER)
    a[1, 1:-1] = _rgba(BORDER_LIT)
    a[1:-1, 1] = _rgba(BORDER_LIT)
    a[-2, 1:-1] = _rgba(BORDER_SHADE)
    a[1:-1, -2] = _rgba(BORDER_SHADE)
    a[-2, 1] = a[1, -2] = _rgba(mix(BORDER_LIT, BORDER_SHADE, 0.5))
    a[2, 2:-2] = a[-3, 2:-2] = _rgba(BORDER_INNER)
    a[2:-2, 2] = a[2:-2, -3] = _rgba(BORDER_INNER)
    # Square corners with the outer line stepped in by one: reads crisper.
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        a[y, x] = (0, 0, 0, 0)
    if studs and w >= 16 and h >= 14:
        _corner_studs(a)
    for y, x0, x1 in dividers:
        _hairline(a, y, x0, x1)
    return _to_image(a)


# Every window the scenes draw, at its exact size and screen position.
# Keep in sync with the NinePatchRect rects in scenes/ui/*.tscn (a rect
# that equals its texture is drawn 1:1; anything else stretches).
@dataclass(frozen=True)
class WindowSpec:
    name: str
    x: int
    y: int
    w: int
    h: int
    dividers: tuple[tuple[int, int, int], ...] = ()
    alpha: int = WINDOW_ALPHA


WINDOWS: tuple[WindowSpec, ...] = (
    # pause_menu.tscn: tab strip, main page, info box (three stacked windows)
    WindowSpec("window_tabs", 20, 4, 344, 18),
    WindowSpec("window_main", 20, 24, 344, 108),
    WindowSpec("window_info", 20, 134, 344, 56),
    # save_menu.tscn
    WindowSpec("window_save", 52, 40, 280, 136, dividers=((25, 16, 263),)),
    # title_menu.tscn: the option list
    WindowSpec("window_title", 92, 70, 200, 80, alpha=236),
)


def build_menu_ui() -> None:
    for spec in WINDOWS:
        img = window(spec.w, spec.h, alpha=spec.alpha, dividers=spec.dividers, offset=(spec.x, spec.y))
        img.save(os.path.join(UI, f"{spec.name}.png"))
    # Generic nine-patch (patch margins 6): undithered bands so stretching
    # cannot smear a pattern; the 36 px centre holds bands 1-3.
    window(48, 48, dither=False).save(os.path.join(UI, "menu_frame.png"))
    build_cursor()
    build_marker()


# ---------------------------------------------------------------------------
# Cursor and equipped marker
# ---------------------------------------------------------------------------
def _sprite_from(rows: Sequence[str], legend: dict[str, Sequence[int]]) -> Image.Image:
    h, w = len(rows), len(rows[0])
    a = np.zeros((h, w, 4), np.uint8)
    for y, r in enumerate(rows):
        for x, ch in enumerate(r):
            if ch in legend:
                a[y, x] = _rgba(legend[ch])
    return _to_image(a)


def build_cursor() -> None:
    """7x9 crimson shard pointing at the selected row: a faceted gem with a
    lit upper facet, a darker lower facet, a hot specular and a tinted rim
    (crimson C1, which still reads against the navy window)."""
    rows = [
        "oo.....",
        "ohoo...",
        "olhhoo.",
        "ollhwho",
        "ommmmmo",
        "odddmo.",
        "odddo..",
        "odoo...",
        "oo.....",
    ]
    legend = {"o": CRIMSON[1], "d": CRIMSON[3], "m": CRIMSON[4], "l": CRIMSON[5],
              "h": COLORS["crimson_sheen"], "w": (255, 220, 224)}
    _sprite_from(rows, legend).save(os.path.join(UI, "cursor.png"))


def build_marker() -> None:
    """7x7 'equipped' jewel: a gold-set diamond with a white glint."""
    rows = [
        "...o...",
        "..oho..",
        ".ohwmo.",
        "ohmmmdo",
        ".omddo.",
        "..odo..",
        "...o...",
    ]
    legend = {"o": GOLD[0], "d": GOLD[2], "m": GOLD[3], "h": GOLD[4], "w": GOLD[5]}
    _sprite_from(rows, legend).save(os.path.join(UI, "marker_equipped.png"))


# ===========================================================================
# HUD
# ===========================================================================
# Frame-local layout (hud_frame.png is drawn at screen (2, 2) by hud.tscn;
# the child rects in hud.tscn use these same frame-local numbers). The HUD is
# SotN's compact top-left cluster: medallion, HP number, HP and MP gauges,
# hearts and a small "LV n". NEXT and gold are not on it: they live in a
# top-right ledger (the notice plate) that hud.gd fades in only when they change.
HUD_W, HUD_H = 132, 34
ORB_C = (17.0, 17.0)          # centre of the 32 px medallion (pixels 1..32)
ORB_R = 16.0                  # outer radius (outline sits outside it)
ORB_GOLD_IN = 14.6            # outer gold rim: ORB_GOLD_IN .. ORB_R
ORB_STEEL_IN = 11.4           # gunmetal ring: ORB_STEEL_IN .. ORB_GOLD_IN
ORB_GLASS = 10.4              # inner gold rim: ORB_GLASS .. ORB_STEEL_IN; glass inside
SPIKE_R = (12.5, 20.5)        # diagonal crest spikes behind the medallion
PLATE_X0, PLATE_X1 = 26, 116  # bar plate (behind the medallion's right half)
PLATE_Y0, PLATE_Y1 = 6, 27
HP_DIGITS_RECT = (34, 9, 63, 22)    # HPLabel (x0, y0, x1, y1), font nocturne_hp
HP_GAUGE_RECT = (36, 22, 60, 24)    # HPBar, bar_hp.png 24x2
HEART_ICON_POS = (67, 10)           # heart_icon.png 9x8
HEARTS_RECT = (77, 11, 93, 18)      # HeartsLabel, font nocturne_small
LEVEL_RECT = (90, 11, 114, 18)      # LevelLabel "LV n", font nocturne_small, right-aligned
MP_GAUGE_RECT = (67, 21, 113, 24)   # MPBar, bar_mp.png 46x3
LIGHT_2D = (LIGHT_ENV[0], LIGHT_ENV[1])


def _gold_by_facing(nx: float, ny: float) -> RGB:
    """Gold tone for a surface whose screen-space normal is (nx, ny), lit
    from the top-left."""
    lit = -(nx * LIGHT_2D[0] + ny * LIGHT_2D[1])
    if lit > 0.45:
        return GOLD[4]
    if lit > 0.0:
        return GOLD[3]
    if lit > -0.45:
        return GOLD[2]
    return GOLD[1]


def _hud_spikes(a: np.ndarray) -> None:
    """Four pyramidal gold crest points on the diagonals, drawn first so the
    plate and the medallion overlap them."""
    cx, cy = ORB_C
    r0, r1 = SPIKE_R
    for ang in (45.0, 135.0, 225.0, 315.0):
        phi = math.radians(ang)
        ux, uy = math.cos(phi), math.sin(phi)
        for y in range(HUD_H):
            for x in range(HUD_W):
                dx, dy = x + 0.5 - cx, y + 0.5 - cy
                along = dx * ux + dy * uy
                across = -dx * uy + dy * ux
                if not (r0 <= along <= r1):
                    continue
                half = 3.4 * (r1 - along) / (r1 - r0)
                if abs(across) > half:
                    continue
                side = 1.0 if across >= 0 else -1.0
                nx, ny = -uy * side * 0.8 + ux * 0.6, ux * side * 0.8 + uy * 0.6
                c = GOLD[5] if abs(across) < 0.5 and along > r1 - 3 else _gold_by_facing(nx, ny)
                a[y, x] = _rgba(c)


def _plate_row(y: int, y0: int, y1: int) -> RGB:
    """One row of the gunmetal plate (rows y0..y1): a lit gold top rail,
    two steel rows, dark indigo glass in 3 tones, two steel rows and a
    shaded gold bottom rail."""
    if y == y0:
        return GOLD[4]
    if y == y1:
        return GOLD[2]
    if y == y0 + 1:
        return STEEL[3]
    if y == y0 + 2:
        return STEEL[1]
    if y == y1 - 1:
        return STEEL[0]
    if y == y1 - 2:
        return STEEL[1]
    t = (y - (y0 + 3)) / max(1, (y1 - 3) - (y0 + 3))
    return WINDOW[0] if t < 0.3 else (WINDOW[1] if t < 0.68 else WINDOW[2])


def _hud_plate(a: np.ndarray) -> None:
    for x in range(PLATE_X0, PLATE_X1 + 1):
        for y in range(PLATE_Y0, PLATE_Y1 + 1):
            a[y, x] = _rgba(_plate_row(y, PLATE_Y0, PLATE_Y1))
    # rivets on the top rail every 8 px, catching the light
    for x in range(38, PLATE_X1 - 3, 8):
        a[PLATE_Y0, x] = _rgba(GOLD[5])
    # gothic lace under the bottom rail: small pendant drops
    for x in range(38, PLATE_X1 - 5, 12):
        a[PLATE_Y1 + 1, x - 1:x + 2] = _rgba(GOLD[2])
        a[PLATE_Y1 + 2, x] = _rgba(GOLD[1])
    # sunken wells for the HP and MP gauges (1 px dark seat, lit lower lip)
    for (x0, y0, x1, y1), fill in ((HP_GAUGE_RECT, (22, 4, 14)), (MP_GAUGE_RECT, (6, 8, 30))):
        a[y0 - 1:y1 + 1, x0 - 1:x1 + 1] = _rgba(BORDER_OUTER)
        a[y0:y1, x0:x1] = _rgba(fill)
        a[y1, x0:x1 + 1] = _rgba(STEEL[1])
    _hud_end_cap(a)


NOTICE_W, NOTICE_H = 24, 14


def build_notice_plate() -> None:
    """notice_plate.png: a small window for the HUD's one-line notices
    (weapon swaps, pickups, level-ups, saves), drawn by a StyleBoxTexture
    with 4 px margins. The ring matches the menu windows (outer dark line,
    silver border lit top/left, dark seat); the centre is one flat,
    undithered window tone so it stretches cleanly to any text width."""
    w, h = NOTICE_W, NOTICE_H
    a = np.zeros((h, w, 4), np.uint8)
    a[:] = _rgba(WINDOW[1], 224)
    a[0, :] = a[-1, :] = a[:, 0] = a[:, -1] = _rgba(BORDER_OUTER)
    a[1, 1:-1] = _rgba(BORDER_LIT)
    a[1:-1, 1] = _rgba(BORDER_LIT)
    a[-2, 1:-1] = _rgba(BORDER_SHADE)
    a[1:-1, -2] = _rgba(BORDER_SHADE)
    a[-2, 1] = a[1, -2] = _rgba(mix(BORDER_LIT, BORDER_SHADE, 0.5))
    a[2, 2:-2] = a[-3, 2:-2] = _rgba(BORDER_INNER)
    a[2:-2, 2] = a[2:-2, -3] = _rgba(BORDER_INNER)
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        a[y, x] = (0, 0, 0, 0)
    _to_image(a).save(os.path.join(UI, "notice_plate.png"))


def _hud_end_cap(a: np.ndarray) -> None:
    """A gold bar closing the plate, and a gothic trefoil finial beyond it."""
    x0 = PLATE_X1 + 1
    for y in range(PLATE_Y0 - 3, PLATE_Y1 + 4):
        a[y, x0] = _rgba(GOLD[4])
        a[y, x0 + 1] = _rgba(GOLD[3])
        a[y, x0 + 2] = _rgba(GOLD[1])
    for y in (PLATE_Y0 - 4, PLATE_Y1 + 4):
        a[y, x0 + 1] = _rgba(GOLD[3] if y < PLATE_Y0 else GOLD[1])
    cy = (PLATE_Y0 + PLATE_Y1 + 1) / 2.0
    lobes = ((x0 + 8.0, cy, 2.7), (x0 + 5.0, cy - 4.6, 2.2), (x0 + 5.0, cy + 4.6, 2.2))
    for y in range(HUD_H):
        for x in range(x0 + 3, HUD_W - 1):
            px_, py_ = x + 0.5, y + 0.5
            hit = None
            for lx, ly, lr in lobes:
                d = math.hypot(px_ - lx, py_ - ly)
                if d <= lr:
                    hit = ((px_ - lx) / lr, (py_ - ly) / lr)
                    break
            if hit is None and x <= x0 + 5 and abs(py_ - cy) <= 1.0:
                hit = (0.0, (py_ - cy))                     # stem
            if hit is None and x0 + 10 <= x <= x0 + 12 and abs(py_ - cy) <= (x0 + 12.5 - px_) * 0.7:
                hit = (0.6, (py_ - cy) * 0.6)               # spear tip
            if hit is None:
                continue
            nx, ny = hit
            nz = math.sqrt(max(0.0, 1.0 - min(1.0, nx * nx + ny * ny)))
            lit = -(nx * LIGHT_2D[0] + ny * LIGHT_2D[1]) + 0.5 * nz
            c = GOLD[5] if lit > 0.95 else GOLD[4] if lit > 0.55 else GOLD[3] if lit > 0.15 else GOLD[2]
            a[y, x] = _rgba(c)


def _hud_orb(a: np.ndarray) -> None:
    cx, cy = ORB_C
    yy, xx = np.mgrid[0:HUD_H, 0:HUD_W].astype(np.float64)
    dx, dy = xx + 0.5 - cx, yy + 0.5 - cy
    r = np.hypot(dx, dy)
    ux, uy = dx / np.maximum(r, 1e-6), dy / np.maximum(r, 1e-6)

    def ring_lit(r0: float, r1: float, convex: bool = True) -> np.ndarray:
        """Torus-section shading: a dome across the ring width (or a groove
        if not convex), lit by the fixed top-left environment light."""
        t = np.clip((r - r0) / (r1 - r0), 0.0, 1.0)
        slope = -np.cos(np.pi * t) * (1.0 if convex else -1.0)
        nz = np.sin(np.pi * t) * 0.9 + 0.3
        nx, ny = ux * slope, uy * slope
        n = np.sqrt(nx * nx + ny * ny + nz * nz)
        return shade_normals(nx / n, ny / n, nz / n, LIGHT_ENV, ambient=0.12, gamma=1.0, rim=0.0)

    def band(lit: np.ndarray, cuts: Sequence[float], tones: Sequence[int]) -> np.ndarray:
        return np.array(tones)[np.searchsorted(np.asarray(cuts), lit)]

    out_gold = (r >= ORB_GOLD_IN) & (r < ORB_R)
    steel = (r >= ORB_STEEL_IN) & (r < ORB_GOLD_IN)
    in_gold = (r >= ORB_GLASS) & (r < ORB_STEEL_IN)
    glass = r < ORB_GLASS
    gold_out_idx = band(ring_lit(ORB_GOLD_IN, ORB_R), (0.3, 0.55, 0.8), (1, 2, 3, 4))
    steel_idx = band(ring_lit(ORB_STEEL_IN, ORB_GOLD_IN), (0.3, 0.52, 0.72, 0.9), (0, 1, 2, 3, 4))
    # inner rim: the lip of a recess, lit on the lower right (light falls in)
    lit_in = -(ux * LIGHT_2D[0] + uy * LIGHT_2D[1])
    gold_in_idx = np.where(lit_in < -0.35, 4, np.where(lit_in < 0.3, 3, 1))
    for mask, ramp, idx in ((out_gold, GOLD, gold_out_idx), (steel, STEEL, steel_idx),
                            (in_gold, GOLD, gold_in_idx)):
        ys, xs = np.nonzero(mask)
        for y, x in zip(ys, xs):
            a[y, x] = _rgba(ramp[int(idx[y, x])])
    # specular glint on the steel at the upper left
    for gx, gy in ((7, 6), (6, 7), (8, 5)):
        if steel[gy, gx]:
            a[gy, gx] = _rgba(STEEL[5])
    # glass: deep indigo, 3-band vertical gradient, darker under the rim
    g = (yy + 0.5 - (cy - ORB_GLASS)) / (2 * ORB_GLASS)
    glass_cols = [(8, 8, 30), (14, 14, 46), (22, 22, 64), (30, 30, 84)]
    gi = np.clip((g * 3.2).astype(int), 0, 3)
    gi = np.where(r > ORB_GLASS - 1.2, np.maximum(gi - 1, 0), gi)   # inner shadow ring
    ys, xs = np.nonzero(glass)
    for y, x in zip(ys, xs):
        a[y, x] = _rgba(glass_cols[int(gi[y, x])])
    # 2x2 glass highlight at upper-left, plus a 1 px glint
    hx, hy = int(cx - 6), int(cy - 7)
    a[hy:hy + 2, hx:hx + 2] = _rgba((70, 76, 140))
    a[hy, hx] = _rgba((150, 160, 206))
    # four gold studs on the steel ring (N, E, S, W)
    sr = (ORB_STEEL_IN + ORB_GOLD_IN) / 2.0
    for ang in (-90.0, 0.0, 90.0, 180.0):
        x0 = int(math.floor(cx + math.cos(math.radians(ang)) * sr - 0.5))
        y0 = int(math.floor(cy + math.sin(math.radians(ang)) * sr - 0.5))
        a[y0, x0] = _rgba(GOLD[5])
        a[y0, x0 + 1] = _rgba(GOLD[3])
        a[y0 + 1, x0] = _rgba(GOLD[3])
        a[y0 + 1, x0 + 1] = _rgba(GOLD[1])


def _outline_rgba(a: np.ndarray, color: RGB, diagonal: bool = False) -> None:
    solid = a[:, :, 3] > 0
    ring = _dilate(solid, diagonal=diagonal) & ~solid
    a[ring] = _rgba(color)


def build_hud() -> None:
    a = np.zeros((HUD_H, HUD_W, 4), np.uint8)
    _hud_spikes(a)
    _hud_plate(a)
    _hud_orb(a)
    # keep a free 1 px border so the outline fits inside the canvas
    a[:, HUD_W - 1] = 0
    a[0, :] = a[HUD_H - 1, :] = 0
    a[:, 0] = 0
    _outline_rgba(a, VOID_OUTLINE)
    _to_image(a).save(os.path.join(UI, "hud_frame.png"))

    # HP gauge: a slim crimson line under the HP digits (2 rows).
    hp_w, hp_h = HP_GAUGE_RECT[2] - HP_GAUGE_RECT[0], HP_GAUGE_RECT[3] - HP_GAUGE_RECT[1]
    hp = np.zeros((hp_h, hp_w, 4), np.uint8)
    hp[0] = _rgba(CRIMSON[5])
    hp[1] = _rgba(CRIMSON[3])
    hp[:, hp_w - 1] = _rgba(COLORS["crimson_sheen"])   # bright leading edge
    _to_image(hp).save(os.path.join(UI, "bar_hp.png"))
    # MP gauge: light top row, mid row, dark bottom row (MANA ramp).
    mp_w, mp_h = MP_GAUGE_RECT[2] - MP_GAUGE_RECT[0], MP_GAUGE_RECT[3] - MP_GAUGE_RECT[1]
    mp = np.zeros((mp_h, mp_w, 4), np.uint8)
    mp[0] = _rgba(MANA[2])
    mp[1:mp_h - 1] = _rgba(MANA[1])
    mp[mp_h - 1] = _rgba((24, 52, 160))
    mp[:, mp_w - 1] = _rgba(MANA[3])            # bright leading edge
    _to_image(mp).save(os.path.join(UI, "bar_mp.png"))

    build_heart_icon()
    build_notice_plate()



def build_heart_icon() -> None:
    """9x8 heart: 7x6 body in the HEART ramp, lit upper-left, with a
    tinted sel-out rim (darkest heart tone, never black)."""
    rows = [
        ".ooo.ooo.",
        "ohlmomddo",
        "olmmmmddo",
        "ommmmddoo",
        ".omdddoo.",
        "..oddoo..",
        "...odo...",
        "....o....",
    ]
    legend = {"o": HEART_R[0], "d": HEART_R[1], "m": HEART_R[2], "l": HEART_R[3],
              "h": (255, 220, 224)}
    _sprite_from(rows, legend).save(os.path.join(UI, "heart_icon.png"))


# ===========================================================================
# Area-name banner (AreaTitle's StyleBoxTexture) and title backdrop
# ===========================================================================
BANNER_W, BANNER_H = 232, 44


def build_area_banner() -> None:
    """232x44 box: dithered vertical gradient from (24,10,22) to (10,6,48)
    at ~60% alpha, a silver border and two fading hairlines framing the
    title-font text."""
    ramp = [(24, 10, 22), (20, 8, 30), (16, 8, 38), (12, 6, 44), (10, 6, 48)]
    a = np.zeros((BANNER_H, BANNER_W, 4), np.uint8)
    a[:] = _window_fill(BANNER_W, BANNER_H, 156, ramp=ramp)
    a[0, :] = a[-1, :] = a[:, 0] = a[:, -1] = _rgba(BORDER_OUTER, 200)
    a[1, 1:-1] = a[1:-1, 1] = _rgba(BORDER_LIT)
    a[-2, 1:-1] = a[1:-1, -2] = _rgba(BORDER_SHADE)
    for x, y in ((0, 0), (BANNER_W - 1, 0), (0, BANNER_H - 1), (BANNER_W - 1, BANNER_H - 1)):
        a[y, x] = (0, 0, 0, 0)
    _corner_studs(a)
    _hairline(a, 7, 24, BANNER_W - 25)
    _hairline(a, BANNER_H - 8, 24, BANNER_W - 25)
    _to_image(a).save(os.path.join(UI, "area_banner.png"))


SCREEN_W, SCREEN_H = 384, 216
MOON = (322.0, 70.0, 24.0)            # centre x, y, radius on the title screen
TITLE_DIVIDER_Y = 45                  # ornament under the baked "CRIMSON NOCTURNE" logo (y 24..37)


@dataclass(frozen=True)
class Tower:
    cx: int
    half: int          # half width of the shaft's top stage (it steps out 1 px every SETBACK_ROWS down)
    top: int           # screen y where the roof starts
    roof: int          # spire height


# Near massing, composed toward the moon: the option window hides x 92-292,
# y 70-150, so the silhouette that reads is either side of it. A tall keep
# whose spire crosses the moon disc, two flanking turrets, a gate tower tied
# to the right turret by an arcaded bridge, and a small pair on the left crag.
NEAR_TOWERS: tuple[Tower, ...] = (
    Tower(44, 9, 126, 32), Tower(72, 5, 146, 18),
    Tower(236, 6, 136, 20),
    Tower(292, 7, 118, 28), Tower(318, 11, 96, 44), Tower(350, 6, 110, 26),
)
# Far plane: thin spires in one flat, cooler tone with no rim, standing in the
# horizon glow behind the ridge, so the gaps in the near massing read as
# depth. They sit in the strip between the option window's bottom edge and
# the crag, so their roofs and finials show (build_title_backdrop checks it).
FAR_SPIRES: tuple[Tower, ...] = (
    Tower(124, 3, 172, 16), Tower(150, 4, 182, 26), Tower(178, 3, 180, 16), Tower(206, 4, 182, 28),
)
TITLE_WINDOW_BOTTOM = 150          # first screen row under window_title (y 70 + 80)
FAR_SPIRE_RGB: RGB = (30, 26, 54)
# Short curtain walls between paired towers (x0, x1, top y), merlons 2 on / 2 off.
WALL_RUNS: tuple[tuple[int, int, int], ...] = ((53, 67, 150), (299, 307, 130), (329, 344, 124))
BRIDGE = (242, 286, 152)           # arcaded bridge, gate tower -> right turret: x0, x1, deck y
# (the deck sits just under the option window, so the whole arcade shows)
# Crag top: a base profile (low in the middle, under the option window, rising
# under the keep and a little on the left) plus seeded 1-D fbm, 6 px amplitude.
CRAG_PROFILE: tuple[tuple[float, float], ...] = (
    (0.0, 166.0), (20.0, 165.0), (110.0, 170.0), (150.0, 184.0), (230.0, 184.0), (262.0, 172.0),
    (280.0, 151.0), (360.0, 150.0), (384.0, 155.0))
CRAG_SEED = 41
CRAG_LEDGE_GAPS = (6, 5, 7, 6, 5, 7, 6, 5)   # rows between strata ledges, from the crag top down
LEDGE_MAX_RUN = 8                  # strata break at least every 8 px: rock beds, not ruled lines
SETBACK_ROWS = 18
# The 1 px moon rim is drawn as short ticks, not a continuous outline (a
# continuous rim on a stepped diagonal reads as a wireframe). Each edge is
# walked from its top (or, for the crag lip, its moon-ward end): RIM_ON px lit,
# then a gap of RIM_GAP px, doubled beyond RIM_NEAR px from the moon centre.
RIM_SEED = 13
RIM_ON = (2, 4)                    # inclusive px range of one rim tick
RIM_GAP = (3, 6)                   # inclusive px range between ticks near the moon
RIM_NEAR = 80.0
# A crag-lip pixel takes the rim only where the lip faces the moon (its normal
# within ~18 degrees of the moon direction); elsewhere near the moon it is lit stone.
RIM_LIP_FACING = 0.95
GROUND_Y = 196                     # foot of the frame's column shafts


def _crag_top(w: int) -> np.ndarray:
    xs = [p[0] for p in CRAG_PROFILE]
    ys = [p[1] for p in CRAG_PROFILE]
    base = np.interp(np.arange(w) + 0.5, xs, ys)
    n = fbm(w, 4, octaves=3, cell=14.0, seed=CRAG_SEED, tileable=False)[0]
    n = n - n.mean()
    n = n / (float(np.abs(n).max()) or 1.0)
    return np.round(base + 6.0 * n).astype(int)


def _concave_hw(t: Tower, k: int) -> float:
    """Half width of a concave (flared) spire `k` rows above its base."""
    return (t.half + 1.5) * (1.0 - k / t.roof) ** 1.35


def _spire_rows(t: Tower) -> list[tuple[int, int, int]]:
    """(y, x0, x1) rows of a tower's spire, base to tip, plus its finial."""
    rows = []
    for k in range(t.roof):
        hw = _concave_hw(t, k)
        x0 = int(math.floor(t.cx - hw + 0.5))
        x1 = int(math.floor(t.cx + hw + 0.5))
        if x1 < x0:
            x0 = x1 = t.cx
        rows.append((t.top - 1 - k, x0, x1))
    tip = t.top - t.roof
    rows += [(tip - 1, t.cx, t.cx), (tip - 2, t.cx - 1, t.cx + 1), (tip - 3, t.cx, t.cx), (tip - 4, t.cx, t.cx)]
    return rows


def _shaft_half(t: Tower, y: int) -> int:
    return t.half + max(0, y - t.top) // SETBACK_ROWS


def _rim_ticks(a: np.ndarray, chains: Sequence[Sequence[tuple[int, int]]], rim: RGB,
               rng: np.random.Generator) -> None:
    """Light each ordered chain of edge pixels (x, y) in short rim ticks,
    starting with a tick at the chain's first pixel."""
    lo_on, hi_on = RIM_ON
    lo_gap, hi_gap = RIM_GAP
    for chain in chains:
        on = True
        left = int(rng.integers(lo_on, hi_on + 1))
        for x, y in chain:
            if on:
                a[y, x] = _rgba(rim)
            left -= 1
            if left > 0:
                continue
            on = not on
            if on:
                left = int(rng.integers(lo_on, hi_on + 1))
            else:
                far_k = 1 if math.hypot(x + 0.5 - MOON[0], y + 0.5 - MOON[1]) < RIM_NEAR else 2
                left = far_k * int(rng.integers(lo_gap, hi_gap + 1))


def _edge_chains(cand: np.ndarray) -> list[list[tuple[int, int]]]:
    """Group moon-facing edge pixels into edges, each ordered top to bottom.
    A rim candidate has an open moon-ward neighbour, so an edge holds one
    pixel per row; a flared spire steps out more than 1 px a row, so the
    grouping bridges 2 px sideways."""
    bridged = binary_dilation(cand, structure=np.ones((1, 5), bool))
    lab, n = label(bridged, structure=np.ones((3, 3), int))
    chains: list[list[tuple[int, int]]] = []
    for k in range(1, n + 1):
        ys, xs = np.nonzero((lab == k) & cand)
        order = np.lexsort((xs, ys))
        chains.append([(int(xs[i]), int(ys[i])) for i in order])
    return chains


def _castle(a: np.ndarray) -> None:
    """Distant castle on a crag, in STONE_FAR: a far plane of thin flat spires
    in the horizon glow; a near massing of towers with setbacks, corbel rows,
    flared spires and finials, short merloned walls and an arcaded bridge,
    lit by the moon on the outer 2 px of the side that faces it, broken 1 px
    moon-rim ticks along that edge; slit windows, some lit; and the crag itself, its strata
    ledges catching the moon on the right."""
    H, W = a.shape[:2]
    far = RAMPS["stone_far"]
    rim = COLORS["moon_rim"]
    mx = MOON[0]
    crag = _crag_top(W)

    # 1. far plane: flat, cooler, no rim
    for t in FAR_SPIRES:
        a[t.top:crag[t.cx] + 2, t.cx - t.half:t.cx + t.half + 1] = _rgba(FAR_SPIRE_RGB)
        for y, x0, x1 in _spire_rows(t):
            a[y, x0:x1 + 1] = _rgba(FAR_SPIRE_RGB)

    # 2. near massing: masks first, so lighting can test the whole silhouette
    near = np.zeros((H, W), bool)
    roofs = np.zeros((H, W), bool)
    for t in NEAR_TOWERS:
        for y in range(t.top, H):
            hw = _shaft_half(t, y)
            near[y, t.cx - hw:t.cx + hw + 1] = True
        near[t.top + 2, t.cx - t.half - 1:t.cx + t.half + 2] = True      # corbel row
        for y, x0, x1 in _spire_rows(t):
            roofs[y, x0:x1 + 1] = True
    for x0, x1, top in WALL_RUNS:
        near[top:, x0:x1 + 1] = True
        for x in range(x0, x1 + 1):
            if ((x - x0) // 2) % 2 == 0:
                near[top - 2:top, x] = True
    bx0, bx1, deck = BRIDGE
    near[deck:deck + 4, bx0:bx1 + 1] = True
    arch_open = np.zeros((H, W), bool)          # sky seen through the bridge's arches
    for ax in range(bx0 + 2, bx1 - 3, 8):
        for y in range(deck + 4, H):
            for x in range(ax, min(ax + 6, bx1 + 1)):
                dy = deck + 7 - y - 0.5
                in_arch = y >= deck + 7 or abs(x + 0.5 - (ax + 3)) < math.sqrt(max(0.0, 9.0 - dy * dy))
                if not in_arch:
                    near[y, x] = True
                else:
                    arch_open[y, x] = True
        near[deck + 4:, ax + 6:ax + 8] = True
    arch_open &= ~near
    sil = near | roofs
    a[near] = _rgba(far[1])
    a[roofs] = _rgba(far[0])

    # moonlight: the outer 2 px on the side facing the moon, per tower
    for t in NEAR_TOWERS:
        both = abs(t.cx - mx) <= t.half + 4          # backlit, right in front of the disc
        sides = (-1, 1) if both else ((1,) if t.cx < mx else (-1,))
        for side in sides:
            for y in range(t.top, H):
                hw = _shaft_half(t, y) + (1 if y == t.top + 2 else 0)
                for d in (0, 1):
                    x = t.cx + side * (hw - d)
                    if 0 <= x < W and near[y, x]:
                        a[y, x] = _rgba(far[2])
            for y, x0, x1 in _spire_rows(t):
                edge = x1 if side > 0 else x0
                for d in (0, 1):
                    x = edge - side * d
                    if (x - t.cx) * side >= 0 and roofs[y, x]:
                        a[y, x] = _rgba(far[2])
        # the corbel row and each setback step catch the light along their tops
        a[t.top + 2, t.cx - t.half - 1:t.cx + t.half + 2] = _rgba(far[2])
    rim_cand = np.zeros((H, W), bool)
    for y in range(1, H):
        for x in range(1, W - 1):
            if not sil[y, x]:
                continue
            toward = 1 if x < mx else -1
            if arch_open[y, x + toward]:
                a[y, x] = _rgba(far[2])              # pier faces inside the arcade: dim, not rimmed
            elif not sil[y, x + toward] and abs(x - mx) < 150:
                a[y, x] = _rgba(far[2])              # moon-facing edge: lit, rim ticks below
                rim_cand[y, x] = True
            elif not sil[y - 1, x] and abs(x - mx) < 120:
                a[y, x] = _rgba(far[2])              # tops of walls, merlons, setbacks
    rng = np.random.default_rng(RIM_SEED)
    _rim_ticks(a, _edge_chains(rim_cand), rim, rng)
    # slit windows: 1x3 with a pointed (single-pixel) top; ~40% lit
    for t in NEAR_TOWERS:
        cols = [t.cx] if t.half < 7 else [t.cx - t.half // 2, t.cx + t.half // 2]
        for col in cols:
            for y in range(t.top + 7, crag[col] - 4, 13):
                h = (col * 73856093 ^ y * 19349663) & 0xFFFF
                if not (sil[y - 1, col] and sil[y + 3, col]):
                    continue
                if h % 100 < 40:
                    a[y, col] = _rgba(GOLD[4])
                    a[y + 1:y + 3, col] = _rgba(GOLD[3])
                else:
                    a[y:y + 3, col] = _rgba(far[0])

    # 3. the crag in front of every foot. Its strata run level (rock beds,
    # not contour lines): each ledge sits at a fixed height with a 1 px
    # low-frequency wobble, shows only where it is inside the rock, and is
    # broken into short runs. Ledges near the moon catch it.
    for x in range(W):
        a[crag[x]:, x] = _rgba(far[0])
    # Near the moon a ledge is lit (far[2]) and only its moon-facing 2 px
    # take the moon-rim tone; elsewhere it is a dim far[1] crease.
    breaks = fbm(W, len(CRAG_LEDGE_GAPS), octaves=2, cell=9.0, seed=CRAG_SEED + 1, tileable=False)
    wobble = fbm(W, len(CRAG_LEDGE_GAPS), octaves=1, cell=40.0, seed=CRAG_SEED + 2, tileable=False)
    level = int(crag.min()) + 2
    for i, gap in enumerate(CRAG_LEDGE_GAPS):
        level += gap
        runs: list[list[tuple[int, int]]] = []
        run: list[tuple[int, int]] = []
        for x in range(W):
            y = level + int(round((wobble[i, x] - 0.5) * 2.0))
            if not (crag[x] + 1 < y < H) or breaks[i, x] < 0.55 or len(run) >= LEDGE_MAX_RUN:
                if run:
                    runs.append(run)
                run = []
                continue
            run.append((x, y))
        if run:
            runs.append(run)
        for run in runs:
            mid_x = (run[0][0] + run[-1][0]) / 2.0
            facing = run[-2:] if mid_x < mx else run[:2]
            for x, y in run:
                near_moon = abs(x - mx) < 70 and y < 176
                c = far[2] if near_moon else far[1]
                # every other bed catches the moon on its facing end; the rest stay dim
                if near_moon and i % 2 == 0 and (x, y) in facing and len(run) >= 4:
                    c = rim
                a[y, x] = _rgba(c)
    # the crag's lip: lit near the moon, with rim ticks only on the stretches
    # that face it; a dim edge elsewhere
    my = MOON[1]
    lip_runs: list[list[tuple[int, int]]] = []
    run_lip: list[tuple[int, int]] = []
    for x in range(W):
        y = int(crag[x])
        near_moon = abs(x - mx) < 60
        a[y, x] = _rgba(far[2] if near_moon or x > 230 else far[1])
        slope = (float(crag[min(x + 1, W - 1)]) - float(crag[max(x - 1, 0)])) / 2.0
        nx, ny = slope, -1.0                         # outward normal of the rock below y = crag(x)
        lx, ly = mx - (x + 0.5), my - (y + 0.5)
        facing = (nx * lx + ny * ly) / (math.hypot(nx, ny) * math.hypot(lx, ly))
        if near_moon and facing > RIM_LIP_FACING:
            run_lip.append((x, y))
        elif run_lip:
            lip_runs.append(run_lip)
            run_lip = []
    if run_lip:
        lip_runs.append(run_lip)
    # walk each facing stretch from its moon-ward end
    _rim_ticks(a, [r if r[0][0] > mx else r[::-1] for r in lip_runs], rim, rng)


def _moon(a: np.ndarray) -> None:
    H, W = a.shape[:2]
    mcx, mcy, mr = MOON
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    d = np.hypot(xx + 0.5 - mcx, yy + 0.5 - mcy)
    # dithered halo, three rings, never darker than the sky behind it
    halo = np.clip(1.0 - (d - mr) / 36.0, 0, 1) ** 1.7
    halo_idx = quantize_to_ramp(halo, 4, dither="bayer4")
    halo_cols = [(0, 0, 0), (22, 18, 54), (32, 28, 72), (46, 42, 96)]
    for k in (1, 2, 3):
        m = (halo_idx == k) & (d >= mr)
        base = a[m][:, :3].astype(np.int32)
        a[m, :3] = np.maximum(base, np.array(halo_cols[k], np.int32)).astype(np.uint8)
    moon = RAMPS["moon"]
    disc = d < mr
    nx = (xx + 0.5 - mcx) / mr
    ny = (yy + 0.5 - mcy) / mr
    nz = np.sqrt(np.clip(1 - nx * nx - ny * ny, 0, 1))
    lit = np.clip(0.2 + 0.8 * (-0.5 * nx - 0.45 * ny + 0.74 * nz), 0, 1)
    # maria: a few soft ellipses (low-frequency, so they read as seas, not noise)
    maria = np.zeros_like(lit)
    for ex, ey, erx, ery in ((0.22, -0.3, 0.34, 0.2), (-0.34, 0.22, 0.26, 0.17), (0.36, 0.36, 0.16, 0.12),
                             (-0.1, -0.05, 0.12, 0.1)):
        e = ((nx - ex) / erx) ** 2 + ((ny - ey) / ery) ** 2
        maria = np.maximum(maria, np.clip(1.0 - e, 0, 1))
    lit = lit - 0.28 * (maria > 0.25)
    m_idx = quantize_to_ramp(lit, len(moon), thresholds=[0.3, 0.52, 0.76])
    a[disc] = np.array([_rgba(c) for c in moon], np.uint8)[m_idx][disc]
    # a few 2 px craters on the lit side
    for cxp, cyp in ((-0.5, 0.1), (-0.15, -0.55), (0.05, 0.62), (-0.62, -0.25)):
        x, y = int(mcx + cxp * mr), int(mcy + cyp * mr)
        a[y, x] = _rgba(moon[1])
        a[y, x + 1] = _rgba(moon[3])


def _clouds(a: np.ndarray) -> None:
    """Cloud strata drifting across the lower half of the moon: stretched
    fbm thresholded inside soft horizontal bands, two body tones and a
    moonlit upper rim near the moon (no dithering inside the shapes)."""
    H, W = a.shape[:2]
    cloud = RAMPS["cloud"]
    raw = fbm(W, H * 3, octaves=4, cell=36, seed=5)
    n = raw[np.arange(H) * 3][:, :W]                     # 3x vertical squash -> long strata
    yy = np.mgrid[0:H, 0:W][0].astype(np.float64)
    xx = np.mgrid[0:H, 0:W][1].astype(np.float64)
    env = (np.exp(-((yy - 84.0) / 8.0) ** 2) * np.clip((xx - 200.0) / 50.0, 0, 1)
           + 0.9 * np.exp(-((yy - 58.0) / 6.0) ** 2) * np.clip((170.0 - xx) / 60.0, 0, 1)
           + 0.8 * np.exp(-((yy - 116.0) / 6.0) ** 2))
    dens = n * env
    body = dens > 0.27
    core = dens > 0.36
    a[body] = _rgba(cloud[0])
    a[core] = _rgba(cloud[1])
    top = body & ~np.roll(body, 1, axis=0)
    near = np.hypot(xx - MOON[0], yy - MOON[1]) < MOON[2] + 40
    a[top & near] = _rgba(cloud[3])
    a[top & ~near] = _rgba(cloud[2])


def _sky(a: np.ndarray) -> None:
    H, W = a.shape[:2]
    yy = np.mgrid[0:H, 0:W][0].astype(np.float64)
    sky = RAMPS["sky"]
    t = np.clip((yy + 0.5) / 172.0, 0, 1)
    idx = quantize_to_ramp(t, len(sky), dither="bayer4")
    a[:] = np.array([_rgba(c) for c in sky], np.uint8)[idx]
    # crimson horizon glow, dithered in over the last band
    g = np.exp(-((yy - 176.0) / 20.0) ** 2)
    th = bayer(4, (H, W))
    glow = (g * 0.9 + (th - 0.5) * 0.5) > 0.5
    a[glow] = _rgba(COLORS["sky_glow"])
    rng = np.random.default_rng(1729)
    for _ in range(80):
        sx, sy = int(rng.integers(20, W - 20)), int(rng.integers(4, 130))
        bright = rng.random() < 0.22
        a[sy, sx] = _rgba(COLORS["star"] if bright else COLORS["star_dim"])


def _arch_opening(W: int, H: int, pier: int, spring: float, apex: float, c: float) -> np.ndarray:
    """Pointed arch from two elliptical arcs: each side is an ellipse whose
    centre sits `c` px beyond the centre line on the springing line, so the
    side rises vertically from the pier and the two arcs meet at a point."""
    A = W / 2.0 - pier + c
    B = (spring - apex) / math.sqrt(1.0 - (c / A) ** 2)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64) + 0.5
    in_l = ((xx - (W / 2.0 + c)) / A) ** 2 + ((yy - spring) / B) ** 2 <= 1.0
    in_r = ((xx - (W / 2.0 - c)) / A) ** 2 + ((yy - spring) / B) ** 2 <= 1.0
    walls = (xx >= pier) & (xx <= W - pier)
    return walls & ((yy >= spring) | (in_l & in_r))


def _gothic_frame(a: np.ndarray) -> None:
    H, W = a.shape[:2]
    stone = RAMPS["stone"]
    pier = 18
    spring, apex = 62.0, 4.0
    opening = _arch_opening(W, H, pier, spring, apex, 40.0)
    frame = ~opening
    dist = distance_transform_edt(frame)
    gy, gx = np.gradient(dist)
    gn = np.hypot(gx, gy) + 1e-6
    # normal of the moulding faces points from the stone into the opening
    lit = (gx / gn) * LIGHT_2D[0] * -1 + (gy / gn) * LIGHT_2D[1] * -1
    lit = -lit
    tone = np.full((H, W), 1, int)
    roll1 = dist <= 2.0
    tone = np.where(roll1, np.where(lit > 0.2, 5, np.where(lit > -0.3, 4, 2)), tone)
    tone = np.where((dist > 2.0) & (dist <= 3.0), 0, tone)                     # carved groove
    roll2 = (dist > 3.0) & (dist <= 5.0)
    tone = np.where(roll2, np.where(lit > 0.2, 4, np.where(lit > -0.3, 3, 2)), tone)
    tone = np.where((dist > 5.0) & (dist <= 6.0), 0, tone)
    tone = np.where(dist > 6.0, 1, tone)
    cols = np.array([_rgba(c) for c in stone], np.uint8)
    a[frame] = cols[np.clip(tone, 0, len(stone) - 1)][frame]
    # ashlar coursing on the outer stone (beyond the mouldings): every block
    # gets its own hashed face tone (60% S1, 40% S2), a lit top row (S3) and
    # a shaded bottom row (S0), so the frame reads as laid stone, not a grid
    outer = frame & (dist > 6.0)
    for y in range(H):
        for x in range(W):
            if not outer[y, x]:
                continue
            course = y // 12
            shift = (course % 2) * 12
            block = (x + shift) // 24
            joint = (y % 12 == 0) or ((x + shift) % 24 == 0)
            if joint:
                a[y, x] = _rgba(stone[0])
            elif y % 12 == 1:
                a[y, x] = _rgba(stone[3])
            elif y % 12 == 11:
                a[y, x] = _rgba(stone[0])
            elif (x + shift) % 24 == 1:
                a[y, x] = _rgba(stone[2])
            else:
                h = ((course * 92821) ^ (block * 68917) ^ 0x5bd1) * 2654435761 & 0xFFFFFFFF
                a[y, x] = _rgba(stone[2] if (h >> 16) % 10 < 4 else stone[1])
    # engaged column shafts on both piers, lit from the left
    for x0 in (pier - 7, W - pier + 1):
        for x in range(x0, x0 + 6):
            t = x - x0
            c = (stone[2], stone[4], stone[5], stone[4], stone[3], stone[1])[t]
            a[int(spring) + 3:GROUND_Y + 6, x] = _rgba(c)
        a[int(spring) + 3:GROUND_Y + 6, x0 - 1] = _rgba(stone[0])  # seat lines either side
        a[int(spring) + 3:GROUND_Y + 6, x0 + 6] = _rgba(stone[0])
        # capital with a gold band, and a base
        for dy, cc in ((0, GOLD[4]), (1, GOLD[2]), (2, stone[4]), (3, stone[2])):
            a[int(spring) - 1 + dy, x0 - 2:x0 + 8] = _rgba(cc)
        a[int(spring) - 2, x0 - 2:x0 + 8] = _rgba(stone[0])
        for dy, cc in ((0, stone[4]), (1, stone[3]), (2, stone[1])):
            a[GROUND_Y + 6 + dy, x0 - 2:x0 + 8] = _rgba(cc)
    # keystone jewel at the apex
    cx = W // 2
    apex_y = int(np.argmax(opening[:, cx]))
    _jewel(a, cx, max(3, apex_y - 3))


def _jewel(a: np.ndarray, cx: int, cy: int) -> None:
    """5x5 crimson cabochon in a gold setting."""
    pts = [
        (0, -2, GOLD[4]), (-1, -1, GOLD[4]), (0, -1, CRIMSON[5]), (1, -1, GOLD[3]),
        (-2, 0, GOLD[4]), (-1, 0, CRIMSON[5]), (0, 0, CRIMSON[4]), (1, 0, CRIMSON[2]), (2, 0, GOLD[2]),
        (-1, 1, GOLD[3]), (0, 1, CRIMSON[2]), (1, 1, GOLD[2]), (0, 2, GOLD[1]),
    ]
    for dx, dy, c in pts:
        a[cy + dy, cx + dx] = _rgba(c)
    a[cy - 1, cx - 1] = _rgba(GOLD[5])
    a[cy - 1, cx] = _rgba((255, 220, 224))


def _title_divider(a: np.ndarray) -> None:
    """Silver rule with a crimson jewel under the game title."""
    y, cx = TITLE_DIVIDER_Y, SCREEN_W // 2
    for x in range(cx - 78, cx + 79):
        d = abs(x - cx)
        if d < 6:
            continue
        if d > 70 and (x % 2):
            continue
        a[y, x] = _rgba(BORDER_SHADE if d > 30 else BORDER_LIT)
        a[y + 1, x] = _rgba(BORDER_OUTER)
    for side in (-1, 1):
        for k in range(3):
            a[y - 1 - k, cx + side * (8 + k * 2)] = _rgba(BORDER_SHADE)
            a[y + 1 + k, cx + side * (8 + k * 2)] = _rgba(BORDER_OUTER)
    _jewel(a, cx, y)


# The game title is baked into the backdrop as a gilt logo (title_menu.tscn's
# Title label is hidden): the Roman title capitals laid out exactly as that
# Label drew them, filled with the GOLD ramp in bands down the cap height,
# struck with G5 glints on the top-left of every other letter, outlined, with
# a 1 px crimson drop shadow, and a thorned scroll either side.
TITLE_TEXT = "CRIMSON NOCTURNE"
TITLE_LABEL_RECT = (24, 24, 360, 40)          # the (hidden) Title label in title_menu.tscn
LOGO_BANDS = (4, 4, 4, 3, 3, 3, 3, 2, 2, 2, 1, 1)   # GOLD tone per cap row, top -> bottom
LOGO_SHADOW: RGB = CRIMSON[2]                  # (88, 14, 36)
# One scroll, for the right-hand side (u outward from the text, v down), in
# px: a thin stem that rises in a shallow arc and rolls up into a volute of
# 1.3 turns at its end. The left one is its mirror.
SCROLL_STEM: tuple[tuple[float, float], ...] = tuple(
    (u * 0.5, -0.8 * math.sin(u * 0.5 * math.pi / 11.0)) for u in range(0, 23))
SCROLL_CURL_C: Pt = (12.4, -2.8)
SCROLL_TURNS = 1.3
SCROLL_SHRINK = 0.72                           # the volute's radius falls to 28%
SCROLL_THORNS: tuple[int, ...] = (4, 9)        # u positions of the two thorns (pointing up and out)


def _logo_layout() -> tuple[int, int, list[tuple[int, np.ndarray]]]:
    pen, parts = 0, []
    for ch in TITLE_TEXT:
        if ch == " ":
            pen += TITLE_SPACE_ADVANCE
            continue
        m = _mask(TITLE_GLYPHS[ch])
        parts.append((pen, m))
        pen += m.shape[1] + 2 + TITLE_TRACKING
    x0 = TITLE_LABEL_RECT[0] + (TITLE_LABEL_RECT[2] - TITLE_LABEL_RECT[0] - pen) // 2
    return x0, TITLE_LABEL_RECT[1], parts


def _scroll_pixels() -> list[tuple[int, int]]:
    """The right-hand scroll as 1x pixels relative to its root."""
    pts: list[Pt] = list(SCROLL_STEM)
    cx, cy = SCROLL_CURL_C
    r0 = math.hypot(pts[-1][0] - cx, pts[-1][1] - cy)
    a0 = math.atan2(pts[-1][1] - cy, pts[-1][0] - cx)
    for i in range(1, 60):
        t = i / 59.0
        a = a0 - t * SCROLL_TURNS * 2.0 * math.pi      # rolls up and back toward the text
        r = r0 * (1.0 - SCROLL_SHRINK * t)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    out: list[tuple[int, int]] = []
    for u, v in pts:
        p = (int(math.floor(u + 0.5)), int(math.floor(v + 0.5)))
        if p not in out:
            out.append(p)
    return out


def _title_logo(a: np.ndarray) -> None:
    H, W = a.shape[:2]
    x0, y0, parts = _logo_layout()
    fill = np.zeros((H, W), bool)
    band = np.full((H, W), -1)
    for i, (px, m) in enumerate(parts):
        h, w = m.shape
        gx, gy = x0 + px + 1, y0 + 1
        fill[gy:gy + h, gx:gx + w] |= m
        for r in range(h):
            row = band[gy + r, gx:gx + w]
            row[m[r]] = LOGO_BANDS[r]
    # thorned scrolls either side, at mid cap height
    xs = np.nonzero(fill.any(axis=0))[0]
    mid = y0 + 1 + TITLE_CAP // 2
    scroll = _scroll_pixels()
    for side, root in ((1, int(xs.max()) + 4), (-1, int(xs.min()) - 4)):
        for u, v in scroll:
            x, y = root + side * u, mid + v
            fill[y, x] = True
            band[y, x] = 3
        for u in SCROLL_THORNS:
            v = next(vv for uu, vv in scroll if uu == u)
            for du, dv in ((0, -1), (side * 1, -2)):
                x, y = root + side * u + du, mid + v + dv
                fill[y, x] = True
                band[y, x] = 2
        # a bead where the scroll meets the lettering
        fill[mid - 1:mid + 2, root - side] = True
        band[mid - 1:mid + 2, root - side] = 3
        band[mid - 1, root - side] = 4
    outline = _dilate(fill, diagonal=True) & ~fill
    body = fill | outline
    shadow = np.zeros_like(body)
    shadow[1:, 1:] = body[:-1, :-1]
    shadow &= ~body
    a[shadow] = _rgba(LOGO_SHADOW)
    a[outline] = _rgba(GLYPH_OUTLINE)
    for k in range(len(GOLD)):
        a[band == k] = _rgba(GOLD[k])
    # scroll undersides one tone darker, so the thin stem has a lit top
    for side, root in ((1, int(xs.max()) + 4), (-1, int(xs.min()) - 4)):
        for u, v in scroll:
            x, y = root + side * u, mid + v
            if fill[y, x] and fill[y - 1, x] and band[y, x] == 3:
                a[y, x] = _rgba(GOLD[2])
    # struck glints: the top-left corner of every other letter
    for i, (px, m) in enumerate(parts):
        if i % 2:
            continue
        gx, gy = x0 + px + 1, y0 + 1
        ys_, xs_ = np.nonzero(m)
        order = np.lexsort((xs_, ys_))
        for j in order:
            y, x = int(ys_[j]), int(xs_[j])
            if (y == 0 or not m[y - 1, x]) and (x == 0 or not m[y, x - 1]):
                a[gy + y, gx + x] = _rgba(GOLD[5])
                break


def build_title_backdrop() -> None:
    """384x216 title screen: indigo night sky with a crimson horizon glow,
    a large moon behind cloud strata, a distant castle on its crag, a gothic
    pointed-arch frame of carved stone around the whole screen, and the
    gilt game-title logo."""
    for t in FAR_SPIRES:
        finial_top = t.top - t.roof - 4
        assert finial_top >= TITLE_WINDOW_BOTTOM, f"far spire at x {t.cx} hides under the option window"
    a = np.zeros((SCREEN_H, SCREEN_W, 4), np.uint8)
    _sky(a)
    _moon(a)
    _clouds(a)
    _castle(a)
    _gothic_frame(a)
    _title_logo(a)
    _title_divider(a)
    _to_image(a).save(os.path.join(UI, "title_backdrop.png"))



def build() -> None:
    build_font()
    build_title_font()
    build_digit_fonts()
    build_hud()
    build_menu_ui()
    build_area_banner()
    build_title_backdrop()


if __name__ == "__main__":
    build()
