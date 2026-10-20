## Breakable candle — the genre's signature loot container.
##
## Struck by any player attack, it bursts into a small flame and drops
## [member drop_scene] (usually a heart).
##
## Every candle starts its flame and halo at a phase taken from its position,
## so a row of candles never flickers in lock-step (deterministic, and it
## leaves the gameplay RNG alone).
class_name Candle
extends Node2D

@export var drop_scene: PackedScene
@export var break_effect_scene: PackedScene

@onready var hurtbox: Hurtbox = $Hurtbox


func _ready() -> void:
	hurtbox.hit_received.connect(_on_hit_received)
	var phase: int = absi(int(global_position.x) * 7 + int(global_position.y) * 13)
	_desync(get_node_or_null(^"Sprite") as AnimatedSprite2D, phase)
	_desync(get_node_or_null(^"Halo") as AnimatedSprite2D, phase * 3 + 1)


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


## Start [param sprite] [param phase] ticks into its cycle (wrapped), so the
## uneven flicker frames are hit in proportion to their length.
func _desync(sprite: AnimatedSprite2D, phase: int) -> void:
	if sprite == null:
		return
	AnimPhase.seek(sprite, float(phase))
