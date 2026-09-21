## Collectible dropped by enemies and candles (hearts, and later money, items...).
##
## Small hearts drift down side-to-side like falling leaves; big hearts
## drop straight. Pickups expire after [member lifetime] seconds, blinking
## during the final stretch as a warning.
class_name Pickup
extends CharacterBody2D

enum Kind { HEARTS, HEALTH }

@export var kind: Kind = Kind.HEARTS
@export var amount: int = 1
## Side-to-side sway while falling (0 = straight down).
@export var sway_amplitude: float = 0.0
@export var sway_frequency: float = 3.0
@export var fall_speed: float = 60.0
@export var pop_velocity: float = -90.0
@export var lifetime: float = 8.0
@export var collect_sfx: StringName = &"heart_pickup"

@onready var collect_area: Area2D = $CollectArea
@onready var sprite: Sprite2D = $Sprite

var _age: float = 0.0
var _gravity: float = ProjectSettings.get_setting("physics/2d/default_gravity")


func _ready() -> void:
	velocity.y = pop_velocity
	collect_area.body_entered.connect(_on_body_entered)


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
	Audio.play_sfx(collect_sfx)
	queue_free()
