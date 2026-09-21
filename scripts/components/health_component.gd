## Reusable hit-point container.
##
## Attach to anything that can be damaged (player, enemies, bosses,
## destructible walls). It knows nothing about *how* damage arrives — a
## [Hurtbox] or a script calls [method take_damage] — and simply reports
## changes through signals.
class_name HealthComponent
extends Node

## Emitted after any change to [member current_health].
signal health_changed(current: int, maximum: int)
## Emitted after damage is applied, with the amount actually removed.
signal damaged(amount: int)
## Emitted once when health first reaches zero.
signal died

## Maximum hit points. Changing it at runtime clamps current health.
@export_range(1, 9999) var max_health: int = 10:
	set(value):
		max_health = maxi(1, value)
		if is_node_ready():
			current_health = mini(current_health, max_health)
			health_changed.emit(current_health, max_health)

## Flat damage reduction applied to every hit (minimum 1 damage still dealt).
@export_range(0, 999) var defense: int = 0

var current_health: int = 0
var is_dead: bool:
	get:
		return current_health <= 0


func _ready() -> void:
	current_health = max_health


## Apply [param amount] damage (after defense). Returns the damage dealt.
func take_damage(amount: int) -> int:
	if is_dead:
		return 0
	var dealt: int = maxi(1, amount - defense)
	current_health = maxi(0, current_health - dealt)
	damaged.emit(dealt)
	health_changed.emit(current_health, max_health)
	if current_health == 0:
		died.emit()
	return dealt


## Restore up to [param amount] hit points. Returns the amount healed.
func heal(amount: int) -> int:
	if is_dead:
		return 0
	var before: int = current_health
	current_health = mini(max_health, current_health + amount)
	if current_health != before:
		health_changed.emit(current_health, max_health)
	return current_health - before


## Refill to full (e.g. on respawn or at a save point).
func reset() -> void:
	current_health = max_health
	health_changed.emit(current_health, max_health)
