## The SotN death tint: when Vesper dies the whole screen sinks toward
## red-black over 40 ticks, under the death label and the closing fade.
##
## Visual only. It answers [signal Events.player_died] like any other UI, so
## gameplay never knows it exists, and the scene reload that follows a death
## rebuilds it clear.
class_name DeathTint
extends ColorRect

const TINT_TICKS: float = 40.0
## Kept subtle: the room stays readable under it.
@export_range(0.0, 1.0) var tint_alpha: float = 0.4

var _tween: Tween


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	color.a = 0.0
	Events.player_died.connect(_on_player_died)


func _on_player_died() -> void:
	if _tween != null and _tween.is_valid():
		return
	_tween = create_tween()
	_tween.tween_property(self, "color:a", tint_alpha, TINT_TICKS / 60.0) \
		.set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_OUT)
