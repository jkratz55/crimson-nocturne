# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Crimson Nocturne is a 2D Metroidvania in **Godot 4.7**, GDScript only, built
against [`SPEC.md`](SPEC.md) — a phased specification with MUST/SHOULD/MAY
requirements. **Read `SPEC.md` before doing feature work**; it dictates the
build order (Phases 0–4), what is explicitly out of scope, and several exact
formulas. `ASSUMPTIONS.md` records every decision taken where the spec left a
blank, plus the two places the project knowingly deviates from it — update it
when you make another such call.

Phases 0–2 are implemented (moveset, combat, persistence, progression).
Phase 3 is the first castle wing: more rooms, a boss, a merchant, the real
minimap.

## Commands

Godot is not on `PATH` on this machine:

```bash
GODOT=/Applications/Godot.app/Contents/MacOS/Godot

$GODOT --path . res://scenes/main.tscn          # play
$GODOT --headless --path . --import             # reimport assets; also compiles every
                                                # script — use it to surface errors/warnings
$GODOT --headless --path . res://tests/unit_test.tscn    # logic tests   (exit 0 = pass)
$GODOT --headless --path . res://tests/smoke_test.tscn   # in-game tests (exit 0 = pass, ~40s)
```

There is no "run one test" granularity: each suite is a single scene that
prints `[ok]` / `[FAIL]` per check and exits non-zero on any failure. To narrow
a run, comment out calls in `_run()` in the relevant test script.

Headless stdout is block-buffered when redirected, so a long run looks hung —
redirect to a file and read it after the process exits rather than tailing it.

### Asset pipeline

All art and audio is generated, not sourced (see *Licensing* below).

```bash
python3 tools/asset_pipeline/build_all.py         # all art + audio
python3 tools/asset_pipeline/equipment.py         # or one module on its own
python3 tools/level_builder/build_castle_hall.py  # regenerate the room scene
$GODOT --headless --path . --import               # then always reimport
```

- Needs **Python ≥ 3.10** (`common.py` uses PEP 604 unions at runtime). macOS
  system `python3` is 3.9 and fails at import with a `TypeError` on
  `tuple[...] | tuple[...]`; use `/opt/homebrew/opt/python@3.14/bin/python3.14`
  or a venv from it.
- `pip install pillow numpy scipy`, plus `ffmpeg` with libvorbis for the music.
- `tools/` and `docs/` carry `.gdignore`, so Godot never scans them.

### Regenerated files are not hand-editable

`scenes/rooms/castle_hall.tscn` is written by `build_castle_hall.py` (tile data
is a binary `PackedByteArray`; the ASCII layout in the builder is the readable
source). Re-running it **overwrites editor changes**. Same for
`resources/sprite_frames/*.tres` and `assets/sprites/*.json`, which
`SheetBuilder` emits. Edit the generator, not the output.

## Architecture

### The run lives in GameManager, not on the player

The player scene is destroyed and rebuilt on every room change and every death,
so nothing that must survive is stored on it. `GameManager` (autoload) owns
level, experience, stats, gold, hearts, the inventory, the seven equipment
slots, collected world items, defeated bosses, unlocked abilities, explored
rooms and the last checkpoint. `Player` reads through to it (`hearts`, `weapon`,
`secondary_weapon` are property getters) and keeps only current HP, which
`HealthComponent` needs locally — mirrored two-way through `_sync_from_game_state()`
under a `_syncing_health` guard. `SaveManager.to_save_data()` persists exactly
what `GameManager` holds and nothing else.

Autoload order matters and is set in `project.godot`:
`Events → Audio → Controls → GameFeel → ItemDB → GameManager → SaveManager`.

### Base stats vs. effective stats

`PlayerStats` is the character sheet a level-up writes to. Combat reads
`GameManager.get_strength()` / `get_defense()` / …, which layer equipped items
on top: **all flat bonuses summed first, then percentages applied to that
subtotal** (`GameManager._total()`). Equipment is therefore never baked into a
save. Never write equipment effects into `GameManager.stats`.

### One damage formula

`Combat.compute_damage()` is static and side-effect free. Both directions go
through it — the player's swings and everything that hurts the player.
`HealthComponent.take_damage()` applies what it is handed and does **no**
arithmetic of its own; its `defense` field is a stat that attackers read, not a
subtraction it performs. `Hitbox` carries `damage` (base) and `attack_power`
(the wielder's Strength), which the owner sets at runtime.

### Items are ids, never paths

Every inventory item is an `ItemData` `.tres` with a unique `id`. Saves and
shop lists store the id; `ItemDB` scans `resources/` at boot and maps ids back
to resources, pushing an error on duplicates or blanks. Adding a new item
category means a new `ItemData` subclass plus its folder in `ItemDB.ITEM_DIRS`.
Renaming or moving a `.tres` can never invalidate a save.

`WorldItem` (unique, placed by hand, never respawns) and `Pickup` (rolled from
a drop table, expires) are deliberately different things. A `WorldItem` needs a
`world_item_id` that is unique across the whole game — it is what the save
remembers, and two sharing one would make taking either delete both.

### Composition for combat

Anything damageable has a `Hurtbox` + `HealthComponent`; anything that deals
damage has a `Hitbox`. Hurtboxes **scan**, hitboxes are **scanned** — the
hurtbox polls overlaps every physics frame rather than relying on
`area_entered`, so standing inside an enemy keeps hurting once i-frames expire.
A hitbox hits each target once per `activate()`.

### Decoupling through Events

`Events` (autoload signal bus) is how gameplay talks to UI. Gameplay code never
holds references to UI nodes — a `SavePoint` emits `save_point_activated` and
whatever is drawing menus answers. Only genuinely cross-cutting signals belong
there; parent/child stays on regular node signals.

### Menus are modal

`PauseMenu` and `SaveMenu` each run `PROCESS_MODE_ALWAYS`, set
`get_tree().paused` themselves, and mark **every** input they see as handled so
nothing leaks into gameplay. `Main` runs `PROCESS_MODE_ALWAYS` with `World` and
`HUD` explicitly `PAUSABLE`, and skips its own pause handling while a menu is
open. The pause menu builds its rows from `GameManager` at runtime, so new
weapons, rings or item types appear with no UI changes.

### Conventions

- **Static typing everywhere** — typed vars, params, returns, `@export`s,
  `class_name` on custom classes. `project.godot` enables the
  `untyped_declaration` and `unsafe_call_argument` warnings; new code must
  compile with none.
- **Input is always a named Input Map action**, never a scancode or button
  index. Godot's SDL mapping means one map covers every pad; only *prompts* are
  device-aware, via `Controls.get_action_label()`. Adding an action means adding
  a row to `Controls._labels` too.
- **Analog interpretation lives where it is used** (`Player._move_input()`,
  `_is_holding_down()`), not in `Controls`.
- Physics layers are named in *Project Settings → Layer Names* (1 world,
  2 player, 3 enemy, 4/5 hurtboxes, 6/7 attacks, 8 pickup, 9 one_way) and used
  consistently — check them before adding an `Area2D`.
- Behaviour is explicit state machines (`Player.State` enum + `_change_state`,
  `Enemy._ai_process`), not branching `_process` bodies.

## Licensing constraint

Every sprite, tile, font, SFX and the music track is generated in-tree by
`tools/`. Do not add ripped assets from commercial games, and do not add
third-party packs or Godot addons without checking with the user — the
no-vendored-dependencies property is why the tests use the in-tree headless
harness instead of GUT (see `ASSUMPTIONS.md`).

## Other agent configs

A `~/.codex/config.toml` exists on this machine. If you want its MCP servers,
commands or instructions brought over, reply `/import` to see what's
importable, then `/import --yes=<digest>` to apply it. (If `/import` isn't
available here, run `claude import` from a terminal.)
