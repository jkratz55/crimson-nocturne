"""
Phase 2 art: the equipment, consumables and relics the RPG layer added, the
pickups that carry them, and the save-point shrine.

Icons are 16x16 so they drop straight into the equip menu, the shop list and
the HUD next to the ones `sprites_misc.py` already draws.
"""
from __future__ import annotations

import math
import os

from PIL import Image

from common import (
    BLADE, BLADE_SH, BONE, CAPE_IN, EYE, FIRE_1, FIRE_2, FIRE_3, HEART, HEART_HI,
    HEART_SH, LEATHER, LEATHER_HI, LEATHER_SH, MOSS, OUTLINE, SPRITES, STONE,
    STONE_HI, STONE_SH, TRIM, TRIM_SH, UI,
    Image as _Image, SheetBuilder, line, new_canvas, outline, polar, poly, px, rect,
)

GOLD = (240, 196, 68)
GOLD_HI = (255, 240, 170)
GOLD_SH = (162, 108, 28)
VITAE = (206, 36, 62)
VITAE_HI = (255, 128, 140)
GLASS = (168, 196, 216)
JADE = (72, 196, 148)
JADE_HI = (168, 248, 214)
ONYX = (58, 44, 86)
ONYX_HI = (128, 110, 176)
SOUL = (126, 208, 255)
SOUL_HI = (226, 246, 255)
SOUL_SH = (44, 96, 176)


# ---------------------------------------------------------------------------
# Armour
# ---------------------------------------------------------------------------
def cuirass(body, trim, highlight, seam: bool = True) -> tuple[Image.Image, object]:
    """A sleeveless torso plate: shoulders at the top, waist at the bottom.

    Returns the un-outlined canvas and its draw handle so a variant can stamp
    a device on the breast before the outline goes on.
    """
    img, d = new_canvas(16, 16)
    poly(d, [(4, 2), (11, 2), (13, 5), (12, 12), (8, 15), (3, 12), (2, 5)], body)
    poly(d, [(4, 2), (7, 2), (6, 14), (3, 12), (2, 5)], highlight)
    line(d, [(4, 2), (8, 5), (11, 2)], trim, 1)          # collar
    line(d, [(3, 11), (12, 11)], trim, 1)                # belt
    px(img, 8, 11, GOLD)                                 # buckle
    if seam:
        line(d, [(8, 6), (8, 10)], trim, 1)              # centre seam
    return img, d


def leather_cuirass() -> Image.Image:
    img, _ = cuirass(LEATHER, TRIM_SH, LEATHER_HI)
    return outline(img)


def moonsteel_plate() -> Image.Image:
    # A waxing crescent stamped on the breast, which is where the name is from:
    # a full disc of highlight with a shadow disc bitten out of its right side.
    img, d = cuirass(BLADE_SH, TRIM, BLADE, seam=False)
    d.ellipse([5, 4, 11, 10], fill=FIRE_1 + (255,))
    d.ellipse([7, 4, 13, 10], fill=BLADE_SH + (255,))
    return outline(img)


# ---------------------------------------------------------------------------
# Accessories
# ---------------------------------------------------------------------------
def pendant(stone, stone_hi) -> Image.Image:
    """A chain looping down to a teardrop stone."""
    img, d = new_canvas(16, 16)
    line(d, [(3, 2), (5, 6), (8, 8)], BLADE_SH, 1)
    line(d, [(13, 2), (11, 6), (8, 8)], BLADE_SH, 1)
    px(img, 4, 4, BLADE)
    px(img, 12, 4, BLADE)
    poly(d, [(8, 8), (11, 11), (8, 14), (5, 11)], stone)
    poly(d, [(8, 9), (9, 11), (8, 12), (7, 11)], stone_hi)
    return outline(img)


def ring(stone, stone_hi) -> Image.Image:
    """A band seen face-on with a raised setting at the top."""
    img, d = new_canvas(16, 16)
    band = [polar((8, 9), a, 4.5) for a in range(0, 380, 20)]
    line(d, band, TRIM_SH, 2)
    line(d, [polar((8, 9), a, 4.5) for a in range(150, 290, 20)], TRIM, 1)
    rect(d, 6, 2, 10, 5, TRIM)
    rect(d, 7, 3, 9, 4, stone)
    px(img, 7, 3, stone_hi)
    return outline(img)


# ---------------------------------------------------------------------------
# Consumables & relics
# ---------------------------------------------------------------------------
def vial() -> Image.Image:
    """A stoppered flask, three-quarters full."""
    img, d = new_canvas(16, 16)
    rect(d, 6, 1, 9, 3, LEATHER_SH)                      # cork
    poly(d, [(6, 4), (9, 4), (12, 8), (12, 13), (3, 13), (3, 8)], GLASS)
    poly(d, [(4, 8), (11, 8), (11, 12), (4, 12)], VITAE)
    line(d, [(4, 8), (11, 8)], VITAE_HI, 1)              # meniscus
    px(img, 5, 10, VITAE_HI)
    px(img, 4, 6, (255, 255, 255))                       # glass glint
    return outline(img)


def leap_stone() -> Image.Image:
    """The traversal relic: a winged stone that hangs in the air."""
    img, d = new_canvas(16, 16)
    poly(d, [(8, 3), (12, 8), (8, 13), (4, 8)], SOUL_SH)
    poly(d, [(8, 5), (10, 8), (8, 11), (6, 8)], SOUL)
    px(img, 8, 7, SOUL_HI)
    for side in (-1, 1):
        line(d, [(8 + 3 * side, 6), (8 + 6 * side, 3), (8 + 6 * side, 7)], BONE, 1)
    return outline(img)


def heart_max_up() -> Image.Image:
    """A heart with a cross cut into it — the capacity upgrade pickup."""
    img, d = new_canvas(14, 14)
    poly(d, [(2, 5), (4, 3), (7, 5), (10, 3), (12, 5), (7, 12)], HEART)
    poly(d, [(3, 5), (4, 4), (6, 6), (5, 8)], HEART_HI)
    px(img, 9, 8, HEART_SH)
    line(d, [(7, 4), (7, 9)], FIRE_1, 1)                 # the "+"
    line(d, [(5, 6), (9, 6)], FIRE_1, 1)
    return outline(img)


def coin(turn: float) -> Image.Image:
    """One frame of a spinning gold coin (turn 0..1 across a half rotation).

    The spin is a disc squashed horizontally, so edge-on it is a bright
    vertical sliver and face-on it shows its stamped face.
    """
    img, d = new_canvas(10, 10)
    half = max(0.5, abs(math.cos(turn * math.pi)) * 4.0)
    d.ellipse([4.5 - half, 1, 4.5 + half, 8], fill=GOLD + (255,))
    d.ellipse([4.5 - half, 1, 4.5 + half, 4], fill=GOLD_HI + (255,))
    d.ellipse([4.5 - half, 6, 4.5 + half, 8], fill=GOLD_SH + (255,))
    if half > 2.5:
        # The face only reads once the coin is wide enough to hold it.
        d.ellipse([4.5 - half + 1.5, 2.5, 4.5 + half - 1.5, 6.5], fill=GOLD + (255,))
        px(img, 4, 4, GOLD_SH)
        px(img, 5, 5, GOLD_SH)
    return outline(img)


# ---------------------------------------------------------------------------
# Save shrine (SPEC 4.4.2)
# ---------------------------------------------------------------------------
def shrine(phase: float) -> Image.Image:
    """A stone plinth with a soul-light hovering over it, breathing."""
    img, d = new_canvas(32, 48)
    # plinth
    poly(d, [(6, 44), (25, 44), (23, 36), (8, 36)], STONE)
    poly(d, [(8, 36), (15, 36), (13, 44), (6, 44)], STONE_HI)
    rect(d, 4, 44, 27, 46, STONE_SH)
    for x in (10, 16, 22):
        px(img, x, 40, STONE_SH)
    line(d, [(9, 34), (22, 34)], TRIM_SH, 1)
    # gothic arch behind the light
    line(d, [(9, 34), (9, 20), (16, 12), (23, 20), (23, 34)], STONE_SH, 2)
    line(d, [(10, 33), (10, 21), (16, 14)], STONE_HI, 1)
    # the light itself
    radius = 5.0 + math.sin(phase * math.tau) * 1.2
    cx, cy = 16, 25 - math.sin(phase * math.tau) * 1.0
    d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=SOUL_SH + (255,))
    d.ellipse([cx - radius + 2, cy - radius + 2, cx + radius - 2, cy + radius - 2],
              fill=SOUL + (255,))
    px(img, cx - 1, cy - 1, SOUL_HI)
    px(img, cx, cy - 2, SOUL_HI)
    return outline(img)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def build() -> None:
    icons = {
        "armor_leather": leather_cuirass(),
        "armor_moonsteel": moonsteel_plate(),
        "necklace_silver": pendant(SOUL, SOUL_HI),
        "ring_ruby": ring(HEART, HEART_HI),
        "ring_jade": ring(JADE, JADE_HI),
        "ring_onyx": ring(ONYX, ONYX_HI),
        "vial_of_vitae": vial(),
        "leap_stone": leap_stone(),
        "heart_max_up": heart_max_up(),
    }
    for name, img in icons.items():
        img.save(os.path.join(SPRITES, f"{name}.png"))

    # The coin spins, so it ships as a little sheet rather than a still.
    sb = SheetBuilder("gold_coin", 10, 10)
    sb.add("spin", [coin(i / 6) for i in range(6)], 12, True)
    sb.save()
    coin(0.0).save(os.path.join(UI, "gold_icon.png"))

    shrine_sheet = SheetBuilder("save_shrine", 32, 48)
    shrine_sheet.add("idle", [shrine(i / 8) for i in range(8)], 8, True)
    shrine_sheet.save()

    print("equipment: %d icons, gold_coin, save_shrine" % len(icons))


if __name__ == "__main__":
    build()
