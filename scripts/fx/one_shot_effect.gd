## Plays its animation once, then frees itself. Used for hit sparks,
## death flames and other fire-and-forget visual effects.
class_name OneShotEffect
extends AnimatedSprite2D


func _ready() -> void:
	animation_finished.connect(queue_free)
	play()
