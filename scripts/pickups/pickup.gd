## Collectible dropped by enemies and candles: hearts, health and gold.
##
## Small hearts drift down side-to-side like falling leaves; big hearts and
## coins drop straight. Pickups expire after [member lifetime] seconds,
## blinking during the final stretch as a warning.
##
## This is the [i]transient[/i] kind of loot — rolled from a drop table and
## gone if you walk away. Unique, once-only things placed in the world by hand
## are [WorldItem]s instead, and those are remembered in the save file.
class_name Pickup
extends CharacterBody2D

enum Kind { HEARTS, HEALTH, GOLD }

@export var kind: Kind = Kind.HEARTS
@export var amount: int = 1
## Side-to-side sway while falling (0 = straight down).
@export var sway_amplitude: float = 0.0
@export var sway_frequency: float = 3.0
@export var fall_speed: float = 60.0
@export var pop_velocity: float = -90.0
@export var lifetime: float = 8.0
@export var collect_sfx: StringName = &"heart_pickup"
## Little additive star left behind when it is collected (visual only).
@export var collect_effect_scene: PackedScene = preload("res://scenes/fx/pickup_sparkle.tscn")

@onready var collect_area: Area2D = $CollectArea
## Sprite2D for a still pickup, AnimatedSprite2D for a spinning one.
@onready var sprite: CanvasItem = $Sprite

var _age: float = 0.0
var _gravity: float = ProjectSettings.get_setting("physics/2d/default_gravity")


func _ready() -> void:
	velocity.y = pop_velocity
	collect_area.body_entered.connect(_on_body_entered)
	# Start the baked glint / coin spin at a random moment of its cycle (not a
	# random frame: the glint frames are short, see [AnimPhase]), so drops
	# spawned together do not glint together. A private generator, so a drop
	# never shifts the gameplay rolls.
	var anim := sprite as AnimatedSprite2D
	if anim != null:
		var rng := RandomNumberGenerator.new()
		rng.randomize()
		AnimPhase.randomize_phase(anim, rng)


func _physics_process(delta: float) -> void:
	_age += delta
	if is_on_floor():
		velocity = Vector2.ZERO
	else:
		velocity.y = minf(velocity.y + _gravity * 0.5 * delta, fall_speed)
		velocity.x = cos(_age * sway_frequency) * sway_amplitude if velocity.y > 0.0 else 0.0
	move_and_slide()

	var remaining: float = lifetime - _age
	if remaining <= 0.0:
		queue_free()
	elif remaining < 2.0:
		sprite.visible = int(_age * 12.0) % 2 == 0


func _on_body_entered(body: Node2D) -> void:
	var player := body as Player
	if player == null or player.state == Player.State.DEAD:
		return
	match kind:
		Kind.HEARTS:
			player.add_hearts(amount)
		Kind.HEALTH:
			player.heal(amount)
		Kind.GOLD:
			GameManager.add_gold(amount)
	Audio.play_sfx(collect_sfx)
	_spawn_collect_effect()
	queue_free()


func _spawn_collect_effect() -> void:
	if collect_effect_scene == null or get_parent() == null:
		return
	var fx := collect_effect_scene.instantiate() as Node2D
	if fx == null:
		return
	fx.position = position + Vector2(0.0, -6.0)
	# Deferred: we are inside a physics callback.
	get_parent().add_child.call_deferred(fx)
