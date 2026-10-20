"""
Combat and ambience effects (SotN-style PS1 semi-transparency look).

Every effect is rendered as a float intensity field (rays, rings, a
noise-carved fire column, sphere-shaded smoke and dust puffs) and banded into a shared ramp with
crisp, posterized steps: no anti-aliasing against transparency, alpha only
0/255. The scenes that play them decide the blend:

- ADD (CanvasItemMaterial blend_mode ADD) for sparks, glows and the hot
  core of big fire. Big fire (death flame, fire pops, candle break) also
  has an opaque body row in the shared FIRE ramp, drawn on a plain child
  sprite under the ADD core, so it reads red-orange on any wall (see
  FIRE_CORE).
- MIX at reduced alpha (the PS1 "average" mode) for smoke, dust and mist.

Outputs (all sheets via SheetBuilder, animation timing in 60 Hz ticks):

- hit_spark        32x32 centred. default (impact star), slash, burst.
- death_flame      40x88, base at the bottom row. default (the fire
                   column's additive hot core, ADD root) + default_body (the
                   column itself, opaque child) + smoke (puffs, MIX child),
                   all the same ticks; the fire uses the bottom 64 rows, the
                   top 24 rows are headroom the smoke rises into.
- fire_pop         40x48, origin (20, 32) = spawn point. default (small
                   explosion: white star -> round fireball that rises and
                   cools, 16 ticks; ADD core) + default_body (opaque) +
                   smoke (MIX); large (+ large_body, smoke_large), the next
                   size up (24 ticks).
- candle_break     48x48 centred. default (white pop -> fire ball over the
                   candlestick; ADD core) + default_body (opaque) + shards
                   (wax and gilt fragments), all the same ticks.
- dust_puff        32x16, base at the bottom row (run start / skid puff,
                   kicked toward -x; flip with the hero).
- land_dust        48x12, base at the bottom row (two puffs spreading).
- double_jump_ring 32x16 centred (additive soul-light ring under the feet).
- pickup_sparkle   9x9 centred (additive 1 px star glint).
- death_mist       48x96, feet at the bottom row. default (crimson mist,
                   MIX) + embers (ADD child layer, same ticks).

Everything is deterministic: each effect owns a seeded numpy Generator.
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from PIL import Image

from common import RAMPS, RGB, SheetBuilder, indices_to_image, majority, remove_orphans

# ---------------------------------------------------------------------------
# Local ramps (dark -> light). Fire, smoke and soul come from the shared
# registry; the rest are derived from it so the screen stays cohesive.
# ---------------------------------------------------------------------------
FIRE: list[RGB] = list(RAMPS["fire"])            # ember .. white core (6)
SMOKE: list[RGB] = [(34, 26, 40)] + list(RAMPS["smoke"])  # 3 tones, darkest added below S0
SOUL: list[RGB] = list(RAMPS["soul"])            # cool additive light (5)
WAX: list[RGB] = list(RAMPS["wax"])
GOLD: list[RGB] = list(RAMPS["gold"])
# Castle dust: pale violet-grey billows, lit from above (drawn at ~55 % MIX,
# the PS1 average blend). Three light tones only: a dark underside tone made
# the puffs read as stones on the carpet.
DUST: list[RGB] = [(150, 146, 172), (196, 194, 214), (236, 236, 244)]
# Crimson mist (player death): CRIMSON C2..C5 + velvet sheen as the hot tip.
MIST: list[RGB] = list(RAMPS["crimson"][2:]) + [RAMPS["velvet"][-1]]
# Crimson embers for the additive mist layer: crimson -> fire.
EMBER: list[RGB] = [RAMPS["crimson"][3], RAMPS["crimson"][5], FIRE[2], FIRE[3], FIRE[4]]

# Fire banding: field value -> FIRE tone (first cut = visible edge).
FIRE_CUTS: tuple[float, ...] = (0.10, 0.22, 0.38, 0.58, 0.82, 1.10)

# Big fire (death flame, fire pops, candle break) is drawn as TWO layers, the
# way SotN's opaque flame sprites carry an additive hot centre:
# - body: the whole silhouette, opaque (a plain MIX child sprite), in the
#   shared FIRE ramp. It decides the colour on every wall: red edges, orange
#   body, small yellow-white core, whatever the background value or hue
#   (pure ADD fire turned peach and cream on the mid-value run band).
# - core: ADD (the effect's root sprite), only over the two hottest tones. It
#   lifts F4 (255,236,150) to (255,255,186) and burns F5 to full white over
#   the body, and it alone carries the 2-tick ignition star (body empty).
FIRE_CORE_FROM = 4
FIRE_CORE: list[RGB] = [(150, 100, 36), (210, 180, 120)]          # added over F4, F5
# The ignition star is pure light (ADD only): the shared ramp, white core.
FIRE_ADD: list[RGB] = list(FIRE)
# Banding for the two-layer fire: most of the column is F1-F2, white is a
# small core.
FIRE_CUTS_ADD: tuple[float, ...] = (0.10, 0.26, 0.46, 0.70, 0.95, 1.20)
# Share caps (of the opaque pixels) for the hot tones once ignition is over
# (tone -> max share): F4+F5 (the cream/white core) stay at most 16 %, and
# F0-F2 stay the majority so the flame reads orange-red.
FIRE_CAPS: dict[int, float] = {5: 0.05, 4: 0.11, 3: 0.20}

# Death/explosion smoke: discrete round puffs (cf. SotN's explosion puffs),
# drawn at 60 % MIX, the PS1 average blend. Each puff is a sphere lit from
# the upper front: a small light cap, mid and shade bands and a 1 px darker
# lower-back edge, so overlapping puffs stay separate billows. A puff
# younger than SMOKE_WARM_AGE ticks has a 1 px warm crescent underneath,
# lit by the fire.
SMOKE_FX: list[RGB] = [(78, 66, 88), (118, 104, 122), (160, 148, 160), (200, 190, 196)]
SMOKE_WARM: RGB = (196, 120, 92)
SMOKE_WARM_AGE = 6
# puff sphere shading: light from the upper left front; N.L cut-offs for the
# light cap (<= ~25 % of a puff) and the mid band (~40 %); the rest is shade
PUFF_LIGHT: tuple[float, float, float] = (-0.42, -0.62, 0.66)
PUFF_CUTS: tuple[float, float] = (0.86, 0.44)
# outward direction whose rim pixels take the dark edge tone (lower back)
PUFF_BACK: tuple[float, float] = (0.45, 0.89)
# one emitter: 5 puffs leave one point around one seeded heading (within
# +/-50 deg of straight up) at falling speeds, slowing x0.88 per tick, with
# a little lift; the slow ones stay near the fire, the fast ones lead. At
# these speeds puffs sent along one line pile into a single loaf, so each
# puff fans off the heading by PUFF_FAN deg: the five open into a cluster
# of separate billows. The leaders are a little smaller (PUFF_SIZE).
PUFF_SPEEDS: tuple[float, ...] = (1.6, 1.3, 1.0, 0.7, 0.4)
PUFF_FAN: tuple[float, ...] = (-34.0, 26.0, -12.0, 40.0, 6.0)
PUFF_SIZE: tuple[float, ...] = (0.72, 0.8, 0.88, 0.96, 1.0)
PUFF_DECEL = 0.88
PUFF_LIFT = 0.25
# the last 3 frames: each puff's radius erodes 1 px per frame and this share
# of its pixels drops out (seeded hash), so the smoke fades, not pops off
PUFF_FADE_DROP: tuple[float, ...] = (0.30, 0.60, 0.85)


# ---------------------------------------------------------------------------
# Field primitives (pixel-centre sampling, so 1 px lines stay 1 px)
# ---------------------------------------------------------------------------
def _u(g: np.random.Generator, rng: tuple[float, float], n: int) -> np.ndarray:
    """uniform() that accepts (high, low) pairs (mirrored effects)."""
    return g.uniform(min(rng), max(rng), n)


def _grid(w: int, h: int) -> tuple[np.ndarray, np.ndarray]:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    return xx + 0.5, yy + 0.5


def _ray(X: np.ndarray, Y: np.ndarray, c: tuple[float, float], ang_deg: float, r0: float, r1: float,
         w0: float, w1: float, i0: float, i1: float, soft: float = 0.35) -> np.ndarray:
    """Tapered ray from radius r0 (width w0, intensity i0) to r1 (w1, i1)."""
    a = math.radians(ang_deg)
    ux, uy = math.cos(a), math.sin(a)
    dx, dy = X - c[0], Y - c[1]
    along = dx * ux + dy * uy
    across = np.abs(-dx * uy + dy * ux)
    t = (along - r0) / max(1e-6, r1 - r0)
    half = np.maximum((w0 + (w1 - w0) * np.clip(t, 0, 1)) / 2.0, 0.5)
    inside = (t >= 0) & (t <= 1) & (across <= half + 1e-6)
    inten = i0 + (i1 - i0) * np.clip(t, 0, 1)
    return np.where(inside, inten * (1.0 - soft * across / half), 0.0)


def _ring(X: np.ndarray, Y: np.ndarray, c: tuple[float, float], r: float, thick: float, inten: float,
          gaps: int = 0, gap_frac: float = 0.3, rot_deg: float = 0.0, outer_dim: float = 0.3,
          sy: float = 1.0) -> np.ndarray:
    """Ring of radius r (optionally broken into `gaps` arcs), brighter on its
    inner edge. `sy` squashes it vertically (perspective ellipse)."""
    dx, dy = X - c[0], (Y - c[1]) / sy
    d = np.hypot(dx, dy) - r
    inside = np.abs(d) <= thick / 2.0
    if gaps:
        ang = (np.degrees(np.arctan2(dy, dx)) - rot_deg) % 360.0
        inside &= ((ang / (360.0 / gaps)) % 1.0) < (1.0 - gap_frac)
    v = inten * (1.0 - outer_dim * np.clip((d + thick / 2.0) / max(thick, 1e-6), 0, 1))
    return np.where(inside, v, 0.0)


def _disc(X: np.ndarray, Y: np.ndarray, c: tuple[float, float], r: float, inten: float,
          power: float = 1.0) -> np.ndarray:
    q = np.hypot(X - c[0], Y - c[1]) / max(r, 1e-6)
    return np.where(q <= 1.0, inten * (1.0 - q ** power * 0.6), 0.0)


def _tones(field: np.ndarray, cuts: Sequence[float]) -> np.ndarray:
    """Band a field: < cuts[0] transparent (-1), then tone 0, 1, ..."""
    idx = np.searchsorted(np.asarray(cuts, np.float64), field, side="right") - 1
    return np.clip(idx, -1, len(cuts) - 1).astype(np.int16)


_N4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _shift(a: np.ndarray, dx: int, dy: int, fill: int) -> np.ndarray:
    out = np.full_like(a, fill)
    h, w = a.shape
    out[max(0, -dy):h - max(0, dy), max(0, -dx):w - max(0, dx)] = \
        a[max(0, dy):h - max(0, -dy), max(0, dx):w - max(0, -dx)]
    return out


def _tidy(idx: np.ndarray, keep: np.ndarray | None = None, iterations: int = 1,
          fill_holes: bool = True) -> np.ndarray:
    """Pixel-art cleanup of a banded effect: drop opaque pixels with no
    4-neighbour, fill pinholes, 3x3 majority on tones, remove orphan tones.
    `keep` protects deliberate single pixels (sparks, embers)."""
    t = idx.astype(np.int16).copy()
    kp = np.zeros(t.shape, bool) if keep is None else keep.astype(bool)
    op = t >= 0
    n_op = sum((_shift(op.astype(np.int16), dx, dy, 0)) for dx, dy in _N4)
    t[op & (n_op == 0) & ~kp] = -1
    if fill_holes:
        op = t >= 0
        n_op = sum((_shift(op.astype(np.int16), dx, dy, 0)) for dx, dy in _N4)
        holes = ~op & (n_op >= 4)
        if holes.any():
            nb = np.stack([_shift(t, dx, dy, -1) for dx, dy in _N4])
            nb = np.where(nb >= 0, nb, 99)
            t[holes] = nb.min(0)[holes]
    mat = np.where(t >= 0, 0, -1)
    tone = np.maximum(t, 0)
    tone = majority(tone, mat, iterations=iterations, keep=kp) if iterations else tone
    tone = remove_orphans(tone, mat, keep=kp)
    return np.where(t >= 0, tone, -1).astype(np.int16)


def _img(idx: np.ndarray, ramp: Sequence[RGB]) -> Image.Image:
    return indices_to_image(idx, ramp)


def _starts(ticks: Sequence[int]) -> list[int]:
    out, acc = [], 0
    for t in ticks:
        out.append(acc)
        acc += int(t)
    return out


_CROSS = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], bool)


def _cool_fire(idx: np.ndarray, field: np.ndarray, *, rim: int = 2, rim_tone: int | Sequence[int] = 1,
               ground: bool = False, detached_tone: int = 1,
               caps: dict[int, float] | None = None) -> np.ndarray:
    """Make banded ADD fire read red-orange instead of cream:

    - the outer `rim` px of the silhouette drop to at most `rim_tone` (or
      to rim_tone[d] for the d-th pixel in from the edge), so the flame
      edge reads red against the wall (with `ground`, the bottom
      frame row counts as inside: a flame standing on the floor keeps its
      hot base);
    - pieces not attached to the main body (torn-off tips) drop to at most
      `detached_tone`;
    - `caps` {tone: max share}: the coolest pixels of an over-full hot tone
      (lowest field value) are demoted one tone, hottest tone first, so the
      white/yellow core stays a small cluster inside the body."""
    from scipy import ndimage
    t = idx.astype(np.int16).copy()
    op = t >= 0
    if not op.any():
        return t
    if rim > 0:
        # the rim of the filled silhouette: carved holes inside the body do
        # not grow dark rings, and inner ember-tone flecks are lifted to F1
        pad = np.pad(ndimage.binary_fill_holes(op), 1, constant_values=False)
        if ground:
            pad[-1, :] = pad[-2, :]
        tones = [rim_tone] * rim if isinstance(rim_tone, int) else list(rim_tone)
        outer = op.copy()
        inner = op
        for d in range(rim):
            inner = ndimage.binary_erosion(pad, _CROSS, iterations=d + 1)[1:-1, 1:-1]
            edge = outer & ~inner
            t[edge] = np.minimum(t[edge], tones[min(d, len(tones) - 1)])
            outer = op & inner
        t[op & inner & (t == 0)] = 1
    lab, n = ndimage.label(op, _CROSS)
    if n > 1:
        sizes = ndimage.sum(op, lab, range(1, n + 1))
        main = int(np.argmax(sizes)) + 1
        det = op & (lab != main)
        t[det] = np.minimum(t[det], detached_tone)
    if caps:
        total = int(op.sum())
        for tone in sorted(caps, reverse=True):
            sel = np.nonzero((t == tone).ravel())[0]
            limit = int(caps[tone] * total)
            if len(sel) > limit:
                order = np.argsort(field.ravel()[sel], kind="stable")
                demote = sel[order[:len(sel) - limit]]
                t.ravel()[demote] = tone - 1
    return t


# ---------------------------------------------------------------------------
# Particle systems (smoke/dust puffs, pixel embers)
# ---------------------------------------------------------------------------
class _Blobs:
    """Vectorised round puff particles stepped at 60 Hz (position,
    velocity with drag and buoyancy, growing radius, `heat` = remaining
    life that also shrinks the drawn radius). Rendered by _render_puffs."""

    KEYS = ("x", "y", "vx", "vy", "r", "dr", "heat", "cool", "ph", "sw", "fq", "age", "acc", "drag")

    def __init__(self, seed: int) -> None:
        self.rng = np.random.default_rng(seed)
        self.p: dict[str, np.ndarray] = {k: np.zeros(0) for k in self.KEYS}

    def emit(self, n: int, x: float, y: float, *, sx: float, sy: float = 1.0,
             vx: tuple[float, float] = (-0.2, 0.2), vy: tuple[float, float] = (-2.0, -1.4),
             r: tuple[float, float] = (3.0, 5.0), dr: tuple[float, float] = (-0.12, -0.06),
             heat: tuple[float, float] = (0.8, 1.0), cool: tuple[float, float] = (0.03, 0.05),
             sway: tuple[float, float] = (0.0, 0.8), freq: tuple[float, float] = (0.2, 0.4),
             acc: float = 0.0, drag: float = 1.0, radial: float = 0.0) -> None:
        if n <= 0:
            return
        g = self.rng
        new = {
            "x": x + g.uniform(-sx, sx, n),
            "y": y + g.uniform(-sy, sy, n),
            "vx": _u(g, vx, n),
            "vy": _u(g, vy, n),
            "r": _u(g, r, n),
            "dr": _u(g, dr, n),
            "heat": _u(g, heat, n),
            "cool": _u(g, cool, n),
            "ph": g.uniform(0, math.tau, n),
            "sw": _u(g, sway, n),
            "fq": _u(g, freq, n),
            "age": np.zeros(n),
            "acc": np.full(n, acc),
            "drag": np.full(n, drag),
        }
        if radial:
            ang = g.uniform(0, math.tau, n)
            sp = g.uniform(0.5, 1.0, n) * radial
            new["vx"] = new["vx"] + np.cos(ang) * sp
            new["vy"] = new["vy"] + np.sin(ang) * sp * 0.8
        for k in self.KEYS:
            self.p[k] = np.concatenate([self.p[k], new[k]])

    def step(self) -> None:
        p = self.p
        p["x"] += p["vx"]
        p["y"] += p["vy"]
        p["vx"] *= p["drag"]
        p["vy"] = p["vy"] * p["drag"] + p["acc"]
        p["r"] += p["dr"]
        p["heat"] -= p["cool"]
        p["age"] += 1
        alive = (p["heat"] > 0.02) & (p["r"] > 0.6)
        for k in self.KEYS:
            p[k] = p[k][alive]


class _Sparks:
    """1 px embers/sparks with gravity or buoyancy and sine sway."""

    def __init__(self, seed: int) -> None:
        self.rng = np.random.default_rng(seed)
        self.x = np.zeros(0)
        self.y = np.zeros(0)
        self.vx = np.zeros(0)
        self.vy = np.zeros(0)
        self.age = np.zeros(0)
        self.life = np.zeros(0)
        self.ph = np.zeros(0)
        self.sw = np.zeros(0)
        self.acc = np.zeros(0)

    def emit(self, n: int, x: float, y: float, *, sx: float, sy: float,
             vx: tuple[float, float], vy: tuple[float, float], life: tuple[float, float],
             sway: tuple[float, float] = (0.0, 0.0), acc: float = 0.0) -> None:
        if n <= 0:
            return
        g = self.rng
        self.x = np.concatenate([self.x, x + g.uniform(-sx, sx, n)])
        self.y = np.concatenate([self.y, y + g.uniform(-sy, sy, n)])
        self.vx = np.concatenate([self.vx, _u(g, vx, n)])
        self.vy = np.concatenate([self.vy, _u(g, vy, n)])
        self.age = np.concatenate([self.age, np.zeros(n)])
        self.life = np.concatenate([self.life, _u(g, life, n)])
        self.ph = np.concatenate([self.ph, g.uniform(0, math.tau, n)])
        self.sw = np.concatenate([self.sw, _u(g, sway, n)])
        self.acc = np.concatenate([self.acc, np.full(n, acc)])

    def step(self) -> None:
        self.x += self.vx + self.sw * np.cos(self.ph + self.age * 0.25) * 0.25
        self.y += self.vy
        self.vy += self.acc
        self.age += 1
        alive = self.age < self.life
        for k in ("x", "y", "vx", "vy", "age", "life", "ph", "sw", "acc"):
            setattr(self, k, getattr(self, k)[alive])

    def draw(self, idx: np.ndarray, keep: np.ndarray, tones: Sequence[int], *,
             streak: float = 0.0, x_off: float = 0.0) -> None:
        """Stamp each spark at a tone that drops with age (tones: young ->
        old). Fast sparks get a 1 px trailing streak along their motion."""
        h, w = idx.shape
        for x, y, vx, vy, age, life in zip(self.x, self.y, self.vx, self.vy, self.age, self.life):
            k = min(len(tones) - 1, int(age / max(1.0, life) * len(tones)))
            tone = tones[k]
            pts = [(x, y)]
            if streak and math.hypot(vx, vy) > streak:
                pts.append((x - vx * 0.7, y - vy * 0.7))
            for j, (px_, py_) in enumerate(pts):
                xi, yi = int(math.floor(px_ + x_off)), int(math.floor(py_))
                if 0 <= xi < w and 0 <= yi < h:
                    t = tone if j == 0 else max(0, tone - 1)
                    if idx[yi, xi] < t:
                        idx[yi, xi] = t
                    keep[yi, xi] = True


class _PuffChain:
    """Explosion smoke as discrete puffs (the SotN explosion-puff idea,
    reimplemented): each emitter sends len(PUFF_SPEEDS) puffs from one point
    along one heading at falling speeds, slowing PUFF_DECEL per tick, with
    PUFF_LIFT of buoyancy; the radius grows r0 -> r1 (ease-out). Rendered
    back to front, fastest (farthest) first, each puff a lit sphere with its
    own dark lower-back rim, so the cloud reads as separate round billows."""

    def __init__(self, seed: int, *, r0: float, r1: float, grow: float = 10.0,
                 speeds: Sequence[float] = PUFF_SPEEDS) -> None:
        self.rng = np.random.default_rng(seed)
        self.seed = seed
        self.r0, self.r1, self.grow = r0, r1, grow
        self.speeds = tuple(speeds)
        # per puff: birth tick, x, y, unit heading (ux, uy), speed, lift, emitter, size
        self.puffs: list[list[float]] = []

    def emit(self, t: int, x: float, y: float, angle_deg: float, scale: float = 1.0) -> int:
        """One emitter at tick t; heading in degrees from straight up
        (negative = left). The puffs fan out +/-9 deg around it, so the
        string does not line up like beads. Returns the emitter id."""
        eid = len({int(p[7]) for p in self.puffs})
        for k, sp in enumerate(self.speeds):
            fan = PUFF_FAN[k % len(PUFF_FAN)] + self.rng.uniform(-5.0, 5.0)
            a = math.radians(max(-80.0, min(80.0, angle_deg + fan)))
            self.puffs.append([float(t), x, y, math.sin(a), -math.cos(a), sp * scale,
                               PUFF_LIFT * scale, float(eid), PUFF_SIZE[k % len(PUFF_SIZE)]])
        return eid

    def _state(self, p: Sequence[float], t: int) -> tuple[float, float, float, float]:
        """(x, y, radius, age) of puff p at tick t (age < 0: not born)."""
        age = t - p[0]
        if age < 0:
            return p[1], p[2], 0.0, age
        travel = p[5] * (1.0 - PUFF_DECEL ** age) / (1.0 - PUFF_DECEL)
        x = p[1] + p[3] * travel
        y = p[2] + p[4] * travel - p[6] * age
        r = self.r0 + (self.r1 - self.r0) * (1.0 - math.exp(-age / self.grow)) \
            / (1.0 - math.exp(-30.0 / self.grow))
        return x, y, min(r, self.r1) * p[8], age

    def fit(self, frame_ticks: Sequence[int], fade_from: int, w: int, h: int, margin: int = 1) -> None:
        """Slow an emitter down (speed and lift x0.9 per pass) until every
        puff stays `margin` px inside the frame at every frame start."""
        for eid in sorted({int(p[7]) for p in self.puffs}):
            mine = [p for p in self.puffs if int(p[7]) == eid]
            for _ in range(40):
                worst = 0.0
                for fi, t in enumerate(frame_ticks):
                    erode = max(0, fi - fade_from + 1)
                    for p in mine:
                        x, y, r, age = self._state(p, t)
                        if age < 0:
                            continue
                        r = max(0.0, r - erode)
                        worst = max(worst, margin - (y - r), margin - (x - r), (x + r) - (w - margin),
                                    (y + r) - (h - margin))
                if worst <= 0.0:
                    break
                for p in mine:
                    p[5] *= 0.9
                    p[6] *= 0.9

    def render(self, t: int, w: int, h: int, fade: int = 0) -> Image.Image:
        """The puffs at tick t. `fade` 1..3: radius eroded by `fade` px and
        about PUFF_FADE_DROP[fade - 1] of the pixels knocked out (seeded
        hash on 2x2 cells, rims first), so each puff thins from the edge."""
        X, Y = _grid(w, h)
        idx = np.full((h, w), -1, np.int16)
        rimq = np.zeros((h, w))
        warm = np.zeros((h, w), bool)
        lx, ly, lz = PUFF_LIGHT
        ln = math.sqrt(lx * lx + ly * ly + lz * lz)
        bx, by = PUFF_BACK
        live = []
        for p in self.puffs:
            x, y, r, age = self._state(p, t)
            if age >= 0:
                live.append((p[0], -p[5], x, y, r - fade, age))
        # back to front: older emitters behind newer ones; within one, the
        # fastest (farthest out) first, the slower ones in front of it
        for _, _, x, y, r, age in sorted(live, key=lambda q: (q[0], q[1])):
            if r < 2.2:                  # a newborn dot reads as a pebble: wait until it is a puff
                continue
            dx, dy = (X - x) / r, (Y - y) / r
            q2 = dx * dx + dy * dy
            inside = q2 <= 1.0
            if not inside.any():
                continue
            nz = np.sqrt(np.clip(1.0 - q2, 0.0, 1.0))
            lit = (dx * lx + dy * ly + nz * lz) / ln
            tone = np.where(lit > PUFF_CUTS[0], 3, np.where(lit > PUFF_CUTS[1], 2, 1)).astype(np.int16)
            pad = np.pad(inside, 1, constant_values=False)
            rim = inside & ~(pad[:-2, 1:-1] & pad[2:, 1:-1] & pad[1:-1, :-2] & pad[1:-1, 2:])
            tone = np.where(rim & ((dx * bx + dy * by) > 0.3), 0, tone)
            idx = np.where(inside, tone, idx)
            rimq = np.where(inside, q2, rimq)
            young = rim & (dy > 0.5) if age < SMOKE_WARM_AGE else np.zeros_like(rim)
            warm = np.where(inside, young, warm)
        # the fire-lit crescent only where it is the underside of the cloud
        # (nothing drawn below it), never a stripe across another puff
        below = np.vstack([idx[1:], np.full((1, w), -1, np.int16)])
        idx = np.where(warm & (below < 0), 4, idx).astype(np.int16)
        if fade > 0:
            # knocked out in 2x2 cells (seeded per frame), rims first: the
            # puff thins into a few clumps rather than salt-and-pepper noise
            cells = np.random.default_rng(self.seed * 131 + t).random(((h + 1) // 2, (w + 1) // 2))
            hsh = np.repeat(np.repeat(cells, 2, 0), 2, 1)[:h, :w]
            frac = PUFF_FADE_DROP[min(fade, len(PUFF_FADE_DROP)) - 1]
            idx = np.where(hsh < frac * (0.55 + 0.9 * rimq), -1, idx).astype(np.int16)
            # no lone pixels: what is left of a puff is 2+ px clumps
            op = idx >= 0
            pad = np.pad(op, 1, constant_values=False)
            lone = op & ~(pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:])
            idx = np.where(lone, -1, idx).astype(np.int16)
        return _img(idx, SMOKE_FX + [SMOKE_WARM])


def _fire_layers(idx: np.ndarray) -> tuple[Image.Image, Image.Image]:
    """(core for the ADD root, body for the opaque MIX child) from banded
    FIRE tones: the body is the whole silhouette in the shared ramp, the core
    only the FIRE_CORE_FROM+ tones as additive lifts."""
    body = _img(idx, FIRE)
    core = np.where(idx >= FIRE_CORE_FROM, idx - FIRE_CORE_FROM, -1).astype(np.int16)
    return _img(core, FIRE_CORE), body


def _top_of(idx: np.ndarray) -> tuple[int, float]:
    """(highest opaque row, mean x of the pixels in its top 3 rows)."""
    ys, xs = np.nonzero(idx >= 0)
    if len(ys) == 0:
        return idx.shape[0], idx.shape[1] / 2.0
    top = int(ys.min())
    sel = ys <= top + 2
    return top, float(xs[sel].mean()) + 0.5


# ---------------------------------------------------------------------------
# HIT SPARK (32x32 centred, additive): 3 variants
# ---------------------------------------------------------------------------
SPARK_W = SPARK_H = 32
SPARK_C = (15.5, 15.5)    # centre of pixel (15, 15): 1 px rays stay 1 px
SPARK_CUTS = (0.08, 0.20, 0.36, 0.55, 0.74, 0.90)


Spark = tuple[float, float, float, int]          # x, y, heading (deg), head tone


def _spark_frame(layers: Sequence[np.ndarray], sparks: Sequence[Spark] = ()) -> Image.Image:
    f = np.maximum.reduce(list(layers)) if layers else np.zeros((SPARK_H, SPARK_W))
    idx = _tones(f, SPARK_CUTS)
    keep = np.zeros(idx.shape, bool)
    for x, y, ang, tone in sparks:
        # a streak along its heading: bright head, 1-2 px cooling tail
        ux, uy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        tail = ((0, tone), (1, tone - 1), (2, tone - 3)) if tone >= 3 else ((0, tone), (1, tone - 2))
        for j, tt in tail:
            if tt < 0:
                continue
            xi, yi = int(math.floor(x - ux * j)), int(math.floor(y - uy * j))
            if 0 <= xi < SPARK_W and 0 <= yi < SPARK_H and idx[yi, xi] < tt:
                idx[yi, xi] = tt
                keep[yi, xi] = True
    idx = _tidy(idx, keep, iterations=0, fill_holes=False)
    return _img(idx, FIRE)


def _spark_set(seed: int, n: int, r0: float, r1: float,
               avoid: Sequence[float] = (0, 90, 180, 270)) -> list[tuple[float, float, float]]:
    """(angle, start radius, speed per frame) for flying sparks, kept off the
    main ray axes so they read as separate debris."""
    g = np.random.default_rng(seed)
    out: list[tuple[float, float, float]] = []
    base = g.uniform(0, 360)
    for k in range(n):
        ang = (base + k * 360.0 / n + g.uniform(-12, 12)) % 360.0
        for a in avoid:
            d = (ang - a + 540.0) % 360.0 - 180.0
            if abs(d) < 10:
                ang = a + (10 if d >= 0 else -10)
        out.append((ang, g.uniform(r0, r1), g.uniform(2.4, 3.2)))
    return out


def _fly(sp: Sequence[tuple[float, float, float]], c: tuple[float, float], k: float, tone: int,
         drop: float = 0.35, every: int = 1) -> list[Spark]:
    """Sparks after `k` frames of flight (slight gravity: y += drop * k^2)."""
    out: list[Spark] = []
    for i, (a, r, s) in enumerate(sp):
        if i % every:
            continue
        d = r + s * k
        x = c[0] + math.cos(math.radians(a)) * d
        y = c[1] + math.sin(math.radians(a)) * d + drop * k * k
        head = math.degrees(math.atan2(math.sin(math.radians(a)) * s + 2 * drop * k,
                                       math.cos(math.radians(a)) * s))
        out.append((x, y, head, tone))
    return out


def _arcs_between(n: int, gap_frac: float, offset: float = 0.0) -> float:
    """rot_deg for _ring so its n arcs are centred between n rays (+offset)."""
    seg = 360.0 / n
    return seg / 2.0 - (1.0 - gap_frac) * seg / 2.0 + offset


def _spark_star() -> tuple[list[Image.Image], list[int]]:
    """Impact star: white 8-ray star -> ring of 8 arcs -> flying sparks."""
    X, Y = _grid(SPARK_W, SPARK_H)
    c = SPARK_C
    sp = _spark_set(11, 5, 7.0, 8.5)
    frames: list[Image.Image] = []
    # f0: tight white star
    L = [_disc(X, Y, c, 2.6, 1.05, 2.0)]
    L += [_ray(X, Y, c, a, 1.5, 10.0, 3.0, 1.0, 1.0, 0.5) for a in (0, 90, 180, 270)]
    L += [_ray(X, Y, c, a, 1.5, 6.0, 1.0, 1.0, 0.85, 0.42) for a in (45, 135, 225, 315)]
    frames.append(_spark_frame(L))
    # f1: full star, fat white core
    L = [_disc(X, Y, c, 4.2, 1.0, 1.6)]
    L += [_ray(X, Y, c, a, 2.0, 14.5, 3.0, 1.0, 0.98, 0.32) for a in (0, 90, 180, 270)]
    L += [_ray(X, Y, c, a, 2.0, 9.0, 2.0, 1.0, 0.8, 0.3) for a in (45, 135, 225, 315)]
    frames.append(_spark_frame(L))
    # f2: the star collapses into a ring of 8 arcs; sparks leave
    L = [_disc(X, Y, c, 2.2, 0.8, 1.0),
         _ring(X, Y, c, 8.5, 2.0, 0.82, gaps=8, gap_frac=0.4, rot_deg=_arcs_between(8, 0.4))]
    frames.append(_spark_frame(L, _fly(sp, c, 1, 4)))
    # f3: thin ring, sparks further out
    L = [_ring(X, Y, c, 11.0, 1.0, 0.44, gaps=8, gap_frac=0.55, rot_deg=_arcs_between(8, 0.55))]
    frames.append(_spark_frame(L, _fly(sp, c, 2, 3)))
    # f4: only the sparks remain, cooling
    frames.append(_spark_frame([], _fly(sp, c, 3, 2)))
    # f5: last embers sinking
    frames.append(_spark_frame([], _fly(sp, c, 3.7, 1, drop=0.5, every=2)))
    return frames, [2, 2, 2, 2, 2, 3]


def _spark_slash() -> tuple[list[Image.Image], list[int]]:
    """Blade-hit slash: a white crescent streak across the impact that
    splits apart, with sparks thrown off perpendicular to the cut."""
    X, Y = _grid(SPARK_W, SPARK_H)
    c = SPARK_C
    ang = -35.0                      # rising cut (right-facing swing)
    ux, uy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    nx, ny = -uy, ux                 # crescent bulge direction

    def crescent(length: float, width: float, inten: float, split: float = 0.0,
                 bow: float = 2.0) -> np.ndarray:
        dx, dy = X - c[0], Y - c[1]
        along = dx * ux + dy * uy
        across = dx * nx + dy * ny
        t = along / (length / 2.0)                       # -1 .. 1
        centre = bow * (1.0 - t * t)                      # bowed spine
        half = np.maximum(width / 2.0 * np.clip(1.0 - t * t, 0.0, 1.0) ** 0.8, 0.5)
        dist = np.abs(across - centre)
        inside = (np.abs(t) <= 1.0) & (dist <= half) & (np.abs(t) >= split)
        v = inten * (1.0 - 0.45 * np.abs(t) ** 1.5) * (1.0 - 0.3 * dist / half)
        return np.where(inside, v, 0.0)

    g = np.random.default_rng(5)
    sp = [(90 + ang + d, g.uniform(3, 5), g.uniform(2.4, 3.2)) for d in (-25, 12, 195, 168)]
    frames: list[Image.Image] = []
    frames.append(_spark_frame([crescent(18, 1.6, 1.0, bow=1.0), _disc(X, Y, c, 2.0, 1.0)]))
    frames.append(_spark_frame([crescent(28, 4.2, 1.02, bow=2.0), _disc(X, Y, c, 3.0, 1.0, 2.0),
                                _ray(X, Y, c, ang + 90, 0, 5, 1, 1, 0.9, 0.5),
                                _ray(X, Y, c, ang - 90, 0, 4, 1, 1, 0.9, 0.5)]))
    frames.append(_spark_frame([crescent(30, 3.0, 0.74, split=0.18, bow=2.6)], _fly(sp, c, 1, 4)))
    frames.append(_spark_frame([crescent(30, 1.6, 0.42, split=0.45, bow=3.0)], _fly(sp, c, 2, 3)))
    frames.append(_spark_frame([], _fly(sp, c, 3, 2)))
    frames.append(_spark_frame([], _fly(sp, c, 3.7, 1, drop=0.5, every=2)))
    return frames, [1, 2, 2, 2, 2, 3]


def _spark_burst() -> tuple[list[Image.Image], list[int]]:
    """Heavy hit / whip crack: round white flash with a spiked shock ring."""
    X, Y = _grid(SPARK_W, SPARK_H)
    c = SPARK_C
    sp = _spark_set(23, 7, 9.0, 10.5, avoid=())
    frames: list[Image.Image] = []
    L = [_disc(X, Y, c, 5.2, 1.05, 2.5)]
    L += [_ray(X, Y, c, a, 4.0, 9.0, 2.0, 1.0, 0.8, 0.4) for a in range(0, 360, 45)]
    frames.append(_spark_frame(L))
    L = [_disc(X, Y, c, 4.0, 0.8, 1.5), _ring(X, Y, c, 7.5, 3.0, 1.0, outer_dim=0.55)]
    L += [_ray(X, Y, c, a + 22.5, 8.0, 13.5, 1.0, 1.0, 0.62, 0.3) for a in range(0, 360, 45)]
    frames.append(_spark_frame(L))
    L = [_ring(X, Y, c, 10.5, 2.0, 0.7, gaps=12, gap_frac=0.25, rot_deg=8, outer_dim=0.5)]
    frames.append(_spark_frame(L, _fly(sp, c, 1, 4)))
    L = [_ring(X, Y, c, 12.5, 1.0, 0.36, gaps=12, gap_frac=0.6, rot_deg=8)]
    frames.append(_spark_frame(L, _fly(sp, c, 1.8, 3)))
    frames.append(_spark_frame([], _fly(sp, c, 2.4, 2)))
    frames.append(_spark_frame([], _fly(sp, c, 2.9, 1, drop=0.5, every=2)))
    return frames, [2, 2, 2, 2, 3, 3]


def build_hit_spark() -> None:
    sb = SheetBuilder("hit_spark", SPARK_W, SPARK_H, origin=(16, 16))
    for name, fn in (("default", _spark_star), ("slash", _spark_slash), ("burst", _spark_burst)):
        frames, ticks = fn()
        sb.add(name, frames, 60, False, ticks=ticks)
    sb.save()


# ---------------------------------------------------------------------------
# DEATH FLAME (40x88, base on the bottom row): rising column of fire (an
# opaque body under an additive hot core) that burns upward and dissolves
# into embers, with smoke puffs rolling off its top (MIX child layer)
# ---------------------------------------------------------------------------
FLAME_W, FLAME_H = 40, 64      # the fire column's own canvas
FLAME_HEADROOM = 24            # extra rows above it so the smoke never leaves the frame
FLAME_TICKS = [2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5]   # 42 ticks = 0.70 s


def _render_puffs(puffs: _Blobs, w: int, h: int, ramp: Sequence[RGB], *,
                  light: tuple[float, float, float] = (-0.45, -0.75, 0.5), size: float = 1.0,
                  floor_y: float | None = None, crumble: float = 0.0,
                  warm: tuple[float, float, RGB] | None = None, dissolve: float = 0.0) -> Image.Image:
    """Billowing puffs: every blob is a lit sphere (radius * heat ** 0.5 *
    `size`), the front-most sphere wins each pixel and its normal picks the
    ramp tone, so the cloud reads as round clustered billows lit from the
    upper left. `crumble` in 0..1 knocks out an ordered pattern near the
    rims (the puff breaking into specks). Pixels below `floor_y` are cut.
    `warm` (max age in ticks, min downward normal, colour): the underside of
    young puffs is lit by the fire below them. `dissolve` in 0..1 thins the
    whole puff (rims first) instead of only its rim."""
    from common import bayer
    X, Y = _grid(w, h)
    depth = np.full((h, w), -np.inf)
    inten = np.zeros((h, w))
    rimq = np.zeros((h, w))
    ages = np.full((h, w), np.inf)
    ndy = np.zeros((h, w))
    lx, ly, lz = light
    ln = math.sqrt(lx * lx + ly * ly + lz * lz)
    p = puffs.p
    xs = p["x"] + p["sw"] * np.sin(p["ph"] + p["fq"] * p["age"])
    for i, (x, y, r, ht, ag) in enumerate(zip(xs, p["y"], p["r"], p["heat"], p["age"])):
        rr = r * size * max(0.0, ht) ** 0.5
        if rr < 0.8:
            continue
        x0, x1 = max(0, int(x - rr - 1)), min(w, int(x + rr + 2))
        y0, y1 = max(0, int(y - rr - 1)), min(h, int(y + rr + 2))
        if x0 >= x1 or y0 >= y1:
            continue
        dx = (X[y0:y1, x0:x1] - x) / rr
        dy = (Y[y0:y1, x0:x1] - y) / rr
        q2 = dx * dx + dy * dy
        nz = np.sqrt(np.clip(1.0 - q2, 0.0, 1.0))
        d = nz * rr + i * 1e-3
        upd = (q2 < 1.0) & (d > depth[y0:y1, x0:x1])
        lit = (dx * lx + dy * ly + nz * lz) / ln
        depth[y0:y1, x0:x1] = np.where(upd, d, depth[y0:y1, x0:x1])
        inten[y0:y1, x0:x1] = np.where(upd, lit, inten[y0:y1, x0:x1])
        rimq[y0:y1, x0:x1] = np.where(upd, q2, rimq[y0:y1, x0:x1])
        ages[y0:y1, x0:x1] = np.where(upd, ag, ages[y0:y1, x0:x1])
        ndy[y0:y1, x0:x1] = np.where(upd, dy, ndy[y0:y1, x0:x1])
    n = len(ramp)
    cuts = np.linspace(-0.25, 0.85, n + 1)[1:-1]
    tone = np.where(np.isfinite(depth), np.searchsorted(cuts, inten, side="right"), -1)
    cols = list(ramp)
    if warm is not None:
        max_age, min_dy, col = warm
        cols.append(col)
        tone = np.where((tone >= 0) & (ages < max_age) & (ndy > min_dy) & (rimq > 0.3), n, tone)
    if floor_y is not None:
        tone = np.where(Y > floor_y, -1, tone)
    if crumble > 0:
        b = bayer(4, (h, w))
        tone = np.where((tone >= 0) & (rimq > 0.35) & (b < crumble), -1, tone)
    if dissolve > 0:
        b = bayer(4, (h, w))
        tone = np.where((tone >= 0) & (b < dissolve * (0.3 + 0.9 * rimq)), -1, tone)
    idx = _tidy(tone.astype(np.int16), iterations=1)
    return _img(idx, cols)


def _tongue_noise(w: int, h: int, seed: int, cell: float = 4.0, stretch: float = 3.0) -> np.ndarray:
    """Value noise in [0, 1] stretched vertically: carving a fire column
    with it leaves tall, pointed tongues instead of round blobs."""
    from scipy.ndimage import zoom
    from common import value_noise
    hs = int(math.ceil(h / stretch)) + 2
    n = 0.68 * value_noise(w, hs, cell, seed, tileable=True) \
        + 0.32 * value_noise(w, hs, cell / 2.0, seed + 1, tileable=True)
    return zoom(n, (stretch, 1.0), order=1)[:h]


FLAME_TONGUES: tuple[tuple[float, float, float, float], ...] = (
    # (x offset in base half-widths, height fraction, width fraction, sway phase)
    (0.0, 1.0, 0.78, 0.0),
    (-1.0, 0.70, 0.42, 2.1),
    (0.95, 0.82, 0.40, 4.0),
    (-0.42, 0.88, 0.34, 5.2),
)


def _column_field(X: np.ndarray, Y: np.ndarray, t: float, *, cx: float, base: float, top_h: float,
                  lift: float, hw0: float, gain: float, carve: float, noise: np.ndarray,
                  edge: np.ndarray,
                  tongues: Sequence[tuple[float, float, float, float]] = FLAME_TONGUES) -> np.ndarray:
    """Intensity of a burning column at tick t: a tall central tongue among
    lower side tongues, each hot and wide at the base and tapering to a
    swaying tip. `edge` (fast noise) makes the silhouette ragged; `noise`
    (vertically stretched, scrolled upward) carves it multiplicatively,
    harder toward the top, so tips split and detach. Nothing is drawn
    outside the tongues."""
    bottom = base - lift
    acc = np.zeros(X.shape)
    # once lifted, the burning-away underside is convex (edges end higher)
    rnd = min(7.0, lift * 0.9) * np.clip(((X - cx) / max(hw0 * 1.4, 1.0)) ** 2, 0.0, 1.5)
    for k, (ox, hf, wf, ph) in enumerate(tongues):
        top = base - top_h * hf
        span = max(1.0, bottom - top)
        hr = (bottom - Y - rnd) / span
        hrc = np.clip(hr, 0.0, 1.0)
        sway = (1.8 * np.sin(Y * 0.15 + t * 0.33 + ph) + 1.0 * np.sin(Y * 0.31 - t * 0.52 + ph)) * hrc
        taper = 1.0 - 0.8 * hrc ** 1.25
        if lift > 0:      # a lifted column also tapers at its burning-away bottom
            taper = taper * np.clip(0.35 + hrc * 3.0, 0.0, 1.0)
        hw = hw0 * wf * taper + 0.5
        u = (X - cx - ox * hw0 * (1.0 - 0.3 * hrc) - sway + edge * (0.8 + 1.6 * hrc)) / hw
        core = np.clip(1.0 - u * u, 0.0, 1.0) ** 0.8 * np.clip(1.0 - hr, 0.0, 1.0) ** 0.36
        core = np.where((hr >= -0.02) & (hr <= 1.0), core, 0.0) * (1.0 if k == 0 else 0.9)
        acc = np.maximum(acc, core)
    hrm = np.clip((bottom - Y) / max(1.0, top_h), 0.0, 1.0)
    low = 0.0
    if lift > 0:
        # the burning-away underside: cooler, ragged, carved like the tips
        nb = np.clip((bottom - Y) / 8.0, 0.0, 1.0)
        acc = acc * (0.25 + 0.75 * nb)
        low = (1.0 - nb) * 0.3
    m = np.clip(1.3 - carve * (noise - 0.25) * (0.08 + 1.4 * hrm ** 1.3 + low), 0.0, 1.3)
    # inner tongues: the same climbing noise shapes the hot core, so the
    # white/yellow bands inside the column are licks, not a solid block
    inner = 1.0 - 0.32 * np.clip(noise - 0.35, 0.0, 1.0) * (1.0 - 0.6 * hrm)
    return gain * acc * m * inner


def _death_flame_frames(seed: int = 3) -> tuple[list[Image.Image], list[Image.Image], list[Image.Image]]:
    """(core frames for ADD, body frames for the opaque child, smoke frames
    for the MIX child), all 40 x (64 + FLAME_HEADROOM), base on the bottom
    row."""
    W, H = FLAME_W, FLAME_H
    FH = H + FLAME_HEADROOM
    cx, base = W / 2.0, H - 0.5
    total = sum(FLAME_TICKS)
    speed = 1.9                                   # tongues climb ~1.9 px/tick
    noise = _tongue_noise(W, H + int(total * speed) + 8, seed + 3)
    edge_n = (_tongue_noise(W, H + int(total * speed * 1.3) + 8, seed + 5, cell=2.0, stretch=1.5) - 0.5) * 2.0
    X, Y = _grid(W, H)
    embers = _Sparks(seed + 1)
    g = np.random.default_rng(seed + 4)
    starts = _starts(FLAME_TICKS)
    n = len(FLAME_TICKS)
    # smoke: one puff emitter at frame 6 (the base has started to lift and
    # the column tops out) and a second at frame 7 heading off the other
    # side, both from 3 px above that frame's highest flame pixel
    smoke = _PuffChain(seed + 2, r0=2.0, r1=6.0, grow=6.0)
    smoke_at = {starts[6]: -1.0, starts[7]: 1.0}
    core_frames: list[Image.Image] = []
    body_frames: list[Image.Image] = []
    fi = 0
    for t in range(total + 1):
        # envelope: ignition (squat, white-hot) -> roaring 60 px column ->
        # the base burns away upward while the tongues cool and break up
        top_h = min(62.0, 30.0 + t * 8.0)
        lift = max(0.0, (t - 16) * 1.45)
        # white-hot only for the 2-tick ignition; after that the column
        # burns orange (gain <= 1.15) and cools
        gain = 1.42 if t < 2 else min(1.15, max(0.42, 1.18 - 0.016 * max(0, t - 6) - 0.012 * max(0, t - 22)))
        hw0 = 11.5 if t < 2 else max(5.0, 9.5 - 0.10 * t)
        carve = 1.05 + 0.03 * t
        if t == 0:
            embers.emit(5, cx, base - 18, sx=9, sy=8, vx=(-0.7, 0.7), vy=(-2.8, -1.6),
                        life=(12, 22), sway=(0.5, 1.5))
        if 2 <= t <= 30 and t % 3 == 0:
            embers.emit(1, cx, base - 22 - lift, sx=6, sy=10, vx=(-0.45, 0.45), vy=(-2.4, -1.3),
                        life=(10, 22), sway=(0.6, 1.6))
        if fi < len(starts) and t == starts[fi]:
            off = int(t * speed)
            f = _column_field(X, Y, t, cx=cx, base=base, top_h=top_h, lift=lift, hw0=hw0,
                              gain=gain, carve=carve, noise=noise[off:off + H],
                              edge=edge_n[int(t * speed * 1.3):int(t * speed * 1.3) + H])
            idx = _tones(f, FIRE_CUTS_ADD)
            keep = np.zeros(idx.shape, bool)
            idx = _tidy(idx, keep, iterations=2)
            idx = _cool_fire(idx, f, rim=2, rim_tone=(1, 2), ground=lift <= 0.0, detached_tone=1,
                             caps=FIRE_CAPS if t >= 2 else None)
            embers.draw(idx, keep, (3, 3, 2, 2, 1), streak=1.2)
            full = np.full((FH, W), -1, np.int16)
            full[FLAME_HEADROOM:] = idx
            core, body = _fire_layers(full)
            core_frames.append(core)
            body_frames.append(body)
            if t in smoke_at:
                top, tx = _top_of(full)
                side = smoke_at[t]
                smoke.emit(t, tx + side * g.uniform(1.0, 4.0), top - 3.0 - smoke.r0,
                           max(-50.0, min(50.0, side * g.uniform(14.0, 40.0))))
            fi += 1
        embers.step()
    smoke.fit(starts, n - 3, W, FH)
    smoke_frames = [smoke.render(t, W, FH, fade=max(0, i - (n - 4))) for i, t in enumerate(starts)]
    return core_frames, body_frames, smoke_frames


def build_death_flame() -> None:
    core, body, smoke = _death_flame_frames()
    full_h = FLAME_H + FLAME_HEADROOM
    sb = SheetBuilder("death_flame", FLAME_W, full_h, origin=(FLAME_W // 2, full_h - 1))
    sb.add("default", core, 60, False, ticks=FLAME_TICKS)
    sb.add("smoke", smoke, 60, False, ticks=FLAME_TICKS)
    sb.add("default_body", body, 60, False, ticks=FLAME_TICKS)
    sb.save()


# ---------------------------------------------------------------------------
# FIRE BALL: the SotN small explosion, shared by fire_pop (skeleton pieces,
# the bat) and candle_break. A 2-tick white star, then a round fireball of
# 3-5 overlapping lobes with a convex, noise-broken underside: it swells,
# rises 0.5-1 px/tick, splits into 2-3 tongues on top and cools through
# orange and red into a few ember specks, while a cluster of smoke puffs
# rises off its crown on a MIX sibling layer. Nothing is cut flat: it hangs
# in the air. Opaque body + additive core, like the death flame.
# ---------------------------------------------------------------------------
FireLobe = tuple[float, float, float, float]   # angle (deg), spread (x R), radius (x R), rise multiplier
POP_LOBES_S: tuple[FireLobe, ...] = (
    (-90.0, 0.42, 0.68, 1.15), (150.0, 0.44, 0.60, 0.92), (30.0, 0.44, 0.58, 1.0))
POP_LOBES_L: tuple[FireLobe, ...] = (
    (-90.0, 0.44, 0.62, 1.18), (145.0, 0.48, 0.56, 0.92), (35.0, 0.48, 0.56, 1.0),
    (195.0, 0.46, 0.46, 1.05), (-15.0, 0.46, 0.44, 1.08))
# field -> FIRE tone: a big white core only while the ball is young
POP_CUTS: tuple[float, ...] = (0.06, 0.22, 0.42, 0.62, 0.80, 0.93)
POP_CAPS: dict[int, float] = {5: 0.06, 4: 0.11, 3: 0.22}
POP_CAPS_YOUNG: dict[int, float] = {5: 0.14, 4: 0.20, 3: 0.30}      # the first ball frame


def _smooth(a: float, b: float, x: float) -> float:
    s = min(1.0, max(0.0, (x - a) / max(1e-6, b - a)))
    return s * s * (3.0 - 2.0 * s)


def _fireball_frames(w: int, h: int, c: tuple[float, float], ticks: Sequence[int], *, r_max: float,
                     lobes: Sequence[FireLobe], seed: int, rise: tuple[float, float] = (0.5, 1.0),
                     flash_r: float = 2.6, ray_len: float = 4.0, n_embers: int = 4,
                     smoke_frames_at: Sequence[int] = (), puff_r: tuple[float, float] = (1.5, 4.5),
                     ) -> tuple[list[Image.Image], list[Image.Image], list[Image.Image]]:
    """(core frames for the ADD root, body frames for the opaque child,
    smoke frames for the MIX child), one per tick entry. `c` is the spawn
    point: the flash and the young ball are centred on it, then the ball
    rises. `smoke_frames_at`: frame indices that each start one puff emitter
    3 px above that frame's ball."""
    total = sum(ticks)
    starts = _starts(ticks)
    n = len(ticks)
    t0 = int(ticks[0])                  # the flash; the ball forms after it
    life = float(total - t0)
    X, Y = _grid(w, h)
    scroll = 1.6
    tn = _tongue_noise(w, h + int(total * scroll) + 8, seed + 1, cell=2.6, stretch=2.2)
    from common import value_noise
    frag_n = value_noise(w, h + int(total * scroll) + 8, 2.2, seed + 5, tileable=True)
    en = (_tongue_noise(w, h + int(total * scroll * 1.4) + 8, seed + 2, cell=1.8, stretch=1.2) - 0.5) * 2.0
    g = np.random.default_rng(seed)
    jit = [(g.uniform(-12, 12), g.uniform(0.9, 1.1)) for _ in lobes]
    embers = _Sparks(seed + 3)
    smoke = _PuffChain(seed + 4, r0=puff_r[0], r1=puff_r[1], grow=4.0)
    gs = np.random.default_rng(seed + 6)
    smoke_ticks = {starts[i]: (-1.0 if j % 2 == 0 else 1.0) for j, i in enumerate(smoke_frames_at)}
    core_frames: list[Image.Image] = []
    body_frames: list[Image.Image] = []
    empty = np.full((h, w), -1, np.int16)
    fi = 0
    for t in range(total + 1):
        k = float(t - t0)
        u = k / life
        rise_px = rise[0] * k + 0.5 * (rise[1] - rise[0]) * k * k / life if k > 0 else 0.0
        if t == t0:
            embers.emit(n_embers, c[0], c[1] - 1.0, sx=2.0, sy=2.0, vx=(-1.1, 1.1), vy=(-1.6, -0.3),
                        life=(8, 14), acc=0.05)
        if fi < len(starts) and t == starts[fi]:
            if t < t0:
                # the white star: a small disc with 4 short rays (SPARK_CUTS),
                # pure light on the ADD root; the body has nothing yet
                f = np.maximum.reduce([_disc(X, Y, c, flash_r, 1.05, 3.0)]
                                      + [_ray(X, Y, c, a, flash_r * 0.6, flash_r + ray_len, 1.0, 1.0, 1.0, 0.62)
                                         for a in (0, 90, 180, 270)])
                idx = _tidy(_tones(f, SPARK_CUTS), iterations=0)
                # no ember/red ray tips: under ADD they turn mauve on a
                # mid-value wall; the flash is white, yellow and orange only
                idx = np.where(idx >= 2, idx, -1).astype(np.int16)
                core_frames.append(_img(idx, FIRE_ADD))
                body_frames.append(_img(empty, FIRE))
            else:
                R = r_max * (0.72 + 0.28 * _smooth(0.0, 3.0, k))     # ~10 px ball -> full size
                heat = max(0.0, 1.0 - u ** 1.1)
                off = int(t * scroll)
                noise = tn[off:off + h]
                edge = en[int(t * scroll * 1.4):int(t * scroll * 1.4) + h]
                split = _smooth(0.5, 4.5, k)                          # one ball -> lobes
                field = np.zeros((h, w))
                for (ang, spread, rf, rm), (dj, sj) in zip(lobes, jit):
                    a = math.radians(ang + dj)
                    lx = c[0] + math.cos(a) * spread * R * split * (1.0 + 0.3 * u)
                    ly = c[1] + math.sin(a) * spread * R * split * 0.8 - rise_px * rm
                    rl = R * (1.0 - (1.0 - rf * sj) * split) * (1.0 - 0.6 * u ** 1.4)
                    if rl < 0.7:
                        continue
                    dx, dy = X - lx, Y - ly
                    stretch = 1.0 + 1.1 * _smooth(0.15, 0.7, u)        # tops pull up into tongues
                    dyy = np.where(dy < 0, dy / stretch, dy * (1.0 + 0.5 * u))
                    q = np.hypot(dx, dyy) / rl
                    q = q + 0.2 * edge * (0.25 + q)                      # ragged rim, convex overall
                    v = np.sqrt(np.clip(1.0 - q * q, 0.0, 1.0))
                    # the burning-away underside rises but stays round
                    v = v * np.clip(1.0 - 0.9 * u * np.clip(dy / rl, 0.0, 1.0), 0.0, 1.0)
                    field = np.maximum(field, v)
                # climbing noise carves the upper half into tongues, harder as it cools
                up = np.clip((c[1] - rise_px - Y) / max(1.0, R), 0.0, 1.6)
                carve = 0.25 + 1.5 * _smooth(0.1, 0.8, u)
                field = field * np.clip(1.25 - carve * (noise - 0.3) * (0.3 + up), 0.0, 1.25)
                field = field * (0.55 + 0.5 * heat) * (0.35 + 0.65 * heat)
                if u > 0.42:
                    # cooling: the ball tears into tongues and specks that burn out
                    thr = (u - 0.42) * 1.45
                    fr_ = frag_n[off:off + h]
                    field = field * np.clip((fr_ - thr) * 5.0 + 0.15, 0.0, 1.0)
                idx = _tidy(_tones(field, POP_CUTS), iterations=1)
                idx = _cool_fire(idx, field, rim=1 if u < 0.3 else 2, rim_tone=2 if u < 0.2 else 1,
                                 detached_tone=1, caps=POP_CAPS if k >= 1 else POP_CAPS_YOUNG)
                keep = np.zeros(idx.shape, bool)
                embers.draw(idx, keep, (3, 2, 2, 1, 0), streak=1.0)
                core, body = _fire_layers(idx)
                core_frames.append(core)
                body_frames.append(body)
                if t in smoke_ticks:
                    top, tx = _top_of(idx)
                    side = smoke_ticks[t]
                    first = t == min(smoke_ticks)
                    # the first emitter leaves the crown, later ones a shoulder
                    # (heading out sideways, where the frame has room)
                    shoulder = 0.0 if first else r_max * 0.45
                    smoke.emit(t, tx + side * (gs.uniform(0.0, 1.5) + shoulder),
                               top - 3.0 - smoke.r0 + (0.0 if first else r_max * 0.3),
                               side * (gs.uniform(8.0, 30.0) if first else gs.uniform(34.0, 50.0)))
            fi += 1
        embers.step()
    smoke.fit(starts, n - 3, w, h)
    smoke_frames = [smoke.render(t, w, h, fade=max(0, i - (n - 4))) for i, t in enumerate(starts)]
    return core_frames, body_frames, smoke_frames


POP_W, POP_H = 40, 48
POP_ORIGIN = (20, 32)          # the spawn point: the flash and the young ball sit on it
POP_TICKS = [2] * 8            # 16 ticks: SotN's small explosion life
POP_TICKS_L = [2] * 12         # 24 ticks: the next size up (bat)


def build_fire_pop() -> None:
    """fire_pop: default (~14 px ball, skeleton pieces) and large (~22 px,
    the bat). Each has a smoke row and a body row of the same length (for
    the MIX smoke child and the opaque body child; the root, ADD, plays the
    core row and frees the effect when it ends)."""
    c = (float(POP_ORIGIN[0]), float(POP_ORIGIN[1]))
    core_s, body_s, smoke_s = _fireball_frames(POP_W, POP_H, c, POP_TICKS, r_max=7.0, lobes=POP_LOBES_S,
                                               seed=41, rise=(0.5, 1.0), n_embers=4,
                                               smoke_frames_at=(2,), puff_r=(1.5, 4.5))
    core_l, body_l, smoke_l = _fireball_frames(POP_W, POP_H, c, POP_TICKS_L, r_max=10.5, lobes=POP_LOBES_L,
                                               seed=53, rise=(0.4, 0.8), flash_r=3.6, ray_len=6.0,
                                               n_embers=6, smoke_frames_at=(2, 5), puff_r=(2.0, 6.0))
    sb = SheetBuilder("fire_pop", POP_W, POP_H, origin=POP_ORIGIN)
    sb.add("default", core_s, 60, False, ticks=POP_TICKS)
    sb.add("smoke", smoke_s, 60, False, ticks=POP_TICKS)
    sb.add("large", core_l, 60, False, ticks=POP_TICKS_L)
    sb.add("smoke_large", smoke_l, 60, False, ticks=POP_TICKS_L)
    sb.add("default_body", body_s, 60, False, ticks=POP_TICKS)
    sb.add("large_body", body_l, 60, False, ticks=POP_TICKS_L)
    sb.save()


# ---------------------------------------------------------------------------
# CANDLE BREAK (48x48 centred on the spawn point, candle root - 20): white
# pop -> 16 px fire ball over the candlestick (ADD) and wax / gilt shards
# flying in parabolas (MIX child layer)
# ---------------------------------------------------------------------------
BREAK_W = BREAK_H = 48
BREAK_TICKS = [2, 2, 2, 2, 2, 2, 3, 3, 3, 4]       # 25 ticks = 0.42 s
BREAK_BALL_C = (24.0, 28.0)                         # candle root - 16: the candlestick's middle


def _shard(idx: np.ndarray, mat: np.ndarray, cx: float, cy: float, w: float, h: float, ang: float,
           m: int, light: tuple[float, float] = (-0.6, -0.8)) -> None:
    """Rotated rectangle chip, 3 tones by facing (lit top-left edge, dark
    bottom-right), sampled at pixel centres."""
    H, W = idx.shape
    ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    r = math.hypot(w, h) / 2 + 1
    for yi in range(max(0, int(cy - r)), min(H, int(cy + r) + 1)):
        for xi in range(max(0, int(cx - r)), min(W, int(cx + r) + 1)):
            dx, dy = xi + 0.5 - cx, yi + 0.5 - cy
            u, v = dx * ca + dy * sa, -dx * sa + dy * ca
            if abs(u) <= w / 2 and abs(v) <= h / 2:
                s = (dx * light[0] + dy * light[1]) / max(0.5, r - 1)
                tone = 2 if s > 0.15 else (0 if s < -0.25 else 1)
                idx[yi, xi] = tone
                mat[yi, xi] = m


def _candle_break_frames(seed: int = 9) -> tuple[list[Image.Image], list[Image.Image], list[Image.Image]]:
    W, H = BREAK_W, BREAK_H
    c = (W / 2.0, H / 2.0)
    g = np.random.default_rng(seed + 3)
    # shards: [x, y, vx, vy, spin, w, h, angle, material 0 wax / 1 gilt]
    shards: list[list[float]] = []
    for k in range(7):
        side = -1 if k % 2 == 0 else 1
        gilt = 1 if k in (2, 5) else 0
        shards.append([c[0] + side * g.uniform(1.5, 3.5), c[1] + g.uniform(-4, 3),
                       side * g.uniform(0.45, 1.0), g.uniform(-2.1, -1.2), g.uniform(-20, 20),
                       g.uniform(2.2, 3.4) if not gilt else 2.0, g.uniform(1.6, 2.4) if not gilt else 1.5,
                       g.uniform(0, 180), gilt])
    core_frames, body_frames, _ = _fireball_frames(W, H, BREAK_BALL_C, BREAK_TICKS, r_max=8.0,
                                                   lobes=POP_LOBES_S, seed=seed, rise=(0.45, 0.9),
                                                   flash_r=3.2, ray_len=5.0, n_embers=6)
    starts = _starts(BREAK_TICKS)
    shard_frames: list[Image.Image] = []
    fi = 0
    for t in range(sum(BREAK_TICKS) + 1):
        if fi < len(starts) and t == starts[fi]:
            sidx = np.full((H, W), -1, np.int16)
            smat = np.full((H, W), -1, np.int16)
            if t > 0:
                for sh in shards:
                    _shard(sidx, smat, sh[0], sh[1], sh[5], sh[6], sh[7], int(sh[8]))
            img = np.zeros((H, W, 4), np.uint8)
            for m, lut in ((0, np.array([WAX[1], WAX[2], WAX[3]], np.uint8)),
                           (1, np.array([GOLD[1], GOLD[3], GOLD[4]], np.uint8))):
                sel = (smat == m) & (sidx >= 0)
                img[sel, :3] = lut[np.clip(sidx[sel], 0, 2)]
                img[sel, 3] = 255
            shard_frames.append(Image.fromarray(img, "RGBA"))
            fi += 1
        if t > 0:
            for sh in shards:
                sh[0] += sh[2]
                sh[1] += sh[3]
                sh[3] += 0.17
                sh[7] += sh[4]
    return core_frames, body_frames, shard_frames


def build_candle_break() -> None:
    core, body, shards = _candle_break_frames()
    sb = SheetBuilder("candle_break", BREAK_W, BREAK_H, origin=(BREAK_W // 2, BREAK_H // 2))
    sb.add("default", core, 60, False, ticks=BREAK_TICKS)
    sb.add("shards", shards, 60, False, ticks=BREAK_TICKS)
    sb.add("default_body", body, 60, False, ticks=BREAK_TICKS)
    sb.save()


# ---------------------------------------------------------------------------
# DUST: run-start / skid puff and landing dust (MIX, reduced alpha)
# ---------------------------------------------------------------------------
DUST_TICKS = [3, 3, 4, 4, 5]                        # 19 ticks


# One billow: (x offset along the kick, height of its centre above the floor
# at birth, birth radius, full radius, kick speed px/tick, extra lift px/tick)
DustBillow = tuple[float, float, float, float, float, float]
# run start / skid: a pale puff at the heel that swells, rolls back and lifts
DUST_BILLOWS: tuple[DustBillow, ...] = (
    (0.0, 2.0, 1.7, 5.0, 0.20, 0.14), (2.6, 3.0, 1.3, 3.4, 0.42, 0.34))
# landing: lower, wider billows (the 12 px frame), spreading to both sides
LAND_BILLOWS: tuple[DustBillow, ...] = (
    (0.0, 1.8, 1.5, 3.8, 0.26, 0.06), (2.8, 2.6, 1.2, 2.8, 0.52, 0.20))
DUST_GROW_TAU = 9.0           # ticks: the swell eases out (about 0.3 px/tick at first)
DUST_LIFE = 23.0              # ticks: a puff thins (its drawn radius shrinks) toward the end


def _dust_frames(w: int, h: int, sources: Sequence[tuple[float, float]], seed: int,
                 ticks: Sequence[int], billows: Sequence[DustBillow] = DUST_BILLOWS) -> list[Image.Image]:
    """Billows kicked from each (x, direction) source along the floor line:
    each is born small and pale at the foot, swells (easing out), rolls
    outward and lifts off the floor as it grows (so only the first two
    frames sit on the floor line), then crumbles into specks."""
    puffs = _Blobs(seed)
    specks = _Sparks(seed + 1)
    floor_y = h - 0.5
    decay = math.exp(-1.0 / DUST_GROW_TAU)
    for x, d in sources:
        for ox, oy, r0, r1, vx, lift in billows:
            dr0 = (r1 - r0) * (1.0 - decay)
            # the centre climbs with the swell (+ a little extra lift), so the
            # growing puff never ploughs into the floor
            puffs.emit(1, x + ox * d, floor_y - oy, sx=0.2, sy=0.2, vx=(vx * d, vx * d * 1.08),
                       vy=(-(dr0 + lift), -(dr0 + lift) * 0.92),
                       r=(r0, r0 * 1.04), dr=(dr0, dr0 * 1.05), heat=(1.0, 1.0),
                       cool=(0.012, 0.016), sway=(0.0, 0.0), drag=decay)
        specks.emit(2, x, floor_y - 2, sx=2, sy=1, vx=(0.6 * d, 1.1 * d), vy=(-0.7, -0.4),
                    life=(10, 16), acc=0.06)
    starts = _starts(ticks)
    out: list[Image.Image] = []
    fi = 0
    total = sum(ticks)
    for t in range(total + 1):
        if fi < len(starts) and t == starts[fi]:
            age = t / total
            img = _render_puffs(puffs, w, h, DUST, light=(-0.35, -0.85, 0.45),
                                floor_y=floor_y if fi < 2 else None)
            idx = _indices_of(img, DUST)
            keep = np.zeros(idx.shape, bool)
            specks.draw(idx, keep, (2, 1, 1, 0))
            out.append(_img(idx, DUST))
            fi += 1
        puffs.step()
        puffs.p["dr"] = puffs.p["dr"] * decay           # ease-out swell
        # full-bodied while it swells, thinning from about a third of its life
        puffs.p["heat"] = np.maximum(0.03, 1.0 - (puffs.p["age"] / DUST_LIFE) ** 2.5)
        specks.step()
    return out


def _indices_of(img: Image.Image, ramp: Sequence[RGB]) -> np.ndarray:
    """Back from an image painted in `ramp` to tone indices (-1 = clear)."""
    a = np.array(img.convert("RGBA"))
    idx = np.full(a.shape[:2], -1, np.int16)
    for k, col in enumerate(ramp):
        idx[(a[..., 3] > 0) & np.all(a[..., :3] == np.array(col, np.uint8), axis=-1)] = k
    return idx


def build_dust() -> None:
    sb = SheetBuilder("dust_puff", 32, 16, origin=(16, 15))
    # kicked backward (-x) from the back foot of a right-facing hero, which
    # stands on the origin: the puff starts at the heel and rolls back
    sb.add("default", _dust_frames(32, 16, [(21.0, -1.0)], 31, DUST_TICKS), 60, False, ticks=DUST_TICKS)
    sb.save()
    sb = SheetBuilder("land_dust", 48, 12, origin=(24, 11))
    sb.add("default", _dust_frames(48, 12, [(21.0, -1.0), (27.0, 1.0)], 37, DUST_TICKS, LAND_BILLOWS),
           60, False, ticks=DUST_TICKS)
    sb.save()


# ---------------------------------------------------------------------------
# DOUBLE-JUMP RING (32x16 centred, additive soul light under the feet)
# ---------------------------------------------------------------------------
RING_TICKS = [2, 3, 3, 4]


def _ellipse_ring(X: np.ndarray, Y: np.ndarray, c: tuple[float, float], rx: float, ry: float,
                  thick: float, inten: float, gaps: int = 0, gap_frac: float = 0.3,
                  rot_deg: float = 0.0) -> np.ndarray:
    """Ellipse outline with a screen-space thickness (first-order distance
    (q - 1) / |grad q|), optionally broken into arcs."""
    dx, dy = X - c[0], Y - c[1]
    q = np.sqrt((dx / rx) ** 2 + (dy / ry) ** 2) + 1e-9
    gx, gy = dx / (rx * rx * q), dy / (ry * ry * q)
    d = (q - 1.0) / np.maximum(np.hypot(gx, gy), 1e-6)
    inside = np.abs(d) <= thick / 2.0
    if gaps:
        ang = (np.degrees(np.arctan2(dy / ry, dx / rx)) - rot_deg) % 360.0
        inside &= ((ang / (360.0 / gaps)) % 1.0) < (1.0 - gap_frac)
    return np.where(inside, inten * (1.0 - 0.2 * np.clip((d + thick / 2.0) / max(thick, 1e-6), 0, 1)), 0.0)


def build_double_jump_ring() -> None:
    """A perspective ring of soul-light kicked out under the feet: the near
    (lower) arc is thick and bright, the far arc thin and dim."""
    W, H = 32, 16
    X, Y = _grid(W, H)
    c = (15.5, 7.5)
    cuts = (0.12, 0.3, 0.5, 0.7, 0.88)
    spec = [  # (rx, ry, near thickness, far thickness, intensity, gaps)
        (5.5, 1.8, 2.0, 1.0, 1.0, 0),
        (9.0, 2.8, 2.0, 1.0, 0.92, 0),
        (12.0, 3.6, 1.6, 1.0, 0.72, 8),
        (14.0, 4.2, 1.0, 1.0, 0.46, 8),
    ]
    frames: list[Image.Image] = []
    for k, (rx, ry, th_n, th_f, it, gaps) in enumerate(spec):
        near = _ellipse_ring(X, Y, c, rx, ry, th_n, it, gaps=gaps, gap_frac=0.28, rot_deg=10)
        far = _ellipse_ring(X, Y, c, rx, ry, th_f, it * 0.6, gaps=gaps, gap_frac=0.5, rot_deg=10)
        f = np.where(Y >= c[1], near, far)
        if k == 0:
            # the push-off flash: a bright horizontal bar through the ring
            bar = np.where((np.abs(Y - c[1]) < 1.0) & (np.abs(X - c[0]) < 7.5),
                           1.0 - np.abs(X - c[0]) / 12.0, 0.0)
            f = np.maximum(f, bar)
        idx = _tidy(_tones(f, cuts), iterations=0, fill_holes=False)
        frames.append(_img(idx, SOUL))
    sb = SheetBuilder("double_jump_ring", W, H, origin=(16, 8))
    sb.add("default", frames, 60, False, ticks=RING_TICKS)
    sb.save()


# ---------------------------------------------------------------------------
# PICKUP SPARKLE (9x9 centred, additive 1 px star glint)
# ---------------------------------------------------------------------------
SPARKLE_RAMP: list[RGB] = [FIRE[2], FIRE[3], FIRE[4], FIRE[5]]
SPARKLE = [
    [".........",
     ".........",
     ".........",
     "....1....",
     "...131...",
     "....1....",
     ".........",
     ".........",
     "........."],
    [".........",
     "....0....",
     "....1....",
     "..0.2.0..",
     "0123332100"[:9],
     "..0.2.0..",
     "....1....",
     "....0....",
     "........."],
    [".........",
     ".........",
     "....0....",
     "...0.0...",
     "..0.2.0..",
     "...0.0...",
     "....0....",
     ".........",
     "........."],
]


def build_pickup_sparkle() -> None:
    frames: list[Image.Image] = []
    for tpl in SPARKLE:
        idx = np.full((9, 9), -1, np.int16)
        for y, row in enumerate(tpl):
            for x, ch in enumerate(row):
                if ch.isdigit():
                    idx[y, x] = int(ch)
        frames.append(_img(idx, SPARKLE_RAMP))
    sb = SheetBuilder("pickup_sparkle", 9, 9, origin=(4, 4))
    sb.add("default", frames, 60, False, ticks=[3, 4, 4])
    sb.save()


# ---------------------------------------------------------------------------
# DEATH MIST (player): body breaks into rising crimson mist (MIX): clots
# first, then thinning motes and wisps, with a few crimson embers (ADD
# child layer)
# ---------------------------------------------------------------------------
MIST_W, MIST_H = 48, 96
MIST_TICKS = [4] * 16                                # 64 ticks


def _death_mist_frames(seed: int = 17) -> tuple[list[Image.Image], list[Image.Image]]:
    W, H = MIST_W, MIST_H
    g = np.random.default_rng(seed)
    feet = H - 1
    # 46 motes seeded inside the fallen/kneeling body, released bottom-up
    # over the first ~26 ticks so the body evaporates upward. Each starts as
    # a 2x2 bright clot, thins to a 1x2 wisp, then a single dim pixel.
    n = 46
    sx = W / 2 + g.normal(0, 4.5, n).clip(-12, 12)
    sy = feet - g.uniform(1, 30, n)
    release = ((feet - sy) / 30.0 * 18 + g.uniform(0, 8, n)).astype(int)
    speed = g.uniform(0.3, 0.8, n)
    amp = g.uniform(1.0, 3.0, n)
    per = g.uniform(40, 70, n)
    ph = g.uniform(0, math.tau, n)
    life = g.uniform(34, 60, n)
    em = _Sparks(seed + 1)
    # 14 clots of mist (2x2 / 3x2, CRIMSON C4/C5 with a velvet sheen on the
    # lit top-left pixel) lift off the body over the first 24 ticks: the
    # mass that reads before the motes thin out into wisps
    gc = np.random.default_rng(seed + 2)
    nc = 14
    c_birth = np.sort(22.0 * gc.uniform(0, 1, nc) ** 1.5)     # front-loaded: mass from tick 0
    c_x = W / 2 + gc.normal(0, 5.0, nc).clip(-13, 13)
    c_y = feet - gc.uniform(3, 26, nc)
    c_w = gc.choice([2, 3], nc, p=[0.45, 0.55])
    c_v = gc.uniform(0.4, 0.8, nc)
    c_amp = gc.uniform(1.0, 2.0, nc)
    c_per = gc.uniform(34, 56, nc)
    c_ph = gc.uniform(0, math.tau, nc)
    c_life = gc.uniform(26, 38, nc)
    starts = _starts(MIST_TICKS)
    mist_frames: list[Image.Image] = []
    ember_frames: list[Image.Image] = []
    fi = 0
    for t in range(sum(MIST_TICKS) + 1):
        if t % 5 == 0 and t < 40:
            em.emit(2, W / 2, feet - 12, sx=8, sy=11, vx=(-0.25, 0.25), vy=(-1.3, -0.6),
                    life=(14, 26), sway=(0.6, 1.4))
        if fi < len(starts) and t == starts[fi]:
            idx = np.full((H, W), -1, np.int16)
            for i in range(nc):
                age = t - c_birth[i]
                if age < 0 or age >= c_life[i]:
                    continue
                k = age / c_life[i]
                x = c_x[i] + c_amp[i] * math.sin(c_ph[i] + age * math.tau / c_per[i])
                y = c_y[i] - c_v[i] * age
                if k < 0.5:            # full clot: sheen, C5, C4 below
                    tpl = ((4, 3, 3), (3, 2, 2)) if c_w[i] == 3 else ((4, 3), (3, 2))
                elif k < 0.78:         # thinning: one tone down, a pixel narrower
                    tpl = ((3, 2), (2, 1)) if c_w[i] == 3 else ((3, 2), (2, -1))
                else:                  # breaking into a wisp
                    tpl = ((2, 1),) if c_w[i] == 3 else ((1,),)
                xi, yi = int(math.floor(x)), int(math.floor(y))
                for oy, row in enumerate(tpl):
                    for ox, tt in enumerate(row):
                        if tt >= 0 and 0 <= xi + ox < W and 0 <= yi + oy < H:
                            idx[yi + oy, xi + ox] = max(idx[yi + oy, xi + ox], tt)
            for i in range(n):
                age = t - release[i]
                if age < 0:
                    # not yet released: a mote smouldering in the body
                    tone, shape = (1 if (i + t // 4) % 3 else 2), ((0, 0),)
                    x, y = sx[i], sy[i]
                elif age < life[i]:
                    k = age / life[i]
                    if k < 0.25:
                        tone, shape = 4, ((0, 0), (1, 0), (0, 1), (1, 1))
                    elif k < 0.55:
                        tone, shape = 3, ((0, 0), (0, 1))
                    elif k < 0.8:
                        tone, shape = 2, ((0, 0),)
                    else:
                        tone, shape = 0, ((0, 0),)
                    x = sx[i] + amp[i] * math.sin(ph[i] + age * math.tau / per[i])
                    y = sy[i] - speed[i] * age
                else:
                    continue
                xi, yi = int(math.floor(x)), int(math.floor(y))
                for ox, oy in shape:
                    tt = tone - (1 if oy or ox else 0) if len(shape) > 1 else tone
                    if 0 <= xi + ox < W and 0 <= yi + oy < H:
                        idx[yi + oy, xi + ox] = max(idx[yi + oy, xi + ox], tt)
            mist_frames.append(_img(idx, MIST))
            eidx = np.full((H, W), -1, np.int16)
            ek = np.zeros((H, W), bool)
            em.draw(eidx, ek, (4, 3, 2, 1, 0), streak=0.9)
            ember_frames.append(_img(eidx, EMBER))
            fi += 1
        em.step()
    return mist_frames, ember_frames


def build_death_mist() -> None:
    mist, embers = _death_mist_frames()
    sb = SheetBuilder("death_mist", MIST_W, MIST_H, origin=(MIST_W // 2, MIST_H - 1))
    sb.add("default", mist, 60, False, ticks=MIST_TICKS)
    sb.add("embers", embers, 60, False, ticks=MIST_TICKS)
    sb.save()


def build() -> None:
    build_hit_spark()
    build_death_flame()
    build_fire_pop()
    build_candle_break()
    build_dust()
    build_double_jump_ring()
    build_pickup_sparkle()
    build_death_mist()


if __name__ == "__main__":
    build()
