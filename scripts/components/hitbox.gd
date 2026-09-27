## Area that deals damage ("the business end" of a weapon, projectile or body).
##
## Hitboxes are passive: they are detected by [Hurtbox]es, which ask
## [method can_hit] before accepting a hit. The collision *layer* decides
## who can be hurt (player attacks live on the "player_attack" layer and
## are only scanned by enemy hurtboxes, and vice versa).
##
## [b]Activation model[/b][br]
## Melee swings call [method activate] on their first active frame and
## [method deactivate] after the last one. With [member single_hit_per_activation]
## each hurtbox can only be hit once per swing, no matter how many frames
## it overlaps. Contact damage (enemy bodies) leaves that off and relies on
## the victim's invincibility frames instead.
class_name Hitbox
extends Area2D

## Emitted after a hurtbox accepted this hitbox's hit.
signal hit_landed(hurtbox: Hurtbox)

## Base damage, before [method Combat.compute_damage] applies the wielder's
## power and the victim's Defense.
@export_range(0, 999) var damage: int = 1
## The wielder's Strength (or an enemy's equivalent). Set at runtime by
## whatever owns the hitbox; 0 means "the base damage is the whole story".
@export_range(0, 999) var attack_power: int = 0
## Horizontal knockback speed applied to the victim (px/s).
@export var knockback_force: float = 120.0
## If true a given hurtbox can only be hit once until [method activate] is called again.
@export var single_hit_per_activation: bool = true
## Whether the hitbox starts enabled.
@export var start_active: bool = true

var is_active: bool = false
var _already_hit: Array[Hurtbox] = []


func _ready() -> void:
	# Hitboxes never scan; they are scanned by hurtboxes.
	monitoring = false
	if start_active:
		activate()
	else:
		deactivate()


## Enable the hitbox and forget who it already hit.
func activate() -> void:
	is_active = true
	_already_hit.clear()
	_set_shapes_disabled(false)


## Disable the hitbox (shape changes are deferred to be physics-safe).
func deactivate() -> void:
	is_active = false
	_set_shapes_disabled(true)


func can_hit(hurtbox: Hurtbox) -> bool:
	if not is_active:
		return false
	return not (single_hit_per_activation and _already_hit.has(hurtbox))


## Called by the hurtbox once the hit is accepted.
func register_hit(hurtbox: Hurtbox) -> void:
	if single_hit_per_activation:
		_already_hit.append(hurtbox)
	hit_landed.emit(hurtbox)


## Direction a victim at [param target_position] should be knocked back.
## Returns -1 (left) or 1 (right).
func get_knockback_direction(target_position: Vector2) -> float:
	var dx: float = target_position.x - global_position.x
	return 1.0 if dx >= 0.0 else -1.0


func _set_shapes_disabled(disabled: bool) -> void:
	for child: Node in get_children():
		if child is CollisionShape2D or child is CollisionPolygon2D:
			child.set_deferred(&"disabled", disabled)
