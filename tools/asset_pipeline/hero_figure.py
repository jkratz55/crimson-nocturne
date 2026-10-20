"""
Vesper figure assembly: one solved `Rig` + one `SimFrame` of follower
chains -> one finished 128x80 frame.

Painter order (back to front): cape sheet, far arm, far coat tail, far leg,
near leg, near coat tail, torso (belt, frogging, lapel), near arm, capelet,
ribbon tails, ponytail, head, ribbon bow, near arm over the capelet (attacks), far arm in
front (throw). Then: orphan merge, cloth cleanup, cast shadows, rim, sel-out,
tooth AA, polish, edge sweep; then the weapon layer (own outline) is composited on top or
underneath, and the CLUT turns indices into RGBA.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from hero_paint import (
    BACK_HEAD, FLOOR_Y, H, HAND_LEGEND, HANDS, HEAD_LEGEND, HEADS, L2, MID, W, XX, YY, Canvas, ClothArt, Pt,
    ToneMemory,
    WeaponDraw, addp, catmull, cloth_grid, composite_weapon, dilate4, paint_blob, paint_cloth,
    paint_hair_clump, paint_limb, poly_mask, pp_line, ray_exit, render_weapon, resample, rnd, sabre_tip, shift,
)
from hero_rig import SLASH_FLAT, Pose, Rig, SimFrame, anchors, foot_points, solve

NU_CAPE, NS_CAPE = 44, 64


@dataclass
class Frame:
    """A finished frame: RGBA plus the index buffers (palette swaps, hit
    masks) and the weapon anchor the manifest records."""
    rgba: np.ndarray
    mat: np.ndarray
    tone: np.ndarray
    hand: Pt
    weapon: WeaponDraw
    tip: Pt | None
    wmask: np.ndarray            # pixels written by the weapon layer
    part: np.ndarray | None = None   # part index per pixel (0 = outline / empty), for checks
    names: tuple[str, ...] = ()      # part names indexed by `part`


# --------------------------------------------------------------------------
# Cloth sheets from simulated chains
# --------------------------------------------------------------------------
def _rel(chain: np.ndarray, ns: int) -> tuple[np.ndarray, float]:
    pts = catmull([(float(x), float(y)) for x, y in chain], 4)
    rel, ln = resample(np.asarray(pts) - chain[0], ns)
    return rel, ln


def cape_sheet(sec: SimFrame, art: ClothArt, length_scale: float = 1.0, trail: float = 0.0
               ) -> tuple[np.ndarray, ...]:
    """Cape sheet between the two simulated edge chains. `trail` lengthens
    the strands toward the trailing edge (u = 1) so the hem flares back
    instead of rising toward the back corner."""
    c0, c1 = sec.chains["cape0"], sec.chains["cape1"]
    rel0, _ = _rel(c0, NS_CAPE)
    rel1, _ = _rel(c1, NS_CAPE)
    us = np.linspace(0, 1, NU_CAPE)
    r0, r1 = c0[0], c1[0]
    roots = np.stack([r0[0] + (r1[0] - r0[0]) * us, r0[1] + (r1[1] - r0[1]) * us + 0.9 * np.sin(np.pi * us)], 1)
    ss = np.linspace(0, 1, NS_CAPE)
    rel = (1 - us)[:, None, None] * rel0[None] + us[:, None, None] * rel1[None]
    # 3 shallow hem points (scalloped hem), kept off the back corner (u > 0.85) so the
    # trailing corner stays square, + the trailing edge a little longer
    taper = np.clip((0.95 - us) / 0.1, 0.0, 1.0)
    scal = 1.0 + (1.2 * us - 1.2 * (0.5 + 0.5 * np.cos(6 * np.pi * us)) * taper) / 28.0
    rel = rel * (scal * length_scale * (1.0 + trail * us))[:, None, None]
    if art.wave:
        tan = np.gradient(rel, axis=1)
        tn = np.hypot(tan[..., 0], tan[..., 1]) + 1e-9
        nx, ny = -tan[..., 1] / tn, tan[..., 0] / tn
        U, S = np.meshgrid(us, ss, indexing="ij")
        amp = art.wave * S ** 1.3
        wv = amp * np.sin(2 * np.pi * art.wave_k * S - art.wave_phase + 0.8 * U)
        rel = rel + np.stack([nx * wv, ny * wv], -1)
    return cloth_grid(roots, rel)


def tail_sheet(chain: np.ndarray, root0: Pt, root1: Pt, fan: float, nu: int = 14, ns: int = 26,
               shorten: float = 0.0) -> tuple[np.ndarray, ...]:
    rel, _ = _rel(chain, ns)
    us = np.linspace(0, 1, nu)
    roots = np.stack([root0[0] + (root1[0] - root0[0]) * us, root0[1] + (root1[1] - root0[1]) * us], 1)
    out = np.zeros((nu, ns, 2))
    for i, u in enumerate(us):
        a = math.radians(fan * (u - 0.5))
        c, s = math.cos(a), math.sin(a)
        k = 1.0 - shorten * u
        out[i, :, 0] = (rel[:, 0] * c - rel[:, 1] * s) * k
        out[i, :, 1] = (rel[:, 0] * s + rel[:, 1] * c) * k
    return cloth_grid(roots, out)


# --------------------------------------------------------------------------
# Body parts
# --------------------------------------------------------------------------
def paint_leg(cv: Canvas, r: Rig, side: str, darker: int) -> None:
    J = r.J
    hip, knee, ank = J["hip" + side], J["knee" + side], J["ank" + side]
    pitch = r.p.pitch_n if side == "N" else r.p.pitch_f
    # value layering: the near leg sits on tone 3 (Y ~60), the far leg one step behind
    paint_limb(cv, "thigh" + side, hip, knee, 1.8, 1.4, "trousers", 3, th=(-0.1, 0.66), darker=darker)
    top = knee if (side == "N" and r.p.kneel_n) else addp(knee, (knee[0] - ank[0], knee[1] - ank[1]), 0.14)

    def boot_extra(tone: np.ndarray, t: np.ndarray, lat: np.ndarray, I: np.ndarray) -> np.ndarray:
        tone = tone.copy()
        tone[t < 0.13] = 4 - darker                      # 1-px cuff line at the boot top
        return tone
    # boots: darker glossy leather than the matte trousers: base 2, lit front half,
    # a tone-4 cuff line and (near boot) a 1-px polish streak down the shin front
    bpid, bmask, _ = paint_limb(cv, "boot" + side, top, ank, 1.65, 1.1, "boot", 2, th=(-0.25, 0.42),
                                extra=boot_extra, darker=darker)
    if darker == 0:
        # the streak is a drawn line riding the shin (one pixel in from its lit edge), so it
        # travels with the leg instead of re-thresholding into fragments every drawing
        dx, dy = ank[0] - top[0], ank[1] - top[1]
        ln = math.hypot(dx, dy) or 1.0
        nrm = (-dy / ln, dx / ln)
        if nrm[0] * L2[0] + nrm[1] * L2[1] < 0:
            nrm = (-nrm[0], -nrm[1])
        a0 = addp(addp(top, (dx, dy), 0.26), nrm, 0.75)
        a1 = addp(addp(top, (dx, dy), 0.74), nrm, 0.6)
        for (x, y) in pp_line([a0, a1]):
            if 0 <= x < W and 0 <= y < H and bmask[y, x] and cv.part[y, x] == bpid:
                cv.tone[y, x] = 4
                cv.lock[y, x] = True
    pts = foot_points(ank, pitch)
    if not r.p.airborne and not r.p.rot:
        # a planted toe bends at the ball: the toe stays on the floor
        pts = [(x, min(y, FLOOR_Y)) for x, y in pts]
    fm = poly_mask(pts)
    pid = paint_blob(cv, "foot" + side, fm, "boot", 2 - darker, sh=1.0, hi=1.2, sep=True)
    toe = addp(ank, (4.3 * math.cos(math.radians(pitch)) - 2.6 * math.sin(math.radians(pitch)),
                     4.3 * math.sin(math.radians(pitch)) + 2.6 * math.cos(math.radians(pitch))))
    tx, ty = rnd(toe)
    for (x, y) in ([(tx, ty), (tx - 1, ty)] if darker == 0 else [(tx, ty)]):
        if 0 <= x < W and 0 <= y < H and fm[y, x]:
            cv.px(x, y, "gold", 3 if (x, y) == (tx, ty) else 2, pid)


def paint_arm(cv: Canvas, r: Rig, side: str, darker: int) -> None:
    J = r.J
    sh, el, wr, hd = J["sh" + side], J["elb" + side], J["wri" + side], J["hand" + side]
    # sleeves: the near sleeve gets a wider lit flank so it reads over the coat
    lit = 0.3 if side == "N" else 0.58
    _, um, _ = paint_limb(cv, "upper" + side, sh, el, 1.65, 1.4, "coat", 3, th=(-0.08, lit), darker=darker)
    _, fm, _ = paint_limb(cv, "fore" + side, el, wr, 1.45, 1.3, "coat", 3, th=(-0.08, lit), darker=darker)
    if side == "N" and darker == 0:
        # a 1-px CO5 highlight on the sleeve's lit edge (the edge facing the key light), from
        # the shoulder down the upper arm and onto the forearm: the coat's brightest plane
        arm = (um | fm) & (cv.mat == MID["coat"])
        lx, ly = (1 if L2[0] > 0 else -1), (1 if L2[1] > 0 else -1)
        edge = arm & (~shift(arm, lx, 0) | ~shift(arm, 0, ly)) & ~shift(arm, lx, ly)
        d_sh = np.hypot(XX - sh[0], YY - sh[1])
        hl = edge & (d_sh <= 13.0) & ~cv.lock
        cv.tone[hl] = 5
        cv.lock[hl] = True
    # 2-px gold cuff across the wrist
    d = (wr[0] - el[0], wr[1] - el[1])
    ln = math.hypot(*d) or 1.0
    nx, ny = -d[1] / ln, d[0] / ln
    pid = cv.new_part("cuff" + side)
    for j, k in enumerate((-0.7, -1.6)):
        c = addp(wr, d, k / ln)
        for i, (x, y) in enumerate(pp_line([addp(c, (nx, ny), -1.4), addp(c, (nx, ny), 1.4)])):
            tone = (4 if i == 0 else 3) if j == 0 else (3 if side == "N" else 2)
            cv.px(x, y, "gold", max(1, tone - darker), pid, lock=False)
    grip = r.p.grip_n if side == "N" else r.p.grip_f
    rows, (ax, ay) = HANDS[grip]
    hx, hy = rnd(hd)
    cv.stamp(rows, HAND_LEGEND, hx - ax, hy - ay, "hand" + side, sep=True)


def paint_torso(cv: Canvas, r: Rig) -> np.ndarray:
    p = r.p
    ys = max(-0.6, min(1.25, math.sin(math.radians(p.yaw)) / math.sin(math.radians(35.0))))
    T = r.T
    back = lambda k: -(k[0] + k[1] * ys)   # noqa: E731
    front = lambda k: (k[0] + k[1] * ys)   # noqa: E731
    pts = [T("pelvis", back((3.0, 0.8)), 1.5), T("pelvis", back((2.7, 0.7)), 4.2),
           T("pelvis", back((3.3, 1.1)), 8.5), T("neck", back((3.5, 1.5)), -1.2),
           T("neck", -1.5, 0.3), T("neck", 1.6, 0.3), T("neck", front((3.3, 1.7)), -1.4),
           T("pelvis", front((3.4, 1.6)), 9.0), T("pelvis", front((2.8, 0.8)), 4.6),
           T("pelvis", front((2.7, 0.9)), 1.5)]
    tm = poly_mask(pts)
    hot = T("neck", 2.6 * ys, -4.4)
    # lit plane on the chest front (wider when the chest is open to the camera)
    cfront = T("pelvis", front((1.0, 1.2)), 8.0)
    lit_plane = ((XX - cfront[0]) * r.rt[0] + (YY - cfront[1]) * r.rt[1] > 0) if ys > 0.2 else None
    paint_blob(cv, "torso", tm, "coat", 3, sh=2.4, hi=1.8, hot=hot, hot_r=2.8, sep=True, lit_extra=lit_plane)
    # satin specular: one CO6 jewel on the chest hot spot's CO5 pixel nearest its centre
    hot_px = tm & (cv.mat == MID["coat"]) & (cv.tone == 5)
    cv.lock |= hot_px                  # a designed highlight cluster: the cloth cleanup keeps it
    hs_y, hs_x = np.nonzero(hot_px)
    if len(hs_x) >= 3:                 # only on a real highlight cluster (no 1-px blinking)
        j = int(np.argmin((hs_x - hot[0]) ** 2 + (hs_y - hot[1]) ** 2))
        cv.px(int(hs_x[j]), int(hs_y[j]), "coat", 6, "coat_spec")
    # belt + buckle
    bm = poly_mask([T("pelvis", -4.4, 3.3), T("pelvis", 4.4, 3.3), T("pelvis", 4.4, 5.2),
                    T("pelvis", -4.4, 5.2)]) & tm
    cv.put(bm, "leather", np.where(shift(bm, 0, -1), 1, 2), "belt")
    if ys > -0.2:
        bx, by = rnd(T("pelvis", front((1.4, 1.0)), 4.3))
        cv.px(bx, by, "gold", 4, "buckle")
        cv.px(bx, by + 1, "gold", 2, "buckle")
    # three tapered gold frogging bars across the chest front
    if ys > 0.25:
        for b, a0, a1 in ((11.2, 0.3, 3.3), (9.4, 0.5, 3.0), (7.6, 0.8, 2.7)):
            seg = pp_line([T("pelvis", a0 * ys + 0.2, b), T("pelvis", a1 * ys + 0.4, b)])
            pid = cv.new_part("frog")
            for i, (x, y) in enumerate(seg):
                if 0 <= x < W and 0 <= y < H and tm[y, x]:
                    cv.px(x, y, "gold", 4 if i == len(seg) - 1 else 3, pid)
    # folded-back crimson lapel: a 1-px edge down the coat front from the collar
    if ys > 0.1:
        pid = cv.new_part("lapel")
        for k, (a, b) in enumerate(((1.4, -1.6), (2.0, -2.6), (2.5, -3.6))):
            x, y = rnd(T("neck", a * ys + 0.2, b))
            if 0 <= x < W and 0 <= y < H and tm[y, x]:
                cv.px(x, y, "cape_in", (3, 2, 2)[k], pid)
    return tm


def paint_capelet(cv: Canvas, r: Rig, sec: SimFrame) -> np.ndarray:
    """Short capelet over the near shoulder and back: a designed bell whose
    free hem is sheared by the simulated capelet pendulum; lit shoulder ball,
    one crease, sheen hem, and the hem turning up to flash the lining."""
    p = r.p
    c = sec.chains["capelet"]
    rest_tip = (c[0][0] + 0.0, c[0][1] + 6.0)
    wdx = float(np.clip((c[-1][0] - rest_tip[0]) * 0.9, -4.0, 4.0))
    wdy = float(np.clip(-(c[-1][1] - rest_tip[1]) * 0.9, -2.0, 4.0))
    ys = max(-0.6, min(1.25, math.sin(math.radians(p.yaw)) / math.sin(math.radians(35.0))))
    k = 0.75 + 0.25 * ys
    # the back hem point steps out >= 2 px past the cape's back contour (layered silhouette)
    spec = [(1.0, -0.2, 0.0), (0.4 * k, -3.6, 0.35), (-0.4, -7.2, 1.0), (-2.6, -8.4, 1.0), (-4.4, -7.0, 0.9),
            (-6.2, -8.4, 1.0), (-9.6 * k - 0.4, -7.8, 1.0), (-7.8 * k - 0.4, -4.4, 0.6), (-5.2 * k, -1.6, 0.2),
            (-3.0 * k, 0.4, 0.0), (-1.0, 0.8, 0.0)]
    pts = []
    neck = r.J["neck"]
    # the free hem hangs toward gravity instead of turning rigidly with a leaning torso
    hang = -math.radians(r.p.lean if not r.p.rot else 0.0) * 0.65
    for a, b, dd in spec:
        x, y = r.T("neck", a, b)
        ang = hang * dd
        vx, vy = x - neck[0], y - neck[1]
        x, y = neck[0] + vx * math.cos(ang) - vy * math.sin(ang), neck[1] + vx * math.sin(ang) + vy * math.cos(ang)
        pts.append((x + wdx * dd, y - wdy * dd))
    m = poly_mask(pts)
    ys_, xs_ = np.nonzero(m)
    if len(ys_) == 0:
        return m
    top, bot = ys_.min(), ys_.max()
    rel = (YY - top) / max(bot - top, 1)
    dl = ray_exit(m, L2)
    # lifted a step off the cape behind it: lit shoulder CX4, body CX3
    tone = np.where(rel < 0.36, 4, 3)
    hot = r.T("neck", -4.8 * k, -2.8)
    tone = np.where((np.hypot(XX - hot[0], YY - hot[1]) <= 1.7) & (dl > 1), 4, tone)
    lowest = np.zeros((H, W), bool)
    for x in np.unique(xs_):
        lowest[ys_[xs_ == x].max(), x] = True
    free = lowest & (YY > r.T("neck", 0, -5.0)[1])
    mats = np.full((H, W), MID["cape_out"], np.int16)
    tone = np.where(free, 4, tone)
    # the lifted hem shows the crimson lining (1 px) when the capelet is blown up
    if wdy > 1.2:
        lift = free & shift(free, 0, 0)
        mats = np.where(lift, MID["cape_in"], mats)
        tone = np.where(lift, 3, tone)
    cv.put(m, mats, tone, "capelet", sep=True)
    c0 = r.T("neck", -4.2 * k, -3.4)
    c1 = r.T("neck", -4.4 * k, -6.8)
    c1 = (c1[0] + wdx * 0.9, c1[1] - wdy * 0.9)
    for (x, y) in pp_line([c0, c1])[1:]:
        if 0 <= y < H and 0 <= x < W and m[y, x]:
            cv.tone[y, x] = 1
    # crimson brooch with a gold setting where the cape fastens at the front shoulder
    bx, by = rnd(r.T("neck", 1.3, -1.8))
    pid = cv.new_part("brooch")
    for (x, y, mm, t) in ((bx, by, "cape_in", 4), (bx, by + 1, "cape_in", 2), (bx + 1, by, "gold", 3),
                          (bx + 1, by + 1, "gold", 2), (bx, by - 1, "gold", 5)):
        cv.px(x, y, mm, t, pid)
    return m


def paint_pony(cv: Canvas, sec: SimFrame) -> None:
    """Low ponytail (12-13 px) from the simulated chain: one tapered clump
    ending in a single 1-px point, with H3 along its lit upper edge all the way
    to the tip. Only while it streams out (closer to horizontal than vertical:
    run, backdash, the fall canopy) does a second strand split off near the
    end, with a 1-px H1 parting."""
    ch = sec.chains["pony"]
    main = catmull([(float(x), float(y)) for x, y in ch], 5)
    m1, t1 = paint_hair_clump(main, 1.8, 0.45, 2, True, lit=0.62, tip_lit=True)
    any_m = m1
    tone = t1
    span = (main[-1][0] - main[0][0], main[-1][1] - main[0][1])
    if abs(span[0]) > abs(span[1]) * 1.15:
        k = int(len(main) * 0.55)
        st = main[k]
        d = (main[-1][0] - main[k][0], main[-1][1] - main[k][1])
        ln = math.hypot(*d) or 1.0
        d = (d[0] / ln, d[1] / ln)
        side = (d[1], -d[0]) if d[0] < 0 else (-d[1], d[0])
        sub = catmull([st, addp(addp(st, d, 2.4), side, -0.9), addp(addp(st, d, 4.6), side, -2.2)], 5)
        m2, t2 = paint_hair_clump(sub, 1.0, 0.45, 2, False)
        any_m = m1 | m2
        tone = np.where(m1, t1, t2)
        tone = np.where(m2 & ~m1 & dilate4(m1), 1, tone)
    cv.put(any_m, "hair", tone, "pony", sep=True, sep_mats=["cape_out", "coat", "cape_in"])


def paint_ribbon_tails(cv: Canvas, sec: SimFrame) -> None:
    """The ribbon's two 1-px tails (3rd-order lag), painted before the ponytail: they
    hang a little steeper than the tail, so they show along its underside instead
    of lying over the hair as a red patch."""
    pid = cv.new_part("ribbon")
    for name, tone in (("rib0", 2), ("rib1", 3)):
        pts = [(float(x), float(y)) for x, y in sec.chains[name]]
        for i, (x, y) in enumerate(pp_line(pts)[1:]):
            cv.px(x, y, "cape_in", tone if i < 2 else tone - 1, pid)


def paint_ribbon_bow(cv: Canvas, sec: SimFrame, knot: Pt) -> None:
    """Crimson 3x2 bow tied round the ponytail's root, painted over the hair. It is
    pushed 1 px off the tail toward its upper (outer) side, so it straddles the
    silhouette edge instead of sitting inside the hair next to the lapel."""
    ch = sec.chains["pony"]
    d = (float(ch[1][0] - ch[0][0]), float(ch[1][1] - ch[0][1]))
    ln = math.hypot(*d) or 1.0
    nrm = (d[1] / ln, -d[0] / ln)
    if nrm[1] > 0 or (abs(nrm[1]) < 1e-6 and nrm[0] > 0):
        nrm = (-nrm[0], -nrm[1])
    c = addp(knot, nrm, 1.0)
    kx, ky = int(math.floor(c[0] + 0.5)), int(math.floor(c[1] + 0.5))
    pid = cv.new_part("ribbon")
    for (dx, dy, t) in ((-1, 0, 3), (0, 0, 4), (1, 0, 3), (-1, 1, 2), (1, 1, 2)):
        cv.px(kx + dx, ky + dy, "cape_in", t, pid)


def paint_head(cv: Canvas, r: Rig) -> Pt:
    """Head stamp (rotated in quarter turns for the somersault, anchored on the
    neck by the rig; while the figure is upside down the face is turned away,
    so the back-of-head stamp is used). Returns the ribbon knot position (the
    same point the ribbon chains hang from)."""
    rows = list(HEADS[r.p.head].rows)
    hx, hy = r.head_xy
    if r.p.rot:
        if 90.0 < r.p.rot % 360.0 < 270.0:
            rows = list(BACK_HEAD.rows)
        arr = np.rot90(np.array([list(row) for row in rows]), -r.head_k)
        rows = ["".join(row) for row in arr]
    cv.stamp(rows, HEAD_LEGEND, hx, hy, "head", sep=True)
    a = anchors(r)
    return ((a["rib0"][0] + a["rib1"][0]) / 2.0 + 0.1, a["rib0"][1])


# --------------------------------------------------------------------------
# Frame
# --------------------------------------------------------------------------
def weapon_of(r: Rig, prev_tip: Pt | None) -> tuple[WeaponDraw, Pt | None]:
    p = r.p
    hand = r.J["handN"]
    if p.weapon == "sabre":
        grip = addp(hand, (0.0, 0.0))
        wd = WeaponDraw("sabre", grip, p.blade, behind=p.blade_behind)
        wd.length *= p.blade_len
        wd.curve *= p.blade_len
        tip = sabre_tip(grip, p.blade, wd.length, wd.curve)
        if p.smear > 0 and prev_tip is not None:
            # the cut is flat: the tip runs round an ellipse centred under the near shoulder
            # on the blade line, from behind the body past the camera side (lower on screen)
            # to the front, i.e. counter-clockwise on screen
            k = SLASH_FLAT
            piv = (r.J["shN"][0], hand[1])
            t0 = prev_tip
            if p.smear_sweep > 0:
                # the arc's tail sits `smear_sweep` degrees back along the swing from this
                # frame's tip, on the path the tip runs now (the arm is already out)
                a = math.atan2((tip[1] - piv[1]) / k, tip[0] - piv[0]) + math.radians(p.smear_sweep)
                rad = math.hypot(tip[0] - piv[0], (tip[1] - piv[1]) / k)
                t0 = (piv[0] + rad * math.cos(a), piv[1] + k * rad * math.sin(a))
            wd.smear = (piv, t0, tip, p.smear, k)
        return wd, tip
    if p.weapon == "whip":
        return WeaponDraw("whip", hand, whip=list(p.whip), spark=p.spark), (p.whip[-1] if p.whip else None)
    return WeaponDraw(), None


def render_frame(p: Pose, sec: SimFrame, mem: ToneMemory | None = None, prev_tip: Pt | None = None,
                 raw: bool = False) -> Frame:
    r = solve(p)
    cv = Canvas(mem)
    J = r.J
    # 1. cape (behind everything)
    U, S, X, Y = cape_sheet(sec, p.cape, trail=0.0 if p.rot else 0.08)
    # the outer, camera-facing part of the cape sits on CX3, the part under the arm on CX2;
    # lit fold flanks and the 1-px hem one step up (CX4), troughs one down with a CX1 core,
    # the sheen (CX5) only on the 1-px fold crests and the back rim
    paint_cloth(cv, "cape", U, S, X, Y, p.cape, folds=[(0.28, 0.4, 14.0), (0.55, 0.16), (0.82, 0.36, 11.0)],
                top_dark=0.16, sep=False, floor_y=FLOOR_Y if (p.floor and not p.airborne) else None,
                base_u=(0.35, 3), ridge=(2.2, 1.2), trough=(1.6, 1.2), core=True, width_ref=15.0,
                crest_k=(0.6, 0.85), hem_step=1)
    # 2. far arm behind the torso
    if not p.far_arm_front:
        paint_arm(cv, r, "F", darker=1)
    # 3. far coat tail (back panel), far leg
    U, S, X, Y = tail_sheet(sec.chains["tailF"], r.T("pelvis", -3.4, 2.6), r.T("pelvis", -0.6, 2.2), 10.0)
    paint_cloth(cv, "tailF", U, S, X, Y, ClothArt(), folds=[(0.5, 0.2)], out_base=2, top_dark=0.0, hem=False,
                ext="coat", lin="coat", lining=False, ridge=(1.0, 0.8), trough=(1.0, 0.6))
    paint_leg(cv, r, "F", darker=1)
    # 4. near leg, near coat tail over the near thigh
    paint_leg(cv, r, "N", darker=0)
    U, S, X, Y = tail_sheet(sec.chains["tailN"], r.T("pelvis", -3.9, 2.2), r.T("pelvis", 0.3, 2.0), 14.0,
                            shorten=0.18)
    # the near tail: one fold trough on the base, no lit flank (a 3-tone fold on a 4-5 px
    # panel was speckle)
    paint_cloth(cv, "tailN", U, S, X, Y, ClothArt(), folds=[(0.42, 0.25)], out_base=3, top_dark=0.0, hem=False,
                ext="coat", lin="coat", lining=False, ridge=(0.0, 0.0), trough=(1.4, 1.0))
    # 5. torso (coat body) + jewellery
    tm = paint_torso(cv, r)
    # 6. near arm under the capelet
    if not p.arm_over:
        paint_arm(cv, r, "N", darker=0)
    # 7. capelet
    cm = paint_capelet(cv, r, sec)
    # 8. ribbon tails, ponytail, head, ribbon bow
    paint_ribbon_tails(cv, sec)
    paint_pony(cv, sec)
    knot = paint_head(cv, r)
    paint_ribbon_bow(cv, sec, knot)
    # 9. arms in front
    if p.arm_over:
        paint_arm(cv, r, "N", darker=0)
    if p.far_arm_front:
        paint_arm(cv, r, "F", darker=0)
    # finishing
    cv.cleanup()
    cv.cloth_cleanup()
    head = cv.part_mask("head")
    cv.cast_shadow(head, cv.part_mask("torso", "capelet"), depth=1)
    cv.cast_shadow(cm, cv.part_mask("torso", "upperN", "foreN"), depth=1)
    cv.cast_shadow(cm, cv.part_mask("cape"), depth=1)        # 1-px shade line under the capelet hem
    cv.rim()
    cv.cloth_cleanup(final=True)
    cv.outline()
    cv.aa()
    cv.polish()
    cv.edge_sweep()
    wd, tip = weapon_of(r, prev_tip)
    wmask = composite_weapon(cv, render_weapon(wd), wd)
    if mem is not None:
        mem.advance()
    return Frame(cv.rgba(raw), cv.mat.copy(), cv.tone.copy(), J["handN"], wd, tip, wmask, cv.part.copy(),
                 tuple(cv.names))
