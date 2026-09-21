## Area that can receive hits from [Hitbox]es.
##
## Polls overlapping hitboxes every physics frame instead of relying only
## on [signal Area2D.area_entered]. This matters for contact damage: if the
## player is still standing inside an enemy when their invincibility ends,
## they must get hit again even though no new "enter" event happens.
##
## The hurtbox does not modify health itself. Its owner listens to
## [signal hit_received] and decides what a hit means (damage, knockback,
## a candle breaking, a boss weak point, ...).
class_name Hurtbox
extends Area2D

## Emitted when a hit is accepted.
signal hit_received(hitbox: Hitbox)

## Seconds of invincibility granted automatically after each hit (0 = none).
@export var invincibility_duration: float = 0.0

var is_invincible: bool = false
var _invincibility_token: int = 0


func _ready() -> void:
	monitorable = false  # Hurtboxes scan; they are never scanned.


func _physics_process(_delta: float) -> void:
	if is_invincible or not monitoring:
		return
	for area: Area2D in get_overlapping_areas():
		var hitbox := area as Hitbox
		if hitbox == null or not hitbox.can_hit(self):
			continue
		hitbox.register_hit(self)
		hit_received.emit(hitbox)
		if invincibility_duration > 0.0:
			start_invincibility(invincibility_duration)
		if is_invincible:
			return


## Ignore all hits for [param duration] seconds. Calling again restarts the timer.
func start_invincibility(duration: float) -> void:
	is_invincible = true
	_invincibility_token += 1
	var token: int = _invincibility_token
	await get_tree().create_timer(duration, false, true).timeout
	if token == _invincibility_token:
		is_invincible = false


## Immediately stop accepting hits (death, cutscenes...). Physics-safe.
func disable() -> void:
	set_deferred(&"monitoring", false)
