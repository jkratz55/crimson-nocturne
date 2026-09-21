"""
Enemies (skeleton, bat), projectiles, pickups, breakable candles,
combat effects and HUD pieces.
"""
from __future__ import annotations

import math
import os
import random

from PIL import Image

from common import (
    BAT, BAT_SH, BAT_WING, BLADE, BLADE_SH, BONE, BONE_DK, BONE_SH, CAPE_IN, EYE,
    FIRE_1, FIRE_2, FIRE_3, FIRE_4, HEART, HEART_HI, HEART_SH, OUTLINE, SPRITES, TRIM,
    TRIM_SH, UI, Point, SheetBuilder, line, new_canvas, outline, polar, poly, px, rect,
)


# ---------------------------------------------------------------------------
# Skeleton (48x48, feet on y=45, centre x=24)
# ---------------------------------------------------------------------------
def skeleton(leg_phase: float, arm: str = "swing", bone_in_hand: bool = False) -> Image.Image:
    img, d = new_canvas(48, 48)
    bob = 1 if math.sin(leg_phase * 2) > 0.5 else 0
    hx, hy = 24, 31 + bob

    def leg(phase: float, col) -> None:
        fx = hx + 5 * math.sin(phase)
        lift = max(0.0, math.cos(phase)) * 3
        fy = 44 - lift
        knee = ((hx + fx) / 2 + 2, (hy + fy) / 2)
        line(d, [(hx, hy + 1), knee, (fx, fy)], col, 2)
        rect(d, fx - 1, fy, fx + 2, fy + 1, col)

    def arm_pts(which: str, back: bool) -> list[Point]:
        sh = (21 if back else 27, 19 + bob)
        if which == "swing":
            s = -1 if back else 1
            hand = (sh[0] + 3 * s * math.sin(leg_phase), sh[1] + 9)
            return [sh, (sh[0] + s * math.sin(leg_phase), sh[1] + 5), hand]
        if which == "raise":
            return [sh, (sh[0] - 3, sh[1] - 4), (sh[0] - 6, sh[1] - 8)]
        if which == "over":
            return [sh, (sh[0] + 2, sh[1] - 5), (sh[0] + 5, sh[1] - 9)]
        return [sh, (sh[0] + 5, sh[1] + 1), (sh[0] + 10, sh[1] + 2)]  # "throw"

    leg(leg_phase + math.pi, BONE_SH)
    line(d, arm_pts("swing", True), BONE_SH, 2)
    # spine + ribs + pelvis
    line(d, [(24, 17 + bob), (24, hy)], BONE_SH, 2)
    for i, y in enumerate((20, 23, 26)):
        yy = y + bob
        line(d, [(20 + i, yy + 1), (24, yy - 1), (28 - i // 2, yy + 1)], BONE, 1)
    rect(d, 21, hy - 1, 27, hy + 1, BONE)
    px(img, 24, hy, BONE_DK)
    leg(leg_phase, BONE)
    # skull
    sy = 6 + bob
    rect(d, 20, sy, 29, sy + 8, BONE)
    rect(d, 20, sy, 21, sy + 7, BONE_SH)
    rect(d, 26, sy + 3, 28, sy + 5, OUTLINE)
    px(img, 27, sy + 4, EYE)
    rect(d, 23, sy + 9, 28, sy + 11, BONE)
    for x in (24, 26, 28):
        px(img, x, sy + 10, BONE_DK)
    px(img, 29, sy + 6, BONE_DK)
    arm_mode = arm
    pts = arm_pts(arm_mode, False)
    line(d, pts, BONE, 2)
    if bone_in_hand:
        hand = pts[-1]
        line(d, [(hand[0] - 2, hand[1] - 2), (hand[0] + 2, hand[1] + 2)], BONE, 2)
    return outline(img)


def build_skeleton() -> None:
    sb = SheetBuilder("skeleton", 48, 48)
    sb.add("walk", [skeleton(i / 4 * math.tau) for i in range(4)], 6, True)
    sb.add("attack", [skeleton(0, "raise", True), skeleton(0, "over", True), skeleton(0, "throw")], 8, False)
    sb.add("hurt", [skeleton(math.pi / 2, "raise")], 1, False)
    sb.save()


# ---------------------------------------------------------------------------
# Bat (32x32)
# ---------------------------------------------------------------------------
def bat(wing: float) -> Image.Image:
    """`wing` in [-1, 1]: -1 wings fully up, 1 fully down."""
    img, d = new_canvas(32, 32)
    cx, cy = 16, 16
    tip_y = cy + wing * 8
    for s in (-1, 1):
        pts = [(cx + 2 * s, cy - 1), (cx + 7 * s, cy - 3 + wing * 3), (cx + 13 * s, tip_y),
               (cx + 11 * s, tip_y + 3), (cx + 9 * s, cy + 1 + wing * 2), (cx + 6 * s, cy + 3 + wing),
               (cx + 3 * s, cy + 3)]
        poly(d, pts, BAT_WING)
        line(d, [(cx + 2 * s, cy - 1), (cx + 7 * s, cy - 3 + wing * 3), (cx + 13 * s, tip_y)], BAT_SH, 1)
    rect(d, cx - 3, cy - 3, cx + 3, cy + 4, BAT)
    rect(d, cx - 3, cy + 2, cx + 3, cy + 4, BAT_SH)
    px(img, cx - 3, cy - 4, BAT)
    px(img, cx + 3, cy - 4, BAT)
    px(img, cx - 1, cy - 1, EYE)
    px(img, cx + 1, cy - 1, EYE)
    px(img, cx, cy + 2, BONE)
    return outline(img)


def bat_hang() -> Image.Image:
    img, d = new_canvas(32, 32)
    cx = 16
    rect(d, cx - 4, 8, cx + 4, 20, BAT_WING)
    rect(d, cx - 2, 9, cx + 2, 19, BAT)
    line(d, [(cx - 1, 6), (cx - 1, 8)], BAT_SH, 1)
    line(d, [(cx + 1, 6), (cx + 1, 8)], BAT_SH, 1)
    px(img, cx - 1, 17, EYE)
    px(img, cx + 1, 17, EYE)
    return outline(img)


def build_bat() -> None:
    sb = SheetBuilder("bat", 32, 32)
    sb.add("fly", [bat(w) for w in (-1.0, -0.2, 1.0, -0.2)], 12, True)
    sb.add("hang", [bat_hang()], 1, False)
    sb.save()


# ---------------------------------------------------------------------------
# Effects
# ---------------------------------------------------------------------------
def build_hit_spark() -> None:
    frames = []
    for f in range(4):
        img, d = new_canvas(24, 24)
        r = [5, 10, 11, 8][f]
        inner = [3, 5, 3, 1][f]
        for k in range(8):
            a = k * 45 + f * 10
            length = r if k % 2 == 0 else r * 0.6
            line(d, [polar((12, 12), a, inner), polar((12, 12), a, length)],
                 FIRE_1 if f < 2 else FIRE_2, 1)
        if f < 2:
            rect(d, 10, 10, 14, 14, (255, 255, 255))
        frames.append(img)
    sb = SheetBuilder("hit_spark", 24, 24)
    sb.add("default", frames, 24, False)
    sb.save()


def flame_frame(f: int, n: int, w: int, h: int, seed: int) -> Image.Image:
    """Classic 'enemy burns away' flame burst: tongues rise then thin out."""
    rng = random.Random(seed * 97 + f)
    img, d = new_canvas(w, h)
    life = f / (n - 1)
    grow = min(1.0, life * 2.5)
    fade = 1.0 - max(0.0, (life - 0.45) / 0.55)
    tongues = 5
    for t in range(tongues):
        bx = w / 2 + (t - (tongues - 1) / 2) * (w / (tongues + 1)) + rng.uniform(-1.5, 1.5)
        height = (h - 4) * grow * fade * rng.uniform(0.55, 1.0) + 2
        width = 5 * fade + 1
        base_y = h - 2 - (1 - fade) * 6
        for layer, col in enumerate((FIRE_4, FIRE_3, FIRE_2, FIRE_1)):
            k = 1 - layer * 0.22
            hh, ww = height * k, width * k
            if hh < 1 or ww < 0.6:
                continue
            poly(d, [(bx - ww, base_y), (bx - ww * 0.6, base_y - hh * 0.5),
                     (bx + rng.uniform(-1, 1), base_y - hh), (bx + ww * 0.6, base_y - hh * 0.5),
                     (bx + ww, base_y)], col)
    # embers
    for _ in range(int(6 * fade) + 1):
        px(img, rng.uniform(2, w - 3), rng.uniform(2, h * 0.6), FIRE_2)
    return img


def build_death_flame() -> None:
    sb = SheetBuilder("death_flame", 32, 40)
    sb.add("default", [flame_frame(f, 10, 32, 40, 3) for f in range(10)], 16, False)
    sb.save()


# ---------------------------------------------------------------------------
# Pickups, projectiles, breakables
# ---------------------------------------------------------------------------
HEART_SMALL = [
    ".##.##.",
    "#######",
    "#######",
    ".#####.",
    "..###..",
    "...#...",
]


def heart(scale: int) -> Image.Image:
    w, h = len(HEART_SMALL[0]) * scale, len(HEART_SMALL) * scale
    img, d = new_canvas(w + 2, h + 2)
    for y, row in enumerate(HEART_SMALL):
        for x, ch in enumerate(row):
            if ch == "#":
                rect(d, 1 + x * scale, 1 + y * scale, x * scale + scale, y * scale + scale, HEART)
    rect(d, 1 + scale, 1 + scale, scale * 2, scale * 2, HEART_HI)
    px(img, w - scale, h - scale * 2, HEART_SH)
    return outline(img)


def dagger() -> Image.Image:
    img, d = new_canvas(16, 7)
    line(d, [(5, 3), (14, 3)], BLADE_SH, 2)
    line(d, [(5, 3), (14, 3)], BLADE, 1)
    line(d, [(4, 1), (4, 5)], TRIM, 1)
    line(d, [(1, 3), (3, 3)], TRIM_SH, 2)
    return outline(img)


def axe() -> Image.Image:
    img, d = new_canvas(16, 16)
    line(d, [(3, 13), (11, 5)], TRIM_SH, 2)
    poly(d, [(8, 2), (14, 2), (15, 8), (12, 9), (9, 6)], BLADE_SH)
    poly(d, [(9, 3), (13, 3), (14, 7), (12, 7)], BLADE)
    return outline(img)


def bone_projectile() -> Image.Image:
    img, d = new_canvas(12, 12)
    line(d, [(3, 8), (8, 3)], BONE, 2)
    for p in ((2, 8), (3, 9), (8, 2), (9, 3)):
        px(img, *p, BONE)
    px(img, 6, 5, BONE_SH)
    return outline(img)


def candle(flicker: int) -> Image.Image:
    img, d = new_canvas(16, 32)
    # wrought-iron stand
    line(d, [(8, 12), (8, 29)], TRIM_SH, 1)
    line(d, [(5, 30), (11, 30)], TRIM_SH, 1)
    line(d, [(4, 11), (12, 11)], TRIM, 1)
    px(img, 4, 10, TRIM)
    px(img, 12, 10, TRIM)
    # wax + flame
    rect(d, 6, 5, 10, 10, (236, 226, 200))
    rect(d, 6, 5, 6, 10, (190, 176, 150))
    fy = 4 - flicker
    poly(d, [(6, 4), (8, fy - 3), (10, 4)], FIRE_3)
    poly(d, [(7, 4), (8, fy - 1), (9, 4)], FIRE_1)
    return outline(img)


def build_items() -> None:
    heart(1).save(os.path.join(SPRITES, "heart_small.png"))
    heart(2).save(os.path.join(SPRITES, "heart_big.png"))
    dagger().save(os.path.join(SPRITES, "dagger.png"))
    axe().save(os.path.join(SPRITES, "axe.png"))
    bone_projectile().save(os.path.join(SPRITES, "bone.png"))
    sb = SheetBuilder("candle", 16, 32)
    sb.add("burn", [candle(0), candle(1), candle(2), candle(1)], 10, True)
    sb.save()


# ---------------------------------------------------------------------------
# HUD
# ---------------------------------------------------------------------------
def build_hud() -> None:
    # Ornate status frame: sub-weapon medallion on the left, two bar slots.
    img, d = new_canvas(116, 30)
    rect(d, 12, 6, 114, 25, (10, 8, 18, 200))
    line(d, [(12, 6), (114, 6)], TRIM, 1)
    line(d, [(12, 25), (114, 25)], TRIM_SH, 1)
    line(d, [(114, 6), (114, 25)], TRIM_SH, 1)
    for x in range(24, 114, 10):
        px(img, x, 6, (255, 230, 150))
    # bar wells (the TextureProgressBars sit on top)
    rect(d, 31, 10, 99, 15, (30, 6, 12))
    rect(d, 31, 18, 83, 21, (8, 10, 34))
    # medallion
    d.ellipse([0, 1, 28, 29], fill=TRIM_SH + (255,))
    d.ellipse([2, 3, 26, 27], fill=TRIM + (255,))
    d.ellipse([4, 5, 24, 25], fill=(26, 14, 34, 255))
    d.ellipse([6, 7, 22, 23], fill=(46, 20, 44, 255))
    outline(img).save(os.path.join(UI, "hud_frame.png"))

    for name, col, hi, w, h in (("bar_hp", (200, 24, 44), (255, 110, 110), 68, 6),
                                ("bar_mp", (40, 72, 200), (120, 160, 255), 52, 4)):
        bar, bd = new_canvas(w, h)
        rect(bd, 0, 0, w - 1, h - 1, col)
        rect(bd, 0, 0, w - 1, 0, hi)
        bar.save(os.path.join(UI, f"{name}.png"))

    icon = heart(1)
    icon.save(os.path.join(UI, "heart_icon.png"))


def build() -> None:
    build_skeleton()
    build_bat()
    build_hit_spark()
    build_death_flame()
    build_items()
    build_hud()


if __name__ == "__main__":
    build()
