"""
Vesper rig: pose model, IK skeleton, run gait and secondary motion.

Architecture (from prototype C, with prototype A's exact run foot-lock):

- `Pose` is a handful of numbers: pelvis, lean, chest yaw, breath, hand and
  foot *targets* (not joint angles), weapon state and the world velocity
  that drives the followers. `lerp_pose()` blends any two poses field by
  field, `keyed()` turns a key list into per-frame poses, so a one-shot
  animation is a short table of keys plus its 60 Hz tick list.
- `solve()` builds the skeleton: an FK spine and head, analytic 2-bone IK for
  all four limbs (with a <= 7 % cartoon stretch instead of floating feet),
  rigid feet that pivot on the heel (toe up) or the ball (toe down) so a
  planted contact point never skates, and every joint snapped to 0.5 px
  so in-betweens cannot boil.
- `run_pose(tick)` is a parametric run on the 40-tick, 16-frame loop: each
  planted contact point moves back exactly run_speed * ticks / 60 px per
  frame (105 px/s = 1.75 px/tick -> 5.25 px on 3-tick frames, 3.5 px on
  2-tick frames).
- Followers (cape edges, capelet, ponytail, ribbon tails, coat tails) are
  verlet chains stepped once per 60 Hz tick (`simulate()`): anchors are
  interpolated through each frame's ticks, air drag is -world_velocity * k,
  a weak shape-matching spring keeps a designed drape, loops run 3 warm-up
  cycles and keep the 4th (seamless), one-shots start from the end state of
  the animation that precedes them in game.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, fields, is_dataclass, replace
from typing import Any, Callable, Sequence

import numpy as np

from hero_paint import CX, FLOOR_Y, HEADS, ClothArt, Pt, addp, dirv

# --------------------------------------------------------------------------
# Proportions (docs/art_style.md, measured up from the sole: ankle 3, knee 12.5,
# crotch 22.5, waist 27, chest 32, shoulder 36.5, chin 38.5, crown 45.5)
# --------------------------------------------------------------------------
LEN_THIGH, LEN_SHIN = 10.4, 9.8
LEN_UP, LEN_FORE, HAND_OFF = 7.4, 6.4, 1.6
LEN_TORSO = 14.0            # pelvis -> neck base
ANKLE_UP = 3.4              # ankle above the sole
STAND_Y = FLOOR_Y - ANKLE_UP   # flat-foot ankle height on the floor
IK_STRETCH = 1.07

RUN_SPEED = 105.0           # px/s, scripts/player/player.gd run_speed
RUN_V = RUN_SPEED / 60.0    # 1.75 px per tick
RUN_TICKS = [3, 2] * 8      # 16 frames, 40 ticks per cycle (= 70 px)
RUN_CYCLE = sum(RUN_TICKS)


def snap(p: Pt, q: float = 0.5) -> Pt:
    return (round(p[0] / q) * q, round(p[1] / q) * q)


def v_add(a: Pt, b: Pt) -> Pt:
    return (a[0] + b[0], a[1] + b[1])


def v_sub(a: Pt, b: Pt) -> Pt:
    return (a[0] - b[0], a[1] - b[1])


def rot2(v: Pt, deg: float) -> Pt:
    """Rotate clockwise on screen (y down) by `deg`."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c)


def ik2(root: Pt, target: Pt, l1: float, l2: float, bend: float, stretch: float = IK_STRETCH) -> tuple[Pt, Pt]:
    """Analytic 2-bone IK. bend=-1 puts the middle joint on the +x side of a
    downward limb (knees), +1 on the -x side (elbows). Returns (mid, end);
    when the target is out of reach the bones stretch up to `stretch`."""
    dx, dy = target[0] - root[0], target[1] - root[1]
    dist = math.hypot(dx, dy)
    k = min(max(dist / (l1 + l2), 1.0), stretch)
    l1, l2 = l1 * k, l2 * k
    dc = min(max(dist, abs(l1 - l2) + 1e-3), l1 + l2 - 1e-3)
    a = math.atan2(dy, dx)
    cb = (l1 * l1 + dc * dc - l2 * l2) / (2 * l1 * dc)
    a1 = a + bend * math.acos(max(-1.0, min(1.0, cb)))
    mid = (root[0] + l1 * math.cos(a1), root[1] + l1 * math.sin(a1))
    ea = math.atan2(target[1] - mid[1], target[0] - mid[0])
    end = (mid[0] + l2 * math.cos(ea), mid[1] + l2 * math.sin(ea))
    return mid, end


# Rigid riding-boot foot in ankle-local coords (+x toe, +y down, pitch + = toe down)
FOOT_POLY: tuple[Pt, ...] = ((-1.3, -0.6), (1.2, -0.6), (2.6, 1.0), (4.6, 1.8), (4.9, ANKLE_UP), (-1.5, ANKLE_UP))
HEEL: Pt = (-1.4, ANKLE_UP)
BALL: Pt = (3.4, ANKLE_UP)
TOE: Pt = (4.4, ANKLE_UP - 0.6)


def foot_ankle(flat: Pt, pitch: float, planted: bool) -> Pt:
    """Ankle position for a foot whose *flat* ankle position is `flat`.
    A planted foot pivots on its heel (toe up) or its ball (toe down), so the
    contact point stays exactly where the flat foot put it."""
    if not planted or pitch == 0.0:
        return flat
    piv = HEEL if pitch < 0 else BALL
    r = rot2(piv, pitch)
    return (flat[0] + piv[0] - r[0], flat[1] + piv[1] - r[1])


def foot_points(ank: Pt, pitch: float) -> list[Pt]:
    return [v_add(ank, rot2(p, pitch)) for p in FOOT_POLY]


def kneel_leg(hip: Pt, pitch: float) -> tuple[Pt, Pt]:
    """Kneeling leg: the knee rests on the floor ahead of the hip, the shin
    runs back along the floor and the toes are tucked under (pitch toe-down)
    with the lowest foot point exactly on the floor. Returns (knee, ankle)."""
    yk = FLOOR_Y - 2.0
    dy = yk - hip[1]
    dx = math.sqrt(max(LEN_THIGH * LEN_THIGH - dy * dy, 0.0))
    knee = (hip[0] + dx, yk)
    low = max(rot2(q, pitch)[1] for q in FOOT_POLY)
    ay = FLOOR_Y - low
    rise = max(-LEN_SHIN + 0.1, min(LEN_SHIN - 0.1, knee[1] - ay))
    ax = knee[0] - math.sqrt(LEN_SHIN * LEN_SHIN - rise * rise)
    return knee, (ax, ay)


# --------------------------------------------------------------------------
# Pose
# --------------------------------------------------------------------------
@dataclass
class Pose:
    pelvis: Pt = (63.5, 51.5)
    lean: float = 2.0              # torso lean, + forward (deg)
    yaw: float = 35.0              # chest opening toward the camera (35 = 3/4, < 0 turned away)
    tilt: float = 1.0              # contrapposto: + raises the near hip, lowers the near shoulder
    breath: float = 0.0            # chest/shoulder/head rise (px)
    head: str = "n"
    head_d: Pt = (0.0, 0.0)
    head_lean: float = 0.0         # head offset along the torso's forward axis (px)
    foot_n: Pt = (58.5, STAND_Y)   # near (camera-side, screen-left) foot: flat-ankle target
    pitch_n: float = 0.0
    plant_n: bool = True
    foot_f: Pt = (69.0, STAND_Y)   # far foot
    pitch_f: float = 0.0
    plant_f: bool = True
    knee_n: float = -1.0
    knee_f: float = -1.0
    kneel_n: bool = False          # near knee on the floor, shin back along it, toes tucked
    hand_n: Pt = (61.0, 54.5)      # near (sword) hand target
    hand_f: Pt = (68.5, 53.5)
    elbow_n: float = 1.0
    elbow_f: float = 1.0
    grip_n: str = "relax"
    grip_f: str = "relax"
    arm_over: bool = False         # near arm drawn over the capelet (attacks)
    far_arm_front: bool = False    # far arm drawn over the torso (throw, reach)
    weapon: str = "none"           # "none" | "sabre" | "whip"
    blade: float = 80.0            # sabre screen angle (0 forward, -90 up)
    blade_behind: bool = False
    whip: tuple[Pt, ...] = ()
    spark: int = 0
    smear: float = 0.0             # slash smear strength (path = previous frame's tip -> this tip)
    smear_sweep: float = 0.0       # > 0: the smear's tail starts this many degrees behind this frame's tip
    vel: Pt = (0.0, 0.0)           # world velocity (px/tick): drives drag on every follower
    airborne: bool = False
    cape: ClothArt = field(default_factory=ClothArt)
    drape: dict[str, tuple[float, ...]] = field(default_factory=dict)   # rest-shape overrides
    stiff: dict[str, float] = field(default_factory=dict)               # shape-pull multipliers
    floor: bool = True             # followers collide with the floor
    collide: bool = True           # the cape's trailing edge collides with the torso (off when it must stream forward)
    crouch: float = 0.0            # 0..1, cape pooling / coat-skirt spread
    rot: float = 0.0               # whole-figure rotation (somersault), clockwise deg
    rot_c: Pt = (64.0, 50.0)
    drape_spin: bool = True        # the followers' rest drapes turn with `rot` (False: they lag a spin)


def lerp_pose(a: Pose, b: Pose, t: float) -> Pose:
    """Blend two poses: numbers and same-length tuples lerp, nested
    dataclasses blend field by field, everything else snaps at t >= 0.5."""
    return _lerp_any(a, b, t)  # type: ignore[no-any-return]


def _lerp_any(x: Any, y: Any, t: float) -> Any:
    if is_dataclass(x) and type(x) is type(y):
        return replace(x, **{f.name: _lerp_any(getattr(x, f.name), getattr(y, f.name), t) for f in fields(x)})
    if isinstance(x, bool) or isinstance(y, bool):
        return y if t >= 0.5 else x
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        return x + (y - x) * t
    if isinstance(x, tuple) and isinstance(y, tuple) and len(x) == len(y) and len(x) > 0:
        return tuple(_lerp_any(p, q, t) for p, q in zip(x, y))
    return y if t >= 0.5 else x


def keyed(keys: Sequence[tuple[Pose, Pose | None, float]]) -> list[Pose]:
    """[(pose_a, pose_b or None, t)] -> per-frame poses (a key or an in-between)."""
    return [lerp_pose(a, b, t) if b is not None else a for a, b, t in keys]


# --------------------------------------------------------------------------
# Skeleton
# --------------------------------------------------------------------------
@dataclass
class Rig:
    p: Pose
    J: dict[str, Pt]
    up: Pt
    rt: Pt
    head_xy: tuple[int, int]       # top-left pixel of the head stamp (rotated stamp when rot != 0)
    head_c: Pt                     # head stamp centre (rotated with the figure)
    head_k: int = 0                # quarter turns (clockwise) applied to the head stamp

    def T(self, o: str | Pt, a: float, b: float) -> Pt:
        """Torso-local -> screen: `a` along the torso's right, `b` along up."""
        oo = self.J[o] if isinstance(o, str) else o
        return (oo[0] + self.rt[0] * a + self.up[0] * b, oo[1] + self.rt[1] * a + self.up[1] * b)


def solve(p: Pose) -> Rig:
    px, py = p.pelvis
    ln = math.radians(p.lean)
    up = (math.sin(ln), -math.cos(ln))
    rt = (-up[1], up[0])
    ys = math.sin(math.radians(p.yaw)) / math.sin(math.radians(35.0))
    J: dict[str, Pt] = {}
    pel = (px, py)
    J["pelvis"] = pel

    def T(o: Pt, a: float, b: float) -> Pt:
        return (o[0] + rt[0] * a + up[0] * b, o[1] + rt[1] * a + up[1] * b)

    J["waist"] = T(pel, 0.0, 4.2)
    neck = T(pel, 0.0, LEN_TORSO + p.breath)
    J["neck"] = neck
    J["chest"] = T(pel, 0.0, 9.5 + 0.7 * p.breath)
    # shoulders on a yawing shoulder line: 3/4 opens them, turning away swaps
    J["shN"] = T(neck, -(3.3 * ys + 0.4), -1.7 + 0.5 * p.tilt)
    J["shF"] = T(neck, 3.3 * ys - 0.2, -1.5 - 0.5 * p.tilt)
    J["hipN"] = T(pel, -(1.3 + 0.6 * ys), 0.5 * p.tilt)
    J["hipF"] = T(pel, 1.1 + 0.6 * ys, -0.5 * p.tilt)
    for s, foot, pitch, plant, kb in (("N", p.foot_n, p.pitch_n, p.plant_n, p.knee_n),
                                      ("F", p.foot_f, p.pitch_f, p.plant_f, p.knee_f)):
        if s == "N" and p.kneel_n:
            J["kneeN"], J["ankN"] = kneel_leg(J["hipN"], pitch)
            continue
        ank_t = foot_ankle(foot, pitch, plant)
        knee, ank = ik2(J["hip" + s], ank_t, LEN_THIGH, LEN_SHIN, kb)
        J["knee" + s], J["ank" + s] = knee, ank
    for s, hand, eb in (("N", p.hand_n, p.elbow_n), ("F", p.hand_f, p.elbow_f)):
        el, hd = ik2(J["sh" + s], hand, LEN_UP, LEN_FORE + HAND_OFF, eb)
        J["elb" + s], J["hand" + s] = el, hd
        k = LEN_FORE / (LEN_FORE + HAND_OFF)
        J["wri" + s] = (el[0] + (hd[0] - el[0]) * k, el[1] + (hd[1] - el[1]) * k)
    # head: rides the neck (breath included), offset forward by head_lean
    hs = HEADS[p.head]
    hn = T(neck, p.head_lean, 0.0)
    hx = int(math.floor(hn[0] + p.head_d[0] + 0.5)) - hs.neck[0]
    hy = int(math.floor(hn[1] - 0.5 + p.head_d[1] + 0.5)) - hs.neck[1]
    h0, w0 = len(hs.rows), len(hs.rows[0])
    head_c = (hx + w0 / 2.0, hy + h0 / 2.0)
    hk = 0
    if p.rot:
        c = p.rot_c
        for k2 in list(J):
            J[k2] = v_add(c, rot2(v_sub(J[k2], c), p.rot))
        up, rt = rot2(up, p.rot), rot2(rt, p.rot)
        # the head stamp turns in quarter turns; it is anchored by its own (rotated) neck
        # pixel on the rotated neck point, so the face never detaches from the neck
        hk = int(round(p.rot / 90.0)) % 4
        neck_px = v_add(c, rot2(v_sub((hx + hs.neck[0], hy + hs.neck[1]), c), p.rot))
        nc, nr = rot_index(hs.neck[0], hs.neck[1], h0, w0, hk)
        hx, hy = int(math.floor(neck_px[0] + 0.5 - nc)), int(math.floor(neck_px[1] + 0.5 - nr))
        wr, hr = (h0, w0) if hk % 2 else (w0, h0)
        head_c = (hx + wr / 2.0, hy + hr / 2.0)
    planted = {"ankN": p.plant_n and not p.rot and not p.kneel_n, "ankF": p.plant_f and not p.rot}
    for k2 in list(J):
        if not planted.get(k2, False):
            J[k2] = snap(J[k2])
    return Rig(p, J, up, rt, (hx, hy), head_c, hk)


def rot_index(tx: float, ty: float, h: int, w: int, k: int) -> Pt:
    """Template point (col tx, row ty) of an h x w stamp after np.rot90(stamp, -k)
    (k clockwise quarter turns), as (col, row) in the rotated stamp."""
    k %= 4
    if k == 1:
        return (h - 1 - ty, tx)
    if k == 2:
        return (w - 1 - tx, h - 1 - ty)
    if k == 3:
        return (ty, w - 1 - tx)
    return (tx, ty)


def head_point(r: Rig, tx: float, ty: float) -> Pt:
    """Screen position of a head-template point (rotation included)."""
    hs = HEADS[r.p.head]
    c, rr = rot_index(tx, ty, len(hs.rows), len(hs.rows[0]), r.head_k)
    return (r.head_xy[0] + c, r.head_xy[1] + rr)


# --------------------------------------------------------------------------
# Secondary motion: verlet chains stepped per 60 Hz tick
# --------------------------------------------------------------------------
@dataclass
class ChainSpec:
    n: int                       # points including the anchor
    length: float
    rest: tuple[float, ...]      # segment angles from straight down (+ toward facing) at rest
    grav: float = 0.25
    damp: float = 0.86
    stiff: float = 0.08          # shape-matching pull toward the rest drape
    wind_k: float = 0.10         # drag: acc = -world_velocity * wind_k
    floor: bool = False
    torso: bool = False          # collide with the torso capsule (stays on the back side)


CHAINS: dict[str, ChainSpec] = {
    # cape edges: cape0 = inner edge (fastened at the front shoulder, falls behind the
    # body), cape1 = trailing edge behind the near shoulder (lighter: lifts first)
    "cape0": ChainSpec(8, 26.0, (-3, -4, -5, -6, -6, -7, -7), 0.25, 0.85, 0.07, 0.09, True),
    "cape1": ChainSpec(8, 24.5, (-12, -16, -20, -23, -25, -27, -28), 0.24, 0.86, 0.06, 0.12, True, True),
    "capelet": ChainSpec(3, 6.0, (-6, -4), 0.22, 0.78, 0.30, 0.05),
    # ponytail at rest: leaves the nape at ~30 deg below horizontal (a wedge of air over
    # the capelet's back contour at the root, so hair and capelet never fuse into a hood),
    # then falls with gravity to hang ~60 deg below horizontal, its tip ~5-6 px behind the
    # nape (never a horizontal spike). Loose (stiff 0.20) so it lags the head as 2nd-order
    # secondary motion; the run / idle sway is designed on top of it in hero.py
    "pony": ChainSpec(5, 11.5, (-58, -36, -18, -8), 0.20, 0.86, 0.20, 0.10),
    # ribbon tails: 3rd-order, looser still, hanging along the ponytail's underside
    "rib0": ChainSpec(3, 4.4, (-40, -26), 0.16, 0.86, 0.12, 0.14),
    "rib1": ChainSpec(3, 3.6, (-22, -10), 0.16, 0.86, 0.12, 0.14),
    "tailN": ChainSpec(3, 11.0, (-8, -5), 0.22, 0.82, 0.28, 0.07, True),
    "tailF": ChainSpec(3, 10.0, (-4, -2), 0.22, 0.82, 0.28, 0.07, True),
}


def rest_shape(angles: Sequence[float], length: float, rot: float = 0.0) -> np.ndarray:
    seg = length / max(1, len(angles))
    pts = [(0.0, 0.0)]
    for a in angles:
        d = rot2(dirv(a), rot)
        pts.append((pts[-1][0] + d[0] * seg, pts[-1][1] + d[1] * seg))
    return np.array(pts, float)


RIBBON_ON_PONY = 2.2           # the bow sits this far down the ponytail's first segment


def pony_knot(r: Rig, nape: Pt) -> Pt:
    """Ribbon knot: on the ponytail's first segment (its rest direction for this
    pose), RIBBON_ON_PONY px out of the nape, so the bow is tied round the tail
    where it leaves the head and reads on the silhouette edge, clear of the collar."""
    spec = CHAINS["pony"]
    rest = r.p.drape.get("pony", spec.rest)
    rot = r.p.rot if r.p.drape_spin else 0.0
    d = rot2(dirv(rest[0]), rot)
    return (nape[0] + d[0] * RIBBON_ON_PONY, nape[1] + d[1] * RIBBON_ON_PONY)


def anchors(r: Rig) -> dict[str, Pt]:
    """Root point of every follower chain for a solved pose."""
    hs = HEADS[r.p.head]
    nape = head_point(r, hs.nape[0], hs.nape[1])
    knot = pony_knot(r, nape)
    return {
        "cape0": r.T("neck", 1.6, -2.4),
        "cape1": r.T("shN", -2.4, -0.2),
        "capelet": r.T("shN", -1.2, 1.4),
        "pony": nape,
        "rib0": (knot[0] - 0.6, knot[1]),
        "rib1": (knot[0] + 0.4, knot[1]),
        "tailN": r.T("pelvis", -3.6, 1.8),
        "tailF": r.T("pelvis", -0.9, 1.6),
    }


class Chain:
    def __init__(self, spec: ChainSpec) -> None:
        self.spec = spec
        self.rest = rest_shape(spec.rest, spec.length)
        self.seg = np.hypot(*np.diff(self.rest, axis=0).T)
        self.p: np.ndarray | None = None
        self.pp: np.ndarray | None = None

    def reset(self, anchor: Pt, rest: np.ndarray) -> None:
        self.p = np.asarray(anchor, float) + rest
        self.pp = self.p.copy()

    def step(self, anchor: Pt, vel: Pt, grav_scale: float, rest: np.ndarray, stiff_scale: float,
             floor_y: float | None, accel: Pt = (0.0, 0.0),
             torso: tuple[Pt, Pt, Pt, float] | None = None) -> None:
        """One 60 Hz tick. `vel` is the body's world velocity (air drag) and
        `accel` its world acceleration (in the sprite's frame the cloth feels
        the opposite: it swings forward when the body brakes)."""
        sp = self.spec
        if self.p is None or self.pp is None:
            self.reset(anchor, rest)
        assert self.p is not None and self.pp is not None
        a = np.asarray(anchor, float)
        v = (self.p - self.pp) * sp.damp
        self.pp = self.p.copy()
        acc = np.array([0.0, sp.grav * grav_scale]) - np.asarray(vel, float) * sp.wind_k \
            - np.asarray(accel, float)
        p = self.p + v + acc
        n = len(rest)
        w = np.linspace(1.0, 0.4, n)[:, None]
        p += sp.stiff * stiff_scale * w * ((a + rest) - p)
        p[0] = a
        for _ in range(2):
            for i in range(1, n):
                d = p[i] - p[i - 1]
                ln = float(np.hypot(*d)) + 1e-9
                p[i] = p[i - 1] + d / ln * self.seg[i - 1]
            if floor_y is not None:
                p[:, 1] = np.minimum(p[:, 1], floor_y)
            if torso is not None:
                # body back-line: a point that entered the torso capsule is put back
                # on its back surface (prevents the trailing edge cutting through the
                # body on fast reversals and turns)
                (ax_, ay_), (bx_, by_), (rx_, ry_), rad = torso
                vx, vy = bx_ - ax_, by_ - ay_
                ll = vx * vx + vy * vy + 1e-9
                t = np.clip(((p[1:, 0] - ax_) * vx + (p[1:, 1] - ay_) * vy) / ll, 0, 1)
                cx_, cy_ = ax_ + vx * t, ay_ + vy * t
                inside = np.hypot(p[1:, 0] - cx_, p[1:, 1] - cy_) < rad
                p[1:, 0] = np.where(inside, cx_ - rx_ * rad, p[1:, 0])
                p[1:, 1] = np.where(inside, cy_ - ry_ * rad, p[1:, 1])
        self.p = p


@dataclass
class SimFrame:
    chains: dict[str, np.ndarray]
    clock: int                     # tick at which this frame starts showing


class Sim:
    """All follower chains of the figure, stepped tick by tick."""

    def __init__(self) -> None:
        self.chains = {k: Chain(s) for k, s in CHAINS.items()}
        self.clock = 0

    def rest_for(self, name: str, p: Pose) -> np.ndarray:
        spec = CHAINS[name]
        rot = p.rot if p.drape_spin else 0.0
        if name in p.drape:
            return rest_shape(p.drape[name], spec.length, rot)
        return rest_shape(spec.rest, spec.length, rot)

    def settle(self, p: Pose, ticks: int = 160) -> None:
        r = solve(p)
        an = anchors(r)
        for k, c in self.chains.items():
            c.reset(an[k], self.rest_for(k, p))
        for _ in range(ticks):
            self._tick(p, an)

    def _tick(self, p: Pose, an: dict[str, Pt], accel: Pt = (0.0, 0.0)) -> None:
        g = 0.3 if p.airborne else 1.0
        torso: tuple[Pt, Pt, Pt, float] | None = None
        if p.collide and not p.rot and abs(p.lean) < 40:
            rg = solve(p)
            torso = (rg.J["pelvis"], rg.J["neck"], rg.rt, 3.4)
        for k, c in self.chains.items():
            fl = FLOOR_Y if (c.spec.floor and p.floor) else None
            c.step(an[k], p.vel, g, self.rest_for(k, p), p.stiff.get(k, 1.0), fl, accel,
                   torso if c.spec.torso else None)
        self.clock += 1

    def copy(self) -> Sim:
        out = Sim()
        for k, c in self.chains.items():
            if c.p is not None and c.pp is not None:
                out.chains[k].p, out.chains[k].pp = c.p.copy(), c.pp.copy()
        out.clock = self.clock
        return out

    def snapshot(self) -> SimFrame:
        return SimFrame({k: (c.p.copy() if c.p is not None else np.zeros((1, 2))) for k, c in self.chains.items()},
                        self.clock)

    def play_frame(self, p0: Pose, p1: Pose, ticks: int) -> None:
        a0, a1 = anchors(solve(p0)), anchors(solve(p1))
        acc = ((p1.vel[0] - p0.vel[0]) / ticks, (p1.vel[1] - p0.vel[1]) / ticks)
        for t in range(ticks):
            f = (t + 1) / ticks
            an = {k: (a0[k][0] + (a1[k][0] - a0[k][0]) * f, a0[k][1] + (a1[k][1] - a0[k][1]) * f) for k in a0}
            pv = lerp_pose(p0, p1, f) if p0 is not p1 else p0
            self._tick(pv, an, acc)


def simulate(poses: Sequence[Pose], ticks: Sequence[int], loop: bool, sim: Sim | None = None,
             warm_loops: int = 3, entry: Pose | None = None, entry_ticks: int = 2) -> tuple[list[SimFrame], Sim]:
    """Secondary motion for one animation. Loops: `warm_loops` full cycles
    first, then the recorded cycle (so the last frame flows into the first).
    One-shots: continue from `sim` (the end state of the animation that
    precedes this one in game; copied, never mutated) or settle on the first
    pose; `entry` (the preceding pose) plays a short blend into frame 0 so
    the impulse of the state change (jump launch, backdash push, hit) reaches
    the followers before the first recorded frame."""
    n = len(poses)
    if sim is None:
        sim = Sim()
        sim.settle(poses[0] if entry is None else entry)
    else:
        sim = sim.copy()
    if entry is not None and not loop:
        sim.play_frame(entry, poses[0], entry_ticks)
    sim.clock = 0

    def nxt(i: int) -> Pose:
        if loop:
            return poses[(i + 1) % n]
        return poses[min(i + 1, n - 1)]

    if loop:
        for _ in range(warm_loops):
            for i in range(n):
                sim.play_frame(poses[i], nxt(i), ticks[i])
        sim.clock = 0
    out: list[SimFrame] = []
    for i in range(n):
        out.append(sim.snapshot())
        sim.play_frame(poses[i], nxt(i), ticks[i])
    return out, sim


def mirror_sim(sim: Sim) -> Sim:
    """Mirror every chain about the body centre (for the turn animation:
    the cape keeps trailing toward the old facing for a few ticks)."""
    out = Sim()
    for k, c in sim.chains.items():
        if c.p is not None and c.pp is not None:
            out.chains[k].p = np.stack([2 * CX - c.p[:, 0], c.p[:, 1]], 1)
            out.chains[k].pp = np.stack([2 * CX - c.pp[:, 0], c.pp[:, 1]], 1)
    return out


# --------------------------------------------------------------------------
# Run gait (exact foot lock)
# --------------------------------------------------------------------------
# One foot's cycle, in ticks from its own heel strike (40-tick cycle):
#   stance 0..15 ticks: the ground contact is fixed in the world, so in the
#     sprite it moves back exactly RUN_V px per tick (heel strike 0-3 with the
#     heel as pivot, flat 3-8, heel-off 8-15 pivoting on the ball);
#   swing 15..40: Catmull-Rom ankle path with a high heel kick and a reach.
STANCE = 15
STRIKE_X = 10.6                  # flat-ankle x ahead of the hip at heel strike
_PITCH_STANCE = ((0, -16.0), (3, 0.0), (8, 0.0), (15, 46.0))
# swing keys: (tick, ankle dx from hip, ankle y, pitch)
_SWING = ((15, None, None, 46.0), (19, -14.5, 65.5, 66.0), (23, -11.0, 63.0, 60.0), (27, -5.0, 64.8, 38.0),
          (32, 3.0, 67.0, 10.0), (36, 9.5, 69.3, -8.0), (40, None, None, -16.0))


def _interp(keys: Sequence[tuple[float, float]], t: float) -> float:
    for (t0, v0), (t1, v1) in zip(keys[:-1], keys[1:]):
        if t0 <= t <= t1:
            return v0 + (v1 - v0) * (t - t0) / max(t1 - t0, 1e-9)
    return keys[-1][1]


def gait_foot(tau: float, hip_x: float) -> tuple[Pt, float, bool]:
    """(flat-ankle target, pitch, planted) for a foot `tau` ticks after its heel strike."""
    tau %= RUN_CYCLE
    if tau <= STANCE:
        x = hip_x + STRIKE_X - RUN_V * tau
        return (x, STAND_Y), _interp(_PITCH_STANCE, tau), True
    # swing: Catmull-Rom through the keys, endpoints = toe-off and next strike ankles
    x_off = hip_x + STRIKE_X - RUN_V * STANCE
    a_off = foot_ankle((x_off, STAND_Y), _PITCH_STANCE[-1][1], True)
    a_on = foot_ankle((hip_x + STRIKE_X, STAND_Y), _PITCH_STANCE[0][1], True)
    pts = []
    for tk, dx, y, pit in _SWING:
        if dx is None:
            a = a_off if tk == STANCE else a_on
            pts.append((float(tk), a[0], a[1], pit))
        else:
            pts.append((float(tk), hip_x + dx, float(y), pit))
    ext = [pts[0]] + pts + [pts[-1]]
    for i in range(1, len(ext) - 2):
        if ext[i][0] <= tau <= ext[i + 1][0]:
            p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
            t = (tau - p1[0]) / max(p2[0] - p1[0], 1e-9)
            vals = [0.5 * ((2 * b) + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t * t
                           + (-a + 3 * b - 3 * c + d) * t ** 3)
                    for a, b, c, d in zip(p0[1:], p1[1:], p2[1:], p3[1:])]
            return (vals[0], vals[1]), vals[2], False
    return a_on, -16.0, False


def run_bob(tick: float) -> float:
    """Integer pelvis bob: +1 (down) while loading, -1 (up) in flight."""
    q = tick % (RUN_CYCLE / 2)
    if 3 <= q < 10:
        return 1.0
    if q >= 15:
        return -1.0
    return 0.0


def run_pose(tick: float, art: Callable[[float], ClothArt] | None = None) -> Pose:
    """The run at `tick` of the 40-tick cycle (near foot strikes at tick 0)."""
    hip_x = 63.0
    bob = run_bob(tick)
    pel = (hip_x + 0.5, 52.4 + bob)
    fn, pn, gn = gait_foot(tick, hip_x - 0.8)
    ff, pf, gf = gait_foot(tick - RUN_CYCLE / 2, hip_x + 0.8)
    ph = 2 * math.pi * tick / RUN_CYCLE
    sw = math.cos(ph)                       # +1: near leg forward -> near arm back
    lean = 9.0
    ln = math.radians(lean)
    sh_y = pel[1] - LEN_TORSO * math.cos(ln) + 1.6
    sh_x = pel[0] + LEN_TORSO * math.sin(ln)
    hand_n = (sh_x - 3.0 - 6.5 * sw, sh_y + 11.0 - 2.4 * abs(sw) + 1.2 * sw)
    hand_f = (sh_x + 3.5 + 6.5 * sw, sh_y + 10.5 - 2.4 * abs(sw) - 1.2 * sw)
    cape = art(tick) if art is not None else ClothArt()
    return Pose(pelvis=pel, lean=lean, yaw=26.0, tilt=0.0, head="fwd", head_lean=0.6,
                foot_n=fn, pitch_n=pn, plant_n=gn, foot_f=ff, pitch_f=pf, plant_f=gf,
                hand_n=hand_n, hand_f=hand_f, elbow_n=1.0, elbow_f=1.0, grip_n="fist", grip_f="fist",
                vel=(RUN_V, 0.0), cape=cape)


def planted_contacts(p: Pose) -> list[Pt]:
    """World-fixed reference point of each planted foot (the heel of the flat
    foot): while a foot is planted it rolls heel -> flat -> ball about points
    that are all fixed on the ground, so this point must move back exactly
    run_speed * ticks / 60 per frame (the foot-lock check)."""
    out = []
    for foot, plant in ((p.foot_n, p.plant_n), (p.foot_f, p.plant_f)):
        if plant:
            out.append(v_add(foot, HEEL))
    return out


__all__ = ["Pose", "Rig", "solve", "lerp_pose", "keyed", "Sim", "SimFrame", "simulate", "mirror_sim",
           "run_pose", "gait_foot", "planted_contacts", "anchors", "head_point", "rot_index", "addp", "RUN_TICKS",
           "RUN_V", "STAND_Y",
           "ANKLE_UP", "foot_points", "CHAINS"]
