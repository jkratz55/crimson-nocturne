"""
Shared helpers for the Crimson Nocturne procedural asset pipeline.

All art is generated at native 1x pixel resolution with a restricted,
gothic palette inspired by 32-bit era 2D action games (deep blues and
violets for the castle, crimson accents, bone whites, candle golds).

Every sprite gets a 1px dark "sel-out" style outline via `outline()`,
which is what makes procedurally drawn shapes read as hand-pixelled art.

The SotN-style art pass adds a shared style guide on top of that, written
as code so every module agrees on it:

- `RAMPS`: one registry of hue-shifted material ramps, dark -> light, used
  by every module so the whole screen shares one palette. `make_ramp()` and
  `aerial()` derive new ramps and background (depth-faded) versions.
- `LIGHT` / `RIM` (sprites, key light upper-front of a right-facing sprite,
  cool back rim; the light mirrors with `flip_h` as in SotN) and
  `LIGHT_ENV` (architecture: top-left bevels, fixed).
- Outlines: `outline()` (the original single-colour 1px border) and
  `selout()` (material-tinted, lighter on the lit edge).
- Shading: `shade_normals()`, `heightmap_normals()`, `shade_heightmap()`,
  `quantize_to_ramp()` (+ `bayer()` dithering), cleanup with
  `remove_orphans()` / `majority()`.
- Procedural detail: `value_noise()`, `fbm()`, `bezier()`, `catmull_rom()`,
  `verlet_chain()` (secondary motion), `rot_sprite()` (pixel-art rotation),
  `radial_halo()`, `gradient_bands()`, `bevel_rect()`.
- `VolCanvas` -> `Indexed`: the material-aware volumetric renderer (lit
  capsules / ellipsoids / cloth / ribbons / heightfields at 4x, resolved to
  one material + ramp tone per 1x pixel, then stamps, strokes, interior
  contours and sel-out).
- `SheetBuilder` optionally writes per-frame 60 Hz ticks and a feet origin.

Everything is deterministic: there is no global RNG, every random source
takes an explicit seed.
"""
from __future__ import annotations

import json
import math
import os
from typing import Callable, Iterable, Literal, Mapping, Sequence, Union

import numpy as np
from PIL import Image, ImageDraw

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SPRITES = os.path.join(ROOT, "assets", "sprites")
TILES = os.path.join(ROOT, "assets", "tiles")
BACKGROUNDS = os.path.join(ROOT, "assets", "backgrounds")
UI = os.path.join(ROOT, "assets", "ui")
FONTS = os.path.join(ROOT, "assets", "fonts")
MUSIC = os.path.join(ROOT, "assets", "audio", "music")
SFX = os.path.join(ROOT, "assets", "audio", "sfx")
FRAMES_RES = os.path.join(ROOT, "resources", "sprite_frames")

for _p in (SPRITES, TILES, BACKGROUNDS, UI, FONTS, MUSIC, SFX, FRAMES_RES):
    os.makedirs(_p, exist_ok=True)

Color = tuple[int, int, int] | tuple[int, int, int, int]
Point = tuple[float, float]

# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------
OUTLINE = (18, 10, 26, 255)

# Hero (the dhampir "Vesper")
SKIN = (238, 218, 206)
SKIN_SH = (178, 142, 150)
HAIR = (44, 34, 66)
HAIR_HI = (92, 76, 132)
COAT = (40, 44, 96)
COAT_SH = (24, 26, 60)
COAT_HI = (76, 84, 150)
TRIM = (220, 178, 76)
TRIM_SH = (150, 104, 40)
CAPE_OUT = (26, 16, 34)
CAPE_IN = (156, 24, 44)
CAPE_IN_HI = (208, 52, 64)
PANTS = (62, 52, 78)
PANTS_SH = (40, 32, 52)
BOOT = (34, 26, 38)
BOOT_HI = (70, 58, 76)
EYE = (230, 40, 48)
BLADE = (226, 234, 246)
BLADE_SH = (132, 144, 178)
LEATHER = (112, 46, 48)
LEATHER_HI = (168, 80, 68)
LEATHER_SH = (58, 24, 32)

# Bone / undead
BONE = (232, 224, 200)
BONE_SH = (160, 150, 128)
BONE_DK = (104, 92, 80)

# Bat
BAT = (70, 36, 84)
BAT_SH = (44, 22, 56)
BAT_WING = (96, 50, 110)

# Castle stone
STONE = (72, 78, 116)
STONE_HI = (108, 116, 160)
STONE_SH = (48, 50, 84)
MORTAR = (30, 30, 52)
STONE_BG = (40, 42, 70)
STONE_BG_HI = (56, 60, 94)
STONE_BG_SH = (28, 28, 50)
CARPET = (128, 20, 40)
CARPET_HI = (176, 40, 56)
MOSS = (58, 92, 76)

# Light / fire
FIRE_1 = (255, 244, 196)
FIRE_2 = (255, 196, 72)
FIRE_3 = (236, 104, 36)
FIRE_4 = (160, 36, 32)
HEART = (224, 32, 56)
HEART_HI = (255, 140, 150)
HEART_SH = (130, 10, 40)

# Soul-light (save shrine orb, Leap Stone, silver necklace)
SOUL = (126, 208, 255)
SOUL_HI = (226, 246, 255)
SOUL_SH = (44, 96, 176)


def rgba(c: Color, a: int = 255) -> tuple[int, int, int, int]:
    """Normalise an RGB/RGBA tuple to RGBA."""
    return (c[0], c[1], c[2], c[3] if len(c) == 4 else a)


def new_canvas(w: int, h: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def outline(img: Image.Image, color: Color = OUTLINE, diagonal: bool = False) -> Image.Image:
    """Add a 1px 4-connected outline around every opaque region.

    `diagonal=True` makes it 8-connected (corners filled too), which reads
    heavier; SotN-style sprites usually want the 4-connected default or
    `selout()`.
    """
    w, h = img.size
    src = img.load()
    out = img.copy()
    dst = out.load()
    offsets: tuple[tuple[int, int], ...] = ((1, 0), (-1, 0), (0, 1), (0, -1))
    if diagonal:
        offsets += ((1, 1), (-1, 1), (1, -1), (-1, -1))
    for y in range(h):
        for x in range(w):
            if src[x, y][3] != 0:
                continue
            for dx, dy in offsets:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and src[nx, ny][3] != 0:
                    dst[x, y] = rgba(color)
                    break
    return out


def line(d: ImageDraw.ImageDraw, pts: Sequence[Point], color: Color, width: int = 1) -> None:
    d.line([(round(x), round(y)) for x, y in pts], fill=rgba(color), width=width, joint="curve")


def poly(d: ImageDraw.ImageDraw, pts: Sequence[Point], color: Color) -> None:
    d.polygon([(round(x), round(y)) for x, y in pts], fill=rgba(color))


def rect(d: ImageDraw.ImageDraw, x0: float, y0: float, x1: float, y1: float, color: Color) -> None:
    d.rectangle([round(x0), round(y0), round(x1), round(y1)], fill=rgba(color))


def px(img: Image.Image, x: float, y: float, color: Color) -> None:
    xi, yi = round(x), round(y)
    if 0 <= xi < img.width and 0 <= yi < img.height:
        img.putpixel((xi, yi), rgba(color))


def lerp(a: Point, b: Point, t: float) -> Point:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def polar(origin: Point, angle_deg: float, length: float) -> Point:
    a = math.radians(angle_deg)
    return (origin[0] + math.cos(a) * length, origin[1] + math.sin(a) * length)


# ==========================================================================
# SotN art-pass style guide. Frozen once the art pass starts: modules read
# these constants and helpers; a module that needs something new defines it
# locally rather than editing this file.
# ==========================================================================
RGB = tuple[int, int, int]
Vec3 = tuple[float, float, float]

TICK_HZ = 60.0              # animation is authored in 60 Hz ticks
VOID: RGB = (6, 4, 12)      # darkest value on screen (out-of-room void)

# Hero frame contract (hero.py, player.tscn sprite offset (0, -36))
HERO_FRAME_W, HERO_FRAME_H = 128, 80
HERO_CENTER_X = 64          # body centred on this column
HERO_FOOT_Y = 75            # lowest opaque sole row
HERO_HEIGHT = 48            # sole -> crown in px, about 7 heads


def _unit3(v: Sequence[float]) -> Vec3:
    n = math.sqrt(sum(float(c) * float(c) for c in v)) or 1.0
    return (float(v[0]) / n, float(v[1]) / n, float(v[2]) / n)


# Light vectors use image axes: +x right, +y DOWN, +z toward the viewer.
# Sprites are drawn facing right and flipped in-engine, so the key light is
# "upper-front" relative to facing and mirrors with the sprite (as in SotN).
LIGHT: Vec3 = _unit3((0.55, -0.62, 0.56))
# Cool back rim: the contour facing away from the light (behind the
# character) picks up a 1 px rim tone.
RIM: Vec3 = _unit3((-0.95, -0.10, 0.0))
# Architecture and tiles are never flipped: highlights on top/left edges,
# shadow on bottom/right (docs/art_style.md, Lighting).
LIGHT_ENV: Vec3 = _unit3((-0.45, -0.70, 0.55))

# --------------------------------------------------------------------------
# Ramp registry. Every ramp runs DARK -> LIGHT; tone 0 doubles as the
# material's sel-out outline colour. Values are hand-picked originals (see
# docs/art_style.md, Palette: hue rotates toward violet in shadow, warm/cyan
# in light; shadows never go neutral grey or pure black). Ramps marked
# "derived" were not hand-picked
# and come from `make_ramp()` / `aerial()` around existing palette colours.
# --------------------------------------------------------------------------
RAMPS: dict[str, list[RGB]] = {
    # --- castle architecture -------------------------------------------
    "stone": [(12, 10, 22), (24, 22, 42), (38, 38, 64), (56, 58, 88), (78, 82, 114),
              (106, 112, 144), (142, 148, 176)],            # S0 mortar .. S6 edge highlight
    "stone_bg": [(8, 7, 18), (16, 14, 32), (26, 24, 46), (38, 36, 62), (52, 50, 80)],
    "stone_far": [(8, 7, 18), (16, 14, 32), (26, 24, 46)],  # distant silhouettes: STONE_BG 0-2 (+ COLORS["moon_rim"])
    "marble": [(46, 44, 70), (78, 78, 106), (114, 116, 142), (152, 154, 176), (190, 192, 208),
               (222, 222, 232), (246, 244, 248)],
    "marble_dk": [(14, 8, 16), (28, 16, 28), (46, 28, 42), (70, 48, 64), (104, 82, 104)],
    "wood": [(22, 10, 14), (42, 20, 22), (66, 34, 30), (94, 52, 38), (126, 76, 50), (164, 108, 66)],
    "crimson": [(30, 4, 16), (56, 8, 26), (88, 14, 36), (124, 20, 44), (160, 34, 52), (196, 62, 66)],
    "carpet": [(30, 4, 16), (56, 8, 26), (88, 14, 36), (124, 20, 44), (160, 34, 52), (196, 62, 66)],
    "velvet": [(30, 4, 16), (56, 8, 26), (88, 14, 36), (124, 20, 44), (160, 34, 52), (196, 62, 66),
               (214, 112, 128)],                            # crimson + fold-crest sheen
    "gold": [(48, 26, 14), (90, 52, 20), (140, 92, 30), (192, 142, 50), (230, 196, 98),
             (252, 240, 184)],                              # G5 is specular only
    "moss": [(26, 44, 40), (44, 72, 58), (70, 104, 80)],
    # --- light, sky, fire ------------------------------------------------
    "fire": [(104, 24, 30), (180, 56, 30), (236, 118, 36), (255, 190, 70), (255, 236, 150),
             (255, 255, 240)],                              # ember .. white core
    "fire_halo": [(20, 12, 4), (40, 24, 8), (60, 36, 12)],  # additive candle-halo rings
    "smoke": [(52, 40, 56), (84, 70, 86)],
    "wax": [(96, 80, 84), (150, 134, 124), (200, 188, 168), (238, 230, 212)],
    "moon": [(96, 104, 170), (150, 160, 206), (204, 212, 240), (238, 240, 252)],
    "moonlight": [(20, 24, 40), (40, 48, 80), (110, 130, 200)],  # additive shafts: half, full, motes
    "sky": [(4, 4, 14), (10, 10, 30), (20, 16, 48), (34, 24, 66), (58, 30, 76)],  # zenith .. horizon
    "cloud": [(28, 24, 52), (44, 40, 74), (70, 66, 104), (120, 120, 168)],       # .. moonlit rim
    "soul": [(24, 30, 94), (44, 96, 176), (84, 156, 226), (126, 208, 255), (226, 246, 255)],  # derived: SOUL_SH/SOUL/SOUL_HI
    # --- hero ------------------------------------------------------------
    "skin": [(64, 34, 52), (122, 80, 96), (176, 134, 140), (220, 186, 184), (246, 226, 220)],
    "hair": [(8, 6, 16), (20, 16, 36), (36, 30, 62), (58, 52, 96), (96, 92, 148), (150, 150, 200)],
    "coat": [(10, 10, 26), (22, 22, 50), (36, 38, 80), (54, 60, 114), (80, 90, 150), (116, 128, 184)],
    "cape_out": [(6, 4, 12), (16, 14, 28), (28, 26, 48), (44, 44, 74), (70, 74, 112)],
    "cape_in": [(40, 4, 18), (84, 10, 32), (130, 20, 44), (178, 40, 58), (220, 84, 88)],
    "trousers": [(12, 8, 18), (26, 20, 34), (44, 36, 56), (66, 58, 82)],
    "boot": [(12, 8, 18), (26, 20, 34), (44, 36, 56), (66, 58, 82), (104, 96, 124)],
    "leather": [(28, 10, 14), (58, 22, 24), (96, 42, 36), (138, 72, 52), (180, 112, 80)],
    "steel": [(24, 26, 40), (56, 62, 86), (98, 106, 136), (146, 156, 186), (196, 206, 228),
              (244, 248, 255)],
    "eye": [(150, 20, 36), (255, 64, 72)],                  # red dhampir glint
    # --- enemies ---------------------------------------------------------
    "bone": [(44, 34, 34), (90, 76, 66), (140, 126, 106), (188, 178, 152), (226, 218, 196),
             (248, 244, 230)],                              # warm dark outline, never violet-black
    "socket": [(255, 60, 48), (255, 170, 120)],             # glow, core
    "bat": [(14, 8, 20), (32, 18, 40), (56, 30, 64), (84, 48, 92), (122, 80, 128)],
    # --- pickups, gems, UI -------------------------------------------------
    "heart": [(70, 6, 26), (140, 14, 40), (222, 34, 60), (255, 128, 140)],
    "mana": [(16, 30, 96), (40, 90, 220), (120, 180, 255), (220, 240, 255)],
    # gems: derived, make_ramp(base, 5, light_range=(0.22, 0.92)); top tone = specular glint
    "gem_ruby": [(56, 0, 25), (125, 0, 48), (198, 28, 58), (255, 119, 101), (255, 220, 208)],
    "gem_jade": [(0, 32, 29), (0, 93, 76), (54, 160, 120), (125, 203, 151), (194, 244, 193)],
    "gem_onyx": [(27, 20, 53), (64, 52, 98), (110, 105, 159), (159, 164, 218), (220, 227, 255)],
    "gem_sapphire": [(25, 0, 83), (39, 41, 147), (40, 90, 200), (84, 164, 255), (205, 233, 255)],
    "ui_window": [(6, 6, 34), (14, 14, 52), (22, 22, 68), (30, 30, 86), (38, 38, 104)],  # top .. bottom
}

# Single accents that are not ramps (docs/art_style.md, Palette).
COLORS: dict[str, RGB] = {
    "void": VOID,
    "eye_glint": (255, 64, 72),
    "lip": (190, 110, 120),
    "coat_rim": (116, 128, 184),
    "hair_sheen": (150, 150, 200),
    "cape_sheen": (70, 74, 112),
    "crimson_sheen": (214, 112, 128),
    "marble_vein": (96, 84, 116),
    "bone_outline": (44, 34, 34),
    "sky_glow": (86, 28, 56),
    "star": (238, 240, 252),
    "star_dim": (150, 160, 206),
    "moon_rim": (120, 120, 168),
    "moon_sill": (204, 212, 240),
    "flash_crimson": (196, 62, 66),
    "burn_tint": (104, 24, 30),
    "dmg_enemy": (255, 255, 255),
    "dmg_enemy_edge": (255, 236, 150),
    "dmg_player": (255, 96, 96),
    "dmg_player_edge": (255, 200, 200),
    "heal": (120, 240, 180),
    "heal_edge": (220, 255, 235),
    "ui_border": (226, 226, 240),
    "ui_border_shadow": (4, 4, 20),
    "ui_text": (240, 240, 248),
    "ui_text_shadow": (6, 6, 24),
    "ui_heading": (232, 196, 110),
    "ui_disabled": (112, 112, 146),
    "ui_gain": (120, 200, 255),
    "ui_loss": (255, 110, 110),
    "ui_cursor_dim": (64, 4, 14),
    "ui_cursor_bright": (96, 4, 14),
    "hp_digit_top": (250, 250, 255),
    "hp_digit_bottom": (196, 200, 232),
    "map_explored": (30, 50, 170),
    "map_wall": (200, 210, 255),
    "map_save": (200, 40, 60),
    "map_warp": (230, 200, 60),
}


# --------------------------------------------------------------------------
# Colour math (OKLab / OKLCh for perceptual ramps)
# --------------------------------------------------------------------------
def luma(c: Sequence[float]) -> float:
    """Rec. 601 luminance Y in 0..255 (the 'Y' values in docs/art_style.md)."""
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def mix(a: Sequence[float], b: Sequence[float], t: float) -> RGB:
    """Linear sRGB-space blend of two colours, rounded."""
    return (round(a[0] + (b[0] - a[0]) * t), round(a[1] + (b[1] - a[1]) * t),
            round(a[2] + (b[2] - a[2]) * t))


def ps1_snap(c: Sequence[int]) -> RGB:
    """Snap to 15-bit (5 bits per channel) PS1 colour depth, re-expanded so
    that 31 maps back to 255."""
    return tuple(((int(v) & 0xF8) | (int(v) >> 5)) for v in c[:3])  # type: ignore[return-value]


def _srgb_to_linear(v: float) -> float:
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(v: float) -> float:
    return v * 12.92 if v <= 0.0031308 else 1.055 * (v ** (1 / 2.4)) - 0.055


def to_oklab(c: Sequence[float]) -> Vec3:
    """sRGB 0..255 -> OKLab (L 0..1)."""
    r, g, b = (_srgb_to_linear(float(v) / 255.0) for v in c[:3])
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def _oklab_to_unit_rgb(lab: Sequence[float]) -> Vec3:
    """OKLab -> sRGB in 0..1, NOT clipped (may be out of gamut)."""
    L, a, b = lab
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    lin = (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
           -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
           -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)
    return tuple(_linear_to_srgb(v) if v >= 0 else -_linear_to_srgb(-v) for v in lin)  # type: ignore[return-value]


def from_oklab(lab: Sequence[float]) -> RGB:
    """OKLab -> sRGB 0..255. Out-of-gamut colours keep L and hue and lose
    chroma until they fit (no hue-shifting hard clip)."""
    L, a, b = lab
    L = min(1.0, max(0.0, L))

    def fits(k: float) -> bool:
        return all(-1e-4 <= v <= 1.0001 for v in _oklab_to_unit_rgb((L, a * k, b * k)))

    k = 1.0
    if not fits(1.0):
        lo, hi = 0.0, 1.0
        for _ in range(24):
            mid = (lo + hi) / 2
            if fits(mid):
                lo = mid
            else:
                hi = mid
        k = lo
    rgb = _oklab_to_unit_rgb((L, a * k, b * k))
    return tuple(int(round(min(1.0, max(0.0, v)) * 255)) for v in rgb)  # type: ignore[return-value]


def to_oklch(c: Sequence[float]) -> Vec3:
    """sRGB -> (L 0..1, chroma, hue degrees 0..360)."""
    L, a, b = to_oklab(c)
    return (L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360.0)


def from_oklch(L: float, C: float, h: float) -> RGB:
    return from_oklab((L, C * math.cos(math.radians(h)), C * math.sin(math.radians(h))))


def _hue_toward(h: float, target: float, max_deg: float) -> float:
    """Rotate hue `h` toward `target` along the short arc by at most `max_deg`."""
    d = (target - h + 540.0) % 360.0 - 180.0
    step = max(-max_deg, min(max_deg, d))
    return (h + step) % 360.0


SHADOW_HUE = 290.0      # OKLCh indigo-violet: where every shadow leans
WARM_LIGHT_HUE = 85.0   # orange-yellow: where warm materials' lights lean
COOL_LIGHT_HUE = 215.0  # cyan-lavender: where cool materials' lights lean


def make_ramp(base: Sequence[int], n: int = 5, hue_shift_deg: float = 20.0, step: float = 0.10,
              accel: float = 1.2, base_index: int | None = None,
              light_range: tuple[float, float] | None = None, sat_curve: float = 0.25,
              shadow_hue: float = SHADOW_HUE, light_hue: float | None = None) -> list[RGB]:
    """Build an `n`-tone hue-shifted ramp (dark -> light) that contains `base`.

    Works in OKLCh, calibrated on the hand-picked RAMPS (docs/art_style.md):
    - `base` sits at `base_index` (default the lower middle tone) exactly.
    - Lightness steps are `step` OKLab L around the base and grow by
      `accel` per tone toward the light (hand-picked ramps step ~0.06 in the
      darks to ~0.12 in the lights; bone/steel/gold use ~0.15). The ends
      are compressed to stay within L 0.14..0.97, so the darkest tone never
      drops below the scene's void value. `light_range=(L0, L1)` instead
      spaces the tones linearly between those lightness values.
    - Shadows rotate toward `shadow_hue` (indigo-violet) and lights toward
      `light_hue` (auto: warm for reds/oranges/yellows/greens, cyan-lavender
      for blues/violets), by up to `hue_shift_deg` at the ends.
    - Chroma peaks in the mid-tones (`sat_curve`, 0 = constant chroma).
      Out-of-gamut tones lose chroma, never hue.
    """
    if n <= 1:
        return [(int(base[0]), int(base[1]), int(base[2]))]
    L_b, C_b, h_b = to_oklch(base)
    if light_range is not None:
        L0, L1 = light_range
        k = int(round((L_b - L0) / max(1e-6, L1 - L0) * (n - 1)))
        k = max(0, min(n - 1, k)) if base_index is None else base_index
        Ls = [L0 + (L_b - L0) * (i / k) if i < k else
              L_b + (L1 - L_b) * ((i - k) / max(1, n - 1 - k)) for i in range(n)]
    else:
        k = (n - 1) // 2 if base_index is None else max(0, min(n - 1, base_index))
        Ls = [0.0] * n
        Ls[k] = L_b
        for i in range(k - 1, -1, -1):
            Ls[i] = Ls[i + 1] - step * accel ** (i - k + 0.5)
        for i in range(k + 1, n):
            Ls[i] = Ls[i - 1] + step * accel ** (i - 1 - k + 0.5)
        lo, hi = 0.14, 0.97
        if k > 0 and Ls[0] < lo < L_b:
            f = (L_b - lo) / (L_b - Ls[0])
            Ls[:k] = [L_b - (L_b - v) * f for v in Ls[:k]]
        if k < n - 1 and Ls[-1] > hi > L_b:
            f = (hi - L_b) / (Ls[-1] - L_b)
            Ls[k + 1:] = [L_b + (v - L_b) * f for v in Ls[k + 1:]]
    if light_hue is None:
        light_hue = WARM_LIGHT_HUE if (h_b < 170.0 or h_b >= 330.0) else COOL_LIGHT_HUE

    def sat(t: float) -> float:
        return 1.0 - sat_curve * (2.0 * t - 1.0) ** 2

    t_b = k / (n - 1)
    out: list[RGB] = []
    for i in range(n):
        if i == k:
            out.append((int(base[0]), int(base[1]), int(base[2])))
            continue
        if i < k:
            h = _hue_toward(h_b, shadow_hue, hue_shift_deg * (k - i) / k)
        else:
            h = _hue_toward(h_b, light_hue, hue_shift_deg * (i - k) / (n - 1 - k))
        C = C_b * sat(i / (n - 1)) / max(1e-6, sat(t_b))
        out.append(from_oklch(Ls[i], C, h))
    return out


def aerial(ramp: Sequence[Sequence[int]], desat: float = 0.35, steps: float = 2.0,
           fog: Sequence[int] = (20, 18, 44), fog_amt: float = 0.25) -> list[RGB]:
    """Background (depth-faded) version of a ramp (docs/art_style.md, Palette):
    desaturate ~35 %, darken by `steps` of the ramp's own tone spacing
    (floored at the void's lightness, so the darkest tones may merge), then
    lean 25 % toward the indigo fog colour."""
    lch = [to_oklch(c) for c in ramp]
    Ls = [v[0] for v in lch]
    n = len(Ls)
    first = (Ls[1] - Ls[0]) if n > 1 else 0.05
    floor = to_oklab(VOID)[0]

    def L_at(x: float) -> float:
        if x <= 0 or n == 1:
            return Ls[0] + x * first
        i = min(int(x), n - 2)
        return Ls[i] + (Ls[i + 1] - Ls[i]) * (x - i)

    fl = to_oklab(fog)
    out: list[RGB] = []
    for i, (_, C, h) in enumerate(lch):
        L = max(floor, L_at(i - steps))
        C *= 1.0 - desat
        a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
        out.append(from_oklab((L + (fl[0] - L) * fog_amt, a + (fl[1] - a) * fog_amt,
                               b + (fl[2] - b) * fog_amt)))
    return out


def ramp_array(ramp: Sequence[Sequence[int]]) -> np.ndarray:
    """(n, 3) uint8 array of a ramp, for numpy lookups."""
    return np.array([tuple(c[:3]) for c in ramp], np.uint8)


def indices_to_image(idx: np.ndarray, ramp: Sequence[Sequence[int]],
                     mask: np.ndarray | None = None) -> Image.Image:
    """Tone-index array -> RGBA image. Pixels with idx < 0 or outside `mask`
    are transparent; alpha is only ever 0 or 255."""
    idx = np.asarray(idx)
    lut = ramp_array(ramp)
    valid = idx >= 0 if mask is None else (np.asarray(mask, bool) & (idx >= 0))
    out = np.zeros(idx.shape + (4,), np.uint8)
    out[valid, :3] = lut[np.clip(idx[valid], 0, len(lut) - 1)]
    out[valid, 3] = 255
    return Image.fromarray(out, "RGBA")


def palette_of(img: Image.Image) -> list[tuple[tuple[int, int, int, int], int]]:
    """Opaque colours of an image with their pixel counts, most used first."""
    a = np.array(img.convert("RGBA")).reshape(-1, 4)
    a = a[a[:, 3] > 0]
    if len(a) == 0:
        return []
    cols, counts = np.unique(a, axis=0, return_counts=True)
    order = sorted(range(len(cols)), key=lambda i: (-int(counts[i]), tuple(int(v) for v in cols[i])))
    return [(tuple(int(v) for v in cols[i]), int(counts[i])) for i in order]  # type: ignore[misc]


def cap_palette(img: Image.Image, max_colors: int,
                protect: Iterable[Sequence[int]] = ()) -> Image.Image:
    """Merge the least-used unprotected colours into their nearest remaining
    colour (OKLab distance) until at most `max_colors` opaque colours remain."""
    arr = np.array(img.convert("RGBA"))
    keep = {tuple(int(v) for v in c[:3]) for c in protect}
    pal = [(c[:3], n) for c, n in palette_of(img)]
    counts = {c: n for c, n in pal}
    remap: dict[tuple[int, ...], tuple[int, ...]] = {}
    while len(counts) > max_colors:
        victims = [c for c in counts if c not in keep]
        if not victims:
            break
        v = min(victims, key=lambda c: (counts[c], c))
        lv = to_oklab(v)
        others = [c for c in counts if c != v]
        tgt = min(others, key=lambda c: (sum((p - q) ** 2 for p, q in zip(to_oklab(c), lv)), c))
        counts[tgt] += counts.pop(v)
        for src, dst in list(remap.items()):
            if dst == v:
                remap[src] = tgt
        remap[v] = tgt
    for src, dst in remap.items():
        sel = (arr[..., 3] > 0) & np.all(arr[..., :3] == np.array(src, np.uint8), axis=-1)
        arr[sel, :3] = dst
    return Image.fromarray(arr, "RGBA")


# --------------------------------------------------------------------------
# Lighting and quantization
# --------------------------------------------------------------------------
def shade_normals(nx: np.ndarray, ny: np.ndarray, nz: np.ndarray, light: Vec3 = LIGHT, *,
                  ambient: float = 0.10, gamma: float = 1.5, rim: float = 0.35,
                  rim_vec: Vec3 = RIM, spec: float = 0.0, spec_pow: float = 12.0) -> np.ndarray:
    """Intensity in [0, 1] for a normal field (image axes, +z to viewer).

    I = ambient + (1 - ambient) * max(0, N.L) ** gamma
        + rim * (max(0, N.RIM_xy) * (1 - nz)) ** 2      (cool back rim)
        + spec * max(0, R.V) ** spec_pow                 (Phong, V = +z)
    The flat recipe in docs/art_style.md (0.75 * N.L + 0.25) is ambient=0.25, gamma=1.
    """
    lx, ly, lz = _unit3(light)
    d = np.clip(nx * lx + ny * ly + nz * lz, 0.0, 1.0)
    i = ambient + (1.0 - ambient) * d ** gamma
    if rim:
        rx, ry, _ = _unit3(rim_vec) if any(rim_vec) else (0.0, 0.0, 0.0)
        r = np.clip(nx * rx + ny * ry, 0.0, 1.0) * (1.0 - np.clip(nz, 0.0, 1.0))
        i = i + rim * r ** 2
    if spec:
        refl = 2.0 * d * nz - lz
        i = i + spec * np.clip(refl, 0.0, 1.0) ** spec_pow
    return np.clip(i, 0.0, 1.0)


def heightmap_normals(h: np.ndarray, strength: float = 2.2,
                      wrap: bool = True) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Unit normals (nx, ny, nz) of a height field via central differences.
    `wrap=True` treats the field as tileable (seamless tiles)."""
    hh = np.asarray(h, np.float64)
    p = np.pad(hh, 1, mode="wrap" if wrap else "edge")
    gx = (p[1:-1, 2:] - p[1:-1, :-2]) * 0.5
    gy = (p[2:, 1:-1] - p[:-2, 1:-1]) * 0.5
    nx, ny, nz = -gx * strength, -gy * strength, np.ones_like(hh)
    n = np.sqrt(nx * nx + ny * ny + nz * nz)
    return nx / n, ny / n, nz / n


def shade_heightmap(h: np.ndarray, strength: float = 2.2, light: Vec3 = LIGHT_ENV, *,
                    ao: float = 0.45, ambient: float = 0.15, gamma: float = 1.0,
                    wrap: bool = True) -> np.ndarray:
    """Lit intensity in [0, 1] for a height field (stone, embossing).
    `ao` darkens low areas (mortar, cracks): I *= (1 - ao) + ao * h_norm.
    Default light is `LIGHT_ENV` (architecture); pass `LIGHT` for sprites."""
    hh = np.asarray(h, np.float64)
    nx, ny, nz = heightmap_normals(hh, strength, wrap)
    lit = shade_normals(nx, ny, nz, light, ambient=ambient, gamma=gamma, rim=0.0)
    span = float(hh.max() - hh.min())
    hn = (hh - hh.min()) / span if span > 1e-9 else np.ones_like(hh)
    return np.clip(lit * ((1.0 - ao) + ao * hn), 0.0, 1.0)


def bayer(n: int, shape: tuple[int, int] | None = None,
          offset: tuple[int, int] = (0, 0)) -> np.ndarray:
    """Ordered-dither threshold matrix of size n x n (n a power of two),
    values (k + 0.5) / n^2 in (0, 1), mean 0.5. With `shape` it is tiled to
    that (h, w), shifted by `offset` (x, y) so dither can be screen-anchored."""
    if n < 1 or n & (n - 1):
        raise ValueError("bayer(n): n must be a power of two")
    m = np.zeros((1, 1), np.int64)
    while m.shape[0] < n:
        m = np.block([[4 * m, 4 * m + 2], [4 * m + 3, 4 * m + 1]])
    t = (m + 0.5) / float(n * n)
    if shape is None:
        return t
    hgt, wid = shape
    ys = (np.arange(hgt) + offset[1]) % n
    xs = (np.arange(wid) + offset[0]) % n
    return t[ys[:, None], xs[None, :]]


Dither = Union[Literal["bayer2", "bayer4", "bayer8"], int, None]


def _dither_size(dither: Dither) -> int:
    if dither is None:
        return 0
    if isinstance(dither, str):
        return {"bayer2": 2, "bayer4": 4, "bayer8": 8}[dither]
    return int(dither)


def quantize_to_ramp(intensity: np.ndarray, n_tones: int, thresholds: Sequence[float] | None = None,
                     bias: float = 0.0, dither: Dither = None, dither_amount: float = 1.0,
                     offset: tuple[int, int] = (0, 0)) -> np.ndarray:
    """Map intensity in [0, 1] to a tone index 0..n_tones-1 (int16).

    `thresholds` (n_tones - 1 ascending cut points, e.g. docs/art_style.md's
    0.15/0.35/0.55/0.75/0.90 for 6 tones) default to uniform bands.
    `dither` ("bayer2"/"bayer4"/"bayer8" or a size; 2-D input only) jitters
    the value by up to +-half a band (`dither_amount` scales that) before
    banding: use it for backgrounds, halos and UI gradients, never inside
    sprites. `offset` (x, y) anchors the pattern to screen space.
    """
    v = np.asarray(intensity, np.float64) + bias
    if thresholds is None:
        cuts = np.arange(1, n_tones, dtype=np.float64) / n_tones
    else:
        cuts = np.asarray(thresholds, np.float64)
        if len(cuts) != n_tones - 1 or np.any(np.diff(cuts) <= 0):
            raise ValueError("thresholds must be n_tones - 1 ascending values")
    size = _dither_size(dither)
    if size and v.ndim == 2:
        band = 1.0 / n_tones if thresholds is None else float(np.mean(np.diff(np.r_[0.0, cuts, 1.0])))
        v = v + (bayer(size, v.shape, offset) - 0.5) * band * dither_amount
    idx = np.searchsorted(cuts, v, side="right")
    return np.clip(idx, 0, n_tones - 1).astype(np.int16)


# --------------------------------------------------------------------------
# Indexed-image cleanup (tone arrays, optionally split by material)
# --------------------------------------------------------------------------
_N4: tuple[tuple[int, int], ...] = ((1, 0), (-1, 0), (0, 1), (0, -1))
_NDIAG: tuple[tuple[int, int], ...] = ((1, 1), (-1, 1), (1, -1), (-1, -1))


def _neighbor(a: np.ndarray, dx: int, dy: int, fill: object) -> np.ndarray:
    """out[y, x] = a[y + dy, x + dx], `fill` outside the array."""
    h, w = a.shape[:2]
    out = np.empty_like(a)
    out[...] = fill
    if abs(dx) >= w or abs(dy) >= h:
        return out
    out[max(0, -dy):h - max(0, dy), max(0, -dx):w - max(0, dx)] = \
        a[max(0, dy):h - max(0, -dy), max(0, dx):w - max(0, -dx)]
    return out


def _box3(a: np.ndarray) -> np.ndarray:
    """3x3 neighbourhood sum with zero padding."""
    p = np.pad(a, 1)
    h, w = a.shape
    return sum(p[dy:dy + h, dx:dx + w] for dy in range(3) for dx in range(3))  # type: ignore[return-value]


def remove_orphans(tone: np.ndarray, mat: np.ndarray | None = None, *, min_same: int = 3,
                   keep: np.ndarray | None = None) -> np.ndarray:
    """Replace isolated tone pixels: a pixel with at least `min_same`
    same-material 4-neighbours, none of which shares its tone, takes their
    most common tone (ties -> darker). `mat` (-1 = empty) defaults to one
    material wherever tone >= 0. `keep` masks pixels that must not change
    (deliberate 1 px speculars, eyes)."""
    t = np.asarray(tone).astype(np.int16)
    m = (np.where(t >= 0, 0, -1) if mat is None else np.asarray(mat)).astype(np.int32)
    nts = [_neighbor(t, dx, dy, -1) for dx, dy in _N4]
    same = [(_neighbor(m, dx, dy, -1) == m) & (m >= 0) for dx, dy in _N4]
    n_same = sum(s.astype(np.int16) for s in same)
    matches = sum((s & (nt == t)).astype(np.int16) for s, nt in zip(same, nts))
    cand = (m >= 0) & (n_same >= min_same) & (matches == 0)
    if keep is not None:
        cand &= ~np.asarray(keep, bool)
    best_score = np.full(t.shape, -1, np.int32)
    best_tone = t.copy()
    for k in range(4):
        cnt = sum((same[j] & (nts[j] == nts[k])).astype(np.int32) for j in range(4))
        score = np.where(same[k], cnt * 1024 - nts[k].astype(np.int32), -1)
        upd = score > best_score
        best_score = np.where(upd, score, best_score)
        best_tone = np.where(upd, nts[k], best_tone)
    return np.where(cand, best_tone, t).astype(np.int16)


def majority(tone: np.ndarray, mat: np.ndarray | None = None, *, iterations: int = 1,
             keep: np.ndarray | None = None) -> np.ndarray:
    """3x3 majority filter on tones, per material: each pixel takes the most
    common tone among same-material pixels in its 3x3 window (ties keep the
    pixel's own tone). Smooths banding and 1 px noise into clusters."""
    t = np.asarray(tone).astype(np.int16)
    m = (np.where(t >= 0, 0, -1) if mat is None else np.asarray(mat)).astype(np.int32)
    kp = np.zeros(t.shape, bool) if keep is None else np.asarray(keep, bool)
    for _ in range(iterations):
        new = t.copy()
        for mv in np.unique(m[m >= 0]):
            M = m == mv
            tones = np.unique(t[M])
            counts = np.stack([_box3((M & (t == tv)).astype(np.int32)) for tv in tones])
            ti = np.searchsorted(tones, np.where(M, t, tones[0]))
            own = np.take_along_axis(counts, ti[None], 0)[0]
            best = tones[counts.argmax(0)]
            upd = M & ~kp & (counts.max(0) > own)
            new[upd] = best[upd]
        t = new
    return t


# --------------------------------------------------------------------------
# Outlines: sel-out
# --------------------------------------------------------------------------
def _selout_apply(base: np.ndarray, dark_rgb: np.ndarray, lit_rgb: np.ndarray, light: Vec3,
                  diagonal: bool, lit_threshold: float) -> Image.Image:
    """Shared core: paint every transparent pixel touching the shape with
    the darkest touching material's outline colour (`dark_rgb`), or its
    lit-edge colour (`lit_rgb`) where the outward edge faces the light."""
    h, w = base.shape[:2]
    opaque = base[..., 3] > 0
    lum = np.where(opaque, dark_rgb[..., 0] * 0.299 + dark_rgb[..., 1] * 0.587 + dark_rgb[..., 2] * 0.114,
                   np.inf)
    best = np.full((h, w), np.inf)
    best_dark = np.zeros((h, w, 3), np.uint8)
    best_lit = np.zeros((h, w, 3), np.uint8)
    has4 = np.zeros((h, w), bool)
    has = np.zeros((h, w), bool)
    nxs = np.zeros((h, w))
    nys = np.zeros((h, w))
    for diag, offs in ((False, _N4), (True, _NDIAG)):
        for dx, dy in offs:
            nb = _neighbor(opaque, dx, dy, False)
            weight = 0.7 if diag else 1.0
            nxs -= np.where(nb, dx * weight, 0.0)
            nys -= np.where(nb, dy * weight, 0.0)
            if diag and not diagonal:
                continue
            nl = _neighbor(lum, dx, dy, np.inf)
            upd = nb & (nl < best)
            if diag:
                upd &= ~has4
            best = np.where(upd, nl, best)
            best_dark = np.where(upd[..., None], _neighbor(dark_rgb, dx, dy, 0), best_dark)
            best_lit = np.where(upd[..., None], _neighbor(lit_rgb, dx, dy, 0), best_lit)
            has |= nb
            if not diag:
                has4 |= nb
    lx, ly = light[0], light[1]
    ln = math.hypot(lx, ly) or 1.0
    nlen = np.maximum(np.hypot(nxs, nys), 1e-6)
    lit = (nxs * lx + nys * ly) / (nlen * ln) > lit_threshold
    target = ~opaque & has
    out = base.copy()
    col = np.where(lit[..., None], best_lit, best_dark)
    out[target, :3] = col[target]
    out[target, 3] = 255
    return Image.fromarray(out, "RGBA")


def _ramp_list(ramps: Mapping[str, Sequence[Sequence[int]]] | Sequence[Sequence[Sequence[int]]]
               ) -> list[Sequence[Sequence[int]]]:
    return list(ramps.values()) if isinstance(ramps, Mapping) else list(ramps)


def selout(src: Image.Image | Indexed,
           ramps: Mapping[str, Sequence[Sequence[int]]] | Sequence[Sequence[Sequence[int]]] | None = None,
           *, dark: Color | None = None, lit_tone: int | None = 1, light: Vec3 = LIGHT,
           diagonal: bool = False, lit_threshold: float = 0.35) -> Image.Image:
    """Sel-out exterior outline (docs/art_style.md): each outline pixel takes the
    darkest tone of the material it touches; on edges facing `light`
    (upper-front) it takes tone `lit_tone` of that ramp instead (None
    disables the lit swap). When several materials touch, the darkest wins.

    - `Indexed` input: materials are known exactly.
    - RGBA input with `ramps`: each pixel's material is the ramp containing
      its colour (exact match, else the nearest ramp colour).
    - RGBA input without ramps: the outline is `dark` (default OUTLINE),
      lit edges blend 35 % toward the touching pixel's colour.
    `dark` given together with a material source forces that fixed colour
    on the unlit edges (the classic "sel-out only where lit" look).
    `diagonal=True` also fills corner pixels (8-connected).
    Existing pixels are never changed; alpha stays 0/255.
    """
    if isinstance(src, Indexed):
        return src.selout(dark=dark, lit_tone=lit_tone, light=light, diagonal=diagonal,
                          lit_threshold=lit_threshold, ramps=ramps if isinstance(ramps, Mapping) else None)
    arr = np.array(src.convert("RGBA"))
    opaque = arr[..., 3] > 0
    dark_rgb = np.zeros(arr.shape[:2] + (3,), np.uint8)
    lit_rgb = np.zeros_like(dark_rgb)
    fixed = rgba(dark if dark is not None else OUTLINE)[:3]
    if ramps is None:
        dark_rgb[opaque] = fixed
        blend = np.array(fixed, np.float64) * 0.65 + arr[..., :3].astype(np.float64) * 0.35
        lit_rgb[opaque] = np.round(blend[opaque]).astype(np.uint8)
        if lit_tone is None:
            lit_rgb[opaque] = fixed
    else:
        rl = _ramp_list(ramps)
        flat = [(tuple(int(v) for v in c[:3]), ri) for ri, r in enumerate(rl) for c in r]
        exact = {c: ri for c, ri in reversed(flat)}
        cols = np.unique(arr[opaque][:, :3], axis=0) if opaque.any() else np.zeros((0, 3), np.uint8)
        for c in cols:
            key = tuple(int(v) for v in c)
            ri = exact.get(key)
            if ri is None:
                ri = min(flat, key=lambda e: sum((p - q) ** 2 for p, q in zip(e[0], key)))[1]
            r = rl[ri]
            sel = opaque & np.all(arr[..., :3] == c, axis=-1)
            d_col = fixed if dark is not None else tuple(r[0][:3])
            l_col = d_col if lit_tone is None else tuple(r[min(lit_tone, len(r) - 1)][:3])
            dark_rgb[sel] = d_col
            lit_rgb[sel] = l_col
    return _selout_apply(arr, dark_rgb, lit_rgb, light, diagonal, lit_threshold)


# --------------------------------------------------------------------------
# Noise, curves, secondary motion
# --------------------------------------------------------------------------
def value_noise(w: int, h: int, cell: float, seed: int = 0, tileable: bool = True) -> np.ndarray:
    """Smooth value noise in [0, 1], shape (h, w), lattice spacing ~`cell`
    px. `tileable=True` snaps the lattice to a whole number of cells per
    axis so the field wraps seamlessly (2x2 repeat shows no seam)."""
    rng = np.random.default_rng(seed)
    if tileable:
        gw, gh = max(1, round(w / cell)), max(1, round(h / cell))
        grid = rng.random((gh, gw))
        x = np.arange(w) * (gw / w)
        y = np.arange(h) * (gh / h)
    else:
        gw, gh = int(math.ceil(w / cell)) + 1, int(math.ceil(h / cell)) + 1
        grid = rng.random((gh, gw))
        x = np.arange(w) / cell
        y = np.arange(h) / cell
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx, fy = x - x0, y - y0
    if tileable:
        x1, y1 = (x0 + 1) % gw, (y0 + 1) % gh
        x0, y0 = x0 % gw, y0 % gh
    else:
        x1, y1 = x0 + 1, y0 + 1
    sx = fx * fx * (3 - 2 * fx)
    sy = fy * fy * (3 - 2 * fy)
    v00 = grid[y0[:, None], x0[None, :]]
    v01 = grid[y0[:, None], x1[None, :]]
    v10 = grid[y1[:, None], x0[None, :]]
    v11 = grid[y1[:, None], x1[None, :]]
    top = v00 + (v01 - v00) * sx[None, :]
    bot = v10 + (v11 - v10) * sx[None, :]
    return top + (bot - top) * sy[:, None]


def fbm(w: int, h: int, octaves: int = 4, cell: float = 16.0, gain: float = 0.5,
        lacunarity: float = 2.0, seed: int = 0, tileable: bool = True) -> np.ndarray:
    """Fractal (summed-octave) value noise in [0, 1], tileable by default.
    Octaves stop once the cell would fall under 1 px."""
    total = np.zeros((h, w))
    amp, norm, c = 1.0, 0.0, float(cell)
    for o in range(octaves):
        if c < 1.0:
            break
        total += amp * value_noise(w, h, c, seed + 7919 * o, tileable)
        norm += amp
        amp *= gain
        c /= lacunarity
    return total / (norm or 1.0)


def bezier(ctrl: Sequence[Point], t: float) -> Point:
    """De Casteljau evaluation for any number of control points."""
    pts = list(ctrl)
    while len(pts) > 1:
        pts = [lerp(pts[i], pts[i + 1], t) for i in range(len(pts) - 1)]
    return pts[0]


def bezier_curve(ctrl: Sequence[Point], samples: int) -> list[Point]:
    """`samples` points along a Bezier curve, both ends included."""
    return [bezier(ctrl, i / max(1, samples - 1)) for i in range(samples)]


def catmull_rom(points: Sequence[Point], samples: int = 8, closed: bool = False,
                alpha: float = 0.5) -> list[Point]:
    """Centripetal (alpha=0.5) Catmull-Rom spline through every point, with
    `samples` points per segment. Open curves end exactly on the last point."""
    pts = [(float(x), float(y)) for x, y in points]
    if len(pts) < 2:
        return pts
    if closed:
        ext = [pts[-1]] + pts + [pts[0], pts[1]]
        n_seg = len(pts)
    else:
        first = (2 * pts[0][0] - pts[1][0], 2 * pts[0][1] - pts[1][1])
        last = (2 * pts[-1][0] - pts[-2][0], 2 * pts[-1][1] - pts[-2][1])
        ext = [first] + pts + [last]
        n_seg = len(pts) - 1
    out: list[Point] = []

    def tj(ti: float, a: Point, b: Point) -> float:
        return ti + max(1e-6, math.hypot(b[0] - a[0], b[1] - a[1]) ** alpha)

    for s in range(n_seg):
        p0, p1, p2, p3 = ext[s], ext[s + 1], ext[s + 2], ext[s + 3]
        t0 = 0.0
        t1 = tj(t0, p0, p1)
        t2 = tj(t1, p1, p2)
        t3 = tj(t2, p2, p3)
        for k in range(samples):
            t = t1 + (t2 - t1) * k / samples

            def lin(a: Point, b: Point, ta: float, tb: float) -> Point:
                u = (t - ta) / (tb - ta)
                return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)

            a1, a2, a3 = lin(p0, p1, t0, t1), lin(p1, p2, t1, t2), lin(p2, p3, t2, t3)
            b1, b2 = lin(a1, a2, t0, t2), lin(a2, a3, t1, t3)
            out.append(lin(b1, b2, t1, t2))
    if not closed:
        out.append(pts[-1])
    return out


def verlet_chain(anchor_track: Sequence[Point], n_links: int, seg_len: float, *,
                 gravity: Point = (0.0, 0.35), damping: float = 0.9, stiffness: float = 1.0,
                 iterations: int = 8, loop: bool = True, warmup_cycles: int = 3,
                 ticks: Sequence[int] | None = None,
                 wind: Callable[[int, int], Point] | None = None,
                 rest_dir: Point = (0.0, 1.0),
                 rest_shape: Sequence[Point] | Callable[[int], Sequence[Point]] | None = None,
                 rest_pull: float = 0.0,
                 constrain: Callable[[int, int, Point], Point] | None = None) -> list[list[Point]]:
    """Secondary motion (cape, ponytail, ribbon tails, coat tails).

    `anchor_track` is the root position (shoulder, nape...) for each frame
    of an animation. The chain is integrated with Verlet steps; `ticks`
    gives the steps per frame (pass the animation's 60 Hz tick list so the
    simulation runs at game rate; default 1 step per frame), and the anchor
    moves linearly toward the next frame's position during those steps.

    Returns, for each frame, the n_links + 1 chain points (anchor first),
    sampled at the moment that frame starts showing.

    - loop=True: runs `warmup_cycles` full cycles first and records the
      next one, so the last frame flows into the first without a pop.
    - loop=False: settles on frame 0's anchor first, then plays once; the
      chain keeps moving during the last frame's ticks but is not recorded.
    - gravity / wind(frame, link) are per-step accelerations in px/tick^2.
      No module calls this today: the hero's followers step on their own
      (hero_rig.Chain; gravity 0.16-0.25, damping 0.78-0.86, drag =
      -world velocity * 0.05-0.14).
    - rest_shape (offsets from the anchor per point, or a per-frame
      callable) with rest_pull in 0..1 gives cloth a memory of its drape.
    - constrain(frame, link, point) -> point runs after every relaxation
      pass (keep the cape behind the back, above the floor, ...).
    Deterministic (pure float math, no randomness).
    """
    n_frames = len(anchor_track)
    if n_frames == 0:
        return []
    step_counts = [1] * n_frames if ticks is None else [max(1, int(t)) for t in ticks]
    if len(step_counts) != n_frames:
        raise ValueError("verlet_chain: ticks must match anchor_track")
    rd = math.hypot(*rest_dir) or 1.0
    rdx, rdy = rest_dir[0] / rd, rest_dir[1] / rd

    def shape_at(frame: int) -> Sequence[Point] | None:
        if rest_shape is None:
            return None
        return rest_shape(frame) if callable(rest_shape) else rest_shape

    ax0, ay0 = anchor_track[0]
    init = shape_at(0)
    if init is not None:
        pts = [(ax0 + init[i][0], ay0 + init[i][1]) for i in range(n_links + 1)]
    else:
        pts = [(ax0 + rdx * seg_len * i, ay0 + rdy * seg_len * i) for i in range(n_links + 1)]
    prev = list(pts)

    def step(frame: int, anchor: Point) -> None:
        nonlocal pts, prev
        gx, gy = gravity
        shp = shape_at(frame) if rest_pull else None
        new = [anchor]
        for i in range(1, n_links + 1):
            x, y = pts[i]
            vx, vy = (x - prev[i][0]) * damping, (y - prev[i][1]) * damping
            fx, fy = gx, gy
            if wind is not None:
                wx, wy = wind(frame, i)
                fx, fy = fx + wx, fy + wy
            nx_, ny_ = x + vx + fx, y + vy + fy
            if shp is not None:
                tx, ty = anchor[0] + shp[i][0], anchor[1] + shp[i][1]
                nx_ += (tx - nx_) * rest_pull
                ny_ += (ty - ny_) * rest_pull
            new.append((nx_, ny_))
        prev = list(pts)
        prev[0] = anchor
        cur = new
        for _ in range(iterations):
            cur[0] = anchor
            for i in range(n_links):
                (x0, y0), (x1, y1) = cur[i], cur[i + 1]
                dx, dy = x1 - x0, y1 - y0
                dist = math.hypot(dx, dy) or 1e-6
                diff = (dist - seg_len) / dist * stiffness
                if i == 0:
                    cur[i + 1] = (x1 - dx * diff, y1 - dy * diff)
                else:
                    cur[i] = (x0 + dx * diff * 0.5, y0 + dy * diff * 0.5)
                    cur[i + 1] = (x1 - dx * diff * 0.5, y1 - dy * diff * 0.5)
            if constrain is not None:
                for i in range(1, n_links + 1):
                    cur[i] = constrain(frame, i, cur[i])
        pts = cur

    def play_frame(f: int) -> None:
        a = anchor_track[f]
        b = anchor_track[(f + 1) % n_frames] if (loop or f + 1 < n_frames) else a
        n = step_counts[f]
        for s in range(1, n + 1):
            u = s / n
            step(f, (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u))

    if loop:
        for _ in range(max(0, warmup_cycles)):
            for f in range(n_frames):
                play_frame(f)
    else:
        for _ in range(max(1, warmup_cycles) * max(30, sum(step_counts))):
            step(0, anchor_track[0])
    out: list[list[Point]] = []
    for f in range(n_frames):
        pts[0] = anchor_track[f]
        out.append(list(pts))
        play_frame(f)
    return out


# --------------------------------------------------------------------------
# Pixel-art rotation (RotSprite-style)
# --------------------------------------------------------------------------
def _scale2x(p: np.ndarray) -> np.ndarray:
    """EPX / Scale2x on a 2-D array of packed colours."""
    A = _neighbor(p, 0, -1, 0)
    A[0] = p[0]
    D = _neighbor(p, 0, 1, 0)
    D[-1] = p[-1]
    C = _neighbor(p, -1, 0, 0)
    C[:, 0] = p[:, 0]
    B = _neighbor(p, 1, 0, 0)
    B[:, -1] = p[:, -1]
    h, w = p.shape
    out = np.empty((h * 2, w * 2), p.dtype)
    out[0::2, 0::2] = np.where((C == A) & (C != D) & (A != B), A, p)
    out[0::2, 1::2] = np.where((A == B) & (A != C) & (B != D), B, p)
    out[1::2, 0::2] = np.where((D == C) & (D != B) & (C != A), C, p)
    out[1::2, 1::2] = np.where((B == D) & (B != A) & (D != C), D, p)
    return out


def rot_sprite(img: Image.Image, angle_deg: float, center: Point | None = None,
               expand: bool = False) -> Image.Image:
    """Rotate pixel art without the shredding of a plain nearest rotate:
    Scale2x three times (8x), rotate with nearest sampling, then take the
    most common colour of every 8x8 block (a pixel is opaque only if at
    least half its block is). Positive angles turn clockwise on screen
    (Godot's rotation direction). `center` is in 1x pixel units (default
    the image centre); `expand` grows the canvas to fit."""
    src = np.ascontiguousarray(np.array(img.convert("RGBA")))
    src[src[..., 3] == 0] = 0
    h, w = src.shape[:2]
    packed = src.view(np.uint32).reshape(h, w)
    for _ in range(3):
        packed = _scale2x(packed)
    big = Image.fromarray(np.ascontiguousarray(packed).view(np.uint8).reshape(h * 8, w * 8, 4), "RGBA")
    ctr = None if center is None else (center[0] * 8, center[1] * 8)
    rot = big.rotate(-angle_deg, resample=Image.NEAREST, expand=expand, center=ctr,
                     fillcolor=(0, 0, 0, 0))
    ra = np.ascontiguousarray(np.array(rot))
    ra[ra[..., 3] == 0] = 0
    H, W = ra.shape[:2]
    oh, ow = (H + 7) // 8, (W + 7) // 8
    pad = np.zeros((oh * 8, ow * 8, 4), np.uint8)
    py, px_ = (oh * 8 - H) // 2, (ow * 8 - W) // 2
    pad[py:py + H, px_:px_ + W] = ra
    vals = np.ascontiguousarray(pad).view(np.uint32).reshape(oh * 8, ow * 8).astype(np.int64)
    blocks = vals.reshape(oh, 8, ow, 8).transpose(0, 2, 1, 3).reshape(oh, ow, 64)
    opaque_n = (blocks != 0).sum(-1)
    # transparent samples get unique negative ids so they never win the mode
    uniq = -(np.arange(64, dtype=np.int64) + 1)
    keyed = np.where(blocks != 0, blocks, uniq[None, None, :])
    s = np.sort(keyed, axis=-1)
    idx = np.arange(64)
    change = np.concatenate([np.ones(s.shape[:2] + (1,), bool), s[..., 1:] != s[..., :-1]], axis=-1)
    starts = np.maximum.accumulate(np.where(change, idx, 0), axis=-1)
    runlen = idx - starts + 1
    score = runlen * 2 + (s >= 0)
    mode = np.take_along_axis(s, score.argmax(-1)[..., None], -1)[..., 0]
    mode = np.where((opaque_n * 2 >= 64) & (mode > 0), mode, 0).astype(np.uint32)
    out = np.ascontiguousarray(mode).view(np.uint8).reshape(oh, ow, 4)
    return Image.fromarray(out, "RGBA")


# --------------------------------------------------------------------------
# FX and UI primitives
# --------------------------------------------------------------------------
def radial_halo(size: int | tuple[int, int], ramp: Sequence[Sequence[int]], falloff: float = 2.0,
                dither: Dither = "bayer4", center: Point | None = None,
                radius: float | None = None, thresholds: Sequence[float] | None = None) -> Image.Image:
    """Posterized round glow: intensity (1 - r/radius) ** falloff banded into
    `ramp` (dark outer ring -> bright core); below the first band is
    transparent. Dithered band edges by default (fine for halos and
    additive light layers). `thresholds` (len(ramp) cut points) override
    the uniform rings, e.g. 3 halo rings at 8/16/24 px."""
    w, h = (size, size) if isinstance(size, int) else size
    cx, cy = center if center is not None else (w / 2.0, h / 2.0)
    rad = radius if radius is not None else min(w, h) / 2.0
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.hypot(xx + 0.5 - cx, yy + 0.5 - cy) / max(rad, 1e-6)
    inten = np.clip(1.0 - r, 0.0, 1.0) ** falloff
    idx = quantize_to_ramp(inten, len(ramp) + 1, thresholds=thresholds, dither=dither) - 1
    idx = np.where(inten > 0, idx, -1)
    return indices_to_image(idx, ramp)


def gradient_bands(w: int, h: int, stops: Sequence[Sequence[int]], steps: int | None = None,
                   dither: Dither = None, horizontal: bool = False) -> Image.Image:
    """Stepped (posterized) gradient, opaque. With `steps=None` the stops
    themselves are the bands (e.g. RAMPS["ui_window"] top -> bottom);
    otherwise `steps` colours are interpolated between the stops. `dither`
    softens band edges with a Bayer pattern (UI windows, skies)."""
    if steps is None:
        cols = [tuple(int(v) for v in c[:3]) for c in stops]
    else:
        cols = []
        for i in range(steps):
            u = i / max(1, steps - 1) * (len(stops) - 1)
            k = min(int(u), len(stops) - 2) if len(stops) > 1 else 0
            cols.append(mix(stops[k], stops[min(k + 1, len(stops) - 1)], u - k) if len(stops) > 1
                        else tuple(int(v) for v in stops[0][:3]))
    n = len(cols)
    if horizontal:
        t = np.tile((np.arange(w) + 0.5) / w, (h, 1))
    else:
        t = np.tile(((np.arange(h) + 0.5) / h)[:, None], (1, w))
    return indices_to_image(quantize_to_ramp(t, n, dither=dither), cols)


def bevel_rect(d: ImageDraw.ImageDraw, box: tuple[float, float, float, float],
               light: Color | Sequence[Color], dark: Color | Sequence[Color], width: int = 2,
               fill: Color | None = None) -> None:
    """Bevelled frame inside `box` (x0, y0, x1, y1, inclusive): `light` on the
    top/left edges, `dark` on bottom/right, `width` rings deep. `light` and
    `dark` may be one colour or a list per ring (outer -> inner). The
    top-right and bottom-left corner pixels go to `dark`."""
    def ring_colors(c: Color | Sequence[Color]) -> list[Color]:
        if isinstance(c[0], (int, np.integer)):
            return [c] * width  # type: ignore[list-item]
        cs = list(c)  # type: ignore[arg-type]
        return [cs[min(i, len(cs) - 1)] for i in range(width)]

    lc, dc = ring_colors(light), ring_colors(dark)
    x0, y0, x1, y1 = box
    for k in range(width):
        rect(d, x0 + k, y0 + k, x1 - k, y0 + k, lc[k])
        rect(d, x0 + k, y0 + k, x0 + k, y1 - k, lc[k])
        rect(d, x0 + k, y1 - k, x1 - k, y1 - k, dc[k])
        rect(d, x1 - k, y0 + k, x1 - k, y1 - k, dc[k])
    if fill is not None and x1 - x0 >= 2 * width and y1 - y0 >= 2 * width:
        rect(d, x0 + width, y0 + width, x1 - width, y1 - width, fill)


# --------------------------------------------------------------------------
# Volumetric renderer: VolCanvas (4x lit primitives) -> Indexed (1x pixels)
# --------------------------------------------------------------------------
def _bresenham(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    pts: list[tuple[int, int]] = []
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        pts.append((x0, y0))
        if x0 == x1 and y0 == y1:
            return pts
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


class Indexed:
    """A 1x sprite as material + ramp tone per pixel (no colours yet).

    Arrays (h, w): `mat` (index into `mats`, -1 = transparent), `tone`
    (index into that material's ramp), `group` (index into `groups`;
    interior contours are drawn between different groups), `z` (painter
    depth of the part that won the pixel; higher = in front), `part` (the
    VolCanvas part id, -1 none, -2 stamped/stroked), `value` (the resolved
    0..1 intensity, for custom re-quantizing).

    Typical pipeline: VolCanvas.resolve() -> remove_orphans() ->
    interior_contours() -> stamp() / stroke() -> selout() (-> RGBA image).
    Every method that edits returns self, so calls chain.
    """

    def __init__(self, w: int, h: int, ramps: Mapping[str, Sequence[RGB]] | None = None) -> None:
        self.w, self.h = w, h
        self.ramps: Mapping[str, Sequence[RGB]] = RAMPS if ramps is None else ramps
        self.mat = np.full((h, w), -1, np.int16)
        self.tone = np.zeros((h, w), np.int16)
        self.group = np.full((h, w), -1, np.int16)
        self.z = np.zeros((h, w), np.float32)
        self.part = np.full((h, w), -1, np.int32)
        self.value = np.zeros((h, w), np.float32)
        self.mats: list[str] = []
        self.groups: list[str] = []

    # -- bookkeeping -------------------------------------------------------
    def mat_id(self, name: str) -> int:
        if name not in self.ramps:
            raise KeyError(f"unknown material {name!r} (not in ramps)")
        if name not in self.mats:
            self.mats.append(name)
        return self.mats.index(name)

    def group_id(self, name: str) -> int:
        if name not in self.groups:
            self.groups.append(name)
        return self.groups.index(name)

    def _tone(self, mat: str, tone: int) -> int:
        n = len(self.ramps[mat])
        t = tone + n if tone < 0 else tone
        return max(0, min(n - 1, t))

    def _front_z(self) -> float:
        return float(self.z.max()) + 1.0 if (self.mat >= 0).any() else 1.0

    def copy(self) -> Indexed:
        o = Indexed(self.w, self.h, self.ramps)
        for k in ("mat", "tone", "group", "z", "part", "value"):
            setattr(o, k, getattr(self, k).copy())
        o.mats, o.groups = list(self.mats), list(self.groups)
        return o

    def mask(self, *mats: str) -> np.ndarray:
        """Boolean mask of the pixels of the given materials (all opaque if none)."""
        if not mats:
            return self.mat >= 0
        ids = [self.mats.index(m) for m in mats if m in self.mats]
        return np.isin(self.mat, ids)

    # -- pixel edits -------------------------------------------------------
    def set_px(self, x: int, y: int, mat: str, tone: int, *, group: str | None = None,
               z: float | None = None) -> Indexed:
        if 0 <= x < self.w and 0 <= y < self.h:
            self.mat[y, x] = self.mat_id(mat)
            self.tone[y, x] = self._tone(mat, tone)
            self.group[y, x] = self.group_id(group or mat)
            self.z[y, x] = self._front_z() if z is None else z
            self.part[y, x] = -2
        return self

    def clear_px(self, x: int, y: int) -> Indexed:
        if 0 <= x < self.w and 0 <= y < self.h:
            self.mat[y, x] = -1
            self.group[y, x] = -1
            self.part[y, x] = -1
        return self

    def stamp(self, template: Sequence[str], origin: tuple[int, int],
              legend: Mapping[str, tuple[str, int] | None], *, flip_x: bool = False,
              group: str | None = None) -> Indexed:
        """Write a hand-authored 1x template (eyes, mouth, hands, buckles).
        `legend` maps a character to (material, tone) or None (= make
        transparent); "." and " " are skipped unless the legend names them.
        Negative tones count from the light end (-1 = lightest)."""
        ox, oy = origin
        width = max((len(r) for r in template), default=0)
        z = self._front_z()
        for j, row in enumerate(template):
            for i, ch in enumerate(row):
                if ch not in legend:
                    if ch in ". ":
                        continue
                    raise KeyError(f"stamp: character {ch!r} not in legend")
                x = ox + (width - 1 - i if flip_x else i)
                y = oy + j
                entry = legend[ch]
                if entry is None:
                    self.clear_px(x, y)
                else:
                    self.set_px(x, y, entry[0], entry[1], group=group, z=z)
        return self

    def stroke(self, points: Sequence[Point], mat: str, tone: int | Callable[[float], int],
               width: int = 1, *, closed: bool = False, group: str | None = None) -> Indexed:
        """1x polyline in a ramp tone (blades, whips, trims) drawn after
        quantizing so it stays crisp. `tone` may be a function of t in
        [0, 1] along the stroke (e.g. bright core near the hilt fading to
        the tip). `width` > 1 uses a square brush."""
        pts = [(int(round(x)), int(round(y))) for x, y in points]
        if closed and len(pts) > 2:
            pts.append(pts[0])
        pix: list[tuple[int, int]] = []
        for i in range(len(pts) - 1):
            seg = _bresenham(*pts[i], *pts[i + 1])
            pix.extend(seg if not pix else seg[1:])
        if len(pts) == 1:
            pix = list(pts)
        z = self._front_z()
        lo = -((width - 1) // 2)
        n = max(1, len(pix) - 1)
        for k, (x, y) in enumerate(pix):
            t = tone(k / n) if callable(tone) else tone
            for oy in range(lo, lo + width):
                for ox in range(lo, lo + width):
                    self.set_px(x + ox, y + oy, mat, t, group=group, z=z)
        return self

    def overlay(self, other: Indexed, dx: int = 0, dy: int = 0) -> Indexed:
        """Paste another Indexed (e.g. a separately rendered weapon) in front."""
        z = self._front_z()
        ys, xs = np.nonzero(other.mat >= 0)
        for y, x in zip(ys.tolist(), xs.tolist()):
            gname = other.groups[other.group[y, x]] if other.group[y, x] >= 0 else None
            self.set_px(x + dx, y + dy, other.mats[other.mat[y, x]], int(other.tone[y, x]),
                        group=gname, z=z + float(other.z[y, x]))
        return self

    # -- cleanup -----------------------------------------------------------
    def _keep_mask(self, keep: Iterable[str]) -> np.ndarray:
        return self.mask(*keep) if keep else np.zeros((self.h, self.w), bool)

    def remove_orphans(self, *, min_same: int = 3, keep: Iterable[str] = ("eye",)) -> Indexed:
        """Single stray tone pixels inside a material -> neighbours' tone."""
        self.tone = remove_orphans(self.tone, self.mat, min_same=min_same, keep=self._keep_mask(tuple(keep)))
        return self

    def majority(self, *, iterations: int = 1, keep: Iterable[str] = ("eye",)) -> Indexed:
        """3x3 per-material majority filter on tones (cluster cleanup)."""
        self.tone = majority(self.tone, self.mat, iterations=iterations, keep=self._keep_mask(tuple(keep)))
        return self

    def interior_contours(self, *, skip: Iterable[str] = ("eye", "gold"), tone: int = 0) -> Indexed:
        """Where a pixel touches (4-connected) a pixel of a different group
        that is in front of it, set it to `tone` (default the darkest) of
        its own ramp: the 1 px line that separates an arm from the coat
        behind it. Same-group parts (folds of one cloth) never get lines.
        Materials in `skip` neither receive nor cast contours."""
        skip_ids = {self.mats.index(m) for m in skip if m in self.mats}
        valid = self.mat >= 0
        own_ok = valid & ~np.isin(self.mat, list(skip_ids))
        hit = np.zeros((self.h, self.w), bool)
        for dx, dy in _N4:
            nm = _neighbor(self.mat, dx, dy, -1)
            ng = _neighbor(self.group, dx, dy, -1)
            nz = _neighbor(self.z, dx, dy, -np.inf)
            hit |= own_ok & (nm >= 0) & ~np.isin(nm, list(skip_ids)) & (ng != self.group) & (nz > self.z)
        for mi, name in enumerate(self.mats):
            sel = hit & (self.mat == mi)
            self.tone[sel] = self._tone(name, tone)
        return self

    # -- output ------------------------------------------------------------
    def to_rgba(self, ramps: Mapping[str, Sequence[RGB]] | None = None) -> Image.Image:
        """Colour the pixels from the ramps (alpha 0/255 only)."""
        rp = self.ramps if ramps is None else ramps
        out = np.zeros((self.h, self.w, 4), np.uint8)
        for mi, name in enumerate(self.mats):
            sel = self.mat == mi
            if sel.any():
                lut = ramp_array(rp[name])
                out[sel, :3] = lut[np.clip(self.tone[sel], 0, len(lut) - 1)]
                out[sel, 3] = 255
        return Image.fromarray(out, "RGBA")

    def selout(self, *, dark: Color | None = None, lit_tone: int | None = 1, light: Vec3 = LIGHT,
               diagonal: bool = False, lit_threshold: float = 0.35,
               ramps: Mapping[str, Sequence[RGB]] | None = None) -> Image.Image:
        """RGBA image with the sel-out exterior outline (see `selout()`)."""
        rp = self.ramps if ramps is None else ramps
        base = np.array(self.to_rgba(rp))
        dark_rgb = np.zeros((self.h, self.w, 3), np.uint8)
        lit_rgb = np.zeros_like(dark_rgb)
        fixed = None if dark is None else rgba(dark)[:3]
        for mi, name in enumerate(self.mats):
            sel = self.mat == mi
            r = rp[name]
            dark_rgb[sel] = r[0][:3] if fixed is None else fixed
            lit_rgb[sel] = (r[0][:3] if fixed is None else fixed) if lit_tone is None \
                else r[min(lit_tone, len(r) - 1)][:3]
        return _selout_apply(base, dark_rgb, lit_rgb, light, diagonal, lit_threshold)

    @classmethod
    def from_rgba(cls, img: Image.Image, ramps: Mapping[str, Sequence[RGB]] | None = None) -> Indexed:
        """Index an existing RGBA sprite: each opaque colour becomes the
        (material, tone) whose ramp colour matches exactly, else the nearest."""
        rp = RAMPS if ramps is None else ramps
        arr = np.array(img.convert("RGBA"))
        ix = cls(arr.shape[1], arr.shape[0], rp)
        flat = [(tuple(int(v) for v in c[:3]), name, t) for name, r in rp.items() for t, c in enumerate(r)]
        opaque = arr[..., 3] > 0
        for c in (np.unique(arr[opaque][:, :3], axis=0) if opaque.any() else []):
            key = tuple(int(v) for v in c)
            hit = next((e for e in flat if e[0] == key), None)
            if hit is None:
                hit = min(flat, key=lambda e: sum((p - q) ** 2 for p, q in zip(e[0], key)))
            sel = opaque & np.all(arr[..., :3] == c, axis=-1)
            ix.mat[sel] = ix.mat_id(hit[1])
            ix.tone[sel] = hit[2]
            ix.group[sel] = ix.group_id(hit[1])
            ix.z[sel] = 1.0
        return ix

    def color_count(self) -> int:
        """Distinct opaque colours the sprite will use."""
        pairs = {(int(m), int(t)) for m, t in zip(self.mat[self.mat >= 0].tolist(),
                                                  self.tone[self.mat >= 0].tolist())}
        return len({tuple(self.ramps[self.mats[m]][t]) for m, t in pairs})


class VolCanvas:
    """Supersampled, material-aware volumetric canvas (technique "D").

    Draw lit primitives back to front in 1x pixel coordinates (floats are
    fine; the canvas samples at `ss` x `ss` per pixel). Each call becomes a
    *part* with a material (a key of `ramps`), a group (default: the
    material name; interior contours separate different groups) and a
    painter depth. `resolve()` then picks, per 1x pixel, the front-most part
    covering at least `front_share` of the covered samples (else the most
    common part), averages that part's intensity and quantizes it into the
    part's ramp, so a pixel can never get an off-material colour.

    Shading: normals lit by `light` (default LIGHT) with the cool `rim`; per
    primitive `ambient`, `gamma`, `rim` strength, `spec`ular and `bias`
    (added to intensity; e.g. bias=-0.2 drops a far limb ~1 ramp step).
    `behind=True` draws a part only into still-empty samples and puts it
    behind everything drawn so far.
    """

    def __init__(self, w: int, h: int, ss: int = 4, *,
                 ramps: Mapping[str, Sequence[RGB]] | None = None,
                 light: Vec3 = LIGHT, rim: Vec3 = RIM) -> None:
        self.w, self.h, self.ss = w, h, ss
        self.ramps: Mapping[str, Sequence[RGB]] = RAMPS if ramps is None else ramps
        self.light = _unit3(light)
        self.rim_vec: Vec3 = _unit3(rim) if any(rim) else (0.0, 0.0, 0.0)
        self._part = np.full((h * ss, w * ss), -1, np.int32)
        self._inten = np.zeros((h * ss, w * ss), np.float32)
        self._xc = ((np.arange(w * ss) + 0.5) / ss).astype(np.float64)
        self._yc = ((np.arange(h * ss) + 0.5) / ss).astype(np.float64)
        self.mats: list[str] = []
        self.groups: list[str] = []
        self.part_names: list[str] = []
        self._part_mat: list[int] = []
        self._part_group: list[int] = []
        self._part_z: list[float] = []
        self._front = 0.0
        self._back = 0.0

    # -- plumbing ----------------------------------------------------------
    def _window(self, x0: float, y0: float, x1: float, y1: float
                ) -> tuple[slice, slice, np.ndarray, np.ndarray] | None:
        s = self.ss
        ix0 = max(0, int(math.floor(x0 * s)))
        ix1 = min(self.w * s, int(math.ceil(x1 * s)) + 1)
        iy0 = max(0, int(math.floor(y0 * s)))
        iy1 = min(self.h * s, int(math.ceil(y1 * s)) + 1)
        if ix0 >= ix1 or iy0 >= iy1:
            return None
        sx, sy = slice(ix0, ix1), slice(iy0, iy1)
        return sy, sx, self._xc[sx][None, :], self._yc[sy][:, None]

    def _poly_window(self, poly: Sequence[Point]) -> tuple[slice, slice, np.ndarray, np.ndarray,
                                                           np.ndarray] | None:
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        win = self._window(min(xs) - 1, min(ys) - 1, max(xs) + 1, max(ys) + 1)
        if win is None:
            return None
        sy, sx, X, Y = win
        s = self.ss
        im = Image.new("L", (sx.stop - sx.start, sy.stop - sy.start), 0)
        ImageDraw.Draw(im).polygon([(x * s - 0.5 - sx.start, y * s - 0.5 - sy.start) for x, y in poly],
                                   fill=255)
        return sy, sx, X, Y, np.array(im) > 0

    def _shade(self, nx: np.ndarray, ny: np.ndarray, nz: np.ndarray, ambient: float, gamma: float,
               rim: float, spec: float, bias: float) -> np.ndarray:
        i = shade_normals(nx, ny, nz, self.light, ambient=ambient, gamma=gamma, rim=rim,
                          rim_vec=self.rim_vec, spec=spec)
        return np.clip(i + bias, 0.0, 1.0)

    def _index(self, names: list[str], name: str) -> int:
        if name not in names:
            names.append(name)
        return names.index(name)

    def put(self, mask: np.ndarray, mat: str, intensity: np.ndarray | float, *,
            window: tuple[slice, slice] | None = None, group: str | None = None,
            behind: bool = False, name: str | None = None) -> int:
        """Low-level: write a part. `mask`/`intensity` cover `window` (sample
        rows, cols) or the whole sample grid. Returns the part id."""
        if mat not in self.ramps:
            raise KeyError(f"unknown material {mat!r} (not in ramps)")
        sy, sx = window if window is not None else (slice(None), slice(None))
        region = self._part[sy, sx]
        m = np.asarray(mask, bool)
        if behind:
            m = m & (region < 0)
        pid = len(self._part_z)
        if behind:
            self._back -= 1.0
            z = self._back
        else:
            self._front += 1.0
            z = self._front
        self._part_z.append(z)
        self._part_mat.append(self._index(self.mats, mat))
        self._part_group.append(self._index(self.groups, group or mat))
        self.part_names.append(name or f"{mat}{pid}")
        region[m] = pid
        vals = np.broadcast_to(np.asarray(intensity, np.float32), m.shape)
        self._inten[sy, sx][m] = vals[m]
        return pid

    # -- primitives --------------------------------------------------------
    def capsule(self, a: Point, b: Point, ra: float, rb: float, mat: str, *, spec: float = 0.0,
                flat: float = 1.0, ambient: float = 0.10, gamma: float = 1.5, rim: float = 0.35,
                bias: float = 0.0, group: str | None = None, behind: bool = False,
                name: str | None = None) -> int:
        """Tapered cylinder with round caps from a (radius ra) to b (rb):
        limbs, neck, belts. `flat` < 1 flattens the bulge toward the viewer."""
        r = max(ra, rb)
        win = self._window(min(a[0], b[0]) - r, min(a[1], b[1]) - r, max(a[0], b[0]) + r, max(a[1], b[1]) + r)
        if win is None:
            return -1
        sy, sx, X, Y = win
        vx, vy = b[0] - a[0], b[1] - a[1]
        ll = vx * vx + vy * vy + 1e-9
        t = np.clip(((X - a[0]) * vx + (Y - a[1]) * vy) / ll, 0.0, 1.0)
        dx, dy = X - (a[0] + vx * t), Y - (a[1] + vy * t)
        rr = ra + (rb - ra) * t
        dist = np.sqrt(dx * dx + dy * dy)
        nx, ny = dx / (rr + 1e-6), dy / (rr + 1e-6)
        nz = np.sqrt(np.clip(1.0 - nx * nx - ny * ny, 0.0, 1.0)) * flat
        inten = self._shade(nx, ny, nz, ambient, gamma, rim, spec, bias)
        return self.put(dist <= rr, mat, inten, window=(sy, sx), group=group, behind=behind, name=name)

    def ellipsoid(self, c: Point, rx: float, ry: float, mat: str, *, rot_deg: float = 0.0,
                  spec: float = 0.0, flat: float = 1.0, ambient: float = 0.10, gamma: float = 1.5,
                  rim: float = 0.35, bias: float = 0.0, group: str | None = None,
                  behind: bool = False, name: str | None = None) -> int:
        """Ellipsoid (head, chest, hands, skull, gems); `rot_deg` turns it
        clockwise on screen."""
        r = max(rx, ry)
        win = self._window(c[0] - r, c[1] - r, c[0] + r, c[1] + r)
        if win is None:
            return -1
        sy, sx, X, Y = win
        u, v = X - c[0], Y - c[1]
        cr, sr = math.cos(math.radians(rot_deg)), math.sin(math.radians(rot_deg))
        if rot_deg:
            u, v = u * cr + v * sr, -u * sr + v * cr
        qx, qy = u / rx, v / ry
        q = qx * qx + qy * qy
        nz = np.sqrt(np.clip(1.0 - q, 0.0, 1.0)) * flat
        nx, ny = (qx * cr - qy * sr, qx * sr + qy * cr) if rot_deg else (qx, qy)
        inten = self._shade(nx, ny, nz, ambient, gamma, rim, spec, bias)
        return self.put(q <= 1.0, mat, inten, window=(sy, sx), group=group, behind=behind, name=name)

    def cloth(self, poly: Sequence[Point], mat: str, *, folds: float = 3.0, amp: float = 0.55,
              axis: Point = (0.0, 1.0), phase: float = 0.0, fan: float = 0.08,
              base_n: Point = (0.0, 0.0), spec: float = 0.0, ambient: float = 0.18,
              gamma: float = 1.5, rim: float = 0.35, bias: float = 0.0, group: str | None = None,
              behind: bool = False, name: str | None = None) -> int:
        """Polygon of cloth with procedural fold normals (coat skirt, cape,
        capelet, drapes). Folds run along `axis` (the direction the cloth
        hangs); across it the normal swings by sin(phase), with phase =
        u * folds * 0.35 + v * fan + `phase`, u/v measured from poly[0]
        across/along the axis, so the fold pattern travels with the cloth.
        `folds` ~ fold frequency (2.2-4 reads well at hero scale), `amp`
        fold depth, `fan` makes folds spread toward the hem, animating
        `phase` walks the ridges, `base_n` tilts the whole sheet."""
        pw = self._poly_window(poly)
        if pw is None:
            return -1
        sy, sx, X, Y, mask = pw
        al = math.hypot(*axis) or 1.0
        ax_, ay_ = axis[0] / al, axis[1] / al
        ox, oy = poly[0]
        u = (X - ox) * ay_ - (Y - oy) * ax_
        v = (X - ox) * ax_ + (Y - oy) * ay_
        s = np.sin(u * folds * 0.35 + v * fan + phase)
        nx = s * amp * ay_ + base_n[0]
        ny = -s * amp * ax_ + base_n[1]
        nz = np.sqrt(np.clip(1.0 - nx * nx - ny * ny, 0.05, 1.0))
        inten = self._shade(nx, ny, nz, ambient, gamma, rim, spec, bias)
        return self.put(mask, mat, inten, window=(sy, sx), group=group, behind=behind, name=name)

    def ribbon(self, points: Sequence[Point], widths: float | Sequence[float], mat: str, *,
               back_mat: str | None = None, facing: Sequence[float] | None = None,
               curvature: float = 1.0, spec: float = 0.0, ambient: float = 0.12, gamma: float = 1.5,
               rim: float = 0.35, bias: float = 0.0, group: str | None = None, behind: bool = False,
               name: str | None = None) -> int:
        """Tapered strip swept along a polyline (ponytail, ribbon tails,
        cape from a verlet chain, whip). `widths` is the full width per
        point (or one value). The cross-section is a tube of `curvature`
        (1 round, 0 flat to the viewer). Two-sided cloth: with `back_mat`
        and per-point `facing` (sign: > 0 outside faces the viewer, < 0 the
        lining shows), each sample takes the side its interpolated facing
        selects; both sides share one group so they never get a contour.
        Returns the front part id."""
        pts = [(float(x), float(y)) for x, y in points]
        if len(pts) < 2:
            raise ValueError("ribbon needs at least 2 points")
        wl = [float(widths)] * len(pts) if isinstance(widths, (int, float)) else [float(v) for v in widths]
        if len(wl) != len(pts) or (facing is not None and len(facing) != len(pts)):
            raise ValueError("ribbon: widths/facing must match points")
        r = max(wl) / 2.0
        win = self._window(min(p[0] for p in pts) - r, min(p[1] for p in pts) - r,
                           max(p[0] for p in pts) + r, max(p[1] for p in pts) + r)
        if win is None:
            return -1
        sy, sx, X, Y = win
        shape = (Y.shape[0], X.shape[1])
        best = np.full(shape, np.inf)
        bnx = np.zeros(shape)
        bny = np.zeros(shape)
        bfac = np.ones(shape)
        for k in range(len(pts) - 1):
            (ax0, ay0), (bx0, by0) = pts[k], pts[k + 1]
            vx, vy = bx0 - ax0, by0 - ay0
            ll = vx * vx + vy * vy + 1e-9
            t = np.clip(((X - ax0) * vx + (Y - ay0) * vy) / ll, 0.0, 1.0)
            dx, dy = X - (ax0 + vx * t), Y - (ay0 + vy * t)
            rr = np.maximum((wl[k] + (wl[k + 1] - wl[k]) * t) / 2.0, 1e-6)
            q = np.sqrt(dx * dx + dy * dy) / rr
            upd = q < best
            best = np.where(upd, q, best)
            bnx = np.where(upd, dx / rr, bnx)
            bny = np.where(upd, dy / rr, bny)
            if facing is not None:
                bfac = np.where(upd, facing[k] + (facing[k + 1] - facing[k]) * t, bfac)
        mask = best <= 1.0
        nx, ny = bnx * curvature, bny * curvature
        nz = np.sqrt(np.clip(1.0 - nx * nx - ny * ny, 0.0, 1.0))
        inten = self._shade(nx, ny, nz, ambient, gamma, rim, spec, bias)
        if back_mat is None or facing is None:
            return self.put(mask, mat, inten, window=(sy, sx), group=group, behind=behind, name=name)
        g = group or mat
        pid = self.put(mask & (bfac >= 0), mat, inten, window=(sy, sx), group=g, behind=behind, name=name)
        self.put(mask & (bfac < 0), back_mat, inten, window=(sy, sx), group=g, behind=behind,
                 name=(name or mat) + "_back")
        return pid

    def heightfield(self, mask: np.ndarray, height: np.ndarray, mat: str, *,
                    origin: tuple[int, int] = (0, 0), strength: float = 2.2, spec: float = 0.0,
                    ambient: float = 0.10, gamma: float = 1.0, rim: float = 0.0, bias: float = 0.0,
                    group: str | None = None, behind: bool = False, name: str | None = None) -> int:
        """A 1x-authored relief (skull template, embossed plate, carved
        stone) placed with its top-left at `origin`: `mask` and `height`
        are (h, w) arrays at 1x; normals come from `heightmap_normals`."""
        m = np.asarray(mask, bool)
        hgt = np.asarray(height, np.float64)
        if m.shape != hgt.shape:
            raise ValueError("heightfield: mask and height shapes differ")
        nx, ny, nz = heightmap_normals(hgt, strength, wrap=False)
        inten = self._shade(nx, ny, nz, ambient, gamma, rim, spec, bias)
        s = self.ss
        big_m = np.repeat(np.repeat(m, s, 0), s, 1)
        big_i = np.repeat(np.repeat(inten, s, 0), s, 1)
        y0, x0 = origin[1] * s, origin[0] * s
        y1, x1 = y0 + big_m.shape[0], x0 + big_m.shape[1]
        cy0, cx0 = max(0, y0), max(0, x0)
        cy1, cx1 = min(self.h * s, y1), min(self.w * s, x1)
        if cy0 >= cy1 or cx0 >= cx1:
            return -1
        crop = (slice(cy0 - y0, cy1 - y0), slice(cx0 - x0, cx1 - x0))
        return self.put(big_m[crop], mat, big_i[crop], window=(slice(cy0, cy1), slice(cx0, cx1)),
                        group=group, behind=behind, name=name)

    def polygon(self, poly: Sequence[Point], mat: str, *, normal: Vec3 = (0.0, 0.0, 1.0),
                spec: float = 0.0, ambient: float = 0.10, gamma: float = 1.5, rim: float = 0.0,
                bias: float = 0.0, group: str | None = None, behind: bool = False,
                name: str | None = None) -> int:
        """Flat facet with one normal (blade flats, plates, gem facets)."""
        pw = self._poly_window(poly)
        if pw is None:
            return -1
        sy, sx, _, _, mask = pw
        n = _unit3(normal)
        inten = float(self._shade(np.array(n[0]), np.array(n[1]), np.array(n[2]), ambient, gamma,
                                  rim, spec, bias))
        return self.put(mask, mat, inten, window=(sy, sx), group=group, behind=behind, name=name)

    # -- resolve -----------------------------------------------------------
    def resolve(self, *, min_cover: float = 0.45, front_share: float = 0.3,
                smooth_sigma: float | None = None,
                thresholds: Mapping[str, Sequence[float]] | None = None) -> Indexed:
        """Downsample to an `Indexed` 1x sprite.

        - A pixel is opaque when >= `min_cover` of its samples are covered
          (no AA against transparency: alpha is 0 or 255).
        - Its part is the front-most one covering >= `front_share` of the
          covered samples, else the most common part.
        - Tone = that part's mean intensity quantized into its ramp
          (`thresholds[material]` overrides the uniform bands).
        - `smooth_sigma` (in samples; ~ss/2 recommended for animation)
          blurs intensity within each group first, so tone boundaries do
          not boil from frame to frame.
        """
        s, H, W = self.ss, self.h, self.w
        ix = Indexed(W, H, self.ramps)
        ix.mats, ix.groups = list(self.mats), list(self.groups)
        if not self._part_z:
            return ix
        inten = self._inten
        part_group = np.array(self._part_group, np.int32)
        if smooth_sigma:
            from scipy.ndimage import gaussian_filter
            pg = np.where(self._part >= 0, part_group[np.maximum(self._part, 0)], -1)
            sm = inten.astype(np.float64).copy()
            for g in np.unique(pg[pg >= 0]):
                M = (pg == g).astype(np.float64)
                num = gaussian_filter(inten * M, smooth_sigma, mode="constant")
                den = gaussian_filter(M, smooth_sigma, mode="constant")
                sm = np.where(M > 0, num / np.maximum(den, 1e-9), sm)
            inten = sm.astype(np.float32)
        pb = self._part.reshape(H, s, W, s).transpose(0, 2, 1, 3).reshape(H, W, s * s)
        ib = inten.reshape(H, s, W, s).transpose(0, 2, 1, 3).reshape(H, W, s * s)
        covered = (pb >= 0).sum(-1)
        present = np.unique(pb[pb >= 0])
        counts = np.stack([(pb == p).sum(-1) for p in present])
        zs = np.array(self._part_z, np.float64)[present]
        elig = (counts > 0) & (counts >= front_share * covered[None])
        score = np.where(elig, zs[:, None, None], -np.inf)
        best = np.where(elig.any(0), score.argmax(0), counts.argmax(0))
        chosen = present[best]
        opaque = (covered > 0) & (covered >= min_cover * s * s)
        sel = pb == chosen[..., None]
        val = (ib * sel).sum(-1) / np.maximum(sel.sum(-1), 1)
        part_mat = np.array(self._part_mat, np.int16)
        ix.mat = np.where(opaque, part_mat[chosen], -1).astype(np.int16)
        ix.group = np.where(opaque, part_group[chosen], -1).astype(np.int16)
        ix.z = np.where(opaque, np.array(self._part_z, np.float32)[chosen], 0).astype(np.float32)
        ix.part = np.where(opaque, chosen, -1).astype(np.int32)
        ix.value = np.where(opaque, val, 0).astype(np.float32)
        for mi, name in enumerate(ix.mats):
            m = ix.mat == mi
            if m.any():
                th = None if thresholds is None else thresholds.get(name)
                ix.tone[m] = quantize_to_ramp(ix.value[m], len(self.ramps[name]), thresholds=th)
        return ix


# --------------------------------------------------------------------------
# Sprite sheets + Godot SpriteFrames export
# --------------------------------------------------------------------------
class SheetBuilder:
    """Packs animation frames into a grid (one row per animation) and
    writes a matching Godot 4 `SpriteFrames` resource (.tres).

    Timing comes in one of two forms per animation:

    - `fps` alone (the original behaviour): every frame lasts `1 / fps` s,
      the .tres gets `"speed": fps` and `"duration": 1.0` per frame.
    - `ticks` (one int per frame, in 60 Hz ticks, SotN-style holds): the
      .tres gets `"speed": 60.0` and `"duration": float(ticks[i])`, so a
      frame lasts `ticks[i] / (60 * AnimatedSprite2D.speed_scale)` s. The
      JSON manifest then records `"fps": 60.0`, `"ticks"` and
      `"total_ticks"`; `fps` is ignored for playback.

    `origin` (optional) is the feet / pivot point inside a frame, written to
    the JSON so scene offsets are documented rather than guessed.
    """

    def __init__(self, name: str, frame_w: int, frame_h: int,
                 origin: tuple[int, int] | None = None) -> None:
        self.name = name
        self.fw = frame_w
        self.fh = frame_h
        self.origin = origin
        # list of (anim_name, frames, fps, loop)
        self.anims: list[tuple[str, list[Image.Image], float, bool]] = []
        # per-animation tick lists, parallel to `anims` (None = use fps)
        self.ticks: list[list[int] | None] = []

    def add(self, anim: str, frames: Iterable[Image.Image], fps: float, loop: bool,
            ticks: Sequence[int] | None = None) -> None:
        frame_list = list(frames)
        tick_list: list[int] | None = None
        if ticks is not None:
            tick_list = [int(t) for t in ticks]
            if len(tick_list) != len(frame_list):
                raise ValueError(f"{self.name}/{anim}: {len(frame_list)} frames but {len(tick_list)} ticks")
            if any(t < 1 for t in tick_list):
                raise ValueError(f"{self.name}/{anim}: every frame needs at least 1 tick")
        self.anims.append((anim, frame_list, fps, loop))
        self.ticks.append(tick_list)

    def save(self) -> None:
        cols = max(len(f) for _, f, _, _ in self.anims)
        rows = len(self.anims)
        sheet = Image.new("RGBA", (cols * self.fw, rows * self.fh), (0, 0, 0, 0))
        for r, (_, frames, _, _) in enumerate(self.anims):
            for c, fr in enumerate(frames):
                sheet.paste(fr, (c * self.fw, r * self.fh))
        png_path = os.path.join(SPRITES, f"{self.name}.png")
        sheet.save(png_path)
        self._write_sprite_frames()
        manifest: dict[str, dict[str, object]] = {}
        for i, (a, f, fps, loop) in enumerate(self.anims):
            entry: dict[str, object] = {"frames": len(f), "fps": fps, "loop": loop, "row": i}
            tick_list = self.ticks[i]
            if tick_list is not None:
                entry["fps"] = TICK_HZ
                entry["ticks"] = tick_list
                entry["total_ticks"] = sum(tick_list)
            manifest[a] = entry
        data: dict[str, object] = {"frame_size": [self.fw, self.fh]}
        if self.origin is not None:
            data["origin"] = [int(self.origin[0]), int(self.origin[1])]
        data["animations"] = manifest
        with open(os.path.join(SPRITES, f"{self.name}.json"), "w") as fh:
            json.dump(data, fh, indent=2)

    def _write_sprite_frames(self) -> None:
        lines: list[str] = ['[gd_resource type="SpriteFrames" format=3]', ""]
        lines.append(f'[ext_resource type="Texture2D" path="res://assets/sprites/{self.name}.png" id="1_sheet"]')
        lines.append("")
        sub_ids: dict[tuple[int, int], str] = {}
        for r, (_, frames, _, _) in enumerate(self.anims):
            for c in range(len(frames)):
                sid = f"AtlasTexture_r{r}c{c}"
                sub_ids[(r, c)] = sid
                lines.append(f'[sub_resource type="AtlasTexture" id="{sid}"]')
                lines.append('atlas = ExtResource("1_sheet")')
                lines.append(f"region = Rect2({c * self.fw}, {r * self.fh}, {self.fw}, {self.fh})")
                lines.append("")
        lines.append("[resource]")
        anim_strs: list[str] = []
        for r, (anim, frames, fps, loop) in enumerate(self.anims):
            tick_list = self.ticks[r]
            durations = [1.0] * len(frames) if tick_list is None else [float(t) for t in tick_list]
            speed = float(fps) if tick_list is None else TICK_HZ
            fr = ", ".join(
                '{\n"duration": %r,\n"texture": SubResource("%s")\n}' % (durations[c], sub_ids[(r, c)])
                for c in range(len(frames))
            )
            anim_strs.append(
                '{\n"frames": [%s],\n"loop": %s,\n"name": &"%s",\n"speed": %s\n}'
                % (fr, "true" if loop else "false", anim, speed)
            )
        lines.append("animations = [" + ", ".join(anim_strs) + "]")
        with open(os.path.join(FRAMES_RES, f"{self.name}_frames.tres"), "w") as fh:
            fh.write("\n".join(lines) + "\n")
