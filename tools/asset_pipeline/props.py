"""
World props: the breakable candlestick and the save-point reliquary
(SPEC 4.4.2), plus their additive light layers.

- candle           24x40, base on the bottom row (scene offset (0, -20)).
                   burn: gilt pricket candlestick with wax drips and a
                   lively 5-drawing flame flicker (irregular ticks).
- candle_halo      56x56 centred on the flame: 4 posterized warm rings
                   (radius ~4/7/12/18, checker only on the 2 px ring seams),
                   flickering +-1 px in radius and +-10 % in strength. ADD.
- save_shrine      48x68, base on the bottom row (scene offset (0, -34)),
                   4 rows of headroom so the finial draws in full.
                   idle: a gothic reliquary altar (stone steps, carved
                   marble altar with a blind arcade, gilt pinnacled canopy)
                   with a blood crystal floating in a crimson velvet niche,
                   bobbing and pulsing on a 64-tick cycle.
- save_shrine_glow 96x224, crystal at (48, 192) (scene: centered=false,
                   offset (-48, -192), positioned on the crystal). default:
                   pulsing crimson-violet halo and rising motes (loop, in
                   sync with idle). activate: the save light column (once),
                   190 px tall, its top dithered away rather than capped,
                   rising streak grain, a few pulse rings at uneven gaps on
                   its core and 1-px sparkles up its sides.

Shading follows the shared art rules: material ramps from common.RAMPS,
architecture lit from the upper left (LIGHT_ENV-like), sel-out outlines,
alpha 0/255, no dithering inside sprites (only in the additive halos).
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from PIL import Image

from common import (
    RAMPS, RGB, Indexed, SheetBuilder, bayer, heightmap_normals, indices_to_image,
    shade_normals,
)
from fx import FIRE, _tidy, _tones

# ---------------------------------------------------------------------------
# Ramps. Wax gets a darker outline tone below the shared WAX ramp so the
# candle's sel-out reads; it is never produced by shading (thresholds).
# ---------------------------------------------------------------------------
PROP_RAMPS: dict[str, list[RGB]] = dict(RAMPS)
PROP_RAMPS["wax_o"] = [(70, 52, 62)] + list(RAMPS["wax"])
PROP_RAMPS["fire"] = list(FIRE)
PROP_RAMPS["wick"] = [(24, 14, 18), (52, 30, 30)]
# crimson velvet lit only by the crystal: deepest wine -> lit fold crest
PROP_RAMPS["niche"] = [(14, 2, 10), (30, 4, 16), (56, 8, 26), (88, 14, 36), (130, 24, 48)]
# blood crystal: gem_ruby with a hotter rim glint
PROP_RAMPS["crystal"] = list(RAMPS["gem_ruby"])

# Upper-left key for props (they are never flipped); a bit more from above
# than LIGHT_ENV, since candle flames sit over them.
PROP_LIGHT = (-0.42, -0.78, 0.48)


def _paint(ix: Indexed, mask: np.ndarray, mat: str, tone: np.ndarray | int, group: str | None = None) -> None:
    """Write a material/tone layer into an Indexed in front of what is there."""
    m = np.asarray(mask, bool)
    if not m.any():
        return
    mid = ix.mat_id(mat)
    gid = ix.group_id(group or mat)
    z = ix._front_z()
    ix.mat[m] = mid
    t = np.broadcast_to(np.asarray(tone, np.int16), m.shape)
    n = len(ix.ramps[mat])
    ix.tone[m] = np.clip(t[m], 0, n - 1)
    ix.group[m] = gid
    ix.z[m] = z
    ix.part[m] = -2


def _grid(w: int, h: int) -> tuple[np.ndarray, np.ndarray]:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    return xx + 0.5, yy + 0.5


def _quant(v: np.ndarray, n: int, lo: int = 0, hi: int | None = None,
           cuts: Sequence[float] | None = None) -> np.ndarray:
    """Intensity 0..1 -> tone in [lo, hi]."""
    hi = n - 1 if hi is None else hi
    k = hi - lo + 1
    c = np.asarray(cuts if cuts is not None else [i / k for i in range(1, k)], np.float64)
    return (lo + np.searchsorted(c, v, side="right")).astype(np.int16)


# ---------------------------------------------------------------------------
# Candle flame (shared by the candlestick)
# ---------------------------------------------------------------------------
FLAME_CUTS = (0.06, 0.2, 0.38, 0.56, 0.74, 0.92)


def _flame_field(w: int, h: int, cx: float, base_y: float, height: float, width: float,
                 lean: float, tip: float = 0.0) -> np.ndarray:
    """Teardrop flame: widest a third of the way up, white-hot low centre,
    tip bent by `lean` (px at the top). `tip` adds a detached flicker blob
    above the point."""
    X, Y = _grid(w, h)
    v = (base_y - Y) / height                      # 0 at the base, 1 at the tip
    vc = np.clip(v, 0.0, 1.0)
    prof = np.where(v < 0.3, np.sqrt(np.clip(v / 0.3, 0, 1)) * 0.85 + 0.15, (1.0 - (vc - 0.3) / 0.7) ** 0.9)
    hw = width * np.clip(prof, 0.0, 1.0) + 0.25
    u = (X - cx - lean * vc ** 2) / hw
    core = np.clip(1.0 - u * u, 0.0, 1.0) ** 0.6 * np.clip(1.0 - vc, 0.0, 1.0) ** 0.45
    f = np.where((v >= -0.08) & (v <= 1.0), core * 1.15, 0.0)
    if tip:
        ty = base_y - height - tip
        q = ((X - cx - lean * 1.2) ** 2 + ((Y - ty) / 1.4) ** 2)
        f = np.maximum(f, np.where(q <= 1.1, 0.42, 0.0))
    return f


# (height, half-width, lean, detached tip)
FLAME_SHAPES: dict[str, tuple[float, float, float, float]] = {
    "a": (9.0, 2.6, 0.0, 0.0),     # calm
    "b": (10.0, 2.4, -1.2, 0.0),   # leaning back
    "c": (7.5, 3.0, 0.4, 0.0),     # squat flare
    "d": (11.0, 2.2, 0.9, 2.0),    # tall, a tip tears off
    "e": (9.0, 2.7, 1.3, 0.0),     # leaning forward
}
CANDLE_SEQ: tuple[tuple[str, int], ...] = (
    ("a", 8), ("b", 6), ("c", 8), ("b", 6), ("d", 3), ("a", 7), ("e", 6), ("c", 5))


# ---------------------------------------------------------------------------
# Candlestick (24x40, base row 39, axis between columns 11 and 12)
# ---------------------------------------------------------------------------
CANDLE_W, CANDLE_H = 24, 40
CAX = 12.0                 # lathe axis (between columns 11 and 12)
WICK_Y = 18                # top row of the wax; the flame sits just above
FLAME_BASE = 17.9

# Lathe profile of the gilt pricket stand, top -> bottom:
# (row, half-width, tone bias, specular?) - bias -1 for recessed necks and
# the shadowed underside of the drip pan, +1 for the bright pan rim.
STAND_PROFILE: tuple[tuple[int, float, int, bool], ...] = (
    (26, 6.0, 1, True),     # drip pan rim
    (27, 5.0, 0, False),
    (28, 3.0, -1, False),   # pan underside
    (29, 1.0, -1, False),   # neck
    (30, 2.0, 0, True),     # upper knop
    (31, 1.0, -1, False),
    (32, 3.0, 1, True),     # main knop
    (33, 3.0, 0, False),
    (34, 1.0, -1, False),
    (35, 2.0, 0, True),     # lower knop
    (36, 3.0, 0, False),    # domed base
    (37, 4.0, 0, True),
    (38, 6.0, 0, False),    # foot ring
)
WAX_ROWS = range(WICK_Y, 26)


def _lathe_tone(x: int, hw: float, bias: int, spec: bool, n: int) -> int:
    """Tone for column x of a turned (lathe) part lit from the upper left:
    bright band left of the axis, a specular on swelling parts, darker
    toward the right rim."""
    f = (x + 0.5 - (CAX - hw)) / (2.0 * hw)          # 0 left edge .. 1 right edge
    if f < 0.12:
        t = 3
    elif f < 0.38:
        t = 5 if (spec and 0.18 <= f < 0.3) else 4
    elif f < 0.62:
        t = 3
    elif f < 0.85:
        t = 2
    else:
        t = 1
    if t != 5:
        t += bias
    return max(1, min(n - 1, t))


def _candlestick() -> Indexed:
    """The gilt pricket stand and the wax candle (no flame), drawn once from
    a lathe profile: about 31 px tall with the flame, a third smaller than
    the hero, centred on the axis with an upper-left light."""
    ix = Indexed(CANDLE_W, CANDLE_H, PROP_RAMPS)
    ng = len(PROP_RAMPS["gold"])
    for y, hw, bias, spec in STAND_PROFILE:
        for x in range(int(CAX - hw), int(CAX + hw)):
            ix.set_px(x, y, "gold", _lathe_tone(x, hw, bias, spec, ng), group="stand")
    # rolled ends of the drip pan and two claw feet + a front toe
    for x, y, t in ((5, 25, 3), (18, 25, 1), (5, 26, 4), (18, 26, 2),
                    (5, 39, 3), (6, 39, 4), (17, 39, 2), (18, 39, 1), (11, 39, 4), (12, 39, 2)):
        ix.set_px(x, y, "gold", t, group="stand")
    # the candle: a 4 px wax column, dished top, drips down the side and pan
    nw = len(PROP_RAMPS["wax_o"])
    for y in WAX_ROWS:
        for x, t in ((10, 3), (11, 4), (12, 3), (13, 2)):
            ix.set_px(x, y, "wax_o", min(nw - 1, t), group="wax")
    for x, t in ((10, 4), (11, 3), (12, 2), (13, 3)):
        ix.set_px(x, WICK_Y, "wax_o", t, group="wax")
    for x, y0, y1, t in ((10, 20, 22, 4), (13, 21, 24, 1), (9, 26, 27, 3), (14, 26, 28, 2)):
        for y in range(y0, y1 + 1):
            ix.set_px(x, y, "wax_o", t if y < y1 else max(1, t - 1), group="wax")
    # wick
    ix.set_px(12, WICK_Y - 1, "wick", 1, group="wick")
    ix.set_px(12, WICK_Y, "wick", 0, group="wick")
    return ix


def candle(shape: str, stick: Indexed) -> Image.Image:
    ix = stick.copy()
    h, w, lean, tip = FLAME_SHAPES[shape]
    f = _flame_field(CANDLE_W, CANDLE_H, CAX + 0.5, FLAME_BASE, h, w, lean, tip)
    idx = _tidy(_tones(f, FLAME_CUTS), iterations=0)
    _paint(ix, idx >= 0, "fire", np.maximum(idx, 0), group="flame")
    img = ix.selout(lit_tone=1, light=PROP_LIGHT)
    # the flame keeps a hot fringe instead of a dark outline (it is a light)
    arr = np.array(img)
    fl = ix.mask("fire")
    ring = np.zeros_like(fl)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        ring |= np.roll(np.roll(fl, dy, 0), dx, 1)
    ring &= ~(ix.mat >= 0)
    arr[ring] = (0, 0, 0, 0)
    return Image.fromarray(arr, "RGBA")


def build_candle() -> None:
    stick = _candlestick()
    drawn = {k: candle(k, stick) for k in FLAME_SHAPES}
    sb = SheetBuilder("candle", CANDLE_W, CANDLE_H, origin=(CANDLE_W // 2, CANDLE_H - 1))
    sb.add("burn", [drawn[k] for k, _ in CANDLE_SEQ], 60, True, ticks=[t for _, t in CANDLE_SEQ])
    sb.save()


# ---------------------------------------------------------------------------
# Candle halo (56x56, additive, centred on the flame)
# ---------------------------------------------------------------------------
HALO_SIZE = 56
# outer -> inner. A tight warm pool (radius ~4/7/12/18) whose strength is
# concentrated near the flame: a wide, evenly faint disc read as a muddy
# brown smudge on the indigo stone. The rings lean red-orange (little blue)
# so they still read as firelight once added to the cool mid-value wainscot.
HALO_RAMP: list[RGB] = [(20, 10, 3), (40, 20, 6), (72, 40, 12), (120, 72, 24)]
HALO_RINGS: tuple[float, ...] = (1.0, 12.0 / 18.0, 7.0 / 18.0, 4.0 / 18.0)   # x outer radius
HALO_SEQ: tuple[tuple[float, float, int], ...] = (       # (outer radius, strength, ticks)
    (18.0, 1.0, 9), (19.0, 1.1, 7), (17.0, 0.9, 11), (18.5, 1.05, 8))


def _halo(size: int, radii: Sequence[float], ramp: Sequence[RGB], strength: float,
          band_px: float = 2.0, offset: tuple[int, int] = (0, 0)) -> Image.Image:
    """Posterized concentric rings (outer -> inner radii): solid steps,
    with a 2x2 checker only in a `band_px` wide seam across each ring edge,
    colours scaled by `strength`."""
    X, Y = _grid(size, size)
    c = size / 2.0
    r = np.hypot(X - c, Y - c)
    checker = bayer(2, (size, size), offset) < 0.5
    half = band_px / 2.0
    idx = np.full((size, size), -1, np.int16)
    for k, rad in enumerate(radii):
        inside = (r <= rad - half) | ((r <= rad + half) & checker)
        idx = np.where(inside, k, idx)
    cols = [tuple(int(min(255, round(v * strength))) for v in col) for col in ramp]
    return indices_to_image(idx, cols)  # type: ignore[arg-type]


def build_candle_halo() -> None:
    frames = []
    for outer, strength, _ in HALO_SEQ:
        frames.append(_halo(HALO_SIZE, tuple(outer * f for f in HALO_RINGS), HALO_RAMP, strength))
    sb = SheetBuilder("candle_halo", HALO_SIZE, HALO_SIZE, origin=(HALO_SIZE // 2, HALO_SIZE // 2))
    sb.add("default", frames, 60, True, ticks=[t for _, _, t in HALO_SEQ])
    sb.save()


# ---------------------------------------------------------------------------
# Save shrine: gothic reliquary altar (48x68, base row 67, axis x = 24)
# ---------------------------------------------------------------------------
SHRINE_W, SHRINE_H = 48, 68
SHRINE_TOP = 4               # headroom rows: the fleur finial and its outline draw in full
SAX = 24.0
CRYSTAL_C = (24.0, 25.0)     # crystal centre (rest position), in rows below SHRINE_TOP
SHRINE_TICKS = [8] * 8       # 64-tick breathing cycle
BOB = [0, -1, -1, -1, 0, 1, 1, 1]          # crystal bob per frame (px)
PULSE = [0.0, 0.35, 0.75, 1.0, 0.75, 0.35, 0.0, -0.25]


def _relief_tone(h: np.ndarray, n: int, *, strength: float = 2.4, lo: int = 1, hi: int | None = None,
                 bias: float = 0.0, ao: float = 0.35) -> np.ndarray:
    """Heightfield -> lit tone (upper-left light), AO in the hollows."""
    nx, ny, nz = heightmap_normals(h, strength, wrap=False)
    lit = shade_normals(nx, ny, nz, PROP_LIGHT, ambient=0.18, gamma=1.0, rim=0.0)
    span = float(h.max() - h.min()) or 1.0
    lit = lit * ((1.0 - ao) + ao * (h - h.min()) / span) + bias
    return _quant(np.clip(lit, 0, 1), n, lo, hi)


def _rect(X: np.ndarray, Y: np.ndarray, x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    """Pixels whose centres lie in [x0, x1) x [y0, y1)."""
    return (X >= x0) & (X < x1) & (Y >= y0) & (Y < y1)


def _pointed_arch(X: np.ndarray, Y: np.ndarray, cx: float, half: float, spring_y: float,
                  apex_y: float) -> np.ndarray:
    """Inside of a two-centred (equilateral-ish) pointed arch of half-width
    `half` springing at `spring_y` with its point at `apex_y`; below the
    springing line it is a straight-sided opening."""
    hgt = spring_y - apex_y
    # each side is an arc centred on the opposite jamb's springing line
    rad = (half * half + hgt * hgt) / (2.0 * half)
    left_c = cx + half - rad
    right_c = cx - half + rad
    in_l = np.hypot(X - right_c, Y - spring_y) <= rad
    in_r = np.hypot(X - left_c, Y - spring_y) <= rad
    upper = (Y < spring_y) & in_l & in_r & (Y >= apex_y)
    lower = (Y >= spring_y) & (np.abs(X - cx) <= half)
    return upper | lower


def _shrine_base() -> Indexed:
    """Everything that does not animate: steps, altar, canopy, niche cloth.
    Drawn in rows measured from SHRINE_TOP (the headroom above the finial)."""
    W, H = SHRINE_W, SHRINE_H
    X, Y = _grid(W, H)
    Y = Y - SHRINE_TOP
    ix = Indexed(W, H, PROP_RAMPS)

    def px(x: int, y: int, mat: str, tone: int, group: str) -> None:
        ix.set_px(x, y + SHRINE_TOP, mat, tone, group=group)

    nst = len(PROP_RAMPS["stone"])
    nmb = len(PROP_RAMPS["marble"])
    # --- two stone steps ----------------------------------------------------
    for (x0, x1, y0, y1) in ((2, 46, 59, 64), (6, 42, 55, 59)):
        m = _rect(X, Y, x0, y0, x1, y1)
        tone = np.where(Y < y0 + 1, 6, np.where(Y < y0 + 2, 5, 3))     # lit tread, lip, riser
        tone = np.where(m & (X < x0 + 1), np.maximum(tone - 1, 2), tone)
        tone = np.where(m & (X >= x1 - 1), 2, tone)
        tone = np.where(m & (Y >= y1 - 1) & (Y >= y0 + 2), 2, tone)
        # joints between step blocks
        for jx in range(x0 + 9, x1 - 4, 11):
            tone = np.where(m & (np.abs(X - jx - 0.5) < 0.5) & (Y >= y0 + 2), 1, tone)
        _paint(ix, m, "stone", tone, group=f"step{y0}")
    # --- altar body with a blind arcade (marble heightfield) ----------------
    ax0, ax1, ay0, ay1 = 10, 38, 40, 55
    m = _rect(X, Y, ax0, ay0, ax1, ay1)
    h = np.ones((H, W))
    # three pointed-arch recesses on the front, colonnettes between them
    for cx in (16.0, 24.0, 32.0):
        rec = _pointed_arch(X, Y, cx, 2.6, 46.0, 42.0) & (Y < 53)
        h = np.where(rec, 0.35, h)
    for cx in (12.0, 20.0, 28.0, 36.0):
        col = (np.abs(X - cx) <= 1.0) & (Y >= 42) & (Y < 54)
        h = np.where(col, 1.0 + 0.35 * np.cos((X - cx) * 1.2), h)
    h = np.where(Y >= 53, 1.2, h)                       # plinth band
    h = np.where(Y < 42, 1.15, h)                       # frieze under the mensa
    tone = _relief_tone(np.where(m, h, 0.0), nmb, lo=1, hi=4)
    tone = np.where(m & (X >= ax1 - 1), 1, tone)        # shadowed right edge
    _paint(ix, m, "marble", tone, group="altar")
    # a ruby rose (quatrefoil) inlaid in the central recess
    rose = [(24, 47, 3), (23, 48, 2), (25, 48, 2), (24, 49, 2), (24, 48, 4), (23, 47, 1), (25, 47, 1)]
    for x, y, t in rose:
        px(x - 1, y, "gem_ruby", t, "rose")
    # --- mensa slab with a gilt moulding -----------------------------------
    m = _rect(X, Y, 7, 36, 41, 40)
    tone = np.where(Y < 37, 4, np.where(Y < 38, 3, 2))
    tone = np.where(m & (X < 8), 3, tone)
    tone = np.where(m & (X >= 40), 2, tone)
    _paint(ix, m, "marble", tone, group="mensa")
    gm = _rect(X, Y, 8, 39, 40, 40)
    _paint(ix, gm, "gold", np.where(X < 24, 4, 3), group="mould")
    _paint(ix, _rect(X, Y, 10, 40, 38, 41), "gold", 1, group="mould")
    # --- canopy: two piers, a pointed arch and a gable with crockets --------
    # piers
    for (x0, x1) in ((8, 13), (35, 40)):
        pm = _rect(X, Y, x0, 14, x1, 36)
        ph = 1.0 + 0.0 * X
        ph = np.where(X < x0 + 1, 0.7, ph)
        ph = np.where(X >= x1 - 1, 0.7, ph)
        # a sunk panel with a little lancet down the pier face
        lan = _pointed_arch(X, Y, (x0 + x1) / 2.0 - 0.5, 0.9, 22.0, 19.0) & (Y < 32)
        ph = np.where(lan, 0.5, ph)
        tone = _relief_tone(np.where(pm, ph, 0.0), nmb, lo=1, hi=4, strength=2.0)
        _paint(ix, pm, "marble", tone, group=f"pier{x0}")
        # gilt capital band and base band
        _paint(ix, _rect(X, Y, x0 - 1, 13, x1 + 1, 15), "gold", np.where(X < x0 + 2, 4, 3), group=f"cap{x0}")
        _paint(ix, _rect(X, Y, x0 - 1, 34, x1 + 1, 36), "gold", np.where(X < x0 + 2, 4, 2), group=f"cap{x0}")
        # pinnacle: a faceted spire with crockets and a knob finial
        pcx = (x0 + x1) / 2.0 - 0.5
        spire = (Y >= 4) & (Y < 13) & (np.abs(X - pcx - 0.5) <= (Y - 4) / 9.0 * 2.6 + 0.4)
        stone_t = np.where(X < pcx + 0.5, 4, 2)
        _paint(ix, spire, "gold", stone_t, group=f"spire{x0}")
        for cy in (7, 10):
            half = (cy - 4) / 9.0 * 2.6 + 0.4
            px(int(pcx - half - 0.5), cy, "gold", 3, f"spire{x0}")
            px(int(pcx + half + 1.5), cy, "gold", 2, f"spire{x0}")
        px(int(pcx), 3, "gold", 5, f"spire{x0}")
        px(int(pcx + 1), 3, "gold", 3, f"spire{x0}")
        px(int(pcx), 2, "gold", 4, f"spire{x0}")
    # the arch itself: a 2 px gilt moulding around the niche opening
    outer = _pointed_arch(X, Y, SAX, 11.0, 22.0, 6.0) & (Y < 36)
    inner = _pointed_arch(X, Y, SAX, 9.0, 22.0, 9.0) & (Y < 36)
    band = outer & ~inner & (X >= 13) & (X < 35)
    edge_lit = band & (X < SAX)
    _paint(ix, band, "gold", np.where(edge_lit, 4, 2), group="arch")
    # inner edge of the moulding one tone darker (a groove)
    groove = band & ~(_pointed_arch(X, Y, SAX, 10.0, 22.0, 7.5) & (Y < 36))
    _paint(ix, groove & inner.__invert__(), "gold", np.where(X < SAX, 5, 3), group="arch")
    # gable above the arch (marble triangle) with gilt edges and finial
    gab = (Y >= 1) & (Y < 14) & (np.abs(X - SAX) <= (Y - 1) * 0.95 + 0.5) & ~outer & (X >= 13) & (X < 35)
    gtone = _relief_tone(np.where(gab, 1.0 + 0.0 * X, 0.0), nmb, lo=1, hi=3)
    _paint(ix, gab, "marble", gtone, group="gable")
    gedge = gab & ~((Y >= 2) & (np.abs(X - SAX) <= (Y - 2) * 0.95 - 0.3))
    _paint(ix, gedge, "gold", np.where(X < SAX, 4, 2), group="gable_edge")
    # a small rose window (trefoil) in the gable
    for x, y, t in ((23, 10, 3), (24, 10, 3), (23, 11, 1), (24, 11, 1), (22, 11, 2), (25, 11, 1)):
        px(x, y, "gem_ruby", t, "gable_rose")
    # finial: a gilt fleur-cross on the apex - a pointed central petal, two
    # side petals curling up off a crossbar, a collar on the gable point
    # (lit left, shaded right; it rises into the headroom rows)
    for x, y, t in ((23, -2, 4), (24, -2, 3),
                    (21, -1, 3), (23, -1, 5), (24, -1, 3), (26, -1, 2),
                    (21, 0, 4), (22, 0, 4), (23, 0, 4), (24, 0, 3), (25, 0, 2), (26, 0, 2),
                    (22, 1, 3), (23, 1, 5), (24, 1, 3), (25, 1, 2)):
        px(x, y, "gold", t, "finial")
    # --- niche: crimson velvet drape behind the crystal ---------------------
    niche = inner & (Y < 36) & (X >= 15) & (X < 33)
    _paint(ix, niche, "niche", 0, group="niche")
    return ix


def _crystal(ix: Indexed, cx: float, cy: float, pulse: float) -> None:
    """Faceted blood crystal: a long bipyramid (7 x 15 px) seen with three
    facets - lit left, bright front ridge, dark right - a pale rim on the
    lit edge and a 1 px glint. `pulse` (-0.25..1) feeds a small inner
    core; the real glow is the additive save_shrine_glow layer."""
    W, H = ix.w, ix.h
    X, Y = _grid(W, H)
    dx, dy = X - cx, Y - cy
    hw, top, bot = 3.6, 8.0, 7.0
    up = dy < 0
    d = np.where(up, np.abs(dx) / hw + (-dy) / top, np.abs(dx) / hw + dy / bot)
    body = d <= 1.0
    left, mid = dx < -1.0, np.abs(dx) <= 1.0
    tone = np.where(left, 2, np.where(mid, np.where(up, 3, 2), 1))
    tone = np.where(mid & (dy > 3.0), 1, tone)
    # pale rim along the lit upper-left edge, dark rim lower right
    rim = body & (d > 0.7)
    tone = np.where(rim & (dx < 0) & (dy < 0), 3, tone)
    tone = np.where(rim & (dx > 0) & (dy > -2), 0, tone)
    # inner core: a short bright seam that swells with the pulse
    core = mid & (np.abs(dy + 1.0) <= 0.5 + 1.8 * max(0.0, pulse))
    tone = np.where(core & body, np.where(np.abs(dy + 1.0) <= 0.5 + 0.8 * max(0.0, pulse), 4, 3), tone)
    _paint(ix, body, "crystal", tone, group="crystal")
    ix.set_px(int(cx - 2), int(cy - 4), "crystal", 4, group="crystal")
    ix.set_px(int(cx - 2), int(cy - 3), "crystal", 4, group="crystal")


def _niche_light(ix: Indexed, cx: float, cy: float, pulse: float) -> None:
    """Relight the velvet niche by distance to the crystal, with soft
    vertical folds (crest every 4 px) catching the glow."""
    X, Y = _grid(ix.w, ix.h)
    m = ix.mask("niche")
    d = np.hypot((X - cx) * 1.0, (Y - cy) * 0.75)
    fold = np.cos((X - 15.0) * (math.tau / 4.5))
    lit = np.clip(1.0 - d / (13.0 + 3.0 * pulse), 0.0, 1.0) + 0.12 * fold - 0.04
    tone = np.where(lit > 0.62, 4, np.where(lit > 0.42, 3, np.where(lit > 0.24, 2, np.where(lit > 0.08, 1, 0))))
    ix.tone[m] = tone[m]


def shrine(frame: int, base: Indexed) -> Image.Image:
    ix = base.copy()
    cx, cy = CRYSTAL_C[0], CRYSTAL_C[1] + SHRINE_TOP + BOB[frame]
    _niche_light(ix, cx, cy, PULSE[frame])
    _crystal(ix, cx, cy, PULSE[frame])
    ix.interior_contours(skip=("gold", "gem_ruby", "crystal", "niche"))
    return ix.selout(lit_tone=1, light=PROP_LIGHT)


# ---------------------------------------------------------------------------
# Shrine glow (96x224, additive; crystal at (48, 192)). The tall frame is
# headroom for the save-light column; the idle glow uses only its bottom.
# ---------------------------------------------------------------------------
GLOW_W, GLOW_H = 96, 224
GLOW_C = (48.0, 192.0)
BEAM_REACH = 190.0           # px above the crystal: the column runs off the top of the screen
BEAM_FADE = 24.0             # its top this many px thin out through a 2x2 ordered dither
# additive crimson-violet: outer haze -> inner ring (kept dim, it is added)
GLOW_RAMP: list[RGB] = [(16, 4, 14), (30, 8, 26), (50, 14, 44), (78, 26, 70)]
MOTE_RAMP: list[RGB] = [(60, 20, 50), (120, 60, 110), (150, 160, 206), (220, 220, 245)]
# activation column: crimson C4 sheath -> violet -> (150,160,206) core
BEAM_RAMP: list[RGB] = [(40, 6, 18), (88, 14, 36), (124, 20, 44), (96, 70, 140), (150, 160, 206),
                        (230, 232, 250)]
ACTIVATE_TICKS = [2, 2, 3, 3, 4, 4, 4, 5, 6, 8]


def _glow_frame(frame: int, motes: np.ndarray) -> Image.Image:
    p = PULSE[frame]
    X, Y = _grid(GLOW_W, GLOW_H)
    cx, cy = GLOW_C[0], GLOW_C[1] + BOB[frame]
    r = np.hypot(X - cx, (Y - cy) * 1.1)
    b = bayer(4, (GLOW_H, GLOW_W)) - 0.5
    rj = r + b * 3.0
    radii = [30 + 2 * p, 21 + 2 * p, 13 + 1.5 * p, 7 + 1.5 * p]
    idx = np.full((GLOW_H, GLOW_W), -1, np.int16)
    for k, rad in enumerate(radii):
        idx = np.where(rj <= rad, k, idx)
    # a faint shaft of light rising off the crystal
    shaft = (np.abs(X - cx) <= 2.5 + 0.5 * p) & (Y < cy - 6) & (Y > cy - 60 - 6 * p)
    fade = (cy - 6 - Y) / 60.0
    shaft_t = np.where(fade + b * 0.25 < 0.45, 1, 0)
    idx = np.where(shaft & (idx < shaft_t + 1), np.maximum(idx, shaft_t), idx)
    img = indices_to_image(idx, GLOW_RAMP)
    # rising motes (1 px, brightest mid-life)
    arr = np.array(img)
    t = frame * 8
    for mx, my, sp, ph, life in motes:
        age = (t + ph) % life
        y = my - sp * age
        x = mx + 1.5 * math.sin((age + ph) * 0.15)
        k = age / life
        tone = 1 if k < 0.2 else (3 if k < 0.45 else (2 if k < 0.75 else 0))
        xi, yi = int(x), int(y)
        if 0 <= xi < GLOW_W and 0 <= yi < GLOW_H:
            arr[yi, xi, :3] = MOTE_RAMP[tone]
            arr[yi, xi, 3] = 255
    return Image.fromarray(arr, "RGBA")


# Pulse rings in the activate column: born at the crystal every
# RING_BIRTHS ticks (uneven gaps, so ~29-40 px apart: never a ladder),
# rising RING_SPEED px/tick, drawn only on the column's core and fading out
# by RING_REACH px above the crystal.
RING_BIRTHS: tuple[int, ...] = (-30, -20, -9, 0, 12, 21, 32, 42)
RING_SPEED = 3.2
RING_REACH = 120.0
# 12 1-px sparkles rising beside the column at 3 px/tick (MOTE_RAMP 2-3).
COLUMN_MOTES = 12


def _activate_frames() -> list[Image.Image]:
    """The save light: a column of crimson-violet light shoots up through
    the shrine (and on out of the top of the screen), its white-blue core
    pulses, then it thins and fades. No cap: the top BEAM_FADE px of the
    column thin out through a 2x2 ordered dither. Inside, the band edges
    wobble on rising streak noise (an ordered dither made a regular zipper)
    and a few pulse rings rise off the crystal at uneven gaps; 1-px motes
    sparkle up its sides."""
    from scipy.ndimage import zoom
    from common import value_noise
    out: list[Image.Image] = []
    X, Y = _grid(GLOW_W, GLOW_H)
    cx, cy = GLOW_C
    b2 = bayer(2, (GLOW_H, GLOW_W))
    # vertical streaks, scrolled up with time: tall, irregular light grain
    st = 6
    streak_n = value_noise(GLOW_W, (GLOW_H + 200) // st + 2, 2.0, 913, tileable=True)
    streak_n = zoom(streak_n, (st, 1.0), order=1) - 0.5
    g = np.random.default_rng(311)
    m_x = g.uniform(-1.0, 1.0, COLUMN_MOTES)          # x as a fraction of (width + 3)
    m_y = g.uniform(cy - 150.0, cy + 6.0, COLUMN_MOTES)
    m_birth = g.integers(0, 5, COLUMN_MOTES)          # the frame it appears on
    m_tone = g.integers(2, 4, COLUMN_MOTES)
    n = len(ACTIVATE_TICKS)
    acc = 0
    for k in range(n):
        t = k / (n - 1)
        reach = min(1.0, (k + 1) / 3.0)                    # column climbs in 3 frames
        width = (5.0 + 9.0 * math.sin(min(1.0, t * 1.6) * math.pi / 2)) * (1.0 - 0.75 * max(0.0, t - 0.6) / 0.4)
        top = cy - 4 - reach * (BEAM_REACH - 4)
        inten = (1.0 - max(0.0, t - 0.45) / 0.55 * 0.85)
        dx = np.abs(X - cx) / max(width, 0.5)
        col = np.where((Y >= top) & (Y <= cy + 30), np.clip(1.0 - dx, 0, 1) ** 0.9, 0.0)
        col = col * np.clip((cy + 30 - Y) / 14.0, 0, 1) * inten
        # pulse rings: core only, uneven spacing, fading with height
        ring = np.zeros_like(col)
        for born in RING_BIRTHS:
            d = 4.0 + (acc - born) * RING_SPEED
            if 0.0 < d < RING_REACH:
                ry = cy - d
                fade = 1.0 - d / RING_REACH
                ring = np.maximum(ring, np.where((np.abs(Y - ry) < 1.0) & (np.abs(X - cx) < 0.6 * width),
                                                 0.12 * fade, 0.0))
        grain = np.roll(streak_n, -int(acc * 4.0), axis=0)[:GLOW_H]       # rises 4 px/tick
        f = col + ring * (col > 0.05) + grain * 0.10 * (col > 0.02)
        idx = np.searchsorted(np.array([0.06, 0.2, 0.36, 0.55, 0.75, 0.92]), f, side="right") - 1
        idx = np.where(f > 0.06, idx, -1).astype(np.int16)
        # the leading BEAM_FADE px thin out (2x2 ordered dither), no rounded cap
        keep = np.clip((Y - top) / BEAM_FADE, 0.0, 1.0)
        idx = np.where(b2 < keep, idx, -1).astype(np.int16)
        # base flare on the altar
        flare = np.hypot((X - cx) / 1.0, (Y - cy - 2) * 2.2) <= 16 * (1.0 - t) + 4
        idx = np.where(flare & (idx < 1), 1, idx)
        arr = np.array(indices_to_image(idx, BEAM_RAMP))
        # sparkles rising up the column's sides
        for i in range(COLUMN_MOTES):
            if k < m_birth[i]:
                continue
            y = int(m_y[i] - 3.0 * acc)
            x = int(cx + m_x[i] * (width + 3.0))
            if top + 4 <= y < GLOW_H and 0 <= x < GLOW_W:      # never ahead of the column
                c = MOTE_RAMP[int(m_tone[i])]
                arr[y, x, :3] = np.maximum(arr[y, x, :3], np.array(c, np.uint8))
                arr[y, x, 3] = 255
        out.append(Image.fromarray(arr, "RGBA"))
        acc += ACTIVATE_TICKS[k]
    return out


def build_shrine() -> None:
    base = _shrine_base()
    sb = SheetBuilder("save_shrine", SHRINE_W, SHRINE_H, origin=(SHRINE_W // 2, SHRINE_H - 1))
    sb.add("idle", [shrine(i, base) for i in range(len(SHRINE_TICKS))], 60, True, ticks=SHRINE_TICKS)
    sb.save()
    g = np.random.default_rng(77)
    motes = np.stack([GLOW_C[0] + g.uniform(-14, 14, 10), GLOW_C[1] + g.uniform(-4, 30, 10),
                      g.uniform(0.35, 0.6, 10), g.uniform(0, 64, 10), g.uniform(48, 80, 10)], 1)
    sb = SheetBuilder("save_shrine_glow", GLOW_W, GLOW_H, origin=(int(GLOW_C[0]), int(GLOW_C[1])))
    sb.add("default", [_glow_frame(i, motes) for i in range(len(SHRINE_TICKS))], 60, True,
           ticks=SHRINE_TICKS)
    sb.add("activate", _activate_frames(), 60, False, ticks=ACTIVATE_TICKS)
    sb.save()


def build() -> None:
    build_candle()
    build_candle_halo()
    build_shrine()


if __name__ == "__main__":
    build()
