"""
Vesper renderer: the 1x "pixel-artist" painter used by hero.py.

Every part is rasterised directly at 1x on pixel centres into a
material + ramp-tone index buffer (never RGB), with tone bands that are
*designed* in pixels rather than produced by a generic lighting model:

- limbs   : tapered capsules; the lateral coordinate across the capsule is
            dotted with the key light and cut at per-part thresholds
            (2-3 bands at most on 3-5 px limbs, so no banding).
- blobs   : torso, feet, capelet: ray-exit distance toward / away from the
            light inside the part's own mask (offset-polygon crescents) plus
            a highlight hot-spot cluster on the form.
- cloth   : a dense (u, s) strand sheet splatted at 1x. Fold bands are lit
            flank + dark trough measured in pixels across the cloth, they
            widen toward the hem and are anchored in cloth space (they travel
            with the cloth instead of boiling). The crimson lining shows where
            the sheet turns over (Jacobian sign) plus a designed flare at the
            lifting trailing edge.
- stamps  : hand-authored 1x templates (heads/faces, hands, jewels).
- weapons : a separate layer (sabre, smear, whip, spark) with its own
            outline, composited over (or under) the finished body.

Finishing passes, in order: orphan merge, cast shadows, cool rim on back
contours, sel-out outline (material tone 0, tone 1 on lit edges), tooth-only
internal AA at stair-steps, 8-neighbour polish that protects jewels. Colours
come from `common.RAMPS` through one deterministic, ramp-derived CLUT-sharing
table (`CLUT`), so a frame's colours never depend on any other frame.

The rig, the gait and the secondary-motion simulation live in hero_rig.py;
the animation tables live in hero.py.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

import numpy as np
from scipy import ndimage

from common import HERO_CENTER_X, HERO_FOOT_Y, HERO_FRAME_H, HERO_FRAME_W, LIGHT, RAMPS, luma

RGB = tuple[int, int, int]
Pt = tuple[float, float]

W, H = HERO_FRAME_W, HERO_FRAME_H
CX = HERO_CENTER_X
SOLE = HERO_FOOT_Y              # outline row under a planted sole
FLOOR_IN = SOLE - 1             # lowest fill row of a planted sole
FLOOR_Y = FLOOR_IN + 0.45       # float y of a planted sole (pixel centres are integers)

# ==========================================================================
# Palette: materials are keys of common.RAMPS (plus two un-outlined FX ramps)
# ==========================================================================
HERO_RAMPS: dict[str, list[RGB]] = {
    "hair": list(RAMPS["hair"]),          # H0..H5 (H4 sheen, H5 specular jewel)
    "skin": list(RAMPS["skin"]),          # K0 outline .. K4 face plane
    "eye": [RAMPS["eye"][1]],             # red dhampir glint
    # CO0..CO5 (CO5 = cool rim) + CO6: a 1-px satin specular on the chest hot spot (the
    # steel S4 white, so it shares that CLUT entry)
    "coat": list(RAMPS["coat"]) + [RAMPS["steel"][4]],
    # CX0..CX5: the blue-black ramp with one inserted step, CX4 = (58,52,96) (the hair's H3,
    # so it shares that CLUT entry), between the CX3 body and the CX5 sheen (70,74,112). Lit
    # fold flanks sit on CX4 so the sheen is left for the 1-px crests, the hem and the back rim
    # (round-2 review: hero-value-murk-r2 / hero-cape-mottle).
    "cape_out": list(RAMPS["cape_out"][:4]) + [RAMPS["hair"][3], RAMPS["cape_out"][4]],
    "cape_in": list(RAMPS["cape_in"]),    # crimson lining, lapel, ribbon, brooch
    "gold": list(RAMPS["gold"]),          # G5 specular only
    "leather": list(RAMPS["leather"]),    # gloves, belt, whip
    # trousers share the 5-tone TROUSER/BOOT ramp (docs/art_style.md: one charcoal-violet
    # family), so the near thigh can sit on tone 3 with a lit tone above it
    "trousers": list(RAMPS["boot"]),
    "boot": list(RAMPS["boot"]),          # + polish sheen
    "steel": list(RAMPS["steel"]),        # blade, whip tip
    "smear": list(RAMPS["steel"]),        # slash arc: steel colours, never outlined
    # whip-tip spark, never outlined: crimson -> gold -> white, built from tones the
    # sprite already owns so the spark costs no extra CLUT entries
    "spark": [RAMPS["cape_in"][3], RAMPS["gold"][4], RAMPS["gold"][5], RAMPS["steel"][5], RAMPS["cape_in"][4]],
}
MATS: list[str] = ["_"] + list(HERO_RAMPS)        # index 0 = empty
MID: dict[str, int] = {m: i for i, m in enumerate(MATS)}
N_TONES = np.array([0] + [len(HERO_RAMPS[m]) for m in MATS[1:]], np.int16)
# cool 1-px back-contour rim (docs/art_style.md: hair, back shoulder, cape back edge, back leg); the
# lining's trailing edge keeps CI3 where it meets the silhouette, never its dark CI1
RIM_TONE: dict[str, int] = {"hair": 3, "coat": 5, "cape_out": 5, "trousers": 3, "boot": 3, "cape_in": 3}
CAPE_DEEP = 4                   # the cape rim's inner step where the cloth is thick (never the sheen)
# sel-out on lit (upper-front) edges: the cape and the face keep one step lighter than tone 0
# (CX2 / K2: the face's lit profile reads pale, round-2 hero-value-murk-r2). Hair, coat, trousers
# and boots keep their darkest tone all round: the hero holds a dark contour (shared value plan),
# because a lit outline at Y 29-35 sits inside the band of both the mid dado (Y ~45-60) and the
# dark upper wall and lost the head and boots against them (round-2 hero-value-floor-r2).
LIT_OUTLINE: dict[str, int] = {"cape_out": 2, "skin": 2, "hair": 0, "coat": 0, "boot": 0, "trousers": 0}
LIT_DOT_DEFAULT = 0.5           # outward-normal . key-light above which an outline pixel is a lit edge
LIMB_HYST = 0.04                # limb band edges within this of a threshold keep last drawing's tone
SEP_DY = 25.0                   # interior contact lines only between parts closer than this in luma
NO_OUTLINE = ("smear", "spark", "eye")
JEWELS = ("gold", "eye", "spark", "steel", "smear")


CLEAN_MATS = ("cape_out", "coat", "trousers", "boot", "hair")
CLEAN_STEPS: tuple[str, ...] = ("thin", "islands", "majority", "islands")
SWEEP_MATS = ("cape_out", "coat", "trousers", "boot", "hair")


def _clut_table(tol: int = 10, dark: float = 20.0) -> dict[tuple[str, int], RGB]:
    """Deterministic CLUT sharing built from the ramps alone (never from
    usage, so adding an animation can never recolour another frame).

    Rule (from prototype C): a ramp tone darker than luma `dark` that lies
    within `tol` per channel of an earlier canonical dark reuses it, so only
    the true near-black outline tones of hair, coat, cape, trousers and boots
    collapse onto the cape's blue-blacks. The shadow tones (coat CO1, trouser
    and boot T1/T2) keep their own hue, so legs, coat shadow and cape stay
    separate value families (round-1 review: hero-value-murk).

    Then an explicit list of designed merges (a PS1 artist sharing entries
    between the body, cape and weapon CLUTs), each between tones of nearly
    the same value:
    - leather L0 -> lining CI0; leather L1 and gold G0 -> lining CI1 (dark
      reds: glove shadow, gold outline);
    - gold G1 (lit gold outline) -> leather L2;
    - coat CO1 -> cape CX2 (deep indigo shadow); coat CO0 (outline) -> cape CX0, so
      the contour is one unbroken blue-black where coat and cape meet it;
    - steel S1 (lit blade outline) -> coat CO3;
    - trouser/boot T1 -> cape CX2, T2 -> cape CX3, T3 -> hair H3, trouser T4
      -> hair H4 and boot B4 (the polish streak and cuff line) -> coat CO5,
      the cool gloss of riding leather: the charcoal-violet legs are realised
      on the shared night ramp and add no CLUT entries of their own;
    - steel S2 (blade spine / smear tail) -> hair H4;
    - colour-budget merges (round-1 review: clut-budget), each a rare 1-3 px
      accent folded onto a tone of nearly the same value: hair H5 (crown
      specular) -> coat CO5 (cool highlight; also keeps the hair off silver),
      lining CI0 (lining outline) -> cape CX1, lining CI4 (ribbon / brooch
      glint) -> the eye's hot red, leather L3 (glove knuckle) -> gold G2."""
    order = ("cape_out", "hair", "coat", "trousers", "boot", "cape_in", "leather", "skin", "gold",
             "steel", "smear", "eye", "spark")
    canon: list[RGB] = []
    table: dict[tuple[str, int], RGB] = {}
    for name in order:
        for t, c in enumerate(HERO_RAMPS[name]):
            hit = None
            if luma(c) < dark:
                hit = next((k for k in canon if luma(k) < dark and max(abs(a - b) for a, b in zip(c, k)) <= tol),
                           None)
            if hit is None:
                canon.append(c)
                hit = c
            table[(name, t)] = hit
    designed = {("leather", 0): ("cape_in", 0), ("leather", 1): ("cape_in", 1), ("gold", 0): ("cape_in", 1),
                ("gold", 1): ("leather", 2), ("coat", 1): ("cape_out", 2), ("coat", 0): ("cape_out", 0),
                ("steel", 1): ("coat", 3), ("smear", 1): ("coat", 3),
                ("trousers", 1): ("cape_out", 2), ("boot", 1): ("cape_out", 2),
                ("trousers", 2): ("cape_out", 3), ("boot", 2): ("cape_out", 3),
                ("trousers", 3): ("hair", 3), ("boot", 3): ("hair", 3),
                ("trousers", 4): ("hair", 4), ("boot", 4): ("coat", 5),
                ("steel", 2): ("hair", 4), ("smear", 2): ("hair", 4),
                ("hair", 5): ("coat", 5), ("cape_in", 0): ("cape_out", 1), ("leather", 0): ("cape_out", 1),
                ("cape_in", 4): ("eye", 0), ("spark", 4): ("eye", 0), ("leather", 3): ("gold", 2)}
    for src, dst in designed.items():
        table[src] = table[dst]
    return table


CLUT: dict[tuple[str, int], RGB] = _clut_table()
# (mat_index, tone) -> RGB lookup used by Canvas.rgba(); shape (n_mats, 8, 3)
_LUT = np.zeros((len(MATS), 8, 3), np.uint8)
_LUT_RAW = np.zeros((len(MATS), 8, 3), np.uint8)
for _mi, _m in enumerate(MATS[1:], start=1):
    for _t, _c in enumerate(HERO_RAMPS[_m]):
        _LUT[_mi, _t] = CLUT[(_m, _t)]
        _LUT_RAW[_mi, _t] = _c
    _LUT[_mi, len(HERO_RAMPS[_m]):] = _LUT[_mi, len(HERO_RAMPS[_m]) - 1]
# displayed luminance per (material, tone), for value-aware contact lines
LUMT = (0.299 * _LUT[..., 0] + 0.587 * _LUT[..., 1] + 0.114 * _LUT[..., 2]).astype(np.float64)
_LIT_OL = np.ones(len(MATS), np.int16)
for _m, _t in LIT_OUTLINE.items():
    _LIT_OL[MID[_m]] = _t

# Key light (common.LIGHT, upper-front of a right-facing sprite) in 3-D and
# its screen-plane direction.
L3 = np.array(LIGHT, np.float64)
L2 = L3[:2] / np.linalg.norm(L3[:2])

YY, XX = np.mgrid[0:H, 0:W].astype(np.float64)   # pixel centres at integer coords
N4: tuple[tuple[int, int], ...] = ((1, 0), (-1, 0), (0, 1), (0, -1))
N8: tuple[tuple[int, int], ...] = N4 + ((1, 1), (1, -1), (-1, 1), (-1, -1))


# ==========================================================================
# Raster helpers
# ==========================================================================
def shift(a: np.ndarray, dx: int, dy: int, fill: object = False) -> np.ndarray:
    """out[y, x] = a[y + dy, x + dx]; `fill` outside."""
    out = np.full_like(a, fill)
    ys0, ys1 = max(0, -dy), min(H, H - dy)
    xs0, xs1 = max(0, -dx), min(W, W - dx)
    if ys0 < ys1 and xs0 < xs1:
        out[ys0:ys1, xs0:xs1] = a[ys0 + dy:ys1 + dy, xs0 + dx:xs1 + dx]
    return out


def dilate4(m: np.ndarray) -> np.ndarray:
    o = m.copy()
    for dx, dy in N4:
        o |= shift(m, dx, dy)
    return o


def poly_mask(pts: Sequence[Pt]) -> np.ndarray:
    """Even-odd polygon fill sampled at pixel centres."""
    p = [(float(x), float(y)) for x, y in pts]
    inside = np.zeros((H, W), bool)
    n = len(p)
    for i in range(n):
        x0, y0 = p[i]
        x1, y1 = p[(i + 1) % n]
        if y0 == y1:
            continue
        cond = ((y0 <= YY) & (YY < y1)) | ((y1 <= YY) & (YY < y0))
        xi = x0 + (YY - y0) * (x1 - x0) / (y1 - y0)
        inside ^= cond & (XX < xi)
    return inside


def capsule(p0: Pt, p1: Pt, r0: float, r1: float | None = None
            ) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[float, float]]:
    """Tapered capsule on pixel centres: mask, t (0..1 along), lat (-1..1
    across, + on the screen-right of p0->p1 rotated), unit normal."""
    r1 = r0 if r1 is None else r1
    ax, ay = p1[0] - p0[0], p1[1] - p0[1]
    l2 = ax * ax + ay * ay
    if l2 < 1e-9:
        ax, ay, l2 = 0.0, 1e-3, 1e-6
    t = ((XX - p0[0]) * ax + (YY - p0[1]) * ay) / l2
    tc = np.clip(t, 0, 1)
    dx = XX - (p0[0] + tc * ax)
    dy = YY - (p0[1] + tc * ay)
    r = r0 + (r1 - r0) * tc
    mask = dx * dx + dy * dy <= r * r + 1e-6
    ln = math.sqrt(l2)
    nx, ny = -ay / ln, ax / ln
    lat = np.clip((dx * nx + dy * ny) / np.maximum(r, 1e-3), -1, 1)
    return mask, tc, lat, (nx, ny)


def ray_exit(mask: np.ndarray, d: Sequence[float], kmax: float = 12.0) -> np.ndarray:
    """Distance (px) from each pixel to the first outside sample walking along d."""
    offs: list[tuple[tuple[int, int], float]] = []
    seen: set[tuple[int, int]] = set()
    for k in np.arange(0.5, kmax, 0.5):
        o = (int(round(k * d[0])), int(round(k * d[1])))
        if o == (0, 0) or o in seen:
            continue
        seen.add(o)
        offs.append((o, math.hypot(*o)))
    dist = np.full(mask.shape, kmax)
    rem = mask.copy()
    for (dx, dy), ln in offs:
        hit = rem & ~shift(mask, dx, dy)
        dist[hit] = ln
        rem &= ~hit
    return dist


def pp_line(pts: Sequence[Pt]) -> list[tuple[int, int]]:
    """Pixel-perfect 1-px polyline through float points (no L-shaped doubles)."""
    out: list[tuple[int, int]] = []
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        n = int(max(abs(x1 - x0), abs(y1 - y0)) * 2) + 1
        for i in range(n + 1):
            t = i / n
            p = (int(math.floor(x0 + (x1 - x0) * t + 0.5)), int(math.floor(y0 + (y1 - y0) * t + 0.5)))
            if not out or out[-1] != p:
                out.append(p)
    res: list[tuple[int, int]] = []
    for p in out:
        if len(res) >= 2:
            a, b = res[-2], res[-1]
            if abs(p[0] - a[0]) == 1 and abs(p[1] - a[1]) == 1 and (b[0] == a[0] or b[1] == a[1]):
                res.pop()
        res.append(p)
    return res


def catmull(pts: Sequence[Pt], n: int = 8) -> list[Pt]:
    """Uniform Catmull-Rom through every point, n samples per segment."""
    ext = [pts[0]] + list(pts) + [pts[-1]]
    out: list[Pt] = []
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = (np.array(ext[j], float) for j in (i - 1, i, i + 1, i + 2))
        for k in range(n):
            t = k / n
            q = 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                       + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)
            out.append((float(q[0]), float(q[1])))
    out.append((float(ext[-2][0]), float(ext[-2][1])))
    return out


def resample(pts: np.ndarray, n: int) -> tuple[np.ndarray, float]:
    """n points evenly spaced by arc length along a polyline, and its length."""
    p = np.asarray(pts, float)
    seg = np.hypot(*np.diff(p, axis=0).T)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    tt = np.linspace(0.0, cum[-1], n)
    return np.stack([np.interp(tt, cum, p[:, 0]), np.interp(tt, cum, p[:, 1])], 1), float(cum[-1])


def dirv(deg: float) -> Pt:
    """Angle from straight down; + rotates toward facing (+x)."""
    r = math.radians(deg)
    return (math.sin(r), math.cos(r))


def sdir(deg: float) -> Pt:
    """Screen angle: 0 = +x (forward), -90 = up."""
    r = math.radians(deg)
    return (math.cos(r), math.sin(r))


def addp(p: Pt, d: Pt, k: float = 1.0) -> Pt:
    return (p[0] + d[0] * k, p[1] + d[1] * k)


def rnd(p: Pt) -> tuple[int, int]:
    return int(math.floor(p[0] + 0.5)), int(math.floor(p[1] + 0.5))


# ==========================================================================
# Tone hysteresis (anti-boil between in-betweens)
# ==========================================================================
class ToneMemory:
    """Remembers each part's tones from the previous frame of a sequence.
    Where a pixel's continuous field sits within a hair of a band threshold
    and the same part covered that pixel last frame, it keeps last frame's
    tone, so tone boundaries do not flicker by 1 px between in-betweens."""

    def __init__(self) -> None:
        self.prev: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self.cur: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    def apply(self, name: str, mask: np.ndarray, tone: np.ndarray, near: np.ndarray) -> np.ndarray:
        prev = self.prev.get(name)
        out = tone
        if prev is not None:
            pm, pt = prev
            keep = near & mask & pm
            if keep.any():
                out = np.where(keep, pt, tone)
        self.cur[name] = (mask.copy(), np.asarray(out).copy())
        return out

    def advance(self) -> None:
        self.prev, self.cur = self.cur, {}


# ==========================================================================
# Canvas: material/tone index buffer + finishing passes
# ==========================================================================
class Canvas:
    def __init__(self, mem: ToneMemory | None = None) -> None:
        self.mat = np.zeros((H, W), np.int16)
        self.tone = np.zeros((H, W), np.int16)
        self.part = np.zeros((H, W), np.int16)
        self.lock = np.zeros((H, W), bool)
        # designed 1-px lines (cloth crests / hem sheen, interior contact lines): the cloth
        # cleanup may merge them when they break into 1-2 px bits, never thin them away
        self.designed = np.zeros((H, W), bool)
        self.names: list[str] = ["_"]
        self.mem = mem
        self.anchors: dict[str, Pt] = {}

    def new_part(self, name: str) -> int:
        self.names.append(name)
        return len(self.names) - 1

    def part_mask(self, *prefixes: str) -> np.ndarray:
        ids = [i for i, n in enumerate(self.names) if any(n.startswith(p) for p in prefixes)]
        return np.isin(self.part, ids) & (self.mat > 0)

    def hyst(self, name: str, mask: np.ndarray, tone: np.ndarray, near: np.ndarray) -> np.ndarray:
        if self.mem is None:
            return tone
        return self.mem.apply(name, mask, tone, near)

    def put(self, mask: np.ndarray, mat: str | np.ndarray, tone: int | np.ndarray, name: str | int, *,
            lock: bool | np.ndarray = False, sep: bool = False, sep_mats: Sequence[str] | None = None) -> int:
        """Paint a part over what is there. `sep` draws the interior contour
        on the part *behind*, only where the new part overlaps something
        already painted AND the two touching pixels are within SEP_DY of each
        other in luminance (docs/art_style.md: interior lines only between similar
        values; elsewhere the value step already separates them). The line is
        a one-step value valley in the back part's own ramp (never above tone
        2, never tone 0), not an outline-black seam."""
        pid = name if isinstance(name, int) else self.new_part(name)
        mask = np.asarray(mask, bool)
        m_arr = np.full((H, W), MID[mat], np.int16) if isinstance(mat, str) else np.asarray(mat, np.int16)
        t_arr = np.full((H, W), tone, np.int16) if np.isscalar(tone) else np.asarray(tone, np.int16)
        if sep:
            ring = dilate4(mask) & ~mask & (self.mat > 0) & ~self.lock
            ring &= ~np.isin(self.mat, [MID[m] for m in NO_OUTLINE])
            if sep_mats is not None:
                ring &= np.isin(self.mat, [MID[m] for m in sep_mats])
            if ring.any():
                fm = np.zeros((H, W), np.int16)
                ft = np.zeros((H, W), np.int16)
                for dx, dy in N4:
                    take = ring & shift(mask, dx, dy) & (fm == 0)
                    fm[take] = shift(m_arr, dx, dy, 0)[take]
                    ft[take] = shift(t_arr, dx, dy, 0)[take]
                yb = LUMT[self.mat, np.clip(self.tone, 0, 7)]
                yf = LUMT[fm, np.clip(ft, 0, 7)]
                need = ring & (fm > 0) & (np.abs(yf - yb) < SEP_DY)
                self.tone[need] = np.clip(np.minimum(self.tone[need] - 1, 2), 1, None)
                self.designed |= need
        self.mat[mask] = m_arr[mask]
        self.tone[mask] = t_arr[mask]
        self.part[mask] = pid
        self.designed[mask] = False
        self.lock[mask] = lock if isinstance(lock, bool) else np.asarray(lock, bool)[mask]
        return pid

    def px(self, x: int, y: int, mat: str, tone: int, name: str | int, lock: bool = True) -> int:
        pid = name if isinstance(name, int) else self.new_part(name)
        if 0 <= x < W and 0 <= y < H:
            self.mat[y, x], self.tone[y, x], self.part[y, x], self.lock[y, x] = MID[mat], tone, pid, lock
        return pid

    def stamp(self, rows: Sequence[str], legend: Mapping[str, tuple[str, int, bool]], x0: int, y0: int,
              name: str, sep: bool = False, only_on: np.ndarray | None = None) -> int:
        mask = np.zeros((H, W), bool)
        mats = np.zeros((H, W), np.int16)
        tones = np.zeros((H, W), np.int16)
        lock = np.zeros((H, W), bool)
        for j, row in enumerate(rows):
            for i, ch in enumerate(row):
                if ch in " .":
                    continue
                x, y = x0 + i, y0 + j
                if 0 <= x < W and 0 <= y < H:
                    m, t, lk = legend[ch]
                    mask[y, x] = True
                    mats[y, x], tones[y, x], lock[y, x] = MID[m], t, lk
        if only_on is not None:
            mask &= only_on
        return self.put(mask, mats, tones, name, lock=lock, sep=sep)

    # ---------------------------------------------------------------- finishing passes
    def cleanup(self, passes: int = 2) -> None:
        """Merge orphan pixels (no same-tone 4-neighbour inside the same part)."""
        for _ in range(passes):
            key = self.mat.astype(np.int32) * 16 + self.tone
            occ = self.mat > 0
            nk = [shift(key, dx, dy, -1) for dx, dy in N4]
            npart = [shift(self.part, dx, dy, -1) for dx, dy in N4]
            same = sum(((k == key) & (p == self.part)).astype(int) for k, p in zip(nk, npart))
            orphan = occ & (same == 0) & ~self.lock
            if not orphan.any():
                break
            K = np.stack([np.where(p == self.part, k, -1) for k, p in zip(nk, npart)])
            cnt = np.stack([sum(((K[i] == K[j]) & (K[i] >= 0)).astype(int) for j in range(4)) for i in range(4)])
            cnt = np.where(K >= 0, cnt, -1)
            best = np.take_along_axis(K, cnt.argmax(0)[None], 0)[0]
            fix = orphan & (best >= 0)
            self.mat[fix] = best[fix] // 16
            self.tone[fix] = best[fix] % 16

    def cloth_cleanup(self, mats: Sequence[str] = CLEAN_MATS, majority: Sequence[str] = ("cape_out",),
                      skip_parts: Sequence[str] = ("head",), final: bool = False,
                      steps: Sequence[str] = CLEAN_STEPS) -> None:
        """Cluster cleanup on the cloth (docs/art_style.md: 3x3 majority per material, no
        orphan pixels, no 1-px banding lines, clusters of 2-3 px or more). Runs on tone
        indices, before the cast shadows, rim and outline, so the CLUT and the colour
        count are untouched; locked pixels (jewels, stamps) are never changed.
        1. thin lines: a pixel whose left and right (or upper and lower) neighbours of
           the same part share one other tone takes it (designed lines are kept);
        2. islands: every 4-connected same-tone island of <= 2 px takes the commonest
           tone among its 4-neighbours in the same part;
        3. a 3x3 tone-majority filter on the `majority` materials (cape exterior).
        `final`: the last speck sweep after the rim, shadows and AA, islands only,
        never touching what those passes drew (they mark `designed`)."""
        skip = [i for i, n in enumerate(self.names) if any(n.startswith(p) for p in skip_parts)]
        cand = np.isin(self.mat, [MID[m] for m in mats]) & ~self.lock & (self.part > 0) & ~np.isin(self.part, skip)
        if not cand.any():
            return
        same_key = self.part.astype(np.int32) * 64 + self.mat

        def thin() -> None:
            for (ax, ay), (bx, by) in (((1, 0), (-1, 0)), ((0, 1), (0, -1))):
                ka, kb = shift(same_key, ax, ay, -1), shift(same_key, bx, by, -1)
                ta, tb = shift(self.tone, ax, ay, -1), shift(self.tone, bx, by, -1)
                sel = cand & ~self.designed & (ka == same_key) & (kb == same_key) & (ta == tb) & (ta != self.tone)
                self.tone[sel] = ta[sel]

        def islands() -> None:
            key = same_key.astype(np.int64) * 16 + self.tone
            for k in np.unique(key[cand]):
                sel = cand & (key == k)
                lab, n = ndimage.label(sel)
                if n == 0:
                    continue
                sizes = np.bincount(lab.ravel())
                for j in np.nonzero(sizes[1:] <= 2)[0] + 1:
                    isl = lab == j
                    ring = dilate4(isl) & ~isl & (same_key == (k // 16))
                    if not ring.any():
                        continue
                    tv = self.tone[ring]
                    vals, cnt = np.unique(tv, return_counts=True)
                    own = int(k % 16)
                    # commonest neighbour tone; ties go to the tone nearest the island's own
                    order = sorted(zip(vals.tolist(), cnt.tolist()), key=lambda q: (-q[1], abs(q[0] - own), q[0]))
                    self.tone[isl] = order[0][0]

        def majority_pass() -> None:
            mm = cand & np.isin(self.mat, [MID[m] for m in majority]) & ~self.designed
            if not mm.any():
                return
            nk = [shift(same_key, dx, dy, -1) for dx, dy in N8 + ((0, 0),)]
            nt = [shift(self.tone, dx, dy, -1) for dx, dy in N8 + ((0, 0),)]
            avail = sum((k == same_key).astype(int) for k in nk)
            best_t = self.tone.copy()
            best_c = np.zeros((H, W), int)
            own_c = np.zeros((H, W), int)
            for t in range(8):
                c = sum(((k == same_key) & (q == t)).astype(int) for k, q in zip(nk, nt))
                own_c = np.where(self.tone == t, c, own_c)
                upd = c > best_c
                best_t = np.where(upd, t, best_t)
                best_c = np.where(upd, c, best_c)
            sel = mm & (best_t != self.tone) & (best_c > own_c) & (best_c * 2 > avail)
            self.tone[sel] = best_t[sel]

        if final:
            cand &= ~self.designed
            islands()
            return
        run = {"thin": thin, "islands": islands, "majority": majority_pass}
        for st in steps:
            run[st]()

    def cast_shadow(self, caster: np.ndarray, receiver: np.ndarray, depth: int = 1, steps: int = 1) -> None:
        """Hard cast shadow: receiver pixels just below/behind the caster
        (away from the key light) drop `steps` ramp tones (never below 1)."""
        d = (-L2[0], -L2[1])
        sh = np.zeros((H, W), bool)
        for k in range(1, depth + 1):
            sh |= shift(caster, -int(round(d[0] * k)), -int(round(d[1] * k)))
            sh |= shift(caster, 0, -k)
        sel = sh & receiver & ~caster & (self.mat > 0) & ~self.lock & (self.tone >= 2)
        self.tone[sel] = np.maximum(self.tone[sel] - steps, 1)
        self.designed |= sel

    def rim(self) -> None:
        """Cool 1-px rim light on the back contour (outward normal facing -x,
        the RIM direction) of hair, coat, cape, trousers and boots; isolated
        rim pixels are dropped so the rim reads as runs of 2 px or more. The
        hair rim is the skull's only (H3, at most a 4-px run at the back of the
        crown), so hair + ponytail + capelet never fuse into one lit hood;
        the cape rim is the 1-px sheen with a CX4 step inside it where the cloth
        is 6 px or thicker; the lining's trailing edge keeps CI3."""
        occ = self.mat > 0
        nx = np.zeros((H, W))
        ny = np.zeros((H, W))
        for dx, dy in N8:
            emp = ~shift(occ, dx, dy, False)
            w = 0.7 if dx and dy else 1.0
            nx += np.where(emp, dx * w, 0.0)
            ny += np.where(emp, dy * w, 0.0)
        ln = np.maximum(np.hypot(nx, ny), 1e-6)
        back = occ & (np.hypot(nx, ny) > 0.5) & ((nx * -0.97 + ny * -0.24) / ln > 0.5) & ~self.lock
        ok = np.zeros_like(back)
        for m in RIM_TONE:
            ok |= back & (self.mat == MID[m]) & (self.tone >= 1)
        hair = ok & (self.mat == MID["hair"])
        skull = hair & self.part_mask("head")
        if skull.any():
            skull &= YY <= np.nonzero(skull)[0].min() + 3
        ok = (ok & ~hair) | skull
        nb = sum(shift(ok, dx, dy, False).astype(int) for dx, dy in N8)
        run = ok & (nb >= 1)
        cape = self.mat == MID["cape_out"]
        cloth = cape | (self.mat == MID["cape_in"])
        deep = shift(run & cape, -1, 0) & cape & ~self.lock & (self.tone >= 1) & shift(cloth, 7, 0) & ~run
        if deep.any():
            # a 2-px rim only where the cloth is 8 px thick or more, and only the top 6 rows of
            # each run (where the cape turns over the shoulder), never all the way down the edge
            lab, n = ndimage.label(deep, structure=np.ones((3, 3), bool))
            top = ndimage.minimum(YY, lab, range(1, n + 1))
            deep &= YY < np.concatenate([[0.0], np.asarray(top, float)])[lab] + 6
        for m, t in RIM_TONE.items():
            self.tone[run & (self.mat == MID[m])] = t
        # the sheen stays a 1-px edge; inside it, where the cloth is thick, a CX4 step
        self.tone[deep] = np.maximum(self.tone[deep], CAPE_DEEP)
        self.designed |= run | deep

    def outline(self, drop_lit: Sequence[str] = ()) -> None:
        """Sel-out: each exterior outline pixel takes tone 0 of the front-most
        adjacent material, a lighter tone where the outward edge faces the
        light; next to `drop_lit` materials the lit-edge outline is dropped."""
        occ = self.mat > 0
        outl = np.zeros((H, W), bool)
        omat = np.zeros((H, W), np.int16)
        best_part = np.full((H, W), -1, np.int16)
        lit = np.zeros((H, W), bool)
        no_ol = np.isin(self.mat, [MID[m] for m in NO_OUTLINE])
        for dx, dy in N4:
            nm = shift(np.where(no_ol, 0, self.mat), dx, dy, 0)
            npt = shift(self.part, dx, dy, -1)
            cand = ~occ & (nm > 0)
            take = cand & (npt > best_part)
            omat[take] = nm[take]
            best_part[take] = npt[take]
            if (-dx) * L2[0] + (-dy) * L2[1] > LIT_DOT_DEFAULT:
                lit |= cand
            outl |= cand
        if drop_lit:
            outl &= ~(lit & np.isin(omat, [MID[m] for m in drop_lit]))
        self.mat[outl] = omat[outl]
        self.tone[outl] = np.where(lit[outl], _LIT_OL[omat[outl]], 0)
        self.part[outl] = 0

    def aa(self, mats: Sequence[str] = ("cape_out", "cape_in", "hair")) -> int:
        """Tooth-only internal AA: a fill pixel that is the last tooth of a
        horizontal or vertical stair run (outline on two orthogonal sides, run
        continuing along one axis) drops one ramp step. 45-degree diagonals and
        the outer contour are untouched; alpha stays 0/255. Only on the curves
        docs/art_style.md names (hair clumps, cape hem, lining): on the 3-5 px
        limbs a tooth pixel is a 1-px speck, not a smoothed curve."""
        occ = self.mat > 0
        out = occ & (self.part == 0)
        fill = occ & ~out & ~self.lock & np.isin(self.mat, [MID[m] for m in mats]) & (self.tone >= 2)
        o = {d: shift(out, *d) for d in N4}
        res = np.zeros((H, W), bool)
        for hx in (1, -1):
            for vy in (1, -1):
                corner = fill & o[(hx, 0)] & o[(0, vy)]
                run_h = shift(o[(0, vy)], -hx, 0)
                run_v = shift(o[(hx, 0)], 0, -vy)
                diag_ok = ~shift(out, hx, vy)
                res |= corner & (run_h | run_v) & ~(run_h & run_v) & diag_ok
        self.tone[res] -= 1
        self.designed |= res
        return int(res.sum())

    def edge_sweep(self, mats: Sequence[str] = SWEEP_MATS, skip_parts: Sequence[str] = ("head",)) -> int:
        """Band stubs against an edge (docs/art_style.md: clusters of 2-3 px or more): a fold
        band or lit flank that runs into another part or the outline leaves a 1-2 px
        stub once the 1-px rim of the material is set aside, which reads as speckle on
        a 3-5 px limb or between overlapping cloth panels. Inside each material's
        interior (its mask eroded by one pixel), every same-tone 4-connected piece of
        <= 2 px takes the commonest tone among its interior 8-neighbours. Outline,
        locked pixels (jewels, speculars, polish line) and the hand-drawn head stamp are
        never changed; the CLUT and the colour count are untouched. Returns the number
        of pixels changed."""
        changed = 0
        skip = [i for i, n in enumerate(self.names) if any(n.startswith(p) for p in skip_parts)]
        fill = (self.mat > 0) & (self.part > 0)
        free = fill & ~np.isin(self.part, skip)
        for m in mats:
            mm = self.mat == MID[m]
            inner = ndimage.binary_erosion(mm)
            ok = inner & fill
            small = np.zeros((H, W), bool)
            for t in np.unique(self.tone[inner]):
                sel = inner & (self.tone == t)
                lab, n = ndimage.label(sel)
                if n == 0:
                    continue
                sizes = np.bincount(lab.ravel())
                small |= np.isin(lab, np.nonzero(sizes[1:] <= 2)[0] + 1) & sel
            small &= free & ~self.lock
            for y, x in zip(*np.nonzero(small)):
                votes: dict[int, int] = {}
                for dx, dy in N8:
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < H and 0 <= xx < W and ok[yy, xx]:
                        tv = int(self.tone[yy, xx])
                        votes[tv] = votes.get(tv, 0) + 1
                if not votes:
                    continue
                own = int(self.tone[y, x])
                best = sorted(votes.items(), key=lambda q: (-q[1], abs(q[0] - own), q[0]))[0][0]
                if best != own:
                    self.tone[y, x] = best
                    changed += 1
        return changed

    def polish(self, keep: Sequence[str] = JEWELS) -> None:
        """Last pass: a pixel with no 8-neighbour of its own colour merges into
        the commonest colour among its same-material 8-neighbours. Jewels
        (gold, eye, steel glints, FX, locked stamp pixels) are kept."""
        key = self.mat.astype(np.int32) * 16 + self.tone
        key[self.mat == 0] = -1
        nk = np.stack([shift(key, dx, dy, -1) for dx, dy in N8])
        same = (nk == key[None]).sum(0)
        cand = (self.mat > 0) & (same == 0) & ~self.lock & ~np.isin(self.mat, [MID[m] for m in keep])
        if not cand.any():
            return
        same_mat = (nk >= 0) & ((nk // 16) == self.mat[None])
        votes = np.stack([((nk == nk[i:i + 1]) & same_mat).sum(0) * same_mat[i] for i in range(8)])
        best = np.take_along_axis(nk, votes.argmax(0)[None], 0)[0]
        ok = cand & (votes.max(0) > 0)
        self.tone[ok] = (best[ok] % 16).astype(np.int16)

    def rgba(self, raw: bool = False) -> np.ndarray:
        img = np.zeros((H, W, 4), np.uint8)
        occ = self.mat > 0
        t = np.clip(self.tone, 0, N_TONES[self.mat] - 1)
        img[occ, :3] = (_LUT_RAW if raw else _LUT)[self.mat[occ], t[occ]]
        img[occ, 3] = 255
        return img


# ==========================================================================
# Stamps: heads (A's face-template idea, one per expression / attitude),
# hands, jewels
# ==========================================================================
# Legend: a-f hair H0-H5, k-o skin K0-K4, r eye glint, w lip.
HEAD_LEGEND: dict[str, tuple[str, int, bool]] = {
    "a": ("hair", 0, False), "b": ("hair", 1, False), "c": ("hair", 2, False), "d": ("hair", 3, False),
    "e": ("hair", 4, True), "f": ("hair", 5, True),
    "k": ("skin", 0, True), "l": ("skin", 1, True), "m": ("skin", 2, True), "n": ("skin", 3, True),
    "o": ("skin", 4, True), "r": ("eye", 0, True), "w": ("skin", 1, True),
}


@dataclass(frozen=True)
class HeadStamp:
    rows: tuple[str, ...]
    neck: tuple[int, int]      # template pixel that sits on the neck joint
    nape: tuple[float, float]  # ponytail root, template coords
    knot: tuple[int, int]      # ribbon bow position, template coords


def _head(rows: Sequence[str], neck: tuple[int, int], nape: tuple[float, float],
          knot: tuple[int, int]) -> HeadStamp:
    width = max(len(r) for r in rows)
    return HeadStamp(tuple(r.ljust(width, ".") for r in rows), neck, nape, knot)


# 3/4 heads facing right, 9 px of fill wide (11 with the outline) and 8 rows
# crown to chin (about 7 heads on a 48 px figure: 6-7 px of skull + hair volume). Hair: swept back into two tapered clumps at the
# back, a 2-3 px H4 sheen arc with one H5 jewel, one forelock over the brow.
# Face: a broad K3/K4 plane (the brightest skin on the sprite, one of its three focal
# points), a 1-px brow shadow over the red glint, K2 only on the cheek turning toward
# the hair and a K0 jaw shadow. Variants share one skull so the head never swims.
HEADS: dict[str, HeadStamp] = {
    "n": _head([          # neutral 3/4
        "..bccdb..",
        ".bcdeedc.",
        ".cdcdfedc",
        "bdcdcdnoc",
        ".cbcdnlod",
        "..bcmnroo",
        ".bbcnnoo.",
        "..bbknoo.",
        ".....kl..",
    ], (5, 8), (1.4, 6.4), (2, 6)),
    "fwd": _head([        # chin down, intent (run, attacks)
        "...bccdb.",
        "..bcdeedc",
        ".cdcdcfec",
        "bdcdcdcoc",
        ".cbcdnlod",
        "..bcmnroo",
        ".bbcnnoo.",
        "..bbknoo.",
        ".....kl..",
    ], (5, 8), (1.4, 6.4), (2, 6)),
    "up": _head([         # looking up (jump, whip wind-up)
        "..bccdb..",
        ".bcdeedd.",
        ".cdcdfeno",
        "bdcdcnlro",
        ".cbcdnnooo",
        "..bcmnoo.",
        ".bbcknno.",
        "..bbklm..",
        ".....kl..",
    ], (5, 8), (1.4, 6.4), (2, 6)),
    "hurt": _head([       # eyes shut, mouth open
        "..bccdb..",
        ".bcdeedc.",
        ".cdcdfedc",
        "bdcdcdnoc",
        ".cbcdnnod",
        "..bcmllo.",
        ".bbcnnnwo",
        "..bbknon.",
        ".....kl..",
    ], (5, 8), (1.4, 6.4), (2, 6)),
    "death": _head([      # bowed, eyes closed
        ".........",
        "...bccdb.",
        ".bcddeedc",
        ".cdcdcfec",
        "bdcdcdcnc",
        ".cbcdnlno",
        "..bcnllo.",
        ".bbcmnno.",
        "..bbklm..",
    ], (5, 8), (1.4, 6.8), (2, 6)),
}

# back of the head (somersault frames where the face is turned away): the neutral
# skull with the face plane filled by hair: blue-black mass, one H3 strand line
BACK_HEAD: HeadStamp = _head([
    "..bccdb..",
    ".bcdeedc.",
    ".cdcdfedc",
    "bdcdcdcdc",
    ".cbcdcdcb",
    "..bcdcdcb",
    ".bbcccccb",
    "..bbbcbb.",
    ".....bb..",
], (5, 8), (1.4, 6.4), (2, 6))

HAND_LEGEND: dict[str, tuple[str, int, bool]] = {
    "g": ("leather", 1, False), "h": ("leather", 2, False), "i": ("leather", 3, True),
    "j": ("leather", 4, True),
}
# hand stamps, anchor = template pixel placed on the hand point
HANDS: dict[str, tuple[tuple[str, ...], tuple[int, int]]] = {
    "relax": (("hi", "hh", "gh"), (0, 1)),
    "fist": (("ii", "hh", "gh"), (0, 1)),          # knuckles lit, curled fingers
    "grip": (("hii", "ghh", ".g."), (1, 1)),       # thumb over the grip
    "open": (("hii", "ghh", ".gh"), (1, 0)),
    "point": (("hiii", "ghh."), (1, 0)),           # throw release: fingers forward
}


# ==========================================================================
# Painters
# ==========================================================================
def paint_limb(cv: Canvas, name: str, p0: Pt, p1: Pt, r0: float, r1: float, mat: str, base: int,
               th: tuple[float, float | None] = (-0.05, 0.62),
               extra: Callable[[np.ndarray, np.ndarray, np.ndarray, np.ndarray], np.ndarray] | None = None,
               sep: bool = True, darker: int = 0) -> tuple[int, np.ndarray, np.ndarray]:
    """Capsule limb, 2-3 designed bands from the lateral cylinder normal."""
    mask, t, lat, n = capsule(p0, p1, r0, r1)
    z = np.sqrt(np.clip(1 - lat * lat, 0, 1))
    I = n[0] * lat * L3[0] + n[1] * lat * L3[1] + z * L3[2]
    tone = np.full((H, W), base - darker)
    tone[I < th[0]] = base - 1 - darker
    near = np.abs(I - th[0]) < LIMB_HYST
    if th[1] is not None:
        tone[I > th[1]] = base + 1 - darker
        near |= np.abs(I - th[1]) < LIMB_HYST
    if extra is not None:
        tone = extra(tone, t, lat, I)
    tone = np.clip(tone, 1, len(HERO_RAMPS[mat]) - 1)
    tone = cv.hyst(name, mask, tone, near)
    return cv.put(mask, mat, tone, name, sep=sep), mask, t


def paint_blob(cv: Canvas, name: str, mask: np.ndarray, mat: str, base: int, sh: float = 2.0, hi: float = 1.5,
               hot: Pt | None = None, hot_r: float = 3.0, deep: float | None = None, sep: bool = True,
               lit_extra: np.ndarray | None = None) -> int:
    """Offset-polygon crescents: shadow on the side away from the light,
    a lit crescent toward it and a hot-spot cluster on the form."""
    dl = ray_exit(mask, L2)
    ds = ray_exit(mask, -L2)
    tone = np.full((H, W), base)
    tone[ds <= sh] = base - 1
    if deep is not None:
        tone[ds <= deep] = base - 2
    tone[(dl <= hi) & (ds > sh)] = base + 1
    if lit_extra is not None:
        tone[lit_extra & mask & (ds > sh)] = base + 1
    if hot is not None:
        d = np.hypot(XX - hot[0], YY - hot[1])
        tone[(dl <= hi + 1.0) & (d <= hot_r) & (ds > sh)] = base + 2
    tone = np.clip(tone, 1, len(HERO_RAMPS[mat]) - 1)
    return cv.put(mask, mat, tone, name, sep=sep)


@dataclass
class ClothArt:
    """Art-direction knobs of a cloth sheet. Its geometry comes from the
    simulated chains; these only decide how it is painted."""
    flare: float = 0.10       # lining revealed along the lifting trailing edge (fraction of u at the hem)
    flare_pulse: float = 0.0  # 0..1: how much the flare follows the travelling wave (lifting hem)
    hem_in: float = 0.0       # fraction of strand length near the hem that curls over (lining)
    face: str = "auto"        # "auto" = geometric facing, "out" = exterior only (edges may still flash)
    fold_phase: float = 0.0   # slides the fold ridges across the cloth (cloth-space, so they travel)
    wave: float = 0.0         # travelling flutter amplitude at the hem (px)
    wave_k: float = 1.2       # waves along a strand
    wave_phase: float = 0.0   # radians, advanced by the simulation clock
    turn: float = 0.0         # with face="out": geometric lining still shows above this s (the turn-over)
    flare_from: float = 0.45  # the trailing-edge flare starts this far down the strands


def cloth_grid(roots: np.ndarray, strands: np.ndarray) -> tuple[np.ndarray, ...]:
    """(u, s) sheet from root points (NU, 2) and strand offsets (NU, NS, 2)."""
    NU, NS = strands.shape[:2]
    us = np.linspace(0, 1, NU)
    ss = np.linspace(0, 1, NS)
    U, S = np.meshgrid(us, ss, indexing="ij")
    X = roots[:, None, 0] + strands[..., 0]
    Y = roots[:, None, 1] + strands[..., 1]
    return U, S, X, Y


def paint_cloth(cv: Canvas, name: str, U: np.ndarray, S: np.ndarray, X: np.ndarray, Y: np.ndarray,
                art: ClothArt, *, folds: Sequence[tuple[float, ...]], out_base: int = 2,
                top_dark: float = 0.10, hem: bool = True, ext: str = "cape_out", lin: str = "cape_in",
                sep: bool = True, ridge: tuple[float, float] = (2.0, 1.0), trough: tuple[float, float] = (1.5, 1.0),
                edge_rim: bool = True, lining: bool = True, floor_y: float | None = None,
                clip: np.ndarray | None = None, base_u: tuple[float, int] | None = None,
                core: bool = False, width_ref: float | None = None,
                crest_k: tuple[float, float] = (0.72, 1.01), hem_step: int = 2) -> int:
    """Splat a cloth sheet with designed fold bands (lit flank + dark
    trough, widening to the hem), geometric lining and a 1-px hem sheen.
    `base_u` = (u0, tone): strands past u0 (the outer, camera-facing part of
    the sheet) sit on that base tone instead of `out_base`. `core`: the trough
    of a fold on a base-3 field gets a second, darker core where the trough is
    widest (toward the hem). `width_ref`: the fold bands scale with the sheet's
    local width across u (a sheet narrower than `width_ref` px gets narrower
    bands), so a streaming cape keeps a base field between its folds instead of
    turning into wall-to-wall flanks and troughs. `crest_k`: the depth range
    (fraction of the fold's length) that carries the 1-px crest. `hem_step`: the
    1-px hem line sits this many ramp steps above the base. A fold is
    (u, s0) or (u, s0, min_width): with a min width it only forms where the
    sheet is at least that wide across u (2 broad folds on a streaming cape,
    3 on a wide drape, never a corduroy of narrow ones)."""
    if floor_y is not None:          # pooling: cloth reaching the floor slides back along it
        over = np.maximum(Y - floor_y, 0)
        X = X - over * 1.0
        Y = np.minimum(Y, floor_y)
    gu_x, gs_x = np.gradient(X)
    gu_y, gs_y = np.gradient(Y)
    det = gu_x * gs_y - gu_y * gs_x
    dA = np.hypot(np.diff(X, axis=0), np.diff(Y, axis=0))
    A = np.concatenate([np.zeros((1, X.shape[1])), np.cumsum(dA, axis=0)], axis=0)
    Atot = np.broadcast_to(A[-1:, :], X.shape)
    dS = np.hypot(np.diff(X, axis=1), np.diff(Y, axis=1))
    Ls = np.concatenate([np.zeros((X.shape[0], 1)), np.cumsum(dS, axis=1)], axis=1)
    Lr = np.broadcast_to(Ls[:, -1:], X.shape)
    order = np.argsort(S.ravel(), kind="stable")
    xi = np.floor(X.ravel()[order] + 0.5).astype(int)
    yi = np.floor(Y.ravel()[order] + 0.5).astype(int)
    u, s, dt = U.ravel()[order], S.ravel()[order], det.ravel()[order]
    a_px, a_tot, lr, ls = A.ravel()[order], Atot.ravel()[order], Lr.ravel()[order], Ls.ravel()[order]
    ok = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
    xi, yi, u, s, dt, a_px, a_tot, lr, ls = (v[ok] for v in (xi, yi, u, s, dt, a_px, a_tot, lr, ls))
    # which face shows: geometric turn-over, or the designed lifting-edge flare
    if lining:
        geo = (dt > 0) if art.face == "auto" else ((dt > 0) & (s < art.turn))
        pulse = 1.0 - art.flare_pulse * (0.5 + 0.5 * np.sin(2 * np.pi * art.wave_k * s - art.wave_phase + 0.8 * u))
        reach = np.clip((s - art.flare_from) / (1.0 - art.flare_from), 0.0, 1.0) ** 1.3   # lower trailing edge
        flare_edge = u > 1.0 - art.flare * reach * pulse + 1e-9
        curl = s > 1.0 - art.hem_in * (0.4 + 0.6 * u)
        is_lin = geo | flare_edge | curl
    else:
        is_lin = np.zeros_like(dt, bool)
    # designed folds: each = lit flank (toward the light) + dark trough, both
    # widening toward the hem, emerging at depth s0, anchored in cloth space
    base = np.full(u.shape, out_base)
    if base_u is not None:
        base = np.where(u > base_u[0], base_u[1], base)
    tone = base.copy()
    ltone = np.full(u.shape, 2)
    near = np.zeros(u.shape, bool)
    des = np.zeros(u.shape, bool)
    wscale = np.ones(u.shape) if width_ref is None else np.clip(a_tot / width_ref, 0.55, 1.0)
    for fold in folds:
        uc, s0 = fold[0], fold[1]
        wmin = fold[2] if len(fold) > 2 else 0.0
        uc = uc + 0.035 * math.sin(art.fold_phase)
        d = a_px - uc * a_tot
        k = np.clip((s - s0) / max(1 - s0, 1e-3), 0, 1) * (a_tot >= wmin)
        rw = (ridge[0] + ridge[1] * k) * (k > 0) * wscale
        tw = (trough[0] + trough[1] * k) * (k > 0) * wscale
        litb = (d >= -rw) & (d < 0)
        dark = (d >= 0) & (d < tw)
        tone = np.where(litb, base + 1, np.where(dark, base - 1, tone))
        if core:
            tone = np.where(dark & (tw >= 2.6) & (d >= 0.3 * tw) & (d < 0.7 * tw) & (base >= 3), base - 2, tone)
        ltone = np.where(litb, 3, np.where(dark, 1, ltone))
        crest = (d >= -1.0) & (d < 0) & (k > crest_k[0]) & (k < crest_k[1])
        tone = np.where(crest, base + 2, tone)
        ltone = np.where(crest, 4, ltone)
        des |= crest
        near |= (k > 0) & ((np.abs(d + rw) < 0.2) | (np.abs(d) < 0.2) | (np.abs(d - tw) < 0.2))
    tone = np.where(s < top_dark, base - 1, tone)
    if hem:
        at_hem = ls >= lr - 0.8
        tone = np.where(at_hem, base + hem_step, tone)
        ltone = np.where(at_hem, 3, ltone)
        des |= at_hem
    tone = np.minimum(tone, len(HERO_RAMPS[ext]) - 1)
    mat_i = np.where(is_lin, MID[lin], MID[ext]).astype(np.int16)
    ton_i = np.where(is_lin, ltone, tone).astype(np.int16)
    M = np.zeros((H, W), np.int16)
    T = np.zeros((H, W), np.int16)
    NR = np.zeros((H, W), bool)
    D = np.zeros((H, W), bool)
    M[yi, xi] = mat_i            # later (larger s) wins
    T[yi, xi] = ton_i
    NR[yi, xi] = near
    D[yi, xi] = des
    mask = M > 0
    # silhouette cleanup: drop 1-px spurs, fill notches
    for _ in range(2):
        nb = sum(shift(mask, dx, dy).astype(int) for dx, dy in N4)
        mask &= ~(mask & (nb <= 1))
        notch = ~mask & (nb >= 3)
        for dx, dy in N4:
            src = notch & shift(mask, dx, dy)
            M[src] = shift(M, dx, dy)[src]
            T[src] = shift(T, dx, dy)[src]
            mask |= src
            notch &= ~src
    if clip is not None:
        mask &= clip
    M[~mask] = 0
    T = cv.hyst(name, mask, T, NR)
    pid = cv.put(mask, M, T, name, sep=sep)
    cv.designed |= D & mask
    return pid


def paint_hair_clump(curve: Sequence[Pt], r_root: float, r_tip: float, base: int, sheen: bool,
                     lit: float = 0.62, tip_lit: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Tapered hair clump along a polyline: lateral bands from the clump
    angle and the key light, 1-px point at the tip, a short sheen on the lit
    flank near the root. `tip_lit`: the lit band runs on to the tip (where the
    clump is 1-2 px wide its lit half takes the band), so the strand end reads."""
    n = len(curve)
    acc = np.zeros((H, W), bool)
    tone = np.zeros((H, W), np.int16)
    for i in range(n - 1):
        t0, t1 = i / (n - 1), (i + 1) / (n - 1)
        r0 = r_root + (r_tip - r_root) * t0 ** 0.8
        r1 = r_root + (r_tip - r_root) * t1 ** 0.8
        m, _, lat, nn = capsule(curve[i], curve[i + 1], max(r0, 0.45), max(r1, 0.45))
        z = np.sqrt(np.clip(1 - lat * lat, 0, 1))
        I = nn[0] * lat * L3[0] + nn[1] * lat * L3[1] + z * L3[2]
        tt = np.where(I > lit, base + 1, np.where(I < 0.15, base - 1, base))
        if tip_lit and t0 >= 0.5:
            lit_side = (nn[0] * L3[0] + nn[1] * L3[1]) * lat > 0.0
            tt = np.where(lit_side | (max(r0, r1) < 0.9), base + 1, tt)
        if sheen and 0.1 < t0 < 0.25:
            tt = np.where(I > 0.72, base + 2, tt)
        new = m & ~acc
        tone[new] = tt[new]
        acc |= m
    return acc, tone


# ==========================================================================
# Weapon layer (separate canvas, own outline, composited onto the body)
# ==========================================================================
@dataclass
class WeaponDraw:
    """What the weapon layer draws this frame; produced by the rig."""
    kind: str = "none"               # "sabre" | "whip" | "none"
    hand: Pt = (0.0, 0.0)            # grip point
    angle: float = 0.0               # sabre screen angle (0 = forward, -90 = up)
    length: float = 23.0
    curve: float = 1.6
    behind: bool = False             # under the body (anticipation: blade cocked behind)
    whip: list[Pt] = field(default_factory=list)   # lash control points after the hand
    spark: int = 0                   # 0 none, 1 burst, 2 fading
    smear: tuple[Pt, Pt, Pt, float] | None = None   # (pivot, tip_from, tip_to, strength)


def sabre_points(hand: Pt, deg: float, length: float, curve: float) -> tuple[Pt, list[Pt], Pt, Pt]:
    d = sdir(deg)
    nrm = (d[1], -d[0])              # spine side (counter-clockwise of the blade direction)
    guard = addp(hand, d, 2.0)
    pts = []
    for i in range(int(length * 2) + 1):
        t = i / (length * 2)
        b = addp(guard, d, length * t)
        pts.append(addp(b, nrm, curve * t * t))
    return guard, pts, d, nrm


def sabre_tip(hand: Pt, deg: float, length: float = 23.0, curve: float = 1.6) -> Pt:
    return sabre_points(hand, deg, length, curve)[1][-1]


def paint_sabre(cv: Canvas, wd: WeaponDraw) -> None:
    """Slender curved sabre: 1-px edge with an S5 glint, 1-px spine on the
    base 70 %, gold cup-hilt with a G5 glint and a pommel."""
    guard, pts, d, nrm = sabre_points(wd.hand, wd.angle, wd.length, wd.curve)
    edge = pp_line(pts)
    pid = cv.new_part("blade")
    n = len(edge)
    glint = 0.18 + 0.5 * (0.5 + 0.5 * math.sin(math.radians(wd.angle * 1.7)))   # glint slides with the angle
    spine: list[tuple[int, int, int]] = []
    for i, (x, y) in enumerate(edge):
        t = i / max(n - 1, 1)
        tone = 4 if t > 0.1 else 3
        if abs(t - glint) < 0.05:
            tone = 5
        cv.px(x, y, "steel", tone, pid, lock=False)
        if t < 0.7:
            sx, sy = int(round(x + nrm[0])), int(round(y + nrm[1]))
            spine.append((sx, sy, 2 if t < 0.45 else 3))
    for sx, sy, t in spine:
        if 0 <= sx < W and 0 <= sy < H and cv.part[sy, sx] != pid:
            cv.px(sx, sy, "steel", t, pid, lock=False)
    gx, gy = rnd(guard)
    hp = cv.new_part("hilt")
    side = (int(round(nrm[0])), int(round(nrm[1])))
    for (dx, dy, t) in ((0, 0, 3), (side[0], side[1], 4), (-side[0], -side[1], 2)):
        cv.px(gx + dx, gy + dy, "gold", t, hp)
    cv.px(gx + side[0], gy + side[1], "gold", 5 if d[0] > -0.3 else 4, hp)
    # knuckle bow: from the guard back over the hand
    kb = addp(addp(wd.hand, nrm, 1.6), d, 0.4)
    kx, ky = rnd(kb)
    cv.px(kx, ky, "gold", 2, hp)
    pm = addp(wd.hand, d, -1.8)
    cv.px(*rnd(pm), "gold", 3, hp)


# smear tiers by strength: (min strength, t_max px, rim tone, body tone, inner tone, max sweep deg,
# lead gap deg, crescent profile?)
SMEAR_TIERS: tuple[tuple[float, float, int, int, int, float, float, bool], ...] = (
    (0.9, 6.5, 5, 4, 3, 100.0, 0.0, True),     # strike: broad bright comet, its head on the blade
    (0.5, 3.5, 4, 3, 2, 80.0, 3.0, True),      # follow-through: a narrower comet stopping short of the tip
    (0.0, 11.0, 3, 2, 2, 50.0, 0.5, False),    # hold: a thin motion band on the outer blade
)
SMEAR_LEAD_EXP = 2.2       # comet profile: thickness ~ 0.2 + 0.8 * g ** exp (g: 0 tail .. 1 blade)
SMEAR_CAP = 0.12           # the last 12 % of the sweep rounds the head off onto the blade


def paint_smear(cv: Canvas, wd: WeaponDraw) -> None:
    """Slash smear = the band swept by the outer blade along the tip's path
    (tail -> this frame's tip, around the shoulder). Outer edge = the tip
    path; thickness follows a comet profile (SotN-era smears): 1 px at the
    tail, growing toward the blade, widest where the blade is now, the head
    rounded off over the last SMEAR_CAP of the sweep and still >= 3 px where it
    meets the outer blade, so the arc and the strike read as one shape instead
    of a banana floating above it. Strike: S5 rim, S4 body, S3 inner;
    follow-through one step dimmer and narrower; hold a thin S3/S2 tail."""
    if wd.smear is None:
        return
    piv, tip0, tip1, strength = wd.smear
    tier = next(t for t in SMEAR_TIERS if strength >= t[0])
    _, t_max, rim_t, body_t, inner_t, sweep, gap, crescent = tier
    a0 = math.atan2(tip0[1] - piv[1], tip0[0] - piv[0])
    a1 = math.atan2(tip1[1] - piv[1], tip1[0] - piv[0])
    da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
    if abs(da) < 1e-3:
        return
    max_sweep = math.radians(sweep)
    if abs(da) > max_sweep:
        a0 = a1 - math.copysign(max_sweep, da)
        da = a1 - a0
    r0 = math.hypot(tip0[0] - piv[0], tip0[1] - piv[1])
    r1 = math.hypot(tip1[0] - piv[0], tip1[1] - piv[1])
    ang = np.arctan2(YY - piv[1], XX - piv[0])
    rad = np.hypot(XX - piv[0], YY - piv[1])
    f = ((ang - a0 + math.pi) % (2 * math.pi) - math.pi) / da     # 0 at the tail .. 1 at the blade
    lead = 1.0 - (math.radians(gap) + 1.0 / max(r1, 1.0)) / abs(da)
    g = np.clip(f / max(lead, 1e-3), 0.0, 1.0)
    r_path = r0 + (r1 - r0) * np.clip(f, 0, 1) - 0.5
    if crescent:
        g0 = 1.0 - SMEAR_CAP
        body = t_max * (0.2 + 0.8 * np.minimum(g, g0) ** SMEAR_LEAD_EXP)
        cap = np.sqrt(np.clip(1.0 - ((g - g0) / SMEAR_CAP) ** 2, 0.0, 1.0))
        thick = np.where(g > g0, body * (0.55 + 0.45 * cap), body)
        thick = np.maximum(thick, np.where(g > 0.02, 1.0, 0.0))
    else:                                 # a tail: thickest where it meets the tip, fading back
        thick = t_max * np.clip(g, 0.0, 1.0) ** 0.7
    band = (f >= 0) & (f <= lead) & (rad <= r_path + 0.5) & (rad >= r_path + 0.5 - thick) & (thick > 0.6)
    depth = (r_path + 0.5 - rad) / np.maximum(thick, 1e-3)          # 0 at the tip path .. 1 at the inner edge
    edge = rad > r_path - 0.6
    tone = np.where(depth > 0.6, inner_t, body_t)
    tone = np.where(edge & (g > 0.25), rim_t, tone)
    tone = np.where(g < 0.18, np.maximum(tone - 1, 2), tone)       # the tail fades out
    cv.put(band, "smear", tone.astype(np.int16), "smear", sep=False)


def paint_whip(cv: Canvas, wd: WeaponDraw) -> None:
    """Crimson Lash: braided leather with a 2-px core for the first 60 % (lit
    row L4/L3 braided in 2-px steps, shadow row L2 on the side away from the
    light), then 1 px of L3 with L4 on every other pixel; a crimson C4 glint
    every 4 px; a 2x2 silver tip; at the crack a 5x5 spark cross (S5 heart,
    G4 arms, C4 corners), then a fading 3x3 (G4 heart, C3 corners)."""
    if not wd.whip:
        return
    curve = catmull([wd.hand] + list(wd.whip), 10)
    line = pp_line(curve)
    pid = cv.new_part("whip")
    n = len(line)
    for i, (x, y) in enumerate(line):
        t = i / max(n - 1, 1)
        if i >= n - 2:
            tip = i == n - 1
            cv.px(x, y, "steel", 5 if tip else 4, pid, lock=True)
            cv.px(x, y + 1, "steel", 4 if tip else 3, pid, lock=True)
            continue
        if i % 4 == 2:
            m, tone = "cape_in", 4
        elif t < 0.6:
            m, tone = "leather", 4 if (i // 2) % 2 == 0 else 3
        else:
            m, tone = "leather", 4 if i % 2 == 0 else 3
        cv.px(x, y, m, tone, pid, lock=(m != "leather"))
        if t < 0.6:
            # second core row on the shadow side of the lash (away from the key light)
            a, b = line[max(i - 1, 0)], line[min(i + 1, n - 1)]
            dx, dy = b[0] - a[0], b[1] - a[1]
            nx, ny = -dy, dx
            if nx * L2[0] + ny * L2[1] > 0:
                nx, ny = -nx, -ny
            ln = math.hypot(nx, ny) or 1.0
            sx, sy = x + int(round(nx / ln)), y + int(round(ny / ln))
            if 0 <= sx < W and 0 <= sy < H and cv.part[sy, sx] != pid:
                cv.px(sx, sy, "leather", 2, pid, lock=False)
    if wd.spark:
        ex, ey = line[-1]
        sp = cv.new_part("spark")
        if wd.spark == 1:
            pts = [(0, 0, 3)] + [(dx, dy, 1) for dx, dy in ((1, 0), (2, 0), (-1, 0), (-2, 0), (0, 1), (0, 2),
                                                           (0, -1), (0, -2))] \
                + [(dx, dy, 4) for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1))]
        else:
            pts = [(0, 0, 1)] + [(dx, dy, 0) for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1))]
        for (dx, dy, t) in pts:
            if 0 <= ex + dx < W and 0 <= ey + dy < H:
                cv.px(ex + dx, ey + dy, "spark", t, sp)


def render_weapon(wd: WeaponDraw) -> Canvas | None:
    """The weapon as its own layer: blade/whip + smear, outlined on its own."""
    if wd.kind == "none":
        return None
    cv = Canvas()
    if wd.kind == "sabre":
        paint_smear(cv, wd)
        paint_sabre(cv, wd)
    elif wd.kind == "whip":
        paint_whip(cv, wd)
    # the lash keeps only its underside outline, so its lit upper edge reads over any wall
    cv.outline(drop_lit=("leather",) if wd.kind == "whip" else ())
    return cv


def composite_weapon(body: Canvas, weapon: Canvas | None, wd: WeaponDraw) -> np.ndarray:
    """Weapon layer over (or, `behind`, under) the finished body. The near
    hand always stays in front of the grip; weapon outline pixels only land
    on empty space; the smear never covers the body. Returns the mask of the
    pixels the weapon layer wrote (hit-zone checks, manifest)."""
    if weapon is None:
        return np.zeros((H, W), bool)
    occ_b = body.mat > 0
    hand = body.part_mask("handN")
    wmat = weapon.mat
    w_occ = wmat > 0
    w_out = w_occ & (weapon.part == 0)
    w_smear = np.isin(wmat, [MID["smear"]])
    if wd.behind:
        sel = w_occ & ~occ_b
    else:
        sel = (w_occ & ~w_out & ~w_smear & ~hand) | ((w_out | w_smear) & ~occ_b)
    pid = body.new_part("weapon")
    body.mat[sel] = wmat[sel]
    body.tone[sel] = weapon.tone[sel]
    body.part[sel] = pid
    body.lock[sel] = True
    return sel
