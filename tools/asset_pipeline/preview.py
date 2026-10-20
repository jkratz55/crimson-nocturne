"""
Dev-only previews for the asset pipeline. Never called by a build.

    python3 tools/asset_pipeline/preview.py zoom SRC DST SCALE [x y w h]
    python3 tools/asset_pipeline/preview.py sheet NAME_OR_JSON DST [SCALE]
    python3 tools/asset_pipeline/preview.py silhouette SRC DST [SCALE]

`sheet` takes a SheetBuilder name ("vesper"), or the path of a sheet's
.json manifest (the .png must sit next to it). Every function writes only
to the path it is given and refuses paths inside the repository, so a
preview can never land in assets/ or get imported by Godot.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

from common import ROOT, SPRITES

BG = (96, 96, 104, 255)          # neutral mid grey, like docs/art_style.md's checks
GRID = (70, 70, 78, 255)
LABEL = (236, 236, 244, 255)
MARK = (255, 64, 200, 255)       # origin marker: a colour no ramp uses


def _guard(dst: str) -> str:
    path = os.path.realpath(dst)
    root = os.path.realpath(ROOT)
    if path == root or path.startswith(root + os.sep):
        raise ValueError(f"preview output must live outside the repository: {dst}")
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path


def _load(src: str | Image.Image) -> Image.Image:
    return (src if isinstance(src, Image.Image) else Image.open(src)).convert("RGBA")


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.load_default(size=size)
    except (TypeError, OSError):
        return ImageFont.load_default()


def zoom(src: str | Image.Image, dst: str | None, scale: int,
         crop: tuple[int, int, int, int] | None = None,
         bg: tuple[int, int, int, int] = BG) -> Image.Image:
    """Nearest-neighbour upscale over a flat grey backdrop. `crop` is
    (x, y, w, h) in source pixels. Saves to `dst` when given."""
    img = _load(src)
    if crop is not None:
        x, y, w, h = crop
        img = img.crop((x, y, x + w, y + h))
    base = Image.new("RGBA", img.size, bg)
    base.alpha_composite(img)
    out = base.resize((img.width * scale, img.height * scale), Image.NEAREST)
    if dst:
        out.save(_guard(dst))
    return out


def silhouette(img: str | Image.Image, bg: tuple[int, int, int, int] = (128, 128, 128, 255),
               fg: tuple[int, int, int, int] = (0, 0, 0, 255)) -> Image.Image:
    """The silhouette test in docs/art_style.md: every opaque pixel 100 % black on
    mid grey, at 1x (zoom it afterwards)."""
    src = _load(img)
    out = Image.new("RGBA", src.size, bg)
    mask = src.getchannel("A").point(lambda a: 255 if a > 0 else 0)
    out.paste(Image.new("RGBA", src.size, fg), (0, 0), mask)
    return out


def strip(images: Sequence[Image.Image], dst: str | None, scale: int = 1, pad: int = 4,
          labels: Sequence[str] | None = None, bg: tuple[int, int, int, int] = BG) -> Image.Image:
    """Lay 1x images side by side on grey, upscale, optionally label each."""
    ims = [_load(i) for i in images]
    w = sum(i.width for i in ims) + pad * (len(ims) + 1)
    h = max((i.height for i in ims), default=0) + pad * 2
    board = Image.new("RGBA", (w, h), bg)
    x = pad
    xs: list[int] = []
    for im in ims:
        board.alpha_composite(im, (x, pad))
        xs.append(x)
        x += im.width + pad
    out = board.resize((w * scale, h * scale), Image.NEAREST)
    if labels:
        font = _font(10)
        lh = 14
        framed = Image.new("RGBA", (out.width, out.height + lh), bg)
        framed.alpha_composite(out, (0, lh))
        d = ImageDraw.Draw(framed)
        for x0, text in zip(xs, labels):
            d.text((x0 * scale, 1), text, fill=LABEL, font=font)
        out = framed
    if dst:
        out.save(_guard(dst))
    return out


def _manifest(sheet: str) -> tuple[dict[str, object], str]:
    if sheet.endswith(".json"):
        path = sheet
    elif sheet.endswith(".png"):
        path = sheet[:-4] + ".json"
    else:
        path = os.path.join(SPRITES, f"{sheet}.json")
    with open(path) as fh:
        return json.load(fh), path[:-5] + ".png"


def contact_sheet(sheet: str, out_png: str, scale: int = 3, *, silhouettes: bool = False,
                  bg: tuple[int, int, int, int] = BG) -> Image.Image:
    """Every animation row of a SheetBuilder sheet, zoomed, labelled with
    name, frame count, loop flag and timing (ticks per frame and total, or
    fps), with each frame's tick count under it and the manifest origin
    (feet point) marked. `silhouettes=True` adds a black-fill row per
    animation for the silhouette test."""
    data, png = _manifest(sheet)
    src = Image.open(png).convert("RGBA")
    fw, fh = data["frame_size"]  # type: ignore[misc]
    origin = data.get("origin")
    anims = sorted(data["animations"].items(), key=lambda kv: kv[1]["row"])  # type: ignore[union-attr]
    font = _font(12)
    small = _font(10)
    gap, head, foot = 2 * scale, 18, 14
    cols = max(int(a["frames"]) for _, a in anims)
    cell_w, cell_h = fw * scale, fh * scale
    row_h = head + cell_h + foot + (cell_h + gap if silhouettes else 0)
    width = 8 + cols * (cell_w + gap)
    height = 8 + len(anims) * (row_h + gap)
    out = Image.new("RGBA", (max(width, 320), height), (52, 52, 60, 255))
    d = ImageDraw.Draw(out)
    y = 4
    for name, a in anims:
        n, row = int(a["frames"]), int(a["row"])
        ticks = a.get("ticks")
        loop = "loop" if a["loop"] else "once"
        if ticks:
            total = int(a.get("total_ticks", sum(ticks)))
            timing = f"ticks {list(ticks)} = {total}t ({total / 60:.2f}s)"
        else:
            fps = float(a["fps"])
            timing = f"{fps:g} fps ({n / fps:.2f}s)" if fps else "0 fps"
        d.text((6, y + 2), f"{name}  {n}f  {loop}  {timing}", fill=LABEL, font=font)
        for c in range(n):
            fr = src.crop((c * fw, row * fh, c * fw + fw, row * fh + fh))
            x = 4 + c * (cell_w + gap)
            tile = Image.new("RGBA", (fw, fh), bg)
            tile.alpha_composite(fr)
            big = tile.resize((cell_w, cell_h), Image.NEAREST)
            out.alpha_composite(big, (x, y + head))
            if origin:
                half = scale // 2   # centre of the origin pixel
                ox = int(origin[0]) * scale + x + half  # type: ignore[index]
                oy = int(origin[1]) * scale + y + head + half  # type: ignore[index]
                d.line([(ox - 3 * scale, oy), (ox + 3 * scale, oy)], fill=MARK)
                d.line([(ox, oy - 3 * scale), (ox, oy + 3 * scale)], fill=MARK)
            d.rectangle([x - 1, y + head - 1, x + cell_w, y + head + cell_h], outline=GRID)
            tag = f"{c}" + (f": {ticks[c]}t" if ticks else "")
            d.text((x + 2, y + head + cell_h + 1), tag, fill=LABEL, font=small)
            if silhouettes:
                sil = silhouette(fr).resize((cell_w, cell_h), Image.NEAREST)
                out.alpha_composite(sil, (x, y + head + cell_h + foot))
        y += row_h + gap
    out.save(_guard(out_png))
    return out


def main(argv: Sequence[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "zoom":
        crop = tuple(int(v) for v in argv[4:8]) if len(argv) >= 8 else None
        zoom(argv[1], argv[2], int(argv[3]) if len(argv) > 3 else 4, crop)  # type: ignore[arg-type]
    elif cmd == "sheet":
        contact_sheet(argv[1], argv[2], int(argv[3]) if len(argv) > 3 else 3)
    elif cmd == "silhouette":
        zoom(silhouette(argv[1]), argv[2], int(argv[3]) if len(argv) > 3 else 4)
    else:
        print(__doc__)
        return 2
    print(f"wrote {argv[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
