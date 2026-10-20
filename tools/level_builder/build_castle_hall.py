#!/usr/bin/env python3
"""Generator for ``scenes/rooms/castle_hall.tscn``.

Why a generator?
----------------
Hand-authoring TileMapLayer data in a text scene is impractical (it is a
binary PackedByteArray), and we want the starter room to be reproducible
from a readable, diff-friendly ASCII layout.

    python3 tools/level_builder/build_castle_hall.py [--layers PATH] [--out PATH]

WARNING: re-running overwrites any manual edits made to the scene in the
editor. Treat it as a bootstrap, not a round-trip format.

Inputs
------
- ``COLLISION_LAYOUT`` below: the gameplay map. It is locked: cell for cell
  it is what the tests and the save data were built against.
- ``assets/tiles/castle_tiles.json``, written by
  ``tools/asset_pipeline/tiles.py``: names -> atlas coordinates for single
  tiles, the world-periodic wall field, exposure-edge overlays and
  multi-cell pieces. Nothing here hard-codes an atlas coordinate.
- ``assets/backgrounds/layers.json`` (optional, written by
  ``tools/asset_pipeline/backgrounds.py``): one Parallax2D per entry, far ->
  near. Without it the room falls back to a plain Sky / Hall pair.

Layers emitted (all world space, z as before for actors):
    <background Parallax2D nodes>   z from layers.json (fallback -30 / -10)
    Decor        TileMapLayer z -5  architecture: frieze, piers, arches, niche
    DecorFront   TileMapLayer z -4  fixtures: banners, drapes, lamps, webs
    Tiles        TileMapLayer z 0   collision (the only layer with physics)
    TileEdges    TileMapLayer z 0   lips / arrises over exposed wall faces
then props, actors and spawners exactly as before, then (when
castle_tiles.json describes one) the ``Foreground`` Parallax2D occluder
plane (visual only, scroll 1.3, over the actors), then the camera.

TileMapLayer data format (Godot 4.3+, "format 0")
-------------------------------------------------
    u16 format_version (= 0)
    then per cell, 12 bytes little-endian:
    i16 x, i16 y, u16 source_id, u16 atlas_x, u16 atlas_y, u16 alternative
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from typing import Any

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "scenes", "rooms", "castle_hall.tscn")
TILES_JSON = os.path.join(ROOT, "assets", "tiles", "castle_tiles.json")
LAYERS_JSON = os.path.join(ROOT, "assets", "backgrounds", "layers.json")

TILE = 16
PLAYER_START = (168, 256)

Cell = tuple[int, int]

# ---------------------------------------------------------------------------
# Layout (48 x 18 tiles = 768 x 288 px, i.e. two screens wide)
#
#   #  solid wall / ceiling / foundation   =  solid floor top
#   -  one-way ledge                       ^  solid ceiling trim (cornice)
#   _  solid carpeted dais top             .  empty
#
# GAMEPLAY LOCK: do not change a single cell (tests, saves, spawn points).
# ---------------------------------------------------------------------------
COLLISION_LAYOUT = [
    "################################################",  # 0
    "##^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^##",  # 1
    "##............................................##",  # 2
    "##............................................##",  # 3
    "##............................................##",  # 4
    "##............................................##",  # 5
    "##=====.......................................##",  # 6
    "######........................................##",  # 7
    "##...........-----............-----...........##",  # 8
    "##............................................##",  # 9
    "##............................................##",  # 10
    "##............................................##",  # 11
    "##....-----.........--------.........-----....##",  # 12
    "##............................................##",  # 13
    "##............................................##",  # 14
    "##............................................##",  # 15
    "##============================================##",  # 16
    "################################################",  # 17
]
SOLID = "#=^_"
FLOOR_ROW = 16
# The crimson runner covers the gallery floor between these columns.
CARPET_COLS = (9, 39)

# ---------------------------------------------------------------------------
# Decor (non-collision) composition, in cells. The arcade: piers two cells
# wide, pointed / round arches between them springing at y=112 (the top of
# row 7), a frieze under the cornice, and a niche wall over the balcony.
# Every ledge end that meets a pier hangs from a gilt ring on its shaft.
# ---------------------------------------------------------------------------
FRIEZE_ROW = 2
ARCH_ROW = 3                 # arch pieces span rows 3..7 (row 7 = imposts)
CAP_ROW = 7                  # pier capital row; shafts run below it
BASE_ROWS = (14, 15)         # pier base (stands on the floor line, y=256)
# (left column, pilaster variant, front-layer fixture over the pilaster)
PIERS: list[tuple[int, str, str | None]] = [
    (11, "pier_top_mask", None),
    (19, "pier_top", "banner"),
    (29, "pier_top", "banner"),
    (36, "pier_top_mask", None),
]
NICHE = ("niche_statue", 2, 3)          # piece, x, y: over the balcony
NICHE_RIGHT = 7                         # first column right of the niche wall
RIGHT_WALL = 46                         # first solid column of the right wall
# Extra architecture: (piece or tile name, x, y)
DECOR_EXTRA: list[tuple[str, int, int]] = [
    ("balcony_corbel", 6, 7),           # under the balcony's overhanging end
    ("modillion", 3, 8),
    ("modillion", 5, 8),
    ("urn_pedestal", 43, 13),
]
# Fixtures on the front decor layer: (piece, x, y)
FRONT_EXTRA: list[tuple[str, int, int]] = [
    ("drape_l", 21, 7),
    ("drape_r", 27, 7),
    ("hook_chain", 33, 3),
    ("cobweb_tl", 2, 2),
    ("cobweb_tr", 44, 2),
    ("cobweb_tl", 2, 8),
]

# Actor / prop placement in pixels (feet or base position).
CANDLES = [
    # Reward for reaching the balcony. It stands at the balcony's wall end,
    # 48 px from the Heart Max Up, so the heart never sits in its goblet.
    ((40, 96), "big"),
    ((248, 224), "small"),
    ((408, 112), "small"),
    ((520, 224), "small"),
    ((664, 168), "small"),
]
SKELETON_SPAWNS = [(48, 256), (620, 256), (728, 256), (360, 192)]
BAT_SPAWNS = [(216, 42), (400, 42), (552, 42), (696, 42)]

# The save shrine. It sits on the ground floor near the player's start so a
# fresh run reaches it in a few seconds.
SAVE_POINT = (104, 256)

# Unique, once-only world items (SPEC 4.7). Each needs a world_item_id that
# is never reused: it is what the save file remembers, and two items sharing
# one would make taking either delete both.
#   (id, x, y, grant, extra props)
WORLD_ITEMS = [
    # The traversal relic. It is on the ground floor for now, so the ability
    # gate is real but nothing in this one room is locked behind it; the
    # properly gated area arrives with the first wing.
    ("hall_leap_stone", 296, 256, "ITEM", {"item": "leap_stone"}),
    # A heart-capacity upgrade on the balcony, which needs the double jump.
    # It floats in front of the niche statue, clear of the big candle.
    ("hall_heart_max", 88, 88, "HEART_MAX_UP", {"amount": "5", "icon": "heart_max_up"}),
    # A ring tucked on the right-hand ledge.
    ("hall_ruby_ring", 640, 184, "ITEM", {"item": "ruby_ring", "auto_equip": "true"}),
]

# Grant enum values, mirroring WorldItem.Grant.
GRANT = {"ITEM": "0", "HEART_MAX_UP": "1", "GOLD": "2"}

# A two-plane background (the sky and the 512-wide back wall, with the same
# numbers backgrounds.py writes for them), used when layers.json is absent or
# invalid. The hall is value-graded in its own pixels, so it needs no modulate.
FALLBACK_BACKGROUNDS: list[dict[str, Any]] = [
    {"name": "Sky", "texture": "res://assets/backgrounds/sky.png", "scroll_scale": [0.03, 0.05],
     "repeat_size": [480, 0], "repeat_times": 2, "z_index": -30, "offset": [0, 0],
     "modulate": [1, 1, 1, 1]},
    {"name": "Hall", "texture": "res://assets/backgrounds/hall.png", "scroll_scale": [0.7, 1],
     "repeat_size": [512, 0], "repeat_times": 3, "z_index": -10, "offset": [0, 0],
     "modulate": [1, 1, 1, 1]},
]
BLEND_MODES = {"mix": 0, "add": 1, "sub": 2, "mul": 3, "premult_alpha": 4}


# ===========================================================================
# Atlas table
# ===========================================================================
class Atlas:
    """Read-only view of assets/tiles/castle_tiles.json."""

    def __init__(self, path: str = TILES_JSON) -> None:
        if not os.path.exists(path):
            sys.exit(f"error: {os.path.relpath(path, ROOT)} is missing; run "
                     "tools/asset_pipeline/tiles.py first")
        with open(path, encoding="utf-8") as fh:
            self.data: dict[str, Any] = json.load(fh)
        self.solid = {tuple(c) for c in self.data["collision"]["solid"]}
        self.one_way = {tuple(c) for c in self.data["collision"]["one_way"]}

    def tile(self, name: str) -> Cell:
        c = self.data["tiles"].get(name)
        if c is None:
            raise KeyError(f"tile {name!r} not in castle_tiles.json")
        return (int(c[0]), int(c[1]))

    def has_tile(self, name: str) -> bool:
        return name in self.data["tiles"]

    def field(self, name: str, x: int, y: int) -> Cell:
        f = self.data["fields"][name]
        fw, fh = f["size"]
        c = f["cells"][y % fh][x % fw]
        return (int(c[0]), int(c[1]))

    def edge(self, mask: int) -> Cell:
        c = self.data["edges"][str(mask)]
        return (int(c[0]), int(c[1]))

    def piece(self, name: str) -> tuple[int, int, list[list[Cell | None]]]:
        p = self.data["pieces"].get(name)
        if p is None:
            raise KeyError(f"piece {name!r} not in castle_tiles.json")
        cells = [[None if c is None else (int(c[0]), int(c[1])) for c in row] for row in p["cells"]]
        return int(p["size"][0]), int(p["size"][1]), cells


# ===========================================================================
# Layer composition
# ===========================================================================
def _at(x: int, y: int) -> str:
    if 0 <= y < len(COLLISION_LAYOUT) and 0 <= x < len(COLLISION_LAYOUT[0]):
        return COLLISION_LAYOUT[y][x]
    return "#"      # outside the room counts as solid rock (no edge drawn)


def _hash(x: int, y: int) -> int:
    """Deterministic cell hash. The coordinates are mixed (murmur-style
    finaliser) before anyone takes `% n`: the bare xor of two products kept
    only (x mod 4) ^ (3y mod 4) in its low bits, so floor variants used to
    repeat every 64 px."""
    h = ((x * 73856093) ^ (y * 19349663)) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 0x5BD1E995) & 0xFFFFFFFF
    return h ^ (h >> 15)


class _Variants:
    """Hash-picked art variants along a row that never put the same
    variant on three neighbouring cells of one family."""

    def __init__(self) -> None:
        self._last: dict[tuple[str, int], tuple[int, int, int]] = {}   # (family, y) -> (x, v, run)

    def pick(self, family: str, n: int, x: int, y: int) -> int:
        v = _hash(x, y) % n
        prev = self._last.get((family, y))
        run = 1
        if prev is not None and prev[0] == x - 1:
            if prev[1] == v:
                run = prev[2] + 1
                if run >= 3:
                    v = (v + 1 + _hash(y, x) % (n - 1)) % n if n > 1 else v
                    run = 1
        self._last[(family, y)] = (x, v, run)
        return v


def _pier_cols() -> set[int]:
    return {c for x, _, _ in PIERS for c in (x, x + 1)}


def _plinth_plan(atlas: Atlas) -> dict[Cell, Cell]:
    """The foundation course under the walkable floor (row FLOOR_ROW + 1):
    wine-marble slabs 1-3 cells wide laid left to right, their widths and
    variants picked by `_hash`, so the joints fall every 32 or 48 px on no
    regular grid. Returns cell -> atlas tile; every tile is solid."""
    y = FLOOR_ROW + 1
    widths = sorted({int(n.split("_")[1]) for n in atlas.data["pieces"] if n.startswith("plinth_")})
    n_var = len({n.split("_")[2] for n in atlas.data["pieces"] if n.startswith("plinth_")})
    cols = [x for x in range(len(COLLISION_LAYOUT[0]))
            if _at(x, y) == "#" and _at(x, FLOOR_ROW) == "="]
    plan: dict[Cell, Cell] = {}
    laid: list[tuple[int, int]] = []
    i = 0
    while i < len(cols):
        run = 1
        while i + run < len(cols) and cols[i + run] == cols[i] + run:
            run += 1
        x = cols[i]
        end = x + run
        while x < end:
            left = end - x
            h = _hash(x, y + 101)
            fits = [c for c in widths if 2 <= c <= left]
            if not fits:
                w = left                            # a lone cell against a wall
            else:
                w = fits[h % len(fits)]
                keep = [c for c in fits if left - c != 1]   # never strand a single cell
                if left - w == 1 and keep:
                    w = keep[h % len(keep)]
            if w not in widths:
                raise ValueError(f"no plinth slab {w} cells wide in castle_tiles.json")
            v = (h >> 8) % n_var
            if n_var > 1 and laid and laid[-1] == (w, v):
                v = (v + 1) % n_var                 # two neighbouring slabs never match
            laid.append((w, v))
            _pw, _ph, cells = atlas.piece(f"plinth_{w}_{v}")
            for k in range(w):
                c = cells[0][k]
                if c is None:
                    raise ValueError(f"plinth_{w}_{v} has an empty cell")
                plan[(x + k, y)] = c
            x += w
        i += run
    return plan


def collision_layer(atlas: Atlas) -> dict[Cell, Cell]:
    """Atlas tile for every collision cell. Only the visuals vary; each
    cell's collision kind (solid / one-way) is checked against the layout."""
    cells: dict[Cell, Cell] = {}
    piers = _pier_cols()
    plinth = _plinth_plan(atlas)
    variants = _Variants()
    for y, row in enumerate(COLLISION_LAYOUT):
        for x, ch in enumerate(row):
            if ch == ".":
                continue
            if ch == "#":
                if (x, y) in plinth:
                    tile = plinth[(x, y)]
                else:
                    # the ceiling mass sits in the top vignette: darker field
                    tile = atlas.field("wall_dark" if y == 0 else "wall", x, y)
            elif ch == "=":
                if y == FLOOR_ROW:
                    lo, hi = CARPET_COLS
                    if x == lo:
                        tile = atlas.tile("floor_carpet_l")
                    elif x == hi:
                        tile = atlas.tile("floor_carpet_r")
                    elif lo < x < hi:
                        tile = atlas.tile(f"floor_carpet_{variants.pick('carpet', 4, x, y)}")
                    else:
                        tile = atlas.tile(f"floor_marble_{variants.pick('marble', 4, x, y)}")
                elif _at(x, y + 1) not in SOLID and _at(x + 1, y) not in SOLID:
                    tile = atlas.tile("slab_end_r")
                elif _at(x, y + 1) not in SOLID and _at(x - 1, y) not in SOLID:
                    tile = atlas.tile("slab_end_l")
                else:
                    tile = atlas.tile(f"floor_marble_{variants.pick('marble', 4, x, y)}")
            elif ch == "^":
                tile = atlas.tile(f"cornice_{x % 2}")
            elif ch == "_":
                tile = atlas.tile(f"floor_carpet_{variants.pick('carpet', 4, x, y)}")
            elif ch == "-":
                left_open = _at(x - 1, y) != "-"
                right_open = _at(x + 1, y) != "-"
                run_start = x
                while _at(run_start - 1, y) == "-":
                    run_start -= 1
                mid = "ledge_m" if (x - run_start) % 2 == 0 else "ledge_p"
                if left_open and (x - 1) not in piers:
                    tile = atlas.tile("ledge_l")
                elif right_open and (x + 1) not in piers:
                    tile = atlas.tile("ledge_r")
                elif left_open and atlas.has_tile("ledge_el"):
                    tile = atlas.tile("ledge_el")      # butts against a pier on its left
                elif right_open and atlas.has_tile("ledge_er"):
                    tile = atlas.tile("ledge_er")      # butts against a pier on its right
                else:
                    tile = atlas.tile(mid)
            else:
                raise ValueError(f"unknown layout char {ch!r} at {x},{y}")
            want = "one_way" if ch == "-" else "solid"
            have = "one_way" if tile in atlas.one_way else ("solid" if tile in atlas.solid else "none")
            if have != want:
                raise ValueError(f"cell {x},{y} ({ch!r}) would use a {have} tile, needs {want}")
            cells[(x, y)] = tile
    return cells


def edge_layer(atlas: Atlas) -> dict[Cell, Cell]:
    """Lip / arris overlays over the exposed sides of wall cells."""
    bits = atlas.data["edge_bits"]
    cells: dict[Cell, Cell] = {}
    for y, row in enumerate(COLLISION_LAYOUT):
        for x, ch in enumerate(row):
            if ch != "#" or (y == FLOOR_ROW + 1 and _at(x, FLOOR_ROW) == "="):
                continue
            mask = 0
            if _at(x, y - 1) not in SOLID:
                mask |= bits["top"]
            if _at(x + 1, y) not in SOLID:
                mask |= bits["right"]
            if _at(x, y + 1) not in SOLID:
                mask |= bits["bottom"]
            if _at(x - 1, y) not in SOLID:
                mask |= bits["left"]
            if mask:
                cells[(x, y)] = atlas.edge(mask)
    return cells


class Layer:
    """Sparse cell -> atlas map that refuses silent overlaps."""

    def __init__(self, name: str, atlas: Atlas) -> None:
        self.name = name
        self.atlas = atlas
        self.cells: dict[Cell, Cell] = {}

    def put(self, x: int, y: int, tile: Cell) -> None:
        if (x, y) in self.cells and self.cells[(x, y)] != tile:
            raise ValueError(f"{self.name}: cell {x},{y} placed twice")
        if _at(x, y) in SOLID:
            return      # hidden behind a collision tile anyway
        self.cells[(x, y)] = tile

    def tile(self, name: str, x: int, y: int) -> None:
        self.put(x, y, self.atlas.tile(name))

    def piece(self, name: str, x: int, y: int) -> None:
        w, h, rows = self.atlas.piece(name)
        for j in range(h):
            for i in range(w):
                c = rows[j][i]
                if c is not None:
                    self.put(x + i, y + j, c)


STAND_MAX_GAP = 8       # a pricket stand only bridges gaps up to this (px)


def _candle_support(x: int, y: int, atlas: Atlas | None = None) -> tuple[str, int, int] | None:
    """Pick a fixture so a candle never floats, with nothing drawn below a
    candle's base unless a surface is right under it: none when it stands
    on a surface, a short pricket stand when a surface is at most
    STAND_MAX_GAP px below it, else a chain-hung lamp whose pan sits behind
    the candle's goblet foot. The lamp hangs from the corbel of the ledge
    above (``lamp_ledge_<base>``) or, with nothing above up to the arcade,
    from the arch soffit (``lamp_arch_<base>``, piece top on ARCH_ROW);
    ``<base>`` is the candle's base row relative to the piece's top.
    Returns (piece, cell x, cell y)."""
    cx = x // TILE
    for d in range(0, STAND_MAX_GAP + 1):
        row, off = divmod(y + d, TILE)
        if off == 0 and _at(cx, row) in SOLID + "-":
            if d == 0:
                return None
            top = (y + d - 2 * TILE) // TILE
            if (y + d - 2 * TILE) % TILE:
                raise ValueError(f"candle stand at {x},{y} is off the tile grid")
            return (f"candle_stand_{d}", cx, top)
    piece, top_row = "", -1
    for row in range((y - 1) // TILE, ARCH_ROW, -1):
        ch = _at(cx, row)
        if ch == "-":
            run_start = cx
            while _at(run_start - 1, row) == "-":
                run_start -= 1
            ends = _at(cx - 1, row) != "-" or _at(cx + 1, row) != "-"
            if ends or (cx - run_start) % 2:
                raise ValueError(f"candle at {x},{y}: the ledge cell above it has no centred corbel "
                                 "(ledge_m) for the lamp's eye")
            piece, top_row = f"lamp_ledge_{y - row * TILE}", row
            break
        if ch != ".":
            raise ValueError(f"candle at {x},{y}: no lamp anchor for a {ch!r} cell above it")
    else:
        piece, top_row = f"lamp_arch_{y - ARCH_ROW * TILE}", ARCH_ROW
    if atlas is not None and piece not in atlas.data["pieces"]:
        raise KeyError(f"candle at {x},{y} needs piece {piece!r}: add it to LAMPS in tiles.py")
    return (piece, cx, top_row)


def decor_layers(atlas: Atlas) -> tuple[Layer, Layer]:
    """Decor (architecture) and DecorFront (fixtures), composed from the
    pier / bay description above and the collision layout."""
    deco = Layer("Decor", atlas)
    front = Layer("DecorFront", atlas)
    width = len(COLLISION_LAYOUT[0])
    # frieze under the cornice, modillion and rosette alternating every 16 px
    for x in range(width):
        if _at(x, FRIEZE_ROW) == "." and _at(x, FRIEZE_ROW - 1) == "^":
            deco.tile("frieze_a" if x % 2 == 0 else "frieze_b", x, FRIEZE_ROW)
    # piers: pilaster, capital, fluted shaft (rings where ledges meet it), base
    for px, top, fixture in PIERS:
        deco.piece(top, px, ARCH_ROW)
        deco.piece("pier_cap", px, CAP_ROW)
        for y in range(CAP_ROW + 1, BASE_ROWS[0]):
            ring = _at(px - 1, y) == "-" or _at(px + 2, y) == "-"
            deco.piece("pier_shaft_ring" if ring else "pier_shaft", px, y)
        deco.piece("pier_base", px, BASE_ROWS[0])
        if fixture:
            front.piece(fixture, px, ARCH_ROW)
    # arches spanning every bay between niche wall, piers and right wall
    edges = [NICHE_RIGHT] + [c for px, _, _ in PIERS for c in (px, px + 2)] + [RIGHT_WALL]
    for left, right in zip(edges[0::2], edges[1::2]):
        deco.piece(f"arch_{right - left}", left, ARCH_ROW)
    piece, nx, ny = NICHE
    deco.piece(piece, nx, ny)
    for name, x, y in DECOR_EXTRA:
        if name in atlas.data["pieces"]:
            deco.piece(name, x, y)
        else:
            deco.tile(name, x, y)
    for name, x, y in FRONT_EXTRA:
        front.piece(name, x, y)
    for (x, y), _ in CANDLES:
        sup = _candle_support(x, y, atlas)
        if sup:
            front.piece(*sup)
    return deco, front


def encode_cells(cells: dict[Cell, Cell]) -> str:
    data = bytearray(struct.pack("<H", 0))
    for (x, y) in sorted(cells, key=lambda c: (c[1], c[0])):
        ax, ay = cells[(x, y)]
        data += struct.pack("<hhHHHH", x, y, 0, ax, ay, 0)
    return "PackedByteArray(" + ", ".join(str(b) for b in data) + ")"


# ===========================================================================
# Background layers (layers.json contract with backgrounds.py)
# ===========================================================================
def _show(path: str) -> str:
    """Repo-relative path for messages (absolute when outside the repo)."""
    return os.path.relpath(path, ROOT) if os.path.abspath(path).startswith(ROOT + os.sep) else path


def _vec(v: Any, n: int, key: str) -> list[float]:
    if not isinstance(v, (list, tuple)) or len(v) != n or not all(isinstance(c, (int, float)) for c in v):
        raise ValueError(f"{key} must be a list of {n} numbers, got {v!r}")
    return [float(c) for c in v]


def load_background_layers(path: str = LAYERS_JSON) -> tuple[list[dict[str, Any]], str]:
    """Validated background layers, far -> near, plus where they came from.
    Falls back to the original Sky / Hall pair when the file is absent or
    invalid (with a warning, so a broken manifest never breaks the room)."""
    if not os.path.exists(path):
        return [dict(e) for e in FALLBACK_BACKGROUNDS], "fallback (no layers.json)"
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        entries = raw["layers"] if isinstance(raw, dict) else None
        if not isinstance(entries, list) or not entries:
            raise ValueError('expected {"layers": [ ... ]} with at least one entry')
        out: list[dict[str, Any]] = []
        names: set[str] = set()
        for i, e in enumerate(entries):
            if not isinstance(e, dict):
                raise ValueError(f"layer {i} is not an object")
            name = str(e.get("name", ""))
            if not name or not all(ch.isalnum() or ch == "_" for ch in name) or name in names:
                raise ValueError(f"layer {i}: name must be unique [A-Za-z0-9_], got {name!r}")
            names.add(name)
            tex = str(e.get("texture", ""))
            if not tex.startswith("res://"):
                raise ValueError(f"layer {name}: texture must be a res:// path")
            if not os.path.exists(os.path.join(ROOT, tex[len("res://"):])):
                raise ValueError(f"layer {name}: {tex} does not exist")
            mod = e.get("modulate", [1, 1, 1, 1])
            if isinstance(mod, list) and len(mod) == 3:
                mod = mod + [1]
            layer: dict[str, Any] = {
                "name": name,
                "texture": tex,
                "scroll_scale": _vec(e.get("scroll_scale", [1, 1]), 2, "scroll_scale"),
                "repeat_size": _vec(e.get("repeat_size", [0, 0]), 2, "repeat_size"),
                "repeat_times": int(e.get("repeat_times", 1)),
                "z_index": int(e.get("z_index", -10)),
                "offset": _vec(e.get("offset", [0, 0]), 2, "offset"),
                "modulate": _vec(mod, 4, "modulate"),
            }
            if "autoscroll" in e:
                layer["autoscroll"] = _vec(e["autoscroll"], 2, "autoscroll")
            if "blend" in e:
                blend = str(e["blend"]).lower()
                if blend not in BLEND_MODES:
                    raise ValueError(f"layer {name}: blend must be one of {sorted(BLEND_MODES)}")
                layer["blend"] = blend
            if not -4096 <= layer["z_index"] <= 4096:
                raise ValueError(f"layer {name}: z_index out of range")
            # "motes" (Hall) and "twinkle" (Sky) are read at runtime by
            # scripts/world/ambient_fx.gd, not baked into the scene.
            known = {"name", "texture", "scroll_scale", "repeat_size", "repeat_times", "z_index",
                     "offset", "modulate", "autoscroll", "blend", "motes", "twinkle"}
            extra = sorted(set(e) - known)
            if extra:
                print(f"note: layers.json layer {name}: ignoring keys {extra}")
            out.append(layer)
        return out, _show(path)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"WARNING: {_show(path)} unusable ({exc}); using the fallback "
              "Sky/Hall backgrounds", file=sys.stderr)
        return [dict(e) for e in FALLBACK_BACKGROUNDS], "fallback (invalid layers.json)"


def foreground_layer(atlas: Atlas) -> dict[str, Any] | None:
    """The optional L5 occluder plane described in castle_tiles.json
    (``"foreground"``: texture, scroll_scale, z_index), or None when the
    atlas has none or its texture is missing."""
    fg = atlas.data.get("foreground")
    if not isinstance(fg, dict):
        return None
    tex = str(fg.get("texture", ""))
    if not tex.startswith("res://") or not os.path.exists(os.path.join(ROOT, tex[len("res://"):])):
        print(f"WARNING: foreground texture {tex!r} missing; no Foreground layer", file=sys.stderr)
        return None
    z = int(fg.get("z_index", 18))
    if not -4096 <= z <= 4096:
        raise ValueError("foreground z_index out of range")
    return {"texture": tex, "scroll_scale": _vec(fg.get("scroll_scale", [1.3, 1.0]), 2, "scroll_scale"),
            "z_index": z}


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(float(v))


def _v2(v: list[float]) -> str:
    return f"Vector2({_num(v[0])}, {_num(v[1])})"


# ===========================================================================
# Scene writer
# ===========================================================================
def build(layers_path: str = LAYERS_JSON, out_path: str = OUT) -> None:
    width = len(COLLISION_LAYOUT[0])
    height = len(COLLISION_LAYOUT)
    assert all(len(r) == width for r in COLLISION_LAYOUT), "ragged layout"

    atlas = Atlas()
    tiles = collision_layer(atlas)
    edges = edge_layer(atlas)
    deco, front = decor_layers(atlas)
    backgrounds, bg_source = load_background_layers(layers_path)

    ext: list[tuple[str, str, str]] = [
        ('Script', 'res://scripts/world/room.gd', '1_room'),
        ('AudioStream', 'res://assets/audio/music/nocturne_of_the_crimson_hall.ogg', '2_music'),
        ('PackedScene', 'res://scenes/fx/damage_number.tscn', '3_dmg'),
        ('TileSet', 'res://resources/tilesets/castle_tileset.tres', '6_tiles'),
        ('PackedScene', 'res://scenes/player/player.tscn', '7_player'),
        ('PackedScene', 'res://scenes/world/candle.tscn', '8_candle'),
        ('PackedScene', 'res://scenes/pickups/heart_big.tscn', '9_heart_big'),
        ('Script', 'res://scripts/world/enemy_spawner.gd', '10_spawner'),
        ('PackedScene', 'res://scenes/enemies/skeleton.tscn', '11_skeleton'),
        ('PackedScene', 'res://scenes/enemies/bat.tscn', '12_bat'),
        ('PackedScene', 'res://scenes/fx/death_flame.tscn', '13_spawn_fx'),
        ('Script', 'res://scripts/world/room_camera.gd', '14_camera'),
        ('PackedScene', 'res://scenes/world/save_point.tscn', '15_save'),
        ('PackedScene', 'res://scenes/pickups/world_item.tscn', '16_world_item'),
        ('Resource', 'res://resources/relics/leap_stone.tres', '17_leap_stone'),
        ('Resource', 'res://resources/accessories/ruby_ring.tres', '18_ruby_ring'),
        ('Texture2D', 'res://assets/sprites/heart_max_up.png', '19_heart_max'),
    ]
    tex_ids: dict[str, str] = {}
    for bg in backgrounds:
        if bg["texture"] not in tex_ids:
            tex_ids[bg["texture"]] = f"{20 + len(tex_ids)}_bg_{bg['name'].lower()}"
            ext.append(('Texture2D', bg["texture"], tex_ids[bg["texture"]]))
    fg = foreground_layer(atlas)
    if fg is not None:
        ext.append(('Texture2D', fg["texture"], '40_fg'))
    subs: list[tuple[str, str, dict[str, str]]] = []
    blend_ids: dict[str, str] = {}
    for bg in backgrounds:
        blend = bg.get("blend", "mix")
        if blend != "mix" and blend not in blend_ids:
            blend_ids[blend] = f"CanvasItemMaterial_{blend}"
            subs.append(("CanvasItemMaterial", blend_ids[blend], {"blend_mode": str(BLEND_MODES[blend])}))

    ITEM_REFS = {"leap_stone": '17_leap_stone', "ruby_ring": '18_ruby_ring',
                 "heart_max_up": '19_heart_max'}
    out: list[str] = [f'[gd_scene load_steps={len(ext) + len(subs) + 1} format=3]', '']
    out += [f'[ext_resource type="{t}" path="{p}" id="{i}"]' for t, p, i in ext]
    out += ['']
    for t, sid, props in subs:
        out.append(f'[sub_resource type="{t}" id="{sid}"]')
        out.extend(f'{k} = {v}' for k, v in props.items())
        out.append('')

    def node(name: str, type_: str | None = None, parent: str | None = None,
             instance: str | None = None, **props: str) -> None:
        head = f'[node name="{name}"'
        if type_:
            head += f' type="{type_}"'
        if parent is not None:
            head += f' parent="{parent}"'
        # Exported Node-typed properties must be declared in `node_paths`,
        # otherwise Godot keeps them as raw NodePaths and never resolves them.
        node_paths = [k for k, v in props.items() if v.startswith("NodePath(")]
        if node_paths:
            head += ' node_paths=PackedStringArray(' + ", ".join(f'"{k}"' for k in node_paths) + ')'
        if instance:
            head += f' instance=ExtResource("{instance}")'
        out.append(head + ']')
        out.extend(f'{k} = {v}' for k, v in props.items())
        out.append('')

    node("CastleHall", "Node2D", script='ExtResource("1_room")',
         room_id='&"crimson_hall"',
         display_name='"Crimson Hall"',
         size_in_tiles=f'Vector2i({width}, {height})',
         music='ExtResource("2_music")',
         damage_number_scene='ExtResource("3_dmg")',
         player='NodePath("Actors/Player")',
         camera='NodePath("Camera")')

    # --- Parallax background (far -> near) ------------------------------------
    for bg in backgrounds:
        props: dict[str, str] = {"scroll_scale": _v2(bg["scroll_scale"])}
        if bg["offset"] != [0.0, 0.0]:
            props["scroll_offset"] = _v2(bg["offset"])
        if bg["repeat_size"] != [0.0, 0.0]:
            props["repeat_size"] = _v2(bg["repeat_size"])
        if bg["repeat_times"] != 1:
            props["repeat_times"] = str(bg["repeat_times"])
        if "autoscroll" in bg and bg["autoscroll"] != [0.0, 0.0]:
            props["autoscroll"] = _v2(bg["autoscroll"])
        props["z_index"] = str(bg["z_index"])
        node(bg["name"], "Parallax2D", ".", **props)
        sprite: dict[str, str] = {}
        if bg["modulate"] != [1.0, 1.0, 1.0, 1.0]:
            sprite["modulate"] = "Color(" + ", ".join(_num(c) for c in bg["modulate"]) + ")"
        if bg.get("blend", "mix") != "mix":
            sprite["material"] = f'SubResource("{blend_ids[bg["blend"]]}")'
        sprite["texture"] = f'ExtResource("{tex_ids[bg["texture"]]}")'
        sprite["centered"] = "false"
        node("Sprite", "Sprite2D", bg["name"], **sprite)

    # --- Tiles --------------------------------------------------------------
    node("Decor", "TileMapLayer", ".", z_index="-5",
         tile_map_data=encode_cells(deco.cells),
         tile_set='ExtResource("6_tiles")', collision_enabled="false")
    node("DecorFront", "TileMapLayer", ".", z_index="-4",
         tile_map_data=encode_cells(front.cells),
         tile_set='ExtResource("6_tiles")', collision_enabled="false")
    node("Tiles", "TileMapLayer", ".",
         tile_map_data=encode_cells(tiles),
         tile_set='ExtResource("6_tiles")')
    node("TileEdges", "TileMapLayer", ".",
         tile_map_data=encode_cells(edges),
         tile_set='ExtResource("6_tiles")', collision_enabled="false")

    # --- Props --------------------------------------------------------------
    node("Candles", "Node2D", ".")
    for i, ((x, y), kind) in enumerate(CANDLES):
        props = {"position": f"Vector2({x}, {y})"}
        if kind == "big":
            props["drop_scene"] = 'ExtResource("9_heart_big")'
        node(f"Candle{i + 1}", None, "Candles", "8_candle", **props)

    # --- Save shrine and unique world items ---------------------------------
    node("SavePoint", None, ".", "15_save",
         position=f"Vector2({SAVE_POINT[0]}, {SAVE_POINT[1]})")

    node("WorldItems", "Node2D", ".")
    for item_id, x, y, grant, extra in WORLD_ITEMS:
        props = {"position": f"Vector2({x}, {y})",
                 "world_item_id": f'&"{item_id}"',
                 "grant": GRANT[grant]}
        for key, value in extra.items():
            if key == "item":
                props["item"] = f'ExtResource("{ITEM_REFS[value]}")'
            elif key == "icon":
                props["icon_override"] = f'ExtResource("{ITEM_REFS[value]}")'
            else:
                props[key] = value
        node(item_id, None, "WorldItems", "16_world_item", **props)

    # --- Actors (player, enemies, projectiles and pickups live here) --------
    node("Actors", "Node2D", ".")
    node("Player", None, "Actors", "7_player",
         position=f"Vector2({PLAYER_START[0]}, {PLAYER_START[1]})")

    # --- Spawners -----------------------------------------------------------
    node("SkeletonSpawner", "Node2D", ".", script='ExtResource("10_spawner")',
         enemy_scene='ExtResource("11_skeleton")', max_alive="3",
         spawn_interval="5.0", initial_delay="1.5", min_player_distance="100.0",
         spawn_effect_scene='ExtResource("13_spawn_fx")',
         enemy_container='NodePath("../Actors")')
    for i, (x, y) in enumerate(SKELETON_SPAWNS):
        node(f"SpawnPoint{i + 1}", "Marker2D", "SkeletonSpawner", position=f"Vector2({x}, {y})")

    node("BatSpawner", "Node2D", ".", script='ExtResource("10_spawner")',
         enemy_scene='ExtResource("12_bat")', max_alive="2",
         spawn_interval="7.0", initial_delay="4.0", min_player_distance="90.0",
         enemy_container='NodePath("../Actors")')
    for i, (x, y) in enumerate(BAT_SPAWNS):
        node(f"SpawnPoint{i + 1}", "Marker2D", "BatSpawner", position=f"Vector2({x}, {y})")

    # --- Foreground occluder plane (visual only, over the actors) -----------
    if fg is not None:
        node("Foreground", "Parallax2D", ".", scroll_scale=_v2(fg["scroll_scale"]), z_index=str(fg["z_index"]))
        node("Sprite", "Sprite2D", "Foreground", texture='ExtResource("40_fg")', centered="false")

    node("Camera", "Camera2D", ".", script='ExtResource("14_camera")',
         position=f"Vector2({PLAYER_START[0]}, {PLAYER_START[1] - 30})")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"wrote {_show(out_path)} ({width}x{height} tiles; {len(tiles)} collision, {len(edges)} edge, "
          f"{len(deco.cells)} decor, {len(front.cells)} front cells; backgrounds: {bg_source})")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--layers", default=LAYERS_JSON, help="background manifest (default: %(default)s)")
    ap.add_argument("--out", default=OUT, help="scene to write (default: %(default)s)")
    args = ap.parse_args(argv)
    build(os.path.abspath(args.layers), os.path.abspath(args.out))


if __name__ == "__main__":
    main()
