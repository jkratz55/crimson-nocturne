"""
Hero sprite generator: "Vesper", a dhampir swordsman (SotN-style art pass).

    python3 tools/asset_pipeline/hero.py

Writes assets/sprites/vesper.png + vesper.json and
resources/sprite_frames/vesper_frames.tres.

Frame contract (player.tscn Sprite offset (0, -36)): 128x80 frames, body
centred on x = 64, the soles' lowest opaque row is y = 75 on grounded frames,
~48 px sole to crown, 3/4 contrapposto, drawn facing right (the engine flips
it). Every animation is authored in 60 Hz ticks (SpriteFrames speed 60,
per-frame duration = ticks).

Module map:
- hero_paint.py  : the 1x painter (index buffer, designed bands, cloth,
                   stamps, weapon layer, finishing passes, CLUT).
- hero_rig.py    : pose model, IK skeleton, run gait, follower simulation.
- hero_figure.py : one pose + one follower state -> one finished frame.
- hero.py        : this file: the pose library, the animation table (frames,
                   ticks, entry states), the timing-window contract and the
                   sheet export.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field, replace
from typing import Callable

import numpy as np
from PIL import Image

from common import HERO_CENTER_X, HERO_FOOT_Y, HERO_FRAME_H, HERO_FRAME_W, SPRITES, SheetBuilder
from hero_figure import Frame, render_frame
from hero_paint import ClothArt, Pt, ToneMemory
from hero_rig import (
    CHAINS, RUN_CYCLE, RUN_TICKS, STAND_Y, Pose, Sim, SimFrame, anchors, flat_blade, keyed, lerp_pose, mirror_sim,
    rest_shape, run_pose, simulate, solve,
)

FW, FH = HERO_FRAME_W, HERO_FRAME_H
ORIGIN = (HERO_CENTER_X, HERO_FOOT_Y)

# ==========================================================================
# Timing contract (60 Hz ticks before AnimatedSprite2D.speed_scale)
# ==========================================================================
# Hitbox windows: active_frames in resources/weapons/*.tres must match.
SWORD_TICKS = [2, 1, 2, 3, 4, 2, 1]            # startup 3 | active 9 | recovery 3
SWORD_ACTIVE = (2, 4)
WHIP_TICKS = [2, 2, 2, 2, 2, 2, 2, 1]          # startup 6 | active 6 | recovery 3 (speed_scale 0.72)
WHIP_ACTIVE = (3, 5)
THROW_TICKS = [4, 3, 2, 2]                     # frame 0 = 4, projectile spawns on frame 1
THROW_SPAWN_FRAME = 1


def _window(ticks: list[int], active: tuple[int, int]) -> tuple[int, int, int]:
    a, b = active
    return sum(ticks[:a]), sum(ticks[a:b + 1]), sum(ticks[b + 1:])


assert _window(SWORD_TICKS, SWORD_ACTIVE) == (3, 9, 3)
assert _window(WHIP_TICKS, WHIP_ACTIVE) == (6, 6, 3)
assert THROW_TICKS[0] == 4 and sum(THROW_TICKS[1:]) == 7


# ==========================================================================
# Pose library
# ==========================================================================
def stand(**kw: object) -> Pose:
    return replace(IDLE, **kw)  # type: ignore[arg-type]


IDLE = Pose()                                  # 3/4 contrapposto A-stance (defaults)
IDLE_ART = ClothArt(flare=0.06)
# idle drape: the trailing edge holds its swept-back rest shape against gravity, so the
# hem flares back into SotN's draped triangle instead of hanging as a narrow column
IDLE_STIFF = {"cape0": 2.4, "cape1": 2.4,
              # standing still, the short followers (capelet hem, coat tails, ribbon tails) hold
              # their drape firmly, so a 1-px pendulum wobble never flips their edge pixels
              "capelet": 3.0, "tailN": 3.0, "tailF": 3.0, "rib0": 3.0, "rib1": 3.0}
# idle ponytail: leaves the nape ~26 deg below horizontal, clearing the capelet, and bends
# under its weight to hang ~70 deg below horizontal; its single tapered tip ~7 px behind the
# nape just breaks the capelet's back contour, so the tail reads in silhouette (no spike)
IDLE_PONY = (-64.0, -46.0, -30.0, -20.0)
# ... and sways as 2nd-order motion one drawing behind the breath (docs/art_style.md: "the idle
# ponytail sways 1 px"): it stays down while the head rises (f2), catches up (f3), stays up
# while the head settles (f4), then drops back (f5). Vertical lag of the tail per drawing
# (px at the tip, fading to 0 at the knot), against a chain that rides the head
IDLE_PONY_LAG = (0.0, 0.0, 1.0, 0.0, -1.0, 0.0)


def idle_frames() -> list[Pose]:
    """6 drawings x 7 ticks: chest, shoulders and head rise 1 px on frames
    2-3, hands follow by half a pixel, the followers sway on a slow air drift
    (never enough to flash the lining). The fold bands stay anchored in cloth
    space and ride the breath; sliding them across the sheet as well made the
    1-px band edges flip back and forth (boil) on a figure standing still."""
    out = []
    for i in range(6):
        b = (0, 0, 1, 1, 0, 0)[i]
        ph = 2 * math.pi * i / 6
        out.append(stand(breath=float(b), hand_n=(61.0, 54.5 - 0.5 * b), hand_f=(68.5, 53.5 - 0.5 * b),
                         vel=(0.05 * math.sin(ph), 0.0), cape=IDLE_ART, stiff=IDLE_STIFF,
                         drape={"pony": IDLE_PONY}))
    return out


def idle_pony(poses: list[Pose], sims: list[SimFrame]) -> list[SimFrame]:
    """The idle ponytail is drawn, not simulated: its rest shape hung from this
    drawing's nape, with the designed one-drawing lag (IDLE_PONY_LAG) growing
    toward the tip, so the tip moves exactly 1 px on two drawings and never
    jitters with the sim."""
    out = []
    spec = CHAINS["pony"]
    for i, (p, sf) in enumerate(zip(poses, sims)):
        root = anchors(solve(p))["pony"]
        c = rest_shape(IDLE_PONY, spec.length) + np.asarray(root, float)
        k = np.linspace(0.0, 1.0, len(c)) ** 1.5
        c[:, 1] += IDLE_PONY_LAG[i] * k
        out.append(SimFrame({**sf.chains, "pony": c}, sf.clock))
    return out


RUN_DRAPE = {"cape0": (-14, -18, -22, -25, -27, -28, -29), "cape1": (-26, -31, -35, -38, -40, -41, -42),
             "pony": (-84, -74, -62, -52), "rib0": (-80, -70), "rib1": (-60, -50), "tailN": (-22, -26),
             "tailF": (-16, -20), "capelet": (-20, -24)}


def run_art(tick: float) -> ClothArt:
    ph = 2 * math.pi * tick / RUN_CYCLE
    return ClothArt(flare=0.26, flare_pulse=0.8, wave=1.6, wave_k=1.7, wave_phase=2 * ph + 0.6,
                    fold_phase=ph)


# run ponytail: streams back from the nape and bobs as 2nd-order motion: a designed +/-7 deg
# swing of the whole chain over each 20-tick stride (one per foot), phase-lagged two drawings
# (5 ticks) behind the pelvis bob, on top of the simulated drag (the loose chain adds its own lag)
RUN_PONY_SWING = 7.0
RUN_PONY_LAG = 5.0


def run_pony(tick: float) -> tuple[float, ...]:
    """Ponytail rest angles at `tick` of the run. The pelvis bob peaks (lowest) at
    tick 6.5 of each 20-tick stride; the tail tip follows it RUN_PONY_LAG ticks
    late, so against the head it reads cos(th - lag) - cos(th) = sin(th - lag / 2)
    (unit amplitude): it hangs lowest ~9 ticks after the drop, highest ~9 ticks
    after the rise. + angle = toward straight down (tip lower)."""
    stride = RUN_CYCLE / 2
    w = math.sin(2 * math.pi * (tick - 6.5 - RUN_PONY_LAG / 2) / stride)
    return tuple(a + RUN_PONY_SWING * w * (0.7 + 0.1 * k) for k, a in enumerate(RUN_DRAPE["pony"]))


def run_frames() -> list[Pose]:
    starts = np.cumsum([0] + RUN_TICKS[:-1])
    return [replace(run_pose(float(t), run_art), drape={**RUN_DRAPE, "pony": run_pony(float(t))}) for t in starts]


# --- airborne -------------------------------------------------------------
JUMP_VY = -335.0 / 60.0                       # px/tick at take-off
AIR = dict(airborne=True, floor=False, plant_n=False, plant_f=False)


def air(**kw: object) -> Pose:
    base: dict[str, object] = dict(AIR)
    base.update(kw)
    return replace(IDLE, **base)  # type: ignore[arg-type]


JUMP_DRAPE = {"cape0": (-10, -12, -14, -16, -18, -19, -20), "cape1": (-24, -28, -32, -35, -37, -38, -39),
              "pony": (-40, -24, -10, 0), "tailN": (-16, -10), "tailF": (-12, -8)}
JUMP_LAUNCH = air(pelvis=(63.5, 48.5), lean=2.0, yaw=30.0, head="up", foot_n=(61.5, 67.0), pitch_n=52.0,
                  foot_f=(65.5, 67.5), pitch_f=58.0, hand_n=(58.5, 49.0), hand_f=(73.0, 35.5), elbow_f=1.0,
                  grip_f="open", vel=(0.0, JUMP_VY), cape=ClothArt(flare=0.10, wave=0.8, wave_k=1.3),
                  drape=JUMP_DRAPE, stiff={"cape0": 1.4, "cape1": 1.4})
JUMP_RISE = air(pelvis=(63.5, 48.0), lean=7.0, yaw=30.0, head="up", foot_n=(68.5, 58.5), pitch_n=26.0,
                foot_f=(61.0, 63.5), pitch_f=44.0, hand_n=(58.0, 45.5), hand_f=(72.0, 40.0), grip_f="fist",
                vel=(0.0, -3.4), cape=ClothArt(flare=0.12, wave=1.0, wave_k=1.3), drape=JUMP_DRAPE,
                stiff={"cape0": 1.4, "cape1": 1.4})
APEX = air(pelvis=(63.5, 48.0), lean=4.0, yaw=32.0, head="n", foot_n=(68.0, 60.0), pitch_n=24.0,
           foot_f=(61.0, 64.5), pitch_f=32.0, hand_n=(58.0, 47.0), hand_f=(71.0, 44.5), grip_f="relax",
           vel=(0.0, -0.4), cape=ClothArt(flare=0.12, wave=0.6))
FALL = air(pelvis=(63.5, 48.0), lean=-2.0, yaw=34.0, head="n", foot_n=(66.0, 64.5), pitch_n=26.0,
           foot_f=(60.0, 67.5), pitch_f=34.0, hand_n=(55.5, 41.0), elbow_n=-1.0, hand_f=(73.5, 42.5),
           grip_n="open", grip_f="open", vel=(0.0, 5.0),
           cape=ClothArt(flare=0.26, hem_in=0.14, wave=1.4, wave_k=1.1, face="out"),
           drape={"cape0": (-140, -146, -152, -158, -164, -170, -176), "cape1": (-88, -94, -100, -106, -112, -118, -124),
                  "pony": (-110, -124, -138, -126), "rib0": (-120, -134), "rib1": (-100, -116),
                  "capelet": (-60, -80), "tailN": (-40, -60), "tailF": (-30, -50)},
           stiff={"cape0": 1.6, "cape1": 1.6, "pony": 1.3})


FALL_FLAP = (0.0, 0.5, 1.0, 0.5)   # canopy flap over the 20-tick loop: down, rising, up, settling


def fall_frames() -> list[Pose]:
    """Fall loop, 4 x 5 ticks: the canopy flaps once per loop (the drape swings
    up-back on the up-flap, lifting the hem ~3-4 px and the ponytail ~2 px, the
    lining flare opening with it), so the umbrella breathes instead of hanging."""
    out = []
    for i in range(4):
        ph = 2 * math.pi * i / 4
        up = FALL_FLAP[i]
        drape = dict(FALL.drape)
        for k in ("cape0", "cape1"):
            drape[k] = tuple(a - 14.0 * up for a in FALL.drape[k])
        drape["pony"] = tuple(a - 8.0 * up for a in FALL.drape["pony"])
        out.append(replace(FALL, hand_n=(55.5, 41.0 + 0.5 * math.sin(ph)), hand_f=(73.5, 42.5 - 0.5 * math.sin(ph)),
                           drape=drape, cape=replace(FALL.cape, wave_phase=ph, fold_phase=ph, flare=0.26 + 0.18 * up)))
    return out


# --- crouch -----------------------------------------------------------------
CROUCH = stand(pelvis=(62.0, 65.5), lean=30.0, yaw=30.0, tilt=0.0, head="fwd", head_lean=0.6,
               foot_n=(54.0, STAND_Y), pitch_n=62.0, kneel_n=True, foot_f=(70.5, STAND_Y), knee_n=-1.0,
               hand_n=(69.5, 63.0), hand_f=(73.0, 61.5), grip_n="relax", grip_f="relax", crouch=1.0,
               cape=ClothArt(flare=0.10, hem_in=0.08), stiff={"cape0": 0.6, "cape1": 0.6})


def crouch_frames() -> list[Pose]:
    return keyed([(IDLE, CROUCH, 0.35), (IDLE, CROUCH, 0.7), (IDLE, CROUCH, 0.92), (CROUCH, None, 0.0)])


# --- sword ------------------------------------------------------------------
# A flat, horizontal cut at chest height, the genre's sword swing (never an overhead
# chop): the near arm draws the sabre back level past the hip, sweeps it round the
# camera side and snaps it straight out in front, the blade level on the hitbox line,
# holds it there, then recovers. The chest winds open toward the camera (near shoulder
# back) and closes toward profile as the shoulder comes through.
SW_READY = stand(lean=3.0, yaw=34.0, arm_over=True, weapon="sabre", blade=70.0, grip_n="grip",
                 hand_n=(62.5, 53.0))
# f0 antic, held 2 ticks: weight on the back foot, chest open, the blade pointing behind
SW_ANTIC = stand(pelvis=(62.5, 52.4), lean=-3.0, yaw=58.0, tilt=0.0, head="fwd", foot_n=(56.5, STAND_Y),
                 foot_f=(71.0, STAND_Y), hand_n=(52.5, 45.0), elbow_n=1.0, hand_f=(70.0, 47.0), grip_n="grip",
                 grip_f="fist", arm_over=True, weapon="sabre", **flat_blade(172.0), vel=(-0.6, 0.0),
                 cape=ClothArt(flare=0.08))
# the cut: front foot stepped out, chest closed so the near shoulder leads, the arm
# straight out at chest height, the off hand pulled back to the hip
SW_CUT = stand(pelvis=(65.0, 52.7), lean=8.0, yaw=18.0, tilt=0.0, head="fwd", foot_n=(56.5, STAND_Y),
               foot_f=(74.0, STAND_Y), hand_n=(79.5, 42.0), elbow_n=1.0, hand_f=(59.0, 48.5), grip_n="grip",
               grip_f="fist", arm_over=True, weapon="sabre", **flat_blade(0.0), vel=(1.4, 0.0),
               cape=ClothArt(flare=0.16, wave=0.8))
# Frame plan (ticks 2,1 | 2,3,4 | 2,1; hitbox live on f2-f4, chest height in front):
# f0 antic (above);
# f1 the 1-tick passing drawing: the hand leads round the camera side at the belt,
#    the blade swinging forward past the camera (foreshortened, angled down);
# f2 impact: arm and blade straight out, level inside the hitbox, under a broad flat
#    swoosh that comes round the camera side onto the blade (the hit-stop freezes this
#    frame, so the held hit shows the blade on the target with its sweep below it);
# f3 follow-through: the blade a hair past level (turning away), a narrower swoosh;
# f4 hold: a thin fading tail; f5-f6 recovery.
SW_PASS = replace(lerp_pose(SW_ANTIC, SW_CUT, 0.5), hand_n=(70.0, 44.0), **flat_blade(60.0), smear=0.6,
                  smear_sweep=45.0, vel=(1.0, 0.0))
SW_HIT = replace(SW_CUT, smear=1.0, smear_sweep=100.0)
SW_FOLLOW = replace(SW_CUT, pelvis=(65.2, 52.8), lean=9.0, yaw=16.0, hand_n=(80.5, 42.5), **flat_blade(-6.0),
                    smear=0.75, smear_sweep=55.0, vel=(1.0, 0.0))
SW_HOLD = replace(SW_FOLLOW, hand_n=(80.0, 43.0), **flat_blade(-8.0), smear=0.3, smear_sweep=14.0, vel=(0.2, 0.0))
SW_REC1 = replace(lerp_pose(SW_HOLD, SW_READY, 0.45), blade=38.0, blade_len=1.0, smear=0.0, weapon="sabre",
                  arm_over=True)
SW_REC2 = replace(lerp_pose(SW_HOLD, SW_READY, 0.8), blade=62.0, blade_len=1.0, smear=0.0, weapon="sabre",
                  arm_over=True)


def sword_frames() -> list[Pose]:
    return [SW_ANTIC, SW_PASS, SW_HIT, SW_FOLLOW, SW_HOLD, SW_REC1, SW_REC2]


# --- whip -------------------------------------------------------------------
WH_BASE = stand(pelvis=(64.5, 52.6), lean=9.0, yaw=30.0, tilt=0.0, head="fwd", foot_n=(56.5, STAND_Y),
                foot_f=(73.5, STAND_Y), hand_n=(76.0, 38.5), elbow_n=1.0, hand_f=(61.5, 49.5), grip_n="fist",
                grip_f="fist", arm_over=True, weapon="whip", blade=0.0, vel=(1.4, 0.0),
                cape=ClothArt(flare=0.16, wave=0.8))
WHIP_KEYS: list[tuple[dict[str, object], tuple[Pt, ...], int]] = [
    (dict(pelvis=(62.5, 52.2), lean=-5.0, yaw=8.0, head="up", hand_n=(57.5, 35.5), elbow_n=-1.0, vel=(-0.4, 0.0)),
     ((52.0, 41.0), (46.0, 47.0), (42.0, 54.0), (40.5, 61.0)), 0),
    (dict(pelvis=(62.5, 52.0), lean=-6.0, yaw=0.0, head="up", hand_n=(61.0, 30.5), elbow_n=-1.0, vel=(-0.2, 0.0)),
     ((54.0, 26.0), (45.0, 24.5), (37.0, 28.0), (31.5, 35.0)), 0),
    (dict(pelvis=(63.5, 52.3), lean=2.0, yaw=18.0, head="fwd", hand_n=(69.0, 33.0), elbow_n=1.0, vel=(0.6, 0.0)),
     ((65.0, 23.5), (56.0, 19.5), (46.0, 21.0), (38.0, 27.5)), 0),
    # f3 (first active frame): the lash has already shot out onto the hitbox line, still
    # carrying a shallow travelling wave toward the tip
    (dict(hand_n=(77.5, 39.5)), ((89.0, 42.0), (100.5, 41.5), (111.0, 43.0), (119.5, 44.5)), 0),
    (dict(hand_n=(79.0, 41.0)), ((92.0, 41.5), (104.0, 42.5), (115.0, 43.0), (124.0, 42.5)), 1),
    (dict(hand_n=(79.0, 41.5)), ((92.0, 42.5), (104.0, 44.5), (114.5, 45.0), (123.5, 44.0)), 2),
    (dict(hand_n=(76.0, 43.5), vel=(0.3, 0.0)), ((88.0, 46.5), (97.5, 50.5), (103.5, 55.0), (105.5, 59.5)), 0),
    (dict(hand_n=(71.5, 47.0), vel=(0.0, 0.0), lean=6.0), ((79.0, 53.0), (82.5, 59.0), (82.0, 65.0), (78.5, 69.0)), 0),
]


def whip_frames() -> list[Pose]:
    out = []
    for kw, pts, spark in WHIP_KEYS:
        out.append(replace(WH_BASE, whip=pts, spark=spark, **kw))  # type: ignore[arg-type]
    return out


# --- stance variants (crouch / air share frame count and timing) -----------
def crouched(p: Pose) -> Pose:
    """Same upper-body action on the crouch's legs: the hands and weapon
    drop with the shoulders."""
    dy = 13.0
    lean = max(-4.0, min(16.0, p.lean + 6.0))
    q = replace(p, pelvis=(CROUCH.pelvis[0] + (p.pelvis[0] - IDLE.pelvis[0]) * 0.5, CROUCH.pelvis[1]), lean=lean,
                foot_n=CROUCH.foot_n, pitch_n=CROUCH.pitch_n, foot_f=CROUCH.foot_f, pitch_f=0.0,
                knee_n=CROUCH.knee_n, kneel_n=True, crouch=1.0, hand_n=(p.hand_n[0] + 1.5, p.hand_n[1] + dy),
                hand_f=(p.hand_f[0] + 1.5, p.hand_f[1] + dy),
                whip=tuple((x + max(0.0, y + dy - 71.0) * 0.6, min(y + dy, 71.0)) for x, y in p.whip),
                # a blade hanging down-forward (the recovery) would cut into the floor; level or
                # pointing back (the flat cut's antic and passing drawings) it clears
                blade=min(p.blade, 16.0) if 16.0 < p.blade <= 90.0 else p.blade,
                stiff={"cape0": 0.6, "cape1": 0.6})
    return q


# Air attacks: the figure rides 3 px high (tucked, as in the fall) on the startup and
# recovery drawings, and drops onto the standing weapon line on the active frames, so
# the blade / lash is drawn where the (standing-offset) air hitbox actually is.
AIR_LIFT_SWORD = (3.0, 3.0, 0.0, 0.0, 0.0, 2.0, 3.0)
AIR_LIFT_WHIP = (3.0, 3.0, 3.0, 0.0, 0.0, 0.0, 2.0, 3.0)


def airborne(p: Pose, lift: float = 3.0) -> Pose:
    """The same upper-body action in the air: legs tucked as in the fall, and the
    cape keeps the fall canopy's drape through the swing (no pop entering or
    leaving the attack from / back to `fall`)."""
    return replace(p, airborne=True, floor=False, plant_n=False, plant_f=False,
                   pelvis=(p.pelvis[0], p.pelvis[1] - lift),
                   foot_n=(FALL.foot_n[0] + 1.0, FALL.foot_n[1] - lift), pitch_n=FALL.pitch_n,
                   foot_f=(FALL.foot_f[0] + 1.0, FALL.foot_f[1] - lift), pitch_f=FALL.pitch_f,
                   hand_n=(p.hand_n[0], p.hand_n[1] - lift), hand_f=(p.hand_f[0], p.hand_f[1] - lift),
                   whip=tuple((x, y - lift) for x, y in p.whip), vel=(p.vel[0], 1.5),
                   drape=dict(FALL.drape), stiff=dict(FALL.stiff),
                   cape=replace(FALL.cape, wave_phase=p.cape.wave_phase, fold_phase=p.cape.fold_phase, turn=0.25))


# --- throw ------------------------------------------------------------------
THROW_KEYS = [
    stand(pelvis=(62.5, 52.0), lean=-4.0, yaw=16.0, head="fwd", hand_n=(55.0, 40.0), elbow_n=1.0, grip_n="fist",
          arm_over=True, foot_n=(57.0, STAND_Y), foot_f=(71.0, STAND_Y), vel=(-0.3, 0.0)),
    stand(pelvis=(64.5, 52.4), lean=8.0, yaw=34.0, head="fwd", hand_n=(75.0, 41.0), elbow_n=1.0, grip_n="point",
          hand_f=(61.0, 50.0), arm_over=True, foot_n=(57.0, STAND_Y), foot_f=(72.5, STAND_Y), vel=(0.8, 0.0)),
    stand(pelvis=(64.5, 52.5), lean=9.0, yaw=32.0, head="fwd", hand_n=(74.0, 46.0), elbow_n=1.0, grip_n="open",
          hand_f=(61.5, 51.0), arm_over=True, foot_n=(57.0, STAND_Y), foot_f=(72.5, STAND_Y), vel=(0.2, 0.0)),
]


def throw_frames() -> list[Pose]:
    return THROW_KEYS + [replace(lerp_pose(THROW_KEYS[2], IDLE, 0.6), arm_over=True)]


# --- backdash (0.30 s state = 18 ticks) ----------------------------------------
BD_V = -250.0 / 60.0
BD_GLIDE = stand(collide=False, pelvis=(64.5, 54.0), lean=20.0, yaw=26.0, tilt=0.0, head="fwd", head_lean=0.6,
                 foot_n=(55.0, STAND_Y), pitch_n=10.0, foot_f=(70.5, STAND_Y), pitch_f=-8.0,
                 hand_n=(70.0, 52.5), hand_f=(75.5, 50.5), grip_n="relax", grip_f="open",
                 vel=(BD_V * 0.9, 0.0),
                 cape=ClothArt(flare=0.10, hem_in=0.12, wave=1.6, wave_k=1.0, face="out", turn=0.3),
                 drape={"cape0": (40, 62, 80, 94, 104, 110, 114), "cape1": (92, 106, 118, 128, 135, 140, 144),
                        "pony": (30, 52, 64, 70), "rib0": (50, 70), "rib1": (30, 50), "tailN": (30, 46),
                        "tailF": (24, 40), "capelet": (40, 50)},
                 stiff={"cape0": 1.8, "cape1": 1.8, "pony": 1.5})


def backdash_frames() -> list[Pose]:
    """Push (the cape keeps its idle mass for the 2-tick shove), glide x2 (the cape
    streams forward between shoulder and hip, never over the head: drape capped at
    90 deg), brake x2 (it droops forward, then swings back toward idle on one side
    of the body only)."""
    push = replace(BD_GLIDE, pelvis=(65.5, 54.5), lean=14.0, foot_n=(57.0, STAND_Y), pitch_n=24.0,
                   foot_f=(72.0, STAND_Y - 1.0), pitch_f=-14.0, plant_f=False, vel=(BD_V, 0.0),
                   drape={"cape0": (-6, -7, -8, -9, -10, -10, -10), "cape1": (-14, -18, -22, -26, -28, -30, -30),
                          "pony": (-40, -24, -10, 0), "rib0": (-60, -50), "rib1": (-40, -30)},
                   stiff={"cape0": 1.2, "cape1": 1.2})
    glide_drape = {"cape0": (30, 48, 62, 72, 78, 82, 84), "cape1": (60, 70, 78, 84, 88, 90, 90),
                   "pony": (30, 52, 64, 70), "rib0": (50, 70), "rib1": (30, 50), "tailN": (30, 46),
                   "tailF": (24, 40), "capelet": (40, 50)}
    g1 = replace(BD_GLIDE, drape=glide_drape)
    g2 = replace(BD_GLIDE, pelvis=(64.5, 54.5), foot_f=(70.0, STAND_Y), pitch_f=-4.0, vel=(BD_V * 0.65, 0.0),
                 cape=replace(BD_GLIDE.cape, wave_phase=1.6), drape=glide_drape)
    brake_art = ClothArt(flare=0.10, hem_in=0.10, wave=0.9, face="out", turn=0.3)
    # brake 1: the cape droops only 20-35 deg forward, hanging mostly under the shoulder; the
    # backdash `settle` then swings it home in even steps from the second glide drawing on
    # (no front-to-back swap in one drawing)
    b1 = replace(lerp_pose(BD_GLIDE, IDLE, 0.45), vel=(BD_V * 0.3, 0.0), stiff={"cape0": 1.6, "cape1": 1.6},
                 drape={"cape0": (20, 26, 30, 32, 32, 30, 28), "cape1": (28, 32, 35, 35, 33, 30, 26),
                        "pony": (0, 14, 26, 34), "rib0": (10, 30), "rib1": (0, 20)}, cape=brake_art)
    b2 = replace(lerp_pose(BD_GLIDE, IDLE, 0.8), vel=(0.0, 0.0), stiff={"cape0": 0.8, "cape1": 0.8},
                 drape={"cape0": (8, 12, 14, 14, 12, 10, 8), "cape1": (16, 20, 22, 20, 16, 12, 8)},
                 cape=replace(brake_art, wave=0.5, hem_in=0.06))
    return [push, g1, g2, b1, b2]


# --- hurt / death -----------------------------------------------------------
HURT_V = (-110.0 / 60.0, -170.0 / 60.0)
# knock-back: the body is thrown backward, so cloth inertia throws the cape forward over the
# hips (docs/art_style.md: "a hurt throws the cape forward"): it starts to swing on the impact drawing,
# streams forward between shoulder and hip on the recoil, then falls back toward idle (the
# exit blend carries the hold drawing home)
HURT_HIT = stand(collide=False, pelvis=(62.5, 51.5), lean=-13.0, yaw=40.0, head="hurt", head_d=(-1.0, 0.0),
                 hand_n=(70.5, 43.5), elbow_n=1.0, hand_f=(74.5, 46.5), grip_n="open", grip_f="open",
                 far_arm_front=True, vel=HURT_V, cape=ClothArt(flare=0.18, hem_in=0.08, wave=1.2),
                 drape={"cape0": (0, 4, 8, 10, 12, 12, 12), "cape1": (10, 18, 26, 32, 36, 38, 38)},
                 stiff={"cape0": 1.4, "cape1": 1.4})
HURT_RECOIL = replace(HURT_HIT, pelvis=(61.5, 52.5), lean=-17.0, head_d=(-1.0, 1.0), hand_n=(71.5, 39.0),
                      hand_f=(75.0, 42.0), foot_f=(70.5, STAND_Y), pitch_f=-12.0, vel=(HURT_V[0], -1.0),
                      cape=ClothArt(flare=0.10, hem_in=0.10, wave=1.0, face="out", turn=0.3),
                      drape={"cape0": (30, 44, 54, 60, 62, 62, 60), "cape1": (50, 62, 70, 74, 74, 72, 68),
                             "pony": (10, 26, 38, 46), "rib0": (20, 40), "rib1": (10, 30)},
                      stiff={"cape0": 1.2, "cape1": 1.2})
HURT_HOLD = replace(HURT_RECOIL, pelvis=(62.0, 53.5), lean=-10.0, head_d=(-1.0, 0.0), hand_n=(69.0, 46.0),
                    hand_f=(72.5, 48.0), pitch_f=0.0, vel=(-0.6, 0.0), cape=ClothArt(flare=0.12, hem_in=0.06),
                    drape={}, stiff={"cape0": 2.0, "cape1": 2.0})   # pulled firmly back onto the idle drape

KNEEL = stand(pelvis=(62.0, 62.5), lean=16.0, yaw=34.0, tilt=0.0, head="death", foot_n=(50.5, STAND_Y),
              pitch_n=62.0, kneel_n=True, foot_f=(69.0, STAND_Y), hand_n=(66.0, 61.0), hand_f=(70.0, 60.5),
              grip_n="relax", grip_f="relax", crouch=0.6, stiff={"cape0": 0.6, "cape1": 0.6})


DEATH_PONY = (-62.0, -40.0, -20.0, -8.0)


def death_frames() -> list[Pose]:
    """Stagger 2, knees buckle 2, kneel hold, topple forward 3, lie 2 (~1.4 s).
    The topple rotates the whole rig (the light stays put, so shading stays
    right) while the legs straighten out behind; the lying figure is prone,
    face down, the cape settling over its back."""
    # the stagger keeps the plain hanging drape (the hurt hold's forward-swinging cape is
    # the knock-back's, not the collapse's)
    st1 = replace(HURT_HOLD, head="hurt", lean=-8.0, hand_n=(66.0, 47.0), hand_f=(68.5, 46.0), far_arm_front=True,
                  vel=(0.0, 0.0), cape=HURT_HIT.cape, drape={}, stiff={})
    st2 = replace(st1, pelvis=(62.5, 54.0), lean=2.0, head="death", hand_n=(65.5, 50.0), hand_f=(68.0, 49.0))
    bk1 = lerp_pose(st2, KNEEL, 0.45)
    bk2 = lerp_pose(st2, KNEEL, 0.8)
    # prone target, authored upright and rotated 90 deg forward about the pelvis
    pc = (58.0, 70.0)
    prone = stand(pelvis=pc, lean=0.0, yaw=34.0, tilt=0.0, head="death", plant_n=False, plant_f=False,
                  foot_n=(57.0, pc[1] + 19.0), pitch_n=40.0, foot_f=(59.5, pc[1] + 18.0), pitch_f=50.0,
                  hand_n=(66.0, pc[1] - 23.0), elbow_n=-1.0, hand_f=(61.0, pc[1] + 4.0), grip_n="open",
                  grip_f="relax", rot=90.0, rot_c=pc, floor=True, cape=ClothArt(flare=0.0, face="out"),
                  stiff={"cape0": 0.4, "cape1": 0.4})
    knee_c = (KNEEL.pelvis[0] + 4.0, 72.0)
    f1 = replace(KNEEL, rot=24.0, rot_c=knee_c, cape=ClothArt(flare=0.06, face="out"))
    f2 = replace(lerp_pose(KNEEL, replace(prone, rot=0.0), 0.35), rot=56.0, rot_c=knee_c, head="death",
                 cape=ClothArt(flare=0.0, face="out"), kneel_n=False, plant_n=False, plant_f=False)
    f3 = replace(lerp_pose(KNEEL, replace(prone, rot=0.0), 0.8), rot=82.0, rot_c=pc, head="death",
                 cape=ClothArt(flare=0.0, face="out"), kneel_n=False, plant_n=False, plant_f=False)
    lie1 = prone
    lie2 = replace(prone, hand_n=(66.5, pc[1] - 23.5))
    # on the rotated (toppling / prone) drawings the ponytail's rest drape turns with the
    # rig; the hanging drape keeps it lying along the back instead of spiking upward
    lying = {"pony": DEATH_PONY}
    f1, f2, f3, lie1, lie2 = (replace(q, drape={**q.drape, **lying}) for q in (f1, f2, f3, lie1, lie2))
    return [st1, st2, bk1, bk2, KNEEL, f1, f2, f3, lie1, lie2]


# --- transitions (extras; integration wires them behind has_animation) -------
# the canopy folds down over the three landing drawings: f0 a third of the way (the cloth
# already dropping behind the shoulders, lining turning away), f1 two thirds, f2 almost on
# the idle drape, so the hand-off to idle is a settle, not a snap
LAND_SETTLE = (0.12, 0.52, 0.9)


def land_frames() -> list[Pose]:
    deep = stand(pelvis=(63.5, 55.0), lean=10.0, head="fwd", foot_n=(58.0, STAND_Y), foot_f=(69.5, STAND_Y),
                 hand_n=(62.5, 57.0), hand_f=(70.5, 56.0), vel=(0.0, 0.0), cape=ClothArt(flare=0.12, hem_in=0.06))
    # f0: the canopy is already collapsing behind the shoulders, its outer face turning back
    # toward the camera (the lining shows only where the cloth still turns over at the top)
    first = replace(deep, cape=ClothArt(flare=0.08, hem_in=0.08, face="out", turn=0.3))
    return [first, lerp_pose(deep, IDLE, 0.4), lerp_pose(deep, IDLE, 0.75)]


def run_start_frames() -> list[Pose]:
    lead = stand(pelvis=(64.0, 52.5), lean=12.0, yaw=28.0, head="fwd", foot_f=(70.5, STAND_Y), pitch_f=0.0,
                 foot_n=(57.5, STAND_Y), pitch_n=20.0, hand_n=(57.5, 51.5), hand_f=(70.0, 50.0),
                 grip_n="fist", grip_f="fist", vel=(0.6, 0.0))
    starts = [30.0, 33.0, 35.0]
    out = [lead]
    for w, t in zip((0.6, 0.82, 1.0), starts):
        out.append(lerp_pose(lead, run_pose(t, run_art), w))
    return out


def skid_frames() -> list[Pose]:
    """Brake from the run: lean back, plant the front heel, the cape swings
    forward past the body on its own momentum, then settle into idle."""
    plant = stand(collide=False, pelvis=(62.5, 53.5), lean=-8.0, yaw=30.0, head="fwd", foot_f=(73.5, STAND_Y),
                  pitch_f=-18.0,
                  foot_n=(57.0, STAND_Y), pitch_n=22.0, hand_n=(56.5, 50.0), hand_f=(71.5, 47.5), grip_f="open",
                  vel=(0.4, 0.0), cape=ClothArt(flare=0.14, wave=0.8, face="out", turn=0.25),
                  drape={"cape0": (20, 34, 48, 58, 66, 72, 76), "cape1": (30, 46, 60, 72, 80, 86, 90)},
                  stiff={"cape0": 1.4, "cape1": 1.4})
    mid = replace(plant, pelvis=(62.5, 53.0), lean=-10.0, pitch_f=-10.0, vel=(0.0, 0.0))
    s3 = replace(lerp_pose(mid, IDLE, 0.3), vel=(0.0, 0.0), drape={}, stiff={})
    return [plant, mid, s3, replace(lerp_pose(mid, IDLE, 0.55), drape={}, stiff={}),
            replace(lerp_pose(mid, IDLE, 0.8), drape={}, stiff={}), IDLE]


def apex_frames() -> list[Pose]:
    return [APEX, replace(APEX, vel=(0.0, 0.4)), lerp_pose(APEX, FALL, 0.4), lerp_pose(APEX, FALL, 0.75)]


def double_jump_frames() -> list[Pose]:
    """Drawn somersault, 6 x 3 ticks: a tight tuck (heels under the seat, knees to
    the chest, hands on the shins) spun 60 deg per drawing about the body centre;
    the cape's rest drape does not spin and it is almost free (stiffness 0.02), so
    it lags the spin as one swirl that flashes its lining."""
    # torso curled 46 deg over the knees; each ankle sits just ahead of and below its
    # hip so the IK folds the knee up to the chest (an ankle behind the hip lets it dangle)
    tuck = air(pelvis=(63.0, 52.0), lean=46.0, yaw=34.0, head="n", head_lean=1.6, foot_n=(64.0, 53.0),
               pitch_n=30.0, foot_f=(66.5, 55.5), pitch_f=36.0, hand_n=(69.0, 49.5), hand_f=(71.0, 50.5),
               grip_n="fist", grip_f="fist", rot_c=(64.0, 47.0), vel=(0.0, -290.0 / 60.0), drape_spin=False,
               stiff={"cape0": 0.02, "cape1": 0.02},
               cape=ClothArt(flare=0.3, hem_in=0.2, wave=1.2))
    return [replace(tuck, rot=float(a)) for a in (0, 60, 120, 180, 240, 300)]


def turn_frames() -> list[Pose]:
    """Frontal, then 3/4: the flip trail of the cape belongs on f0/f1; f2 already
    hangs in (about) the idle drape so the hand-off to idle does not snap."""
    front = stand(yaw=80.0, lean=1.0, foot_n=(60.0, STAND_Y), foot_f=(67.5, STAND_Y), hand_n=(58.5, 54.0),
                  hand_f=(69.5, 54.0))
    settle = replace(lerp_pose(front, IDLE, 0.85), stiff={"cape0": 2.0, "cape1": 2.4},
                     drape={"cape0": (-4, -5, -6, -7, -8, -8, -8), "cape1": (-12, -15, -18, -21, -23, -25, -26)})
    return [front, lerp_pose(front, IDLE, 0.5), settle]


def drape_pull(weights: tuple[float, ...], names: tuple[str, ...] = ("cape0", "cape1")
               ) -> Callable[[list[Pose], list[SimFrame]], list[SimFrame]]:
    """A follower override: frame i's named chains turned weights[i] of the way
    toward that frame's own designed rest drape (for an impulse too sudden for
    the soft cloth spring to reach in a 2-4 tick drawing, such as a hit)."""
    def post(poses: list[Pose], sims: list[SimFrame]) -> list[SimFrame]:
        out = []
        for i, (p, sf) in enumerate(zip(poses, sims)):
            w = weights[min(i, len(weights) - 1)]
            chains = dict(sf.chains)
            for name in names:
                c = sf.chains[name]
                rest = rest_shape(p.drape.get(name, CHAINS[name].rest), CHAINS[name].length) + c[0]
                if w > 0 and rest.shape == c.shape:
                    chains[name] = _blend_chain(c, rest, w)
            out.append(SimFrame(chains, sf.clock))
        return out
    return post


# ==========================================================================
# Animation table
# ==========================================================================
@dataclass
class Anim:
    name: str
    frames: Callable[[], list[Pose]]
    ticks: list[int]
    loop: bool
    entry: str | None = None          # animation whose end state feeds the followers
    entry_pose: Callable[[], Pose] | None = None
    mirror_entry: bool = False
    exit_to: tuple[str, int] | None = None   # (animation, frame) the game shows next: the
    #                                          followers of the last 2 frames ease into it
    exit_blend: tuple[float, ...] = (0.45, 0.85)
    # settle: per-frame weights; the follower chains named in SETTLE_CHAINS keep the first
    # frame's shapes (re-rooted on each frame's anchors) turned that far toward the exit
    # target's shapes, so a big drape change (the fall canopy dropping on landing) is spread
    # evenly over the animation instead of happening in one drawing
    settle: tuple[float, ...] = ()
    settle_from: int = 0              # frames before this one keep their simulated followers
    post: Callable[[list[Pose], list[SimFrame]], list[SimFrame]] | None = None   # designed follower override


SETTLE_CHAINS = ("cape0", "cape1", "capelet", "pony", "rib0", "rib1")


ANIMS: list[Anim] = [
    Anim("idle", idle_frames, [7] * 6, True, post=idle_pony),
    Anim("run", run_frames, RUN_TICKS, True),
    Anim("jump", lambda: [JUMP_LAUNCH, lerp_pose(JUMP_LAUNCH, JUMP_RISE, 0.5), JUMP_RISE,
                          replace(JUMP_RISE, vel=(0.0, -2.2), cape=replace(JUMP_RISE.cape, wave_phase=2.0)),
                          replace(JUMP_RISE, vel=(0.0, -1.4), cape=replace(JUMP_RISE.cape, wave_phase=4.0))],
         [3, 3, 4, 4, 6], False, entry="idle", entry_pose=lambda: IDLE),
    Anim("fall", fall_frames, [5, 5, 5, 5], True),
    Anim("crouch", crouch_frames, [1, 1, 2, 30], False, entry="idle"),
    Anim("attack", sword_frames, SWORD_TICKS, False, entry="idle", exit_to=("idle", 0)),
    Anim("attack_crouch", lambda: [crouched(p) for p in sword_frames()], SWORD_TICKS, False, entry="crouch",
         exit_to=("crouch", 3)),
    Anim("attack_air", lambda: [airborne(p, AIR_LIFT_SWORD[i]) for i, p in enumerate(sword_frames())], SWORD_TICKS,
         False, entry="fall", exit_to=("fall", 0)),
    Anim("attack_whip", whip_frames, WHIP_TICKS, False, entry="idle", exit_to=("idle", 0)),
    Anim("attack_whip_crouch", lambda: [crouched(p) for p in whip_frames()], WHIP_TICKS, False, entry="crouch",
         exit_to=("crouch", 3)),
    Anim("attack_whip_air", lambda: [airborne(p, AIR_LIFT_WHIP[i]) for i, p in enumerate(whip_frames())], WHIP_TICKS,
         False, entry="fall", exit_to=("fall", 0)),
    Anim("throw", throw_frames, THROW_TICKS, False, entry="idle", exit_to=("idle", 0)),
    # brake: from the second glide drawing on, the streaming cape swings home in even steps
    Anim("backdash", backdash_frames, [2, 4, 4, 4, 4], False, entry="idle", entry_pose=lambda: IDLE,
         exit_to=("idle", 0), settle=(0.18, 0.62, 0.95), settle_from=2),
    Anim("hurt", lambda: [HURT_HIT, HURT_RECOIL, HURT_HOLD], [2, 4, 8], False, entry="run",
         entry_pose=lambda: IDLE, exit_to=("idle", 0), exit_blend=(0.0, 0.8), post=drape_pull((0.35, 0.8, 0.0))),
    Anim("death", death_frames, [6, 6, 7, 7, 18, 5, 5, 6, 8, 16], False, entry="hurt"),
    # extras (integration wires these behind has_animation() guards)
    Anim("land", land_frames, [3, 4, 5], False, entry="fall", entry_pose=lambda: FALL, exit_to=("idle", 0),
         settle=LAND_SETTLE),
    Anim("run_start", run_start_frames, [3, 3, 3, 3], False, entry="idle"),
    Anim("skid", skid_frames, [4] * 6, False, entry="run", entry_pose=lambda: run_frames()[0],
         exit_to=("idle", 0)),
    Anim("apex", apex_frames, [4, 4, 4, 4], False, entry="jump", exit_to=("fall", 0), exit_blend=(0.34, 0.85)),
    Anim("double_jump", double_jump_frames, [3] * 6, False, entry="jump"),
    Anim("turn", turn_frames, [2, 2, 2], False, entry="idle", mirror_entry=True, exit_to=("idle", 0)),
]


@dataclass
class Rendered:
    anim: Anim
    poses: list[Pose]
    frames: list[Frame]
    sim_end: Sim
    sims: list[SimFrame] = field(default_factory=list)


def floor_clamp(fr: Frame) -> Frame:
    """Rotated grounded poses (the death topple) rest on the floor: move the
    finished frame so its lowest opaque row is exactly the sole row."""
    ys = np.nonzero(fr.rgba[..., 3] > 0)[0]
    dy = int(ys.max()) - HERO_FOOT_Y if len(ys) else 0
    if dy == 0:
        return fr
    return replace(fr, rgba=np.roll(fr.rgba, -dy, 0), mat=np.roll(fr.mat, -dy, 0), tone=np.roll(fr.tone, -dy, 0),
                   wmask=np.roll(fr.wmask, -dy, 0), hand=(fr.hand[0], fr.hand[1] - dy),
                   part=None if fr.part is None else np.roll(fr.part, -dy, 0))


def _blend_chain(c: np.ndarray, s: np.ndarray, w: float) -> np.ndarray:
    """Chain `c` turned `w` of the way toward the shape of `s`, segment by
    segment in angle (the shorter way round) with lengths kept, rebuilt from
    c's own root, so a cloth edge swings toward the target shape instead of
    crumpling (a positional lerp between opposite drapes collapses it)."""
    dc, ds = np.diff(c, axis=0), np.diff(s, axis=0)
    ac, as_ = np.arctan2(dc[:, 1], dc[:, 0]), np.arctan2(ds[:, 1], ds[:, 0])
    da = (as_ - ac + np.pi) % (2 * np.pi) - np.pi
    a = ac + w * da
    ln = np.hypot(dc[:, 0], dc[:, 1]) * (1.0 - w) + np.hypot(ds[:, 0], ds[:, 1]) * w
    seg = np.stack([np.cos(a) * ln, np.sin(a) * ln], 1)
    return np.concatenate([c[:1], c[:1] + np.cumsum(seg, axis=0)], 0)


def ease_exit(sims: list[SimFrame], succ: SimFrame, weights: tuple[float, ...]) -> list[SimFrame]:
    """Ease the follower chains of the last two frames toward the shapes the
    successor animation starts with (each chain stays on its own anchor), so
    the cape and hair do not pop at the hand-off."""
    out = list(sims)
    n = len(out)
    for k, w in enumerate(weights):
        i = n - len(weights) + k
        if i < 0:
            continue
        cur = out[i]
        chains = {}
        for name, c in cur.chains.items():
            s = succ.chains.get(name)
            chains[name] = c if (s is None or s.shape != c.shape) else _blend_chain(c, s, w)
        out[i] = SimFrame(chains, cur.clock)
    return out


def settle_chains(sims: list[SimFrame], succ: SimFrame, weights: tuple[float, ...], first: int = 0
                  ) -> list[SimFrame]:
    """From frame `first` on, frame i's SETTLE_CHAINS = frame `first`'s shapes,
    re-rooted on frame i's own anchors, turned weights[i - first] of the way
    (segment angles, lengths kept) toward the successor's shapes."""
    out = list(sims)
    src = sims[first]
    for i in range(first, len(sims)):
        cur = sims[i]
        w = weights[min(i - first, len(weights) - 1)]
        chains = dict(cur.chains)
        for name in SETTLE_CHAINS:
            c0, s = src.chains.get(name), succ.chains.get(name)
            if c0 is None or s is None or s.shape != c0.shape:
                continue
            chains[name] = _blend_chain(c0 - c0[0] + cur.chains[name][0], s, w)
        out[i] = SimFrame(chains, cur.clock)
    return out


def render_anim(a: Anim, entry_sims: dict[str, Sim], succ: SimFrame | None = None) -> Rendered:
    poses = a.frames()
    if len(poses) != len(a.ticks):
        raise ValueError(f"{a.name}: {len(poses)} poses but {len(a.ticks)} ticks")
    entry = entry_sims.get(a.entry) if a.entry else None
    if entry is not None and a.mirror_entry:
        entry = mirror_sim(entry)
    sims, end = simulate(poses, a.ticks, a.loop, sim=entry,
                         entry=a.entry_pose() if a.entry_pose is not None else None)
    if a.post is not None:
        sims = a.post(poses, sims)
    if succ is not None and a.settle:
        sims = settle_chains(sims, succ, a.settle, a.settle_from)
    elif succ is not None:
        sims = ease_exit(sims, succ, a.exit_blend)
    mem = ToneMemory()
    passes = 2 if a.loop else 1
    frames: list[Frame] = []
    for _ in range(passes):
        frames = []
        tip: Pt | None = None
        for p, s in zip(poses, sims):
            fr = render_frame(p, s, mem, tip)
            if p.rot and not p.airborne:
                fr = floor_clamp(fr)
            frames.append(fr)
            tip = fr.tip if fr.tip is not None else tip
    return Rendered(a, poses, frames, end, sims)


def _closure(names: list[str]) -> set[str]:
    """`names` plus every animation they depend on (entry states, exit targets)."""
    by = {a.name: a for a in ANIMS}
    need: set[str] = set()
    todo = list(names)
    while todo:
        n = todo.pop()
        if n in need:
            continue
        need.add(n)
        a = by[n]
        if a.entry:
            todo.append(a.entry)
        if a.exit_to:
            todo.append(a.exit_to[0])
    return need


def render_all(names: list[str] | None = None) -> dict[str, Rendered]:
    """Render in table order (every entry / exit dependency precedes its user);
    with `names`, only those and what they depend on (same pixels as a full run)."""
    out: dict[str, Rendered] = {}
    sims: dict[str, Sim] = {}
    need = _closure(names) if names is not None else None
    for a in ANIMS:
        if need is not None and a.name not in need:
            continue
        succ = None
        if a.exit_to is not None:
            nxt, fi = a.exit_to
            if nxt not in out:
                raise ValueError(f"{a.name}: exit target {nxt} must precede it in ANIMS")
            succ = out[nxt].sims[fi]
        r = render_anim(a, sims, succ)
        out[a.name] = r
        sims[a.name] = r.sim_end
    return out


# ==========================================================================
# Export
# ==========================================================================
def _weapon_entry(fr: Frame) -> dict[str, object]:
    wd = fr.weapon
    e: dict[str, object] = {"hand": [round(fr.hand[0], 1), round(fr.hand[1], 1)], "weapon": wd.kind}
    if wd.kind == "sabre":
        e["angle"] = round(wd.angle, 1)
        e["length"] = round(wd.length, 1)
        e["behind"] = wd.behind
    if fr.tip is not None:
        e["tip"] = [round(fr.tip[0], 1), round(fr.tip[1], 1)]
    return e


def build() -> None:
    rendered = render_all()
    sheet = SheetBuilder("vesper", FW, FH, origin=ORIGIN)
    for a in ANIMS:
        r = rendered[a.name]
        sheet.add(a.name, [Image.fromarray(f.rgba, "RGBA") for f in r.frames], 60.0, a.loop, ticks=a.ticks)
    sheet.save()
    # manifest extras (no runtime consumer): per-frame hand anchor / weapon state,
    # hitbox windows and the throw spawn frame, so scene work never guesses them
    path = os.path.join(SPRITES, "vesper.json")
    with open(path) as fh:
        data = json.load(fh)
    for a in ANIMS:
        entry = data["animations"][a.name]
        entry["weapon"] = [_weapon_entry(f) for f in rendered[a.name].frames]
    data["attack_windows"] = {
        "attack": {"active_frames": list(SWORD_ACTIVE), "ticks": _window(SWORD_TICKS, SWORD_ACTIVE)},
        "attack_whip": {"active_frames": list(WHIP_ACTIVE), "ticks": _window(WHIP_TICKS, WHIP_ACTIVE)},
        "throw": {"spawn_frame": THROW_SPAWN_FRAME, "ticks_before_spawn": THROW_TICKS[0]},
    }
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)


if __name__ == "__main__":
    build()
