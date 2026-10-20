"""
Enemies: the skeleton, the bat and the bone the skeleton throws.

SotN-style pass. Everything is drawn at 1x into a material-aware `Indexed`
canvas (common.py), so every pixel is a (material, ramp tone) pair from the
shared `RAMPS`. Each drawing is finished with interior contours (a 1 px dark
line where a front part crosses a back part) and a sel-out outline (each
material's darkest tone, its second-darkest on edges facing `LIGHT`). Bone
outlines are therefore the warm (44, 34, 34), never violet-black.

- Long bones are "doubled" 1x strokes: the Bresenham line is the lit side
  and a parallel line on the side away from the light is the shadow side, so
  a 2 px shaft always shows a terminator. Joints are small lit spheres
  (knobby epiphyses). Skull, ribcage, pelvis and feet are hand-authored 1x
  templates. Far-side limbs are thinner and one ramp step darker on the lit
  side (lit 3 / shade 2), so they read as bone, not as a dark mass.
- The bat is a dark violet mass (shared RAMPS["bat"], body median Y ~33)
  over a light lavender-bone wing armature, with red eyes and a cool 1 px
  rim (BAT_RIM) swapped in for the sel-out outline on the lit upper-front
  contour (ears, crown, near wing's leading edge), so it separates from both
  the dark upper walls and the mid-value wainscot band.
- Animation is authored in 60 Hz ticks (SheetBuilder `ticks=`) with the
  timings in docs/art_style.md: skeleton walk 6,4,4,6,5,5 (long holds on the
  contacts); bat flap 4,1,1,1,1,1,4,2,2,2,1,2,2 from 8 drawings.
- Feet never skate: the skeleton's planted foot moves back by
  walk_speed * ticks / 60 px per frame (skeleton.gd walk_speed 26 px/s).
- The skeleton stands 40-41 px (crown outline at world y -41) so the skull
  sits close to the unchanged 16x38 hurtbox; the throw's release frame
  draws an open, empty hand in front of the face where skeleton.gd spawns
  the bone (bone_spawn_offset (6, -34)).

Outputs (drawn facing right; the scenes flip them):
- skeleton.png/.json + skeleton_frames.tres: 64x64 frames, origin (32, 59)
  = feet. Lowest opaque row 59 -> world y -1 with the scene offset (0, -28).
  walk 6f loop, attack 6f once (bone released on frame ATTACK_RELEASE_FRAME),
  hurt 2f once, idle 2f loop.
- skeleton_parts.png/.json + skeleton_parts_frames.tres: 24x24 cells, one
  single-frame animation per break-apart part, placed so that its spawn point
  (PART_PIVOTS = skeleton.gd PART_ATTACH) is the cell centre; the JSON adds a
  "parts" table (attach, centre, launch velocity, spin, fire-pop delay).
- bat.png/.json + bat_frames.tres: 32x32 frames, origin (16, 16) = body
  centre (sprite centred, no offset). fly 13 steps loop, hang 4f loop,
  unfurl 3f once.
- bone.png: 14x14 still centred on its spin pivot; the 10x6 bone (with its
  outline) stays inside bone.tscn's 9x9 Hitbox. projectile.gd spins the
  projectile root in-engine (nearest sampling, as the PS1 did), so the bone
  ships unrotated.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, replace
from typing import Callable, Mapping, Sequence

from PIL import Image, ImageDraw

import numpy as np
from scipy import ndimage

from common import LIGHT, RAMPS, RGB, SPRITES, Indexed, Point, SheetBuilder

# ---------------------------------------------------------------------------
# Local ramps (common.py is frozen; these extend the shared registry)
# ---------------------------------------------------------------------------
# Bat (shared RAMPS["bat"], no warm shift): the body is a dark violet mass
# (tones 1-2, median Y ~35) so it reads against the mid-value wainscot band;
# against the darker upper walls it is carried by a cool rim, light wing
# bones, red eyes and the membrane, which sits a step above the body.
BAT_FUR: list[RGB] = list(RAMPS["bat"])
# Wing membrane: the same ramp plus two pinker tones that read as light
# glowing through thin skin, used only as small clusters at the scallops.
BAT_WING: list[RGB] = list(RAMPS["bat"][:4]) + [(118, 66, 112), (150, 94, 134)]
# Wing bones: tones 0-1 are the fur's outline tones (so the sel-out adds no
# colour), 2 the far wing's strut (= fur tone 4), 3 the lavender-bone.
BAT_BONE: list[RGB] = [(14, 8, 20), (32, 18, 40), (122, 80, 128), (170, 146, 176)]
# 1 px cool rim on the lit upper-front contour (ears, crown, leading edge),
# applied over the sel-out outline (docs/art_style.md: drop the outline where the
# rim light sits). Same value as the hero's hair sheen.
BAT_RIM: RGB = (150, 150, 200)
# The far wing's leading edge is the bat's upper-BACK contour: it takes the
# back-contour rim a step dimmer, so the far wing still separates from the
# darker (Y ~15-20) upper walls without competing with the lit near side.
BAT_RIM_FAR: RGB = (104, 102, 150)

ERAMPS: dict[str, list[RGB]] = {**RAMPS, "bat_fur": BAT_FUR, "bat_wing": BAT_WING,
                                "bat_bone": BAT_BONE}

# Skeleton back rim (docs/art_style.md: a cool 1 px rim on back contours, as the
# hero and the bat carry). It replaces the warm (44, 34, 34) sel-out outline
# only on the exterior back contour of the skull, cervical spine, ribcage and
# far leg; the front, bottom and inter-bone outlines stay warm. SK_RIM_HI is
# the 2 px cool catch-light on the skull dome's upper-back corner.
SK_RIM: RGB = (132, 136, 170)
SK_RIM_HI: RGB = (236, 236, 244)
SK_RIM_GROUPS: frozenset[str] = frozenset({"skull", "neck", "ribs", "leg_far"})

LXY = (LIGHT[0], LIGHT[1])  # key light direction in image space (up-right)


# ---------------------------------------------------------------------------
# 1x drawing kit on top of `Indexed`
# ---------------------------------------------------------------------------
def _bres(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
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


def _ri(p: Point) -> tuple[int, int]:
    return (int(math.floor(p[0] + 0.5)), int(math.floor(p[1] + 0.5)))


def _dir(theta_deg: float) -> Point:
    """Unit vector for an angle measured from straight DOWN, positive toward
    +x (forward for a right-facing sprite)."""
    t = math.radians(theta_deg)
    return (math.sin(t), math.cos(t))


def _add(p: Point, v: Point, s: float = 1.0) -> Point:
    return (p[0] + v[0] * s, p[1] + v[1] * s)


def _lerp(a: Point, b: Point, t: float) -> Point:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _ik(hip: Point, foot: Point, l1: float, l2: float) -> Point:
    """Knee position for a two-bone leg with the knee bending forward (+x)."""
    dx, dy = foot[0] - hip[0], foot[1] - hip[1]
    d = max(1e-6, min(math.hypot(dx, dy), l1 + l2 - 1e-3))
    a = math.acos(max(-1.0, min(1.0, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d))))
    ang = math.atan2(dy, dx) - a
    return (hip[0] + l1 * math.cos(ang), hip[1] + l1 * math.sin(ang))


class Pix:
    """A 1x canvas of (material, tone, group) pixels, drawn back to front.
    `only` restricts drawing to a set of groups (used to cut the skeleton
    into break-apart parts with exactly the pixels of the full drawing)."""

    def __init__(self, w: int, h: int, ramps: Mapping[str, Sequence[RGB]] = ERAMPS,
                 only: set[str] | None = None) -> None:
        self.ix = Indexed(w, h, ramps)
        self.w, self.h = w, h
        self.only = only

    def wants(self, group: str) -> bool:
        return self.only is None or group in self.only

    # -- primitives ------------------------------------------------------
    def put(self, x: int, y: int, tone: int, group: str, mat: str = "bone") -> None:
        if 0 <= x < self.w and 0 <= y < self.h and self.wants(group):
            self.ix.set_px(x, y, mat, tone, group=group)

    def clear(self, x: int, y: int) -> None:
        self.ix.clear_px(x, y)

    def line(self, a: Point, b: Point, tone: int | Callable[[float], int], group: str,
             mat: str = "bone") -> list[tuple[int, int]]:
        pts = _bres(*_ri(a), *_ri(b))
        n = max(1, len(pts) - 1)
        for k, (x, y) in enumerate(pts):
            self.put(x, y, tone(k / n) if callable(tone) else tone, group, mat)
        return pts

    def limb(self, a: Point, b: Point, lit: int, shade: int, group: str, *, width: int = 2,
             mat: str = "bone", mid: int | None = None) -> None:
        """A bone shaft. The Bresenham line carries `lit`; with width 2 a
        parallel line one pixel toward the shadow side carries `shade`
        (mostly-vertical bones double sideways, mostly-horizontal ones up or
        down), so the shaft is a clean 2 px stair with a terminator. `mid`
        replaces the lit tone along the middle third (the narrower shaft
        between two bright epiphyses)."""
        ax, ay = _ri(a)
        bx, by = _ri(b)
        dx, dy = bx - ax, by - ay
        pts = _bres(ax, ay, bx, by)
        if width >= 2:
            n1 = (-dy, dx)
            if n1[0] * LXY[0] + n1[1] * LXY[1] < 0:
                n1 = (dy, -dx)
            if abs(dy) >= abs(dx):
                off = (-1 if n1[0] >= 0 else 1, 0)
            else:
                off = (0, 1 if n1[1] <= 0 else -1)
            for (x, y) in pts:
                self.put(x + off[0], y + off[1], shade, group, mat)
        n = max(1, len(pts) - 1)
        for k, (x, y) in enumerate(pts):
            t = lit
            if mid is not None and 0.3 < k / n < 0.7:
                t = mid
            self.put(x, y, t, group, mat)

    def knob(self, c: Point, base: int, group: str, *, r: float = 1.0, mat: str = "bone",
             lo: int = 1, hi: int = 5) -> None:
        """A small lit sphere (joint epiphysis) centred on pixel `c`."""
        cx, cy = _ri(c)
        ri = int(math.ceil(r))
        for y in range(cy - ri, cy + ri + 1):
            for x in range(cx - ri, cx + ri + 1):
                ddx, ddy = (x - cx) / r, (y - cy) / r
                q = ddx * ddx + ddy * ddy
                if q > 1.0 + 1e-6:
                    continue
                nz = math.sqrt(max(0.0, 1.0 - q))
                d = ddx * LIGHT[0] + ddy * LIGHT[1] + nz * LIGHT[2]
                t = base + (1 if d > 0.80 else 0 if d > 0.45 else -1 if d > 0.1 else -2)
                self.put(x, y, max(lo, min(hi, t)), group, mat)

    def stamp(self, rows: Sequence[str], x0: int, y0: int, group: str, *,
              legend: Mapping[str, tuple[str, int] | None] | None = None, mat: str = "bone",
              shift: int = 0, row_dx: Sequence[int] | None = None) -> None:
        """Hand-authored 1x template. Digits are tones of `mat`; `legend`
        maps other characters to (material, tone) or None (= clear); '.' and
        ' ' are transparent. `shift` is added to every non-zero digit (far
        parts use -1/-2); `row_dx` shears the template row by row."""
        lg = dict(legend or {})
        for j, row in enumerate(rows):
            sx = row_dx[j] if row_dx is not None and j < len(row_dx) else 0
            for i, ch in enumerate(row):
                if ch in ". ":
                    continue
                x, y = x0 + i + sx, y0 + j
                if ch.isdigit():
                    t = int(ch)
                    self.put(x, y, t if t == 0 else max(1, min(5, t + shift)), group, mat)
                elif ch in lg:
                    e = lg[ch]
                    if e is None:
                        self.clear(x, y)
                    else:
                        self.put(x, y, e[1], group, e[0])
                else:
                    raise KeyError(f"stamp: unknown template character {ch!r}")

    # -- finish ----------------------------------------------------------
    def finish(self, *, contours: bool = True,
               skip: Sequence[str] = ("socket", "eye")) -> Image.Image:
        if contours:
            self.ix.interior_contours(skip=skip, tone=0)
        return self.ix.selout(lit_tone=1, light=LIGHT)


# ===========================================================================
# Skeleton
# ===========================================================================
SK_W, SK_H = 64, 64
SK_CX = 32          # world x 0 is the left edge of column 32
SK_SOLE = 58        # lowest bone row; the sel-out outline lands on row 59
SK_FOOT_ROW = 59    # lowest opaque row
# skeleton.tscn Sprite offset: a centred 64x64 frame puts row r at world
# y = r - 32 + offset_y, so the lowest opaque row 59 lands on y = -1 (resting
# on the floor line, like the hero) with offset_y = -28.
SK_OFFSET = (0, SK_H // 2 - (SK_FOOT_ROW + 1))

WALK_TICKS = [6, 4, 4, 6, 5, 5]          # SotN skeleton walk (30-tick cycle)
WALK_SPEED = 26.0                        # skeleton.gd walk_speed, px/s
ATTACK_TICKS = [4, 5, 6, 2, 3, 3]        # release on frame 3 at 15 ticks; 23 ticks total
ATTACK_RELEASE_FRAME = 3                 # = skeleton.gd THROW_RELEASE_FRAME
HURT_TICKS = [3, 24]
IDLE_TICKS = [12, 12]


def P(x: float, h: float) -> Point:
    """Rig space -> frame pixel: x right of the body centre, h up from the
    sole row."""
    return (SK_CX + x, SK_SOLE - h)


# Skull, facing right, 3/4 view, 10x8 (cranium + upper teeth). Digits are
# bone tones; r = near-socket glint, e = far-socket glint; spaces are holes
# that the sel-out fills with the warm outline (the socket depths, the gap
# where the neck enters). The teeth columns line up with the mandible's.
SKULL = [
    "...3444...",
    "..344555..",
    ".23445554.",
    "2334444554",
    "23344004 0",
    "2334 0r4e.",
    ".23345524.",
    "..22 41414",
]
# Head thrown back (hurt, wind-up): the dome shears back a pixel.
SKULL_BACK_DX = [-1, -1, -1, 0, 0, 0, 0, 0]
JAW = [            # placed at skull x + 3, one row below the skull
    "234141",
    ".2333.",
]
SKULL_LEGEND: dict[str, tuple[str, int] | None] = {"r": ("socket", 0), "e": ("eye", 0)}

# Ribcage, 9x8: spine column on the left, four ribs arcing forward and down.
RIBCAGE = [
    "2345.....",
    "2...54...",
    "23445.4..",
    "2....543.",
    "234455.4.",
    "2.....43.",
    "23444.3..",
]
# Pelvis, 7x5: iliac wing on top, the obturator ring below. The hip socket
# (femur head) sits at template (4, 2).
PELVIS = [
    "..2344.",
    ".234454",
    "23 0443",
    ".2. .3.",
    "..2..2.",
]
PELVIS_HIP = (4, 2)

# Feet, relative to the ankle pixel: (dx, dy, tone role). Roles: l lit, m one
# below lit, s shade.
FOOT_FLAT = [(-1, 0, "m"), (0, 0, "l"), (-1, 1, "s"), (0, 1, "m"), (1, 1, "l"), (2, 1, "l"),
             (3, 1, "m")]
FOOT_TOE = [(-1, 0, "s"), (0, 0, "l"), (1, 1, "l"), (2, 2, "l"), (3, 2, "m")]
FOOT_SWING = [(-1, 0, "s"), (0, 0, "l"), (1, 1, "l"), (2, 1, "m"), (2, 2, "m")]
FEET = {"flat": FOOT_FLAT, "toe": FOOT_TOE, "swing": FOOT_SWING}


@dataclass
class SkelPose:
    """One skeleton drawing. Positions are rig space (see `P`)."""
    bob: int = 0                    # torso vertical offset, + = up
    lean: int = 0                   # shoulders/head forward (+) or back (-)
    head_dx: int = 0
    head_dy: int = 0                # skull offset (+ = up), on top of bob
    head_back: bool = False
    jaw: int = 0                    # mandible drop in px
    foot_near: Point = (3.0, 0.0)   # (x, lift) of the ankle
    foot_far: Point = (-3.0, 0.0)
    foot_near_kind: str = "flat"
    foot_far_kind: str = "flat"
    hip_far_dx: float = 0.0         # far hip swung back (opens the femurs on passing frames)
    arm_near: tuple[float, float] = (8.0, 14.0)    # upper, fore angle (deg from down, + forward)
    arm_far: tuple[float, float] = (-4.0, 4.0)
    # Near arm depth against the skull: "front" (whole arm over the skull),
    # "behind" (whole arm under it) or "over" (upper arm under the skull,
    # forearm and hand over it: the arm coming over the top in a throw).
    arm_near_layer: str = "front"
    hand_open: bool = False         # fingers spread wide (an empty, just-released hand)
    arm_near_reach: float = 1.0     # near-arm length scale (< 1: foreshortened toward the target)
    held_bone: float | None = None  # angle of a bone held in the near hand


# Vertical budget (rows above the sole): crown 38 (the top outline row lands
# on world y -41: 41 px tall, inside the brief's 40-44 and only 3 px above
# the unchanged 16x38 hurtbox, 3 px lower than before), skull 38..31 + jaw
# 30..29, ribcage 29..23, lumbar 21..22 visible, pelvis 20..16 around the hip
# socket at 18, legs 18 -> 0 (47 %).
HIP_H = 18.0
FEMUR, TIBIA = 8.8, 9.2
ANKLE_H = 1.0
HUMERUS, FOREARM = 7.0, 6.5
SPINE_X = -3.0                       # spine column at the back of the ribcage
RIB_TOP_H = 29
CROWN_H = 38


def draw_skeleton(pose: SkelPose, only: set[str] | None = None,
                  canvas: tuple[int, int] = (SK_W, SK_H),
                  rim_ref: np.ndarray | None = None) -> Image.Image:
    return draw_skeleton_rim(pose, only, canvas, rim_ref)[0]


def draw_skeleton_rim(pose: SkelPose, only: set[str] | None = None,
                      canvas: tuple[int, int] = (SK_W, SK_H),
                      rim_ref: np.ndarray | None = None) -> tuple[Image.Image, np.ndarray]:
    """The skeleton drawing plus its back-rim mask. `rim_ref` (a part cut
    from a full drawing) takes the rim from that drawing's mask instead of
    measuring the part's own contour, so the parts match the drawing."""
    c = Pix(canvas[0], canvas[1], only=only)
    b, ln = pose.bob, pose.lean
    no_rim = np.zeros((canvas[1], canvas[0]), bool)     # feet: their outline stays warm

    hip_near = (0.0, HIP_H + b)
    hip_far = (-2.0 + pose.hip_far_dx, HIP_H + b)
    sh_near = (1.5 + ln, RIB_TOP_H - 1.5 + b)
    sh_far = (-0.5 + ln, RIB_TOP_H - 1.0 + b)

    def foot(ankle: tuple[int, int], kind: str, lit: int, shade: int, group: str) -> None:
        tones = {"l": lit, "m": max(1, lit - 1), "s": shade}
        for dx, dy, role in FEET[kind]:
            c.put(ankle[0] + dx, ankle[1] + dy, tones[role], group)
            if 0 <= ankle[0] + dx < canvas[0] and 0 <= ankle[1] + dy < canvas[1]:
                no_rim[ankle[1] + dy, ankle[0] + dx] = True

    def leg(hip: Point, fpos: Point, kind: str, lit: int, shade: int, group: str) -> None:
        ankle = _ri(P(fpos[0], ANKLE_H + fpos[1]))
        hp = P(*hip)
        knee = _ik(hp, ankle, FEMUR, TIBIA)
        c.limb(hp, knee, lit, shade, group)
        c.limb(knee, ankle, lit, shade, group, width=2 if lit >= 4 else 1)
        c.knob(knee, lit, group, r=1.0, hi=lit + 1)
        foot(ankle, kind, lit, shade, group)

    def arm(sh: Point, ang: tuple[float, float], lit: int, shade: int, group: str,
            held: float | None = None, part: str = "all", open_hand: bool = False,
            reach: float = 1.0) -> None:
        s = P(*sh)
        elbow = _add(s, _dir(ang[0]), HUMERUS * reach)
        wrist = _add(elbow, _dir(ang[1]), FOREARM * reach)
        near = lit >= 4
        if part in ("all", "upper"):
            c.limb(s, elbow, lit, shade, group, width=2 if near else 1)
            if near:
                c.knob(s, lit, group, r=1.0, hi=lit + 1)
        if part == "upper":
            return
        c.limb(elbow, wrist, lit, shade, group, width=1)
        c.knob(elbow, lit - 1, group, r=1.0, hi=lit)
        # hand: a 2 px palm, two long fingers and a thumb
        palm = _add(wrist, _dir(ang[1] + 6.0), 1.5)
        c.limb(wrist, palm, lit, shade, group, width=2 if near else 1)
        if open_hand:
            # splayed: fingers fanned forward and up, thumb flicked back
            c.line(palm, _add(palm, _dir(ang[1] + 30.0), 2.4), lit, group)
            c.line(palm, _add(palm, _dir(ang[1] - 30.0), 2.2), lit - 1, group)
            c.put(*_ri(_add(palm, _dir(ang[1] - 95.0), 1.6)), shade, group)
        else:
            c.line(palm, _add(palm, _dir(ang[1] + 20.0), 2.2), lit - 1, group)
            c.put(*_ri(_add(palm, _dir(ang[1] - 35.0), 1.5)), shade, group)
        if held is not None:
            mini_bone(c, palm, held, group + "_bone")

    # --- far side (thinner, one ramp step darker in the light, so it stays a
    #     readable bone and not a dark mass), then the near leg ---------------
    arm(sh_far, pose.arm_far, 3, 2, "arm_far")
    leg(hip_far, pose.foot_far, pose.foot_far_kind, 3, 2, "leg_far")
    leg(hip_near, pose.foot_near, pose.foot_near_kind, 4, 2, "leg_near")

    # --- lumbar spine, pelvis (over the femur heads), ribcage ---------------
    rib_top = RIB_TOP_H + b
    for k, hh in enumerate(range(int(HIP_H) + 1 + b, rib_top - 6)):      # lumbar vertebrae
        x, y = _ri(P(SPINE_X + 0.5 * ln, hh))
        c.put(x, y, 4 if k % 2 else 3, "spine")
        if k % 2:
            c.put(x - 1, y, 2, "spine")
    px0, py0 = _ri(P(hip_near[0] - PELVIS_HIP[0], hip_near[1] + PELVIS_HIP[1]))
    c.stamp(PELVIS, px0, py0, "pelvis")
    shear = [max(0, ln) - (j * max(0, ln)) // 6 if ln > 0 else (ln * (7 - j)) // 7
             for j in range(len(RIBCAGE))]
    rx0, ry0 = _ri(P(SPINE_X, rib_top))
    c.stamp(RIBCAGE, rx0, ry0, "ribs", row_dx=shear)
    # cervical spine up to the skull
    neck_a = P(SPINE_X + 0.5 + ln, rib_top + 1.0)
    neck_b = P(SPINE_X + 3.0 + ln + pose.head_dx * 0.5, rib_top + 2.5 + pose.head_dy * 0.5)
    c.limb(neck_a, neck_b, 3, 2, "neck", width=1)

    # --- skull + jaw, with the near arm under, over or across it --------------
    layer = pose.arm_near_layer
    rn = pose.arm_near_reach
    if layer == "behind":
        arm(sh_near, pose.arm_near, 4, 2, "arm_near", pose.held_bone, open_hand=pose.hand_open, reach=rn)
    elif layer == "over":
        arm(sh_near, pose.arm_near, 4, 2, "arm_near", part="upper", reach=rn)
    sx0, sy0 = _ri(P(SPINE_X + 2.0 + ln + pose.head_dx, CROWN_H + b + pose.head_dy))
    c.stamp(SKULL, sx0, sy0, "skull", legend=SKULL_LEGEND,
            row_dx=SKULL_BACK_DX if pose.head_back else None)
    c.stamp(JAW, sx0 + 3 + (1 if pose.head_back else 0), sy0 + len(SKULL) + pose.jaw, "skull")
    if layer != "behind":
        arm(sh_near, pose.arm_near, 4, 2, "arm_near", pose.held_bone,
            part="lower" if layer == "over" else "all", open_hand=pose.hand_open, reach=rn)
    dxs = SKULL_BACK_DX if pose.head_back else [0] * len(SKULL)
    hi = [(sx0 + tx + dxs[ty], sy0 + ty) for tx, ty in SK_RIM_HI_PX]
    return _skel_rim(c.ix, c.finish(), hi, rim_ref, no_rim)


# The cool catch-light: the two pixels on the dome's upper-back diagonal
# (SKULL template coordinates, before the head-back shear).
SK_RIM_HI_PX: tuple[tuple[int, int], ...] = ((3, 0), (2, 1))
_N8: tuple[tuple[int, int], ...] = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1))


def _skel_rim(ix: Indexed, img: Image.Image, hi: Sequence[tuple[int, int]],
              ref: np.ndarray | None, no_rim: np.ndarray) -> tuple[Image.Image, np.ndarray]:
    """Swap the warm sel-out outline for SK_RIM on the exterior back contour
    and add the dome catch-light. A rim pixel is an outline pixel that
    (1) belongs to the outside air (not a socket or other enclosed hole),
    (2) has an outward normal pointing back (nx < -0.5) and not down
    (ny < 0.5), (3) touches only SK_RIM_GROUPS bones and no foot pixel
    (`no_rim`: a heel on the floor is a bottom edge), and (4) has clear air
    for 2 px behind it, so a narrow gap between two bones stays warm. The
    silhouette never changes: only outline pixels are recoloured."""
    a = np.array(img)
    h, w = a.shape[:2]
    drawn = ix.mat >= 0
    opaque = a[..., 3] > 0
    outline = opaque & ~drawn
    if ref is not None:
        rim = outline & ref
    else:
        lab, _ = ndimage.label(~drawn)
        border = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
        ext = np.isin(lab, border[border > 0])
        pad = np.pad(drawn, 1)
        gpad = np.pad(ix.group, 1, constant_values=-1)
        ok_ids = [i for i, g in enumerate(ix.groups) if g in SK_RIM_GROUPS]
        nx = np.zeros((h, w))
        ny = np.zeros((h, w))
        elig = np.ones((h, w), bool)
        touch = np.zeros((h, w), bool)
        for dx, dy in _N8:
            nb = pad[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
            wgt = 0.7 if dx and dy else 1.0
            nx -= np.where(nb, dx * wgt, 0.0)
            ny -= np.where(nb, dy * wgt, 0.0)
            if not (dx and dy):
                g = gpad[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
                elig &= ~nb | np.isin(g, ok_ids)
                elig &= ~np.pad(no_rim, 1)[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
                touch |= nb
        nl = np.maximum(np.hypot(nx, ny), 1e-6)
        back = (nx / nl < -0.5) & (ny / nl < 0.5)
        op = np.pad(opaque, ((0, 0), (2, 0)))
        air = ~op[:, 1:1 + w] & ~op[:, 0:w]
        rim = outline & ext & back & elig & touch & air
    a[rim, :3] = SK_RIM
    for x, y in hi:
        if 0 <= x < w and 0 <= y < h and drawn[y, x] and ix.groups[ix.group[y, x]] == "skull":
            a[y, x, :3] = SK_RIM_HI
    return Image.fromarray(a, "RGBA"), rim


def mini_bone(c: Pix, center: Point, angle_deg: float, group: str, length: float = 6.0) -> None:
    """A small long bone (held in the hand before a throw)."""
    d = (math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg)))
    a = _add(center, d, -length / 2)
    bb = _add(center, d, length / 2)
    c.limb(a, bb, 4, 3, group)
    c.knob(a, 4, group, r=1.0)
    c.knob(bb, 4, group, r=1.0)


# --- walk ------------------------------------------------------------------
def _walk_feet() -> list[tuple[tuple[Point, str], tuple[Point, str]]]:
    """Per frame: ((x, lift), kind) for the near and the far foot. Each foot
    is planted for 4 of the 6 frames and slides back by exactly
    WALK_SPEED * ticks / 60 px per frame (rounded on the cumulative
    displacement), then swings forward for 2 frames."""
    n = len(WALK_TICKS)
    cum = [0.0]
    for t in WALK_TICKS * 2:
        cum.append(cum[-1] + WALK_SPEED * t / 60.0)

    def track(contact: int, x0: float) -> list[tuple[Point, str]]:
        out: list[tuple[Point, str]] = [((0.0, 0.0), "flat")] * n
        for k in range(4):
            f = (contact + k) % n
            disp = cum[contact + k] - cum[contact]
            out[f] = ((float(round(x0 - disp)), 1.0 if k == 3 else 0.0), "toe" if k == 3 else "flat")
        lift_x = x0 - (cum[contact + 4] - cum[contact])
        for j in range(2):
            f = (contact + 4 + j) % n
            x = lift_x + (x0 - lift_x) * (0.4 if j == 0 else 0.8)
            out[f] = ((float(round(x)), 3.0 if j == 0 else 2.0), "swing" if j == 0 else "flat")
        return out

    near = track(0, 3.0)
    far = track(3, 2.0)
    return [(near[f], far[f]) for f in range(n)]


# Walk secondary motion (SotN skeletons lope: loose, bouncy, a little jerky).
# The torso drops on the contacts (0, 3) and springs up on the first passing
# frame (1, 4): 2 px of travel. The skull nods down with the torso on each
# contact, then lags it (the neck stretches 1 px) when the torso springs up,
# so the crown itself only moves 1 px: 40-41 px tall, the top outline row
# never above world y -41.
WALK_BOB = [-1, 1, 0, -1, 1, 0]
WALK_HEAD_DY = [0, -1, 0, 0, -1, 0]
WALK_PASSING = (1, 2, 4, 5)


def walk_poses() -> list[SkelPose]:
    feet = _walk_feet()
    total = float(sum(WALK_TICKS))
    cum = 0.0
    bob = WALK_BOB
    poses: list[SkelPose] = []
    for f, t in enumerate(WALK_TICKS):
        ph = 2.0 * math.pi * cum / total
        (fn, kn), (ff, kf) = feet[f]
        # wide, loose arm swing; the forearm trails the upper arm (drag)
        up_n = 8.0 - 32.0 * math.cos(ph)
        fo_n = up_n + 14.0 - 30.0 * math.cos(ph - 1.4)
        up_f = 4.0 + 26.0 * math.cos(ph)
        fo_f = up_f + 10.0 + 24.0 * math.cos(ph - 1.4)
        passing = f in WALK_PASSING
        far_x, far_lift, near_lift = ff[0] - 1.0, ff[1], fn[1]
        # Open a 1-2 px gap between the femurs on the passing frames without
        # ever moving a planted foot (no skating): the far hip swings back
        # 1 px, a far foot in the air is carried 2 px further back, and a near
        # foot in the air drives its knee higher.
        if passing and ff[1] > 0.0:
            far_x -= 2.0
        if passing and fn[1] > 0.0:
            near_lift += 1.0
        # the trailing forearm flicks forward but never up to a horizontal
        # "zombie reach"
        fo_n = min(fo_n, 56.0)
        poses.append(SkelPose(bob=bob[f], head_dy=WALK_HEAD_DY[f], jaw=1 if f in (1, 4) else 0,
                              lean=1, foot_near=(fn[0], near_lift), foot_far=(far_x, far_lift),
                              foot_near_kind=kn, foot_far_kind=kf,
                              hip_far_dx=-1.0 if passing else 0.0,
                              arm_near=(up_n, fo_n), arm_far=(up_f, fo_f)))
        cum += t
    return poses


def attack_poses() -> list[SkelPose]:
    st = dict(foot_near=(4.0, 0.0), foot_far=(-4.0, 0.0))
    return [
        # 0 anticipation: dip, near arm swings down and back to draw a bone
        SkelPose(bob=-1, lean=2, arm_near=(-40.0, -15.0), arm_far=(15.0, 30.0),
                 held_bone=70.0, **st),  # type: ignore[arg-type]
        # 1 raise: bone swept up behind, torso straightens, head lifts
        SkelPose(bob=0, lean=0, head_back=True, arm_near=(-115.0, -140.0), arm_far=(20.0, 35.0),
                 arm_near_layer="behind", held_bone=-35.0, jaw=1, **st),  # type: ignore[arg-type]
        # 2 cock (held): leaning back, bone cocked behind the skull, jaw open
        SkelPose(bob=0, lean=-1, head_back=True, head_dx=-1, arm_near=(-165.0, -75.0),
                 arm_far=(30.0, 45.0), arm_near_layer="behind", held_bone=-110.0, jaw=1,
                 **st),  # type: ignore[arg-type]
        # 3 release (2 ticks): the torso pitches forward while the skull lags
        # back (overlapping action); the near arm has whipped up-forward across
        # the jaw, foreshortened toward the target, and the hand is open and
        # EMPTY just in front of the face, where skeleton.gd spawns the bone
        # (bone_spawn_offset (6, -34); the palm lands at about (+9, -36)).
        # Nothing is drawn above the skull, so no second bone shows.
        SkelPose(bob=-1, lean=2, head_dx=-3, jaw=1, arm_near=(152.0, 134.0), arm_near_reach=0.62,
                 arm_far=(-15.0, -5.0), hand_open=True, **st),  # type: ignore[arg-type]
        # 4 follow-through: arm forward and down (hand at about (+18, -30)),
        # torso pitched forward, skull catching up
        SkelPose(bob=-1, lean=3, head_dx=1, arm_near=(105.0, 80.0), arm_far=(-15.0, -5.0),
                 **st),  # type: ignore[arg-type]
        # 5 recover
        SkelPose(bob=0, lean=2, arm_near=(45.0, 40.0), arm_far=(-5.0, 5.0), **st),  # type: ignore[arg-type]
    ]


def hurt_poses() -> list[SkelPose]:
    st = dict(foot_near=(3.0, 0.0), foot_far=(-4.0, 0.0))
    return [
        # impact: head snaps back, jaw flies open, arms flung up and out
        SkelPose(bob=0, lean=-2, head_back=True, head_dx=-2, jaw=2, arm_near=(125.0, 160.0),
                 arm_far=(115.0, 140.0), **st),  # type: ignore[arg-type]
        # recoil hold: sagging back, arms dropping loose
        SkelPose(bob=-1, lean=-1, head_back=True, head_dx=-1, jaw=1, arm_near=(70.0, 40.0),
                 arm_far=(60.0, 30.0), **st),  # type: ignore[arg-type]
    ]


def idle_poses() -> list[SkelPose]:
    base = SkelPose(lean=1, foot_near=(3.0, 0.0), foot_far=(-3.0, 0.0), arm_near=(8.0, 14.0),
                    arm_far=(-2.0, 6.0))
    return [base, replace(base, jaw=1)]


def _draw(poses: Sequence[SkelPose]) -> list[Image.Image]:
    return [draw_skeleton(p) for p in poses]


def skeleton_walk() -> list[Image.Image]:
    return _draw(walk_poses())


def skeleton_attack() -> list[Image.Image]:
    return _draw(attack_poses())


def skeleton_hurt() -> list[Image.Image]:
    return _draw(hurt_poses())


def skeleton_idle() -> list[Image.Image]:
    return _draw(idle_poses())


def build_skeleton() -> None:
    sb = SheetBuilder("skeleton", SK_W, SK_H, origin=(SK_CX, SK_FOOT_ROW))
    sb.add("walk", skeleton_walk(), 60.0, True, ticks=WALK_TICKS)
    sb.add("attack", skeleton_attack(), 60.0, False, ticks=ATTACK_TICKS)
    sb.add("hurt", skeleton_hurt(), 60.0, False, ticks=HURT_TICKS)
    sb.add("idle", skeleton_idle(), 60.0, True, ticks=IDLE_TICKS)
    sb.save()


# --- death break-apart parts ------------------------------------------------
PART_CELL = 24
# name, groups, SotN-observed launch numbers (vx away from the hit, vy, in px
# per 60 Hz tick; spin in degrees per tick; ticks until the part bursts into
# a small fire puff). The staggered pops are the SotN feel.
PART_SPECS: list[tuple[str, set[str], float, float, float, int]] = [
    ("skull", {"skull"}, 0.75, -5.0, 22.5, 48),
    ("ribcage", {"ribs", "neck"}, 1.75, -3.0, 11.25, 32),
    ("pelvis", {"pelvis", "spine"}, 1.5, -2.0, 6.3, 20),
    ("arm", {"arm_near"}, 1.0, -3.0, 2.8, 12),
    ("leg_a", {"leg_near"}, 2.0, -4.0, 5.6, 24),
    ("leg_b", {"leg_far"}, 1.75, -0.875, 1.4, 16),
]


# Where each piece spawns and spins, relative to the feet (world px, facing
# right). These MUST equal PART_ATTACH in scripts/enemies/skeleton.gd, which
# hard-codes them. Each part is placed in its cell so that this point is the
# cell centre (the Sprite2D pivot); a piece spawned there therefore covers
# exactly the pixels the skeleton drew, even where the part's own centre has
# moved (the lowered skull and ribcage sit 1-2 px below their pivot).
PART_PIVOTS: dict[str, tuple[int, int]] = {
    "skull": (5, -37), "ribcage": (1, -31), "pelvis": (-1, -22),
    "arm": (5, -23), "leg_a": (3, -11), "leg_b": (-1, -11),
}


def skeleton_parts() -> list[tuple[str, Image.Image, tuple[int, int], tuple[int, int]]]:
    """Each part cut from the idle drawing (same pixels, its own outline) and
    placed in a PART_CELL cell with its PART_PIVOTS point on the cell centre.
    Returns (name, image, pivot, centre): pivot = PART_PIVOTS[name], centre =
    the part's bbox centre, both relative to the feet origin in world pixels
    (facing right)."""
    pose = idle_poses()[0]
    rim_ref = draw_skeleton_rim(pose)[1]
    out: list[tuple[str, Image.Image, tuple[int, int], tuple[int, int]]] = []
    for name, groups, *_ in PART_SPECS:
        full = draw_skeleton(pose, only=groups, rim_ref=rim_ref)
        bb = full.getchannel("A").getbbox()
        if bb is None:
            raise RuntimeError(f"skeleton part {name} is empty")
        cx, cy = (bb[0] + bb[2]) // 2, (bb[1] + bb[3]) // 2
        pv = PART_PIVOTS[name]
        px, py = SK_CX + pv[0], SK_FOOT_ROW + 1 + pv[1]          # pivot in frame pixels
        ox, oy = PART_CELL // 2 - (px - bb[0]), PART_CELL // 2 - (py - bb[1])
        if ox < 0 or oy < 0 or ox + bb[2] - bb[0] > PART_CELL or oy + bb[3] - bb[1] > PART_CELL:
            raise RuntimeError(f"skeleton part {name} does not fit its {PART_CELL}px cell")
        cell = Image.new("RGBA", (PART_CELL, PART_CELL), (0, 0, 0, 0))
        cell.alpha_composite(full.crop(bb), (ox, oy))
        out.append((name, cell, pv, (cx - SK_CX, cy - (SK_FOOT_ROW + 1))))
    return out


def build_skeleton_parts() -> None:
    parts = skeleton_parts()
    sb = SheetBuilder("skeleton_parts", PART_CELL, PART_CELL, origin=(PART_CELL // 2, PART_CELL // 2))
    for name, img, _, _ in parts:
        sb.add(name, [img], 60.0, False, ticks=[1])
    sb.save()
    path = os.path.join(SPRITES, "skeleton_parts.json")
    with open(path) as fh:
        data = json.load(fh)
    table: dict[str, object] = {}
    for (name, img, attach, centre), (_, _, vx, vy, spin, pop) in zip(parts, PART_SPECS):
        bb = img.getchannel("A").getbbox()
        table[name] = {
            "attach": list(attach),
            "centre": list(centre),
            "pivot": [PART_CELL // 2, PART_CELL // 2],
            "rect": [bb[0], bb[1], bb[2] - bb[0], bb[3] - bb[1]] if bb else [0, 0, 0, 0],
            "velocity": [vx, vy],
            "velocity_px_s": [vx * 60.0, vy * 60.0],
            "spin_deg_per_tick": spin,
            "pop_ticks": pop,
        }
    data["parts"] = table
    data["notes"] = ("attach = spawn and spin pivot relative to the skeleton feet origin (world px, "
                     "facing right; mirror x when facing left) = skeleton.gd PART_ATTACH; it is the "
                     "cell centre, so a part spawned there covers the pixels the skeleton drew. "
                     "centre = the part's own bbox centre. velocity is px per 60 Hz tick, +x away "
                     "from the hit. Each part bursts into a small fire puff after pop_ticks.")
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)


# ===========================================================================
# Bone projectile
# ===========================================================================
# Thrown bone, 8x4 (10x6 with its sel-out outline): a 2 px shaft (lit top,
# shaded underside) between two double-knobbed ends. The end columns hold
# only the two condyle lobes, so the outline drops into a notch between them
# and the ends read as knuckles at 1x, the classic thrown-bone silhouette.
# Size: bone.tscn's Hitbox is a 9x9 square that spins with the art, so the
# art must stay inside +-4.5 px of the pivot in its own frame. Stamped at
# (3, 5), every opaque pixel centre (outline included) lies within -4.5..+4.5
# in x and -2.5..+2.5 in y: none overhangs the hitbox (the 12 px bone had 12
# outline/knob pixels outside it, so it could graze the hero without a hit).
BONE_TPL = [
    "34....45",
    ".454455.",
    ".343344.",
    "23....32",
]
BONE_AT = (3, 5)


def bone_projectile() -> Image.Image:
    """14x14, centred on the projectile's spin pivot (7, 7)."""
    c = Pix(14, 14)
    c.stamp(BONE_TPL, BONE_AT[0], BONE_AT[1], "bone")
    return c.finish(contours=False)


def build_bone() -> None:
    bone_projectile().save(os.path.join(SPRITES, "bone.png"))


# ===========================================================================
# Bat
# ===========================================================================
BAT_FW = BAT_FH = 32
BAT_C = (16, 16)                         # body centre = scene origin
# 13-step SotN flap: holds on wings-up (4) and wings-down (4), snapping
# through the downstroke, slower upstroke; 8 distinct drawings.
BAT_FLAP_SEQ = [0, 1, 2, 3, 4, 5, 6, 5, 4, 3, 2, 1, 7]
BAT_FLAP_TICKS = [4, 1, 1, 1, 1, 1, 4, 2, 2, 2, 1, 2, 2]
BAT_HANG_TICKS = [24, 10, 24, 10]
BAT_UNFURL_TICKS = [4, 3, 4]
BAT_TICKS = {"fly": BAT_FLAP_TICKS, "hang": BAT_HANG_TICKS, "unfurl": BAT_UNFURL_TICKS}


@dataclass
class WingPose:
    theta: float          # forearm elevation in degrees (+ up, - down)
    fold: float = 0.0     # 0 spread .. 1 folded
    body_dy: int = 0      # body offset (- = up)
    curl: float = 0.0     # tips curling under (down-stroke extreme)
    # finger fan, degrees relative to the forearm (+ = toward the leading
    # edge, - = toward the trailing edge), and a length scale for forearm +
    # fingers
    spread: tuple[float, float, float] = (10.0, -38.0, -82.0)
    reach: float = 1.0


# drawings 0..7: up, 3 between, horizontal, down x2 (extreme + hold), top
# overshoot. The two wings-up drawings throw the tips 6-8 px above the ear
# tips (frame rows 1-2 against the ears' row 8) and flare them outward, so
# the silhouette is a clear V and not a heart.
BAT_DRAWINGS = [
    WingPose(78.0, 0.0, spread=(-12.0, -44.0, -84.0), reach=1.40),
    WingPose(42.0, 0.0),
    WingPose(18.0, 0.0),
    WingPose(-6.0, 0.0),
    WingPose(-24.0, 0.05, -1),
    WingPose(-36.0, 0.08, -1),
    WingPose(-46.0, 0.14, -1, 0.1),
    WingPose(84.0, 0.0, spread=(-10.0, -40.0, -86.0), reach=1.34),
]


# Flying bat, 3/4 front view facing right, 10x12; digits are fur tones, e =
# eye glint, n = fang (one 1x1 pixel at each mouth corner), m = mouth, w = lit
# inner ear. The mass is tones 1-2 with tone 3 only on the lit upper-front
# planes (crown, cheek, chest). Placed with its top-left at BAT_BODY_AT so
# the chest sits on the frame centre (the scene origin).
BAT_BODY = [
    ".1......2.",
    ".11....23.",
    ".1w1..2w3.",
    "..112233..",
    ".11e12e32.",
    ".1112233..",
    "..1nmmn2..",
    ".1112332..",
    "1111223332",
    ".11112222.",
    "..111122..",
    "...1..1...",
]
BAT_BODY_AT = (11, 8)
BAT_RIM_ROWS = 4          # template rows (ears + crown) that may take the rim
BAT_LEGEND: dict[str, tuple[str, int] | None] = {
    "e": ("socket", 0), "n": ("bone", 5), "m": ("bat_fur", 0), "w": ("bat_wing", 4),
    "v": ("bat_wing", 2), "V": ("bat_wing", 3), "W": ("bat_wing", 4), "b": ("bat_bone", 1),
    "B": ("bat_bone", 3),
}


def _dist_seg(p: Point, a: Point, b: Point) -> float:
    vx, vy = b[0] - a[0], b[1] - a[1]
    ll = vx * vx + vy * vy + 1e-9
    t = max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / ll))
    return math.hypot(p[0] - a[0] - vx * t, p[1] - a[1] - vy * t)


# Membrane tone model: base, panel-centre lift, highest regular tone. The
# membrane stays in BAT_WING tones 1-2 (the body's values) and the struts
# carry the structure, so the whole bat is a dark violet shape with a light
# bone armature, separating from both the dark upper walls and the mid-value
# wainscot band.
MEMBRANE = (1.2, 0.8, 2)


def _wing(c: Pix, side: int, wp: WingPose, body_dy: int, *, dark: int = 0) -> list[tuple[int, int]]:
    """One membrane wing; side +1 = right (toward facing), -1 = left (far,
    slightly foreshortened and a step darker). Structure: forearm from the
    shoulder to the wrist (thumb claw there), three finger bones fanning to
    the tips, membrane between them with a scalloped trailing edge back to
    the hip. Values: the membrane sits a step above the dark body (tones
    2-3), darker along the bones, at the roots and on the underside (down-
    stroke), lighter in the middle of each panel; light glowing through the
    thin skin shows as small pink clusters inside the trailing-edge
    scallops. The finger bones are 1 px darker struts that divide the
    panels; the forearm (the leading edge) is a lavender-bone line. Returns
    the leading-edge pixels (for the rim)."""
    cx, cy = BAT_C
    sh = (cx - 0.5 + 3.0 * side + (0.5 if side > 0 else 0.0), cy - 1.0 + body_dy)
    th = math.radians(wp.theta)
    fold = wp.fold
    scale = (1.0 if side > 0 else 0.9) * wp.reach
    fdir = (side * math.cos(th), -math.sin(th))
    wrist = _add(sh, fdir, 4.2 * (1.0 - 0.35 * fold) * scale)
    lengths = [5.6, 6.0, 5.8]
    base_ang = math.atan2(fdir[1], fdir[0])
    tips: list[Point] = []
    for k in range(3):
        a = base_ang - side * math.radians(wp.spread[k] * (1.0 - 0.55 * fold))
        a += side * math.radians(wp.curl * 55.0 * (k + 1) / 3.0)
        L = lengths[k] * (1.0 - 0.45 * fold) * scale
        tips.append((wrist[0] + math.cos(a) * L, wrist[1] + math.sin(a) * L))
    hip = (cx - 0.5 + 2.0 * side + (0.5 if side > 0 else 0.0), cy + 3.5 + body_dy)

    def scallop(p: Point, q: Point, depth: float = 0.30) -> Point:
        return _lerp(_lerp(p, q, 0.5), wrist, depth)

    sc = [scallop(tips[0], tips[1]), scallop(tips[1], tips[2]), scallop(tips[2], hip, 0.25)]
    poly = [sh, wrist, tips[0], sc[0], tips[1], sc[1], tips[2], sc[2], hip]
    m = Image.new("L", (c.w, c.h), 0)
    ImageDraw.Draw(m).polygon([(x, y) for x, y in poly], fill=255)
    mask = m.load()
    face = 0.5 + 0.5 * math.sin(th)                       # 1 up .. 0 down
    bones = [(sh, wrist)] + [(wrist, t) for t in tips]
    g = "wing_l" if side < 0 else "wing_r"
    # glow spots: on the trailing-edge scallop of the two outer panels
    glow = [_lerp(sc[0], wrist, 0.06), _lerp(sc[1], wrist, 0.06)]
    for y in range(c.h):
        for x in range(c.w):
            if not mask[x, y]:
                continue
            p = (float(x), float(y))
            db = min(_dist_seg(p, a, b) for a, b in bones)
            dr = math.hypot(p[0] - sh[0], p[1] - sh[1])
            v = MEMBRANE[0] + 0.9 * face - 0.45 * dark - 0.7 * fold
            v += MEMBRANE[1] * max(0.0, min(1.0, (db - 0.6) / 1.8)) * (0.35 + 0.65 * min(1.0, dr / 6.0))
            t = max(1, min(MEMBRANE[2], int(round(v))))
            if face > 0.3 and fold < 0.3 and min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in glow) < 1.05:
                t = 5 - dark if t >= 3 else 4
            c.put(x, y, t, g, "bat_wing")
    # finger struts: unbroken 1 px lavender-bone lines from the wrist out to
    # the scallop points (the far wing's a step darker), so the wing reads as
    # skin stretched over a light armature
    for t in tips:
        c.line(_lerp(wrist, t, 0.12), _lerp(wrist, t, 0.92), 3 - dark, g, "bat_bone")
    # forearm = leading edge: mid violet under the rim, turning lavender-bone
    # toward the wrist where the fingers fan out; the far wing's a step down
    lead = c.line(sh, wrist, lambda u: (2 if u < 0.5 else 3) - dark, g, "bat_bone")
    c.put(*_ri(_add(wrist, (0.0, -1.0))), 3 if not dark else 2, g, "bat_bone")   # thumb claw
    return lead


def _rim(img: Image.Image, drawn: np.ndarray, src: Sequence[tuple[int, int]],
         dirs: Sequence[tuple[int, int]], color: RGB = BAT_RIM) -> Image.Image:
    """Swap the sel-out outline for BAT_RIM where it sits next to a rim-
    eligible pixel in one of `dirs` (the lit upper-front contour). Only
    outline pixels (opaque in `img`, not `drawn` before the sel-out) change,
    so the silhouette stays the same."""
    a = np.array(img)
    h, w = a.shape[:2]
    for x, y in src:
        for dx, dy in dirs:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and a[ny, nx, 3] and not drawn[ny, nx]:
                a[ny, nx, :3] = color
    return Image.fromarray(a, "RGBA")


# Upper-back light direction (image space, y down) for the back rim.
BACK_RIM_DIR: Point = (-0.6, -0.8)


def _back_rim(img: Image.Image, ix: Indexed, group: str, color: RGB) -> Image.Image:
    """Recolour the exterior outline pixels that touch only `group` and whose
    outward normal faces the upper-back (n . BACK_RIM_DIR > 0.55). Only
    outline pixels change, so the silhouette stays the same."""
    if group not in ix.groups:
        return img
    gid = ix.groups.index(group)
    a = np.array(img)
    h, w = a.shape[:2]
    drawn = ix.mat >= 0
    outline = (a[..., 3] > 0) & ~drawn
    lab, _ = ndimage.label(~drawn)
    border = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    ext = np.isin(lab, border[border > 0])
    pad = np.pad(drawn, 1)
    gpad = np.pad(ix.group, 1, constant_values=-1)
    nx = np.zeros((h, w))
    ny = np.zeros((h, w))
    only = np.ones((h, w), bool)
    touch = np.zeros((h, w), bool)
    for dx, dy in _N8:
        nb = pad[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
        wgt = 0.7 if dx and dy else 1.0
        nx -= np.where(nb, dx * wgt, 0.0)
        ny -= np.where(nb, dy * wgt, 0.0)
        if not (dx and dy):
            only &= ~nb | (gpad[1 + dy:1 + dy + h, 1 + dx:1 + dx + w] == gid)
            touch |= nb
    nl = np.maximum(np.hypot(nx, ny), 1e-6)
    facing = (nx * BACK_RIM_DIR[0] + ny * BACK_RIM_DIR[1]) / nl > 0.55
    a[outline & ext & only & touch & facing, :3] = color
    return Image.fromarray(a, "RGBA")


def draw_bat(wp: WingPose) -> Image.Image:
    c = Pix(BAT_FW, BAT_FH)
    _wing(c, -1, wp, wp.body_dy, dark=1)
    c.ix.remove_orphans(min_same=3, keep=())
    lead = _wing(c, 1, wp, wp.body_dy)
    c.ix.remove_orphans(min_same=3, keep=())
    bx, by = BAT_BODY_AT[0], BAT_BODY_AT[1] + wp.body_dy
    c.stamp(BAT_BODY, bx, by, "body", mat="bat_fur", legend=BAT_LEGEND)
    # rim sources: the ears and crown (top and front edges) and the near
    # wing's leading edge (top edge only, so it stays a 1 px line)
    head = [(x, y) for y in range(by, by + BAT_RIM_ROWS) for x in range(bx, bx + 10)
            if c.ix.mat[y, x] >= 0 and c.ix.mats[c.ix.mat[y, x]] == "bat_fur"]
    edge = [(x, y) for x, y in lead if c.ix.mat[y, x] >= 0]
    drawn = c.ix.mat >= 0
    img = _rim(c.finish(skip=("socket", "eye", "bone")), drawn, head, ((0, -1), (1, -1)))
    img = _back_rim(img, c.ix, "wing_l", BAT_RIM_FAR)
    return _rim(img, drawn, edge, ((0, -1),))


# Hanging upside down, wings wrapped like a cloak: claws at the top (row 5 =
# world y -11, gripping the ceiling underside), finger ridges down the folded
# wings (b dark strut on the shadow side, B lavender-bone on the lit side),
# the dark fur chest between them, head at the bottom with the ears pointing
# down.
BAT_HANG = [
    "...1..1...",
    "...2..2...",
    "...1221...",
    "..vV12VV..",
    ".vVb12BVv.",
    ".vVb12BVV.",
    "vvVb12BVVv",
    "vVVb12BVVV",
    "vvVb12BVVv",
    ".vVb11BVV.",
    ".vvb11bVv.",
    "..v1122v..",
    "..122332..",
    ".1e2232e2.",
    ".1122n2...",
    "..1....2..",
    ".1......2.",
]
BAT_HANG_AT = (11, 6)


def draw_bat_hang(sway: int, *, drop: int = 0, open_: bool = False) -> Image.Image:
    """`sway` shifts the lower half 1 px (the body pivots on its claws);
    `drop`/`open_` are used by the unfurl."""
    c = Pix(BAT_FW, BAT_FH)
    rows = BAT_HANG
    x0, y0 = BAT_HANG_AT
    shear = [0] * 6 + [sway if j >= 9 else (sway if (j >= 6 and j % 2 == 1) else 0)
                       for j in range(6, len(rows))]
    if open_:
        # wings loosening: the cloak edges peel outward
        rows = [r.replace("vv", "v.") if 3 <= j <= 11 else r for j, r in enumerate(rows)]
    c.stamp(rows, x0, y0 + drop, "body", mat="bat_fur", legend=BAT_LEGEND, row_dx=shear)
    # rim down the lit (front) flank of the folded wings, and on the claws
    drawn = c.ix.mat >= 0
    flank = [(x, y) for y in range(y0 + drop + 3, y0 + drop + 10) for x in range(x0 + 4, x0 + 12)
             if 0 <= y < c.h and 0 <= x < c.w and drawn[y, x]]
    claws = [(x, y) for y in range(y0 + drop, y0 + drop + 2) for x in range(x0, x0 + 10)
             if 0 <= y < c.h and drawn[y, x]]
    img = _rim(c.finish(skip=("socket", "eye", "bone")), drawn, flank, ((1, 0),))
    return _rim(img, drawn, claws, ((1, 0), (1, -1)))


def bat_frames() -> dict[str, list[Image.Image]]:
    drawings = [draw_bat(wp) for wp in BAT_DRAWINGS]
    fly = [drawings[i] for i in BAT_FLAP_SEQ]
    hang = [draw_bat_hang(0), draw_bat_hang(1), draw_bat_hang(0), draw_bat_hang(-1)]
    unfurl = [draw_bat_hang(0, drop=2, open_=True), draw_bat(WingPose(-66.0, 0.55, 0, 0.4)),
              drawings[3]]
    return {"fly": fly, "hang": hang, "unfurl": unfurl}


def build_bat() -> None:
    fr = bat_frames()
    sb = SheetBuilder("bat", BAT_FW, BAT_FH, origin=BAT_C)
    sb.add("fly", fr["fly"], 60.0, True, ticks=BAT_FLAP_TICKS)
    sb.add("hang", fr["hang"], 60.0, True, ticks=BAT_HANG_TICKS)
    sb.add("unfurl", fr["unfurl"], 60.0, False, ticks=BAT_UNFURL_TICKS)
    sb.save()


def build() -> None:
    build_skeleton()
    build_skeleton_parts()
    build_bat()
    build_bone()


if __name__ == "__main__":
    build()
