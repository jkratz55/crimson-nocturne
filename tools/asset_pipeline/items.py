"""
Pickups and sub-weapons: the small and big hearts (glinting pickup sheets,
built from in-memory stills), the dagger, the axe (16x16 icon + a pre-rotated spin strip for the
projectile), the 16x16 sword and whip menu icons, and the aura / glint sheet
that unique world items wear.

It also hosts the small "jewel icon" renderer that `equipment.py` shares.
An icon is built from lit relief parts (a mask plus a height field on a 4x
supersampled grid), shaded with one fixed light, quantized per material
into the shared `RAMPS` (plus a few item-only ramps in `IR`), cleaned up and
outlined with material sel-out, then finished with hand-placed 1 px
speculars. Faceted gems and the tiniest sprites are hand-authored tone
templates instead (`GEMS`, `HEART_SMALL`): at 5-8 px a designed facet
pattern reads as a jewel where a computed one reads as noise.

Icons are never flipped, so they light from the upper left (`ICON_LIGHT`),
like the inventory art of the era. Projectiles flip with their direction:
the dagger is lit from straight above-front (it doubles as the HUD icon, so
it must read either way round) and the axe's spin frames use `LIGHT`
(upper-front of a right-facing sprite) held fixed in the world while the
axe turns, so the glint slides round the blade as it spins.
"""
from __future__ import annotations

import json
import math
import os
from typing import Callable, Mapping, Sequence

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

from common import (
    LIGHT, RAMPS, RGB, SPRITES, Indexed, SheetBuilder, VolCanvas, bayer, bezier_curve,
    heightmap_normals, shade_normals,
)

Vec = tuple[float, float, float]
Pt = tuple[float, float]
Arr = np.ndarray


def unit(v: Sequence[float]) -> Vec:
    n = math.sqrt(sum(float(c) * float(c) for c in v)) or 1.0
    return (float(v[0]) / n, float(v[1]) / n, float(v[2]) / n)


# Icons light from the upper left and slightly in front (mirror of LIGHT).
ICON_LIGHT: Vec = unit((-0.55, -0.62, 0.56))

# --------------------------------------------------------------------------
# Item ramps: the shared registry plus a few materials only items use.
# All run dark -> light; tone 0 doubles as the sel-out outline colour.
# --------------------------------------------------------------------------
IR: dict[str, list[RGB]] = {k: list(v) for k, v in RAMPS.items()}
IR.update({
    # the shared RAMPS["heart"] with two in-betweens and a pink-white gloss
    "heart_gloss": [(70, 6, 26), (122, 10, 38), (176, 20, 50), (222, 34, 60), (255, 112, 124),
                    (255, 218, 222)],
    # glass rim/body: cool, violet in shadow, cyan-white in the light
    "glass": [(22, 24, 48), (46, 56, 92), (88, 108, 146), (150, 176, 204), (222, 238, 250)],
    # the dark castle seen through empty glass
    "glass_in": [(14, 14, 34), (26, 28, 58), (40, 46, 84)],
    # blood / vitae: deep crimson to a hot translucent red
    "vitae": [(40, 4, 18), (86, 8, 32), (142, 16, 44), (200, 34, 56), (246, 96, 98), (255, 200, 190)],
    # milky moonstone cabochon (blue-lilac sheen)
    "moonstone": [(48, 52, 104), (92, 104, 164), (146, 162, 214), (196, 210, 244), (236, 242, 255)],
    # white-lavender feathers
    "feather": [(46, 42, 72), (92, 90, 130), (150, 150, 190), (204, 206, 232), (246, 246, 255)],
    # ember liquid (banked fire)
    "ember": [(70, 14, 22), (140, 36, 24), (210, 86, 30), (250, 150, 52), (255, 220, 120),
              (255, 250, 220)],
    # pale silver (chain, wire, settings): steel without its gunmetal end
    "silver": [(40, 44, 66), (92, 100, 132), (150, 160, 190), (204, 212, 234), (248, 250, 255)],
    # the Crimson Lash: leather pushed toward red
    "lash": [(32, 8, 16), (74, 18, 30), (122, 36, 40), (172, 70, 58), (222, 122, 92)],
    # polished black stone: mostly dark, a cold lavender sheen on top
    "onyx": [(14, 10, 26), (30, 24, 50), (52, 46, 84), (96, 92, 140), (170, 172, 222),
             (236, 238, 255)],
})

# A sparkle's colours: hot white core, the pale arms tinted per object.
STAR_CORE: RGB = (255, 255, 255)


# --------------------------------------------------------------------------
# Geometry kit (1x pixel coordinates, y down)
# --------------------------------------------------------------------------
def d_segment(X: Arr, Y: Arr, a: Pt, b: Pt) -> tuple[Arr, Arr]:
    """Distance to segment a-b and the projection parameter t in 0..1."""
    vx, vy = b[0] - a[0], b[1] - a[1]
    ll = vx * vx + vy * vy + 1e-9
    t = np.clip(((X - a[0]) * vx + (Y - a[1]) * vy) / ll, 0.0, 1.0)
    return np.hypot(X - (a[0] + vx * t), Y - (a[1] + vy * t)), t


def q_ellipse(X: Arr, Y: Arr, c: Pt, rx: float, ry: float, rot: float = 0.0) -> Arr:
    """Normalised ellipse radius (<= 1 inside); `rot` turns it clockwise."""
    u, v = X - c[0], Y - c[1]
    if rot:
        cr, sr = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        u, v = u * cr + v * sr, -u * sr + v * cr
    return np.sqrt((u / rx) ** 2 + (v / ry) ** 2)


def poly_mask(X: Arr, Y: Arr, pts: Sequence[Pt]) -> Arr:
    """Even-odd point-in-polygon test on sample centres."""
    inside = np.zeros(X.shape, bool)
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        if y0 == y1:
            continue
        cond = (y0 > Y) != (y1 > Y)
        xi = x0 + (Y - y0) * (x1 - x0) / (y1 - y0)
        inside ^= cond & (X < xi)
    return inside


def bevel(mask: Arr, radius: float, ss: int, power: float = 0.5) -> Arr:
    """Height (1x px) of a shape with rounded edges: it rises over `radius`
    px from the contour, then stays flat (power 0.5 = round profile)."""
    if not mask.any():
        return np.zeros(mask.shape)
    d = distance_transform_edt(np.pad(mask, 1))[1:-1, 1:-1] / ss
    t = np.clip(d / max(radius, 1e-6), 0.0, 1.0)
    return radius * (1.0 - (1.0 - t) ** 2) ** power


def dome(mask: Arr, ss: int, height: float | None = None, power: float = 0.5) -> Arr:
    """A fully rounded height field over any mask. The light is
    directional, so this still has a proper terminator (never pillowed)."""
    if not mask.any():
        return np.zeros(mask.shape)
    d = distance_transform_edt(np.pad(mask, 1))[1:-1, 1:-1] / ss
    r = float(d.max())
    t = np.clip(d / max(r, 1e-6), 0.0, 1.0)
    return (r if height is None else height) * (1.0 - (1.0 - t) ** 2) ** power


class Xf:
    """Similarity 2-D transform for parts authored in local coordinates:
    scale by `scale` and rotate clockwise by `angle` degrees about the
    local point `com`, then put `com` at `at` on the canvas."""

    def __init__(self, angle: float, com: Pt, at: Pt, scale: float = 1.0) -> None:
        self.c, self.s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        self.com, self.at, self.k = com, at, scale

    def __call__(self, p: Pt) -> Pt:
        x, y = (p[0] - self.com[0]) * self.k, (p[1] - self.com[1]) * self.k
        return (self.at[0] + x * self.c - y * self.s, self.at[1] + x * self.s + y * self.c)

    def pts(self, ps: Sequence[Pt]) -> list[Pt]:
        return [self(p) for p in ps]


# --------------------------------------------------------------------------
# Icon canvas: lit relief parts -> Indexed -> sel-out RGBA
# --------------------------------------------------------------------------
class Icon:
    """A small supersampled canvas of lit parts (see the module docstring).

    Parts paint in call order, later in front (`behind=True` fills only
    empty samples). Each part takes a `group`; interior contours are drawn
    only between different groups (an arm over a coat, a prong over a
    stone), never between the folds of one part."""

    def __init__(self, w: int, h: int, ss: int = 4, light: Vec = ICON_LIGHT,
                 ramps: Mapping[str, Sequence[RGB]] | None = None) -> None:
        self.w, self.h, self.ss = w, h, ss
        self.light = unit(light)
        self.ramps: Mapping[str, Sequence[RGB]] = IR if ramps is None else ramps
        self.vc = VolCanvas(w, h, ss, ramps=self.ramps, light=self.light, rim=(0.0, 0.0, 0.0))
        xs = (np.arange(w * ss) + 0.5) / ss
        ys = (np.arange(h * ss) + 0.5) / ss
        self.X, self.Y = np.meshgrid(xs, ys)

    def shade(self, nx: Arr, ny: Arr, nz: Arr, *, ambient: float = 0.12, gamma: float = 1.2,
              spec: float = 0.0, spec_pow: float = 10.0, bias: float = 0.0) -> Arr:
        i = shade_normals(nx, ny, nz, self.light, ambient=ambient, gamma=gamma, rim=0.0, spec=spec,
                          spec_pow=spec_pow)
        return np.clip(i + bias, 0.0, 1.0)

    def relief(self, mask: Arr, height: Arr, mat: str, *, spec: float = 0.0, spec_pow: float = 10.0,
               ambient: float = 0.12, gamma: float = 1.2, bias: float = 0.0, group: str | None = None,
               behind: bool = False, extra: Arr | float | None = None) -> int:
        """Lit height-field part; `extra` is added to the intensity (an
        inner glow for liquids and stones, a braid pattern, ...)."""
        nx, ny, nz = heightmap_normals(np.asarray(height, np.float64), float(self.ss), wrap=False)
        inten = self.shade(nx, ny, nz, ambient=ambient, gamma=gamma, spec=spec, spec_pow=spec_pow,
                           bias=bias)
        if extra is not None:
            inten = np.clip(inten + extra, 0.0, 1.0)
        return self.vc.put(mask, mat, inten.astype(np.float32), group=group, behind=behind)

    def facet(self, pts: Sequence[Pt], mat: str, normal: Vec, *, spec: float = 0.0,
              ambient: float = 0.12, gamma: float = 1.0, bias: float = 0.0, group: str | None = None,
              behind: bool = False) -> int:
        """Flat polygon with one normal (plates, bevels)."""
        n = unit(normal)
        v = float(self.shade(np.array(n[0]), np.array(n[1]), np.array(n[2]), ambient=ambient,
                             gamma=gamma, spec=spec, bias=bias))
        return self.vc.put(poly_mask(self.X, self.Y, pts), mat, v, group=group, behind=behind)

    def flat(self, mask: Arr, mat: str, value: float | Arr, *, group: str | None = None,
             behind: bool = False) -> int:
        return self.vc.put(mask, mat, np.asarray(value, np.float32), group=group, behind=behind)

    def capsule(self, a: Pt, b: Pt, r: float, mat: str, *, rb: float | None = None,
                **kw: object) -> int:
        """Round rod from a to b (radius r, tapering to rb)."""
        d, t = d_segment(self.X, self.Y, a, b)
        rr = r + ((r if rb is None else rb) - r) * t
        h = np.sqrt(np.clip(rr * rr - d * d, 0.0, None))
        return self.relief(d <= rr, h, mat, **kw)  # type: ignore[arg-type]

    def ellipse(self, c: Pt, rx: float, ry: float, mat: str, *, rot: float = 0.0, depth: float = 1.0,
                **kw: object) -> int:
        q = q_ellipse(self.X, self.Y, c, rx, ry, rot)
        h = np.sqrt(np.clip(1.0 - q * q, 0.0, None)) * min(rx, ry) * depth
        return self.relief(q <= 1.0, h, mat, **kw)  # type: ignore[arg-type]

    def polygon(self, pts: Sequence[Pt], mat: str, *, edge: float = 1.0, power: float = 0.5,
                **kw: object) -> int:
        """Plate with rounded edges (`edge` px bevel)."""
        m = poly_mask(self.X, self.Y, pts)
        return self.relief(m, bevel(m, edge, self.ss, power), mat, **kw)  # type: ignore[arg-type]

    def tube(self, pts: Sequence[Pt], r0: float, r1: float, mat: str, *,
             pattern: Callable[[Arr, Arr], Arr] | None = None, **kw: object) -> tuple[int, Arr]:
        """A round cord swept along a polyline, radius r0 -> r1. `pattern(s,
        side)` (s = arc length in px, side = signed offset across in -1..1)
        is added to the intensity, e.g. a braid. Returns (part id, s field
        on the sample grid)."""
        X, Y = self.X, self.Y
        best = np.full(X.shape, np.inf)
        dist = np.zeros(X.shape)
        rad = np.zeros(X.shape)
        sarc = np.zeros(X.shape)
        side = np.zeros(X.shape)
        seg_len = [math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
                   for i in range(len(pts) - 1)]
        total = sum(seg_len) or 1.0
        acc = 0.0
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            d, t = d_segment(X, Y, a, b)
            s = acc + t * seg_len[i]
            rr = r0 + (r1 - r0) * (s / total)
            q = d / np.maximum(rr, 1e-6)
            upd = q < best
            cross = (b[0] - a[0]) * (Y - a[1]) - (b[1] - a[1]) * (X - a[0])
            best = np.where(upd, q, best)
            dist = np.where(upd, d, dist)
            rad = np.where(upd, rr, rad)
            sarc = np.where(upd, s, sarc)
            side = np.where(upd, np.sign(cross) * q, side)
            acc += seg_len[i]
        m = best <= 1.0
        h = np.sqrt(np.clip(rad * rad - dist * dist, 0.0, None))
        extra = pattern(sarc, side) if pattern is not None else None
        pid = self.relief(m, h, mat, extra=extra, **kw)  # type: ignore[arg-type]
        return pid, sarc

    def resolve(self, *, min_cover: float = 0.5,
                thresholds: Mapping[str, Sequence[float]] | None = None) -> Indexed:
        return self.vc.resolve(min_cover=min_cover, front_share=0.3, thresholds=thresholds)


def finish(ix: Indexed, *, light: Vec = ICON_LIGHT, lit_tone: int | None = 1, orphans: bool = True,
           contours: bool = True, keep: Sequence[str] = (), skip: Sequence[str] = ("gold",),
           lit_threshold: float = 0.35) -> Image.Image:
    """Orphan cleanup + interior contours + sel-out -> RGBA (alpha 0/255)."""
    if orphans:
        ix.remove_orphans(keep=tuple(keep))
    if contours:
        ix.interior_contours(skip=tuple(skip))
    return ix.selout(lit_tone=lit_tone, light=light, lit_threshold=lit_threshold)


def tone(mat: str, i: int) -> RGB:
    """Colour of ramp `mat` at tone `i` (negative counts from the light end)."""
    r = IR[mat]
    return r[i if i >= 0 else len(r) + i]


def put_px(img: Image.Image, pts: Sequence[tuple[int, int]], color: Sequence[int], *,
           only_opaque: bool = True) -> None:
    """Hand-placed 1x pixels (speculars, rivets) after outlining."""
    for x, y in pts:
        if 0 <= x < img.width and 0 <= y < img.height:
            if only_opaque and img.getpixel((x, y))[3] == 0:
                continue
            img.putpixel((x, y), (int(color[0]), int(color[1]), int(color[2]), 255))


def stamp_tones(ix: Indexed, template: Sequence[str], origin: tuple[int, int], mat: str, *,
                group: str | None = None, offset: int = 0) -> Indexed:
    """Write a digit template (digit = ramp tone + `offset`, '.' = skip)."""
    z = float(ix.z.max()) + 1.0 if (ix.mat >= 0).any() else 1.0
    for j, row in enumerate(template):
        for i, ch in enumerate(row):
            if ch.isdigit():
                ix.set_px(origin[0] + i, origin[1] + j, mat, int(ch) + offset, group=group or mat, z=z)
    return ix


def star(img: Image.Image, cx: int, cy: int, r: int, arm: Sequence[int],
         core: Sequence[int] = STAR_CORE, *, diag: bool = False) -> None:
    """A 4-point sparkle (plus 1 px diagonals with `diag`) drawn over the
    sprite and the transparent margin alike: core at the centre, the
    inner arm pixels core-coloured when r >= 2, the outermost `arm`."""
    put_px(img, [(cx, cy)], core, only_opaque=False)
    for k in range(1, r + 1):
        col = core if (k < r) else arm
        put_px(img, [(cx + k, cy), (cx - k, cy), (cx, cy + k), (cx, cy - k)], col, only_opaque=False)
    if diag:
        put_px(img, [(cx + 1, cy + 1), (cx - 1, cy - 1), (cx + 1, cy - 1), (cx - 1, cy + 1)], arm,
               only_opaque=False)


def pad_to(img: Image.Image, w: int, h: int, at: tuple[int, int] | None = None) -> Image.Image:
    """Place `img` on a transparent w x h canvas (centred by default)."""
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(img, at if at is not None else ((w - img.width) // 2, (h - img.height) // 2))
    return out


# Faceted / cabochon stone templates (tone digits, 0 dark .. 4 glint), lit
# from the upper left: bright crown facets and a glint up-left, a dark
# crescent inside the table where the crown shades it, and refracted light
# pooling low-right -- the classic pixel jewel.
GEMS: dict[str, list[str]] = {
    "oval": [            # 7x6 oval brilliant
        ".33222.",
        "3431122",
        "3312212",
        "2122332",
        "1223331",
        ".11221.",
    ],
    "round": [           # 5x5 round brilliant
        ".332.",
        "34212",
        "31123",
        "21232",
        ".121.",
    ],
    "step": [            # 6x5 step (emerald) cut
        "333322",
        "341112",
        "312232",
        "312332",
        "122221",
    ],
    "cabochon": [        # 6x5 smooth dome
        ".3322.",
        "344321",
        "333221",
        "222211",
        ".1111.",
    ],
    "drop": [            # 5x7 pear, point up
        "..3..",
        ".342.",
        "33212",
        "32222",
        "21223",
        "12232",
        ".122.",
    ],
    "kite": [            # 7x9 tall faceted crystal (relic)
        "...3...",
        "..343..",
        ".33421.",
        "3332212",
        "3221223",
        ".21233.",
        ".12232.",
        "..122..",
        "...1...",
    ],
}


# ==========================================================================
# Hearts
# ==========================================================================
HEART_SMALL: list[str] = [   # 7x6 interior (heart_gloss tones); sel-out adds the 1 px rim
    ".43.32.",
    "4543322",
    "3433321",
    ".33321.",
    "..321..",
    "...1...",
]
HEART_ARM: RGB = (255, 218, 222)


def heart_small() -> Image.Image:
    """9x8 small heart: a hand-pixelled glossy heart."""
    ix = Indexed(9, 8, IR)
    stamp_tones(ix, HEART_SMALL, (1, 1), "heart_gloss")
    return ix.selout(lit_tone=1, light=ICON_LIGHT)


def heart_mask(X: Arr, Y: Arr, x0: float, y0: float, w: float, h: float,
               ss: int) -> tuple[Arr, Arr]:
    """Heart = two round lobes + a wedge to the point. Height: each lobe
    is its own sphere, so the cleft between them reads as a real dip."""
    r = w / 4.0 + 0.15
    cy = y0 + r
    lx, rx = x0 + r, x0 + w - r
    dl = np.hypot(X - lx, Y - cy)
    dr = np.hypot(X - rx, Y - cy)
    body = poly_mask(X, Y, [(x0 + 0.05, cy + 0.2), (x0 + w - 0.05, cy + 0.2), (x0 + w / 2.0, y0 + h)])
    m = (dl <= r) | (dr <= r) | body
    hl = np.sqrt(np.clip(r * r - dl * dl, 0, None))
    hr = np.sqrt(np.clip(r * r - dr * dr, 0, None))
    return m, np.maximum(np.maximum(hl, hr) * 0.9, dome(m, ss))


def heart_big() -> Image.Image:
    """16x14 big heart: rendered volume, one crisp gloss on the left lobe."""
    ic = Icon(16, 14)
    m, hgt = heart_mask(ic.X, ic.Y, 1.0, 1.0, 14.0, 12.4, ic.ss)
    ic.relief(m, hgt, "heart_gloss", spec=0.7, spec_pow=14, ambient=0.05, gamma=1.6)
    ix = ic.resolve(thresholds={"heart_gloss": (0.10, 0.22, 0.38, 0.62, 0.80)})
    ix.remove_orphans()
    # the right lobe keeps a soft sheen, the left lobe owns the gloss
    hm = ix.mask("heart_gloss")
    right = np.zeros_like(hm)
    right[:, 8:] = True
    ix.tone[hm & right & (ix.tone >= 5)] = 4
    img = ix.selout(lit_tone=1, light=ICON_LIGHT)
    put_px(img, [(4, 3)], tone("heart_gloss", 5))
    return img


def heart_glint_frames(base: Image.Image, spot: tuple[int, int], margin: int) -> list[Image.Image]:
    """[rest, sparkle grows, full star, fading] on a canvas padded by
    `margin` on every side (the art stays centred, so scene offsets keep
    working)."""
    w, h = base.width + 2 * margin, base.height + 2 * margin
    sx, sy = spot[0] + margin, spot[1] + margin
    frames = []
    for r, diag in ((0, False), (1, False), (2, True), (1, False)):
        f = pad_to(base, w, h, (margin, margin))
        if r:
            star(f, sx, sy, r, HEART_ARM, diag=diag)
        frames.append(f)
    return frames


GLINT_TICKS = [40, 2, 3, 3]   # 48-tick cycle: rest, then a 3-frame sparkle


# ==========================================================================
# Sub-weapons
# ==========================================================================
def dagger() -> Image.Image:
    """16x7 throwing knife, point right (projectile + sub-weapon icon).
    Lit from above-front: bright top bevel, a white ridge glint, a dark
    lower bevel; gold guard and pommel, dark wrapped grip."""
    ix = Indexed(16, 7, IR)
    for x in range(6, 13):
        ix.set_px(x, 2, "steel", 4 if x < 11 else 3)
        ix.set_px(x, 3, "steel", 5 if 7 <= x <= 9 else 4)
        if x < 12:
            ix.set_px(x, 4, "steel", 2 if x < 10 else 1)
    ix.set_px(13, 3, "steel", 4)
    ix.set_px(14, 3, "steel", 5)
    for y, t in zip(range(1, 6), (3, 4, 3, 2, 1)):
        ix.set_px(5, y, "gold", t)
    for x, (t2, t3, t4) in zip((2, 3, 4), ((2, 1, 1), (3, 2, 1), (2, 1, 1))):
        ix.set_px(x, 2, "leather", t2 + 1)
        ix.set_px(x, 3, "leather", t3 + 1)
        ix.set_px(x, 4, "leather", t4)
    ix.set_px(1, 2, "gold", 4)
    ix.set_px(1, 3, "gold", 3)
    ix.set_px(1, 4, "gold", 1)
    return ix.selout(lit_tone=1, light=unit((0.25, -0.85, 0.45)))


# -- axe --------------------------------------------------------------------
# Local axe geometry: haft along -y (head up), bearded crescent blade on +x.
# Units are px; the spin pivot is the head-heavy centre of mass.
AXE_COM: Pt = (1.6, -3.4)
AXE_HAFT = ((0.0, 6.0), (0.0, -6.6))
AXE_EYE = [(-1.3, -6.9), (1.5, -6.9), (1.6, -3.0), (-1.3, -3.0)]
AXE_BLADE = [(1.2, -6.8), (3.0, -7.1), (4.4, -8.3), (5.6, -9.9), (6.6, -8.4), (7.1, -6.0),
             (6.9, -3.4), (6.2, -1.2), (5.3, 0.7), (4.0, -0.6), (2.6, -2.0), (1.2, -3.2)]
AXE_EDGE = [(5.6, -9.9), (6.6, -8.4), (7.1, -6.0), (6.9, -3.4), (6.2, -1.2), (5.3, 0.7)]
AXE_POLL = [(-1.2, -6.2), (-2.9, -6.2), (-2.9, -3.8), (-1.2, -3.8)]


def _edge_field(X: Arr, Y: Arr, pts: Sequence[Pt]) -> tuple[Arr, Arr, Arr]:
    """Distance to a polyline and the unit vector pointing at it."""
    best = np.full(X.shape, np.inf)
    vx = np.zeros(X.shape)
    vy = np.zeros(X.shape)
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        d, t = d_segment(X, Y, a, b)
        px_ = a[0] + (b[0] - a[0]) * t
        py_ = a[1] + (b[1] - a[1]) * t
        upd = d < best
        best = np.where(upd, d, best)
        vx = np.where(upd, px_ - X, vx)
        vy = np.where(upd, py_ - Y, vy)
    n = np.maximum(np.hypot(vx, vy), 1e-6)
    return best, vx / n, vy / n


def axe_render(angle: float, size: int, light: Vec, at: Pt | None = None, *,
               scale: float = 1.0, haft: float = 1.0) -> Image.Image:
    """The axe rotated clockwise by `angle` about AXE_COM, centred at `at`
    (default the canvas centre), lit by a light fixed in the world: the
    cheek brightens toward the light, the ground bevel along the cutting
    edge flashes white where it faces the light and stays a bright steel
    line elsewhere (metal reads by its edges). `scale` shrinks the whole
    axe about its pivot; `haft` additionally shortens the haft below the
    collar (the part that swings widest)."""
    ic = Icon(size, size, light=light)
    xf = Xf(angle, AXE_COM, at if at is not None else (size / 2.0, size / 2.0), scale)
    lx, ly, _ = unit(light)
    ln = math.hypot(lx, ly) or 1.0
    # thin parts keep most of their width when scaled, or they break up at 1x
    rk = math.sqrt(scale)
    butt = AXE_HAFT[0][1] * haft + AXE_COM[1] * (1.0 - haft)
    # haft (walnut) with a gold butt cap and a gold collar under the head
    ic.capsule(xf((0.0, butt)), xf(AXE_HAFT[1]), 0.85 * rk, "wood", spec=0.3, gamma=1.0,
               ambient=0.2, group="haft")
    ic.ellipse(xf((0.0, butt + 0.2)), 1.2 * rk, 1.2 * rk, "gold", spec=0.6, group="cap")
    ic.capsule(xf((0.0, -2.3)), xf((0.0, -2.8)), 1.3 * rk, "gold", spec=0.7, group="collar")
    # head: eye + poll (darker, they sit in the blade's shadow)
    ic.polygon(xf.pts(AXE_EYE), "steel", edge=1.0 * rk, spec=0.3, bias=-0.10, group="head")
    ic.polygon(xf.pts(AXE_POLL), "steel", edge=0.7 * rk, spec=0.5, bias=0.0, group="head")
    blade = xf.pts(AXE_BLADE)
    m = poly_mask(ic.X, ic.Y, blade)
    d, ex, ey = _edge_field(ic.X, ic.Y, xf.pts(AXE_EDGE))
    cx, cy = xf((4.6, -4.4))
    # cheek: flat plate, brighter on the side toward the light
    grad = -((ic.X - cx) * lx + (ic.Y - cy) * ly) / (ln * 4.0 * scale)
    cheek = 0.60 + 0.22 * np.clip(grad, -1.0, 1.0)
    # bevel band along the edge: its normal leans out toward the edge
    facing = -(ex * lx + ey * ly) / ln          # > 0: the edge faces the light
    bev = 0.80 + 0.20 * np.clip(-facing, 0.0, 1.0)
    b0, b1 = 1.15 * rk, 1.75 * rk
    seam = (d > b0) & (d < b1)
    val = np.where(d < b0, bev, np.where(seam, cheek - 0.22, cheek))
    ic.flat(m, "steel", val.astype(np.float32), group="head")
    ix = ic.resolve(thresholds={"steel": (0.16, 0.34, 0.54, 0.76, 0.93)})
    ix.remove_orphans()
    return finish(ix, light=light, skip=("gold", "steel"), orphans=False)


def axe_icon() -> Image.Image:
    """16x16 sub-weapon icon: the axe cocked 35 degrees, head up-right."""
    return axe_render(35.0, 16, ICON_LIGHT, at=(8.3, 7.6))


AXE_SPIN_FRAMES = 12         # 30 degree steps
AXE_SPIN_SIZE = 26           # frame size; the art itself stays within ~9 px of the pivot
# The projectile's root (and with it the 14x14 hitbox) turns at spin_speed
# 14 rad/s in projectile.gd; scripts/projectiles/upright_spin_sprite.gd holds
# the sprite upright and picks the frame for the root's angle. A rotating
# 14x14 box reaches 7..9.9 px from the pivot, so the spin art is shrunk to
# fit inside it (largest opaque radius <= 9 px) and the blade never sweeps
# past where the axe can hit.
AXE_SPIN_SCALE = 0.86
AXE_SPIN_HAFT = 0.80         # the haft swings widest, so it gives up a little more


def axe_spin_frames() -> list[Image.Image]:
    """One full clockwise turn in 30 degree steps, head up on frame 0,
    pivot (the head-heavy centre of mass) at the frame centre. Frame k is
    the axe at k * 30 degrees, the angle the projectile root has reached."""
    return [axe_render(i * 360.0 / AXE_SPIN_FRAMES, AXE_SPIN_SIZE, LIGHT, scale=AXE_SPIN_SCALE,
                       haft=AXE_SPIN_HAFT)
            for i in range(AXE_SPIN_FRAMES)]


# -- sword icon ------------------------------------------------------------
def sword_icon() -> Image.Image:
    """16x16 menu icon: Vesper's slender sabre, point up-right, gold cup
    hilt. The blade is two 1x strokes (lit edge / shaded back) along a
    slight curve so it stays crisp; the hilt is rendered volume."""
    ic = Icon(16, 16)
    ic.ellipse((4.3, 11.0), 2.9, 1.45, "gold", rot=45.0, depth=1.4, spec=0.7, spec_pow=8, group="guard")
    ic.capsule((3.4, 12.6), (1.9, 14.1), 0.95, "leather", spec=0.2, group="grip")
    ic.ellipse((1.45, 14.55), 1.15, 1.15, "gold", spec=0.8, group="pommel")
    ix = ic.resolve(thresholds={"gold": (0.12, 0.28, 0.48, 0.70, 0.93)})
    ix.remove_orphans()
    blade = bezier_curve([(5.0, 10.0), (8.4, 4.4), (14.0, 1.0)], 16)
    occupied = ix.mat >= 0
    under = Indexed(16, 16, IR)
    under.stroke([(x + 1.0, y) for x, y in blade[:-2]], "steel", lambda t: 2 if t < 0.6 else 3)
    under.stroke(blade, "steel", lambda t: 5 if 0.42 < t < 0.62 else 4)
    under.set_px(14, 1, "steel", 3)
    sel = (under.mat >= 0) & ~occupied
    sid = ix.mat_id("steel")
    ix.mat[sel] = sid
    ix.tone[sel] = under.tone[sel]
    ix.group[sel] = ix.group_id("blade")
    ix.z[sel] = 0.5
    ix.interior_contours(skip=("gold", "steel"))
    img = ix.selout(lit_tone=1, light=ICON_LIGHT)
    put_px(img, [(3, 9)], tone("gold", 5))
    return img


# -- whip icon -------------------------------------------------------------
def cord_1x(ix: Indexed, path: Sequence[Pt], r0: float, r1: float, mat: str,
            tone_of: Callable[[float, float, float], int], *, group: str,
            light2: Pt = (-0.66, -0.75), s_out: Arr | None = None) -> Indexed:
    """A thin cord painted per pixel at 1x by rule (crisper than any
    supersampled tube at 2 px): every pixel centre within the radius of
    the path takes `tone_of(f, s, q)` -- f = how much its side of the
    cord faces the light (-1..1), s = arc length (px), q = 0 centre .. 1
    edge."""
    seg = [math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1]) for i in range(len(path) - 1)]
    total = sum(seg) or 1.0
    for y in range(ix.h):
        for x in range(ix.w):
            px_, py_ = x + 0.5, y + 0.5
            best, bs, bx, by = 1e9, 0.0, 0.0, 0.0
            acc = 0.0
            for i in range(len(path) - 1):
                (ax, ay), (bx_, by_) = path[i], path[i + 1]
                vx, vy = bx_ - ax, by_ - ay
                ll = vx * vx + vy * vy + 1e-9
                t = max(0.0, min(1.0, ((px_ - ax) * vx + (py_ - ay) * vy) / ll))
                qx, qy = ax + vx * t, ay + vy * t
                dd = math.hypot(px_ - qx, py_ - qy)
                if dd < best:
                    best, bs, bx, by = dd, acc + t * seg[i], qx, qy
                acc += seg[i]
            r = r0 + (r1 - r0) * bs / total
            if best > r:
                continue
            f = 0.0
            if best > 1e-6:
                f = ((px_ - bx) * light2[0] + (py_ - by) * light2[1]) / best
            q = best / max(r, 1e-6)
            ix.set_px(x, y, mat, tone_of(f, bs, q), group=group)
            if s_out is not None:
                s_out[y, x] = bs
    return ix


# The lash's coil: it leaves the ferrule at 140 degrees and runs about 1.35
# turns while its centre drifts up and to the right, so the second turn
# overlaps the first at the upper right like a coiled cord and the coil
# keeps one open hole (>= 2 px clear). The tail leaves from the top of the
# outer turn along the rim to the tip and never crosses the hole. (A single
# ring with the tail cut through its middle read as a red "no entry" sign.)
WHIP_CENTRE: tuple[Pt, Pt] = ((8.5, 8.9), (10.5, 6.5))                 # coil centre, start -> end
WHIP_RADII: Pt = (4.8, 4.3)
WHIP_COIL: tuple[float, float, float, int] = (140.0, 625.0, 0.86, 72)   # a0, a1 (deg), end k, samples
WHIP_TAIL: tuple[Pt, ...] = ((13.9, 3.4), (14.3, 2.2))                 # bezier controls to the tip


def whip_icon(coil: tuple[float, float, float, int] = WHIP_COIL,
              tail: Sequence[Pt] = WHIP_TAIL) -> Image.Image:
    """16x16 menu icon: the Crimson Lash coiled, handle low-left, the tail
    snapping out up-right to its 2 px silver tip. The braided cord is
    painted per pixel (`cord_1x`): its lit side bright, its far side dark,
    a dark gap every third pixel along it for the braid, and a crimson
    glint on every third bead, as docs/art_style.md describes."""
    ic = Icon(16, 16)
    ic.capsule((2.2, 13.8), (5.0, 11.0), 1.15, "leather", spec=0.25, bias=-0.06, group="grip")
    ic.ellipse((1.6, 14.4), 1.15, 1.15, "gold", spec=0.8, group="pommel")
    ic.ellipse((5.5, 10.5), 1.1, 1.1, "gold", spec=0.8, group="ferrule")
    hilt = ic.resolve()
    hilt.remove_orphans()
    (c0, c1), (rx, ry) = WHIP_CENTRE, WHIP_RADII
    a0, a1, k1, n = coil
    path: list[Pt] = []
    for i in range(n + 1):
        t = i / n
        a = math.radians(a0 + (a1 - a0) * t)
        k = 1.0 - (1.0 - k1) * t
        cx, cy = c0[0] + (c1[0] - c0[0]) * t, c0[1] + (c1[1] - c0[1]) * t
        path.append((cx + rx * k * math.cos(a), cy + ry * k * math.sin(a)))
    path += bezier_curve([path[-1], *tail], 5)[1:]

    def lash_tone(f: float, sv: float, q: float) -> int:
        t = 4 if f > 0.3 else 3 if f > -0.4 else 2
        if f > -0.4 and int(sv / 1.25) % 3 == 2:
            t -= 1                       # braid gap (on the lit side only)
        return t

    lash = Indexed(16, 16, IR)
    sm = np.full((16, 16), -1.0)
    cord_1x(lash, path, 1.2, 0.62, "lash", lash_tone, group="lash", s_out=sm)
    # crimson glints on lit beads, spaced evenly along the lash
    total = float(sm.max())
    for frac in (0.18, 0.42, 0.66, 0.86):
        want = frac * total
        cand = np.argwhere((lash.tone >= 4) & (lash.mat >= 0) & (sm >= 0))
        if len(cand):
            y, x = min(cand.tolist(), key=lambda p: abs(sm[p[0], p[1]] - want))
            lash.set_px(x, y, "crimson", 5, group="lash")
    ix = lash
    ix.overlay(hilt)
    ix.set_px(14, 2, "steel", 4, group="tip")
    ix.set_px(14, 1, "steel", 5, group="tip")
    ix.interior_contours(skip=("gold", "steel", "crimson"))
    return ix.selout(lit_tone=1, light=ICON_LIGHT)


# ==========================================================================
# World-item aura and glint (scenes/pickups/world_item.tscn)
# ==========================================================================
AURA_SIZE = 32
AURA_FRAMES = 8
AURA_TICKS = 8                     # 8 x 8 = the 64-tick relic pulse (docs/art_style.md)
AURA_RAMP: list[RGB] = [(10, 12, 24), (22, 26, 50), (40, 48, 86)]   # additive: dim on purpose
MOTE: RGB = (110, 130, 200)


def aura_frames() -> list[Image.Image]:
    """Posterized additive halo that breathes over 64 ticks, plus two 1 px
    motes on a tilted orbit. Drawn behind the item with BLEND_MODE_ADD, so
    dark values brighten the wall behind instead of covering it."""
    out: list[Image.Image] = []
    s = AURA_SIZE
    yy, xx = np.mgrid[0:s, 0:s]
    for f in range(AURA_FRAMES):
        ph = f / AURA_FRAMES
        rad = 9.5 + 2.0 * math.sin(2 * math.pi * ph)
        r = np.hypot(xx + 0.5 - s / 2.0, (yy + 0.5 - s / 2.0) * 1.08) / rad
        inten = np.clip(1.0 - r, 0.0, 1.0) ** 1.4
        v = inten + (bayer(4, (s, s)) - 0.5) * 0.22
        idx = np.full((s, s), -1)
        idx[v > 0.12] = 0
        idx[v > 0.38] = 1
        idx[v > 0.66] = 2
        arr = np.zeros((s, s, 4), np.uint8)
        for k, col in enumerate(AURA_RAMP):
            arr[idx == k, :3] = col
            arr[idx == k, 3] = 255
        img = Image.fromarray(arr, "RGBA")
        for m in range(2):
            a = 2 * math.pi * (ph + m * 0.5)
            mx = round(s / 2.0 - 0.5 + 10.5 * math.cos(a))
            my = round(s / 2.0 - 0.5 + 4.0 * math.sin(a) - 1.0)
            img.putpixel((mx, my), MOTE + (255,))
        out.append(img)
    return out


GLINT_SIZE = 16
GLINT_SPOT = (5, 4)                 # upper left of the 16x16 icon box
GLINT_ARM: RGB = (196, 210, 255)


def item_glint_frames() -> list[Image.Image]:
    """[nothing, sparkle grows, full star, fading]: docs/art_style.md's 3-frame
    1 px star glint every ~48 ticks, as an additive overlay."""
    frames = []
    for r, diag in ((0, False), (1, False), (2, True), (1, False)):
        f = Image.new("RGBA", (GLINT_SIZE, GLINT_SIZE), (0, 0, 0, 0))
        if r:
            star(f, GLINT_SPOT[0], GLINT_SPOT[1], r, GLINT_ARM, diag=diag)
        frames.append(f)
    return frames


ITEM_GLINT_TICKS = [44, 2, 3, 3]   # 52-tick cycle, out of step with the aura


# ==========================================================================
# Build
# ==========================================================================
def build() -> None:
    # The heart stills are only the source of the glinting pickup sheets (no
    # scene uses a still), so they stay in memory. The 2 px margin keeps the
    # art centred, so the scenes' offsets (0,-4) / (0,-7) still put the
    # heart's tip on the origin.
    hs, hb = heart_small(), heart_big()
    sb = SheetBuilder("pickup_heart_small", hs.width + 4, hs.height + 4)
    sb.add("idle", heart_glint_frames(hs, (2, 2), 2), 0, True, ticks=GLINT_TICKS)
    sb.save()
    sb = SheetBuilder("pickup_heart_big", hb.width + 4, hb.height + 4)
    sb.add("idle", heart_glint_frames(hb, (4, 3), 2), 0, True, ticks=GLINT_TICKS)
    sb.save()

    dagger().save(os.path.join(SPRITES, "dagger.png"))
    axe_icon().save(os.path.join(SPRITES, "axe.png"))
    # pre-rotated spin strip for the projectile (Sprite2D hframes in
    # scenes/projectiles/axe.tscn; upright_spin_sprite.gd picks the frame
    # from the rotating root's angle, so no animation ticks are involved)
    frames = axe_spin_frames()
    strip = Image.new("RGBA", (AXE_SPIN_SIZE * len(frames), AXE_SPIN_SIZE), (0, 0, 0, 0))
    for i, fr in enumerate(frames):
        strip.paste(fr, (i * AXE_SPIN_SIZE, 0))
    strip.save(os.path.join(SPRITES, "axe_spin.png"))
    with open(os.path.join(SPRITES, "axe_spin.json"), "w") as fh:
        json.dump({"frame_size": [AXE_SPIN_SIZE, AXE_SPIN_SIZE], "hframes": len(frames),
                   "origin": [AXE_SPIN_SIZE // 2, AXE_SPIN_SIZE // 2],
                   "step_degrees": 360.0 / len(frames), "direction": "clockwise",
                   "frame_selection": "round(abs(root rotation) / step) mod hframes; "
                                      "flip_h mirrors it for a left throw",
                   "driven_by": "res://scripts/projectiles/upright_spin_sprite.gd"}, fh, indent=2)

    sword_icon().save(os.path.join(SPRITES, "sword.png"))
    whip_icon().save(os.path.join(SPRITES, "whip.png"))

    sb = SheetBuilder("world_item_fx", AURA_SIZE, AURA_SIZE, origin=(AURA_SIZE // 2, AURA_SIZE // 2))
    sb.add("aura", aura_frames(), 0, True, ticks=[AURA_TICKS] * AURA_FRAMES)
    sb.add("glint", [pad_to(f, AURA_SIZE, AURA_SIZE) for f in item_glint_frames()], 0, True,
           ticks=ITEM_GLINT_TICKS)
    sb.save()
    print("items: hearts (+glint sheets), dagger, axe (+12-frame spin), sword, whip, world_item_fx")


if __name__ == "__main__":
    build()
