## A few small fragments that burst out, flutter down and wink out: the torn
## wing bits of a bat, chips of anything small. Drawn as plain pixel rects in
## [method _draw] (positions rounded to whole pixels) so they stay crisp.
##
## With [member shaped] on, each fragment is a torn membrane scrap instead of
## a dot: three 1-px rows 5, 3 and 1 px wide, half of them with a light strut
## row along the top and, when [member edge_color] is set, a light hem down the
## straight side the rows hang from, whose rows flip from left- to
## right-aligned every [member flutter_ticks] ticks so the scrap flutters as it
## falls. A few
## optional 1x1 [member spark_colors] embers can burst out with them and die
## within [member spark_life].
##
## Visual only, self-freeing. Uses its own random generator so spawning one
## never shifts the gameplay RNG sequence.
class_name DebrisBits
extends Node2D

## Small torn scraps, in px (the unshaped look).
const SCRAP_SIZES: Array[Vector2] = [Vector2(2.0, 1.0), Vector2(2.0, 2.0), Vector2(3.0, 2.0)]
## Row widths of a shaped membrane scrap, top to bottom.
const MEMBRANE_ROWS: PackedInt32Array = [5, 3, 1]
const MEMBRANE_WIDTH: int = 5

enum Kind { RECT, SCRAP, SPARK }

## Palette the bits are picked from.
@export var colors: PackedColorArray = PackedColorArray([Color(0.33, 0.19, 0.36)])
@export_range(1, 32) var count: int = 8
## Seconds before the last bit is gone.
@export var life: float = 0.8
## Each bit lives between life * (1 - life_spread) and life.
@export_range(0.0, 1.0) var life_spread: float = 0.45
## Initial burst speed range, px/s.
@export var burst_speed: Vector2 = Vector2(30.0, 75.0)
## px/s^2 pulling the bits down, and the terminal speed they flutter at.
@export var gravity: float = 260.0
@export var max_fall_speed: float = 34.0
## Side-to-side flutter, px/s.
@export var flutter: float = 14.0

@export_group("Shaped scraps")
## Draw torn membrane scraps instead of plain rects.
@export var shaped: bool = false
## The strut (finger bone) row drawn along the top of every other scrap.
@export var strut_color: Color = Color8(170, 146, 176)
## A 1 px hem down the straight side of every scrap (the bone the membrane
## tore from), so the scraps read on backgrounds close to their own hue.
## Fully transparent draws no hem.
@export var edge_color: Color = Color(0.0, 0.0, 0.0, 0.0)
## Ticks (60 Hz) between the scraps' left/right flips.
@export_range(1, 30) var flutter_ticks: int = 6

@export_group("Sparks")
## Ember tones for the 1x1 sparks; none are spawned while this is empty.
@export var spark_colors: PackedColorArray = PackedColorArray()
@export_range(0, 16) var spark_count: int = 0
## No spark outlives this many seconds.
@export var spark_life: float = 0.3

var _pos: PackedVector2Array = PackedVector2Array()
var _vel: PackedVector2Array = PackedVector2Array()
var _size: PackedVector2Array = PackedVector2Array()
var _color: PackedColorArray = PackedColorArray()
var _phase: PackedFloat32Array = PackedFloat32Array()
var _death: PackedFloat32Array = PackedFloat32Array()
var _kind: PackedInt32Array = PackedInt32Array()
## Per-bit tick offset of the flutter flip, so the scraps never flip in unison.
var _flip_offset: PackedInt32Array = PackedInt32Array()
var _strut: PackedByteArray = PackedByteArray()
var _age: float = 0.0
var _rng: RandomNumberGenerator = RandomNumberGenerator.new()


func _ready() -> void:
	_rng.randomize()
	for i: int in count:
		var color: Color = colors[_rng.randi() % colors.size()] if not colors.is_empty() else Color.WHITE
		_add_bit(Kind.SCRAP if shaped else Kind.RECT, color, 1.0,
			life * _rng.randf_range(1.0 - life_spread, 1.0))
		_strut.append(1 if shaped and i % 2 == 0 else 0)
	if not spark_colors.is_empty():
		for _i: int in spark_count:
			# Embers fly a little faster than the scraps and burn out early.
			_add_bit(Kind.SPARK, spark_colors[_rng.randi() % spark_colors.size()], 1.2,
				minf(spark_life, life) * _rng.randf_range(0.6, 1.0))
			_strut.append(0)


func _add_bit(kind: Kind, color: Color, speed_scale: float, death: float) -> void:
	# Mostly upward and outward, like pieces thrown off a burst.
	var angle: float = _rng.randf_range(-PI * 0.95, -PI * 0.05)
	var speed: float = _rng.randf_range(burst_speed.x, burst_speed.y) * speed_scale
	_pos.append(Vector2(_rng.randf_range(-3.0, 3.0), _rng.randf_range(-2.0, 2.0)))
	_vel.append(Vector2.from_angle(angle) * speed)
	_size.append(SCRAP_SIZES[_rng.randi() % SCRAP_SIZES.size()] if kind == Kind.RECT else Vector2.ONE)
	_color.append(color)
	_phase.append(_rng.randf() * TAU)
	_death.append(death)
	_kind.append(kind)
	_flip_offset.append(_rng.randi_range(0, flutter_ticks * 2 - 1))


func _physics_process(delta: float) -> void:
	_age += delta
	if _age >= life:
		queue_free()
		return
	for i: int in _pos.size():
		var v: Vector2 = _vel[i]
		v.x = move_toward(v.x, 0.0, 90.0 * delta)
		v.y = minf(v.y + gravity * delta, max_fall_speed)
		var sway: float = cos(_age * 9.0 + _phase[i]) * flutter if v.y > 0.0 else 0.0
		_pos[i] += Vector2(v.x + sway, v.y) * delta
		_vel[i] = v
	queue_redraw()


func _draw() -> void:
	var tick: int = int(_age * 60.0)
	for i: int in _pos.size():
		var left: float = _death[i] - _age
		if left <= 0.0:
			continue
		# Wink out: blink for the last 0.15 s of each bit's life.
		if left < 0.15 and int(_age * 30.0) % 2 == 0:
			continue
		var at: Vector2 = _pos[i].round()
		if _kind[i] == Kind.SCRAP:
			var flip: int = floori(float(tick + _flip_offset[i]) / float(flutter_ticks))
			_draw_scrap(at, _color[i], _strut[i] != 0, flip % 2 == 0)
		else:
			draw_rect(Rect2(at, _size[i]), _color[i])


## One torn membrane scrap centred on [param at]: an optional strut row, then
## rows 5, 3 and 1 px wide, all hanging from the left edge or the right one,
## with the [member edge_color] hem down that edge.
func _draw_scrap(at: Vector2, color: Color, strut: bool, left_aligned: bool) -> void:
	var rows: int = MEMBRANE_ROWS.size() + (1 if strut else 0)
	var x0: float = at.x - floorf(MEMBRANE_WIDTH / 2.0)
	var y: float = at.y - floorf(rows / 2.0)
	if strut:
		draw_rect(Rect2(x0, y, MEMBRANE_WIDTH, 1.0), strut_color)
		y += 1.0
	for width: int in MEMBRANE_ROWS:
		var x: float = x0 if left_aligned else x0 + MEMBRANE_WIDTH - width
		draw_rect(Rect2(x, y, width, 1.0), color)
		if edge_color.a > 0.0:
			var hem_x: float = x if left_aligned else x + width - 1
			draw_rect(Rect2(hem_x, y, 1.0, 1.0), edge_color)
		y += 1.0
