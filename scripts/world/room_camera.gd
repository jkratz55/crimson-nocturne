## Side-scrolling camera for a single room.
##
## Follows [member target] with exponential smoothing and a look-ahead in
## the direction the player faces, is clamped to the room bounds, and
## performs trauma-style screen shake on [signal Events.camera_shake_requested].
## Runs in the physics step to stay in lockstep with the player body and
## avoid jitter.
class_name RoomCamera
extends Camera2D

@export var target: Node2D
@export var look_ahead: float = 28.0
## Vertical framing offset (negative = look higher than the feet).
@export var vertical_offset: float = -30.0
## Higher = snappier follow.
@export var follow_speed: float = 7.0

var _shake_strength: float = 0.0
var _shake_time_left: float = 0.0
var _shake_duration: float = 0.0


func _ready() -> void:
	process_callback = Camera2D.CAMERA2D_PROCESS_PHYSICS
	Events.camera_shake_requested.connect(shake)
	if target:
		global_position = _desired_position()
		reset_smoothing()


## Clamp the camera to [param bounds] (world space, pixels).
func set_room_bounds(bounds: Rect2i) -> void:
	limit_left = bounds.position.x
	limit_top = bounds.position.y
	limit_right = bounds.end.x
	limit_bottom = bounds.end.y


func shake(strength: float, duration: float) -> void:
	if strength >= _shake_strength * (_shake_time_left / maxf(_shake_duration, 0.001)):
		_shake_strength = strength
		_shake_duration = duration
		_shake_time_left = duration


func _physics_process(delta: float) -> void:
	if is_instance_valid(target):
		var weight: float = 1.0 - exp(-follow_speed * delta)
		global_position = global_position.lerp(_desired_position(), weight)
	if _shake_time_left > 0.0:
		_shake_time_left -= delta
		var k: float = _shake_time_left / _shake_duration
		offset = Vector2(randf_range(-1.0, 1.0), randf_range(-1.0, 1.0)) * _shake_strength * k * k
	else:
		offset = Vector2.ZERO


func _desired_position() -> Vector2:
	var ahead: float = 0.0
	var player := target as Player
	if player:
		ahead = look_ahead * player.facing
	var desired: Vector2 = target.global_position + Vector2(ahead, vertical_offset)
	# Clamp the *camera position* (not just the view) to the room so that
	# smoothing never "lags" behind an invisible out-of-bounds point when
	# the player walks back from a wall.
	var half_view: Vector2 = get_viewport_rect().size * 0.5 / zoom
	desired.x = clampf(desired.x, limit_left + half_view.x, maxf(limit_left + half_view.x, limit_right - half_view.x))
	desired.y = clampf(desired.y, limit_top + half_view.y, maxf(limit_top + half_view.y, limit_bottom - half_view.y))
	return desired
