"""
Phase 2 art: the equipment, consumables and relics the RPG layer added, and
the spinning gold coin. (The save-point shrine lives in `props.py`; the
hearts, sub-weapons and weapon icons in `items.py`, whose small jewel-icon
renderer -- `Icon`, `IR`, `GEMS`, `ICON_LIGHT` -- this module shares.)

Icons are 16x16 so they drop straight into the equip menu, the shop list,
the HUD sub-weapon window and the world-item pedestal. Each is a tiny
painting lit from the upper left: 5-6 tone hue-shifted ramps, faceted
stones with a white glint, steel with bright edge lines, gold with a G5
specular, and material sel-out outlines.
"""
from __future__ import annotations

import math
import os

import numpy as np
from PIL import Image

from common import SPRITES, UI, Indexed, SheetBuilder, bezier_curve
from items import (
    GEMS, ICON_LIGHT, IR, Arr, Icon, Pt, bevel, dome, finish, heart_mask, poly_mask, put_px,
    q_ellipse, stamp_tones, tone,
)


# ---------------------------------------------------------------------------
# Armour
# ---------------------------------------------------------------------------
TORSO: list[Pt] = [
    (2.0, 3.4), (5.4, 2.0), (6.6, 3.7), (8.0, 4.5), (9.4, 3.7), (10.6, 2.0), (14.0, 3.4),
    (14.3, 6.2), (12.7, 7.2), (12.4, 10.6), (13.1, 12.6), (8.0, 13.6), (2.9, 12.6), (3.6, 10.6),
    (3.3, 7.2), (1.7, 6.2),
]


def _torso_height(ic: Icon, m: Arr) -> Arr:
    """Moulded chest: a shallow dome plus two pectoral swells and a
    sternum valley, so the light rakes across real forms."""
    X, Y = ic.X, ic.Y
    h = dome(m, ic.ss, height=2.2, power=0.5)
    for cx in (5.6, 10.4):
        q = q_ellipse(X, Y, (cx, 7.0), 3.0, 2.6)
        h = h + np.sqrt(np.clip(1.0 - q * q, 0.0, None)) * 0.55
    h = h - np.exp(-((X - 8.0) / 0.7) ** 2) * np.clip((Y - 4.5) / 4.0, 0.0, 1.0) * 0.25
    return np.where(m, h, 0.0)


def leather_cuirass() -> Image.Image:
    """Boiled-leather cuirass: moulded chest, a stitched neckline, a belt
    with a gold buckle and four hanging tabs (pteruges) below it."""
    ic = Icon(16, 16)
    m = poly_mask(ic.X, ic.Y, TORSO)
    ic.relief(m, _torso_height(ic, m), "leather", spec=0.35, spec_pow=6, gamma=0.9, ambient=0.3,
              group="body")
    for i, x0 in enumerate((3.4, 5.9, 8.4, 10.9)):
        lean = -0.2 if i < 2 else 0.2
        tab = [(x0, 12.0), (x0 + 2.1, 12.0), (x0 + 2.0 + lean, 15.0), (x0 + 0.2 + lean, 15.0)]
        ic.polygon(tab, "leather", edge=0.8, spec=0.3, ambient=0.3, bias=0.08 - 0.04 * i,
                   group=f"tab{i}")
    belt = [(3.3, 10.3), (12.7, 10.3), (12.9, 12.2), (3.1, 12.2)]
    ic.polygon(belt, "wood", edge=0.7, spec=0.4, bias=0.06, group="belt")
    ic.ellipse((8.0, 11.2), 1.3, 1.1, "gold", spec=0.9, group="buckle")
    ix = ic.resolve(thresholds={"leather": (0.13, 0.30, 0.50, 0.72), "wood": (0.1, 0.2, 0.34, 0.52, 0.8)})
    ix.remove_orphans()
    # stitching: lighter dashes along the neckline and down the flanks
    for (x, y) in ((5, 3), (10, 3), (4, 6), (4, 8), (11, 6), (11, 8)):
        if ix.mat[y, x] >= 0 and ix.mats[ix.mat[y, x]] == "leather":
            ix.set_px(x, y, "leather", 4, group="body")
    # front lacing: a dark slit crossed by light laces, collar to belt
    for y in range(5, 10):
        ix.set_px(8, y, "leather", 1, group="body")
        if y % 2 == 1:
            ix.set_px(7, y, "leather", 4, group="body")
            ix.set_px(9, y, "leather", 3, group="body")
    img = finish(ix, orphans=False, skip=("gold",))
    put_px(img, [(7, 10)], tone("gold", 5))
    return img


def moonsteel_plate() -> Image.Image:
    """Steel breastplate: shoulder caps, a ridged breast with a gold
    waxing crescent struck on it, two fauld lames with bright rivets."""
    ic = Icon(16, 16)
    m = poly_mask(ic.X, ic.Y, TORSO)
    hgt = _torso_height(ic, m)
    ridge = np.exp(-((ic.X - 8.0) / 0.8) ** 2) * np.clip((ic.Y - 4.0) / 3.0, 0.0, 1.0) * 0.45
    ic.relief(m, hgt + ridge, "steel", spec=0.9, spec_pow=6, gamma=0.9, ambient=0.16, group="breast")
    for i, y0 in enumerate((10.4, 12.3)):
        lame = [(3.2 - 0.3 * i, y0), (12.8 + 0.3 * i, y0), (13.1 + 0.3 * i, y0 + 2.1),
                (2.9 - 0.3 * i, y0 + 2.1)]
        ic.polygon(lame, "steel", edge=1.0, spec=0.9, bias=-0.05 * (i + 1), group=f"lame{i}")
    for cx, rot in ((2.9, -25.0), (13.1, 25.0)):
        ic.ellipse((cx, 4.7), 2.1, 1.7, "steel", rot=rot, spec=1.0, spec_pow=8, ambient=0.22,
                   depth=0.6, group=f"pauldron{cx}")
    ix = ic.resolve(thresholds={"steel": (0.12, 0.27, 0.44, 0.64, 0.86)})
    ix.remove_orphans()
    moon = Indexed(16, 16, IR)
    stamp_tones(moon, [".43", "4..", "3..", ".21"], (6, 5), "gold")
    ix.overlay(moon)
    img = finish(ix, orphans=False, skip=("gold",))
    put_px(img, [(3, 11), (12, 11), (3, 13), (12, 13)], tone("steel", 5))
    put_px(img, [(6, 5)], tone("gold", 5))
    return img


# ---------------------------------------------------------------------------
# Accessories
# ---------------------------------------------------------------------------
def _ring_band(ic: Icon, band: str) -> None:
    """A band seen from slightly above: the front arc thick and lit, the
    back arc thinner and in shadow, the finger hole open."""
    X, Y = ic.X, ic.Y
    co, ci = (8.0, 10.6), (8.0, 9.9)
    qo = q_ellipse(X, Y, co, 6.4, 4.7)
    qi = q_ellipse(X, Y, ci, 4.3, 2.9)
    m = (qo <= 1.0) & (qi > 1.0)
    s = np.clip((1 - qo) / np.maximum((1 - qo) + (qi - 1) * 0.6, 1e-6), 0, 1)
    hgt = np.sqrt(np.clip(1 - (2 * s - 1) ** 2, 0, None)) * 1.6
    back = m & (Y < ci[1] - 0.5)
    ic.relief(back, hgt, band, bias=-0.12, spec=0.4, spec_pow=8, gamma=1.1, group="band")
    ic.relief(m & ~back, hgt, band, spec=0.7, spec_pow=8, gamma=1.1, group="band")
    # bezel cup the stone sits in
    q = q_ellipse(X, Y, (8.0, 5.3), 4.6, 3.2)
    ic.relief(q <= 1.0, np.sqrt(np.clip(1 - q * q, 0, None)) * 2.0, band, spec=0.5, bias=-0.05,
              group="setting")


BAND_TH = {"gold": (0.12, 0.28, 0.46, 0.68, 0.90), "silver": (0.14, 0.32, 0.54, 0.80)}


def ring(stone: str, cut: str | list[str], band: str = "gold", lift: int = 0) -> Image.Image:
    """Ring icon: a band in 3/4 view with a hand-faceted stone held by four
    prongs. `cut` is a GEMS template name or a digit template of its own;
    `lift` shifts the template's tones up the stone's ramp."""
    ic = Icon(16, 16)
    _ring_band(ic, band)
    ix = ic.resolve(thresholds=BAND_TH)
    ix.remove_orphans()
    t = GEMS[cut] if isinstance(cut, str) else cut
    gw, gh = len(t[0]), len(t)
    ox, oy = 8 - gw // 2, 5 - gh // 2
    gem = Indexed(16, 16, IR)
    stamp_tones(gem, t, (ox, oy), stone, offset=lift)
    ix.overlay(gem)
    # four prongs over the stone's rim
    for x, y in ((ox, oy), (ox + gw - 1, oy), (ox, oy + gh - 1), (ox + gw - 1, oy + gh - 1)):
        if gem.mat[y, x] < 0:
            continue
        ix.set_px(x, y, band, 3 if (x == ox and y == oy) else 2, group="prong")
    img = finish(ix, orphans=False, skip=(band, stone))
    put_px(img, [(4, 13)], tone(band, -1))
    return img


# Polished black onyx: a step cut on the 6-tone onyx ramp with its table at
# the bottom tone, so the stone is still the darkest thing in a bright silver
# band; but a black table alone reads as a hole on the navy menu window, so
# the crown facet along the top is lit (O3), the upper-left facet holds one
# cold white specular (O5) and the lower right catches a lavender rim of
# reflected light (O3-O4). Corners are covered by the prongs.
ONYX_STEP: list[str] = [
    "133331",
    "350002",
    "300013",
    "200014",
    "112341",
]


def onyx_ring() -> Image.Image:
    return ring("onyx", ONYX_STEP, band="silver")


def pendant() -> Image.Image:
    """Silver Pendant: a fine chain looping down to a moonstone drop in a
    silver bezel."""
    ix = Indexed(16, 16, IR)
    for side in (-1, 1):
        ctrl = [(8 + 6.4 * side, 1.0), (8 + 5.6 * side, 5.6), (8 + 1.2 * side, 6.4)]
        pts = bezier_curve(ctrl, 12)
        ix.stroke(pts, "silver", lambda t: 3 if int(t * 11) % 2 == 0 else 1, group="chain")
    # bail
    ix.set_px(8, 6, "silver", 3, group="bail")
    ix.set_px(8, 7, "silver", 2, group="bail")
    # bezel (silver ring, 1 px) round the stone
    ic = Icon(16, 16)
    q = q_ellipse(ic.X, ic.Y, (8.0, 11.6), 3.4, 4.1)
    ic.relief(q <= 1.0, np.sqrt(np.clip(1 - q * q, 0, None)) * 1.6, "silver", spec=0.8, group="bezel")
    bz = ic.resolve(thresholds={"silver": (0.14, 0.32, 0.54, 0.80)})
    ix.overlay(bz)
    stone = Indexed(16, 16, IR)
    stamp_tones(stone, [
        "..3..",
        ".343.",
        "33432",
        "33322",
        "23221",
        "12221",
        ".112.",
    ], (6, 8), "moonstone")
    ix.overlay(stone)
    img = finish(ix, orphans=False, skip=("silver", "moonstone"))
    put_px(img, [(7, 9)], tone("moonstone", -1))
    put_px(img, [(9, 13)], (210, 226, 255))
    return img


# ---------------------------------------------------------------------------
# Consumables & relics
# ---------------------------------------------------------------------------
def vial() -> Image.Image:
    """Vial of Vitae: a round flask three-quarters full of blood. The glass
    is a 1 px lit rim; the empty top shows the dark room through it; the
    liquid glows where the light passes out of it (low right); a curved
    white reflection sits up-left, a pin glint low-right."""
    ic = Icon(16, 16)
    X, Y = ic.X, ic.Y
    c, rx, ry = (7.9, 10.5), 5.3, 4.6
    q = q_ellipse(X, Y, c, rx, ry)
    bulb = q <= 1.0
    neck = (np.abs(X - 7.9) <= 1.65) & (Y >= 3.6) & (Y <= 6.6)
    glass = bulb | neck
    ic.relief(glass, dome(glass, ic.ss, height=2.5), "glass", spec=0.6, gamma=1.0, group="glass")
    inner = q_ellipse(X, Y, c, rx - 1.15, ry - 1.1) <= 1.0
    liquid = inner & (Y >= 8.4)
    empty = (inner & (Y < 8.4)) | ((np.abs(X - 7.9) <= 0.7) & (Y >= 4.6) & (Y <= 7.0))
    ic.flat(empty, "glass_in", 0.45 - (Y - 6.0) * 0.08, group="inside")
    u = (X - c[0]) / rx
    v = (Y - c[1]) / ry
    glow = np.clip(0.30 + 0.45 * (u * 0.6 + v * 0.8), 0.0, 1.0)
    ic.flat(liquid, "vitae", glow, group="inside")
    # cork + a crimson twine tie round the neck
    ic.polygon([(6.2, 1.8), (9.6, 1.8), (9.4, 4.0), (6.4, 4.0)], "wood", edge=0.9, spec=0.3,
               ambient=0.3, group="cork")
    ic.capsule((6.0, 4.5), (9.8, 4.5), 0.65, "crimson", spec=0.4, group="tie")
    ix = ic.resolve(thresholds={"vitae": (0.14, 0.30, 0.50, 0.72, 0.92)})
    ix.remove_orphans(keep=("glass_in",))
    # meniscus: a bright 1 px line across the liquid's top
    vm = ix.mask("vitae")
    ys = np.nonzero(vm.any(axis=1))[0]
    if len(ys):
        y0 = int(ys.min())
        for x in np.nonzero(vm[y0])[0].tolist():
            ix.set_px(x, y0, "vitae", 4, group="inside")
    img = finish(ix, orphans=False, skip=("glass_in", "vitae", "glass"))
    put_px(img, [(4, 9), (4, 10), (5, 8)], tone("glass", -1))
    put_px(img, [(10, 13)], tone("vitae", -1))
    return img


def ember_draught() -> Image.Image:
    """Ember Draught: a tall apothecary bottle of banked fire -- glowing
    ember liquid, two sparks rising in the empty neck, a wired cork."""
    ic = Icon(16, 16)
    X, Y = ic.X, ic.Y
    body = poly_mask(X, Y, [(4.2, 7.0), (11.8, 7.0), (12.0, 14.0), (11.0, 15.0), (5.0, 15.0),
                            (4.0, 14.0)])
    shoulder = q_ellipse(X, Y, (8.0, 7.4), 3.9, 1.9) <= 1.0
    neck = (np.abs(X - 8.0) <= 1.4) & (Y >= 2.8) & (Y <= 7.0)
    glass = body | shoulder | neck
    ic.relief(glass, bevel(glass, 1.4, ic.ss), "glass", spec=0.6, gamma=1.0, group="glass")
    inner = poly_mask(X, Y, [(5.3, 8.3), (10.7, 8.3), (10.9, 13.4), (10.3, 14.0), (5.7, 14.0),
                             (5.1, 13.4)])
    liquid = inner & (Y >= 9.6)
    empty = (inner & (Y < 9.6)) | ((np.abs(X - 8.0) <= 0.6) & (Y >= 3.6) & (Y <= 8.4))
    ic.flat(empty, "glass_in", 0.5 - (Y - 6.0) * 0.06, group="inside")
    u = (X - 8.0) / 3.0
    v = (Y - 12.0) / 2.5
    core = np.clip(1.0 - np.hypot(u * 0.9, v * 1.1) * 0.75, 0.0, 1.0)
    ic.flat(liquid, "ember", 0.18 + core * 0.8, group="inside")
    ic.polygon([(6.6, 0.8), (9.4, 0.8), (9.3, 3.2), (6.7, 3.2)], "wood", edge=0.8, spec=0.2,
               group="cork")
    ic.capsule((6.4, 3.2), (9.6, 3.2), 0.55, "gold", spec=0.8, group="wire")
    ix = ic.resolve(thresholds={"ember": (0.16, 0.34, 0.54, 0.74, 0.90)})
    ix.remove_orphans(keep=("glass_in",))
    em = ix.mask("ember")
    ys = np.nonzero(em.any(axis=1))[0]
    if len(ys):
        y0 = int(ys.min())
        for x in np.nonzero(em[y0])[0].tolist():
            ix.set_px(x, y0, "ember", 4, group="inside")
    img = finish(ix, orphans=False, skip=("glass_in", "ember", "glass", "gold"))
    put_px(img, [(8, 8), (7, 6)], tone("ember", 4))
    put_px(img, [(5, 9), (5, 10), (5, 11)], tone("glass", -1))
    return img


WING_R: list[Pt] = [          # right wing, spread out and a little up; the left mirrors it
    (10.4, 5.2), (12.2, 3.4), (14.4, 2.4), (15.5, 2.6), (15.5, 4.8), (14.4, 5.2), (14.6, 6.9),
    (13.3, 6.8), (13.0, 8.6), (11.6, 7.9), (10.6, 7.4),
]
WING_QUILLS: list[tuple[Pt, Pt]] = [((11.4, 5.3), (14.4, 5.1)), ((11.4, 6.5), (13.3, 6.8))]


def leap_stone() -> Image.Image:
    """Leap Stone (relic): a faceted soul-blue crystal borne on two small
    swept wings (quill lines and notched trailing edges), with a few
    motes of its light hanging round it."""
    ic = Icon(16, 16)
    for side in (1, -1):
        pts = WING_R if side > 0 else [(16.0 - x, y) for x, y in WING_R]
        m = poly_mask(ic.X, ic.Y, pts)
        lift = np.clip((6.0 - ic.Y) * 0.06, -0.12, 0.2)        # upper coverts catch the light
        ic.relief(m, bevel(m, 1.2, ic.ss), "feather", spec=0.4, gamma=1.0, ambient=0.24,
                  bias=0.02 if side < 0 else -0.06, extra=lift, group=f"wing{side}")
    ix = ic.resolve(thresholds={"feather": (0.16, 0.36, 0.58, 0.80)})
    ix.remove_orphans()
    for side in (1, -1):
        for qa, qb in WING_QUILLS:
            a_ = qa if side > 0 else (16.0 - qa[0], qa[1])
            b_ = qb if side > 0 else (16.0 - qb[0], qb[1])
            for x, y in bezier_curve([a_, b_], 4):
                xi, yi = int(x), int(y)
                if 0 <= xi < 16 and 0 <= yi < 16 and ix.mat[yi, xi] >= 0:
                    ix.tone[yi, xi] = 1
    stone = Indexed(16, 16, IR)
    stamp_tones(stone, GEMS["kite"], (5, 3), "soul")
    ix.overlay(stone)
    img = finish(ix, orphans=False, skip=("feather", "soul"))
    put_px(img, [(7, 5)], tone("soul", -1))
    put_px(img, [(2, 9), (13, 11), (12, 14)], tone("soul", 3), only_opaque=False)
    return img


def heart_max_up() -> Image.Image:
    """Heart Max Up: a gold reliquary heart -- a gilt rim round a glossy
    crimson heart, a little gold finial between the lobes."""
    ic = Icon(16, 16)
    m, _ = heart_mask(ic.X, ic.Y, 1.0, 2.6, 14.0, 12.6, ic.ss)
    inner, ih = heart_mask(ic.X, ic.Y, 2.4, 4.0, 11.2, 10.0, ic.ss)
    rim = m & ~inner
    ic.relief(rim, bevel(m, 1.4, ic.ss), "gold", spec=0.8, spec_pow=8, group="rim")
    ic.relief(inner, ih, "heart_gloss", spec=0.7, spec_pow=14, ambient=0.05, gamma=1.6, group="heart")
    ic.ellipse((8.0, 2.2), 1.3, 1.3, "gold", spec=0.9, group="finial")
    ix = ic.resolve(thresholds={"heart_gloss": (0.10, 0.22, 0.38, 0.62, 0.80),
                                "gold": (0.12, 0.28, 0.46, 0.68, 0.90)})
    ix.remove_orphans()
    hm = ix.mask("heart_gloss")
    right = np.zeros_like(hm)
    right[:, 8:] = True
    ix.tone[hm & right & (ix.tone >= 5)] = 4
    ix.set_px(8, 0, "gold", 4, group="finial")
    img = finish(ix, orphans=False, skip=("gold", "heart_gloss"))
    put_px(img, [(5, 6)], tone("heart_gloss", 5))
    put_px(img, [(3, 4)], tone("gold", 5))
    return img


# ---------------------------------------------------------------------------
# Gold coin
# ---------------------------------------------------------------------------
COIN_FRAMES = 6
COIN_TICKS = 4         # docs/art_style.md: "4-6 frames of 4 ticks"


LIGHT2 = (-0.66, -0.75)     # ICON_LIGHT's screen direction
# The struck device: a 3x4 crescent (it echoes the hall's crescent banners),
# raised from the sunk field -- its outer limb lit G4, its horns and the
# shadow it casts low-right in G1/G2. (x, y, tone) at the face-on centre (5, 5).
COIN_CRESCENT: tuple[tuple[int, int, int], ...] = (
    (5, 3, 4), (6, 3, 3),           # upper horn
    (4, 4, 4), (4, 5, 4),           # limb, facing the light
    (5, 6, 2), (6, 6, 1),           # lower horn, in shadow
    (5, 5, 1),                      # shadow cast inside the crescent
)
COIN_OUTLINE_DARK = (30, 14, 10)    # bottom/right outline: keeps the coin off gold trim
COIN_GLINT_FRAMES = (0, 1, 5)       # face-on-ish frames that get the 2 px G5 rim glint


def coin(turn: float, glint: bool = False) -> Image.Image:
    """One frame of a spinning gold coin (turn 0..1 across a half turn).

    Painted per pixel at 1x by rule, the way one would by hand: a struck
    disc with a raised rim that is lit up-left (G4) and dark low-right, a
    sunk G2 field whose inner edge is shaded up-left and lit low-right, and
    a raised crescent device. `glint` adds a 2 px G5 specular on the most
    lit stretch of the rim. As it turns the face narrows and the milled
    edge (G1/G2 stripes) shows on one side. The outline is darkened along
    the bottom and right so the coin keeps its silhouette on gold trim."""
    ix = Indexed(10, 10, IR)
    th = turn * math.pi
    w = abs(math.cos(th))
    a, b = max(0.55, 4.0 * w), 4.0
    sgn = 1.0 if math.cos(th) >= 0 else -1.0     # past edge-on the far face shows: rim swaps side
    edge = 1.0 if 0.05 < turn < 0.95 else 0.0
    cx, cy = 5.0 + 0.5 * edge * sgn, 5.0
    rim_q = min(0.74, 1.0 - 0.95 / a)          # ~1 px of rim however narrow the face
    rim_lit: list[tuple[float, int, int]] = []
    for y in range(10):
        for x in range(10):
            dx, dy = x + 0.5 - cx, y + 0.5 - cy
            q = math.hypot(dx / a, dy / b)
            qe = math.hypot((dx + edge * sgn) / max(a, 0.55), dy / b)
            f = 0.0
            if q > 1e-6:
                f = (dx / a * LIGHT2[0] + dy / b * LIGHT2[1]) / max(q, 1e-6)
            if q <= 1.0:
                if a < 1.2:                      # edge-on: the face is a sliver
                    t = 3 if f > 0 else 2
                elif q > rim_q:
                    t = 4 if f > 0.2 else 3 if f > -0.45 else 2 if f > -0.88 else 1
                    rim_lit.append((f, x, y))
                else:                            # sunk field, shaded by the rim up-left
                    t = 2
                    if q > 0.45:
                        t = 1 if f > 0.35 else 3 if f < -0.45 else 2
                ix.set_px(x, y, "gold", t, group="face")
            elif edge and qe <= 1.0:
                ix.set_px(x, y, "gold", (3 if y < 4 else 2) if y % 2 == 0 else 1, group="edge")
    if a >= 2.8:                                 # the struck crescent, foreshortened with the face
        k = a / 4.0
        for px_, py_, t in COIN_CRESCENT:
            x = int(math.floor(cx + (px_ + 0.5 - 5.0) * k))
            if ix.mat[py_, x] >= 0:
                ix.set_px(x, py_, "gold", t, group="face")
    img = ix.selout(lit_tone=1, light=ICON_LIGHT)
    if glint and rim_lit:
        rim_lit.sort(reverse=True)
        f0, x0, y0 = rim_lit[0]
        nxt = [(f, x, y) for f, x, y in rim_lit[1:] if max(abs(x - x0), abs(y - y0)) == 1]
        pts = [(x0, y0)] + ([(nxt[0][1], nxt[0][2])] if nxt else [])
        put_px(img, pts, tone("gold", -1))
    dark0 = tone("gold", 0)
    img = img.copy()
    px = img.load()
    for y in range(10):
        for x in range(10):
            r, g, bb, al = px[x, y]
            if al == 0 or (r, g, bb) != dark0:
                continue
            open_right = x == 9 or px[x + 1, y][3] == 0
            open_below = y == 9 or px[x, y + 1][3] == 0
            if open_right or open_below:
                px[x, y] = COIN_OUTLINE_DARK + (255,)
    return img


def coin_frames() -> list[Image.Image]:
    return [coin(i / COIN_FRAMES, glint=i in COIN_GLINT_FRAMES) for i in range(COIN_FRAMES)]


def gold_icon() -> Image.Image:
    """10x10 HUD/menu gold icon: the coin face-on with its G5 rim glint."""
    return coin(0.0, glint=True)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def icons() -> dict[str, Image.Image]:
    """Every 16x16 icon this module draws, by output file name."""
    return {
        "armor_leather": leather_cuirass(),
        "armor_moonsteel": moonsteel_plate(),
        "necklace_silver": pendant(),
        "ring_ruby": ring("gem_ruby", "oval"),
        "ring_jade": ring("gem_jade", "cabochon"),
        "ring_onyx": onyx_ring(),
        "vial_of_vitae": vial(),
        "ember_draught": ember_draught(),
        "leap_stone": leap_stone(),
        "heart_max_up": heart_max_up(),
    }


def build() -> None:
    icon_set = icons()
    for name, img in icon_set.items():
        img.save(os.path.join(SPRITES, f"{name}.png"))

    # The coin spins, so it ships as a little sheet rather than a still.
    sb = SheetBuilder("gold_coin", 10, 10)
    sb.add("spin", coin_frames(), 0, True, ticks=[COIN_TICKS] * COIN_FRAMES)
    sb.save()
    gold_icon().save(os.path.join(UI, "gold_icon.png"))

    print("equipment: %d icons, gold_coin" % len(icon_set))


if __name__ == "__main__":
    build()
