# Crimson Nocturne — Game Specification (v3)

## 0. How to Use This Spec (read first, agent guardrails)

This document uses **MUST** / **SHOULD** / **MAY** to signal requirement strength:
- **MUST** — non-negotiable; do not skip or substitute without asking.
- **SHOULD** — strong default; deviate only if there's a good technical reason, and note the deviation.
- **MAY** — optional / stretch, only after core milestones are complete.

**Guardrails:**

1. **Ambiguity protocol.** Where this spec doesn't give a specific number, formula, or asset, choose the simplest reasonable placeholder, record the assumption (in a code comment and in `ASSUMPTIONS.md` at the project root), and keep moving. Do not silently invent entire new systems (crafting, multiplayer, procedural generation, romance/dialogue trees, etc.) that aren't listed anywhere in this spec — flag them as a question instead.
2. **Scope discipline.** Build in the milestone order in Section 2. Do not start Phase 3 content work before Phase 1–2 are functional and verified. Do not expand the castle beyond the room counts in Section 2 without confirming.
3. **Asset & licensing guardrail (important).**
   - Do **not** use extracted/ripped sprites, tilesets, or music from actual Castlevania, Bloodstained, or any other commercial game. That is copyright infringement regardless of "spirit and style" framing.
   - Acceptable sources: assets the user supplies directly, CC0 assets, assets from the Godot Asset Library or itch.io/Kenney/OpenGameArt with licenses that permit the project's intended use, or purchased asset-store packs with a commercial license if that's the intended distribution.
   - Claude Code cannot draw pixel-art animation frames or compose original music/SFX. For any milestone that needs final art/audio, use clearly-labeled placeholder assets (colored rectangles/capsules for characters, simple tile blocks for terrain, silence or a single placeholder SFX) and structure `AnimationPlayer`/`AnimationTree`/`AudioStreamPlayer` usage so real assets can be dropped in later without code changes. Do not fabricate a "final" art pass.
4. **Verification loop.** After each milestone in Section 2, the project MUST run in the Godot editor/headless with zero script errors and no new console warnings, and the manual checklist in Section 8 for that milestone MUST pass before moving on. Report a short pass/fail summary at each milestone boundary.
5. **Version control.** Initialize a git repository at project start (with a Godot-appropriate `.gitignore`) if one doesn't exist. Commit at each milestone boundary and after each meaningfully complete feature, with descriptive messages.
6. **Engine version.** Target Godot **4.7** exactly. If 4.7 is not available/installed when work starts, stop and ask which version to use rather than silently substituting one.

---

## 1. Vision & Narrative

Crimson Nocturne is a spiritual successor to *Castlevania: Symphony of the Night*, built as a single-player, 2D Metroidvania set in a single large castle (in the tradition of SOTN or *Bloodstained: Ritual of the Night*), composed of multiple visually distinct wings/biomes. The player controls a bare-bones Level 1 character who grows stronger by defeating enemies and finding equipment, progressing deeper into a castle that grows correspondingly more dangerous.

The entire castle **MUST** be hand-crafted — no procedural or randomized level generation (see Non-goals, Section 2).

**Still open / TBD (see Section 10):** protagonist identity and name, story premise (why is the character in the castle?), narrative delivery method beyond NPC dialogue.

---

## 2. Scope & Milestones

Given the size of a full metroidvania, work MUST proceed in phases with a concrete Definition of Done (Section 9) at each boundary.

- **Phase 0 — Project Skeleton:** Godot 4.7 project created, git initialized, folder structure (Section 7.3) in place, input map configured for keyboard + controller, empty test scene loads and runs.
- **Phase 1 — Movement & Combat Prototype:** Full player moveset (Section 4.1) working in a single flat test room, including primary attack, secondary attack, sub-weapon throw with heart consumption (Section 4.2.2), against 1–2 placeholder enemy types. No progression/persistence systems yet.
- **Phase 2 — Persistence & Progression:** Full SOTN-style save/load (Section 4.4.2), leveling (Section 4.3), gold and heart resource tracking (Section 4.7), inventory/equipment/stats pause menu (Section 5.2) working end-to-end in the test room.
- **Phase 3 — First Castle Wing (vertical slice):** One themed wing with **12–18 rooms**, **1 save room**, **4–6 enemy types** (with gold/heart drop tables), **1 boss** with health bar UI, **1 ability-gated traversal upgrade** (Section 4.1) that locks off part of the wing until acquired, **1 merchant NPC** with shop UI (Section 4.6, 4.7), and a minimap with fog of war plus marked save/boss rooms (Section 4.4.3).
- **Phase 4 — Content Expansion:** Additional wings, enemies, weapons, armor, sub-weapons, bosses, NPCs — scoped and prioritized with the user before starting, not assumed.

**Non-goals (explicitly out of scope unless the user says otherwise):**
- Multiplayer / co-op / PvP (single-player only, confirmed).
- Mobile or touch-screen controls.
- Procedurally generated levels — the castle is entirely hand-authored (confirmed).
- Cloud saves / online services / achievements platforms.
- Localization into multiple languages.
- Cinematic cutscenes (dialogue boxes only — see 4.6).
- Any death penalty beyond returning to the last save point (confirmed — see 4.4.2).

---

## 3. Technical Requirements

- **MUST** be built with Godot Engine **4.7**.
- **MUST** use GDScript with static typing throughout: typed variables, typed function signatures and return types, `class_name` on all custom classes, typed `@export` fields. Enable Godot's static-typing warnings project-wide; the project should build with zero untyped-variable warnings in new code.
- **MUST** support keyboard and Xbox/PlayStation controllers via Godot's **Input Map** (action names, not hardcoded scancodes/button indices), so both device types work through the same action bindings out of the box.
- **SHOULD** support runtime input rebinding via a settings menu (MAY be deferred to Phase 4 if time-constrained — flag if deferring).
- **MAY** show device-specific button glyphs (Xbox vs PlayStation) in prompts; if out of scope for now, use generic glyphs and note it as a TODO.
- **MUST** support save/load, modeled directly on Symphony of the Night's save behavior. Save data **MUST** include, at minimum:
  - Last save room and exact position within it (player resumes there on load/respawn).
  - Full inventory: all owned weapons, armor, necklace, rings, sub-weapons, and consumable items.
  - Currently equipped primary weapon, secondary weapon, armor, necklace, up to 2 rings, and equipped sub-weapon.
  - Map exploration state (which rooms/tiles have been revealed on the minimap/full map).
  - Which unique, non-respawning world items have already been collected.
  - Gold amount and current/max hearts.
  - Which bosses have been defeated (so they don't need re-fighting and any resulting unlocks persist).
  - Player level, current XP, and derived stats.
  - Unlocked traversal abilities (Section 4.1).
  - **SHOULD** support a minimum of 3 save slots. **SHOULD** use Godot's `ResourceSaver`/`ConfigFile`/JSON (pick one and document the choice in `ASSUMPTIONS.md`) rather than raw binary.
- **MUST** target 60 FPS on desktop (Windows/macOS/Linux) at a fixed internal resolution appropriate for pixel art (e.g., 320×180 or 384×216 scaled up with integer scaling) — confirm exact target with user if a specific pixel-art resolution matters (Section 10).
- **MUST** use git for version control from project start.

---

## 4. Core Gameplay Systems

### 4.1 Movement & Traversal

Base moveset (**MUST**):
- Primary attack, secondary attack, sub-weapon throw, backward dash, jump, crouch.
- While crouched, the player's collision hitbox **MUST** shrink to match the crouched sprite, and the player **MUST** be able to perform the primary attack from crouch with a crouch-specific hitbox/animation.
- Jump **SHOULD** support variable height based on button hold duration, plus coyote time (~100ms) and jump input buffering (~100ms) for responsive platforming feel.

**Ability-gated traversal (MUST — this is the core metroidvania mechanic and must not be dropped):**
The castle **MUST** contain at least one traversal ability that starts locked and is unlocked by finding a specific item/relic in the world (e.g., double jump, an upgraded longer dash, a wall-cling/wall-jump). At least one room or area **MUST** be inaccessible until that ability is acquired, and backtracking to that area after acquiring it **MUST** be possible. Phase 3 requires at least one such gate; Phase 4 should add more as content grows.

### 4.2 Combat

#### 4.2.1 Primary & Secondary Attacks
- Primary and secondary attacks **MUST** each be defined by data (a Resource, not hardcoded per-weapon script logic) specifying damage, hitbox shape/duration, and animation reference, so new weapons can be added without new code.
- Hurtboxes/hitboxes **MUST** use Godot `Area2D` nodes, not manual distance/overlap math.
- On taking damage, the player **MUST** get brief invincibility frames (**SHOULD** default to ~0.5s) and knockback.
- Blocking/parry: not specified — out of scope unless requested later.

#### 4.2.2 Sub-Weapons (Symphony of the Night model — MUST)
- Sub-weapons work as in SOTN: the player can hold **multiple discovered sub-weapon types simultaneously** (each found once in the world, permanently added to the sub-weapon inventory) and **switch which one is currently equipped** via a dedicated input and/or the pause menu.
- Using the equipped sub-weapon consumes **hearts** from a single **shared heart pool** (not a per-weapon pool). Heart cost **MUST** vary per sub-weapon type (defined as data on the sub-weapon Resource), matching SOTN's design where stronger sub-weapons cost more hearts per use.
- Max heart capacity **MUST** be able to increase via world pickups ("Heart Max Up" style items), starting from a small base pool.
- Sub-weapons **MUST** be defined as data-driven Resources: id, name, icon, heart cost, damage, projectile/behavior type (e.g., straight-line throw, arc throw, short-range strike), animation reference, and cooldown.
- If the player has 0 hearts, attempting to use the sub-weapon **MUST** fail silently (or with a small UI cue) rather than erroring.

- **Placeholder damage formula (MUST use this starting point, tune later):**
  `damage_dealt = max(1, (weapon_base_damage + floor(player_strength * 0.5)) - floor(enemy_defense * 0.5))`, with a flat ±10% random variance. Sub-weapon damage uses the same formula with the sub-weapon's own base damage. Mark this clearly as a placeholder to rebalance once content exists.

### 4.3 Progression / RPG Systems

- **Stat schema (MUST, starting point — confirm/adjust with user):** Strength (melee/weapon damage), Constitution (max HP), Defense (damage reduction), Luck (item drop rate / crit chance). Extend only if the user asks for more (e.g., SOTN-style Intelligence).
- **Leveling (MUST, placeholder curve):** `xp_to_next_level = 50 * current_level^1.5`, rounded up. On level-up, stats increase by a small fixed amount per stat (values TBD — placeholder +2 CON/+1 STR/+1 DEF/+1 LCK per level) — mark as tunable.
- **Equipment (MUST) data schema:**
  - Weapon (primary/secondary): base damage, attack speed multiplier, range/hitbox reference, animation reference.
  - Armor: defense value, optional elemental resistances (MAY be deferred).
  - Necklace / Ring (up to 2 equipped): flat or percentage stat modifiers (e.g., +X Strength, +X% Defense).
  - All equipment **MUST** be defined as Godot `Resource` (`.tres`) files, not hardcoded in scripts, so new items are data, not code.
- Enemies **MUST** grant XP on defeat, scaled to their difficulty tier (Section 4.5).

### 4.4 World & Exploration

#### 4.4.1 Rooms & Level Structure
- The castle **MUST** be composed of individual, hand-authored room scenes connected via marked transition points (doors/edges), assembled into wings/areas per Section 2. No procedural generation (Section 2).
- Hidden/breakable walls revealing secret rooms **SHOULD** be included at least once per wing as a genre-standard feature (MAY be deferred past Phase 3 if time-constrained).

#### 4.4.2 Save Rooms & Respawn
- Save rooms **MUST** let the player save progress (writing all data listed in Section 3) and **SHOULD** fully restore HP and hearts on use (classic Castlevania/SOTN candle/save-point behavior).
- On death, the player **MUST** respawn at their last save point with the state as of that last save (position, HP/hearts restored). **Confirmed:** there is **no penalty** beyond returning to the last save point — no loss of XP, levels, gold, or items on death.

#### 4.4.3 Minimap
- A minimap **MUST** appear in a screen corner (top-right or bottom-right) showing explored rooms only, revealed via **fog of war** as the player physically explores each room (unexplored areas stay hidden/blank).
- Save rooms and boss rooms **MUST** be visually distinguished with a unique icon on the map once discovered, so the player can identify them at a glance.
- A full-castle map screen accessible from the pause menu **SHOULD** be included (SOTN-style), showing overall explored progress with the same save/boss room icons, and unexplored areas left blank.

### 4.5 Enemies & Bosses

- Enemies **MUST** use a shared, data-driven base (Resource or exported stats) for HP, damage, XP reward, and behavior type, so new enemies are mostly data + a behavior state machine, not bespoke scripts.
- Enemy AI **SHOULD** use a simple state machine (e.g., idle/patrol → aggro/chase → attack → stagger/dead).
- **Difficulty scaling (MUST specify a method):** enemies are stronger the deeper into the castle the player goes. **Placeholder approach:** each wing/area defines a difficulty tier multiplier applied to base enemy stats, rather than continuous scaling — simpler to author and balance. Confirm with user if a different approach (e.g., per-room tuning) is preferred.
- **Drops (MUST):** each enemy type's data **MUST** define independent drop chances for gold (amount range) and hearts (amount range) — e.g., `gold_drop_chance: 0.3, gold_amount_range: [5, 15]`, `heart_drop_chance: 0.2, heart_amount_range: [1, 3]`. Not every enemy needs to drop both; values are per-enemy data.
- **Bosses (MUST):** each wing in Phase 3+ content **MUST** end in (or contain) at least one boss encounter: a unique enemy with its **own health bar UI** (Section 5.1), distinct attack patterns, and at least one phase change at a health threshold (e.g., 50%). Boss defeat state **MUST** be saved (doesn't need re-fighting) and **SHOULD** unlock further progression (item, ability, or path).

### 4.6 NPCs & Dialogue

- NPCs **MUST** be interactable (context prompt) and trigger a dialogue box showing linear text (branching dialogue is out of scope unless requested later).
- **Merchant NPC (MUST):** exactly one merchant-type NPC **MUST** exist in the Phase 3 vertical slice, opening a shop interface (Section 5.3) when interacted with. The merchant is the only way to spend gold. Merchant identity/name/character design is TBD (Section 10); functionally it just needs to exist and sell at least a small starting set of items (see 4.7).

### 4.7 Items & Economy

- **Gold (MUST):** a persistent currency, tracked in save data (Section 3), gained primarily from random enemy drops (Section 4.5) and optionally from fixed world pickups. Spent exclusively at the merchant NPC (Section 4.6).
- **Hearts (MUST):** the sub-weapon resource (Section 4.2.2), gained from random enemy drops (Section 4.5) and fixed world pickups, tracked in save data, capped at a max that can be increased via "Heart Max Up" world items.
- **World items (MUST):** unique weapons, armor, rings, necklaces, and ability-unlocking relics are placed as scene instances, pickable once, and **MUST NOT** respawn once collected (persisted via save data per Section 3).
- **Merchant inventory (placeholder — logged as an assumption, adjust if desired):** the merchant's shop **SHOULD** sell at least one consumable HP-restoring item (e.g., a potion) purchasable with gold, since a shop needs something meaningful to offer from the start. Additional shop items (sub-weapons, upgrade materials, equipment) **MAY** be added in Phase 4.

---

## 5. UI/UX Requirements

### 5.1 HUD (in-game overlay)
- **MUST** show: HP bar, current level, heart count (sub-weapon resource), and the currently equipped sub-weapon's icon.
- **MUST** show the minimap (Section 4.4.3).
- **MUST** show a boss health bar during boss encounters (Section 4.5).
- **SHOULD** show current gold count, at least when relevant (e.g., always in HUD, or shown when opening inventory/shop at minimum).

### 5.2 Pause Menu
A single pause menu **MUST** be accessible at any time during gameplay (outside of forced sequences like cutscenes/dialogue), navigable by both keyboard and controller, containing at minimum:
- **Equipment tab (MUST):** equip/unequip primary weapon, secondary weapon, sub-weapon, armor set, necklace, and up to 2 rings.
- **Stats tab (MUST):** current level, XP progress to next level, all stats (Strength/Constitution/Defense/Luck), gold, and heart capacity.
- **Map tab (SHOULD):** full-castle map view (Section 4.4.3).
- **Settings tab (SHOULD):** volume controls, and input rebinding if in scope (Section 3).

### 5.3 Shop UI
- **MUST** be a distinct interface opened via the merchant NPC (Section 4.6), showing: item list with name/description/price, player's current gold, and a buy confirmation flow that deducts gold and adds the item to inventory. Insufficient gold **MUST** block the purchase with clear feedback rather than allowing negative gold.

---

## 6. Art & Audio Direction

- Visual style and audio **SHOULD** evoke 2D Castlevania games (SOTN-era) in spirit — palette, mood, gothic architecture, orchestral/atmospheric music — but **MUST NOT** use actual copyrighted assets from those games (see Guardrail 3 in Section 0).
- **MUST** use placeholder art/audio during Phase 1–2 (see Guardrail 3); final art/audio integration is a separate, later task and likely requires the user to source or commission assets — Claude Code should not attempt to generate final pixel-art frames or music.
- Technical specs (**TBD with user, Section 10**): base tile size (e.g., 16×16 px), character sprite sheet dimensions, target animation frame rate, and internal render resolution (ties to Section 3's resolution target).
- Animation quality (fluid, responsive combat feel) is a core pillar of this spec — a valid priority, but note that "fluid animation" depends on final art assets Claude Code cannot produce; what Claude Code *can* guarantee is animation-ready code architecture (proper use of `AnimationPlayer`/`AnimationTree`, state-driven transitions, no blocking animation calls) so that once real art arrives, swapping it in doesn't require rewrites.

---

## 7. Architecture

### 7.1 Data-Driven Content
- Weapons, sub-weapons, armor, rings, necklaces, enemies, and world items **MUST** be defined as Godot `Resource` (`.tres`) files with typed script backing, not hardcoded per-instance logic, so new content is authored as data.

### 7.2 Patterns
- **SHOULD** use a signal/event-bus autoload for decoupled cross-system communication (e.g., `EventBus.enemy_defeated.emit(...)`, `EventBus.gold_changed.emit(...)`) rather than direct node references across unrelated systems.
- **SHOULD** use autoload singletons only for genuinely global systems: `GameManager` (current run state, including gold/hearts/level), `SaveManager`, `EventBus`. Avoid making everything an autoload.
- **SHOULD** implement player and enemy behavior as explicit state machines (states as either an enum + match, or separate state Resource/Node classes) rather than large branching `_process` methods.
- Rooms **SHOULD** be individual scenes loaded/unloaded by a room/world manager, not all held in memory simultaneously.

### 7.3 Suggested Folder Structure (SHOULD)
```
res://
  autoloads/
  scenes/
    player/
    enemies/
    npcs/
    rooms/<wing_name>/
    ui/
  resources/
    weapons/
    sub_weapons/
    armor/
    enemies/
    items/
  scripts/ (only if not colocated with scenes)
  assets/
    sprites/
    audio/
    tilesets/
```

---

## 8. Testing & Verification

- After each milestone (Section 2), the project **MUST** run with zero script errors and no new warnings.
- **SHOULD** use the GUT (Godot Unit Test) framework for unit tests on non-visual logic: damage formula, XP/leveling curve, save/load round-trip integrity (including gold, hearts, map exploration, and defeated-boss flags), and enemy drop-chance rolls.
- **MUST** perform a manual playtest checklist at each milestone boundary:
  - **Phase 1:** jump/dash/attack/crouch all function with no clipping through geometry; sub-weapon throw consumes hearts and deals damage, and fails gracefully at 0 hearts; enemy takes damage and dies; player takes damage, gets i-frames, and knockback.
  - **Phase 2:** gold, hearts, level/XP, and equipped items all persist correctly through a save → quit → reload cycle; pause menu equipment/stats tabs function correctly.
  - **Phase 3:** minimap fog of war reveals correctly as rooms are explored, with save/boss rooms distinctly marked; the ability-gated area is inaccessible before the relevant relic is found and accessible after; boss health bar displays and depletes correctly, and the boss's defeated state persists after reload; merchant shop opens, purchase flow deducts gold and grants the item, and blocks purchases when gold is insufficient.
  - Report results briefly before proceeding to the next milestone.

---

## 9. Definition of Done (per milestone)

A milestone is complete when: all features listed for that phase in Section 2 are implemented, the Section 8 checklist for that phase passes, the project has zero script errors/new warnings, changes are committed to git with a descriptive message, and any assumptions made along the way are recorded in `ASSUMPTIONS.md`.

---

## 10. Open Questions for the User

These still need a decision before or during the relevant phase — Claude Code should ask rather than assume:

1. Target resolution / pixel-art scale and base tile size? *(blocks art pipeline setup)*
2. Any narrative/story premise beyond "explore the castle," and does the protagonist have a name? *(not blocking for Phase 1–3, but affects NPC dialogue content)*
3. Is controller button-prompt glyph swapping (Xbox vs PlayStation icons) needed, or are generic prompts acceptable for now?
4. Should input rebinding be in the Phase 2 scope or deferred to Phase 4?
5. Source of final art/audio assets — will the user supply/commission these, or should Claude Code search for licensed placeholder/asset-store packs (and if so, is there a budget/license constraint)?
6. Numeric scope check for Phase 3 (12–18 rooms, 4–6 enemy types, 1 boss) — adjust if a different size is intended.
7. Merchant NPC identity/character design (name, appearance, personality) — functionally defined (Section 4.6/4.7), but no character concept yet.
8. Beyond the starting HP potion, is there a specific list of items the user wants the merchant to sell, or should Claude Code propose a starter list in Phase 3?
