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

var ai_state: AIState = AIState.HANG
var _flight_time: float = 0.0


func _ready() -> void:
	super._ready()
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
