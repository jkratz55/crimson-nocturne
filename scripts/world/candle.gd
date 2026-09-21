## Breakable candle — the genre's signature loot container.
##
## Struck by any player attack, it bursts into a small flame and drops
## [member drop_scene] (usually a heart).
class_name Candle
extends Node2D

@export var drop_scene: PackedScene
@export var break_effect_scene: PackedScene

@onready var hurtbox: Hurtbox = $Hurtbox


func _ready() -> void:
	hurtbox.hit_received.connect(_on_hit_received)


func _on_hit_received(_hitbox: Hitbox) -> void:
	hurtbox.disable()
	Audio.play_sfx(&"candle_break")
	_spawn(break_effect_scene, global_position + Vector2(0, -20))
	_spawn(drop_scene, global_position + Vector2(0, -24))
	queue_free()


func _spawn(scene: PackedScene, at: Vector2) -> void:
	if scene == null:
		return
	var node := scene.instantiate() as Node2D
	get_parent().add_child(node)
	node.global_position = at
