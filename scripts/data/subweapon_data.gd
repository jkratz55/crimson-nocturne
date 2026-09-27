## Data definition for a heart-consuming sub-weapon (dagger, axe, holy water...).
##
## Sub-weapons follow the Symphony of the Night model (SPEC 4.2.2): every one
## Vesper has ever found stays in the inventory, only one is equipped at a
## time, and throwing it spends from the single shared heart pool. Name,
## description, icon, price and stat modifiers come from [ItemData].
class_name SubWeaponData
extends ItemData

@export_group("Cost")
## Hearts consumed per throw. Stronger sub-weapons cost more.
@export_range(0, 99) var heart_cost: int = 1
## Seconds before this sub-weapon can be thrown again.
@export_range(0.0, 10.0, 0.05) var cooldown: float = 0.0

@export_group("Damage")
## Base damage fed into [method Combat.compute_damage], like a melee weapon.
## 0 means "let the projectile scene's own Hitbox decide".
@export_range(0, 999) var damage: int = 0

@export_group("Projectile")
## Scene instanced when thrown. Its root must be a [Projectile].
@export var projectile_scene: PackedScene
## Maximum simultaneous instances on screen (classic Castlevania limit).
@export_range(1, 10) var max_active: int = 3
## Spawn point relative to the player's feet when facing right.
@export var spawn_offset: Vector2 = Vector2(12.0, -30.0)

@export_group("Feedback")
@export var throw_sfx: StringName = &"dagger_throw"
