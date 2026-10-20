## Base class for every enemy.
##
## Handles everything enemies have in common so concrete enemies only
## implement behaviour in [method _ai_process]:
## - gravity (optional, flyers turn it off)
## - taking hits: damage numbers, white flash, knockback + stun, hit-stop
## - death: the classic "burst into flames" effect, sound, loot drop
##   (subclasses can replace the visuals in [method _spawn_death_visuals])
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

## SotN-style hit flash (the CLUT swap): solid white with the outlines kept,
## then a crimson tint at 60%, then normal. See shaders/hit_flash.gdshader.
const FLASH_WHITE: Color = Color(1.0, 1.0, 1.0)
const FLASH_CRIMSON: Color = Color(0.769, 0.243, 0.259)
const FLASH_WHITE_TICKS: float = 2.0
const FLASH_CRIMSON_TICKS: float = 2.0
## hit_flash.gdshader's flash_mode values.
const FLASH_MODE_SOLID: int = 0
const FLASH_MODE_TINT: int = 1

@export var display_name: String = "Enemy"

## Difficulty tier multiplier applied to HP and damage when the enemy enters
## the tree, so one resource can staff an early wing and a late one (SPEC 4.5).
## Rooms set this on the enemies they spawn; 1.0 leaves the authored values alone.
@export_range(0.25, 8.0, 0.05) var tier_multiplier: float = 1.0

@export_group("Physics")
@export var uses_gravity: bool = true
@export var max_fall_speed: float = 380.0
## 0 = full knockback, 1 = immovable.
@export_range(0.0, 1.0) var knockback_resistance: float = 0.0
## Seconds the enemy's AI is paused after being hit.
@export var hit_stun_time: float = 0.25

@export_group("Combat")
@export_range(0, 999) var contact_damage: int = 5
## Fed to [method Combat.compute_damage] as this enemy's Strength, on top of
## whatever base damage its hitbox carries.
@export_range(0, 999) var attack_power: int = 0

@export_group("Rewards")
## Experience banked by the player on kill, scaled to the enemy's tier (SPEC 4.5).
@export_range(0, 99999) var experience: int = 5
@export_subgroup("Hearts")
@export_range(0.0, 1.0) var heart_drop_chance: float = 0.4
@export_range(0.0, 1.0) var big_heart_chance: float = 0.15
@export var small_heart_scene: PackedScene
@export var big_heart_scene: PackedScene
@export_subgroup("Gold")
## Chance of dropping coin at all, rolled independently of hearts (SPEC 4.5).
@export_range(0.0, 1.0) var gold_drop_chance: float = 0.3
## Inclusive [min, max] gold in the drop.
@export var gold_amount_range: Vector2i = Vector2i(5, 15)
@export var gold_scene: PackedScene

@export_group("Effects")
@export var death_effect_scene: PackedScene
@export var hit_effect_scene: PackedScene
## Spark for the killing blow (a bigger burst); falls back to [member hit_effect_scene].
@export var kill_effect_scene: PackedScene
## Where this enemy's damage numbers appear, relative to its origin.
@export var damage_number_offset: Vector2 = Vector2(0, -36)

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
## Direction (-1 / 1) the last blow pushed us, 0 if never hit. Visual only:
## death pieces fly this way.
var _last_hit_dir: float = 0.0
## Private generator for cosmetic jitter, so effects never shift gameplay rolls.
var _fx_rng: RandomNumberGenerator = RandomNumberGenerator.new()


func _ready() -> void:
	add_to_group(&"enemies")
	_apply_tier()
	contact_hitbox.damage = contact_damage
	contact_hitbox.attack_power = attack_power
	contact_hitbox.single_hit_per_activation = false
	hurtbox.hit_received.connect(_on_hit_received)
	health.died.connect(_on_died)
	target = get_tree().get_first_node_in_group(&"player") as Player
	_fx_rng.randomize()
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
	# Before take_damage: a killing blow runs _on_died() from inside it.
	_last_hit_dir = hitbox.get_knockback_direction(global_position)
	var dealt: int = health.take_damage(
		Combat.compute_damage(hitbox.damage, hitbox.attack_power, health.defense))
	Events.damage_dealt.emit(dealt, global_position + damage_number_offset, false)
	Audio.play_sfx(&"hit", 0.1)
	_flash()
	var spark: PackedScene = kill_effect_scene if health.is_dead and kill_effect_scene != null \
		else hit_effect_scene
	var jitter := Vector2(_fx_rng.randf_range(-3.0, 3.0), _fx_rng.randf_range(-3.0, 3.0)).round()
	_spawn_effect(spark, hitbox.get_strike_point().lerp(global_position + Vector2(0, -16), 0.5) + jitter)
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
	_spawn_death_visuals()
	_drop_loot()
	GameManager.add_experience(experience)
	Events.enemy_killed.emit(self)
	defeated.emit(self)
	queue_free()


## What the death looks like. The default bursts into [member death_effect_scene];
## subclasses override it (the skeleton breaks apart). Visual only: it runs
## inside [method _on_died], which owns the loot, experience and signals.
func _spawn_death_visuals() -> void:
	_spawn_effect(death_effect_scene, global_position)


## The way death pieces should fly: away from the last blow, or backwards
## if the enemy died without being hit.
func _death_push_direction() -> float:
	return _last_hit_dir if _last_hit_dir != 0.0 else float(-facing)


## Roll the hearts and the gold independently, as the spec's drop tables do:
## an enemy may drop both, either or neither.
func _drop_loot() -> void:
	if randf() < heart_drop_chance:
		var scene: PackedScene = big_heart_scene if randf() < big_heart_chance else small_heart_scene
		if scene:
			_spawn_effect(scene, global_position + Vector2(0, -16))
	if gold_scene != null and randf() < gold_drop_chance:
		var coin := gold_scene.instantiate() as Pickup
		coin.amount = randi_range(gold_amount_range.x, maxi(gold_amount_range.x, gold_amount_range.y))
		get_parent().add_child(coin)
		coin.global_position = global_position + Vector2(randf_range(-6.0, 6.0), -16.0)


## Scale the authored stats by the wing's difficulty tier. Children are ready
## before we are, so the [HealthComponent] has already filled itself to the
## authored maximum — [method HealthComponent.reset] tops it up to the new one.
func _apply_tier() -> void:
	if is_equal_approx(tier_multiplier, 1.0):
		return
	health.max_health = maxi(1, roundi(health.max_health * tier_multiplier))
	health.reset()
	health.defense = roundi(health.defense * tier_multiplier)
	contact_damage = maxi(1, roundi(contact_damage * tier_multiplier))
	attack_power = roundi(attack_power * tier_multiplier)
	experience = maxi(1, roundi(experience * tier_multiplier))


func _flash() -> void:
	var mat := sprite.material as ShaderMaterial
	if mat == null:
		return
	if _flash_tween and _flash_tween.is_valid():
		_flash_tween.kill()
	_set_flash(mat, FLASH_WHITE, 1.0, FLASH_MODE_SOLID)
	# Game-time ticks: hit-stop holds the white frame, as in SotN.
	_flash_tween = create_tween()
	_flash_tween.tween_interval(FLASH_WHITE_TICKS / 60.0)
	_flash_tween.tween_callback(_set_flash.bind(mat, FLASH_CRIMSON, 0.6, FLASH_MODE_TINT))
	_flash_tween.tween_interval(FLASH_CRIMSON_TICKS / 60.0)
	_flash_tween.tween_callback(_set_flash.bind(mat, FLASH_WHITE, 0.0, FLASH_MODE_SOLID))


func _set_flash(mat: ShaderMaterial, color: Color, amount: float, mode: int) -> void:
	mat.set_shader_parameter(&"flash_color", color)
	mat.set_shader_parameter(&"flash_amount", amount)
	mat.set_shader_parameter(&"flash_mode", mode)


## Instance [param scene] into the room (our parent) at [param at].
func _spawn_effect(scene: PackedScene, at: Vector2) -> void:
	if scene == null:
		return
	var node := scene.instantiate() as Node2D
	get_parent().add_child(node)
	node.global_position = at
