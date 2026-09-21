## Floating damage number (rises, then fades out).
class_name DamageNumber
extends Node2D

const PLAYER_COLOR: Color = Color(1.0, 0.35, 0.35)
const ENEMY_COLOR: Color = Color(1.0, 1.0, 1.0)

@export var rise_distance: float = 16.0
@export var duration: float = 0.7

@onready var label: Label = $Label


## Configure before or after adding to the tree.
func setup(amount: int, is_player: bool) -> void:
	if not is_node_ready():
		await ready
	label.text = str(amount)
	modulate = PLAYER_COLOR if is_player else ENEMY_COLOR


func _ready() -> void:
	var tween: Tween = create_tween()
	tween.tween_property(self, "position:y", position.y - rise_distance, duration * 0.6) \
		.set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_OUT)
	tween.tween_property(self, "modulate:a", 0.0, duration * 0.4)
	tween.tween_callback(queue_free)
