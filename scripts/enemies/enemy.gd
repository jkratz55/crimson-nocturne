## Base class for every enemy.
##
## Handles everything enemies have in common so concrete enemies only
## implement behaviour in [method _ai_process]:
## - gravity (optional, flyers turn it off)
## - taking hits: damage numbers, white flash, knockback + stun, hit-stop
## - death: the classic "burst into flames" effect, sound, loot drop
##
## Scene contract (children expected by this script):
## [codeblock]
## Enemy (CharacterBody2D, this script or a subclass)
## ├── Sprite          AnimatedSprite2D, material = hit_flash ShaderMaterial (local to scene)
## ├── BodyShape       CollisionShape2D
## ├── HealthComponent
## ├── Hurtbox         layer "enemy_hurtbox", mask "player_attack"
## └── ContactHitbox   layer "enemy_attack" (damage on touch)
## [/codeblock]
class_name Enemy
extends CharacterBody2D

## Emitted right before the enemy is removed from the tree.
signal defeated(enemy: Enemy)

@export var display_name: String = "Enemy"

@export_group("Physics")
@export var uses_gravity: bool = true
@export var max_fall_speed: float = 380.0
## 0 = full knockback, 1 = immovable.
@export_range(0.0, 1.0) var knockback_resistance: float = 0.0
## Seconds the enemy's AI is paused after being hit.
@export var hit_stun_time: float = 0.25

@export_group("Combat")
@export_range(0, 999) var contact_damage: int = 5

@export_group("Rewards")
@export_range(0.0, 1.0) var heart_drop_chance: float = 0.4
@export_range(0.0, 1.0) var big_heart_chance: float = 0.15
@export var small_heart_scene: PackedScene
@export var big_heart_scene: PackedScene
## Experience awarded on kill (reserved for the future RPG layer).
@export var experience: int = 5

@export_group("Effects")
@export var death_effect_scene: PackedScene
@export var hit_effect_scene: PackedScene

@onready var sprite: AnimatedSprite2D = $Sprite
@onready var health: HealthComponent = $HealthComponent
@onready var hurtbox: Hurtbox = $Hurtbox
@onready var contact_hitbox: Hitbox = $ContactHitbox

## -1 = facing left, 1 = facing right. Sprites are drawn facing right.
var facing: int = -1
## The player, if present. Enemies should always null-check this.
var target: Player

var _gravity: float = ProjectSettings.get_setting("physics/2d/default_gravity")
var _stun_timer: float = 0.0
var _flash_tween: Tween


func _ready() -> void:
	add_to_group(&"enemies")
	contact_hitbox.damage = contact_damage
	contact_hitbox.single_hit_per_activation = false
	hurtbox.hit_received.connect(_on_hit_received)
	health.died.connect(_on_died)
	target = get_tree().get_first_node_in_group(&"player") as Player
	_set_facing(facing)


func _physics_process(delta: float) -> void:
	if uses_gravity:
		velocity.y = minf(velocity.y + _gravity * delta, max_fall_speed)
	if _stun_timer > 0.0:
		_stun_timer -= delta
		velocity.x = move_toward(velocity.x, 0.0, 500.0 * delta)
		if not uses_gravity:
			velocity.y = move_toward(velocity.y, 0.0, 500.0 * delta)
	else:
		_ai_process(delta)
	move_and_slide()


## Override in subclasses: set [member velocity] and animations here.
## Not called while the enemy is stunned.
func _ai_process(_delta: float) -> void:
	pass


## True if the player exists and is alive.
func has_live_target() -> bool:
	return is_instance_valid(target) and target.state != Player.State.DEAD


func _set_facing(dir: int) -> void:
	facing = dir
	sprite.flip_h = facing < 0


# ---------------------------------------------------------------------------
# Damage & death
# ---------------------------------------------------------------------------
func _on_hit_received(hitbox: Hitbox) -> void:
	var dealt: int = health.take_damage(hitbox.damage)
	Events.damage_dealt.emit(dealt, global_position + Vector2(0, -36), false)
	Audio.play_sfx(&"hit", 0.1)
	_flash()
	_spawn_effect(hit_effect_scene, hitbox.global_position.lerp(global_position + Vector2(0, -16), 0.5))
	if health.is_dead:
		return
	var dir: float = hitbox.get_knockback_direction(global_position)
	velocity.x = dir * hitbox.knockback_force * (1.0 - knockback_resistance)
	_stun_timer = hit_stun_time
	_on_hurt(hitbox)


## Hook for subclasses (e.g. interrupt an attack). Called after knockback.
func _on_hurt(_hitbox: Hitbox) -> void:
	pass


func _on_died() -> void:
	hurtbox.disable()
	contact_hitbox.deactivate()
	Audio.play_sfx(&"enemy_death")
	GameFeel.hit_stop(0.08)
	_spawn_effect(death_effect_scene, global_position)
	_drop_loot()
	Events.enemy_killed.emit(self)
	defeated.emit(self)
	queue_free()


func _drop_loot() -> void:
	if randf() > heart_drop_chance:
		return
	var scene: PackedScene = big_heart_scene if randf() < big_heart_chance else small_heart_scene
	if scene:
		_spawn_effect(scene, global_position + Vector2(0, -16))


func _flash() -> void:
	var mat := sprite.material as ShaderMaterial
	if mat == null:
		return
	if _flash_tween and _flash_tween.is_valid():
		_flash_tween.kill()
	mat.set_shader_parameter(&"flash_amount", 1.0)
	_flash_tween = create_tween()
	_flash_tween.tween_method(
		func(v: float) -> void: mat.set_shader_parameter(&"flash_amount", v), 1.0, 0.0, 0.18)


## Instance [param scene] into the room (our parent) at [param at].
func _spawn_effect(scene: PackedScene, at: Vector2) -> void:
	if scene == null:
		return
	var node := scene.instantiate() as Node2D
	get_parent().add_child(node)
	node.global_position = at
