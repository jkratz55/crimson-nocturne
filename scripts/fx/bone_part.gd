## One flying piece of a broken enemy (the SotN skeleton break-apart).
##
## Spawned already moving: it flashes white for [member flash_ticks], arcs
## under [member gravity] while spinning, skips off the floor line if it gets
## that far, and after [member life] seconds bursts into [member pop_scene]
## and frees itself. Purely visual: no collision, no gameplay effect.
class_name BonePart
extends Sprite2D

## px/s; set by the spawner.
var velocity: Vector2 = Vector2.ZERO
## rad/s.
var spin_speed: float = 0.0
## px/s^2 (0.6 x the project's 900, so the pieces hang in the air a moment).
var gravity: float = 540.0
## Seconds until the piece bursts.
var life: float = 0.5
## The small fire puff it bursts into (optional).
var pop_scene: PackedScene
## World y of the floor the enemy stood on; pieces bounce off it.
var floor_y: float = INF
## Ticks the piece stays flashed white (needs a hit_flash [ShaderMaterial]).
var flash_ticks: float = 3.0

var _age: float = 0.0
var _flashing: bool = false


func _ready() -> void:
	var mat := material as ShaderMaterial
	if mat != null and flash_ticks > 0.0:
		mat.set_shader_parameter(&"flash_amount", 1.0)
		_flashing = true


func _physics_process(delta: float) -> void:
	_age += delta
	if _flashing and _age * 60.0 >= flash_ticks:
		_flashing = false
		(material as ShaderMaterial).set_shader_parameter(&"flash_amount", 0.0)
	velocity.y += gravity * delta
	global_position += velocity * delta
	rotation += spin_speed * delta
	if global_position.y > floor_y - 3.0 and velocity.y > 0.0:
		global_position.y = floor_y - 3.0
		velocity = Vector2(velocity.x * 0.5, -velocity.y * 0.35)
		spin_speed *= 0.5
	if _age >= life:
		_pop()


func _pop() -> void:
	if pop_scene != null and get_parent() != null:
		var fx := pop_scene.instantiate() as Node2D
		if fx != null:
			get_parent().add_child(fx)
			fx.global_position = global_position.round()
	queue_free()
