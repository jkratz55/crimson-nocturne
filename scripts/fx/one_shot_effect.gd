## Plays its animation once, then frees itself. Used for hit sparks,
## death flames and other fire-and-forget visual effects.
class_name OneShotEffect
extends AnimatedSprite2D

## Optional: one of these animations is picked at random on spawn (e.g. the
## hit spark's star / slash variants). Empty plays the scene's own animation.
## Picked with a private generator, so effects never shift gameplay rolls.
@export var random_animations: Array[StringName] = []


func _ready() -> void:
	animation_finished.connect(queue_free)
	if not random_animations.is_empty() and sprite_frames != null:
		var rng := RandomNumberGenerator.new()
		rng.randomize()
		var pick: StringName = random_animations[rng.randi() % random_animations.size()]
		if sprite_frames.has_animation(pick):
			animation = pick
	play()
