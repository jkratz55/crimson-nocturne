#!/usr/bin/env python3
"""Bootstrap generator for ``scenes/rooms/castle_hall.tscn``.

Why a generator?
----------------
Hand-authoring TileMapLayer data in a text scene is impractical (it is a
binary PackedByteArray), and we want the starter room to be reproducible
from a readable, diff-friendly ASCII layout. Run this once to (re)create the
room, then keep iterating on it in the Godot editor like any other scene.

    python3 tools/level_builder/build_castle_hall.py

WARNING: re-running overwrites any manual edits made to the scene in the
editor. Treat it as a bootstrap, not a round-trip format.

TileMapLayer data format (Godot 4.3+, "format 0")
-------------------------------------------------
    u16 format_version (= 0)
    then per cell, 12 bytes little-endian:
    i16 x, i16 y, u16 source_id, u16 atlas_x, u16 atlas_y, u16 alternative
"""
from __future__ import annotations

import os
import struct

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "scenes", "rooms", "castle_hall.tscn")

TILE = 16
PLAYER_START = (168, 256)

# ---------------------------------------------------------------------------
# Layout (48 x 18 tiles = 768 x 288 px, i.e. two screens wide)
#
#   #  solid brick (alternates brick_a / brick_b for variety)
#   =  solid floor top          ^  solid ceiling trim
#   -  one-way ledge            _  solid carpeted dais top
#   .  empty
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

# Decorative layer, drawn behind actors and without collision.
#   C pillar capital   P pillar shaft   B pillar base   s window sill
DECOR_LAYOUT = [
    "................................................",
    "................................................",
    "............C......................C............",
    "............P......................P............",
    "............P......................P............",
    "............P......................P............",
    "............P......................P............",
    "............P......................P............",
    "............P......................P............",
    "............P......................P............",
    "............P......................P............",
    "............P......................P............",
    "............P......................P............",
    "............P......................P............",
    "............P......................P............",
    "............B......................B............",
    "................................................",
    "................................................",
]

# Atlas coordinates in castle_tiles.png (see tools/asset_pipeline/environment.py).
BRICK_A, BRICK_B = (0, 0), (1, 0)
TILE_FOR = {
    "=": (2, 0),
    "-": (3, 0),
    "_": (2, 1),
    "^": (3, 1),
    "P": (5, 0),
    "C": (6, 0),
    "B": (7, 0),
    "s": (1, 1),
}

# Actor / prop placement in pixels (feet or base position).
CANDLES = [
    ((56, 96), "big"),     # reward for reaching the balcony
    ((248, 224), "small"),
    ((408, 112), "small"),
    ((520, 224), "small"),
    ((664, 168), "small"),
]
SKELETON_SPAWNS = [(48, 256), (620, 256), (728, 256), (360, 192)]
BAT_SPAWNS = [(216, 42), (400, 42), (552, 42), (696, 42)]


def encode_layer(layout: list[str], collision: bool) -> str:
    data = bytearray(struct.pack("<H", 0))
    for y, row in enumerate(layout):
        for x, ch in enumerate(row):
            if ch == ".":
                continue
            if ch == "#":
                atlas = BRICK_A if (x * 7 + y * 3) % 5 else BRICK_B
            else:
                atlas = TILE_FOR[ch]
            data += struct.pack("<hhHHHH", x, y, 0, atlas[0], atlas[1], 0)
    return "PackedByteArray(" + ", ".join(str(b) for b in data) + ")"


def build() -> None:
    width = len(COLLISION_LAYOUT[0])
    height = len(COLLISION_LAYOUT)
    assert all(len(r) == width for r in COLLISION_LAYOUT + DECOR_LAYOUT), "ragged layout"

    ext = [
        ('Script', 'res://scripts/world/room.gd', '1_room'),
        ('AudioStream', 'res://assets/audio/music/nocturne_of_the_crimson_hall.ogg', '2_music'),
        ('PackedScene', 'res://scenes/fx/damage_number.tscn', '3_dmg'),
        ('Texture2D', 'res://assets/backgrounds/sky.png', '4_sky'),
        ('Texture2D', 'res://assets/backgrounds/hall.png', '5_hall'),
        ('TileSet', 'res://resources/tilesets/castle_tileset.tres', '6_tiles'),
        ('PackedScene', 'res://scenes/player/player.tscn', '7_player'),
        ('PackedScene', 'res://scenes/world/candle.tscn', '8_candle'),
        ('PackedScene', 'res://scenes/pickups/heart_big.tscn', '9_heart_big'),
        ('Script', 'res://scripts/world/enemy_spawner.gd', '10_spawner'),
        ('PackedScene', 'res://scenes/enemies/skeleton.tscn', '11_skeleton'),
        ('PackedScene', 'res://scenes/enemies/bat.tscn', '12_bat'),
        ('PackedScene', 'res://scenes/fx/death_flame.tscn', '13_spawn_fx'),
        ('Script', 'res://scripts/world/room_camera.gd', '14_camera'),
    ]
    out: list[str] = [f'[gd_scene load_steps={len(ext) + 1} format=3]', '']
    out += [f'[ext_resource type="{t}" path="{p}" id="{i}"]' for t, p, i in ext]
    out += ['']

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
         display_name='"Crimson Hall"',
         size_in_tiles=f'Vector2i({width}, {height})',
         music='ExtResource("2_music")',
         damage_number_scene='ExtResource("3_dmg")',
         player='NodePath("Actors/Player")',
         camera='NodePath("Camera")')

    # --- Parallax background ------------------------------------------------
    node("Sky", "Parallax2D", ".", scroll_scale="Vector2(0.15, 0.25)",
         repeat_size="Vector2(480, 0)", repeat_times="3", z_index="-20")
    node("Sprite", "Sprite2D", "Sky", texture='ExtResource("4_sky")', centered="false")
    node("Hall", "Parallax2D", ".", scroll_scale="Vector2(0.7, 1)",
         repeat_size="Vector2(256, 0)", repeat_times="4", z_index="-10")
    # Darken the back wall so the playable foreground tiles read clearly —
    # the same depth cue SotN uses (bright foreground, muted background).
    node("Sprite", "Sprite2D", "Hall", modulate="Color(0.6, 0.6, 0.74, 1)",
         texture='ExtResource("5_hall")', centered="false")

    # --- Tiles --------------------------------------------------------------
    node("Decor", "TileMapLayer", ".", z_index="-5",
         tile_map_data=encode_layer(DECOR_LAYOUT, False),
         tile_set='ExtResource("6_tiles")', collision_enabled="false")
    node("Tiles", "TileMapLayer", ".",
         tile_map_data=encode_layer(COLLISION_LAYOUT, True),
         tile_set='ExtResource("6_tiles")')

    # --- Props --------------------------------------------------------------
    node("Candles", "Node2D", ".")
    for i, ((x, y), kind) in enumerate(CANDLES):
        props = {"position": f"Vector2({x}, {y})"}
        if kind == "big":
            props["drop_scene"] = 'ExtResource("9_heart_big")'
        node(f"Candle{i + 1}", None, "Candles", "8_candle", **props)

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

    node("Camera", "Camera2D", ".", script='ExtResource("14_camera")',
         position=f"Vector2({PLAYER_START[0]}, {PLAYER_START[1] - 30})")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"wrote {os.path.relpath(OUT, ROOT)} ({width}x{height} tiles)")


if __name__ == "__main__":
    build()
