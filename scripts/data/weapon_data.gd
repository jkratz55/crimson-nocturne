## Data definition for a melee weapon (swords, whips, maces, ...).
##
## Weapons are pure data so designers can create new ones as `.tres`
## files in the inspector without touching code. Timing is expressed as
## *animation frames* ("frame data"), the industry-standard way to
## describe attack startup / active / recovery windows.
class_name WeaponData
extends Resource

@export var display_name: String = "Weapon"
@export_multiline var description: String = ""

@export_group("Damage")
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
