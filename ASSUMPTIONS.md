# Assumptions

Decisions taken where `SPEC.md` left a number, a format or an asset open
(Guardrail 0.1). Everything here is a placeholder meant to be overridden —
each entry says where to change it.

Status as of the Phase 2 milestone. Phases 0–2 are implemented; Phase 3
(first castle wing) has not been started. A user-requested art pass toward
*Symphony of the Night* has been applied on top (see the art deviation below
and *Art pass: generated assets*).

---

## Engine, resolution and art

| Question (SPEC §10) | Decision | Where |
|---|---|---|
| 1. Internal resolution | **384×216**, integer-scaled, nearest-neighbour | `project.godot` → `[display]` |
| 1. Base tile size | **16×16 px** | `Room.tile_size`, `tools/asset_pipeline/tiles.py` |
| 2. Protagonist | **Vesper**, a dhampir swordsman. No story premise yet — nothing in the code depends on one. | — |
| 3. Controller glyphs | **Device-specific**, resolved at runtime from the pad's USB vendor id | `scripts/autoload/controls.gd` |
| 5. Art & audio source | **Generated in-tree** by the Python pipeline in `tools/`, so there is no third-party licence to honour (Guardrail 0.3). Nothing is ripped or borrowed. The art rules the generators follow are in `docs/art_style.md`. | `tools/asset_pipeline/` |

Engine is Godot **4.7.2** (the installed 4.7 point release), as SPEC §3
requires.

**Deviation, flagged:** SPEC §6 and Guardrail 3 call for placeholder art
during Phases 1–2 and say not to fabricate a "final" art pass. The project
now ships a SotN-style art pass, made at the user's explicit request
("adjust the art style, animations, and sprites to much more closely
resemble *Castlevania: Symphony of the Night*"). Everything is still
generated in-tree by `tools/`, so the licensing guardrail holds. *Symphony
of the Night* is evoked, never copied: nothing is ripped, traced or
recreated from memory, and Vesper stays an original character, not an
Alucard clone. Gameplay numbers are unchanged apart from the tick rounding
recorded in the *Timing record* row below.
The rules are in `docs/art_style.md`; the decisions are in the two sections
that follow.

## Presentation: runtime effects (SotN art pass)

Everything below is visual only. None of it changes state, velocity,
damage, collision, drops or what input is accepted.

| Question | Decision | Where |
|---|---|---|
| Transition animations | `land`, `run_start`, `skid`, `turn`, `apex` and the drawn `double_jump` are flourishes picked by a visual selector on top of the state machine (no new states). Each plays only while it fits — `run_start` while a direction is held, `skid` and `land` while none is — and is dropped as soon as it stops fitting. `turn` plays only when the hero turns from a stand, and holds only while \|velocity.x\| < `RUN_START_MAX_SPEED` (40 px/s); once the run carries him it hands off to `run_start` (with its push-off dust), so his planted feet never skate. A one-tick tap reversal still shows the whole 6-tick pivot; a turn while running is an instant flip. | `scripts/player/player.gd` (`_animate_grounded`, `_start_run_start`, `_animate_air`) |
| Double jump | The drawn somersault replaces the rotation tween whenever `vesper_frames` has `double_jump`; the tween is kept as a fallback. | `Player._play_double_jump()` |
| Afterimages | During the backdash and the drawn double jump, 6 ghosts in a ring are snapshotted every 3 ticks and live 15 ticks. Each starts 5 ticks into the fade (red/green ≈ 0.80). Red and green fall 5/128 per tick; blue starts at 1.0 and rises 6/128 per tick once red/green are below 124/128 (capped at 240/128). Every ghost is drawn at 50 % from its first tick and flickers on alternate ticks. A ghost-only shader lifts texels to at least (0.22,0.24,0.40) before the tint. Ghosts sit at player z − 1 with their own materials. | `scripts/fx/afterimage_trail.gd` |
| Enemy hit flash | `hit_flash.gdshader`: white for 2 ticks in solid mode (each material's outline tones, luma < 0.16, are kept), then crimson (196,62,66) at 60 % in tint mode for 2 ticks. Ticks are game time, so hit-stop holds the white. | `Enemy._flash()` |
| Enemy deaths | Skeletons break into the 6 `skeleton_parts` pieces using the launch, spin and pop tables in `Skeleton` (`PART_VELOCITY`, `PART_SPIN_DEG_PER_TICK`, `PART_POP_TICKS`); the pieces fly away from the last blow, flash white for 3 ticks, then each bursts into `fire_pop.tscn`. Bats burst into `fire_pop_large.tscn` and shed 7 torn membrane scraps (`DebrisBits.shaped`): rows 5/3/1 px, a light (178,176,222) strut row on every other scrap and a 1-px (196,202,240) hem down the side every scrap hangs from — cool lavender, so they part from the warm rose dado as well as the dark ashlar. They flip every 6 ticks, fall at up to 24 px/s, life spread 0.2. Fire colours fly only as 1×1 embers that die within 0.3 s. Killing blows use `hit_spark_burst`. Loot, XP and signals are untouched (`Enemy._spawn_death_visuals()` is the only hook). | `enemy.gd`, `skeleton.gd`, `bat.gd`, `bone_part.gd`, `debris_bits.gd`, `bat.tscn` |
| Hit sparks | Ordinary hits pick `default` or `slash` at random, with ±3 px of jitter. | `OneShotEffect.random_animations`, `Enemy._on_hit_received()` |
| Damage numbers | Unfold from a 2× wide strip over 6 ticks in whole glyph rows, rise 0.5 px per tick, flicker between two tones, and spend the last 6 of 64 ticks at 50 %. A number landing within 12 px of a live one starts 10 px above it. Offsets: player (0,−52), skeleton (0,−47), bat (0,−24). | `scripts/fx/damage_number.gd`, `damage_number_offset` exports |
| Player death | When the death animation ends, the body fades out over 0.6 s into `death_mist.tscn`, driven by `self_modulate` (the i-frame blink owns `modulate.a`). | `Player._dissolve_body()` |
| Dust and the double-jump ring | Dust is kicked up at the back foot on `run_start` and at the front foot on `skid`. The double-jump ring stays where the jump started. | `player.gd` effect exports |
| Landing dust | Kicked up on the touchdown tick in any state (aerial swings included) when the last airborne speed was 200 px/s or more. | `Player._after_move()`, `LAND_DUST_MIN_FALL` |
| Player hurt flash and blink | Runtime `hit_flash` material on the player sprite, solid mode with the contour kept (`keep_edges`, luma 0.08): white for 2 ticks, crimson at 60 % for 2, then the i-frame blink at 50 % every 2 game ticks. | `Player._impact_flash()`, `_process()` |
| Skeleton flinch | `hurt` plays only for a skeleton that was already walking; an interrupted wind-up keeps its `attack` animation, so the cooldown re-roll and AI timing are as before. | `Skeleton._on_hurt()` |
| Death tint | The screen mixes toward (0.16,0.02,0.06) at 40 % over 40 ticks on `Events.player_died`, under the label and fade. | `scripts/ui/death_tint.gd`, `scenes/main.tscn` |
| Pickups and props | Collecting a pickup or world item leaves a `pickup_sparkle`. Drops, world-item aura and glint, and candle flicker start at a random (pickups, world items; private RNG) or position-derived (candles) *tick* of their cycle, never a random frame. | `AnimPhase`, `pickup.gd`, `world_item.gd`, `candle.gd` |
| Save point | After a save made at the shrine it plays its `activate` light column. Its prompt is white (0.94,0.94,0.97) on the notice plate, re-centres when its text changes, and hides while the column plays (notices stay gold). | `save_point.gd`, `save_point.tscn` |
| Axe spin | The axe root spins at 14 rad/s as before, so its 14×14 hitbox rotates. `UprightSpinSprite` holds the sprite upright and shows the pre-rotated frame for the root's angle; the spin art stays within 9 px of the pivot. | `scripts/projectiles/upright_spin_sprite.gd`, `axe.tscn`, `items.py` |
| Menus | The selected row sits on a dark-crimson bar whose red pulses 64→96 over 64 ticks. Its text is white and the bar is the only cue (the shard cursor keeps its width, so rows never shift, and is drawn only where no bar exists). Every selection bar is 11 px tall with the row's capitals centred (2 px above, 2 below). The unfocused equipment column keeps a 45 % bar on the slot being changed. Windows open as empty frames growing from their centre line over 16 ticks, with contents appearing when open; input is live from the first frame and closing is instant. Item names, slot and stat labels, settings rows, counts and map room names are in mixed or title case; tabs, window headings, button hints and the dashed placeholders stay in caps. The death label uses the title font. | `selection_bar.gd`, `menu_fx.gd`, `pause_menu.gd`, `save_menu.gd`, `title_menu.gd`, `scenes/main.tscn` |
| Overlays | The quick-pause and CONTROLLER DISCONNECTED text sits centred on the notice plate in the HUD's notice gold, with the plate sized to the text (a style override, so the `Overlay/PauseLabel` path the smoke test reads is unchanged). The title screen's error line uses the same plate in theme white and is shown only while it has text, so no blank plate appears. | `scenes/main.tscn`, `title_menu.tscn`, `TitleMenu._show_message()` |
| Ambient life | `Room._ready()` adds `AmbientFx` under the Hall, Sky and Castle Parallax2D layers (z +1 inside each layer, so the motes draw at z −9). 5–7 additive 1-px motes per dado moon shaft rise 2–6 px/s along the shaft and blink. 15 sky points flare for 8 ticks every 40–90 ticks. A 7×4 bat silhouette crosses the far castle every 20–40 s. Mote zones come from `layers.json` Hall `"motes"` (written by `backgrounds.py mote_zones()`), with a built-in copy as fallback; an empty list turns them off. Private RNG, pauses with the tree, no gameplay effect. | `scripts/world/ambient_fx.gd`, `room.gd` |
| Randomness | Every cosmetic roll this pass added uses a private `RandomNumberGenerator`, and the skeleton's flinch never replaces `attack`, so the new effects never shift the gameplay rolls (drops, spawns, damage variance). The screen shake (`RoomCamera`) and SFX pitch jitter (`Audio`) predate the pass and still draw on the global RNG. | — |

## Art pass: generated assets

Decisions inside the generators, where `docs/art_style.md` left a number
open or the shipped art departs from it. All of it is regenerated by
`tools/`; change the generator, not the output.

| Question | Decision | Where |
|---|---|---|
| Hero colour budget | Body frames ≤ 27 colours, weapon frames ≤ 31, 31 across the sheet — more than one 16-colour palette, by design. Deterministic ramp-derived CLUT: near-blacks below luma 20 share, plus the designed merges in `hero_paint._clut_table` (cape CX4 = hair H3; the legs share the cape's night ramp and the hair ramp; weapon steel S1→CO3, S2→H4; the coat's 1-px specular is steel S4). Interior contact lines appear only between parts within 25 Y. | `hero_paint.py` |
| Hero contour and cloth | Hair, coat, trousers and boots outline in their darkest tone. Only the cape (CX2) and the face (K2) keep lit-edge sel-out, because a lit outline at Y 29–35 matched both the mid dado and the dark wall. The sheen CX5 appears only on fold crests and the 1-px back rim; the hem is one step up. Cloth clusters come from three passes on tone indices: `cloth_cleanup`, the post-rim islands sweep, then the post-polish `edge_sweep`. Locked speculars are kept. | `hero_paint.py`, `hero_figure.py` |
| Hero secondary motion | The idle ponytail is drawn with a one-frame lag behind the breath; the run ponytail gets a designed ±7° swing lagging the pelvis bob by 5 ticks; the ribbon tails are their own chains, behind the tail. Landing and the backdash brake spread their cape swing with segment-angle settle blends; a hurt pulls the cape toward a forward drape. The sword smear is comet-shaped with its head on the blade (92° sweep kept). | `hero.py`, `hero_rig.py`, `hero_figure.py` |
| Skeleton | 40–41 px tall (crown −40/−41, 2–3 px above the hurtbox top). Release frame 3 draws an open, empty hand ahead of the jaw where the bone spawns; walk bob 2 px with the skull dipping with the torso. A cool (132,136,170) rim replaces the warm (44,34,34) outline only on the exterior back contour of skull, neck, ribs and far leg, plus a 2-px (236,236,244) dome catch-light; everything else keeps the warm outline. 10 colours per frame. The sheet keeps an `idle` animation that nothing plays; its drawing is the source pose for `skeleton_parts`. | `enemies.py` |
| Thrown bone | An 8×4 core, 10×6 with its outline. The core sits inside the unchanged 9×9 rotating hitbox; the outlined length overhangs it by 0.5 px at each end. The old 12-px bone had 12 outline and knob pixels outside the hitbox, so it could graze the hero without a hit; a 10-px core would still leave 4 outline pixels outside it. | `enemies.py` (`BONE_TPL`, `BONE_AT`) |
| Bat | Fur on the shared `bat` ramp in tones 1–2, light (bone-lavender) finger struts and a cool 1-px (150,150,200) rim, not dark struts: dark struts put the bat at the walls' value and read murky. The far wing carries a dimmer (104,102,150) back-contour rim. Values sit deliberately between the dado (Y 48–60) and the ashlar (faces Y 20). At most 11 colours per frame. | `enemies.py` |
| Fire | Big fire (death flame, fire pops, candle break) is an opaque body (`*_body` rows on a `Body` child, shared `fire` ramp) under an additive hot core (+(150,100,36) on pale yellow, +(210,180,120) on white); the 2-tick ignition star stays additive only. Not plain additive flames, because under ADD the flame went cream-white on the walls. Caps: white ≤ 5–6 %, pale yellow ≤ 11 %, yellow-orange ≤ 20–22 %; the 2-tick young ball 14/20/30 %. Opaque fire hides what is behind it. | `fx.py`, `death_flame.tscn`, `fire_pop*.tscn`, `candle_break.tscn` |
| fire_pop | Its own sheet: 40×48, origin (20,32); `default` 8×2 ticks, `large` 12×2 ticks, each with same-length body rows on an opaque `Body` child and smoke on a 0.6 MIX child. Candle breaks are a fire ball over the candlestick, not a ground column. | `fx.py`, `scenes/fx/fire_pop*.tscn` |
| Smoke, dust, halo | Explosion smoke is discrete puff emitters: 5 puffs at 1.6/1.3/1.0/0.7/0.4 px/tick, ×0.88 per tick, 0.25 px/tick lift, fanned −34/+26/−12/+40/+6° (±5°) off a seeded heading, leading puffs ×0.72–1.0. Each puff is lit from the upper front with its own darker lower-back rim; a warm crescent only on young puffs' undersides; puffs under r 2.2 are not drawn. The last 3 frames erode 1 px per frame and drop 30/60/85 % of pixels in 2×2 cells, rims first. Drawn at 0.6 MIX. Emitters: death_flame f6–7, fire_pop f2, fire_pop_large f2 and f5. Dust has 3 light tones and billows upward. Candle-halo rings are 4/7/12/18 px. | `fx.py`, `props.py` |
| Save column | Pulse rings rise from the crystal at 3.2 px/tick at uneven gaps (29–38 px), on the core only, fading by 120 px; rising streak noise replaces the dither jitter; 12 one-pixel sparkles rise beside it. 190 px reach, dithered top, no cap. | `props.py` |
| Frame sizes | death_flame 40×88 (origin (20,87), offset (0,−44)); save_shrine 48×68 (origin (24,67), offset (0,−34)); save_shrine_glow 96×224 (crystal at (48,192), offset (−48,−192)). | `fx.py`, `props.py`, scenes |
| Heart pickups | The small and big heart stills are built in memory as the source of the glinting `pickup_heart_*` sheets and are no longer written to disk. | `items.py` |
| Onyx ring | The stone has its own `ONYX_STEP` template — a lit crown facet, a white specular upper left and a lavender rim lower right around a black centre — because a plain black stone read as a hole on the navy window. | `equipment.py` |
| HUD | The always-on HUD is SotN's compact top-left cluster: a 132×34 frame at (2,2) with the sub-weapon medallion, the HP number and gauge, hearts, the 46 px MP gauge and a small "LV n" in the 3×5 HUD digits. NEXT and gold appear in a top-right ledger plate (notice-plate style) that fades in for about 3 s only when one of them actually changes. Values are cached, so room loads and respawns that re-send the same numbers never show it. LV, NEXT and gold are always on the pause STATS tab. This deviates from SotN, which shows neither LV nor gold in play, because SPEC 5.1 requires the level and asks for gold when relevant. When the minimap arrives, the ledger moves under it (`Ledger.offset_top = 28`). Notices draw on a small window plate. | `ui.py`, `hud.tscn`, `hud.gd` |
| Level up | A level-up shows a title-font "LEVEL UP" word at top centre for 1.27 s: 4-tick fade, 8 px rise at 1 px per 2 ticks, flickering over the last 16 of 72 hold ticks. The "LEVEL n" notice is gone. There is no white screen flash (see *Known gaps*). | `hud.gd`, `hud.tscn` |
| Area banner | The banner grows and folds by resizing about its centre (140×20 to 232×44 over 15 ticks; folds to 20 px over 24) with 8/10 px nine-slice margins, so its border and hairlines never drop rows. The minimum height is 20 because the hairline diamonds sit inside the 10 px margins. | `hud.gd`, `hud.tscn` |
| Menu windows | Square, plain corners with no rivets; the area banner keeps its studs. Every window is baked at its on-screen size. `menu_frame.png` is still written as a spare generic nine-patch; no scene uses it. | `ui.py` |
| Title | The logo is baked into `title_backdrop.png`; the Title Label is hidden (not deleted; un-hiding it draws over the logo). The far spires stand between the option window and the crag, and a build-time assert keeps their finials at or below y 150. The bridge deck is at y 152 so its arcade shows. The 1-px moon rim is a seeded tick pattern, not a continuous line (`RIM_SEED` 13: 2–4 px on, 3–6 px gaps, gaps doubled more than 80 px from the moon). The crag lip takes the rim only where it faces the moon, within about 18° (`RIM_LIP_FACING` 0.95), and is lit stone elsewhere near it; the left towers stay unrimmed. | `ui.py`, `title_menu.tscn` |
| Foundation | The Crimson Hall foundation (the row below the walkable floor) is wine-black marble slabs, 16/32/48 px and hash-laid, not an ivory/wine checker, which read as a test pattern at 1x. The marble identity is carried by the ivory floor surface, the wine fascia and the column shafts. | `tiles.py`, `build_castle_hall.py` |
| Foreground plane | A `Foreground` Parallax2D (scroll 1.3/1.0, z 18: over actors, under sparks, damage numbers and the HUD) holds two unlit chain-hung lanterns plus balustrade and urn silhouettes rising from the bottom edge (tops at world y 266, screen y 194 at the ground camera). All are near-black with a 1-px (70,74,112) moon rim; the lanterns are 15 px wide with dark navy glass, and lantern B ends at y 64, above the portrait. Column fronts were rejected because a column at 1.3 always crossed a walkable ledge. | `tiles.py`, `build_castle_hall.py` |
| Back wall | The dado is a background-graded wine-rose marble (7 tones, hue ~317–338°, field Y 57, Y 49–75, 1-px glints to 97) with clouding, broken veins and carved bevels, rather than a dark wine-black wainscot or the earlier cool slate. The gilt chair rail sits above the hero's crown. Ashlar faces and hall pilaster shafts use their own `ASHLAR` ramp: faces (19,17,38) Y 20 and mortar or shadow (10,8,22) Y 10, which is STONE_BG 1/0 ×1.2 with the same indigo hue (`ASHLAR_MOON` under the moon shafts). The masonry is carried by 1-px lit lines (the (26,24,46) and (38,36,62) chamfers). Y 20 clears the hero's Y ~6 contour by 12+ on the jump and fall, and stays 9 under his lit cape edge (Y ~29). After the 64 px roll the bays are: rose at texel 128, open arch 256, lancet 384, portrait 500. The lancet is plate tracery (two leaded lights under a blind diamond-lattice head) with no quatrefoil, rather than full tracery, because the hanging lamp at (408,112) and the moon pass behind that bay. Moon shafts are baked as posterized parallelograms, one per window bay (3 of 4). The moon shows only through the open arch (fully at the ground camera, hidden at the top-row cameras). Set-pieces use background-graded ramps, and the back wall paints no light sources. | `backgrounds.py` |
| Clouds | Wisps are broken into 2–3 tapered segments; only the segment crossing the moon (lower third of the disc at the ground camera) keeps the moonlit rim. | `backgrounds.py` |
| Pier marble | Pier faces are wine3 with the wine4 sheen. Wine2, the hero's old contour value, appears only as single pixels or 1-px grooves. The core shadow is 6 px wide: a wine1 terminator, a 3-px (24,14,26) core band, a 1-px wine1 reflected light and the wine0 outline. The plinth incision stays wine0, not wine1, because wine1 (Y 21) is within 12 Y of the hero's lit edges. | `tiles.py` |
| Playfield vs back wall | The foundation is deliberately darker than the dado. Pier faces sit at the dado's value (wine3, Y ≈ 56) and separate from it by drawing (lit chamfer, dark core, incision), not by value. The pier shaft's 3-px core band is (24,14,26), Y 18, not wine0 (Y 11), so the hero's Y ~6 contour separates from it in the air. Outlines, torus cores and creases stay wine0, and the wine1 terminator and reflected light (Y 21) keep the core the darkest band. | `tiles.py` |
| Balcony layout | Visual only: the big candle moved to (40,96) and the Heart Max Up to (88,88), so the heart no longer sits in the candle's gold cup. Reach, drop landing and the `world_item_id` are unchanged. | `build_castle_hall.py` |
| Candle fixtures | A candle with no surface within 8 px below it hangs from a chain off the ledge corbel or arch above, so nothing is drawn below a candle's base and a grounded swing never visibly cuts a fixture it cannot break. A broken candle leaves a spent dish (pricket and wax), not an empty stand. | `build_castle_hall.py` (`_candle_support`), `tiles.py` |
| Timing record | The new sheets are timed in whole 60 Hz ticks; the hit windows are unchanged in ticks. **Weapons:** `active_frames` were re-indexed to the new sheets — sword (1,3)→(2,4), whip (2,3)→(3,5) — so the windows stay 3/9/3 ticks and 6/6/3 ticks (whip at ×0.72). **Throw:** frame 0 is 4 ticks (0.0667 s, was 3.75 = 0.0625 s); the whole throw is 11 ticks (0.183 s, was 11.25 ticks = 0.1875 s), 7 ticks after the release (was 7.5). The THROW state ends on `animation_finished`, so its lock-out is 0.25 tick shorter. **Skeleton:** the bone release moved from frame 2 to frame 3 and still fires at 15 ticks (0.250 s); the attack is 23 ticks (0.383 s, was 22.5 = 0.375 s). | `resources/weapons/*.tres`, `vesper_frames.tres`, `skeleton.gd`, `enemies.py` |
| Known gaps vs. the style guide | Visual only, not built: a stand-up-from-crouch transition (releasing Down snaps to idle), the area banner's slice dissolve, a HUD sub-weapon glint sweep, the save shrine's red tint with an HP and heart count-up, an equipment stat-change preview (blue gain, red loss), green heal numbers when a Vial is used, "+n" pickup text, a level-up white flash, and a menu close animation (closing is instant). The app icon (`icon.svg`) is still the original, and `project.godot` sets no boot splash, so launch shows Godot's default. | `docs/art_style.md` (*Not built yet*) |

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
