## Data definition for a heart-consuming sub-weapon (dagger, axe, holy water...).
class_name SubWeaponData
extends Resource

@export var display_name: String = "Sub-weapon"
## Icon shown in the HUD medallion.
@export var icon: Texture2D
## Scene instanced when thrown. Its root must be a [Projectile].
@export var projectile_scene: PackedScene
## Hearts consumed per throw.
@export_range(0, 99) var heart_cost: int = 1
## Maximum simultaneous instances on screen (classic Castlevania limit).
@export_range(1, 10) var max_active: int = 3
## Spawn point relative to the player's feet when facing right.
@export var spawn_offset: Vector2 = Vector2(12.0, -30.0)
@export var throw_sfx: StringName = &"dagger_throw"
