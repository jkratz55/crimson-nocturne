# Art style guide

The rules every generator in `tools/asset_pipeline/` follows. The look evokes
*Castlevania: Symphony of the Night* — gothic, low-key, ramp-shaded sprites
with eased, tick-timed animation — but every pixel is drawn by our own code
and every design is our own. Where the shipped art departs from these rules,
or a rule is not built yet, `ASSUMPTIONS.md` (*Art pass: generated assets*)
says so and why.

## Frames and resolution

- Internal resolution **384×216**, integer-scaled with nearest filtering.
  Tiles are **16×16**. The Crimson Hall is 768×288 (48×18 tiles).
- **Vesper:** 128×80 frames, body centred on column 64, lowest sole row 75
  (origin (64,75); `player.tscn` sprite offset (0,−36)). Constants live in
  `common.py` (`HERO_FRAME_W/H`, `HERO_CENTER_X`, `HERO_FOOT_Y`).
- **Skeleton:** 64×64, feet origin (32,59), offset (0,−28). **Bat:** 32×32,
  body centre (16,16) is the scene origin.
- Icons are 16×16 (the dagger, which doubles as its projectile sprite, is
  16×7). A new frame size changes the scene offset in the same edit;
  collision, hurtbox and hitbox shapes never move for art.

## Palette

- Every colour comes from the shared **`RAMPS`** registry in
  `tools/asset_pipeline/common.py`, plus `COLORS` for single accents. Module
  ramps (the hall's `HALL_RAMPS`, the items' `IR`, the hero's `HERO_RAMPS`)
  copy or derive from it, so the whole screen shares one palette. Ramps run
  **dark → light**, mostly 4–7 tones (a few accent and additive ramps, such
  as `eye`, `smoke` and `moonlight`, have 2–3); tone 0 doubles as the
  outline colour.
- Hue shifts along a ramp: shadows lean violet/indigo, lights lean warm on
  warm materials and cyan-lavender on cool ones. Saturation peaks in the
  mid-tones. Shadows are never neutral grey and never pure black; the
  darkest value on screen is `VOID` (6,4,12).
- "Y" in comments and docs is Rec. 601 luminance, 0–255 (`common.luma()`).
- New ramps come from `make_ramp()` (OKLCh, calibrated on the hand-picked
  ramps). **Background** versions come from `aerial()`: desaturate about
  35 %, darken about two ramp steps, lean 25 % toward the indigo fog
  (20,18,44).
- Accents — crimson, gold, fire, moonlight — stay a small share of any
  screen. Gold G5 and similar top tones are speculars only.

## Lighting

- **Sprites:** the key light is upper-front *relative to facing* (`LIGHT`);
  sprites are drawn facing right and flip in-engine, light and all.
- **Cool back rim:** a 1-px rim on the contour facing away from the light
  (`RIM`). The hero takes it on hair, back shoulder, cape back edge and back
  leg; the skeleton on the back of skull, neck, ribs and far leg; the bat on
  its far wing.
- **Architecture** is never flipped: `LIGHT_ENV` lights top/left edges.
- Shading quantises a lit normal field into the ramp: the flat recipe is
  0.75 × N·L + 0.25 ambient (`shade_normals()`), cut by `quantize_to_ramp()`
  (for example 0.15/0.35/0.55/0.75/0.90 for 6 tones). No flat top lighting
  and no pillow shading (darkening every edge alike).
- Every flame on screen is a real, breakable candle; the back wall paints
  no light sources. Moonlight enters as posterized shafts leaning down-left
  at about 65° (dx/dy 0.47), one per window bay.

## Outlines and clusters

- **Sel-out** (`selout()`): each exterior outline pixel takes the darkest
  tone of the material it touches; on edges facing the key light it takes
  tone 1 instead. Where a rim light sits, the rim replaces the outline.
- **No pure black interiors:** a sprite's darkest pixel is a material's own
  tone 0. Bone uses a warm dark outline (44,34,34), never violet-black.
- Interior lines only where two overlapping parts have similar values
  (within about 25 Y); never between folds of one material — use a value
  step instead.
- **Alpha is 0 or 255.** No anti-aliasing against transparency, no
  dithering inside sprites. Dithering belongs to backgrounds, halos and UI
  gradients.
- Manual anti-aliasing only inside the sprite, on long curves (hair clumps,
  cape hem, lining): one in-between tone at each stair-step.
- Clusters: 3×3 majority per material, no orphan pixels, no 1-px banding
  lines, clusters of 2–3 px or more. Speculars are deliberate 1-px jewels
  and are locked against cleanup.
- **Silhouette test:** fill every opaque pixel black on mid-grey at 1x
  (`preview.silhouette()`). Ponytail, capelet, coat tails and sabre must
  read, and each frame of an action needs its own silhouette.

## Value plan

The hero carries the widest value range on screen. His dark contour is about
Y 6 and his lit cape edge about Y 29, so every large surface behind him sits
**at least 12 Y above the contour** and, where it can, below the cape edge.

| Surface | Value | How it separates |
|---|---|---|
| Dado (the band behind the run line, up to the gilt chair rail 56 px above the floor) | Wine-rose marble, field Y 57 (49–75), hue ~330° | Mid value and a hue away from the hero's indigo; quiet: 1-px veins and bevels only, no crimson masses |
| Ashlar faces and pilaster shafts | `ASHLAR` (19,17,38) Y 20, mortar (10,8,22) Y 10 | Dark; masonry carried by 1-px lit chamfers |
| Pier shafts (playfield) | Faces wine 3 (Y ≈ 56) with a wine 4 sheen; 3-px core (24,14,26) Y 18 | The light verticals; parted from the dado by drawing (lit chamfer, dark core, incision), not by value |
| Floor | Ivory marble lips (top tone M4), wine-black foundation slabs below | The foundation is the darkest, quietest collision art |

- Collision tiles use the full `stone` and `marble` ramps; non-collision
  architecture on the playfield uses `stone_d`, so walkable shapes read
  brightest.
- The top and bottom of the room sink into a vignette toward `VOID`; the
  gold cornice frames the top. Depth: the further the plane, the darker,
  flatter and bluer, graded in the art (layer `modulate` stays white).

## Colour budgets

- **Vesper:** body frames ≤ 27 colours, weapon frames ≤ 31, 31 across the
  sheet, through a deterministic ramp-derived table (`hero_paint._clut_table`).
- **Enemies:** about 12–15 at most. The skeleton uses 10 per frame; the bat
  at most 11 per frame and 12 across its sheet.

## Vesper

Vesper is an original dhampir swordsman. He shares the genre's elegance, not
any existing character's costume.

- About 48 px sole to crown, roughly 7 heads, legs about half his height.
  Rig landmarks up from the sole: ankle 3, knee 12.5, crotch 22.5, waist 27,
  chest 32, shoulder 36.5, chin 38.5, skull crown 45.5 (hair adds volume).
  He stands in 3/4 contrapposto, never strict profile.
- Blue-black hair swept back into a low ponytail with a crimson ribbon; an
  indigo hussar-style frock coat with gold frogging and split tails; a short
  capelet over a mid-calf cape whose crimson lining flashes as the cloth
  turns; charcoal-violet trousers and knee boots (one shared ramp); dark
  gloves.
- The pale face is the bright focal point, with a red eye glint (255,64,72).
- Weapons: a slim curved sabre with a gold cup hilt; the Crimson Lash is
  braided leather with a crimson glint on every third bead and a steel tip.

## Animation

All timing is authored in **60 Hz ticks**. `SheetBuilder` writes
`speed = 60` and each frame's `duration` in ticks; frame time is
`duration / (60 × speed_scale)` (the whip plays at ×0.72).

- Holds are eased: 1–2 ticks for smears and snaps, 3–4 for locomotion, 5–8
  for idles and settles, long holds on extremes and contacts.
- Every state change gets a short transition (`land`, `run_start`, `skid`,
  `turn`, `apex`, `double_jump`), chosen by a visual selector on top of
  `Player.State` — never a new state.
- Pixel discipline: limbs move in whole pixels, the torso bobs 1 px on
  contacts, the head stays steady in idles, and a planted foot moves back
  `speed × ticks / 60` px per frame so it never skates.
- Secondary motion: the cape lags the torso; the idle ponytail sways 1 px
  one drawing behind the breath; ribbon tails lag further; a hurt throws the
  cape forward. The followers are verlet chains baked offline, one step per
  60 Hz tick (`hero_rig.CHAINS`, `hero_rig.Chain.step()`): gravity
  0.16–0.25 px/tick², damping 0.78–0.86, air drag −world velocity ×
  0.05–0.14, and a weak pull toward a designed drape.

| Vesper | Frames | Ticks | | Others | Frames | Ticks |
|---|---|---|---|---|---|---|
| idle (loop) | 6 | 7 each = 42 | | skeleton walk (loop) | 6 | 6,4,4,6,5,5 = 30 |
| run (loop) | 16 | 3,2 alternating = 40 | | skeleton attack | 6 | 4,5,6,2,3,3 = 23 |
| run_start | 4 | 3 each | | skeleton hurt | 2 | 3,24 |
| skid | 6 | 4 each | | bat fly (loop) | 13 | 4,1,1,1,1,1,4,2,2,2,1,2,2 = 24 |
| turn | 3 | 2 each | | bat hang (loop) | 4 | 24,10,24,10 |
| jump (holds last) | 5 | 3,3,4,4,6 | | bat unfurl | 3 | 4,3,4 |
| apex | 4 | 4 each | | candle burn (loop) | 8 | 8,6,8,6,3,7,6,5 |
| fall (loop) | 4 | 5 each | | gold coin spin | 6 | 4 each |
| land | 3 | 3,4,5 | | world-item aura | 8 | 8 each = 64 |
| double_jump | 6 | 3 each | | heart pickup glint | 4 | 40,2,3,3 |
| crouch (holds last) | 4 | 1,1,2,30 | | shrine idle | 8 | 8 each |
| attack, _crouch, _air | 7 | 2,1,2,3,4,2,1 = 15 | | | | |
| attack_whip, _crouch, _air | 8 | 2,2,2,2,2,2,2,1 = 15 | | | | |
| throw | 4 | 4,3,2,2 = 11 | | | | |
| backdash | 5 | 2,4,4,4,4 | | | | |
| hurt | 3 | 2,4,8 | | | | |
| death | 10 | 6,6,7,7,18,5,5,6,8,16 | | | | |

**Attack windows** (gameplay; they must not drift):

| Action | Frames | Ticks |
|---|---|---|
| Sword | `active_frames` (2,4) | startup 3, active 9, recovery 3 |
| Whip | `active_frames` (3,5) | startup 6, active 6, recovery 3 (before ×0.72) |
| Throw | spawns on frame 1 | 4 before, 7 after |
| Skeleton bone | releases on frame 3 | 15 before, 23 in all |

These numbers are coupled to the generators: `WeaponData.active_frames`,
the throw spawn frame in `player.gd` and `Skeleton.THROW_RELEASE_FRAME`
(= `ATTACK_RELEASE_FRAME` in `enemies.py`) index into the generated sheets.
`hero.py` writes the windows to `attack_windows` in `vesper.json`. Change a
frame count or a tick list and you must update them in the same edit.

Small loops: item glints are a 1-px star that grows, flares and fades over
3 frames about every 48 ticks; spinning pickups use 4–6 frames of 4 ticks;
relic auras pulse over 64 ticks. Pickups, world items and candles start
their loops at a random or position-derived *tick* of the cycle
(`AnimPhase`), never a random frame.

## Effects and blending

- **Add** for light: hit sparks, embers, the hot core and ignition star of
  fire, candle halos, the shrine glow and light column, world-item aura and
  glint, pickup sparkles, the double-jump ring, moon-shaft motes. Paint
  additive art dim; one step of ADD already reads as light.
- **Mix** for matter: smoke (0.6 opacity), dust (0.55), the death-mist body
  (0.8, with additive embers), debris scraps and bone pieces.
- Big fire is an opaque body under an additive core, so it never washes
  cream-white over the walls; white and pale yellow stay a small share.
- Afterimages are half-blended ghosts that darken, shift blue and flicker on
  alternate ticks. The hit flash is white, then crimson (196,62,66) at 60 %,
  2 + 2 ticks, with outlines kept.
- Effects run on game-time ticks (hit-stop freezes them), never change
  gameplay, and roll their randomness on a private `RandomNumberGenerator`.

## Environment

| Plane | Scroll | z | Content |
|---|---|---|---|
| Sky | 0.03, 0.05 | −30 | Dithered gradient, stars, the moon |
| Clouds | 0.06, 0.08 | −28 | Drifting wisps (autoscroll −4 px/s), moonlit rims |
| Castle | 0.15, 0.20 | −24 | Distant skyline with lit windows |
| Arcade | 0.40, 0.60 | −18 | Moonlit cloister, near-silhouette |
| Hall | 0.70, 1.0 | −10 | Back wall: ashlar, rose, arch, lancet, portrait, dado |
| Foreground | 1.3, 1.0 | 18 | Near-black lanterns, balustrade and urn tops with a 1-px moon rim; under sparks, numbers and the HUD |

The playfield (tiles, props, actors) is the 1.0 plane between Hall and
Foreground. Ornament is built as large set-pieces sliced into 16×16 cells;
masonry is a height field lit by `LIGHT_ENV`. `backgrounds.py` writes
`layers.json`, and the room builder turns each entry into a `Parallax2D`.

## UI windows

- Translucent navy windows: a 5-band vertical gradient (`RAMPS["ui_window"]`)
  with 4×4 Bayer dither between bands at alpha 232 (the title window 236),
  a thin silver border lit top/left and shaded bottom/right, a 1-px dark
  seat inside and a dark outer line. Corners are square and plain; only the
  area banner keeps studs.
- Windows are baked at their exact on-screen size (`ui.WINDOWS` must match
  the NinePatchRect rects), so the dither never stretches.
- The selected row sits on an 11 px dark-crimson bar whose red pulses
  64 → 96 over 64 ticks; its text is white and the bar is the only cue.
- Body text is `nocturne_pixel` in mixed case; tabs, headings and button
  hints are capitals; headings are gold (232,196,110). Big words (area
  names, LEVEL UP, the death line) use `nocturne_title`. A label's font size
  must equal the font's size for 1:1 pixels.
- Windows unfold from their centre line over 16 ticks and close instantly.
  Notices sit on the small notice plate in gold; prompts are white. The HUD
  is a compact top-left cluster (132×34 at (2,2)); NEXT and gold appear in a
  top-right ledger only when they change.

## Not built yet

Planned under these rules but missing today (tracked in `ASSUMPTIONS.md`):
a stand-up-from-crouch transition, the area banner's slice dissolve, a HUD
sub-weapon glint, the save shrine's red tint and HP count-up, an equipment
stat-change preview, heal numbers, "+n" pickup text, a level-up screen flash
and a menu close animation.

## Do not

- Do not add ripped, traced, downloaded or recreated-from-memory assets from
  any commercial game. Every pixel is drawn by code in `tools/`.
- Do not copy *Symphony of the Night* — evoke it. **Vesper is not Alucard:**
  no waist-length silver mane, no long black coat with a white cravat and a
  floor-length cape, no shield, no straight cruciform sword, no wolf, bat or
  mist forms.
- Do not add third-party packs, fonts, addons or pip dependencies (beyond
  pillow, numpy, scipy) without asking, or hand-edit a generated output.
- Do not use pure black, partial alpha, edge anti-aliasing or dithering
  inside a sprite, nor flat top lighting, pillow shading or grey shadows.
- Do not paint light sources on the back wall, or let visuals change
  gameplay: no new `Player` states for flourishes, no hitbox or timing
  drift, no cosmetic rolls on the global RNG.
