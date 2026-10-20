## Cave bat.
##
## Hangs from the ceiling until the player passes beneath it (a horizontal
## proximity check, since bats roost far above the floor), then swoops toward
## them in a sine-wave flight path. Ignores level geometry, like its
## 2D-era ancestors.
class_name Bat
extends Enemy

enum AIState { HANG, SWOOP }

## Horizontal distance to the player that wakes a hanging bat.
@export var wake_distance: float = 110.0
## The player must also be within this many pixels vertically (below or
## above) so bats in distant parts of a tall room stay asleep.
@export var wake_vertical_range: float = 240.0
@export var fly_speed: float = 72.0
@export var horizontal_acceleration: float = 140.0
@export var wave_amplitude: float = 40.0
@export var wave_frequency: float = 4.0
## Vertical offset of the point the bat homes in on (the player's chest).
@export var aim_offset: Vector2 = Vector2(0.0, -22.0)

@export_group("Death")
## Torn wing scraps that flutter down after the death puff (visual only).
@export_range(0, 24) var wing_bits: int = 7
## Membrane tones the scraps are drawn in: one dark tone from the bat sheet,
## which reads as a silhouette on the mid-value dado, and three lighter ones
## that read on the dark upper wall. Every other scrap carries a light strut.
@export var wing_bit_colors: PackedColorArray = PackedColorArray([
	Color8(56, 30, 64), Color8(118, 66, 112), Color8(122, 80, 128), Color8(150, 94, 134)])
## The scraps' light edges, cool lavender so they part from the warm rose
## dado as well as the dark ashlar: the strut row along the top of every other
## scrap, and the hem down the side every scrap hangs from.
@export var wing_bit_strut_color: Color = Color8(178, 176, 222)
@export var wing_bit_edge_color: Color = Color8(196, 202, 240)
## A couple of embers thrown off the fire pop with the scraps.
@export_range(0, 8) var wing_bit_sparks: int = 2
@export var wing_bit_spark_colors: PackedColorArray = PackedColorArray([
	Color8(255, 190, 70), Color8(236, 118, 36)])

var ai_state: AIState = AIState.HANG
var _flight_time: float = 0.0


func _ready() -> void:
	super._ready()
	sprite.animation_finished.connect(_on_animation_finished)
	sprite.play(&"hang")


func _ai_process(delta: float) -> void:
	match ai_state:
		AIState.HANG:
			velocity = Vector2.ZERO
			if has_live_target() and _is_target_in_wake_range():
				_wake()
		AIState.SWOOP:
			_swoop(delta)


func _is_target_in_wake_range() -> bool:
	var delta_pos: Vector2 = target.global_position - global_position
	return absf(delta_pos.x) < wake_distance and absf(delta_pos.y) < wake_vertical_range


func _wake() -> void:
	ai_state = AIState.SWOOP
	# Visual only: drop off the roost with a short unfurl, then flap.
	if sprite.sprite_frames.has_animation(&"unfurl"):
		sprite.play(&"unfurl")
	else:
		sprite.play(&"fly")
	Audio.play_sfx(&"bat_screech", 0.15)


func _swoop(delta: float) -> void:
	_flight_time += delta
	var aim: Vector2 = global_position + Vector2(facing * 60.0, 0.0)
	if has_live_target():
		aim = target.global_position + aim_offset
	var to_aim: Vector2 = aim - global_position
	var dir_x: float = signf(to_aim.x) if absf(to_aim.x) > 4.0 else float(facing)
	velocity.x = move_toward(velocity.x, dir_x * fly_speed, horizontal_acceleration * delta)
	var homing: float = clampf(to_aim.y * 1.5, -fly_speed, fly_speed)
	velocity.y = homing + cos(_flight_time * wave_frequency) * wave_amplitude
	if absf(velocity.x) > 1.0:
		_set_facing(1 if velocity.x > 0.0 else -1)


func _on_hurt(_hitbox: Hitbox) -> void:
	if ai_state == AIState.HANG:
		_wake()


func _on_animation_finished() -> void:
	if sprite.animation == &"unfurl":
		sprite.play(&"fly")


## Visual only: the death puff, then a few torn wing scraps drifting down.
func _spawn_death_visuals() -> void:
	super._spawn_death_visuals()
	if wing_bits <= 0 or get_parent() == null:
		return
	# Warm, saturated tones in the palette are embers from the fire pop: they
	# fly as 1x1 sparks that burn out fast, never as membrane scraps.
	var membrane := PackedColorArray()
	var embers := PackedColorArray(wing_bit_spark_colors)
	for color: Color in wing_bit_colors:
		if _is_ember(color):
			embers.append(color)
		else:
			membrane.append(color)
	if membrane.is_empty():
		membrane.append(Color8(122, 80, 128))
	var bits := DebrisBits.new()
	bits.count = wing_bits
	bits.colors = membrane
	bits.shaped = true
	bits.strut_color = wing_bit_strut_color
	bits.edge_color = wing_bit_edge_color
	# Slow, long-lived drift: the scraps hang in the air for the whole 0.8 s.
	bits.max_fall_speed = 24.0
	bits.life_spread = 0.2
	bits.spark_count = wing_bit_sparks if not embers.is_empty() else 0
	bits.spark_colors = embers
	bits.spark_life = 0.3
	bits.z_index = z_index
	get_parent().add_child(bits)
	bits.global_position = global_position.round()


## True for a fire tone (hot red-orange-yellow) rather than a membrane tone.
static func _is_ember(color: Color) -> bool:
	return color.r > 0.7 and color.b < 0.35 and color.r - color.b > 0.5
