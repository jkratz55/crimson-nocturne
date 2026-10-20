# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Crimson Nocturne is a 2D Metroidvania in **Godot 4.7**, GDScript only, built
against [`SPEC.md`](SPEC.md) — a phased specification with MUST/SHOULD/MAY
requirements. **Read `SPEC.md` before doing feature work**; it dictates the
build order (Phases 0–4), what is explicitly out of scope, and several exact
formulas. `ASSUMPTIONS.md` records every decision taken where the spec left a
blank, plus the three places the project knowingly deviates from it — update it
when you make another such call.

Phases 0–2 are implemented (moveset, combat, persistence, progression).
Phase 3 is the first castle wing: more rooms, a boss, a merchant, the real
minimap.

## Commands

Godot is not on `PATH` on this machine:

```bash
GODOT=/Applications/Godot.app/Contents/MacOS/Godot

$GODOT --path . res://scenes/main.tscn          # play
$GODOT --headless --path . --import             # reimport assets; parse errors only, and
                                                # only in the scripts it loads
$GODOT --headless --path . res://tests/unit_test.tscn    # logic tests   (exit 0 = pass)
$GODOT --headless --path . res://tests/smoke_test.tscn   # in-game tests (exit 0 = pass, ~40s)
```

There is no "run one test" granularity: each suite is a single scene that
prints `[ok]` / `[FAIL]` per check and exits non-zero on any failure. To narrow
a run, comment out calls in `_run()` in the relevant test script.

Headless stdout is block-buffered when redirected, so a long run looks hung —
redirect to a file and read it after the process exits rather than tailing it.

A clean `--import` proves little. It parses only the scripts it loads
(autoloads, what they depend on, scenes the editor layout reopens), so a
parse error in an otherwise unreferenced script passes silently. It also
prints no GDScript warnings, so it says nothing about `untyped_declaration` /
`unsafe_call_argument`. Run the test suites to load the rest, and check
warnings in the editor's Errors panel, or run a headless editor with
`--lsp-port` on a scratch copy of the project and read its diagnostics.

### Asset pipeline

All art and audio is generated, not sourced (see *Licensing* below). The art
rules every generator follows are in `docs/art_style.md`.

```bash
python3 tools/asset_pipeline/build_all.py         # all art + audio
python3 tools/asset_pipeline/equipment.py         # or one module on its own
python3 tools/level_builder/build_castle_hall.py  # regenerate the room scene
$GODOT --headless --path . --import               # then always reimport
```

- Modules: `hero` (+ `hero_rig`, `hero_figure`, `hero_paint`), `enemies`, `fx`,
  `props`, `items`, `equipment`, `ui`, `tiles`, `backgrounds`, `audio`. `common`
  holds the shared `RAMPS` palette and `SheetBuilder`; `preview.py` is dev-only
  and refuses to write into the repo.
- Run order: `build_castle_hall.py` reads `assets/tiles/castle_tiles.json` and
  `assets/backgrounds/layers.json`, so run it after `tiles.py` and
  `backgrounds.py` (`build_all.py` does not run it).
- Needs **Python ≥ 3.10** (`common.py` uses PEP 604 unions at runtime). macOS
  system `python3` is 3.9 and fails at import with a `TypeError` on
  `tuple[...] | tuple[...]`; use `/opt/homebrew/opt/python@3.14/bin/python3.14`
  or a venv from it.
- `pip install pillow numpy scipy`, plus `ffmpeg` with libvorbis for the music.
  Without libvorbis, `build_all.py` fails at the music step (the last one, after
  the art is written); run the art modules on their own instead.
- `tools/` and `docs/` carry `.gdignore`, so Godot never scans them.

### Regenerated files are not hand-editable

`scenes/rooms/castle_hall.tscn` is written by `build_castle_hall.py` (tile data
is a binary `PackedByteArray`; the ASCII layout in the builder is the readable
source). Re-running it **overwrites editor changes**. The same goes for:

- every `resources/sprite_frames/*_frames.tres` and `assets/sprites/*.png` /
  `*.json` (`SheetBuilder` and the sprite modules);
- `resources/tilesets/castle_tileset.tres` (its collision polygons live in
  `tiles.py`), `assets/tiles/castle_tiles.png` / `castle_tiles.json` and
  `assets/tiles/castle_foreground.png` (`tiles.py`);
- `assets/backgrounds/*.png` and `layers.json` (`backgrounds.py`; `ambient_fx.gd`
  reads the Hall `motes` from it at runtime);
- `assets/fonts/*.fnt` / `*.png` and `assets/ui/*.png` (`ui.py`, except
  `gold_icon.png` from `equipment.py`; windows are baked at their on-screen
  size, so `ui.WINDOWS` must match the NinePatchRect rects);
- `assets/audio/sfx/*.wav` and `assets/audio/music/*.ogg` (`audio.py`).

Edit the generator, not the output. An open editor re-saves generated `.tres`
files in its own format (uid lines, `loop` 1/0, reordered entries), so after a
regeneration compare SpriteFrames semantically, not byte for byte.

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
- **Animation timing is authored in 60 Hz ticks** (SpriteFrames `speed` 60,
  per-frame `duration` in ticks). Gameplay indexes into the generated sheets:
  `WeaponData.active_frames`, the throw spawn frame (`player.gd`, frame 1) and
  `Skeleton.THROW_RELEASE_FRAME` (must equal `ATTACK_RELEASE_FRAME` in
  `enemies.py`). Change frame counts or ticks in `hero.py` / `enemies.py` and
  these must move with them — no test pins the windows yet.
- **Presentation is visual only.** Flourishes (`land`, `run_start`, `skid`,
  `turn`, `apex`, `double_jump`) are picked on top of `Player.State`, never as
  new states; enemy death visuals hang off `Enemy._spawn_death_visuals()`;
  visual effects roll on a private `RandomNumberGenerator`, never the global
  one (the older screen shake and SFX pitch jitter still use the global RNG).

## Licensing constraint

Every sprite, tile, font, SFX and the music track is generated in-tree by
`tools/`. Do not add ripped assets from commercial games, and do not add
third-party packs or Godot addons without checking with the user — the
no-vendored-dependencies property is why the tests use the in-tree headless
harness instead of GUT (see `ASSUMPTIONS.md`). The art evokes *Symphony of
the Night* but never copies it — no traced or from-memory sprites — and
Vesper is an original character, not Alucard (`docs/art_style.md`, *Do not*).

## Other agent configs

A `~/.codex/config.toml` exists on this machine. If you want its MCP servers,
commands or instructions brought over, reply `/import` to see what's
importable, then `/import --yes=<digest>` to apply it. (If `/import` isn't
available here, run `claude import` from a terminal.)
