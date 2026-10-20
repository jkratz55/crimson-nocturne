"""
Parallax backgrounds for the Crimson Hall, far -> near:

    sky.png       night sky: dithered gradient, stars, a large maria-shaded
                  moon with a posterized halo                (scroll 0.03)
    clouds.png    drifting cloud bands with moonlit rims and stippled
                  (PS1 "50 % blend") fringes                 (scroll 0.06)
    castle.png    distant castle skyline: towers, spires, a bridge, lit
                  windows, a 1 px moon rim, mist at the base  (scroll 0.15)
    arcade.png    a moonlit gothic cloister arcade with pinnacles and a
                  belfry, mid distance, near-silhouette       (scroll 0.40)
    hall.png      the near interior wall behind the tiles: dark ashlar, a
                  cornice, fluted pilasters, a rose window with drapes, an
                  open arch with a balustrade, a twin-light lancet, a gilt
                  portrait and a wine-rose marble dado with moon shafts (the
                  quiet band behind the hero); openings are cut out so the
                  planes behind show through, and set-pieces use
                  background-graded ramps                    (scroll 0.70)

Depth is carried by value and colour falling toward indigo (docs/art_style.md,
Value plan): the further the plane, the darker, flatter and bluer it is.
Every plane is value-graded in the art itself (modulate stays white).

The layer stack is written to `assets/backgrounds/layers.json`, which the
room builder turns into one Parallax2D (+ Sprite2D, centered = false) per
entry. Godot's Parallax2D places a texel at
    screen = texel + offset - scroll_scale * camera_top_left
and every texture tiles seamlessly at its `repeat_size.x`.
"""
from __future__ import annotations

import json
import math
import os
from typing import Sequence

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from common import (
    BACKGROUNDS, COLORS, LIGHT_ENV, RAMPS, RGB, bayer, fbm, heightmap_normals, mix,
    quantize_to_ramp, remove_orphans, shade_normals, value_noise,
)

ROOM_W, ROOM_H = 768, 288          # castle_hall.tscn: 48 x 18 tiles
VIEW_W, VIEW_H = 384, 216
FLOOR_Y = 256                      # top of the ground-floor tiles
CEIL_Y = 32                        # underside of the ceiling tiles

Mask = np.ndarray


# ---------------------------------------------------------------------------
# Local ramps (dark -> light). Background versions of the shared registry:
# the back wall is STONE_BG plus one edge tone, light pools are the same
# ramp leaned warm (candles) or cool (moon) so a +1 step reads as light.
# ---------------------------------------------------------------------------
def _lean(ramp: Sequence[Sequence[int]], tint: Sequence[int], t: float) -> list[RGB]:
    return [mix(c, tint, t) for c in ramp]


FOG: RGB = (20, 18, 44)            # indigo aerial-perspective target (docs/art_style.md)
SCENE_FLOOR: RGB = (6, 4, 12)      # darkest value on screen
MOONLIGHT: RGB = (110, 130, 200)


def aerial(ramp: Sequence[Sequence[int]], desat: float, steps: float, fog_amt: float) -> list[RGB]:
    """Background version of a foreground ramp (docs/art_style.md, Palette):
    every tone takes the colour `steps` tones further down the ramp
    (fractional steps interpolate; below tone 0 it sinks toward the scene
    floor), is desaturated toward its own luminance by `desat` and lerped
    `fog_amt` toward the indigo fog. Same length as `ramp`, still ordered
    dark -> light, so set-pieces on the back wall keep their modelling but
    sit below the playfield's accents."""
    src = [np.array(c, np.float64) for c in ramp]
    floor = np.array(SCENE_FLOOR, np.float64)
    fog = np.array(FOG, np.float64)
    out: list[RGB] = []
    for i in range(len(src)):
        p = i - steps
        if p < 0.0:
            t = max(p, -1.0) + 1.0
            c = floor + (src[0] - floor) * t
        else:
            k = int(math.floor(p))
            f = p - k
            c = src[k] + (src[min(k + 1, len(src) - 1)] - src[k]) * f
        y = 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
        c = c + (y - c) * desat
        c = c + (fog - c) * fog_amt
        out.append((int(round(c[0])), int(round(c[1])), int(round(c[2]))))
    return out


WALL: list[RGB] = list(RAMPS["stone_bg"]) + [(70, 68, 102)]
WALL_MOON: list[RGB] = [mix(c, MOONLIGHT, 0.08 + 0.05 * i) for i, c in enumerate(WALL)]
# The ashlar field's (and the pilaster shafts') own copy of WALL: the face
# (tone 1) and the mortar / shadow tone (tone 0) are STONE_BG 1 / 0 x1.2,
# the same indigo hue and saturation one notch lighter (face Y 17 -> 20, mortar
# Y 9 -> 10). The hero's darkest contour (the Y ~6 cape line) then clears
# the faces by 12+ on the jump and fall, while his lit cape edge (Y ~29)
# still sits 9 above them. The lit chamfers (tones 2-3) are WALL's own.
ASHLAR: list[RGB] = [(10, 8, 22), (19, 17, 38)] + WALL[2:]
ASHLAR_MOON: list[RGB] = [mix(c, MOONLIGHT, 0.08 + 0.05 * i) for i, c in enumerate(ASHLAR)]
# Wainscot: a warm wine-rose marble graded for the back wall (hue 317-338,
# S 0.19-0.35). It is the quiet, mid-value field behind the hero's run
# line, so its steps are small (Y 49 / 53 / 57 / 65 / 75) and only 1 px
# lines reach the ends of the ramp. Value: everything wider than 1 px sits
# at Y >= 49, so both of the hero's contour families (the Y ~6 cape line
# and the Y 29-35 sel-out) clear it by 12+. Hue: the hero is indigo / navy
# (coat and cape mids 234-245 deg) plus crimson, so the dado takes the
# room's wine identity instead of his blue (~90 deg away) and stays far
# below the crimson accents in saturation (S <= 0.35 against 0.85).
MARBLE_BG: list[RGB] = [
    (40, 26, 36),       # 0  Y 31  behind the floor tiles only
    (62, 42, 54),       # 1  Y 49  veins, skirting, shadowed outer bevel
    (66, 46, 57),       # 2  Y 53  drifts, vein bleed, shadowed inner bevel
    (70, 50, 60),       # 3  Y 57  the field
    (78, 58, 68),       # 4  Y 65  clouding, cap rail, lit inner bevel, beads
    (88, 68, 78),       # 5  Y 75  cloud cores, lit outer bevel, plinth lip
    (112, 90, 98),      # 6  Y 97  1 px glints at the panels' lit corners
]
# Moonlight leans the rose marble to a cool mauve (hue ~275-290) and lifts
# it ~13 Y; with the 1-px checker seams that is the whole shaft.
MOON_LEAN = 0.18
GOLD_BG = aerial(RAMPS["gold"], 0.35, 1.5, 0.25)          # Y 9 / 21 / 38 / 62 / 98 / 132 (G5 unused)
VELVET_BG = aerial(RAMPS["velvet"], 0.30, 1.5, 0.25)

HALL_RAMPS: dict[str, list[RGB]] = {
    "wall": WALL,
    "wall_moon": WALL_MOON,
    "ashlar": ASHLAR,
    "ashlar_moon": ASHLAR_MOON,
    "velvet": VELVET_BG,
    "velvet_moon": _lean(VELVET_BG, MOONLIGHT, 0.10),
    "gold": GOLD_BG,
    "marble_bg": MARBLE_BG,
    # the rose marble under moonlight turns a cool mauve (hue ~290-300)
    "marble_bg_moon": _lean(MARBLE_BG, MOONLIGHT, MOON_LEAN),
    "lead": [(10, 8, 20), (16, 14, 32)],
    "glass": [(56, 8, 26), (124, 20, 44), (176, 40, 58), (39, 41, 147), (40, 90, 200),
              (140, 92, 30), (210, 160, 60)],
    "rose_glass": [(24, 20, 70), (34, 34, 110), (52, 60, 150), (54, 30, 90), (84, 48, 128),
                   (110, 18, 42), (156, 34, 54), (140, 92, 30), (196, 146, 60)],
    "moon": list(RAMPS["moon"]),
    # The portrait's oil paint, graded like the rest of the wall (top tone
    # <= (150, 120, 128)). Not a ramp: indices are named in PAINT below.
    "paint": [(12, 8, 16), (24, 16, 22), (38, 26, 30), (54, 38, 40), (72, 54, 52),
              (94, 72, 70), (120, 94, 94), (148, 118, 124),
              (16, 12, 26), (28, 22, 42), (50, 44, 72),
              (30, 18, 40), (46, 28, 58), (66, 42, 78),
              (88, 80, 96), (124, 116, 128), (128, 30, 44), (104, 64, 72)],
}
# paint indices: varnish/umber ground, skin, blue-black hair, violet gown, lace, a garnet
PAINT = dict(void=0, umber0=1, umber1=2, umber2=3, umber3=4, skin0=5, skin1=6, skin2=7,
             hair0=8, hair1=9, hair_sheen=10, gown0=11, gown1=12, gown2=13,
             lace0=14, lace1=15, garnet=16, lip=17)


# ---------------------------------------------------------------------------
# Plane: a material + tone canvas (one material ramp per pixel, -1 = clear)
# ---------------------------------------------------------------------------
class Plane:
    """Indexed canvas for one parallax layer. Every pixel holds a material
    (index into `names`, -1 transparent) and a tone into that material's
    ramp, so lighting passes can shift tones or swap ramps (warm/cool) and
    the output never contains an off-palette colour."""

    def __init__(self, w: int, h: int, ramps: dict[str, list[RGB]]) -> None:
        self.w, self.h = w, h
        self.ramps = ramps
        self.names = list(ramps)
        self.mat = np.full((h, w), -1, np.int16)
        self.tone = np.zeros((h, w), np.int16)
        self.alpha = np.full((h, w), 255, np.uint8)
        self.yy, self.xx = np.mgrid[0:h, 0:w]

    def mid(self, name: str) -> int:
        return self.names.index(name)

    def n(self, name: str) -> int:
        return len(self.ramps[name])

    def fill(self, mask: Mask, mat: str, tone: int | np.ndarray, alpha: int = 255) -> None:
        m = np.asarray(mask, bool)
        t = np.broadcast_to(np.asarray(tone, np.int16), m.shape)
        self.alpha[m] = alpha
        self.mat[m] = self.mid(mat)
        self.tone[m] = np.clip(t[m], 0, self.n(mat) - 1)

    def clear(self, mask: Mask) -> None:
        self.mat[np.asarray(mask, bool)] = -1

    def shift(self, mask: Mask, delta: int | np.ndarray, mats: Sequence[str] | None = None) -> None:
        m = np.asarray(mask, bool) & (self.mat >= 0)
        if mats is not None:
            m &= np.isin(self.mat, [self.mid(k) for k in mats])
        d = np.broadcast_to(np.asarray(delta, np.int16), m.shape)
        for name in self.names:
            sel = m & (self.mat == self.mid(name))
            self.tone[sel] = np.clip(self.tone[sel] + d[sel], 0, self.n(name) - 1)

    def swap(self, mask: Mask, pairs: dict[str, str]) -> None:
        """Re-ramp pixels (same tone index) e.g. wall -> wall_moon."""
        m = np.asarray(mask, bool)
        for src, dst in pairs.items():
            sel = m & (self.mat == self.mid(src))
            self.mat[sel] = self.mid(dst)
            self.tone[sel] = np.clip(self.tone[sel], 0, self.n(dst) - 1)

    def is_mat(self, *names: str) -> Mask:
        return np.isin(self.mat, [self.mid(k) for k in names])

    def to_image(self) -> Image.Image:
        out = np.zeros((self.h, self.w, 4), np.uint8)
        for name in self.names:
            sel = self.mat == self.mid(name)
            if not sel.any():
                continue
            lut = np.array(self.ramps[name], np.uint8)
            out[sel, :3] = lut[np.clip(self.tone[sel], 0, len(lut) - 1)]
            out[sel, 3] = self.alpha[sel]
        return Image.fromarray(out, "RGBA")


def quant(inten: np.ndarray, cuts: Sequence[float], dither: str | None = None,
          amount: float = 1.0, offset: tuple[int, int] = (0, 0)) -> np.ndarray:
    return quantize_to_ramp(inten, len(cuts) + 1, thresholds=cuts, dither=dither,
                            dither_amount=amount, offset=offset)


def periodic_dx(xx: np.ndarray, cx: float, w: int) -> np.ndarray:
    """Signed x distance to `cx` on a ring of width `w` (pixel centres)."""
    return ((xx + 0.5 - cx + w / 2.0) % w) - w / 2.0


def pointed_arch(xx: np.ndarray, yy: np.ndarray, x0: float, x1: float, spring: float,
                 bottom: float, r_factor: float = 1.0) -> Mask:
    """Pointed (two-centred) arch opening spanning x0..x1, straight jambs
    from `spring` down to `bottom`. r_factor 1.0 = equilateral arch."""
    span = x1 - x0
    r = span * r_factor
    px, py = xx + 0.5, yy + 0.5
    jamb = (px >= x0) & (px <= x1) & (py >= spring) & (py <= bottom)
    head = ((px - (x0 + r)) ** 2 + (py - spring) ** 2 <= r * r) & \
           ((px - (x1 - r)) ** 2 + (py - spring) ** 2 <= r * r) & (py < spring)
    return jamb | head


def round_arch(xx: np.ndarray, yy: np.ndarray, x0: float, x1: float, spring: float,
               bottom: float) -> Mask:
    cx, r = (x0 + x1) / 2.0, (x1 - x0) / 2.0
    px, py = xx + 0.5, yy + 0.5
    jamb = (px >= x0) & (px <= x1) & (py >= spring) & (py <= bottom)
    head = ((px - cx) ** 2 + (py - spring) ** 2 <= r * r) & (py < spring)
    return jamb | head


def edge_dist(mask: Mask) -> np.ndarray:
    """Distance (px) of every pixel outside `mask` to the mask."""
    return ndimage.distance_transform_edt(~np.asarray(mask, bool))


def inner_dist(mask: Mask) -> np.ndarray:
    return ndimage.distance_transform_edt(np.asarray(mask, bool))


def light_of(height: np.ndarray, strength: float, light: Sequence[float] = LIGHT_ENV,
             ambient: float = 0.15, gamma: float = 1.0, wrap: bool = True) -> np.ndarray:
    nx, ny, nz = heightmap_normals(height, strength, wrap)
    return shade_normals(nx, ny, nz, tuple(light), ambient=ambient, gamma=gamma, rim=0.0)


def neighbours(mask: Mask, dx: int, dy: int, wrap_x: bool = True) -> Mask:
    """mask shifted so out[y, x] = mask[y + dy, x + dx] (x wraps)."""
    m = np.asarray(mask, bool)
    out = np.roll(m, -dx, axis=1) if wrap_x else np.pad(m, ((0, 0), (max(0, -dx), max(0, dx))))[
        :, max(0, dx):max(0, dx) + m.shape[1]]
    if dy:
        out = np.roll(out, -dy, axis=0)
        if dy > 0:
            out[-dy:, :] = False
        else:
            out[:-dy, :] = False
    return out


def stipple(level: np.ndarray, offset: tuple[int, int] = (0, 0), n: int = 4) -> Mask:
    """Ordered-dither coverage: True where bayer threshold < level (0..1)."""
    return bayer(n, level.shape, offset) < level


def periodic_wave(w: int, x: np.ndarray, terms: Sequence[tuple[int, float, float]]) -> np.ndarray:
    """Sum of sines with integer frequencies over width w (seamless)."""
    out = np.zeros_like(x, dtype=np.float64)
    for k, amp, ph in terms:
        out += amp * np.sin(2 * math.pi * k * (x + 0.5) / w + ph)
    return out


# ===========================================================================
# L0 sky
# ===========================================================================
SKY_W, SKY_H = 480, 288
# The disc sits high in the hall's open arch: at the ground camera (top 72)
# it spans screen y 21-53, clear of the arch reveal above and of the row-8
# ledge (screen y 56) below, so the walkable lip never crosses it.
MOON_C = (258.0, 41.0)
MOON_R = 16.0
# Moon seas in disc units (cx, cy, rx, ry, rotation deg): an original
# arrangement, not a real lunar map.
MARIA = ((-0.30, -0.34, 0.42, 0.26, 28.0), (0.16, -0.06, 0.24, 0.36, -18.0),
         (-0.30, 0.30, 0.30, 0.16, 12.0), (0.52, 0.30, 0.15, 0.20, 10.0))


def _moon_tones(size: int, r: float) -> np.ndarray:
    """Tone indices (into RAMPS['moon'], -1 outside) of a full moon disc of
    radius `r` centred in a size x size box: bright disc, a lower-left limb
    crescent, three-tone seas and a rayed crater."""
    yy, xx = np.mgrid[0:size, 0:size]
    c = size / 2.0
    u, v = (xx + 0.5 - c) / r, (yy + 0.5 - c) / r
    rr = u * u + v * v
    disc = rr <= 1.0
    nz = np.sqrt(np.clip(1.0 - rr, 0.0, 1.0))
    lam = np.clip(0.34 * u - 0.30 * v + 0.89 * nz, 0.0, 1.0)
    edge_n = 0.5 * (value_noise(size, size, 6.0, seed=6, tileable=False) - 0.5)
    sea = np.zeros_like(u)
    for (mx, my, rx, ry, rot) in MARIA:
        a = math.radians(rot)
        du, dv = u - mx, v - my
        pu = (du * math.cos(a) + dv * math.sin(a)) / rx
        pv = (-du * math.sin(a) + dv * math.cos(a)) / ry
        sea = np.maximum(sea, 1.0 - np.sqrt(pu * pu + pv * pv) + 0.45 * edge_n)
    tone = np.full(u.shape, 3, np.int16)
    tone = np.where(lam < 0.40, 2, tone)                          # limb shade
    tone = np.where(sea > 0.05, 2, tone)                          # seas
    tone = np.where((sea > 0.50) & (lam < 0.97), 1, tone)         # their deep cores
    # a young rayed crater low on the disc
    cu, cv = 0.18, 0.58
    dc = np.hypot(u - cu, v - cv) * r
    tone = np.where(dc < 1.2, 3, tone)
    tone = np.where((dc >= 1.2) & (dc < 2.2), 2, tone)
    tone = np.where((dc >= 2.2) & (dc < 3.0) & (u - cu < 0), 3, tone)
    tone = np.where(disc, tone, -1).astype(np.int16)
    return remove_orphans(tone, min_same=3)


def build_sky() -> Image.Image:
    w, h = SKY_W, SKY_H
    yy, xx = np.mgrid[0:h, 0:w]
    stops: list[RGB] = list(RAMPS["sky"]) + [COLORS["sky_glow"]]
    # Zenith (only the top rows) -> horizon glow behind the castle foot.
    t = np.clip((yy + 0.5) / 176.0, 0.0, 1.0)
    tone = quant(t, [0.11, 0.31, 0.50, 0.69, 0.84], dither="bayer8", amount=0.6)
    out = np.array(stops, np.float64)[tone]

    # Posterized moon halo: three rings leaning the sky toward moonlight.
    d = np.hypot(xx + 0.5 - MOON_C[0], yy + 0.5 - MOON_C[1])
    halo = np.clip(1.0 - (d - MOON_R) / 46.0, 0.0, 1.0) ** 1.5
    ring = quant(halo, [0.10, 0.32, 0.62], dither="bayer4", amount=0.8)
    tints = (0.0, 0.14, 0.27, 0.42)
    moonlight = np.array((110, 130, 200), np.float64)
    for k in (1, 2, 3):
        sel = ring == k
        out[sel] = out[sel] + (moonlight - out[sel]) * tints[k]
    img = np.zeros((h, w, 4), np.uint8)
    img[..., :3] = np.round(out).astype(np.uint8)
    img[..., 3] = 255

    # Stars: 1 px, denser toward the zenith, none in the halo; six brighter
    # four-point stars (integration can twinkle them by blinking a copy).
    rng = np.random.default_rng(11)
    dim, bright = COLORS["star_dim"], COLORS["star"]
    for _ in range(190):
        x, y = int(rng.integers(0, w)), int(rng.integers(0, 170))
        if rng.random() > (1.0 - y / 190.0) ** 1.2:
            continue
        if math.hypot(x - MOON_C[0], y - MOON_C[1]) < MOON_R + 36:
            continue
        c = bright if rng.random() < 0.2 else dim
        if rng.random() < 0.4:
            c = mix(img[y, x, :3], dim, 0.5)
        img[y, x, :3] = c
    for (x, y) in ((40, 22), (152, 46), (196, 12), (414, 108), (452, 30), (98, 96), (336, 22)):
        img[y, x, :3] = bright
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            yy_, xx_ = (y + dy) % h, (x + dx) % w
            img[yy_, xx_, :3] = mix(img[yy_, xx_, :3], dim, 0.6)

    size = int(MOON_R * 2 + 4)
    mt = _moon_tones(size, MOON_R)
    x0, y0 = int(round(MOON_C[0] - size / 2.0)), int(round(MOON_C[1] - size / 2.0))
    lut = np.array(RAMPS["moon"], np.uint8)
    sub = img[y0:y0 + size, x0:x0 + size]
    sel = mt >= 0
    sub[sel, :3] = lut[mt[sel]]
    out_img = Image.fromarray(img, "RGBA")
    out_img.save(os.path.join(BACKGROUNDS, "sky.png"))
    return out_img


# ===========================================================================
# L0b clouds (transparent, crisp alpha). Billowed banks lit from the moon
# (upper right) with a 1 px moonlit rim; thin lens-shaped stratus wisps are
# semi-transparent (alpha ~45 %, the PS1 average blend) with a lit top edge.
# ===========================================================================
CLOUD_W, CLOUD_H = 480, 288
CLOUD_LIGHT = (0.55, -0.62, 0.55)
# The wisp across the moon: centre row in clouds.png (screen row + 6 at the
# ground camera, where the clouds plane sits 6 px up).
MOON_WISP_Y = 54
# Stratus wisps: (centre x, centre y, (segment, gap, segment[, gap, segment]),
# half thickness, bow). Segment and gap lengths in px.
WISPS: tuple[tuple[int, int, tuple[int, ...], float, float], ...] = (
    (60, 24, (34, 5, 26, 4, 18), 1.5, 1.5),
    (212, 32, (30, 4, 24), 1.3, -1.0),
    (404, 20, (38, 6, 30, 5, 26), 1.5, 2.0),
    (256, MOON_WISP_Y, (22, 4, 28, 5, 18), 1.5, 1.0),
    (444, 45, (30, 4, 20), 1.3, -1.5),
    (118, 114, (40, 6, 34, 5, 28), 1.5, 2.0),
    (336, 118, (36, 5, 30), 1.3, -1.0),
)


def _billow_bank(hf: np.ndarray, xx: np.ndarray, yy: np.ndarray, w: int, x0: float, length: float,
                 base: float, tall: float, rng: np.random.Generator) -> None:
    """Raise a cumulus bank into height field `hf` (in place): a row of
    domes whose radii swell toward the middle of the bank, on a flat base."""
    x = x0
    while x < x0 + length:
        t = (x - x0) / length
        swell = math.sin(math.pi * t) ** 0.7
        r = 3.0 + (tall * 0.55) * swell * (0.6 + 0.5 * rng.random())
        cy = base - r * 0.55 - tall * 0.25 * swell
        dx = periodic_dx(xx, x, w)
        dd = dx * dx + (yy + 0.5 - cy) ** 2
        dome = np.sqrt(np.clip(r * r - dd, 0.0, None))
        dome = np.where(yy + 0.5 <= base, dome, 0.0)
        np.maximum(hf, dome, out=hf)
        x += r * (0.9 + 0.5 * rng.random())
    slab = (np.abs(periodic_dx(xx, x0 + length / 2, w)) <= length / 2) & \
        (yy + 0.5 <= base) & (yy + 0.5 >= base - 3)
    np.maximum(hf, np.where(slab, 1.5, 0.0), out=hf)


def build_clouds() -> Image.Image:
    w, h = CLOUD_W, CLOUD_H
    yy, xx = np.mgrid[0:h, 0:w]
    rng = np.random.default_rng(31)
    hf = np.zeros((h, w))
    banks = (  # x0, length, base y, height
        (40, 96, 25, 9), (318, 120, 21, 10),          # high: they graze the moon's upper limb
        (8, 120, 100, 15), (156, 96, 92, 11), (300, 70, 104, 9), (388, 120, 98, 16),
        (60, 150, 132, 18), (250, 180, 128, 20), (440, 70, 136, 12),
    )
    for x0, length, base, tall in banks:
        _billow_bank(hf, xx, yy, w, x0, length, base, tall, rng)
    erode = fbm(w, h, 3, 6, seed=33) - 0.5
    solid = hf + 1.6 * erode > 0.9
    # shading: dome normals lit from the moon side
    nx, ny, nz = heightmap_normals(ndimage.gaussian_filter(hf, 1.0), 0.55, wrap=True)
    lit = shade_normals(nx, ny, nz, CLOUD_LIGHT, ambient=0.1, gamma=1.0, rim=0.0)
    tone = quant(lit, [0.42, 0.62])
    # undersides: the bottom rows of every bank sink a step and fray
    below = np.zeros_like(solid)
    for k in (1, 2, 3):
        below |= solid & ~np.roll(solid, -k, axis=0)
    tone = np.where(below & (tone > 0), tone - 1, tone)
    fray = solid & ~np.roll(solid, -1, axis=0) & ((xx + yy) % 2 == 0)
    solid &= ~fray
    # moonlit rim: contour pixels facing up / up-right
    up = ~np.roll(solid, 1, axis=0)
    up_r = ~np.roll(np.roll(solid, 1, axis=0), -1, axis=1)
    rim = solid & (up | up_r) & (lit > 0.45)
    tone = np.where(rim, 3, tone)
    # stratus wisps: each is broken into 2-3 tapered lens segments (1 px at
    # the tips, 3 px in the middle, 3-6 px gaps), gently bowed. The one at
    # y 54 starts across the lower third of the moon (screen y ~46-50 at the
    # ground camera, clear of the maria) and drifts off with the autoscroll;
    # only its middle segment, where it crosses the disc, keeps a moonlit
    # rim along the top.
    streak = np.zeros_like(solid)
    rim_ok = np.zeros_like(solid)
    wobble = value_noise(w, 1, 16.0, seed=41)[0] - 0.5
    for cx, cy, segs, th, bow in WISPS:
        total = sum(s for s in segs[0::2]) + sum(segs[1::2])
        x = cx - total / 2.0
        for i, length in enumerate(segs[0::2]):
            sc = x + length / 2.0
            dx = periodic_dx(xx, sc, w)
            t = np.clip(dx / length + 0.5, 0.0, 1.0)
            inside = np.abs(dx) < length / 2
            thick = th * np.sin(math.pi * t) ** 0.7
            tw = np.clip(periodic_dx(xx, cx, w) / total + 0.5, 0.0, 1.0)
            centre = cy + bow * (2 * tw - 1) ** 2 + 0.8 * wobble[None, :]
            seg = inside & (np.abs(yy + 0.5 - centre) <= np.maximum(thick, 0.5))
            streak |= seg
            if cy == MOON_WISP_Y and len(segs) > 2 and i == 1:
                rim_ok |= seg
            x += length + (segs[2 * i + 1] if 2 * i + 1 < len(segs) else 0)
    st_mask = streak & ~solid
    st_top = st_mask & ~np.roll(streak, 1, axis=0)
    st_rim = st_top & rim_ok
    mask = solid | st_mask
    tone = remove_orphans(np.where(solid, tone, -1), min_same=3)
    tone = np.where(st_mask, np.where(st_rim, 3, 2), tone)
    lut = np.array(RAMPS["cloud"], np.uint8)
    img = np.zeros((h, w, 4), np.uint8)
    img[mask, :3] = lut[np.clip(tone[mask], 0, 3)]
    img[mask, 3] = 255
    img[st_mask, 3] = 112            # average blend, like a PS1 semi-transparent quad
    img[st_top, 3] = 150
    out = Image.fromarray(img, "RGBA")
    out.save(os.path.join(BACKGROUNDS, "clouds.png"))
    return out


# ===========================================================================
# L1 distant castle skyline (three depth rows: a mountain ridge, a hazy back
# row and the front castle with a 1 px moon rim, all sinking into mist)
# ===========================================================================
CASTLE_W, CASTLE_H = 480, 288
CASTLE_GROUND = 132
FAR = {
    "ridge": (36, 30, 66), "ridge_rim": (50, 44, 84),
    "back": (30, 27, 56), "back_rim": (54, 52, 90),
    "body": (22, 20, 42), "body_sh": (17, 15, 34), "facet": (28, 26, 52), "rim": (100, 102, 150),
    "rim_dim": (60, 58, 94), "win": (150, 92, 46), "win_hi": (214, 150, 70),
    "rose": (110, 40, 44), "rose_hi": (170, 96, 60),
    "fog_lo": (30, 27, 58), "fog": (38, 35, 70), "fog_hi": (52, 50, 88),
}


class _Sil:
    """Silhouette drawing into a 3x wide label canvas so shapes that cross
    the texture edge wrap seamlessly when the copies are folded."""

    def __init__(self, w: int, h: int) -> None:
        self.w, self.h = w, h
        self.img = Image.new("L", (w * 3, h), 0)
        self.d = ImageDraw.Draw(self.img)
        self.windows: list[tuple[int, int]] = []

    def rect(self, x0: float, y0: float, x1: float, y1: float) -> None:
        self.d.rectangle([self.w + x0, y0, self.w + x1, y1], fill=1)

    def poly(self, pts: Sequence[tuple[float, float]]) -> None:
        self.d.polygon([(self.w + x, y) for x, y in pts], fill=1)

    def spire(self, cx: float, base: float, hw: float, height: float) -> None:
        self.poly([(cx - hw, base), (cx + hw, base), (cx, base - height)])
        self.rect(cx, base - height - 3, cx, base - height)

    def merlons(self, x0: float, x1: float, top: float, step: int = 4) -> None:
        x = x0
        while x <= x1 - 1:
            self.rect(x, top - 3, x + 1, top)
            x += step

    def tower(self, cx: float, hw: float, top: float, roof: str, ground: float = CASTLE_GROUND,
              buttress: bool = False, lit: int = 2) -> None:
        self.rect(cx - hw, top, cx + hw, ground)
        if roof == "spire":
            self.rect(cx - hw - 1, top, cx + hw + 1, top + 2)
            self.spire(cx, top, hw + 1, (hw + 1) * 3.3)
        elif roof == "cone":
            self.spire(cx, top, hw + 2, (hw + 2) * 1.8)
        elif roof == "crenel":
            self.rect(cx - hw - 1, top - 1, cx + hw + 1, top + 2)
            self.merlons(cx - hw - 1, cx + hw + 2, top - 1)
        if buttress:
            for sx in (-1, 1):
                bx = cx + sx * (hw + 1)
                self.poly([(bx, ground), (bx + sx * 4, ground), (bx + sx * 4, ground - 14),
                           (bx, ground - 22)])
        for k in range(lit):
            self.windows.append((int(round(cx)) + (k % 2) * 2 - 1, int(top + 8 + k * 10)))

    def mask(self) -> np.ndarray:
        a = np.array(self.img, bool)
        w = self.w
        return a[:, :w] | a[:, w:2 * w] | a[:, 2 * w:]


def build_castle() -> Image.Image:
    w, h = CASTLE_W, CASTLE_H
    yy, xx = np.mgrid[0:h, 0:w]
    g = CASTLE_GROUND
    # --- mountain ridge, farthest -------------------------------------------
    ridge_y = 114 + periodic_wave(w, xx[0].astype(np.float64), [(1, 5.0, 0.7), (3, 3.0, 2.1), (7, 1.5, 0.3)]) \
        + 2.0 * (value_noise(w, 1, 9.0, seed=71)[0] - 0.5)
    R = (yy + 0.5) >= ridge_y[None, :]
    # --- hazy back row -------------------------------------------------------
    back = _Sil(w, h)
    for cx, hw, top, roof in ((34, 6, 84, "spire"), (122, 5, 92, "cone"), (168, 7, 74, "spire"),
                              (296, 5, 82, "spire"), (350, 8, 76, "crenel"), (458, 5, 86, "spire")):
        back.tower(cx, hw, top, roof)
    back.poly([(-20, g), (40, 108), (130, 112), (240, 104), (330, 110), (420, 106), (500, g)])
    B = back.mask()
    # --- front castle ----------------------------------------------------------
    f = _Sil(w, h)
    f.tower(14, 6, 92, "cone", lit=1)
    # chapel: nave + gable, twin spire towers, a rose window
    f.rect(52, 96, 104, g)
    f.poly([(50, 96), (78, 76), (106, 96)])
    f.rect(77, 72, 79, 76)
    f.tower(56, 5, 64, "spire", buttress=True)
    f.tower(100, 5, 64, "spire", buttress=True)
    # curtain wall with a turret
    f.rect(104, 108, 176, g)
    f.merlons(104, 176, 108, 5)
    f.tower(140, 4, 92, "cone", lit=1)
    # the keep: crenellated block, an upper spire tower, a corbelled turret
    f.tower(214, 14, 50, "crenel", buttress=True, lit=3)
    f.tower(214, 7, 30, "spire", ground=50, lit=1)
    f.rect(226, 44, 234, 58)
    f.spire(230, 44, 5, 16)
    f.poly([(226, 58), (234, 58), (228, 64)])
    f.tower(188, 6, 76, "spire", lit=2)
    # great hall with a pitched roof
    f.rect(196, 92, 262, g)
    f.poly([(194, 92), (210, 80), (250, 80), (264, 92)])
    # bridge to the right-hand tower: deck, merlons, piers, pointed arches
    f.rect(262, 98, 400, 104)
    f.merlons(262, 400, 98)
    for px_ in range(268, 400, 22):
        f.rect(px_, 104, px_ + 5, g)
    f.tower(410, 11, 62, "spire", buttress=True, lit=3)
    f.tower(392, 4, 84, "cone", lit=1)
    f.tower(446, 7, 80, "crenel", lit=2)
    f.tower(470, 3, 96, "spire", lit=0)
    crag = [(-20.0, float(h))]
    for k in range(0, w + 41, 6):
        crag.append((-20.0 + k, g - 5 + 4 * math.sin(k * 0.09) + 2 * math.sin(k * 0.31 + 1)))
    crag.append((w + 20.0, float(h)))
    f.poly(crag)
    F = f.mask()
    for px_ in range(268, 400, 22):   # cut the bridge arches
        F &= ~pointed_arch(xx, yy, px_ + 6, px_ + 22, 114, g - 3, 0.8)

    img = np.zeros((h, w, 4), np.uint8)

    def put(mask: Mask, col: Sequence[int]) -> None:
        img[mask, :3] = col[:3]
        img[mask, 3] = 255

    put(R, FAR["ridge"])
    put(R & ~np.roll(R, 1, axis=0) & ~neighbours(R, 1, -1), FAR["ridge_rim"])
    put(B, FAR["back"])
    b_rim = B & ~neighbours(B, 1, 0) & ((yy % 4) != 0) & (yy < g - 6)
    put(b_rim, FAR["back_rim"])
    put(F, FAR["body"])
    put(F & ~neighbours(F, -1, 0), FAR["body_sh"])
    right = F & ~neighbours(F, 1, 0)
    top_r = F & ~neighbours(F, 0, -1) & ~neighbours(F, 1, -1)
    upper = yy < g - 10
    # moonlit facet just inside the rim: towers read round, not cut-out
    facet = F & ~right & (neighbours(right, 1, 0) | neighbours(right, 2, 0)) & upper
    put(facet, FAR["facet"])
    put(right & upper, FAR["rim"])
    put(right & ~upper & (yy < g - 2), FAR["rim_dim"])
    put(top_r & ~right & upper, FAR["rim_dim"])
    # windows: tiny warm lights, about half of the candidates lit
    rng = np.random.default_rng(13)
    for (wx, wy) in f.windows:
        wx %= w
        if wy + 1 >= g - 8 or rng.random() < 0.35:
            continue
        if F[wy, wx] and F[wy + 1, wx] and not right[wy, wx]:
            put((xx == wx) & ((yy == wy) | (yy == wy + 1)), FAR["win"])
            if rng.random() < 0.4:
                put((xx == wx) & (yy == wy), FAR["win_hi"])
    rose_d = np.hypot(xx + 0.5 - 78, yy + 0.5 - 103)
    rose = (np.abs(xx + 0.5 - 78) + np.abs(yy + 0.5 - 103) <= 1.6) & F
    put(rose, FAR["rose"])
    put(rose & (rose_d <= 0.8), FAR["rose_hi"])
    # mist: the castle foot dissolves into a moonlit fog bank (dithered top)
    fog_top = g - 14 + 6.0 * (fbm(w, 1, 3, 40, seed=17)[0] - 0.5) * 2
    lvl = np.clip(((yy + 0.5) - fog_top[None, :]) / 16.0, 0, 1)
    # moonlit crest of the fog bank, then it sinks darker with depth: the
    # mid-ground arches look down into it, so it must read as distance
    put(stipple(np.clip(lvl * 2.0, 0, 1)) & (lvl > 0), FAR["fog"])
    crest = (lvl > 0.28) & (lvl <= 0.5)
    put(crest & stipple(np.clip((lvl - 0.28) * 4.0, 0, 1)), FAR["fog_hi"])
    put(lvl > 0.5, FAR["fog_hi"])
    deep = np.clip(((yy + 0.5) - (g + 8)) / 22.0, 0, 1)
    put((lvl > 0.5) & stipple(deep), FAR["fog"])
    put(yy >= g + 30, FAR["fog"])
    deeper = np.clip(((yy + 0.5) - (g + 34)) / 24.0, 0, 1)
    put((yy >= g + 30) & stipple(deeper), FAR["fog_lo"])
    put(yy >= g + 58, FAR["fog_lo"])
    out = Image.fromarray(img, "RGBA")
    out.save(os.path.join(BACKGROUNDS, "castle.png"))
    return out


# ===========================================================================
# L2 mid-distance arcade: an open gothic gallery-bridge seen against the
# moon, so its faces are in shadow and only right/top contours catch a rim.
# 128 px modules: a buttress pier with a crocketed pinnacle, four pointed
# arches on slender columns, a pierced parapet; one belfry per 512 px.
# ===========================================================================
ARCADE_W, ARCADE_H = 512, 288
MID = {
    "face": (13, 11, 28), "face_sh": (9, 7, 20), "deep": (7, 5, 16),
    "edge": (24, 22, 44), "rim": (62, 62, 102), "rim_hi": (96, 100, 150),
    "jamb": (20, 18, 38), "fog_lo": (24, 22, 46), "fog": (32, 29, 60), "win": (120, 74, 40),
}
A_ROOF = 156          # top of the cornice / foot of the parapet
A_SPRING = 178        # arch springline
A_FLOOR = 216         # gallery floor / podium top
A_BELFRY = 84         # top of the belfry walls


def build_arcade() -> Image.Image:
    w, h = ARCADE_W, ARCADE_H
    yy, xx = np.mgrid[0:h, 0:w]
    X, Y = xx + 0.5, yy + 0.5
    solid = (yy >= A_ROOF) & (yy < A_FLOOR + 40)
    solid |= yy >= A_FLOOR
    openings = np.zeros((h, w), bool)
    for m in range(w // 128):
        for a0 in (10, 38, 66, 94):
            openings |= pointed_arch(xx, yy, m * 128 + a0, m * 128 + a0 + 24, A_SPRING, A_FLOOR, 0.85)
    # spandrel trefoils (dark, not pierced)
    tref = np.zeros((h, w), bool)
    for m in range(w // 128):
        for cx in (36, 64, 92):
            for ox, oy in ((-1.6, 1.0), (1.6, 1.0), (0.0, -1.4)):
                tref |= np.hypot(periodic_dx(xx, m * 128 + cx + ox, w), Y - (A_ROOF + 9 + oy)) <= 1.7
    # parapet: rail + pierced posts; cornice line below it
    rail = (yy >= A_ROOF - 11) & (yy < A_ROOF - 9)
    posts = (yy >= A_ROOF - 9) & (yy < A_ROOF - 2) & ((xx % 4) < 2)
    cornice = (yy >= A_ROOF - 2) & (yy < A_ROOF)
    solid |= rail | posts | cornice
    # little pinnacles over each column
    pin = np.zeros((h, w), bool)
    for m in range(w // 128):
        for cx in (36, 64, 92):
            dx = np.abs(periodic_dx(xx, m * 128 + cx, w))
            pin |= (dx <= 1.0) & (yy >= A_ROOF - 16) & (yy < A_ROOF - 9)
            pin |= (dx <= 0.6) & (yy >= A_ROOF - 19) & (yy < A_ROOF - 16)
    solid |= pin
    # buttress piers: stepped front, tall crocketed pinnacle
    pier = np.zeros((h, w), bool)
    for m in range(w // 128 + 1):
        cx = m * 128
        dx = np.abs(periodic_dx(xx, cx, w))
        pier |= (dx <= 10) & (yy >= A_ROOF - 12) & (yy < A_FLOOR + 40)
        pier |= (dx <= 6) & (yy >= A_ROOF - 26) & (yy < A_ROOF - 12)          # pinnacle shaft
        tip_h = 22.0
        tip = (Y >= A_ROOF - 26 - tip_h) & (yy < A_ROOF - 26) & \
              (dx <= 6.0 * (Y - (A_ROOF - 26 - tip_h)) / tip_h)
        pier |= tip
        pier |= (dx < 0.6) & (yy >= A_ROOF - 26 - tip_h - 4) & (Y < A_ROOF - 26 - tip_h)
        for k in range(4):                                                     # crockets
            cy = A_ROOF - 30 - k * 5
            half = 6.0 * (cy - (A_ROOF - 26 - tip_h)) / tip_h
            pier |= (np.abs(dx - half - 1.0) < 1.0) & (np.abs(Y - cy) < 1.0)
        pier |= (dx <= 8) & (yy >= A_ROOF - 28) & (yy < A_ROOF - 26)          # gablet ledge
    solid |= pier
    # balustrade inside each opening
    bal = openings & (((yy >= A_FLOOR - 13) & (yy < A_FLOOR - 11)) |
                      ((yy >= A_FLOOR - 11) & ((xx % 4) < 2)))
    # belfry over the pier at x = 384
    tcx, thw = 384.0, 18.0
    bt = A_BELFRY
    tower = (np.abs(X - tcx) <= thw) & (yy >= bt) & (yy < A_FLOOR + 40)
    t_open = np.zeros((h, w), bool)
    for ox in (-8.0, 8.0):
        t_open |= pointed_arch(xx, yy, tcx + ox - 4, tcx + ox + 4, bt + 34, bt + 60, 0.9)
    t_open |= pointed_arch(xx, yy, tcx - 10, tcx + 10, bt + 14, bt + 26, 0.85)
    cap = (np.abs(X - tcx) <= thw + 2) & (yy >= bt - 4) & (yy < bt)
    cren = (np.abs(X - tcx) <= thw + 2) & (yy >= bt - 8) & (yy < bt - 4) & (((xx - int(tcx)) % 5) < 3)
    sp_h = 40.0
    sp0 = bt - 8
    spire = (Y >= sp0 - sp_h) & (yy < sp0) & (np.abs(X - tcx) <= (thw - 5) * (Y - (sp0 - sp_h)) / sp_h)
    finial = (np.abs(X - tcx) < 0.6) & (Y >= sp0 - sp_h - 4) & (Y < sp0 - sp_h)
    t_full = (tower & ~t_open) | cap | cren | spire | finial
    solid = (solid & ~openings) | bal | pier | t_full
    solid &= ~(t_open & tower)

    img = np.zeros((h, w, 4), np.uint8)

    def put(mask: Mask, col: Sequence[int]) -> None:
        img[mask, :3] = col[:3]
        img[mask, 3] = 255

    put(solid, MID["face"])
    put(tref & solid, MID["deep"])
    put(solid & (yy >= A_FLOOR), MID["face_sh"])
    put((pier | t_full) & solid & ~(yy >= A_FLOOR), MID["face"])
    right = solid & ~neighbours(solid, 1, 0)
    left = solid & ~neighbours(solid, -1, 0)
    top = solid & ~neighbours(solid, 0, -1)
    bottom = solid & ~neighbours(solid, 0, 1)
    put(left | bottom, MID["face_sh"])
    put(top & ~right, MID["edge"])
    put(right & (yy < A_FLOOR + 4), MID["rim"])
    put(right & top, MID["rim_hi"])
    # the left jamb of each opening faces right, toward the moon
    jamb = solid & neighbours(openings & ~bal, 1, 0) & (yy >= A_SPRING - 12) & ~right
    put(solid & neighbours(jamb, 1, 0) & ~right & (yy >= A_SPRING - 12) & (yy < A_FLOOR - 13), MID["jamb"])
    # a faint lit window high in the belfry
    put((np.abs(X - tcx) < 1.0) & (yy >= bt + 18) & (yy < bt + 22) & t_open, MID["win"])
    # faint stone courses on the spandrel wall, piers and belfry
    course = solid & ~right & ~left & ~top & (((yy - A_ROOF) % 6) == 5) & (yy < A_FLOOR) & \
        ((((xx // 9) + (yy // 6)) % 3) != 0) & ~openings
    put(course & (img[..., 0] == MID["face"][0]), MID["face_sh"])
    # string course on the podium, then mist rising from below
    put((yy == A_FLOOR + 1) & solid, MID["edge"])
    put((yy == A_FLOOR + 2) & solid, MID["deep"])
    fog_top = A_FLOOR + 10 + 6.0 * (fbm(w, 1, 3, 48, seed=23)[0] - 0.5) * 2
    lvl = np.clip(((yy + 0.5) - fog_top[None, :]) / 22.0, 0, 1)
    put(stipple(np.clip(lvl * 2.2, 0, 1)) & (lvl > 0) & solid, MID["fog_lo"])
    put(stipple(np.clip((lvl - 0.5) * 2.0, 0, 1)) & solid, MID["fog"])
    out = Image.fromarray(img, "RGBA")
    out.save(os.path.join(BACKGROUNDS, "arcade.png"))
    return out


# ===========================================================================
# L3 near wall (the hall). 512 px = four 128 px bays between fluted
# pilasters (pilasters sit on every multiple of 128, so any 128-multiple
# repeat - including the old 256 fallback - is seamless):
#   A  a translucent stained-glass rose window over two blind lancets,
#      framed by velvet drapes on a gilt rod
#   C  open round arch with a balustrade, looking out on the night
#   D  a lancet: two leaded lights in a plate under a blind, diaper-carved
#      head (no oculus, so the hanging lamp in front never sits in a ring)
#   B  a gilt portrait of a lady (generic and original, not a likeness)
# Structure: cornice + dentils + corbels under the ceiling, a dark ashlar
# field, a wine-rose marble dado under a gilt chair rail, vignette at the
# top, moonlight.
#
# Value plan (shared with the hero and the playfield tiles). The hero keeps
# a dark sel-out contour (Y ~6) and a lit cape edge (Y ~29), so the wide
# faces behind him sit 12+ above the contour and below the cape edge:
#   - the ashlar faces are ASHLAR 1 (19, 17, 38), Y 20, with ASHLAR 0
#     (10, 8, 22) mortar and a lit (38, 36, 62) chamfer, so 1 px edges
#     carry the masonry; Y 20 clears the hero's Y ~6 contour by 12+ on the
#     jump and fall and stays 9 under his lit cape edge (Y ~29);
#   - the pilaster shafts are the same dark face with 1 px lit flute lines;
#   - the dado (the 48 px band behind the run line) is a quiet mid-value
#     wine-rose marble (hue ~330, away from the hero's indigo): faces Y
#     53-75, rails and skirting >= Y 49, 1 px veins and bevels only; median
#     Y ~57, low edge energy, no crimson accents;
#   - the chair rail (gilt, Y <= 65) sits above the hero's crown.
# Every set-piece on this plane uses background-graded ramps (aerial), so
# only the moon, moonlit glass and the playfield's own gold and candles read
# as bright. The wall paints no light sources of its own: every flame on
# screen is a real, breakable candle, so nothing painted can slide against
# one.
# ===========================================================================
HALL_W, HALL_H = 512, 288
BAY = 128
PIL_HW = 10                 # pilaster half width (shaft 20 px)
CORNICE_END = 56
WAINSCOT_Y = 200            # chair rail top: 56 px above the floor, over the hero's crown
BASE_Y = WAINSCOT_Y - 12    # pilaster attic bases, rows 188-199
ROSE = dict(cx=64.0, cy=112.0, r=24.0)
ARCH = dict(cx=192.0, x0=158.0, x1=226.0, spring=122.0, bottom=float(WAINSCOT_Y))
LANCET = dict(cx=320.0, x0=296.0, x1=344.0, spring=114.0, sill=184.0)
# The lancet's two lights spring here; their heads peak at row ~126, just
# under the moon's lowest row at the ground camera (125), so the moon never
# shows as a stray sliver in them.
LIGHT_SPRING = 141.0
# The portrait sits 12 px left of its bay's centre: at the right end of the
# room (camera x ~350-384) the candle at (664, 168) stands just right of it,
# and this keeps even that candle's outer halo ring (r 24) off the frame.
FRAME = dict(x0=412, y0=84, x1=460, y1=148)
# The art is authored with pilasters on multiples of 128 and then rolled
# right by HALL_ROLL, so at the opening camera (x 0..4) the pilasters hide
# behind the playfield piers at x 192 / 320 and the open arch frames the
# moon in the bay between them; they drift apart as the camera moves.
# After the roll the rose is centred on texel 128, the arch on 256, the
# lancet on 384 and the portrait on 500. A texel t meets a real candle at
# world x c when t - 0.7 cx = c - cx, so over the camera range (cx 0..384)
# each candle sweeps the 115 texels left of it. Planned against every
# candle in the room builder (candles at (40, 96), (248, 224), (408, 112),
# (520, 224), (664, 168)) over camera x 0..384 and tops 0..72, counting a
# candle's body (x-8..x+7, y-37..y-1) and its r 18 halo:
#   - no candle comes near the rose: the closest body stays 37 px outside
#     its moulding (67 px from its centre); only the (248, 224) candle's
#     halo touches the right drape's hem, at the screen's left edge;
#   - the chain-hung candle at (408, 112) sweeps texels 293-408, i.e. the
#     lancet, whose head is blind carved stone: a lamp in front of a dark
#     window, never inside a ring of tracery, and never over the moon (the
#     moon passes behind the lancet at the ground camera, but the lights
#     start below its lowest row);
#   - the portrait frame stays >= 16 px from every candle body and >= 7 px
#     from every halo at every camera that shows both.
HALL_ROLL = 64
# Dado layout (authored coordinates): two raised panels per bay between the
# pilaster pedestals, rows PANEL_TOP .. PANEL_BOT - 1.
PANELS = ((17, 62), (66, 111))
PANEL_TOP, PANEL_BOT = WAINSCOT_Y + 9, FLOOR_Y - 11
# Moonlight on the dado, one posterized shaft per window bay: (x of the
# shaft's left edge on the chair rail, width). They lean down-left at
# ~65 deg (dx/dy 0.47, docs/art_style.md) and pool for 2 rows at the floor line.
SHAFT_SLOPE = 0.47
SHAFT_SEAM = 1.0            # px of checker at each edge of a shaft
DADO_SHAFTS = ((46.0, 10.0), (186.0, 14.0), (309.0, 12.0))

# Cornice rows (wall tones), authored like a moulding profile: lit lips on
# top, shadowed undersides. Rows 39-44 are the frieze, 46-49 the dentils.
CORNICE_ROWS = {32: 5, 33: 4, 34: 4, 35: 3, 36: 3, 37: 2, 38: 0, 39: 1, 40: 1, 41: 1, 42: 1,
                43: 1, 44: 1, 45: 0, 46: 3, 47: 2, 48: 2, 49: 2, 50: 4, 51: 3, 52: 3, 53: 2,
                54: 1, 55: 0}
# Pilaster columns (u = 0..20 across the shaft): a lit left arris, then
# four flutes whose left walls fall in shadow (tone 0) and whose right walls
# catch the light in a 1 px line (tone 3), on ASHLAR 1 fillets, and a
# shadowed right arris. Like the ashlar (and in its ramp), the shaft is a
# dark face (Y 20) carried by 1 px lit lines, so the hero's Y 29-35 contour
# never sits on a mid-value column.
PILASTER_COLS = (4, 1, 0, 1, 4, 1, 0, 1, 4, 1, 0, 1, 4, 1, 0, 1, 4, 1, 1, 0, 0)


def _ashlar(w: int, h: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Pillowed 32x16 ashlar, staggered, 1 px mortar; returns height and a
    per-block id (-1 = mortar)."""
    yy, xx = np.mgrid[0:h, 0:w]
    bw, bh = 32, 16
    course = (yy - CEIL_Y) // bh
    off = np.where(course % 2 == 0, 0, bw // 2)
    lx = (xx + off) % bw
    ly = (yy - CEIL_Y) % bh
    col = (xx + off) // bw
    bid = (course * 97 + col * 13) % 4096
    edge = np.minimum.reduce([lx, ly, bw - 2 - lx, bh - 2 - ly]).astype(np.float64)
    mortar = (lx == bw - 1) | (ly == bh - 1)
    prof = np.clip((edge + 0.6) / 2.2, 0.0, 1.0) ** 0.65
    rng = np.random.default_rng(seed)
    lift = rng.random(4096)
    hgt = 0.55 * prof * (0.92 + 0.16 * lift[bid])
    rough = fbm(w, h, 3, 6, seed=seed + 1) - 0.5
    hgt = hgt + 0.09 * rough * prof
    hgt = np.where(mortar, 0.0, hgt)
    return hgt, np.where(mortar, -1, bid)


def _ashlar_tones(w: int, h: int, bias: np.ndarray, seed: int) -> np.ndarray:
    """ASHLAR tones of the back-wall ashlar field (32x16 blocks, staggered).

    Faces are ASHLAR 1 (Y 20), so the hero's Y ~6 cape line clears them by
    12+; the masonry reads through 1 px edges: a lit (38, 36, 62) chamfer
    on the top and left, an ASHLAR 0 shadow line on the bottom and right,
    ASHLAR 0 mortar. Blocks vary by about one step:
    most carry sparse tone-0 grain, a quarter are darker (dense grain) and
    one in six is lighter (tone-2 clouds), all in clusters of 2 px or more.
    Cast shadows (under the cornice, right of each pilaster) sink a step,
    and the chamfers dim to tone 2 in the top vignette."""
    yy, xx = np.mgrid[0:h, 0:w]
    bw, bh = 32, 16
    course = (yy - CEIL_Y) // bh
    off = np.where(course % 2 == 0, 0, bw // 2)
    lx = (xx + off) % bw
    ly = (yy - CEIL_Y) % bh
    col = (xx + off) // bw
    bid = (course * 97 + col * 13) % 4096
    mortar = (lx == bw - 1) | (ly == bh - 1)
    lit = ((ly == 0) | (lx == 0)) & ~((ly == 0) & (lx == bw - 2)) & ~((lx == 0) & (ly == bh - 2))
    shade = ((ly == bh - 2) | (lx == bw - 2)) & ~lit
    face = ~mortar & ~lit & ~shade
    rng = np.random.default_rng(seed + 5)
    kind = rng.choice(3, size=4096, p=[0.58, 0.25, 0.17])[bid]       # plain / dark / light
    grain = fbm(w, h, 2, 4, seed=seed + 6)
    lvl = np.where(kind == 1, 0.40, np.where(kind == 2, 0.14, 0.12))
    cut = np.quantile(grain, 1.0 - lvl)
    spot = ndimage.binary_opening(grain > cut, np.ones((2, 2), bool)) & face
    t = np.ones((h, w), np.int16)
    t[spot & (kind != 2)] = 0
    t[spot & (kind == 2)] = 2
    t[lit] = np.where(yy[lit] < 72, 2, 3)
    t[shade | mortar] = 0
    t = np.where(bias < -0.1, np.maximum(t - 1, 0), t)
    return t


def _hall_structure(P: Plane) -> tuple[np.ndarray, np.ndarray, Mask]:
    """Height field + light bias for the wall and every carved element above
    the dado. Returns (height, bias, architecture mask)."""
    w, h = P.w, P.h
    yy, xx = P.yy, P.xx
    X, Y = xx + 0.5, yy + 0.5
    hgt, bid = _ashlar(w, h, seed=21)
    bias = np.zeros((h, w))
    archm = np.zeros((h, w), bool)
    rng = np.random.default_rng(4)
    face_shift = rng.choice([-0.08, 0.0, 0.0, 0.0, 0.06, 0.09], size=4096)
    bias += np.where(bid >= 0, face_shift[np.clip(bid, 0, 4095)], 0.0)
    # the cornice casts a shadow on the wall below it
    bias += np.where((yy >= CORNICE_END) & (yy < CORNICE_END + 4), -0.16, 0.0)
    # corbels every 32 px under the cornice
    for k in range(w // 32):
        dx = np.abs(periodic_dx(xx, k * 32 + 16, w))
        corbel = (dx <= 3.0) & (yy >= CORNICE_END) & (yy < CORNICE_END + 8)
        rnd = np.clip(1.0 - ((Y - CORNICE_END) / 8.0) ** 2, 0, 1) * np.clip(1.0 - (dx / 3.4) ** 2, 0, 1)
        hgt = np.where(corbel, 0.7 + 0.6 * np.sqrt(rnd), hgt)
        archm |= corbel

    # pilasters: capital with volutes, fluted shaft (authored tones later), base
    for k in range(w // BAY):
        dx = periodic_dx(xx, k * BAY, w)
        adx = np.abs(dx)
        cap = (adx <= 13) & (yy >= CORNICE_END) & (yy < 70)
        cap_round = np.clip(1.0 - (adx / 13.5) ** 6, 0, 1)
        leaf = np.clip(np.cos(dx / 13.0 * math.pi * 1.5) * np.sin((Y - 60.0) / 8.0 * math.pi), 0, 1)
        cap_h = np.where(yy < 59, 1.5, np.where(yy < 67, 1.1 + 0.35 * leaf, np.where(yy < 69, 1.2, 0.9)))
        cap_h = cap_h * (0.55 + 0.45 * cap_round)
        for vx in (-10.0, 10.0):                       # volutes at the top corners
            dv = np.hypot(dx - vx, Y - 61.5)
            cap_h = np.where(cap & (dv <= 3.0), 1.2 + 0.5 * np.cos(dv * 1.6), cap_h)
        hgt = np.where(cap, cap_h, hgt)
        base = (adx <= 13) & (yy >= BASE_Y) & (yy < WAINSCOT_Y)
        tor = np.clip(1.0 - ((Y - (BASE_Y + 3.5)) / 2.6) ** 2, 0, 1)
        base_h = np.where(yy < BASE_Y + 6, 1.0 + 0.5 * tor, np.where(yy < BASE_Y + 8, 0.9, 1.25))
        base_h = base_h * (0.55 + 0.45 * np.clip(1 - (adx / 13.5) ** 6, 0, 1))
        hgt = np.where(base, base_h, hgt)
        archm |= cap | base
        # cast shadow on the wall right of the shaft (light from upper left)
        bias += np.where((dx > PIL_HW) & (dx <= PIL_HW + 3) & (yy >= 70) & (yy < BASE_Y), -0.14, 0.0)

    # lancet surround: moulded archivolt + keystone + projecting sill
    L = LANCET
    lancet = pointed_arch(xx, yy, L["x0"], L["x1"], L["spring"], L["sill"], 0.85)
    d_out = edge_dist(lancet)
    sur = (d_out > 0) & (d_out <= 6.5) & (yy < L["sill"])
    prof = np.where(d_out <= 1.5, 0.75, np.where(d_out <= 4.5, 1.25 - 0.12 * (d_out - 3.0) ** 2, 0.85))
    hgt = np.where(sur, prof, hgt)
    apex = L["spring"] - math.sqrt((48 * 0.85) ** 2 - (48 * 0.85 - 24) ** 2)
    key = (np.abs(X - L["cx"]) <= 3.0 + (apex - Y) * 0.25) & (Y >= apex - 10) & (Y < apex + 1)
    hgt = np.where(key & ~lancet, 1.45, hgt)
    sill = (np.abs(X - L["cx"]) <= 32) & (yy >= L["sill"]) & (yy < L["sill"] + 6)
    hgt = np.where(sill, np.where(yy < L["sill"] + 2, 1.4, 1.25 - 0.1 * (yy - L["sill"] - 2)), hgt)
    bias += np.where((np.abs(X - L["cx"]) <= 30) & (yy >= L["sill"] + 6) & (yy < L["sill"] + 9), -0.2, 0)
    archm |= sur | (key & ~lancet) | sill

    # round arch surround: voussoirs, keystone, imposts; balustrade inside
    A = ARCH
    arch = round_arch(xx, yy, A["x0"], A["x1"], A["spring"], A["bottom"])
    d_a = edge_dist(arch)
    band = (d_a > 0) & (d_a <= 8.0) & (yy < A["spring"] + 2)
    jambs = (d_a > 0) & (d_a <= 4.0) & (yy >= A["spring"] + 2) & (yy < A["bottom"])
    ang = np.degrees(np.arctan2(A["spring"] - Y, X - A["cx"]))
    vous = (np.abs(((ang + 7.5) % 15.0) - 7.5) < 1.0) & (Y < A["spring"]) & (d_a > 1.0)
    a_prof = np.where(d_a <= 1.5, 0.8, np.where(d_a <= 7.0, 1.25 - 0.02 * (d_a - 4.0) ** 2, 0.9))
    a_prof = np.where(vous, a_prof - 0.55, a_prof)
    hgt = np.where(band, a_prof, hgt)
    hgt = np.where(jambs, np.where(d_a <= 1.5, 0.8, 1.15), hgt)
    a_apex = A["spring"] - (A["x1"] - A["x0"]) / 2
    akey = (np.abs(X - A["cx"]) <= 4.0 + (a_apex - Y) * 0.22) & (Y >= a_apex - 11) & (Y < a_apex + 2)
    hgt = np.where(akey & ~arch, 1.6, hgt)
    imposts = np.zeros((h, w), bool)
    for sx in (A["x0"] - 9, A["x1"]):
        imp = (X >= sx) & (X < sx + 9) & (yy >= A["spring"] - 4) & (yy < A["spring"])
        hgt = np.where(imp, np.where(yy < A["spring"] - 2, 1.5, 1.25), hgt)
        imposts |= imp
    archm |= band | jambs | (akey & ~arch) | imposts
    return hgt, bias, archm


def build_hall() -> Image.Image:
    w, h = HALL_W, HALL_H
    P = Plane(w, h, HALL_RAMPS)
    yy, xx = P.yy, P.xx
    X, Y = xx + 0.5, yy + 0.5
    hgt, bias, archm = _hall_structure(P)
    L, A = LANCET, ARCH

    # --- light the stone from the upper left -----------------------------------
    inten = light_of(hgt * 2.2, 1.0, ambient=0.15)
    inten = inten * (0.62 + 0.38 * np.clip(hgt / 0.6, 0, 1))      # occlusion
    # top vignette (eased): the carved work darkens a little toward the
    # cornice so the playfield's gold cornice is the line that frames the room
    vign = np.clip((96.0 - yy) / 40.0, 0, 1) * 0.07
    inten = inten + bias - vign
    wall_t = quant(inten, [0.22, 0.38, 0.52, 0.72, 0.88])
    field = ~archm & (yy < WAINSCOT_Y)
    # the ashlar field is authored per block, not lit: dark faces (ASHLAR
    # 1) whose lit chamfers and dark mortar carry the masonry
    wall_t = np.where(field, _ashlar_tones(w, h, bias, seed=21), wall_t)
    P.fill(np.ones((h, w), bool), "wall", wall_t)
    P.swap(field, {"wall": "ashlar"})
    # cornice: authored profile rows, dentils, frieze rosettes
    for row, t in CORNICE_ROWS.items():
        P.fill(yy == row, "wall", t)
    dent = (yy >= 46) & (yy < 50) & ((xx % 6) < 3)
    P.fill(dent & (yy == 46), "wall", 4)
    P.fill(dent & (yy > 46) & ((xx % 6) == 0), "wall", 3)
    P.fill((yy >= 46) & (yy < 50) & ((xx % 6) >= 3), "wall", 0)
    P.fill((yy == 49) & ((xx % 6) < 3), "wall", 1)
    for k in range(w // 32):
        dr = np.hypot(periodic_dx(xx, k * 32 + 16, w), Y - 42.0)
        P.fill(dr <= 2.2, "wall", np.where(periodic_dx(xx, k * 32 + 16, w) + (Y - 42.0) < 0, 3, 2))
        P.fill(dr <= 0.8, "wall", 4)
    # pilaster shafts: authored flute columns, darker toward the cornice, in
    # the ashlar's own face and shadow tones
    for k in range(w // BAY):
        dx = periodic_dx(xx, k * BAY, w)
        u = np.floor(dx + PIL_HW).astype(int)
        shaft = (u >= 0) & (u <= 2 * PIL_HW) & (yy >= 70) & (yy < BASE_Y)
        cols = np.array(PILASTER_COLS, np.int16)[np.clip(u, 0, 2 * PIL_HW)]
        cols = cols - ((yy < 84) & (cols >= 3)).astype(np.int16)     # dimmer under the cornice
        P.fill(shaft, "ashlar", cols)
        _capital(P, k * BAY)
        _pilaster_base(P, k * BAY)
    _wainscot(P)
    P.fill(yy >= FLOOR_Y, "marble_bg", 0)          # behind the floor tiles

    # weathering: a damp stain on about one block in ten (a soft blotch one
    # step darker, clusters >= 2 px) and a hairline crack on one in thirty
    _, bid = _ashlar(w, h, seed=21)
    blot = ndimage.gaussian_filter(fbm(w, h, 3, 7, seed=12), 0.8)
    stained = np.zeros((h, w), bool)
    crack = np.zeros((h, w), bool)
    cn = value_noise(w, h, 3.0, seed=9)
    for cid in np.unique(bid[bid >= 0]):
        hsh = (int(cid) * 2654435761) % 30
        sel = bid == cid
        ys, xs = np.nonzero(sel)
        if len(ys) < 300 or ys.min() < 60 or ys.max() > WAINSCOT_Y - 4:
            continue
        if hsh in (0, 7, 14):
            local = blot[sel]
            stained[sel] = blot[sel] > np.percentile(local, 55)
        if hsh == 3:
            x0, y0 = int(np.median(xs)) - 2, int(ys.min()) + 2
            for k in range(11):
                cx_ = (x0 + int(round((cn[y0 + k, x0 % w] - 0.5) * 4.0))) % w
                if sel[y0 + k, cx_]:
                    crack[y0 + k, cx_] = True
    stained &= field & P.is_mat("wall", "ashlar")
    stained = ndimage.binary_opening(stained, np.ones((2, 2), bool))
    P.shift(stained, -1, ["wall", "ashlar"])
    ash = P.is_mat("ashlar")
    P.fill(crack & field & ash, "ashlar", 0)
    P.fill(crack & field & ~ash, "wall", 0)

    # --- lancet: reveals, two leaded lights in a blind plate, sill moon -------
    lancet = pointed_arch(xx, yy, L["x0"], L["x1"], L["spring"], L["sill"], 0.85)
    rev = inner_dist(lancet)
    reveal = lancet & (rev <= 3.0)
    left_half = X < L["cx"]
    P.fill(reveal & left_half, "wall_moon", 4)
    P.fill(reveal & left_half & (rev <= 1.0), "wall_moon", 3)
    P.fill(reveal & ~left_half, "wall", 1)
    P.fill(reveal & ~left_half & (rev <= 1.0), "wall", 0)
    P.fill(reveal & (yy >= L["sill"] - 3), "wall", 2)
    glass = lancet & ~reveal
    # Two lancet lights in a solid plate under the arch (plate tracery), no
    # oculus. The chain-hung candle at (408, 112) sweeps this bay (flame at
    # rows 75-92, goblet down to row 111) and the moon passes behind it at
    # the ground camera (hall rows ~93-125 for camera x ~150-220), so the
    # head above the lights (rows < ~126) is blind stone: the flame never
    # sits in a ring of tracery or over the moon's disc.
    lights = np.zeros((h, w), bool)
    for lx0, lx1 in ((L["x0"] + 4, L["cx"] - 2), (L["cx"] + 2, L["x1"] - 4)):
        lights |= pointed_arch(xx, yy, lx0, lx1, LIGHT_SPRING, L["sill"], 0.9)
    plate = glass & ~lights
    P.fill(plate, "wall", 1)
    # the plate is chamfered round each light: lit on the lights' right
    # (they face the light from the upper left), shadowed on their left
    ring = plate & (edge_dist(lights) <= 1.0)
    P.fill(ring & neighbours(lights, -1, 0), "wall", 3)
    P.fill(ring & neighbours(lights, 1, 0), "wall", 0)
    P.fill(ring & neighbours(lights, 0, 1) & ~neighbours(lights, 1, 0), "wall", 0)
    P.fill(ring & neighbours(lights, 0, -1), "wall", 2)
    # the blind head is carved with a diaper of raised lozenges continuing
    # the lights' quarry net (a fillet lit on its upper left, shadowed below)
    dia_a = (((xx - int(L["cx"])) + (yy - 100)) % 8) == 0
    dia_b = (((xx - int(L["cx"])) - (yy - 100)) % 8) == 0
    face = plate & ~ring & (edge_dist(reveal) > 1.0)
    P.fill(face & (dia_a | dia_b), "wall", 2)
    P.fill(face & ~(dia_a | dia_b) & (neighbours(dia_a, 0, -1) | neighbours(dia_b, 0, -1)), "wall", 0)
    # a 1 px shadow line just under the arch reveal
    P.fill(plate & neighbours(reveal, 0, -1) & ~ring, "wall", 0)
    # the lights are cut out, not glazed: leaded diamond quarries (1 px
    # cames, 8 px pitch) net them over the night behind
    bars = lights & glass & (dia_a | dia_b) & (yy < L["sill"] - 3)
    P.fill(bars, "lead", 1)
    P.clear(lights & glass & ~bars)
    # the sill catches one short glint of moon (not a ledge-length rail)
    sill_top = (yy == L["sill"]) & (np.abs(X - L["cx"]) <= 20)
    P.fill(sill_top, "wall_moon", 4)
    P.fill(sill_top & (np.abs(X - L["cx"]) <= 8), "moon", 0)

    # --- round arch: soffit reveal, open sky, balustrade ----------------------
    arch = round_arch(xx, yy, A["x0"], A["x1"], A["spring"], A["bottom"])
    a_rev = inner_dist(arch)
    b_top = int(A["bottom"]) - 30                     # balustrade rail top (row 170)
    a_reveal = arch & (a_rev <= 4.0) & (yy < b_top)
    moonlit = (X < A["cx"]) & (yy >= A["spring"] - 18)
    P.fill(a_reveal & moonlit, "wall_moon", 3)
    P.fill(a_reveal & moonlit & (a_rev <= 1.0), "wall_moon", 2)
    P.fill(a_reveal & ~moonlit, "wall", 1)
    P.fill(a_reveal & ~moonlit & (a_rev <= 1.0), "wall", 0)
    bx = (xx - int(A["x0"])) % 9
    rail_t = (yy >= b_top) & (yy < b_top + 5)
    rail_b = (yy >= b_top + 25) & (yy < b_top + 30)
    post_w = np.where(np.abs(yy - (b_top + 15)) < 3, 2.6, np.where(np.abs(yy - (b_top + 8)) < 2, 1.4, 1.8))
    post = (yy >= b_top + 5) & (yy < b_top + 25) & (np.abs(bx - 4.0) <= post_w)
    bal = arch & ~a_reveal & (rail_t | rail_b | post)
    b_u = (bx - 4.0) / np.maximum(post_w, 0.5)
    post_t = np.where(b_u < -0.4, 3, np.where(b_u < 0.35, 2, 1))
    P.fill(bal & post, "wall", post_t)
    P.fill(bal & post & (np.abs(yy - (b_top + 15)) < 3) & (b_u < -0.2), "wall", 4)
    P.fill(bal & rail_t, "wall", np.where(yy == b_top, 3, np.where(yy < b_top + 3, 2, 1)))
    P.fill(bal & rail_b, "wall", np.where(yy == b_top + 25, 3, 2))
    # moon catches only the post caps along the rail, never the whole rail
    P.fill(bal & (yy == b_top) & ((bx >= 3) & (bx <= 5)), "wall_moon", 3)
    P.clear(arch & ~a_reveal & ~bal)

    # --- dressing ---------------------------------------------------------------
    _rose_window(P)
    _drapes(P, ROSE["cx"] - 28.0, ROSE["cx"] + 28.0, swag_pad=10.0)
    _portrait(P)

    # --- baked moonlight: one shaft per window bay ------------------------------
    for x_rail, width in DADO_SHAFTS:
        from_sill = L["x0"] <= x_rail <= L["x1"]
        _moon_shaft(P, x_rail, width, L["sill"] + 6 if from_sill else float(WAINSCOT_Y))

    img = Image.fromarray(np.roll(np.array(P.to_image()), HALL_ROLL, axis=1), "RGBA")
    img.save(os.path.join(BACKGROUNDS, "hall.png"))
    return img


def _wainscot(P: Plane) -> None:
    """Wine-rose marble dado from the chair rail to the floor line.

    Rows (hall = world rows): a gilt chair rail (background gold, a 1 px G3
    bead on G1, Y <= 65) over the hero's crown, the cap rail (a 1 px cast
    shadow, a lit top, a groove), two raised panels per bay between the
    pilaster dies, a darker bottom rail, a lit plinth lip and the skirting. Nothing
    wider than 1 px is darker than tone 1 (Y 49), so the hero's dark contour
    always separates from it, and adjacent tones differ by <= 10 Y except
    on the 1 px bevels, so the band stays quiet behind the run line.

    Material: each panel is a polished slab - a tone-3 field with soft
    drifts (tone 2) and clouds (tone 4, cores tone 5) at a 6-10 px scale,
    streaked along the slab's grain, crossed by 2-3 broken, meandering 1 px
    tone-1 veins (25-55 deg, one branch each, bleeding into the field on
    their shadow side and catching a short sheen on the lit side), framed
    by a 2 px carved bevel lit from the upper left (outer ring tone 5 /
    tone 1, inner ring tone 4 / tone 2, a tone-6 glint in the lit corner).
    Neighbouring panels never share a seed or a grain direction. Stiles
    carry a 1 px bead; the pilaster dies project, with a sunk panel."""
    yy, xx = P.yy, P.xx
    w = P.w
    R, F = WAINSCOT_Y, FLOOR_Y
    P.fill((yy >= R) & (yy < F), "marble_bg", 3)
    # chair rail, then the cap rail: cast shadow, lit top, face, groove
    P.fill(yy == R, "gold", 2)
    P.fill(yy == R + 1, "gold", 3)
    P.fill(yy == R + 2, "gold", 1)
    P.fill(yy == R + 3, "marble_bg", 1)
    P.fill(yy == R + 4, "marble_bg", 5)
    P.fill(yy == R + 5, "marble_bg", 4)
    P.fill(yy == R + 7, "marble_bg", 2)
    # bottom rail (a step darker: the wall's bottom vignette), a lit plinth
    # lip, the skirting down to the floor line
    P.fill((yy >= PANEL_BOT) & (yy < F - 6), "marble_bg", 2)
    P.fill(yy == F - 6, "marble_bg", 4)
    P.fill((yy >= F - 5) & (yy < F), "marble_bg", 1)
    top, bot = PANEL_TOP, PANEL_BOT
    grain = {1: _marble_grain(w, P.h, 1, seed=52), -1: _marble_grain(w, P.h, -1, seed=57)}
    n_panel = 0
    for k in range(w // BAY):
        for j, (p0, p1) in enumerate(PANELS):
            x0, x1 = k * BAY + p0, k * BAY + p1
            pm = (xx >= x0) & (xx < x1) & (yy >= top) & (yy < bot)
            u, v = xx - x0, yy - top
            dl, dt, dr, db = u, v, (x1 - x0 - 1) - u, (bot - top - 1) - v
            ring = np.minimum.reduce([dl, dt, dr, db])
            lit_side = np.minimum(dl, dt) <= np.minimum(dr, db)
            face = pm & (ring >= 2)
            sign = 1 if (n_panel % 2 == 0) else -1
            n_panel += 1
            # clouding: per-panel quantiles so every slab carries the same
            # share of drift / field / cloud / core
            g = grain[sign]
            lo, hi, core = np.quantile(g[face], [0.16, 0.71, 0.95])
            t = np.where(g < lo, 2, np.where(g > core, 5, np.where(g > hi, 4, 3))).astype(np.int16)
            t = _min_clusters(t, face, 4)
            P.fill(face, "marble_bg", t)
            # veins
            rng = np.random.default_rng(1000 + 37 * k + 11 * j)
            vein, bleed, sheen = _veins(rng, x0, x1, top, bot, sign, pm & (ring >= 4))
            P.fill(bleed & face & ~vein, "marble_bg", 2)
            P.fill(sheen & face & ~vein, "marble_bg", 4)
            P.fill(vein & face, "marble_bg", 1)
            # 2 px carved bevel, lit from the upper left
            P.fill(pm & (ring == 0), "marble_bg", np.where(lit_side, 5, 1))
            P.fill(pm & (ring == 1), "marble_bg", np.where(lit_side, 4, 2))
            P.fill(pm & (u <= 1) & (v <= 1) & (ring == 0), "marble_bg", 6)
        # stile beads between and beside the panels
        for bx in (k * BAY + 14, k * BAY + 64, k * BAY + 113):
            P.fill((xx == bx) & (yy >= top) & (yy < bot), "marble_bg", 4)
        # the pilaster's die, projecting (lit left arris, shadowed right),
        # with a sunk panel (its top / left in shadow, bottom / right lit)
        pdx = periodic_dx(xx, k * BAY, w)
        fx = np.floor(pdx).astype(int)
        ped = (np.abs(pdx) <= 12) & (yy >= R + 6) & (yy < F - 6)
        P.fill(ped, "marble_bg", 3)
        P.fill(ped & (fx == -12), "marble_bg", 5)
        P.fill(ped & (fx == 11), "marble_bg", 1)
        sunk = (fx >= -7) & (fx <= 6) & (yy >= top + 3) & (yy < bot - 3)
        sr = np.minimum.reduce([fx + 7, yy - (top + 3), 6 - fx, (bot - 4) - yy])
        s_dark = np.minimum(fx + 7, yy - (top + 3)) <= np.minimum(6 - fx, (bot - 4) - yy)
        P.fill(sunk & (sr == 0), "marble_bg", np.where(s_dark, 1, 4))
    # (the floor-line pools and the moon shafts are added by _moon_shaft)


def _marble_grain(w: int, h: int, sign: int, seed: int) -> np.ndarray:
    """Cloud field for the marble slabs: tileable fbm at a ~9 px cell,
    smeared along a 45 deg grain (rising to the right for sign 1) so the
    clouds stretch the way the veins run."""
    base = fbm(w, h, 3, 9.0, seed=seed)
    k = np.zeros((7, 7))
    for i in range(7):
        k[6 - i if sign > 0 else i, i] = 1.0 / 7.0
    return ndimage.convolve(base, k, mode="wrap")


def _min_clusters(tone: np.ndarray, mask: Mask, min_px: int) -> np.ndarray:
    """Fold clusters of the non-field tones smaller than `min_px` inside
    `mask` back one step toward the field (tone 3), so the clouding is
    built from clusters, never single specks."""
    t = tone.copy()
    for level, back in ((5, 4), (4, 3), (2, 3)):
        sel = mask & (t == level)
        lab, n = ndimage.label(sel)
        if n:
            sizes = np.bincount(lab.ravel())
            small = sel & (sizes[lab] < min_px)
            t[small] = back
    return t


def _veins(rng: np.random.Generator, x0: int, x1: int, top: int, bot: int, sign: int,
           inner: Mask) -> tuple[Mask, Mask, Mask]:
    """2-3 meandering 1 px veins braiding across one panel, each 22-40 px
    long at 25-55 deg (rising for sign 1, falling for -1), broken by a 1 px
    gap every 5-9 px, with one short branch. A vein bleeds a 1 px tone-2 edge
    into the field on its lower side for part of its run and catches a
    short sheen on its upper side elsewhere. Returns (vein, bleed, sheen)."""
    h, w = inner.shape
    vein = np.zeros((h, w), bool)
    bleed = np.zeros((h, w), bool)
    sheen = np.zeros((h, w), bool)

    def walk(x: float, y: float, base: float, length: int, gaps: bool) -> list[tuple[int, int]]:
        pts: list[tuple[int, int]] = []
        drift = 0.0
        gap_at = int(rng.integers(5, 10))
        run = 0
        for _ in range(length):
            drift = float(np.clip(0.82 * drift + rng.normal(0.0, 0.13), -0.38, 0.38))
            x += math.cos(base + drift)
            y += math.sin(base + drift)
            p = (int(round(x)), int(round(y)))
            if pts and p == pts[-1]:
                continue
            run += 1
            if gaps and run >= gap_at:
                run = 0
                gap_at = int(rng.integers(5, 10))
                pts.append((-1, -1))
                continue
            pts.append(p)
        return pts

    n = int(rng.integers(2, 4))
    pw, ph = x1 - x0, bot - top
    # the veins braid across the slab: each starts low on the left (rising
    # grain) or high on the left (falling grain), offset across the grain
    # from the last, and runs most of the way across at its own angle
    lane = rng.permutation(n)
    for i in range(n):
        base = -sign * math.radians(float(rng.uniform(25.0, 55.0)))   # screen y grows downward
        length = int(rng.integers(22, 41))
        sx = x0 + 4 + rng.uniform(0.0, pw * 0.3)
        f = (lane[i] + rng.uniform(0.2, 0.8)) / n
        sy = (bot - 5) - f * (ph - 9) * 0.8 if sign > 0 else (top + 4) + f * (ph - 9) * 0.8
        pts = walk(sx, sy, base, length, True)
        solid = [p for p in pts if p[0] >= 0]
        if len(solid) > 6:
            bx, by = solid[int(len(solid) * rng.uniform(0.35, 0.6))]
            bang = base + (1 if rng.random() < 0.5 else -1) * math.radians(float(rng.uniform(22, 38)))
            pts += [(-1, -1)] + walk(float(bx), float(by), bang, int(rng.integers(5, 11)), False)
        m = len(pts)
        b0 = int(m * rng.uniform(0.05, 0.3))
        s0 = int(m * rng.uniform(0.55, 0.7))
        for idx, (px, py) in enumerate(pts):
            if px < 0 or not (0 <= py < h):
                continue
            px %= w
            if not inner[py, px]:
                continue
            vein[py, px] = True
            steep = abs(math.sin(base)) > 0.75
            lo = ((px + 1) % w, py) if steep else (px, py + 1)        # shadow side
            up = ((px - 1) % w, py) if steep else (px, py - 1)        # lit side
            if b0 <= idx < b0 + m // 3 and inner[lo[1], lo[0]]:
                bleed[lo[1], lo[0]] = True
            if s0 <= idx < s0 + m // 4 and inner[up[1], up[0]]:
                sheen[up[1], up[0]] = True
    return vein, bleed, sheen


def _capital(P: Plane, cx: float) -> None:
    """Authored composite capital (rows 56-69): lit abacus, bell shaded
    left -> right, two volutes, two rows of acanthus tips, astragal."""
    X, Y = P.xx + 0.5, P.yy + 0.5
    dx = periodic_dx(P.xx, cx, P.w)
    adx = np.abs(dx)
    yy = P.yy
    aba = (adx <= 13.5) & (yy >= 56) & (yy < 59)
    P.fill(aba & (yy == 56), "wall", np.where(dx < 9, 5, 4))
    P.fill(aba & (yy == 57), "wall", np.where(dx < -10, 4, np.where(dx < 10, 3, 2)))
    P.fill(aba & (yy == 58), "wall", 1)
    half_w = 11.5 - (Y - 59.0) * 0.22
    bell = (adx <= half_w) & (yy >= 59) & (yy < 68)
    u = dx / np.maximum(half_w, 1.0)
    P.fill(bell, "wall", np.where(u < -0.45, 4, np.where(u < 0.25, 3, 2)))
    for row_y, xs, ry, lift in ((67.5, (-8, -4, 0, 4, 8), 4.2, 0), (64.5, (-6, -2, 2, 6), 3.2, 1)):
        for lx in xs:
            ldx = dx - lx
            leaf = (np.abs(ldx) <= 2.0) & (Y <= row_y) & (Y >= row_y - ry) & \
                   (((ldx / 2.0) ** 2 + ((Y - row_y) / ry) ** 2) <= 1.0) & bell
            shade = np.where(ldx < -0.3, 4, np.where(ldx < 0.8, 3, 2)) + lift
            shade = shade - (dx > 6).astype(int)
            P.fill(leaf, "wall", np.clip(shade, 1, 5))
            P.fill(leaf & (Y < row_y - ry + 1.2) & (np.abs(ldx) < 0.8), "wall", 5 if lx < 4 else 4)
            P.fill(bell & (np.abs(ldx - 2.0) < 0.5) & (Y > row_y - ry + 1) & (Y <= row_y), "wall", 1)
    for vx in (-9.5, 9.5):
        dv = np.hypot(dx - vx, Y - 61.0)
        ring = (dv <= 2.7) & (dv > 1.6)
        ang = np.arctan2(Y - 61.0, dx - vx)
        lit = np.cos(ang + math.radians(135)) > 0.0     # upper-left half catches light
        P.fill(ring, "wall", np.where(lit, 5 if vx < 0 else 4, 1))
        P.fill(dv <= 1.6, "wall", 2 if vx < 0 else 1)
        P.fill(dv <= 0.6, "wall", 4 if vx < 0 else 3)
    neck = (adx <= 10.5) & (yy >= 68) & (yy < 70)
    P.fill(neck & (yy == 68), "wall", np.where(dx < 6, 4, 3))
    P.fill(neck & (yy == 69), "wall", 1)


def _pilaster_base(P: Plane, cx: float) -> None:
    """Attic base (rows BASE_Y .. BASE_Y + 11): torus, scotia, torus, plinth;
    it stands on the chair rail."""
    dx = periodic_dx(P.xx, cx, P.w)
    adx = np.abs(dx)
    yy = P.yy
    rows = ((11.5, 1), (12.0, 4), (12.5, 3), (12.5, 2), (11.5, 1), (11.0, 0), (12.5, 4), (13.0, 3),
            (13.0, 2), (13.5, 4), (13.5, 3), (13.5, 1))
    for i, (half, tone) in enumerate(rows):
        sel = (yy == BASE_Y + i) & (adx <= half)
        P.fill(sel, "wall", np.clip(np.where(dx > half - 3, tone - 1, np.where(dx < -half + 2, tone + 1, tone)),
                                    0, 5))


def _moon_shaft(P: Plane, x_rail: float, width: float, y_top: float = float(WAINSCOT_Y),
                seam: float = SHAFT_SEAM) -> None:
    """Moonlight falling down-left (dx/dy SHAFT_SLOPE, ~65 deg) from a
    window, standing in for an additive polygon. Its left edge crosses the
    chair rail at `x_rail`; it starts at `y_top` (a window sill, or the rail
    for a dado-only shaft) and lands on the floor line.

    Posterized, two values only: inside, the stone and marble swap to their
    moon-leaned ramps at the same tone (the rose marble turns a cool mauve,
    ~13 Y lighter, its veins and clouds still showing through), with a
    `seam`-px checker at each edge and no brighter core; the last two rows
    pool a little wider on the skirting."""
    X = P.xx + 0.5
    dy_rail = (P.yy + 0.5) - WAINSCOT_Y
    sx0 = x_rail - dy_rail * SHAFT_SLOPE
    sx1 = sx0 + width
    rows = (P.yy >= y_top) & (P.yy < FLOOR_Y)
    inside = rows & (X >= sx0) & (X <= sx1)
    checker = ((P.xx + P.yy) % 2) == 0
    edge = inside & ((X < sx0 + seam) | (X > sx1 - seam))
    lit = (inside & ~edge) | (edge & checker)
    P.swap(lit, {"wall": "wall_moon", "ashlar": "ashlar_moon", "velvet": "velvet_moon",
                 "marble_bg": "marble_bg_moon"})
    pool = (P.yy >= FLOOR_Y - 2) & (P.yy < FLOOR_Y) & (X >= sx0 - 3.0) & (X <= sx1 + 3.0)
    pool &= ~inside
    P.swap(pool & (checker | (X >= sx0 - 1.0) & (X <= sx1 + 1.0)), {"marble_bg": "marble_bg_moon"})


def _drape_shape(yy: np.ndarray, xx: np.ndarray, outer: float, inner_top: float, inner_tie: float,
                 tie_y: float, top: float, bottom: float, inner_bot: float, side: int
                 ) -> tuple[Mask, np.ndarray]:
    """One drape hanging from `top` to `bottom`, pulled toward the outer side
    at `tie_y`. Returns the mask and u (0 at the outer edge, 1 at the inner
    edge) for folds. `side` -1 = left drape (outer edge on the left)."""
    y = yy + 0.5
    t_up = np.clip((y - top) / max(1.0, tie_y - top), 0, 1)
    t_dn = np.clip((y - tie_y) / max(1.0, bottom - tie_y), 0, 1)
    inner_up = inner_top + (inner_tie - inner_top) * (t_up ** 1.6)
    inner_dn = inner_tie + (inner_bot - inner_tie) * (1 - (1 - t_dn) ** 1.8)
    inner = np.where(y < tie_y, inner_up, inner_dn)
    outer_x = outer + side * np.where(y < tie_y, 0.0, 2.0 * t_dn)
    lo, hi = np.minimum(outer_x, inner), np.maximum(outer_x, inner)
    m = (y >= top) & (y < bottom) & (xx + 0.5 >= lo) & (xx + 0.5 <= hi)
    span = np.where(np.abs(inner - outer_x) < 1e-3, 1.0, inner - outer_x)
    u = np.clip((xx + 0.5 - outer_x) / span, 0, 1)
    return m, u


def _velvet_fill(P: Plane, mask: Mask, u: np.ndarray, folds: float, phase: float,
                 tilt: np.ndarray | None = None, bias: float = 0.0) -> None:
    """Fold-normal shaded velvet: cosine folds across u, lit from the upper
    left; troughs sink, crests get the sheen tone sparingly."""
    f = u * folds + phase
    nx = -np.sin(2 * math.pi * f) * 0.8
    ny = np.zeros_like(nx) if tilt is None else tilt
    nz = np.ones_like(nx)
    n = np.sqrt(nx * nx + ny * ny + nz * nz)
    lit = shade_normals(nx / n, ny / n, nz / n, LIGHT_ENV, ambient=0.16, gamma=1.3, rim=0.0)
    lit = np.where(np.cos(2 * math.pi * f) < -0.8, lit - 0.2, lit) + bias
    P.fill(mask, "velvet", quant(lit, [0.30, 0.44, 0.58, 0.72, 0.87, 0.96]))


def _drapes(P: Plane, wx0: float, wx1: float, swag_pad: float = 14.0) -> None:
    """Velvet drapes framing a window spanning wx0..wx1 (the rose bay, which
    no playfield drape or candle ever crosses), sill-length: they end just
    above the chair rail in a gold fringe, so no crimson hangs behind the
    run line."""
    yy, xx = P.yy, P.xx
    X, Y = xx + 0.5, yy + 0.5
    L = {"x0": wx0, "x1": wx1}
    top, bottom, tie_y = 66.0, float(WAINSCOT_Y - 2), 150.0
    for side in (-1, 1):
        outer = L["x0"] - 9 if side < 0 else L["x1"] + 9
        inner_top = L["x0"] + 9 if side < 0 else L["x1"] - 9
        inner_tie = L["x0"] - 2 if side < 0 else L["x1"] + 2
        inner_bot = L["x0"] + 4 if side < 0 else L["x1"] - 4
        m, u = _drape_shape(yy, xx, outer, inner_top, inner_tie, tie_y, top, bottom, inner_bot, side)
        _velvet_fill(P, m, u, 3.0, 0.15 if side < 0 else 0.4, bias=-0.04)
        P.shift(m & (yy >= bottom - 3), -1, ["velvet"])
        # fringe under the hem (the swag's gold fringe)
        hem = m & ~neighbours(m, 0, 1, wrap_x=False)
        fringe = neighbours(hem, 0, -1, wrap_x=False) | neighbours(hem, 0, -2, wrap_x=False)
        fringe &= ~m
        P.fill(fringe & ((xx % 2) == 0), "gold", 2)
        P.fill(fringe & ((xx % 2) == 1) & neighbours(hem, 0, -1, wrap_x=False), "gold", 1)
        lo, hi = min(outer, inner_tie) - 1, max(outer, inner_tie) + 1
        cord = (X >= lo) & (X <= hi) & (np.abs(Y - tie_y) <= 1.5)
        P.fill(cord, "gold", np.where(Y < tie_y, 3, 1))
        P.fill(cord & ((xx % 3) == 0), "gold", 2)
        tx = outer + side * 1.0
        head = (np.abs(X - tx) <= 1.6) & (Y > tie_y + 1.5) & (Y <= tie_y + 4)
        tassel = (np.abs(X - tx) <= 1.0 + (Y - tie_y - 4) * 0.25) & (Y > tie_y + 4) & (Y <= tie_y + 10)
        P.fill(head, "gold", 3)
        P.fill(tassel, "gold", np.where((xx % 2) == 0, 2, 1))
    x0, x1 = L["x0"] - swag_pad, L["x1"] + swag_pad
    xr = (X - x0) / (x1 - x0)
    swag_bot = 76.0 + 7.0 * np.abs(np.sin(xr * math.pi * 2.0)) ** 0.7
    val = (X >= x0) & (X <= x1) & (yy >= 62) & (Y <= swag_bot)
    vy = (Y - 62) / np.maximum(1.0, swag_bot - 62)
    _velvet_fill(P, val, vy * 0.999, 2.0, 0.1, tilt=np.zeros_like(vy), bias=0.0)
    fringe = (X >= x0) & (X <= x1) & (Y > swag_bot) & (Y <= swag_bot + 2.5)
    P.fill(fringe & ((xx % 2) == 0), "gold", 2)
    P.fill(fringe & ((xx % 2) == 1) & (Y <= swag_bot + 1.5), "gold", 1)
    rod = (X >= x0 - 3) & (X <= x1 + 3) & (yy >= 60) & (yy < 62)
    P.fill(rod, "gold", np.where(yy == 60, 3, 1))
    for fx in (x0 - 4, x1 + 4):
        fin = np.hypot(X - fx, Y - 61) <= 2.3
        P.fill(fin, "gold", np.where((X < fx) & (Y < 61), 3, 1))


def _portrait(P: Plane) -> None:
    """A gilt-framed oil portrait of a lady (generic, original, no likeness):
    half-length, three-quarter view turned to the light on the left, dark
    hair up in a chignon, a lace collar with a garnet brooch, a violet gown,
    one hand at the waist holding a rose, on an umber varnish ground that
    lightens behind the head. Everything in background-graded paint and gold."""
    yy, xx = P.yy, P.xx
    X, Y = xx + 0.5, yy + 0.5
    F = FRAME
    x0, y0, x1, y1 = F["x0"], F["y0"], F["x1"], F["y1"]
    outer = (xx >= x0) & (xx < x1) & (yy >= y0) & (yy < y1)
    ed = np.minimum.reduce([xx - x0, yy - y0, x1 - 1 - xx, y1 - 1 - yy]).astype(np.float64)
    bw = 6
    moulding = outer & (ed < bw)
    prof = np.where(ed < 1, 0.5, np.where(ed < 4, 1.0 - 0.12 * (ed - 2.2) ** 2, 0.55 - 0.1 * (ed - 4)))
    mx = (x0 + x1) / 2
    cart = (np.abs(X - mx) <= 8 - (y0 - Y) * 0.9) & (Y >= y0 - 7) & (yy < y0 + 2)
    boss = np.zeros_like(outer)
    for bx_, by_ in ((x0 + 3, y0 + 3), (x1 - 3, y0 + 3), (x0 + 3, y1 - 3), (x1 - 3, y1 - 3)):
        boss |= np.hypot(X - bx_, Y - by_) <= 3.4
    height = np.where(moulding, prof, 0.0)
    height = np.where(boss, 1.25, height)
    height = np.where(cart & ~outer, 0.9 + 0.3 * np.cos((X - mx) / 3.0), height)
    gold = moulding | boss | (cart & ~outer)
    lit = light_of(ndimage.gaussian_filter(height, 0.5) * 2.4, 1.0, ambient=0.12)
    P.fill(gold, "gold", quant(lit, [0.30, 0.48, 0.66, 0.86]))
    # 1 px gilt slip inside the moulding (lit top/left, shaded bottom/right)
    slip = outer & (ed == bw)
    P.fill(slip, "gold", np.where((yy == y0 + bw) | (xx == x0 + bw), 3, 1))
    cv = outer & (ed > bw)
    cx0, cy0 = x0 + bw + 1, y0 + bw + 1               # canvas top-left (34 x 50)
    u, v = X - cx0, Y - cy0                          # canvas coordinates (pixel centres)
    pn = PAINT
    # umber varnish ground: dark at the edges, a dithered warm glow behind the head
    hc = (17.0, 13.0)
    g = 1.0 - np.hypot((u - hc[0]) / 19.0, (v - hc[1]) / 24.0)
    g = g + (fbm(P.w, P.h, 2, 8, seed=44) - 0.5) * 0.12
    gt = quant(np.clip(g, 0, 1), [0.18, 0.42, 0.66], dither="bayer4", amount=0.9)
    P.fill(cv, "paint", np.choose(gt, [pn["umber0"], pn["umber1"], pn["umber2"], pn["umber3"]]))

    def put(mask: Mask, idx: int | np.ndarray) -> None:
        P.fill(cv & mask, "paint", idx)

    hx, hy = 16, 13                                  # head centre (canvas px)
    # body: sloping shoulders, a fitted bodice to the waist, a widening skirt
    knots_v = (21.0, 24.0, 31.0, 35.0, 49.5)
    knots_h = (5.0, 10.0, 10.5, 7.0, 12.5)
    half = np.interp(v, knots_v, knots_h, left=-1.0)
    bx = hx + 1.5
    rel = u - bx
    gown = (np.abs(rel) <= half) & (v >= knots_v[0])
    put(gown, np.where(rel < -half + 3.0, pn["gown2"], np.where(rel > half - 3.0, pn["gown0"], pn["gown1"])))
    put(gown & (np.abs(rel + 0.5) <= 1.6) & (v > 23) & (v < 35), pn["gown2"])            # lit stomacher
    put(gown & (np.abs(rel - 1.5) < 0.6) & (v > 23) & (v < 35), pn["gown0"])
    for fx, sl, idx in ((-5.0, -0.22, "gown1"), (3.0, 0.12, "void"), (7.0, 0.3, "gown0")):  # skirt folds
        put(gown & (np.abs(rel - (fx + (v - 36) * sl)) < 0.6) & (v > 36 + (fx > 5) * 4), pn[idx])
    # the near arm: sleeve down to the elbow, forearm across to the waist
    seg = [((bx - 8.0, 24.0), (bx - 9.0, 31.0)), ((bx - 9.0, 31.0), (bx - 3.0, 34.0))]
    arm = np.zeros(u.shape, bool)
    for (ax0, ay0), (ax1, ay1) in seg:
        t = np.clip(((u - ax0) * (ax1 - ax0) + (v - ay0) * (ay1 - ay0)) /
                    ((ax1 - ax0) ** 2 + (ay1 - ay0) ** 2), 0, 1)
        arm |= np.hypot(u - (ax0 + t * (ax1 - ax0)), v - (ay0 + t * (ay1 - ay0))) <= 1.7
    put(arm, pn["gown2"])
    put(arm & ~neighbours(arm, 0, 1, wrap_x=False), pn["gown1"])                       # sleeve underside
    put(arm & ~neighbours(arm, -1, 0, wrap_x=False), pn["gown2"])
    # hand at the waist holding a rose
    hand = (np.abs(u - (bx - 2.0)) <= 1.6) & (np.abs(v - 34.0) <= 1.0)
    put(hand, np.where(u < bx - 2.0, pn["skin2"], pn["skin1"]))
    put(hand & (v > 34.0), pn["skin0"])
    put((np.abs(u - (bx + 0.0)) < 0.6) & (v > 32) & (v < 38), pn["umber2"])             # stem
    put((np.abs(u - (bx + 0.0)) < 1.1) & (v > 30) & (v < 32), pn["garnet"])             # rose
    # lace ruff and garnet brooch under the chin
    ruff = (np.abs(u - (hx + 0.5)) <= 5.0 - (v - 20.0) * -0.6) & (v >= 20.0) & (v < 22.0)
    put(ruff, np.where(u < hx + 1, pn["lace1"], pn["lace0"]))
    put((v >= 22.0) & (v < 23.0) & (np.abs(u - (hx + 0.5)) <= 5.5) & ((xx % 2) == 0), pn["lace0"])
    put((np.abs(u - (hx + 0.5)) < 0.6) & (np.abs(v - 22.5) < 0.6), pn["garnet"])
    # head, neck and hair from an authored 11 x 13 cluster map (lit from the left)
    face = ("......KKK..",
            "....hHHHHK.",
            "...hHHHHHHK",
            "..hHHHHHHHK",
            "..HHSSsHHHK",
            "..HSSSssdHK",
            "..SeSSedHHK",
            "..SSSssddHK",
            "..SSSsdddK.",
            "...SmsddK..",
            "....ssdd...",
            "....sdd....",
            "....sdd....")
    key = {"K": "hair0", "H": "hair1", "h": "hair_sheen", "S": "skin2", "s": "skin1", "d": "skin0",
           "e": "umber1", "m": "lip"}
    for j, row in enumerate(face):
        for i, ch in enumerate(row):
            if ch in key:
                put((xx == cx0 + hx - 5 + i) & (yy == cy0 + hy - 6 + j), pn[key[ch]])


def _rose_window(P: Plane) -> None:
    """Bay A: a round window with eight-light tracery, glazed in translucent
    stained glass (alpha ~70 %, so the moving sky tints through it like a
    PS1 semi-transparent quad), over two blind lancets."""
    yy, xx = P.yy, P.xx
    X, Y = xx + 0.5, yy + 0.5
    R = ROSE
    cx, cy, r = R["cx"], R["cy"], R["r"]
    dx, dy = X - cx, Y - cy
    d = np.hypot(dx, dy)
    ang = (np.degrees(np.arctan2(dy, dx)) + 360.0) % 360.0
    # moulded surround + four keystones
    ring = (d > r) & (d <= r + 6.0)
    prof = np.where(d <= r + 1.5, 0.8, np.where(d <= r + 4.5, 1.25 - 0.12 * (d - r - 3.0) ** 2, 0.85))
    keys = ring & (np.abs(((ang + 45.0) % 90.0) - 45.0) < 5.5) & (d > r + 1.5)
    prof = np.where(keys, 1.5, prof)
    lit = light_of(ndimage.gaussian_filter(np.where(ring, prof, 0.4), 0.6) * 2.4, 1.0)
    P.fill(ring, "wall", quant(lit, [0.25, 0.40, 0.55, 0.72, 0.86]))
    # reveal: moonlit on the lower left (moon is upper right, outside)
    rev = (d > r - 2.0) & (d <= r)
    P.fill(rev, "wall_moon", np.where((dx < 0) | (dy > 0), 3, 1))
    P.fill(rev & (dx > 0) & (dy < 0), "wall", 1)
    glass = d <= r - 2.0
    # tracery: hub ring, inner ring, eight spokes, cusped outer lights
    sector = (ang // 45.0).astype(int)
    mid_ang = np.abs(((ang + 22.5) % 45.0) - 22.5)                 # 0 on a spoke
    spoke = glass & (mid_ang * np.pi / 180.0 * d < 1.1) & (d > 4.0)
    hub = glass & (d > 3.0) & (d <= 4.6)
    inner = glass & (np.abs(d - 13.0) <= 0.8)
    cusp = glass & (d > 13.0) & (np.abs(((ang) % 45.0) - 22.5) * np.pi / 180.0 * d < 0.9) & (d > r - 6.0)
    roundel = np.zeros_like(glass)
    roundel_in = np.zeros_like(glass)
    for k in range(8):
        a = math.radians(k * 45.0 + 22.5)
        rd = np.hypot(X - (cx + 18.0 * math.cos(a)), Y - (cy + 18.0 * math.sin(a)))
        roundel |= glass & (rd > 2.4) & (rd <= 3.4)
        roundel_in |= glass & (rd <= 2.4)
    tracery = spoke | hub | inner | cusp | roundel
    tl = light_of(ndimage.gaussian_filter(tracery.astype(np.float64), 0.6) * 2.0, 1.0)
    P.fill(tracery, "wall", quant(tl, [0.25, 0.4, 0.55, 0.7, 0.85]))
    pane = glass & ~tracery
    lit_side = (dx - dy) > 0                                        # facing the moon
    outer_t = np.where(sector % 2 == 0, np.where(lit_side, 2, 1), np.where(lit_side, 4, 3))
    outer_t = np.where(d > r - 4.0, np.where(sector % 2 == 0, 0, 3), outer_t)
    petal_t = np.where(lit_side, 6, 5)
    tone = np.where(d > 13.8, outer_t, np.where(d > 4.6, petal_t, np.where(lit_side, 8, 7)))
    tone = np.where(roundel_in, np.where(lit_side, 8, 7), tone)
    P.fill(pane, "rose_glass", tone, alpha=176)
    # 1 px lead across each outer light, halfway out
    lead = pane & (np.abs(d - 19.0) < 0.55) & ~roundel_in
    P.fill(lead, "lead", 0, alpha=255)
    # two blind lancets below (recessed panels, not open), standing on a
    # shared sill a few rows above the chair rail
    n_top, n_bot = float(WAINSCOT_Y - 42), float(WAINSCOT_Y - 8)
    for bx0 in (cx - 22.0, cx + 6.0):
        niche = pointed_arch(xx, yy, bx0, bx0 + 16, n_top, n_bot, 0.85)
        ind = inner_dist(niche)
        P.fill(niche, "wall", 1)
        P.fill(niche & (ind <= 1.0) & (X < bx0 + 8), "wall", 0)
        P.fill(niche & (ind <= 1.0) & (X >= bx0 + 8), "wall", 3)
        P.fill(niche & (ind > 1.0) & (ind <= 2.0) & (Y < n_top + 8), "wall", 0)
        out = ~niche & (edge_dist(niche) <= 1.0) & (Y < n_bot)
        P.fill(out, "wall", np.where(X < bx0 + 8, 4, 2))
        sill = (X >= bx0 - 1) & (X <= bx0 + 17) & (yy >= n_bot) & (yy < n_bot + 3)
        P.fill(sill, "wall", np.where(yy == n_bot, 4, np.where(yy == n_bot + 1, 3, 1)))


# ===========================================================================
# Layer manifest
# ===========================================================================
def mote_zones() -> list[dict[str, float]]:
    """Dado moon shafts in Hall texels for the runtime dust motes
    (scripts/world/ambient_fx.gd): at row y a zone spans
    x0 - (y - y0) * slope .. x1 - (y - y0) * slope, rows y0 .. y1."""
    zones: list[dict[str, float]] = []
    for x_rail, width in DADO_SHAFTS:
        y_top = LANCET["sill"] + 6 if LANCET["x0"] <= x_rail <= LANCET["x1"] else float(WAINSCOT_Y)
        x0 = (x_rail + HALL_ROLL) % HALL_W + (WAINSCOT_Y - y_top) * SHAFT_SLOPE
        zones.append({"x0": round(x0, 2), "x1": round(x0 + width, 2), "y0": float(y_top),
                      "y1": float(FLOOR_Y), "slope": SHAFT_SLOPE})
    return zones


def layer_entries() -> list[dict[str, object]]:
    """Far -> near. scroll_scale and z per the Environment table in
    docs/art_style.md; repeat_size.x always equals the texture width."""
    def e(name: str, file: str, scroll: tuple[float, float], size: tuple[int, int], z: int,
          offset: tuple[int, int] = (0, 0), autoscroll: tuple[float, float] | None = None
          ) -> dict[str, object]:
        span = VIEW_W + scroll[0] * (ROOM_W - VIEW_W)
        entry: dict[str, object] = {
            "name": name,
            "texture": f"res://assets/backgrounds/{file}",
            "scroll_scale": [scroll[0], scroll[1]],
            "repeat_size": [size[0], 0],
            "repeat_times": max(2, int(math.ceil(span / size[0])) + 1),
            "z_index": z,
            "offset": [offset[0], offset[1]],
            "modulate": [1.0, 1.0, 1.0, 1.0],
        }
        if autoscroll is not None:
            entry["autoscroll"] = [autoscroll[0], autoscroll[1]]
        return entry

    return [
        e("Sky", "sky.png", (0.03, 0.05), (SKY_W, SKY_H), -30),
        e("Clouds", "clouds.png", (0.06, 0.08), (CLOUD_W, CLOUD_H), -28, autoscroll=(-4.0, 0.0)),
        e("Castle", "castle.png", (0.15, 0.2), (CASTLE_W, CASTLE_H), -24),
        e("Arcade", "arcade.png", (0.4, 0.6), (ARCADE_W, ARCADE_H), -18),
        dict(e("Hall", "hall.png", (0.7, 1.0), (HALL_W, HALL_H), -10), motes=mote_zones()),
    ]


def write_manifest() -> None:
    doc = {
        "_comment": ("Generated by tools/asset_pipeline/backgrounds.py. Far -> near. One Parallax2D "
                     "per entry (scroll_scale, repeat_size, repeat_times, z_index, scroll_offset = "
                     "offset, optional autoscroll) with a Sprite2D child (texture, centered = false, "
                     "modulate). Screen = texel + offset - scroll_scale * camera_top_left. "
                     "Hall's 'motes' (moon-shaft zones in Hall texels) are read at runtime by "
                     "scripts/world/ambient_fx.gd."),
        "layers": layer_entries(),
    }
    with open(os.path.join(BACKGROUNDS, "layers.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")


def build() -> None:
    build_sky()
    build_clouds()
    build_castle()
    build_arcade()
    build_hall()
    write_manifest()


if __name__ == "__main__":
    build()
