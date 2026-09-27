"""
Hero sprite generator — "Vesper", a dhampir swordsman.

The character is rigged as a simple 2D skeleton (hip, shoulder, head,
two legs, two arms, cape trailing edge, weapon).  Each animation
frame is a `Pose`; the renderer draws the layers back-to-front and
applies a dark outline pass.  Frames are 128x64 with the feet resting
on y=60 and the body centred on x=64 (this is the sprite origin the
Godot scene is built around: sprite offset = (0, -28)).

The frame is wider than the character needs so the whip's lash has room
to extend a full body-length ahead of him without being clipped.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from PIL import Image

from common import (
    BLADE, BLADE_SH, BOOT, BOOT_HI, CAPE_IN, CAPE_IN_HI, CAPE_OUT, COAT, COAT_HI, COAT_SH,
    EYE, HAIR, HAIR_HI, LEATHER, LEATHER_HI, LEATHER_SH, PANTS, PANTS_SH, SKIN, SKIN_SH,
    TRIM, TRIM_SH,
    Point, SheetBuilder, lerp, line, new_canvas, outline, polar, poly, px, rect,
)

FW, FH = 128, 64
CX = 64
FOOT_Y = 59


@dataclass
class Pose:
    hip: Point = (CX, 42)
    shoulder: Point = (CX + 1, 29)
    head: Point = (CX + 2, 22)
    back_leg: tuple[Point, Point] = ((CX - 2, 51), (CX - 3, FOOT_Y))
    front_leg: tuple[Point, Point] = ((CX + 3, 51), (CX + 3, FOOT_Y))
    back_arm: tuple[Point, Point] = ((CX - 2, 35), (CX - 2, 41))
    front_arm: tuple[Point, Point] = ((CX + 4, 35), (CX + 4, 41))
    cape: list[Point] = field(default_factory=lambda: [(CX - 9, 38), (CX - 12, 50), (CX - 5, 58)])
    hair: Point = (CX - 5, 30)
    sword: float | None = None       # blade angle in degrees (0 = right, 90 = down)
    sword_len: int = 22
    # Whip lash: cubic curve control points, relative to the weapon hand.
    whip: list[Point] | None = None
    whip_behind: bool = False        # draw the lash behind the body (wind-up)
    whip_vscale: float = 1.0         # squash the lash vertically (crouch)
    hem: float = 9                    # coat hem length below the hip


def _leg(img, d, hip: Point, knee: Point, foot: Point, back: bool) -> None:
    pants = PANTS_SH if back else PANTS
    line(d, [hip, knee], pants, 4)
    line(d, [knee, foot], BOOT, 4)
    # boot top cuff + toe pointing forward (+x)
    line(d, [(knee[0] - 1, knee[1] + 1), (knee[0] + 1, knee[1] + 1)], BOOT_HI if not back else BOOT, 1)
    rect(d, foot[0] - 2, foot[1] - 1, foot[0] + 3, foot[1] + 1, BOOT)
    if not back:
        px(img, foot[0] + 2, foot[1] - 1, BOOT_HI)


def _arm(img, d, shoulder: Point, elbow: Point, hand: Point, back: bool) -> None:
    line(d, [shoulder, elbow, hand], COAT_SH if back else COAT, 3)
    if not back:
        line(d, [shoulder, elbow], COAT_HI, 1)
    rect(d, hand[0] - 1, hand[1] - 1, hand[0] + 1, hand[1] + 1, SKIN_SH if back else SKIN)


def _sword(img, d, hand: Point, angle: float, length: int) -> None:
    tip = polar(hand, angle, length)
    base = polar(hand, angle, 3)
    pommel = polar(hand, angle + 180, 3)
    line(d, [base, tip], BLADE_SH, 3)
    line(d, [base, polar(hand, angle, length - 1)], BLADE, 1)
    # cross-guard perpendicular to the blade
    g0 = polar(polar(hand, angle, 2), angle + 90, 3)
    g1 = polar(polar(hand, angle, 2), angle - 90, 3)
    line(d, [g0, g1], TRIM, 2)
    line(d, [hand, pommel], TRIM_SH, 2)
    px(img, *pommel, TRIM)


def _bezier(ctrl: list[Point], t: float) -> Point:
    """De Casteljau evaluation for any number of control points."""
    pts = list(ctrl)
    while len(pts) > 1:
        pts = [lerp(pts[i], pts[i + 1], t) for i in range(len(pts) - 1)]
    return pts[0]


WHIP_SEGMENTS = 18


def _whip(img, d, hand: Point, ctrl: list[Point], vscale: float = 1.0) -> None:
    """Draw the lash as a tapering curve springing from the weapon hand.

    The curve thins from 3px of braided leather at the grip to a single
    pixel at the steel tip, which is what sells the snap at this size.
    """
    pts = [hand] + [(hand[0] + dx, hand[1] + dy * vscale) for dx, dy in ctrl]
    curve = [_bezier(pts, i / (WHIP_SEGMENTS - 1)) for i in range(WHIP_SEGMENTS)]
    for i in range(len(curve) - 1):
        t = i / (len(curve) - 2)
        width = 3 if t < 0.14 else (2 if t < 0.46 else 1)
        line(d, [curve[i], curve[i + 1]], LEATHER if t < 0.46 else LEATHER_HI, width)
    for i in range(2, int(len(curve) * 0.45), 2):                # braided highlights
        px(img, curve[i][0], curve[i][1] - 1, LEATHER_HI)
        px(img, curve[i][0], curve[i][1] + 1, LEATHER_SH)
    line(d, [hand, curve[2]], TRIM_SH, 3)                        # grip, over the lash
    line(d, [hand, curve[1]], TRIM, 1)
    px(img, *curve[-2], BLADE_SH)                                # steel tip
    px(img, *curve[-1], BLADE)


def render(p: Pose) -> Image.Image:
    img, d = new_canvas(FW, FH)
    sx, sy = p.shoulder
    hx, hy = p.hip
    cx, cy = p.head

    # --- Lash trailing behind the body (wind-up frames) --------------------
    if p.whip is not None and p.whip_behind:
        _whip(img, d, p.front_arm[1], p.whip, p.whip_vscale)

    # --- Cape (behind everything) -----------------------------------------
    cape_poly = [(sx + 2, sy - 2), (sx - 4, sy - 2)] + p.cape + [(hx + 1, hy + 2)]
    poly(d, cape_poly, CAPE_OUT)
    line(d, [(sx - 4, sy - 1)] + p.cape, CAPE_IN, 2)
    line(d, [(sx - 4, sy - 1), p.cape[0]], CAPE_IN_HI, 1)

    # --- Long hair flowing behind ------------------------------------------
    poly(d, [(cx - 3, cy - 4), (cx - 1, cy - 1), p.hair, (cx - 5, cy + 1)], HAIR)

    # --- Back limbs ----------------------------------------------------------
    _arm(img, d, (sx - 2, sy + 1), p.back_arm[0], p.back_arm[1], back=True)
    _leg(img, d, (hx - 1, hy), p.back_leg[0], p.back_leg[1], back=True)
    _leg(img, d, (hx + 1, hy), p.front_leg[0], p.front_leg[1], back=False)

    # --- Coat ----------------------------------------------------------------
    hem = p.hem
    coat = [(sx - 4, sy - 1), (sx + 4, sy - 1), (hx + 4, hy), (hx + 6, hy + hem),
            (hx - 6, hy + hem), (hx - 4, hy)]
    poly(d, coat, COAT)
    poly(d, [(sx - 4, sy - 1), (sx - 2, sy - 1), (hx - 2, hy), (hx - 3, hy + hem),
             (hx - 6, hy + hem), (hx - 4, hy)], COAT_SH)
    line(d, [(sx + 2, sy), (hx + 2, hy), (hx + 3, hy + hem - 1)], TRIM, 1)
    line(d, [(hx - 6, hy + hem), (hx + 6, hy + hem)], TRIM_SH, 1)
    line(d, [(hx - 4, hy - 1), (hx + 4, hy - 1)], CAPE_IN, 1)       # sash
    px(img, hx + 1, hy - 1, TRIM)                                      # buckle
    rect(d, sx + 1, sy, sx + 2, sy + 3, CAPE_IN)                       # cravat
    px(img, sx + 2, sy, CAPE_IN_HI)

    # --- High collar ------------------------------------------------------------
    poly(d, [(sx - 4, sy - 1), (sx - 6, sy - 7), (sx - 2, sy - 3)], CAPE_IN)
    line(d, [(sx - 5, sy - 6), (sx - 4, sy - 2)], CAPE_IN_HI, 1)

    # --- Head -------------------------------------------------------------------
    rect(d, cx - 3, cy - 4, cx + 3, cy + 2, SKIN)
    rect(d, cx - 2, cy + 3, cx + 2, cy + 3, SKIN)
    rect(d, cx - 3, cy - 4, cx - 2, cy + 2, SKIN_SH)
    px(img, cx + 2, cy - 1, EYE)
    px(img, cx + 3, cy + 1, SKIN_SH)
    # hair cap + fringe
    poly(d, [(cx - 4, cy - 4), (cx - 2, cy - 6), (cx + 3, cy - 6), (cx + 4, cy - 3),
             (cx + 2, cy - 3), (cx, cy - 2), (cx - 2, cy + 2), (cx - 4, cy + 2)], HAIR)
    line(d, [(cx - 2, cy - 5), (cx + 2, cy - 5)], HAIR_HI, 1)
    px(img, cx + 3, cy - 2, HAIR)

    # --- Front arm + weapon --------------------------------------------------
    elbow, hand = p.front_arm
    _arm(img, d, (sx + 2, sy + 1), elbow, hand, back=False)
    if p.sword is not None:
        _sword(img, d, hand, p.sword, p.sword_len)
        rect(d, hand[0] - 1, hand[1] - 1, hand[0] + 1, hand[1] + 1, SKIN)
    if p.whip is not None and not p.whip_behind:
        _whip(img, d, hand, p.whip, p.whip_vscale)
        rect(d, hand[0] - 1, hand[1] - 1, hand[0] + 1, hand[1] + 1, SKIN)

    return outline(img)


# ---------------------------------------------------------------------------
# Animation definitions
# ---------------------------------------------------------------------------
def shift(p: Pose, dx: float = 0, dy: float = 0) -> Pose:
    """Translate the upper body (hip, shoulder, head, arms, cape, hair)."""
    def s(pt: Point) -> Point:
        return (pt[0] + dx, pt[1] + dy)
    return replace(
        p, hip=s(p.hip), shoulder=s(p.shoulder), head=s(p.head),
        back_arm=(s(p.back_arm[0]), s(p.back_arm[1])),
        front_arm=(s(p.front_arm[0]), s(p.front_arm[1])),
        cape=[s(c) for c in p.cape], hair=s(p.hair),
    )


def idle_frames() -> list[Image.Image]:
    frames = []
    for i in range(4):
        breathe = 1 if i in (1, 2) else 0
        sway = math.sin(i / 4 * math.tau)
        p = Pose()
        p = replace(p,
                    shoulder=(p.shoulder[0], p.shoulder[1] + breathe),
                    head=(p.head[0], p.head[1] + breathe),
                    front_arm=((CX + 4, 35 + breathe), (CX + 4, 41 + breathe)),
                    back_arm=((CX - 2, 35 + breathe), (CX - 2, 41 + breathe)),
                    cape=[(CX - 9 + sway, 38), (CX - 12 + sway * 1.5, 50), (CX - 5 + sway, 58)],
                    hair=(CX - 5 + sway * 0.5, 30 + breathe))
        frames.append(render(p))
    return frames


def run_frames() -> list[Image.Image]:
    frames = []
    n = 8
    for i in range(n):
        ph = i / n * math.tau
        bob = -1 if i % 4 in (1, 2) else 0
        hx, hy = CX, 42 + bob
        sx, sy = CX + 3, 29 + bob

        def leg(phase: float) -> tuple[Point, Point]:
            fx = hx + 8 * math.sin(phase)
            lift = max(0.0, math.cos(phase)) * 5
            fy = FOOT_Y - lift
            knee = ((hx + fx) / 2 + 3, (hy + fy) / 2 - lift * 0.3)
            return knee, (fx, fy)

        def arm(phase: float, back: bool) -> tuple[Point, Point]:
            hand_x = sx + 6 * math.sin(phase) - (1 if back else 0)
            return ((sx + hand_x) / 2 - 1, sy + 6), (hand_x, sy + 10)

        wave = math.sin(ph * 2)
        p = Pose(
            hip=(hx, hy), shoulder=(sx, sy), head=(sx + 1, 22 + bob),
            front_leg=leg(ph), back_leg=leg(ph + math.pi),
            front_arm=arm(ph + math.pi, False), back_arm=arm(ph, True),
            cape=[(sx - 13, sy + 3 + wave), (sx - 19, sy + 10 - wave), (hx - 9, hy + 6)],
            hair=(sx - 9, sy + wave * 0.5),
            hem=8,
        )
        frames.append(render(p))
    return frames


def jump_pose(rising: bool) -> Pose:
    hx, hy = CX, 40
    sx, sy = CX + 1, 27
    if rising:
        return Pose(hip=(hx, hy), shoulder=(sx, sy), head=(sx + 1, 20),
                    back_leg=((hx - 3, hy + 7), (hx - 6, hy + 13)),
                    front_leg=((hx + 6, hy + 5), (hx + 4, hy + 13)),
                    back_arm=((sx - 4, sy + 4), (sx - 6, sy + 1)),
                    front_arm=((sx + 5, sy + 3), (sx + 7, sy - 1)),
                    cape=[(sx - 7, sy + 14), (sx - 5, sy + 25), (hx + 1, hy + 11)],
                    hair=(sx - 6, sy + 5), hem=7)
    return Pose(hip=(hx, hy), shoulder=(sx, sy), head=(sx + 1, 20),
                back_leg=((hx - 2, hy + 9), (hx - 5, hy + 17)),
                front_leg=((hx + 5, hy + 8), (hx + 5, hy + 17)),
                back_arm=((sx - 5, sy + 2), (sx - 8, sy - 2)),
                front_arm=((sx + 6, sy + 2), (sx + 9, sy - 2)),
                cape=[(sx - 11, sy - 6), (sx - 17, sy + 1), (hx - 7, hy + 1)],
                hair=(sx - 7, sy - 6), hem=10)


def crouch_pose() -> Pose:
    hx, hy = CX, 51
    sx, sy = CX + 2, 38
    return Pose(hip=(hx, hy), shoulder=(sx, sy), head=(sx + 1, 31),
                front_leg=((hx + 6, hy - 1), (hx + 6, FOOT_Y)),
                back_leg=((hx - 4, FOOT_Y - 1), (hx - 10, FOOT_Y)),
                back_arm=((sx - 3, sy + 5), (sx - 2, sy + 9)),
                front_arm=((sx + 5, sy + 4), (sx + 7, sy + 8)),
                cape=[(sx - 8, sy + 8), (sx - 12, FOOT_Y), (hx - 2, FOOT_Y)],
                hair=(sx - 6, sy), hem=7)


# Attack: windup -> overhead -> extended thrust -> follow-through -> recover.
# (hand offset from shoulder, blade angle)
ATTACK_KEYS: list[tuple[Point, Point, float]] = [
    ((-2, -4), (-4, -7), -150.0),
    ((4, -4), (7, -6), -55.0),
    ((6, 1), (12, 2), 0.0),
    ((6, 2), (11, 3), 8.0),
    ((4, 5), (6, 8), 55.0),
]


def attack_frames(base: Pose, lunge: bool) -> list[Image.Image]:
    frames = []
    for i, (elb, hand, ang) in enumerate(ATTACK_KEYS):
        p = replace(base)
        sx, sy = p.shoulder
        if lunge and i in (2, 3):
            p = replace(p,
                        front_leg=((CX + 8, 51), (CX + 11, FOOT_Y)),
                        back_leg=((CX - 5, 51), (CX - 9, FOOT_Y)),
                        cape=[(CX - 10, 36), (CX - 15, 47), (CX - 7, 56)])
        p = replace(p,
                    front_arm=((sx + elb[0], sy + elb[1]), (sx + hand[0], sy + hand[1])),
                    back_arm=((sx - 4, sy + 4), (sx - 6, sy + 7)),
                    sword=ang)
        frames.append(render(p))
    return frames


# Whip: coil behind -> arc overhead -> crack forward -> lash drops -> recover.
# (elbow offset, hand offset, lash control points relative to the hand, behind?)
WHIP_KEYS: list[tuple[Point, Point, list[Point], bool]] = [
    ((-3, -4), (-6, -8), [(-6, -2), (-16, 2), (-12, 12)], True),
    ((2, -6), (5, -9), [(-4, -8), (-16, -9), (-26, -3)], True),
    ((7, -2), (13, -1), [(12, -5), (26, -3), (42, 3)], False),
    ((7, 1), (13, 3), [(13, 2), (27, 6), (40, 12)], False),
    ((5, 5), (8, 9), [(7, 5), (12, 13), (4, 19)], False),
]


def whip_attack_frames(base: Pose, lunge: bool, vscale: float = 1.0) -> list[Image.Image]:
    """The same five-beat swing as the sword, but the reach is in the lash."""
    frames = []
    for i, (elb, hand, lash, behind) in enumerate(WHIP_KEYS):
        p = replace(base)
        sx, sy = p.shoulder
        if lunge and i in (2, 3):
            p = replace(p,
                        front_leg=((CX + 8, 51), (CX + 11, FOOT_Y)),
                        back_leg=((CX - 5, 51), (CX - 9, FOOT_Y)),
                        cape=[(CX - 10, 36), (CX - 15, 47), (CX - 7, 56)])
        p = replace(p,
                    front_arm=((sx + elb[0], sy + elb[1]), (sx + hand[0], sy + hand[1])),
                    back_arm=((sx - 4, sy + 4), (sx - 6, sy + 7)),
                    whip=lash, whip_behind=behind, whip_vscale=vscale)
        frames.append(render(p))
    return frames


def throw_frames() -> list[Image.Image]:
    frames = []
    keys = [((-3, -3), (-6, -5)), ((5, -2), (9, -3)), ((6, 3), (10, 5))]
    for elb, hand in keys:
        p = Pose()
        sx, sy = p.shoulder
        p = replace(p, front_arm=((sx + elb[0], sy + elb[1]), (sx + hand[0], sy + hand[1])))
        frames.append(render(p))
    return frames


def backdash_frames() -> list[Image.Image]:
    frames = []
    for i in range(2):
        hx, hy = CX, 43
        sx, sy = CX + 4, 30
        p = Pose(hip=(hx, hy), shoulder=(sx, sy), head=(sx + 2, 23),
                 front_leg=((hx + 5, 51), (hx + 8, FOOT_Y)),
                 back_leg=((hx - 3, 52), (hx - 6 - i, FOOT_Y)),
                 back_arm=((sx - 1, sy + 5), (sx + 2, sy + 9)),
                 front_arm=((sx + 5, sy + 5), (sx + 8, sy + 9)),
                 cape=[(sx + 6, sy + 6 + i), (sx + 12, sy + 14 - i), (hx + 6, hy + 8)],
                 hair=(sx + 5, sy - 1), hem=8)
        frames.append(render(p))
    return frames


def hurt_frames() -> list[Image.Image]:
    hx, hy = CX, 43
    sx, sy = CX - 3, 31
    p = Pose(hip=(hx, hy), shoulder=(sx, sy), head=(sx - 1, 24),
             front_leg=((hx + 4, 51), (hx + 6, FOOT_Y)),
             back_leg=((hx - 3, 51), (hx - 4, FOOT_Y)),
             back_arm=((sx - 5, sy - 1), (sx - 9, sy - 4)),
             front_arm=((sx + 5, sy - 2), (sx + 8, sy - 6)),
             cape=[(sx + 7, sy + 4), (sx + 11, sy + 12), (hx + 5, hy + 8)],
             hair=(sx + 4, sy - 2))
    return [render(p)]


def death_frames() -> list[Image.Image]:
    kneel = crouch_pose()
    kneel = replace(kneel, head=(kneel.head[0] + 1, kneel.head[1] + 2),
                    front_arm=((CX + 6, 44), (CX + 8, 52)))
    collapse = shift(kneel, 0, 4)
    collapse = replace(collapse,
                       front_leg=((CX + 8, FOOT_Y - 1), (CX + 12, FOOT_Y)),
                       back_leg=((CX - 6, FOOT_Y), (CX - 12, FOOT_Y)))
    return [render(kneel), render(collapse)]


def build() -> None:
    sheet = SheetBuilder("vesper", FW, FH)
    sheet.add("idle", idle_frames(), 5, True)
    sheet.add("run", run_frames(), 14, True)
    sheet.add("jump", [render(jump_pose(True))], 1, False)
    sheet.add("fall", [render(jump_pose(False))], 1, False)
    sheet.add("crouch", [render(crouch_pose())], 1, False)
    sheet.add("attack", attack_frames(Pose(shoulder=(CX + 2, 29), head=(CX + 3, 22)), True), 20, False)
    sheet.add("attack_crouch", attack_frames(crouch_pose(), False), 20, False)
    sheet.add("attack_air", attack_frames(jump_pose(False), False), 20, False)
    sheet.add("attack_whip", whip_attack_frames(Pose(shoulder=(CX + 2, 29), head=(CX + 3, 22)), True), 20, False)
    sheet.add("attack_whip_crouch", whip_attack_frames(crouch_pose(), False, 0.5), 20, False)
    sheet.add("attack_whip_air", whip_attack_frames(jump_pose(False), False), 20, False)
    sheet.add("throw", throw_frames(), 16, False)
    sheet.add("backdash", backdash_frames(), 10, True)
    sheet.add("hurt", hurt_frames(), 1, False)
    sheet.add("death", death_frames(), 3, False)
    sheet.save()


if __name__ == "__main__":
    build()
