## Floating damage number, SotN style: the digits unfold from a wide, flat
## strip, rise half a pixel per tick, flicker between two tones every tick
## and spend their last few ticks at half opacity. All timing is in 60 Hz
## ticks of game time, so hit-stop holds the number with everything else.
##
## The unfold grows in whole glyph rows (never a fractional nearest-filtered
## squash, which drops rows and smears the digits into bars), and a number
## that lands on top of one still on screen starts above it instead.
class_name DamageNumber
extends Node2D

const LIFE_TICKS: float = 64.0
const UNFOLD_TICKS: float = 6.0
const RISE_PER_TICK: float = 0.5
const FADE_TICKS: float = 6.0
## Start of the unfold: this many times wider.
const UNFOLD_WIDTH: float = 2.0
## Glyph height of the damage font; the unfold steps through these rows, from
## [constant UNFOLD_MIN_ROWS] up.
const GLYPH_ROWS: float = 9.0
const UNFOLD_MIN_ROWS: float = 2.0
## A new number closer than this (x) to a live one, and less than
## [constant STACK_STEP] apart vertically, starts [constant STACK_STEP] above it.
const STACK_RADIUS: float = 12.0
const STACK_STEP: float = 10.0
## The two tones each number flickers between.
const ENEMY_TONES: Array[Color] = [Color(1.0, 1.0, 1.0), Color(1.0, 0.925, 0.588)]
const PLAYER_TONES: Array[Color] = [Color(1.0, 0.376, 0.376), Color(1.0, 0.784, 0.784)]
## Kept for callers that colour things to match the numbers.
const PLAYER_COLOR: Color = Color(1.0, 0.376, 0.376)
const ENEMY_COLOR: Color = Color(1.0, 1.0, 1.0)

@onready var label: Label = $Label

var _is_player: bool = false
var _age: float = 0.0
var _origin_y: float = 0.0

## Every number currently on screen, for the stacking.
static var _live: Array[DamageNumber] = []


## Configure before or after adding to the tree.
func setup(amount: int, is_player: bool) -> void:
	if not is_node_ready():
		await ready
	label.text = str(amount)
	_is_player = is_player
	_apply()


func _ready() -> void:
	_stack_above_live_numbers()
	_live.append(self)
	_origin_y = position.y
	label.pivot_offset = label.size * 0.5
	_apply()


func _exit_tree() -> void:
	_live.erase(self)


## Move up past any live number this one would land on (visual only).
func _stack_above_live_numbers() -> void:
	for _attempt: int in 4:
		var clash: DamageNumber = null
		for other: DamageNumber in _live:
			if is_instance_valid(other) and other != self and other.get_parent() == get_parent() \
					and absf(other.position.x - position.x) < STACK_RADIUS \
					and absf(other.position.y - position.y) < STACK_STEP:
				clash = other
				break
		if clash == null:
			return
		position.y = clash.position.y - STACK_STEP


func _process(delta: float) -> void:
	_age += delta * 60.0
	if _age >= LIFE_TICKS:
		queue_free()
		return
	_apply()


func _apply() -> void:
	position.y = _origin_y - roundf(_age * RISE_PER_TICK)
	var t: float = clampf(_age / UNFOLD_TICKS, 0.0, 1.0)
	var rows: float = maxf(UNFOLD_MIN_ROWS, roundf(t * GLYPH_ROWS))
	label.scale = Vector2(lerpf(UNFOLD_WIDTH, 1.0, t), rows / GLYPH_ROWS)
	var tones: Array[Color] = PLAYER_TONES if _is_player else ENEMY_TONES
	var c: Color = tones[int(_age) % 2]
	c.a = 0.5 if _age > LIFE_TICKS - FADE_TICKS else 1.0
	modulate = c
