## Ambient life on a room's backdrop (visual only), the SotN habit of never
## leaving a hall as a still painting: 1-px dust motes drifting and blinking
## in the moon shafts on the back wall, a few stars twinkling in the sky, and
## now and then a small bat silhouette crossing the far castle.
##
## [method populate] adds one AmbientFx per effect under the room's
## Parallax2D layers named "Hall", "Sky" and "Castle", so each one draws in
## its layer's texel space and scrolls, repeats and z-sorts with that layer
## (one step above its texture, under everything nearer). Missing layers are
## skipped. Where the motes and stars go comes from the background manifest
## the generator writes ([constant MANIFEST_PATH]): an optional "motes" list
## of shaft zones on the Hall entry and an optional "twinkle" list of star
## texels on the Sky entry. Without them the built-in tables below are used.
##
## Nothing here touches gameplay: no collision, no groups, its own random
## generator (never the global one), and it pauses with the tree.
class_name AmbientFx
extends Node2D

enum Kind { MOTES, STARS, BAT }

const MANIFEST_PATH: String = "res://assets/backgrounds/layers.json"
## Mote zones in Hall texels, five floats each: x0, x1, y0, y1, slope. At row
## y (y0 <= y < y1) a zone spans x0 - (y - y0) * slope .. x1 - (y - y0) * slope,
## the parallelogram of a moon shaft falling down-left. The fallback is the
## hall's three dado shafts as backgrounds.py paints them (DADO_SHAFTS plus
## its HALL_ROLL of 64, SHAFT_SLOPE 0.47): under the rose and the open arch
## from the chair rail (row 200), under the lancet from its sill (row 190),
## all down to the floor line (row 256).
const FALLBACK_ZONES: PackedFloat32Array = [
	110.0, 120.0, 200.0, 256.0, 0.47,
	250.0, 264.0, 200.0, 256.0, 0.47,
	377.7, 389.7, 190.0, 256.0, 0.47,
]
const ZONE_STRIDE: int = 5
## Twinkle points in Sky texels: eleven stars painted into sky.png and four
## bare points where a faint star blinks into sight, all picked from the sky
## the hall's openings show at the most camera positions (sky.png is seeded,
## so they stay put) and none in the moon's halo, which the generator keeps
## starless.
const FALLBACK_STARS: PackedVector2Array = [
	Vector2(156, 75), Vector2(92, 65), Vector2(40, 65), Vector2(302, 70),
	Vector2(107, 53), Vector2(206, 65), Vector2(47, 50), Vector2(117, 46),
	Vector2(152, 46), Vector2(187, 65), Vector2(351, 30), Vector2(135, 79),
	Vector2(81, 76), Vector2(300, 85), Vector2(372, 66),
]
## Catch-up limit after a long frame, in 60 Hz ticks.
const MAX_STEPS_PER_FRAME: int = 4

# --- motes -------------------------------------------------------------------
## One mote per this many square texels of shaft, within the caps below: the
## hall's 10-14 px shafts get 5-7 each, a few specks in the light rather
## than glitter.
const MOTE_AREA_PER_MOTE: float = 120.0
const MOTE_MIN_PER_ZONE: int = 4
const MOTE_MAX_PER_ZONE: int = 14
const MOTE_MAX: int = 40
## Additive tones: the moonlight ramp's full shaft step and its mote tone.
const MOTE_DIM: Color = Color(40.0 / 255.0, 48.0 / 255.0, 80.0 / 255.0)
const MOTE_BRIGHT: Color = Color(110.0 / 255.0, 130.0 / 255.0, 200.0 / 255.0)
## Drift speed range, px/s, and lifetime and blink period ranges, in ticks.
## Motes rise along their shaft (it leans down-left, so up the shaft is up
## and to the right), give or take [constant MOTE_SPREAD] radians, so most of
## them cross the light lengthwise and wink out where they leave it.
const MOTE_SPEED: Vector2 = Vector2(2.0, 6.0)
const MOTE_SPREAD: float = 0.5
const MOTE_LIFE: Vector2i = Vector2i(150, 330)
const MOTE_PERIOD: Vector2i = Vector2i(20, 60)

# --- stars -------------------------------------------------------------------
## A twinkle every 40-90 ticks, 8 ticks long: a cross flares round the star
## for 2 ticks, holds a short cross for 2 more, then fades out from the arms in.
const STAR_PERIOD: Vector2i = Vector2i(40, 90)
const STAR_TWINKLE_TICKS: int = 8
const STAR_CORE: Color = Color(90.0 / 255.0, 90.0 / 255.0, 110.0 / 255.0)
const STAR_ARM: Color = Color(50.0 / 255.0, 52.0 / 255.0, 76.0 / 255.0)
const STAR_ARM_FAINT: Color = Color(24.0 / 255.0, 26.0 / 255.0, 40.0 / 255.0)
const ARMS_NEAR: PackedVector2Array = [Vector2(1, 0), Vector2(-1, 0), Vector2(0, 1), Vector2(0, -1)]
const ARMS_FAR: PackedVector2Array = [Vector2(2, 0), Vector2(-2, 0), Vector2(0, 2), Vector2(0, -2)]

# --- bat ---------------------------------------------------------------------
## STONE_BG 1: only reads against the moon, its halo and the cloud rims.
const BAT_COLOR: Color = Color(16.0 / 255.0, 14.0 / 255.0, 32.0 / 255.0)
## 7x4 frames, pixel offsets from the top-left: wings raised in a V, then down.
const BAT_UP: PackedVector2Array = [
	Vector2(0, 0), Vector2(6, 0),
	Vector2(1, 1), Vector2(2, 1), Vector2(4, 1), Vector2(5, 1),
	Vector2(2, 2), Vector2(3, 2), Vector2(4, 2),
	Vector2(3, 3),
]
const BAT_DOWN: PackedVector2Array = [
	Vector2(2, 0), Vector2(3, 0), Vector2(4, 0),
	Vector2(0, 1), Vector2(1, 1), Vector2(2, 1), Vector2(3, 1), Vector2(4, 1), Vector2(5, 1), Vector2(6, 1),
	Vector2(0, 2), Vector2(3, 2), Vector2(6, 2),
]
const BAT_FLAP_TICKS: int = 5
## Seconds between crossings, the first wait, and flight speed in texels/s.
const BAT_INTERVAL: Vector2 = Vector2(20.0, 40.0)
const BAT_FIRST_WAIT: Vector2 = Vector2(6.0, 14.0)
const BAT_SPEED: Vector2 = Vector2(26.0, 36.0)
## Castle-texel rows the flight path bobs around: at every camera height this
## band crosses the moon disc on screen.
const BAT_ROWS: Vector2 = Vector2(46.0, 54.0)

var kind: Kind = Kind.MOTES
var zones: PackedFloat32Array = PackedFloat32Array()
var stars: PackedVector2Array = PackedVector2Array()

var _rng: RandomNumberGenerator = RandomNumberGenerator.new()
var _tick: int = 0
var _tick_accum: float = 0.0

# motes
var _pos: PackedVector2Array = PackedVector2Array()
var _vel: PackedVector2Array = PackedVector2Array()
var _zone_of: PackedInt32Array = PackedInt32Array()
var _age: PackedInt32Array = PackedInt32Array()
var _life: PackedInt32Array = PackedInt32Array()
var _period: PackedInt32Array = PackedInt32Array()
var _offset: PackedInt32Array = PackedInt32Array()
var _wander: PackedFloat32Array = PackedFloat32Array()

# stars
var _star_start: PackedInt32Array = PackedInt32Array()

# bat
var _bat_active: bool = false
var _bat_next: int = 0
var _bat_ticks: int = 0
var _bat_pos: Vector2 = Vector2.ZERO
var _bat_dir: float = 1.0
var _bat_speed: float = 30.0
var _bat_row: float = 50.0
var _bat_span: Vector2 = Vector2(-12.0, 492.0)


## Add the ambient effects to [param room]'s backdrop layers.
static func populate(room: Node) -> void:
	var manifest: Dictionary = _read_manifest()
	var hall := room.get_node_or_null(^"Hall") as Parallax2D
	if hall != null:
		var hall_entry: Dictionary = manifest.get("Hall", {})
		var mote_zones: PackedFloat32Array = _zones_from(hall_entry)
		if not mote_zones.is_empty():
			hall.add_child(_make(Kind.MOTES, &"AmbientMotes", mote_zones, PackedVector2Array()))
	var sky := room.get_node_or_null(^"Sky") as Parallax2D
	if sky != null:
		var sky_entry: Dictionary = manifest.get("Sky", {})
		var star_texels: PackedVector2Array = _stars_from(sky_entry)
		if not star_texels.is_empty():
			sky.add_child(_make(Kind.STARS, &"AmbientStars", PackedFloat32Array(), star_texels))
	var castle := room.get_node_or_null(^"Castle") as Parallax2D
	if castle != null:
		castle.add_child(_make(Kind.BAT, &"AmbientBat", PackedFloat32Array(), PackedVector2Array()))


static func _make(fx_kind: Kind, fx_name: StringName, fx_zones: PackedFloat32Array,
		fx_stars: PackedVector2Array) -> AmbientFx:
	var fx := AmbientFx.new()
	fx.name = fx_name
	fx.kind = fx_kind
	fx.zones = fx_zones
	fx.stars = fx_stars
	# One step above the layer's own texture, still under every nearer layer.
	fx.z_index = 1
	if fx_kind != Kind.BAT:
		var additive := CanvasItemMaterial.new()
		additive.blend_mode = CanvasItemMaterial.BLEND_MODE_ADD
		fx.material = additive
	return fx


## The manifest's layer entries keyed by name, or {} when it is unreadable.
static func _read_manifest() -> Dictionary:
	var by_name: Dictionary = {}
	if not FileAccess.file_exists(MANIFEST_PATH):
		return by_name
	var file := FileAccess.open(MANIFEST_PATH, FileAccess.READ)
	if file == null:
		return by_name
	var json := JSON.new()
	var ok: bool = json.parse(file.get_as_text()) == OK
	file.close()
	if not ok or json.data is not Dictionary:
		return by_name
	var doc: Dictionary = json.data
	var raw_layers: Variant = doc.get("layers", [])
	if raw_layers is not Array:
		return by_name
	var layers: Array = raw_layers
	for raw_entry: Variant in layers:
		if raw_entry is not Dictionary:
			continue
		var entry: Dictionary = raw_entry
		var layer_name: Variant = entry.get("name", "")
		if layer_name is String:
			by_name[layer_name] = entry
	return by_name


## Mote zones from a Hall entry: its "motes" list when it has one (an empty
## list turns the motes off), the built-in shafts otherwise.
static func _zones_from(entry: Dictionary) -> PackedFloat32Array:
	var raw: Variant = entry.get("motes")
	if raw is not Array:
		return FALLBACK_ZONES
	var list: Array = raw
	var out := PackedFloat32Array()
	for raw_zone: Variant in list:
		if raw_zone is not Dictionary:
			continue
		var zone: Dictionary = raw_zone
		var values := PackedFloat32Array()
		for key: String in ["x0", "x1", "y0", "y1", "slope"]:
			var value: Variant = zone.get(key)
			if value is not float and value is not int:
				break
			# JSON numbers arrive as float; a typed assignment also takes an int.
			var number: float = value
			values.append(number)
		if values.size() == ZONE_STRIDE and values[1] >= values[0] + 6.0 and values[3] >= values[2] + 8.0:
			out.append_array(values)
	return out


## Twinkle points from a Sky entry's "twinkle" list of [x, y] texels (an
## empty list turns the twinkles off), the built-in points otherwise.
static func _stars_from(entry: Dictionary) -> PackedVector2Array:
	var raw: Variant = entry.get("twinkle")
	if raw is not Array:
		return FALLBACK_STARS
	var list: Array = raw
	var out := PackedVector2Array()
	for raw_star: Variant in list:
		if raw_star is not Array:
			continue
		var star: Array = raw_star
		if star.size() >= 2 and (star[0] is float or star[0] is int) and (star[1] is float or star[1] is int):
			var x: float = star[0]
			var y: float = star[1]
			out.append(Vector2(x, y))
	return out


func _ready() -> void:
	_rng.randomize()
	match kind:
		Kind.MOTES:
			_setup_motes()
		Kind.STARS:
			for _i: int in stars.size():
				# Spread the first twinkles over a whole period.
				_star_start.append(_rng.randi_range(0, STAR_PERIOD.y))
		Kind.BAT:
			var layer := get_parent() as Parallax2D
			var width: float = layer.repeat_size.x if layer != null and layer.repeat_size.x > 0.0 else 480.0
			_bat_span = Vector2(-12.0, width + 12.0)
			_bat_next = roundi(_rng.randf_range(BAT_FIRST_WAIT.x, BAT_FIRST_WAIT.y) * 60.0)


func _process(delta: float) -> void:
	_tick_accum += delta * 60.0
	var whole: int = int(_tick_accum)
	if whole <= 0:
		return
	_tick_accum -= float(whole)
	for _i: int in mini(whole, MAX_STEPS_PER_FRAME):
		_tick += 1
		match kind:
			Kind.MOTES:
				_step_motes()
			Kind.STARS:
				_step_stars()
			Kind.BAT:
				_step_bat()
	queue_redraw()


func _draw() -> void:
	match kind:
		Kind.MOTES:
			_draw_motes()
		Kind.STARS:
			_draw_stars()
		Kind.BAT:
			_draw_bat()


# ---------------------------------------------------------------------------
# Motes
# ---------------------------------------------------------------------------
func _setup_motes() -> void:
	var zone_count: int = floori(float(zones.size()) / float(ZONE_STRIDE))
	# Every shaft keeps its own share of motes for good, so no shaft is ever
	# left empty while another fills up.
	for z: int in zone_count:
		var area: float = (zones[z * ZONE_STRIDE + 1] - zones[z * ZONE_STRIDE]) \
			* (zones[z * ZONE_STRIDE + 3] - zones[z * ZONE_STRIDE + 2])
		var share: int = clampi(roundi(area / MOTE_AREA_PER_MOTE), MOTE_MIN_PER_ZONE, MOTE_MAX_PER_ZONE)
		for _k: int in mini(share, MOTE_MAX - _pos.size()):
			var i: int = _pos.size()
			_pos.append(Vector2.ZERO)
			_vel.append(Vector2.ZERO)
			_zone_of.append(z)
			_age.append(0)
			_life.append(1)
			_period.append(MOTE_PERIOD.x)
			_offset.append(0)
			_wander.append(0.0)
			_respawn_mote(i)
			# Start part-way through a life so they never all appear together.
			_age[i] = _rng.randi_range(0, _life[i] - 1)


## A fresh life for mote [param i] somewhere inside its own shaft.
func _respawn_mote(i: int) -> void:
	var base: int = _zone_of[i] * ZONE_STRIDE
	var y0: float = zones[base + 2]
	var y: float = _rng.randf_range(y0 + 2.0, zones[base + 3] - 4.0)
	var shift: float = (y - y0) * zones[base + 4]
	var x: float = _rng.randf_range(zones[base] + 2.0, zones[base + 1] - 3.0) - shift
	_pos[i] = Vector2(x, y)
	# Up the shaft, give or take a little to either side, 2-6 px/s.
	var axis: Vector2 = Vector2(zones[base + 4], -1.0).normalized()
	_vel[i] = axis.rotated(_rng.randf_range(-MOTE_SPREAD, MOTE_SPREAD)) \
		* _rng.randf_range(MOTE_SPEED.x, MOTE_SPEED.y)
	_age[i] = 0
	_life[i] = _rng.randi_range(MOTE_LIFE.x, MOTE_LIFE.y)
	_period[i] = _rng.randi_range(MOTE_PERIOD.x, MOTE_PERIOD.y)
	_offset[i] = _rng.randi_range(0, _period[i] - 1)
	_wander[i] = _rng.randf() * TAU


func _step_motes() -> void:
	for i: int in _pos.size():
		_age[i] += 1
		var v: Vector2 = _vel[i]
		# A lazy side-to-side wander on top of the drift.
		var sway: float = sin(float(_tick) * 0.05 + _wander[i]) * 1.5
		var p: Vector2 = _pos[i] + Vector2(v.x + sway, v.y) / 60.0
		_pos[i] = p
		if _age[i] >= _life[i] or not _in_zone(_zone_of[i], p):
			_respawn_mote(i)


func _in_zone(z: int, p: Vector2) -> bool:
	var base: int = z * ZONE_STRIDE
	var y0: float = zones[base + 2]
	if p.y < y0 + 1.0 or p.y >= zones[base + 3] - 3.0:
		return false
	var shift: float = (p.y - y0) * zones[base + 4]
	return p.x >= zones[base] - shift + 1.0 and p.x <= zones[base + 1] - shift - 2.0


## 0 = hidden, 1 = dim, 2 = bright. Each mote flares bright at the top of its
## blink period and winks out briefly half-way through it, and stays dim for
## the first and last few ticks of its life.
func _mote_level(i: int) -> int:
	var period: int = _period[i]
	var u: float = float((_age[i] + _offset[i]) % period) / float(period)
	var level: int = 1
	if u < 0.15:
		level = 2
	elif u >= 0.55 and u < 0.65:
		level = 0
	if _age[i] < 10 or _life[i] - _age[i] < 10:
		level = mini(level, 1)
	return level


func _draw_motes() -> void:
	for i: int in _pos.size():
		var level: int = _mote_level(i)
		if level == 0:
			continue
		draw_rect(Rect2(_pos[i].round(), Vector2.ONE), MOTE_BRIGHT if level == 2 else MOTE_DIM)


# ---------------------------------------------------------------------------
# Stars
# ---------------------------------------------------------------------------
## Book each star's next twinkle once the last one has played out.
func _step_stars() -> void:
	for i: int in stars.size():
		if _tick - _star_start[i] >= STAR_TWINKLE_TICKS:
			_star_start[i] = _tick + _rng.randi_range(STAR_PERIOD.x, STAR_PERIOD.y)


func _draw_stars() -> void:
	for i: int in stars.size():
		var t: int = _tick - _star_start[i]
		if t < 0 or t >= STAR_TWINKLE_TICKS:
			continue
		var at: Vector2 = stars[i].round()
		# Flare, hold, fade. The centre stays lit the whole way through, so a
		# bare point blinks in and out as a star instead of a hollow cross.
		var core: Color = STAR_CORE if t < 4 else (STAR_ARM if t < 6 else STAR_ARM_FAINT)
		draw_rect(Rect2(at, Vector2.ONE), core)
		if t < 6:
			var arm_tone: Color = STAR_ARM if t < 4 else STAR_ARM_FAINT
			for arm: Vector2 in ARMS_NEAR:
				draw_rect(Rect2(at + arm, Vector2.ONE), arm_tone)
		if t < 2:
			for arm: Vector2 in ARMS_FAR:
				draw_rect(Rect2(at + arm, Vector2.ONE), STAR_ARM_FAINT)


# ---------------------------------------------------------------------------
# Bat
# ---------------------------------------------------------------------------
func _step_bat() -> void:
	if not _bat_active:
		if _tick >= _bat_next:
			_launch_bat()
		return
	_bat_ticks += 1
	_bat_pos.x += _bat_dir * _bat_speed / 60.0
	_bat_pos.y = _bat_row + sin(float(_bat_ticks) * 0.07) * 3.0
	if (_bat_dir > 0.0 and _bat_pos.x > _bat_span.y) or (_bat_dir < 0.0 and _bat_pos.x < _bat_span.x):
		_bat_active = false
		_bat_next = _tick + roundi(_rng.randf_range(BAT_INTERVAL.x, BAT_INTERVAL.y) * 60.0)


func _launch_bat() -> void:
	_bat_active = true
	_bat_ticks = 0
	_bat_dir = 1.0 if _rng.randf() < 0.5 else -1.0
	_bat_speed = _rng.randf_range(BAT_SPEED.x, BAT_SPEED.y)
	_bat_row = _rng.randf_range(BAT_ROWS.x, BAT_ROWS.y)
	_bat_pos = Vector2(_bat_span.x if _bat_dir > 0.0 else _bat_span.y, _bat_row)


func _draw_bat() -> void:
	if not _bat_active:
		return
	var frame: PackedVector2Array = BAT_UP if floori(float(_bat_ticks) / float(BAT_FLAP_TICKS)) % 2 == 0 else BAT_DOWN
	var origin: Vector2 = _bat_pos.round() - Vector2(3.0, 2.0)
	for px: Vector2 in frame:
		draw_rect(Rect2(origin + px, Vector2.ONE), BAT_COLOR)
