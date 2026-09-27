## Generic thrown/fired projectile (player sub-weapons and enemy missiles).
##
## Configure behaviour entirely from the inspector:
## - Straight shot (dagger): [member speed] > 0, no gravity.
## - Arc (axe, bone): set [member launch_velocity] and [member gravity_scale].
## - Piercing: [member destroy_on_hit] = false (the child Hitbox's
##   single-hit-per-activation ensures each target is only hit once).
##
## The root Area2D only scans the "world" layer (to break on walls); the
## child [Hitbox] carries the damage and its layer decides who is hurt.
class_name Projectile
extends Area2D

## Straight-line speed used when [member launch_velocity] is zero.
@export var speed: float = 300.0
## Initial velocity for arcing projectiles (x is mirrored by direction).
@export var launch_velocity: Vector2 = Vector2.ZERO
@export var gravity_scale: float = 0.0
## Spin in radians per second (mirrored by direction).
@export var spin_speed: float = 0.0
@export var lifetime: float = 2.0
@export var destroy_on_world: bool = true
@export var destroy_on_hit: bool = true
@export var impact_effect_scene: PackedScene

@onready var hitbox: Hitbox = $Hitbox
@onready var sprite: Sprite2D = $Sprite

var velocity: Vector2 = Vector2.ZERO
var direction: int = 1
var _gravity: float = ProjectSettings.get_setting("physics/2d/default_gravity")
var _age: float = 0.0
var _impacted: bool = false


func _ready() -> void:
	body_entered.connect(_on_body_entered)
	hitbox.hit_landed.connect(_on_hit_landed)


## Fire the projectile. [param dir] is 1 (right) or -1 (left).
func launch(dir: int) -> void:
	direction = dir
	if launch_velocity != Vector2.ZERO:
		velocity = Vector2(launch_velocity.x * dir, launch_velocity.y)
	else:
		velocity = Vector2(speed * dir, 0.0)
	sprite.flip_h = dir < 0


func _physics_process(delta: float) -> void:
	if _impacted:
		return
	velocity.y += _gravity * gravity_scale * delta
	position += velocity * delta
	rotation += spin_speed * direction * delta
	_age += delta
	if _age >= lifetime:
		hitbox.deactivate()
		queue_free()


func _on_body_entered(_body: Node2D) -> void:
	if destroy_on_world:
		_impact()


func _on_hit_landed(_hurtbox: Hurtbox) -> void:
	if destroy_on_hit:
		_impact()


func _impact() -> void:
	if _impacted:
		return
	_impacted = true
	hitbox.deactivate()
	set_deferred(&"monitoring", false)
	if impact_effect_scene:
		var fx := impact_effect_scene.instantiate() as Node2D
		get_parent().add_child.call_deferred(fx)
		var parent_2d := get_parent() as Node2D
		fx.position = parent_2d.to_local(global_position) if parent_2d else global_position
	queue_free()
