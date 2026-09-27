# Assumptions

Decisions taken where `SPEC.md` left a number, a format or an asset open
(Guardrail 0.1). Everything here is a placeholder meant to be overridden —
each entry says where to change it.

Status as of the Phase 2 milestone. Phases 0–2 are implemented; Phase 3
(first castle wing) has not been started.

---

## Engine, resolution and art

| Question (SPEC §10) | Decision | Where |
|---|---|---|
| 1. Internal resolution | **384×216**, integer-scaled, nearest-neighbour | `project.godot` → `[display]` |
| 1. Base tile size | **16×16 px** | `Room.tile_size`, `tools/asset_pipeline/environment.py` |
| 2. Protagonist | **Vesper**, a dhampir swordsman. No story premise yet — nothing in the code depends on one. | — |
| 3. Controller glyphs | **Device-specific**, resolved at runtime from the pad's USB vendor id | `scripts/autoload/controls.gd` |
| 5. Art & audio source | **Generated in-tree** by the Python pipeline in `tools/`, so there is no third-party licence to honour (Guardrail 0.3). Nothing is ripped or borrowed. | `tools/asset_pipeline/` |

Engine is Godot **4.7.2** (the installed 4.7 point release), as SPEC §3
requires.

## Save data

- **Format: JSON**, one file per slot at `user://saves/slot_N.json`
  (SPEC §3 offers `ResourceSaver` / `ConfigFile` / JSON and asks for the
  choice to be recorded). It is diffable, it survives a class being renamed,
  and — unlike `ResourceSaver` — loading one can never instantiate a script,
  so a hand-edited save is a wrong save rather than an arbitrary-code-execution
  hole. `SaveManager.FORMAT_VERSION` guards future migrations, and every read
  falls back to a new-game default rather than erroring.
- **3 slots**, the spec's minimum (`SaveManager.SLOT_COUNT`).
- Items are stored by `ItemData.id`, never by resource path, so `.tres` files
  can be renamed or moved freely. `ItemDB` refuses duplicate or blank ids at
  boot.

## Stats and progression

The spec fixes the XP curve and the damage formula; everything below is
filling in what it left blank. All of it lives in `scripts/progression/player_stats.gd`
as named constants.

| Value | Choice | Reasoning |
|---|---|---|
| Level 1 stats | STR 5, CON 6, DEF 2, LCK 4 | — |
| Max HP | `50 + Constitution × 5` | SPEC ties max HP to CON but gives no formula. These numbers make a level-1 Vesper 80 HP, which is what the Phase 1 prototype was tuned against, so combat feel did not change under the new system. |
| Per-level gains | +1 STR, +2 CON, +1 DEF, +1 LCK | The spec's own placeholder. |
| Level cap | 99 | Genre convention. |
| Level-up heals | Fully | Classic Castlevania/SOTN courtesy; the spec is silent. |
| Equipment maths | All flat bonuses summed, *then* percentages applied to that subtotal | The spec allows "flat or percentage" without saying how they combine. Order is documented on `GameManager._total()`. |
| Starting heart pool | 20, +5 per Heart Max Up, hard ceiling 99 | SPEC 4.2.2 says "a small base pool" and no more. `GameManager.STARTING_MAX_HEARTS`. |
| Enemy Defense | Authored per enemy on its `HealthComponent.defense` | The formula needs a number from the victim; the spec's enemy schema does not list one. |
| Enemy attack power | `Enemy.attack_power`, default 0 | Same reason, for the attacker's side. 0 means "the hitbox's base damage is the whole story". |
| Difficulty tiers | `Enemy.tier_multiplier`, scaling HP, damage, defense and XP | The spec's preferred "per-wing multiplier" approach (SPEC 4.5). Not exercised yet — there is only one room. |

**Deviation, flagged:** SPEC 4.2.1 suggests ~0.5 s of invincibility after a
hit. The project ships **1.2 s** (`Player.invincibility_time`), which is what
Phase 1 was play-tested at and is closer to SOTN's own generous i-frames.
It is one exported number on the player scene if you disagree.

## Input

- **Secondary attack** (SPEC 4.1 lists it in the base moveset) is bound to
  **V / U** and the **right shoulder button**. All four face buttons were
  already taken by jump / attack / sub-weapon / backdash, so the off hand went
  to the shoulder. Sub-weapon cycling, which used to be LB *or* RB, is now
  LB only.
- **Save points and NPCs are used with Up**, the classic Castlevania "use the
  thing you are standing on" input, rather than a new binding. It does nothing
  else while standing still, so nothing conflicts.
- **Runtime rebinding is deferred to Phase 4** (SPEC §3 marks it SHOULD and
  explicitly permits deferring with a flag — this is the flag). The system tab
  of the pause menu points at *Project Settings → Input Map* in the meantime,
  and every action already goes through named Input Map actions, so adding a
  rebinding screen later needs no gameplay changes.

## Testing

**Deviation, flagged:** SPEC §8 suggests the GUT framework. This project
vendors no third-party addons — the whole point of the in-tree asset pipeline
— so the unit tests use the same headless harness as the existing smoke test:
a scene, a list of checks, one process exit code.

```bash
godot --headless --path . res://tests/unit_test.tscn    # logic
godot --headless --path . res://tests/smoke_test.tscn   # the game itself
```

Tests use separate `user://tests/` directories and watchdog timers. Regression
and sequential cold-start suites also cover validation, write failures, backup
recovery, and loading through the title screen across separate processes.

## Merchant and shop (SPEC §10 q7, q8)

Not built — the merchant belongs to Phase 3. The economy underneath it is:
gold is tracked and saved, `ItemData.price` is authored on every item, and
`GameManager.spend_gold()` already refuses to go negative. A starter shop list
(the Vial of Vitae at 80 gold, the Ember Draught at 60, the Leather Cuirass at
200) is priced and waiting. Merchant identity and appearance are still open.

## Placeholders that are honestly placeholders

- **The map tab** lists the rooms walked rather than drawing them. The fog-of-war
  data it will draw (`GameManager.explored_rooms`) is already recorded and
  saved; the map itself is a Phase 3 deliverable (SPEC 4.4.3), as is the
  minimap and the save/boss room icons.
- **The Leap Stone sits on the open floor** of the Crimson Hall. The gate
  mechanism is real — the double jump starts locked and the relic unlocks it —
  but nothing in this one room is locked behind it. A genuinely inaccessible
  area is a Phase 3 requirement and needs more than one room to be meaningful.
- **Boss flags, difficulty tiers and room exploration** are saved and loaded
  but have nothing to record yet.
- **MP** predates the spec, which never mentions it. It is left alone, unused,
  reserved for spells or familiars.

## Review fixes: persistence and lifecycle

- The application starts at a title screen with Continue, New Game, and Load
  Slot. New Game does not overwrite disk saves. Only Crimson Hall currently
  ships; saves naming another room are refused by the title screen before
  changing the run.
- Format 1 envelopes require a version, timestamp, and character sheet with a
  level. Missing optional fields retain defaults; present fields must have
  valid types and finite, bounded numeric values. Unknown item IDs are skipped,
  and loaded equipment follows ownership, slot, and uniqueness rules.
- Saves are verified in a sibling temporary file before replacement. The prior
  valid primary is retained as `.bak`; unreadable primaries recover from that
  backup. Failed writes do not announce success or change the active slot.
- Stat refreshes preserve zero HP. Posthumous XP remains earned, but the dead
  player stays dead until the normal respawn creates a fresh player instance.
