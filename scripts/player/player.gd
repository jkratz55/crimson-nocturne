## Vesper — the playable dhampir.
##
## A platformer controller driven by a small, explicit finite state machine.
## Every state owns one `_state_*` physics function; transitions go through
## [method _change_state] so enter/exit logic lives in one place.
##
## [b]Feel features[/b] (standard modern platformer toolkit):
## - Coyote time and jump buffering
## - Variable jump height (release jump early to cut the arc)
## - Heavier gravity when falling for a snappier arc
## - Double jump, gated on the Leap Stone relic (SPEC 4.1)
## - Backdash with its own cooldown
## - Drop-through one-way platforms (Down + Jump)
##
## [b]Combat[/b]
## - Two melee hands: Attack swings the primary weapon, Secondary Attack the
##   off-hand one, each a [WeaponData] resource driven by frame data
## - Standing / crouching / aerial attack variants, the crouch shrinking both
##   the body and the hurtbox to match the sprite
## - Heart-powered sub-weapons ([SubWeaponData]) via the Sub-weapon button
##   or the classic Up + Attack input
## - Knockback, stun and blinking invincibility frames when hurt
##
## [b]What it does not own[/b][br]
## Levels, stats, gold, hearts, the inventory and what is equipped all live in
## [GameManager], because this node is thrown away and rebuilt on every room
## change and every death. The player reads through to it and mirrors only
## current HP, which [HealthComponent] needs locally.
##
## Scene contract: see `scenes/player/player.tscn` for the expected children.
class_name Player
extends CharacterBody2D

enum State { IDLE, RUN, JUMP, FALL, CROUCH, ATTACK, THROW, BACKDASH, HURT, DEAD }

## Collision layer number used by one-way platforms (see Project Settings > Layer Names).
const ONE_WAY_LAYER: int = 9
const STAND_SHAPE_SIZE: Vector2 = Vector2(10.0, 34.0)
const CROUCH_SHAPE_SIZE: Vector2 = Vector2(10.0, 22.0)
## The hurtbox is a little narrower than the body so grazes do not register.
const STAND_HURT_SIZE: Vector2 = Vector2(10.0, 30.0)
const CROUCH_HURT_SIZE: Vector2 = Vector2(10.0, 19.0)

@export_group("Movement")
@export var run_speed: float = 105.0
@export var ground_acceleration: float = 1500.0
@export var ground_friction: float = 1800.0
@export var air_acceleration: float = 950.0

@export_group("Jump")
@export var jump_velocity: float = -335.0
@export var double_jump_velocity: float = -290.0
## Vertical velocity is multiplied by this when jump is released while rising.
@export_range(0.0, 1.0) var jump_cut_multiplier: float = 0.4
@export var fall_gravity_multiplier: float = 1.3
@export var max_fall_speed: float = 380.0
@export var coyote_time: float = 0.08
@export var jump_buffer_time: float = 0.12

@export_group("Backdash")
@export var backdash_speed: float = 250.0
@export var backdash_duration: float = 0.30
@export var backdash_cooldown: float = 0.12

@export_group("Combat")
## What Vesper is carrying when a brand new game starts: weapons, sub-weapons,
## armour, rings. Handed to [method GameManager.seed_starting_loadout], which
## equips whatever has an empty slot and ignores the lot if a save was loaded.
@export var starting_loadout: Array[ItemData] = []
@export_range(0, 999) var max_mp: int = 50
## MP regenerated per second (MP is reserved for future spells / familiars).
@export var mp_regen_per_second: float = 2.0
## Knockback velocity when hurt (x is applied away from the attacker).
@export var hurt_knockback: Vector2 = Vector2(110.0, -170.0)
@export var hurt_stun_time: float = 0.35
@export var invincibility_time: float = 1.2

@onready var sprite: AnimatedSprite2D = $Sprite
@onready var body_shape: CollisionShape2D = $BodyShape
@onready var health: HealthComponent = $HealthComponent
@onready var hurtbox: Hurtbox = $Hurtbox
@onready var hurt_shape: CollisionShape2D = $Hurtbox/CollisionShape2D
@onready var weapon_hitbox: Hitbox = $WeaponHitbox
@onready var weapon_shape: CollisionShape2D = $WeaponHitbox/CollisionShape2D

var state: State = State.IDLE
## 1 = facing right, -1 = facing left.
var facing: int = 1
var mp: int = 0

## Hearts, gold, stats and equipment all live in [GameManager]; these are
## read-only windows onto it so gameplay code reads naturally.
var hearts: int:
	get:
		return GameManager.hearts
var weapon: WeaponData:
	get:
		return GameManager.get_primary_weapon()
var secondary_weapon: WeaponData:
	get:
		return GameManager.get_secondary_weapon()

var _gravity: float = ProjectSettings.get_setting("physics/2d/default_gravity")
var _coyote_timer: float = 0.0
var _jump_buffer_timer: float = 0.0
var _state_time: float = 0.0
var _backdash_cooldown_timer: float = 0.0
var _subweapon_cooldown_timer: float = 0.0
var _drop_through_timer: float = 0.0
var _mp_regen_accumulator: float = 0.0
var _has_double_jumped: bool = false
var _is_crouch_attack: bool = false
var _was_on_floor: bool = true
var _thrown_this_state: bool = false
## The hand mid-swing. Held separately from the equipped weapon so an equip
## during recovery cannot retime the frame data underneath the animation.
var _swinging: WeaponData
var _active_projectiles: Array[Node] = []
## Guards the two-way mirror between [HealthComponent] and GameManager.current_hp.
var _syncing_health: bool = false


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
func _ready() -> void:
	mp = max_mp
	weapon_hitbox.deactivate()
	hurtbox.hit_received.connect(_on_hit_received)
	weapon_hitbox.hit_landed.connect(_on_melee_hit_landed)
	health.health_changed.connect(_on_health_changed)
	sprite.frame_changed.connect(_on_sprite_frame_changed)
	sprite.animation_finished.connect(_on_sprite_animation_finished)
	Events.player_equipment_changed.connect(_on_equipment_changed)
	Events.player_stats_changed.connect(_sync_from_game_state)
	GameManager.seed_starting_loadout(starting_loadout)
	_sync_from_game_state()
	# Defer so HUD/other listeners have finished their own _ready().
	_broadcast_stats.call_deferred()


func _physics_process(delta: float) -> void:
	_update_timers(delta)
	_state_time += delta
	match state:
		State.IDLE, State.RUN:
			_state_grounded(delta)
		State.JUMP, State.FALL:
			_state_air(delta)
		State.CROUCH:
			_state_crouch(delta)
		State.ATTACK:
			_state_attack(delta)
		State.THROW:
			_state_throw(delta)
		State.BACKDASH:
			_state_backdash(delta)
		State.HURT:
			_state_hurt(delta)
		State.DEAD:
			_state_dead(delta)
	move_and_slide()
	_after_move()


func _process(_delta: float) -> void:
	# Blink while invincible (classic i-frame feedback).
	if hurtbox.is_invincible and state != State.DEAD:
		sprite.modulate.a = 0.35 if int(Time.get_ticks_msec() / 60.0) % 2 == 0 else 1.0
	else:
		sprite.modulate.a = 1.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
## Add hearts (sub-weapon ammo), clamped to the current maximum.
func add_hearts(amount: int) -> void:
	GameManager.add_hearts(amount)


## Restore HP.
func heal(amount: int) -> void:
	health.heal(amount)


## Currently equipped sub-weapon, or null.
func get_current_subweapon() -> SubWeaponData:
	return GameManager.get_subweapon()


## True while Vesper may double jump: the Leap Stone has to have been found.
func can_double_jump() -> bool:
	return GameManager.has_ability(GameManager.ABILITY_DOUBLE_JUMP)


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------
func _state_grounded(delta: float) -> void:
	_apply_gravity(delta)
	var input_x: float = _move_input()

	if not is_on_floor():
		_coyote_timer = coyote_time
		_change_state(State.FALL)
		return
	if _try_common_actions():
		return
	if _is_holding_down():
		_change_state(State.CROUCH)
		return

	_update_facing(input_x)
	_move_horizontal(input_x * run_speed, ground_acceleration if input_x != 0.0 else ground_friction, delta)
	if absf(velocity.x) > 5.0 or input_x != 0.0:
		_set_state_silently(State.RUN)
		_play(&"run")
	else:
		_set_state_silently(State.IDLE)
		_play(&"idle")


func _state_air(delta: float) -> void:
	var input_x: float = _move_input()
	_apply_gravity(delta)

	# Variable jump height.
	if state == State.JUMP and velocity.y < 0.0 and not Input.is_action_pressed(&"jump"):
		velocity.y *= jump_cut_multiplier
		_change_state(State.FALL)

	if is_on_floor():
		_land()
		return
	if _jump_buffer_timer > 0.0:
		if _coyote_timer > 0.0:
			_start_jump(jump_velocity)
			return
		if can_double_jump() and not _has_double_jumped:
			_has_double_jumped = true
			_start_jump(double_jump_velocity)
			_play_somersault()
			return
	if _try_attack_or_throw():
		return

	_update_facing(input_x)
	_move_horizontal(input_x * run_speed, air_acceleration, delta)
	if state == State.JUMP and velocity.y >= 0.0:
		_change_state(State.FALL)
	_play(&"jump" if velocity.y < 0.0 else &"fall")


func _state_crouch(delta: float) -> void:
	_apply_gravity(delta)
	_move_horizontal(0.0, ground_friction, delta)
	if not is_on_floor():
		_change_state(State.FALL)
		return
	if _consume_jump_buffer():
		if _is_on_one_way_floor():
			_drop_through_platform()
		else:
			_start_jump(jump_velocity)
		return
	if _try_attack_or_throw():
		return
	if Input.is_action_just_pressed(&"backdash") and _backdash_cooldown_timer <= 0.0:
		_change_state(State.BACKDASH)
		return
	if not _is_holding_down():
		_change_state(State.IDLE)
		return
	_update_facing(_move_input())
	_play(&"crouch")


func _state_attack(delta: float) -> void:
	_apply_gravity(delta)
	if is_on_floor():
		_move_horizontal(0.0, ground_friction, delta)
	else:
		# Aerial attacks keep momentum but allow drift; no turning mid-swing.
		var input_x: float = _move_input()
		_move_horizontal(input_x * run_speed, air_acceleration, delta)


func _state_throw(delta: float) -> void:
	_state_attack(delta)


func _state_backdash(delta: float) -> void:
	_apply_gravity(delta)
	var t: float = clampf(_state_time / backdash_duration, 0.0, 1.0)
	velocity.x = -facing * backdash_speed * (1.0 - t * t)
	if _consume_jump_buffer() and is_on_floor():
		_start_jump(jump_velocity)
		return
	if _state_time >= backdash_duration:
		_backdash_cooldown_timer = backdash_cooldown
		_change_state(State.IDLE if is_on_floor() else State.FALL)


func _state_hurt(delta: float) -> void:
	_apply_gravity(delta)
	if is_on_floor() and _state_time > 0.05:
		_move_horizontal(0.0, ground_friction, delta)
	if _state_time >= hurt_stun_time and is_on_floor():
		_change_state(State.IDLE)


func _state_dead(delta: float) -> void:
	_apply_gravity(delta)
	_move_horizontal(0.0, ground_friction, delta)


# ---------------------------------------------------------------------------
# State machine plumbing
# ---------------------------------------------------------------------------
func _change_state(new_state: State) -> void:
	if new_state == state:
		return
	_exit_state(state)
	state = new_state
	_state_time = 0.0
	_enter_state(new_state)


## Swap between states that share behaviour (IDLE <-> RUN) without enter/exit.
func _set_state_silently(new_state: State) -> void:
	state = new_state


func _enter_state(new_state: State) -> void:
	match new_state:
		State.CROUCH:
			_set_crouch_shape(true)
		State.ATTACK:
			_is_crouch_attack = is_on_floor() and _is_holding_down()
			_set_crouch_shape(_is_crouch_attack)
			sprite.speed_scale = _swinging.speed_scale if _swinging else 1.0
			_play(_attack_animation(), true)
			Audio.play_sfx(_swinging.swing_sfx if _swinging else &"sword_swing", 0.08)
		State.THROW:
			_thrown_this_state = false
			_play(&"throw", true)
		State.BACKDASH:
			_play(&"backdash", true)
			Audio.play_sfx(&"backdash")
		State.HURT:
			_play(&"hurt", true)
		State.DEAD:
			_play(&"death", true)


func _exit_state(old_state: State) -> void:
	match old_state:
		State.CROUCH:
			_set_crouch_shape(false)
		State.ATTACK:
			weapon_hitbox.deactivate()
			sprite.speed_scale = 1.0
			_set_crouch_shape(false)
			_swinging = null


## Actions available from any grounded, non-crouching state.
func _try_common_actions() -> bool:
	if _consume_jump_buffer():
		_start_jump(jump_velocity)
		return true
	if _try_attack_or_throw():
		return true
	if Input.is_action_just_pressed(&"switch_subweapon"):
		GameManager.cycle_subweapon()
	if Input.is_action_just_pressed(&"backdash") and _backdash_cooldown_timer <= 0.0:
		_change_state(State.BACKDASH)
		return true
	return false


func _try_attack_or_throw() -> bool:
	var wants_throw: bool = Input.is_action_just_pressed(&"subweapon") \
		or (Input.is_action_just_pressed(&"attack") and _is_holding_up())
	if wants_throw and _can_throw_subweapon():
		_change_state(State.THROW)
		return true
	if Input.is_action_just_pressed(&"subweapon"):
		Audio.play_sfx(&"no_hearts")  # Dedicated button pressed but can't throw.
		return false
	if Input.is_action_just_pressed(&"attack") and weapon != null:
		return _start_swing(weapon)
	if Input.is_action_just_pressed(&"attack_secondary") and secondary_weapon != null:
		return _start_swing(secondary_weapon)
	return false


## Begin a melee swing with [param with]. Returns true if the state changed.
func _start_swing(with: WeaponData) -> bool:
	_swinging = with
	_change_state(State.ATTACK)
	return true


# ---------------------------------------------------------------------------
# Reading the stick
#
# An analog stick is read as a *direction*, not a speed. The classics run at
# one pace, and half-speed creeping would fight the run cycle, so anything
# past the deadzone means "run" — exactly like the d-pad or a key.
# ---------------------------------------------------------------------------
## -1, 0 or 1. (Drop the [method signf] for analog creep speeds.)
func _move_input() -> float:
	return signf(Input.get_axis(&"move_left", &"move_right"))


## True while the player means "down" rather than "run, with the stick
## happening to sit a little low". Without the comparison, running with a
## stick pushed down-forward would crouch; on a d-pad or keyboard both axes
## read 1.0, so holding Down + Right still crouches like it always did.
func _is_holding_down() -> bool:
	var down: float = Input.get_action_strength(&"move_down")
	return down > 0.0 and down >= absf(Input.get_axis(&"move_left", &"move_right"))


## Same rule for "up", which arms the classic Up + Attack sub-weapon throw:
## a stick tilted up-forward while attacking should swing, not throw.
func _is_holding_up() -> bool:
	var up: float = Input.get_action_strength(&"move_up")
	return up > 0.0 and up >= absf(Input.get_axis(&"move_left", &"move_right"))


# ---------------------------------------------------------------------------
# Movement helpers
# ---------------------------------------------------------------------------
func _apply_gravity(delta: float) -> void:
	var multiplier: float = fall_gravity_multiplier if velocity.y > 0.0 else 1.0
	# Gravity is applied even on the floor so floor collisions are reported
	# every frame (needed by the one-way platform check).
	velocity.y = minf(velocity.y + _gravity * multiplier * delta, max_fall_speed)


func _move_horizontal(target_speed: float, rate: float, delta: float) -> void:
	velocity.x = move_toward(velocity.x, target_speed, rate * delta)


func _update_facing(input_x: float) -> void:
	if input_x != 0.0:
		facing = 1 if input_x > 0.0 else -1
		sprite.flip_h = facing < 0


func _start_jump(v: float) -> void:
	velocity.y = v
	_coyote_timer = 0.0
	_jump_buffer_timer = 0.0
	Audio.play_sfx(&"jump", 0.1)
	# Force a re-enter so the jump arc logic resets even when already airborne.
	if state == State.JUMP:
		_state_time = 0.0
	else:
		_change_state(State.JUMP)


func _land() -> void:
	_has_double_jumped = false
	sprite.rotation = 0.0
	_change_state(State.IDLE)


func _play_somersault() -> void:
	var tween: Tween = create_tween()
	sprite.rotation = 0.0
	tween.tween_property(sprite, "rotation", TAU * facing, 0.3)
	tween.tween_callback(func() -> void: sprite.rotation = 0.0)


func _consume_jump_buffer() -> bool:
	if _jump_buffer_timer > 0.0:
		_jump_buffer_timer = 0.0
		return true
	return false


func _update_timers(delta: float) -> void:
	if Input.is_action_just_pressed(&"jump"):
		_jump_buffer_timer = jump_buffer_time
	else:
		_jump_buffer_timer = maxf(0.0, _jump_buffer_timer - delta)
	_coyote_timer = maxf(0.0, _coyote_timer - delta)
	_backdash_cooldown_timer = maxf(0.0, _backdash_cooldown_timer - delta)
	_subweapon_cooldown_timer = maxf(0.0, _subweapon_cooldown_timer - delta)

	if _drop_through_timer > 0.0:
		_drop_through_timer -= delta
		if _drop_through_timer <= 0.0:
			set_collision_mask_value(ONE_WAY_LAYER, true)

	if mp < max_mp and state != State.DEAD:
		_mp_regen_accumulator += mp_regen_per_second * delta
		if _mp_regen_accumulator >= 1.0:
			var gained: int = int(_mp_regen_accumulator)
			_mp_regen_accumulator -= gained
			mp = mini(max_mp, mp + gained)
			Events.player_mp_changed.emit(mp, max_mp)


func _after_move() -> void:
	var on_floor: bool = is_on_floor()
	if on_floor and not _was_on_floor:
		Audio.play_sfx(&"land", 0.1, -4.0)
	_was_on_floor = on_floor


## Shrink (or restore) the body and the hurtbox together, so crouching really
## does duck under things rather than only looking like it (SPEC 4.1).
func _set_crouch_shape(crouching: bool) -> void:
	_resize(body_shape, CROUCH_SHAPE_SIZE if crouching else STAND_SHAPE_SIZE)
	_resize(hurt_shape, CROUCH_HURT_SIZE if crouching else STAND_HURT_SIZE)


## Resize a rectangle collision shape and keep its bottom edge on the feet.
func _resize(shape: CollisionShape2D, size: Vector2) -> void:
	var rect_shape := shape.shape as RectangleShape2D
	if rect_shape == null:
		return
	rect_shape.size = size
	shape.position.y = -size.y * 0.5


# ---------------------------------------------------------------------------
# One-way platforms
# ---------------------------------------------------------------------------
func _is_on_one_way_floor() -> bool:
	var one_way_bit: int = 1 << (ONE_WAY_LAYER - 1)
	for i: int in get_slide_collision_count():
		var collision: KinematicCollision2D = get_slide_collision(i)
		if collision.get_normal().dot(Vector2.UP) < 0.7:
			continue
		var layer: int = PhysicsServer2D.body_get_collision_layer(collision.get_collider_rid())
		if layer & one_way_bit:
			return true
	return false


func _drop_through_platform() -> void:
	set_collision_mask_value(ONE_WAY_LAYER, false)
	_drop_through_timer = 0.25
	position.y += 1.0
	_change_state(State.FALL)


# ---------------------------------------------------------------------------
# Combat
# ---------------------------------------------------------------------------
func _on_sprite_frame_changed() -> void:
	match state:
		State.ATTACK:
			if _swinging == null:
				return
			if _swinging.is_frame_active(sprite.frame):
				if not weapon_hitbox.is_active:
					_configure_weapon_hitbox()
					weapon_hitbox.activate()
			elif weapon_hitbox.is_active:
				weapon_hitbox.deactivate()
		State.THROW:
			if sprite.frame == 1 and not _thrown_this_state:
				_thrown_this_state = true
				_spawn_subweapon()


func _on_sprite_animation_finished() -> void:
	if state in [State.ATTACK, State.THROW]:
		if is_on_floor():
			_change_state(State.CROUCH if _is_holding_down() else State.IDLE)
		else:
			_change_state(State.FALL)


## Attack animation for the swinging weapon in the current stance. Weapons
## that ship no variant of their own fall back to the default swing.
func _attack_animation() -> StringName:
	var airborne: bool = not is_on_floor()
	if _swinging == null:
		return &"attack"
	var anim: StringName = _swinging.get_attack_animation(_is_crouch_attack, airborne)
	if sprite.sprite_frames != null and not sprite.sprite_frames.has_animation(anim):
		push_warning("Weapon '%s' has no '%s' animation; using the default swing."
			% [_swinging.display_name, anim])
		if _is_crouch_attack:
			return &"attack_crouch"
		return &"attack_air" if airborne else &"attack"
	return anim


func _configure_weapon_hitbox() -> void:
	var rect_shape := weapon_shape.shape as RectangleShape2D
	rect_shape.size = _swinging.hitbox_size
	var offset: Vector2 = _swinging.crouch_hitbox_offset if _is_crouch_attack else _swinging.hitbox_offset
	weapon_shape.position = Vector2(offset.x * facing, offset.y)
	weapon_hitbox.damage = _swinging.damage
	weapon_hitbox.attack_power = GameManager.get_strength()
	weapon_hitbox.knockback_force = _swinging.knockback


func _can_throw_subweapon() -> bool:
	var sub: SubWeaponData = get_current_subweapon()
	if sub == null or sub.projectile_scene == null or hearts < sub.heart_cost:
		return false
	if _subweapon_cooldown_timer > 0.0:
		return false
	_active_projectiles.assign(_active_projectiles.filter(func(n: Node) -> bool: return is_instance_valid(n)))
	return _active_projectiles.size() < sub.max_active


func _spawn_subweapon() -> void:
	var sub: SubWeaponData = get_current_subweapon()
	if sub == null:
		return
	var projectile := sub.projectile_scene.instantiate() as Projectile
	if projectile == null:
		push_error("Sub-weapon '%s' scene root must be a Projectile." % sub.display_name)
		return
	add_hearts(-sub.heart_cost)
	_subweapon_cooldown_timer = sub.cooldown
	projectile.global_position = global_position + Vector2(sub.spawn_offset.x * facing, sub.spawn_offset.y)
	# Projectiles live in the world, not under the player, so they don't
	# move with us. The player's parent is the room's actor container.
	get_parent().add_child(projectile)
	projectile.launch(facing)
	# A sub-weapon with its own base damage overrides the projectile scene's,
	# so the same scene can serve a starter dagger and a late-game one.
	if sub.damage > 0:
		projectile.hitbox.damage = sub.damage
	projectile.hitbox.attack_power = GameManager.get_strength()
	projectile.hitbox.hit_landed.connect(_on_weapon_hit_landed.bind(0.03))
	_active_projectiles.append(projectile)
	Audio.play_sfx(sub.throw_sfx)


func _on_melee_hit_landed(_hurtbox: Hurtbox) -> void:
	# Hit-stop length is a per-weapon tuning value (heavier weapons = longer).
	var stop_time: float = _swinging.hit_stop if _swinging else 0.05
	GameFeel.hit_stop(stop_time)
	GameFeel.impact_rumble(stop_time)


func _on_weapon_hit_landed(_hurtbox: Hurtbox, stop_time: float) -> void:
	GameFeel.hit_stop(stop_time)
	GameFeel.impact_rumble(stop_time)


func _on_hit_received(hitbox: Hitbox) -> void:
	if state == State.DEAD:
		return
	var dealt: int = health.take_damage(
		Combat.compute_damage(hitbox.damage, hitbox.attack_power, GameManager.get_defense()))
	Events.damage_dealt.emit(dealt, global_position + Vector2(0, -40), true)
	if health.is_dead:
		_die()
		return
	Audio.play_sfx(&"player_hurt")
	GameFeel.hit_stop(0.06)
	GameFeel.shake(3.0, 0.2)
	var dir: float = hitbox.get_knockback_direction(global_position)
	facing = -int(dir)  # Turn to face the attacker, like the classics.
	sprite.flip_h = facing < 0
	velocity = Vector2(hurt_knockback.x * dir, hurt_knockback.y)
	_change_state(State.HURT)
	hurtbox.start_invincibility(invincibility_time)


func _die() -> void:
	_change_state(State.DEAD)
	hurtbox.disable()
	velocity = Vector2(0.0, -120.0)
	Audio.play_sfx(&"player_death", 0.0)
	GameFeel.shake(5.0, 0.4)
	Events.player_died.emit()


# ---------------------------------------------------------------------------
# Equipment & stats
# ---------------------------------------------------------------------------
## Finishing a swing under a weapon that has just been swapped out would put
## its hitbox on the wrong frames, so cancel anything in progress.
func _on_equipment_changed(slot: int, _item: ItemData) -> void:
	if slot != GameManager.Slot.PRIMARY_WEAPON and slot != GameManager.Slot.SECONDARY_WEAPON:
		return
	if state == State.ATTACK:
		_change_state(State.IDLE if is_on_floor() else State.FALL)
	else:
		weapon_hitbox.deactivate()


## Mirror [GameManager]'s HP and Constitution into the local health component.
## Runs on level-ups, equipment changes, saves and loads.
func _sync_from_game_state() -> void:
	var stored_hp: int = GameManager.current_hp
	_syncing_health = true
	health.max_health = GameManager.get_max_hp()
	health.current_health = 0 if state == State.DEAD else clampi(stored_hp, 0, health.max_health)
	_syncing_health = false
	Events.player_health_changed.emit(health.current_health, health.max_health)


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------
func _play(anim: StringName, restart: bool = false) -> void:
	if restart or sprite.animation != anim:
		sprite.play(anim)
		if restart:
			sprite.frame = 0


func _on_health_changed(current: int, maximum: int) -> void:
	if not _syncing_health:
		GameManager.current_hp = current
	Events.player_health_changed.emit(current, maximum)


func _broadcast_stats() -> void:
	Events.player_health_changed.emit(health.current_health, health.max_health)
	Events.player_mp_changed.emit(mp, max_mp)
	Events.player_hearts_changed.emit(GameManager.hearts, GameManager.max_hearts)
	Events.player_gold_changed.emit(GameManager.gold)
	Events.player_experience_changed.emit(
		GameManager.stats.experience, GameManager.stats.xp_to_next_level(), GameManager.stats.level)
	Events.player_weapon_changed.emit(weapon)
	Events.player_subweapon_changed.emit(get_current_subweapon())
