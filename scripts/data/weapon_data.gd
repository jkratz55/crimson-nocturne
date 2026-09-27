## Data definition for a melee weapon (swords, whips, maces, ...).
##
## Weapons are pure data so designers can create new ones as `.tres`
## files in the inspector without touching code. Timing is expressed as
## *animation frames* ("frame data"), the industry-standard way to
## describe attack startup / active / recovery windows.
##
## The same resource can be equipped in either hand: the primary slot is
## swung by the Attack button, the secondary slot by Secondary Attack
## (SPEC 4.1). Name, description, icon, price and stat modifiers come from
## [ItemData].
class_name WeaponData
extends ItemData

@export_group("Damage")
## Base damage fed into [method Combat.compute_damage]; the wielder's
## Strength and the victim's Defense do the rest.
@export_range(0, 999) var damage: int = 10
## Knockback speed applied to enemies (px/s).
@export var knockback: float = 110.0

@export_group("Hitbox")
## Size of the hitbox rectangle while active.
@export var hitbox_size: Vector2 = Vector2(28.0, 10.0)
## Offset from the player's origin (feet) when facing right while standing.
@export var hitbox_offset: Vector2 = Vector2(24.0, -30.0)
## Offset used for the crouching attack.
@export var crouch_hitbox_offset: Vector2 = Vector2(24.0, -21.0)

@export_group("Animation")
## Base name of the player's attack animation for this weapon. The crouching
## and aerial variants are this name plus "_crouch" / "_air", which is the
## naming convention used by the [SpriteFrames] the hero pipeline generates.
@export var attack_animation: StringName = &"attack"

@export_group("Frame Data")
## First and last animation frame (inclusive) on which the hitbox is live.
@export var active_frames: Vector2i = Vector2i(1, 3)
## Multiplier on the attack animation's base FPS (heavier weapons < 1).
@export_range(0.25, 3.0, 0.05) var speed_scale: float = 1.0

@export_group("Feedback")
@export var swing_sfx: StringName = &"sword_swing"
## Real-time seconds of hit-stop when this weapon connects.
@export var hit_stop: float = 0.05


## True if [param frame] of the attack animation should have a live hitbox.
func is_frame_active(frame: int) -> bool:
	return frame >= active_frames.x and frame <= active_frames.y


## Animation to play for the given stance.
func get_attack_animation(crouching: bool, airborne: bool) -> StringName:
	if crouching:
		return StringName("%s_crouch" % attack_animation)
	if airborne:
		return StringName("%s_air" % attack_animation)
	return attack_animation


## How far the hitbox reaches from the player's centre (px), for menus.
func get_reach() -> float:
	return hitbox_offset.x + hitbox_size.x * 0.5
