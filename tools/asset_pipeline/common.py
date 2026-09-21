"""
Shared helpers for the Crimson Nocturne procedural asset pipeline.

All art is generated at native 1x pixel resolution with a restricted,
gothic palette inspired by 32-bit era 2D action games (deep blues and
violets for the castle, crimson accents, bone whites, candle golds).

Every sprite gets a 1px dark "sel-out" style outline via `outline()`,
which is what makes procedurally drawn shapes read as hand-pixelled art.
"""
from __future__ import annotations

import json
import math
import os
from typing import Iterable, Sequence

from PIL import Image, ImageDraw

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SPRITES = os.path.join(ROOT, "assets", "sprites")
TILES = os.path.join(ROOT, "assets", "tiles")
BACKGROUNDS = os.path.join(ROOT, "assets", "backgrounds")
UI = os.path.join(ROOT, "assets", "ui")
FONTS = os.path.join(ROOT, "assets", "fonts")
MUSIC = os.path.join(ROOT, "assets", "audio", "music")
SFX = os.path.join(ROOT, "assets", "audio", "sfx")
FRAMES_RES = os.path.join(ROOT, "resources", "sprite_frames")

for _p in (SPRITES, TILES, BACKGROUNDS, UI, FONTS, MUSIC, SFX, FRAMES_RES):
    os.makedirs(_p, exist_ok=True)

Color = tuple[int, int, int] | tuple[int, int, int, int]
Point = tuple[float, float]

# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------
OUTLINE = (18, 10, 26, 255)

# Hero (the dhampir "Vesper")
SKIN = (238, 218, 206)
SKIN_SH = (178, 142, 150)
HAIR = (44, 34, 66)
HAIR_HI = (92, 76, 132)
COAT = (40, 44, 96)
COAT_SH = (24, 26, 60)
COAT_HI = (76, 84, 150)
TRIM = (220, 178, 76)
TRIM_SH = (150, 104, 40)
CAPE_OUT = (26, 16, 34)
CAPE_IN = (156, 24, 44)
CAPE_IN_HI = (208, 52, 64)
PANTS = (62, 52, 78)
PANTS_SH = (40, 32, 52)
BOOT = (34, 26, 38)
BOOT_HI = (70, 58, 76)
EYE = (230, 40, 48)
BLADE = (226, 234, 246)
BLADE_SH = (132, 144, 178)

# Bone / undead
BONE = (232, 224, 200)
BONE_SH = (160, 150, 128)
BONE_DK = (104, 92, 80)

# Bat
BAT = (70, 36, 84)
BAT_SH = (44, 22, 56)
BAT_WING = (96, 50, 110)

# Castle stone
STONE = (72, 78, 116)
STONE_HI = (108, 116, 160)
STONE_SH = (48, 50, 84)
MORTAR = (30, 30, 52)
STONE_BG = (40, 42, 70)
STONE_BG_HI = (56, 60, 94)
STONE_BG_SH = (28, 28, 50)
CARPET = (128, 20, 40)
CARPET_HI = (176, 40, 56)
MOSS = (58, 92, 76)

# Light / fire
FIRE_1 = (255, 244, 196)
FIRE_2 = (255, 196, 72)
FIRE_3 = (236, 104, 36)
FIRE_4 = (160, 36, 32)
HEART = (224, 32, 56)
HEART_HI = (255, 140, 150)
HEART_SH = (130, 10, 40)


def rgba(c: Color, a: int = 255) -> tuple[int, int, int, int]:
    """Normalise an RGB/RGBA tuple to RGBA."""
    return (c[0], c[1], c[2], c[3] if len(c) == 4 else a)


def new_canvas(w: int, h: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def outline(img: Image.Image, color: Color = OUTLINE) -> Image.Image:
    """Add a 1px 4-connected outline around every opaque region."""
    w, h = img.size
    src = img.load()
    out = img.copy()
    dst = out.load()
    for y in range(h):
        for x in range(w):
            if src[x, y][3] != 0:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and src[nx, ny][3] != 0:
                    dst[x, y] = rgba(color)
                    break
    return out


def line(d: ImageDraw.ImageDraw, pts: Sequence[Point], color: Color, width: int = 1) -> None:
    d.line([(round(x), round(y)) for x, y in pts], fill=rgba(color), width=width, joint="curve")


def poly(d: ImageDraw.ImageDraw, pts: Sequence[Point], color: Color) -> None:
    d.polygon([(round(x), round(y)) for x, y in pts], fill=rgba(color))


def rect(d: ImageDraw.ImageDraw, x0: float, y0: float, x1: float, y1: float, color: Color) -> None:
    d.rectangle([round(x0), round(y0), round(x1), round(y1)], fill=rgba(color))


def px(img: Image.Image, x: float, y: float, color: Color) -> None:
    xi, yi = round(x), round(y)
    if 0 <= xi < img.width and 0 <= yi < img.height:
        img.putpixel((xi, yi), rgba(color))


def lerp(a: Point, b: Point, t: float) -> Point:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def polar(origin: Point, angle_deg: float, length: float) -> Point:
    a = math.radians(angle_deg)
    return (origin[0] + math.cos(a) * length, origin[1] + math.sin(a) * length)


# --------------------------------------------------------------------------
# Sprite sheets + Godot SpriteFrames export
# --------------------------------------------------------------------------
class SheetBuilder:
    """Packs animation frames into a grid (one row per animation) and
    writes a matching Godot 4 `SpriteFrames` resource (.tres)."""

    def __init__(self, name: str, frame_w: int, frame_h: int) -> None:
        self.name = name
        self.fw = frame_w
        self.fh = frame_h
        # list of (anim_name, frames, fps, loop)
        self.anims: list[tuple[str, list[Image.Image], float, bool]] = []

    def add(self, anim: str, frames: Iterable[Image.Image], fps: float, loop: bool) -> None:
        self.anims.append((anim, list(frames), fps, loop))

    def save(self) -> None:
        cols = max(len(f) for _, f, _, _ in self.anims)
        rows = len(self.anims)
        sheet = Image.new("RGBA", (cols * self.fw, rows * self.fh), (0, 0, 0, 0))
        for r, (_, frames, _, _) in enumerate(self.anims):
            for c, fr in enumerate(frames):
                sheet.paste(fr, (c * self.fw, r * self.fh))
        png_path = os.path.join(SPRITES, f"{self.name}.png")
        sheet.save(png_path)
        self._write_sprite_frames()
        manifest = {a: {"frames": len(f), "fps": fps, "loop": loop, "row": i}
                    for i, (a, f, fps, loop) in enumerate(self.anims)}
        with open(os.path.join(SPRITES, f"{self.name}.json"), "w") as fh:
            json.dump({"frame_size": [self.fw, self.fh], "animations": manifest}, fh, indent=2)

    def _write_sprite_frames(self) -> None:
        lines: list[str] = ['[gd_resource type="SpriteFrames" format=3]', ""]
        lines.append(f'[ext_resource type="Texture2D" path="res://assets/sprites/{self.name}.png" id="1_sheet"]')
        lines.append("")
        sub_ids: dict[tuple[int, int], str] = {}
        for r, (_, frames, _, _) in enumerate(self.anims):
            for c in range(len(frames)):
                sid = f"AtlasTexture_r{r}c{c}"
                sub_ids[(r, c)] = sid
                lines.append(f'[sub_resource type="AtlasTexture" id="{sid}"]')
                lines.append('atlas = ExtResource("1_sheet")')
                lines.append(f"region = Rect2({c * self.fw}, {r * self.fh}, {self.fw}, {self.fh})")
                lines.append("")
        lines.append("[resource]")
        anim_strs: list[str] = []
        for r, (anim, frames, fps, loop) in enumerate(self.anims):
            fr = ", ".join(
                '{\n"duration": 1.0,\n"texture": SubResource("%s")\n}' % sub_ids[(r, c)]
                for c in range(len(frames))
            )
            anim_strs.append(
                '{\n"frames": [%s],\n"loop": %s,\n"name": &"%s",\n"speed": %s\n}'
                % (fr, "true" if loop else "false", anim, float(fps))
            )
        lines.append("animations = [" + ", ".join(anim_strs) + "]")
        with open(os.path.join(FRAMES_RES, f"{self.name}_frames.tres"), "w") as fh:
            fh.write("\n".join(lines) + "\n")
