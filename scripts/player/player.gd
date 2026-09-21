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
## - Double jump (an unlockable ability flag)
## - Backdash with its own cooldown
## - Drop-through one-way platforms (Down + Jump)
##
## [b]Combat[/b]
## - Melee attacks defined by a [WeaponData] resource using frame data
## - Standing / crouching / aerial attack variants
## - Heart-powered sub-weapons ([SubWeaponData]) via the Sub-weapon button
##   or the classic Up + Attack input
## - Knockback, stun and blinking invincibility frames when hurt
##
## Scene contract: see `scenes/player/player.tscn` for the expected children.
class_name Player
extends CharacterBody2D

enum State { IDLE, RUN, JUMP, FALL, CROUCH, ATTACK, THROW, BACKDASH, HURT, DEAD }

## Collision layer number used by one-way platforms (see Project Settings > Layer Names).
const ONE_WAY_LAYER: int = 9
const STAND_SHAPE_SIZE: Vector2 = Vector2(10.0, 34.0)
const CROUCH_SHAPE_SIZE: Vector2 = Vector2(10.0, 22.0)

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
## Ability unlock flag (think "Leap Stone"). Toggle to gate progression.
@export var can_double_jump: bool = true

@export_group("Backdash")
@export var backdash_speed: float = 220.0
@export var backdash_duration: float = 0.22
@export var backdash_cooldown: float = 0.12

@export_group("Combat")
@export var weapon: WeaponData
@export var subweapons: Array[SubWeaponData] = []
@export_range(0, 999) var starting_hearts: int = 10
@export_range(0, 999) var max_hearts: int = 99
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
@onready var weapon_hitbox: Hitbox = $WeaponHitbox
@onready var weapon_shape: CollisionShape2D = $WeaponHitbox/CollisionShape2D

var state: State = State.IDLE
## 1 = facing right, -1 = facing left.
var facing: int = 1
var hearts: int = 0
var mp: int = 0
var subweapon_index: int = 0

var _gravity: float = ProjectSettings.get_setting("physics/2d/default_gravity")
var _coyote_timer: float = 0.0
var _jump_buffer_timer: float = 0.0
var _state_time: float = 0.0
var _backdash_cooldown_timer: float = 0.0
var _drop_through_timer: float = 0.0
var _mp_regen_accumulator: float = 0.0
var _has_double_jumped: bool = false
var _is_crouch_attack: bool = false
var _was_on_floor: bool = true
var _thrown_this_state: bool = false
var _active_projectiles: Array[Node] = []


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
func _ready() -> void:
	hearts = starting_hearts
	mp = max_mp
	weapon_hitbox.deactivate()
	hurtbox.hit_received.connect(_on_hit_received)
	weapon_hitbox.hit_landed.connect(_on_melee_hit_landed)
	health.health_changed.connect(_on_health_changed)
	sprite.frame_changed.connect(_on_sprite_frame_changed)
	sprite.animation_finished.connect(_on_sprite_animation_finished)
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
## Add hearts (sub-weapon ammo), clamped to [member max_hearts].
func add_hearts(amount: int) -> void:
	hearts = clampi(hearts + amount, 0, max_hearts)
	Events.player_hearts_changed.emit(hearts)


## Restore HP.
func heal(amount: int) -> void:
	health.heal(amount)


## Currently equipped sub-weapon, or null.
func get_current_subweapon() -> SubWeaponData:
	if subweapons.is_empty():
		return null
	return subweapons[subweapon_index % subweapons.size()]


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------
func _state_grounded(delta: float) -> void:
	_apply_gravity(delta)
	var input_x: float = Input.get_axis(&"move_left", &"move_right")

	if not is_on_floor():
		_coyote_timer = coyote_time
		_change_state(State.FALL)
		return
	if _try_common_actions():
		return
	if Input.is_action_pressed(&"move_down"):
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
	var input_x: float = Input.get_axis(&"move_left", &"move_right")
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
		if can_double_jump and not _has_double_jumped:
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
	if not Input.is_action_pressed(&"move_down"):
		_change_state(State.IDLE)
		return
	_update_facing(Input.get_axis(&"move_left", &"move_right"))
	_play(&"crouch")


func _state_attack(delta: float) -> void:
	_apply_gravity(delta)
	if is_on_floor():
		_move_horizontal(0.0, ground_friction, delta)
	else:
		# Aerial attacks keep momentum but allow drift; no turning mid-swing.
		var input_x: float = Input.get_axis(&"move_left", &"move_right")
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
			_is_crouch_attack = is_on_floor() and Input.is_action_pressed(&"move_down")
			_set_crouch_shape(_is_crouch_attack)
			var anim: StringName = &"attack"
			if _is_crouch_attack:
				anim = &"attack_crouch"
			elif not is_on_floor():
				anim = &"attack_air"
			sprite.speed_scale = weapon.speed_scale if weapon else 1.0
			_play(anim, true)
			Audio.play_sfx(weapon.swing_sfx if weapon else &"sword_swing", 0.08)
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


## Actions available from any grounded, non-crouching state.
func _try_common_actions() -> bool:
	if _consume_jump_buffer():
		_start_jump(jump_velocity)
		return true
	if _try_attack_or_throw():
		return true
	if Input.is_action_just_pressed(&"switch_subweapon"):
		_cycle_subweapon()
	if Input.is_action_just_pressed(&"backdash") and _backdash_cooldown_timer <= 0.0:
		_change_state(State.BACKDASH)
		return true
	return false


func _try_attack_or_throw() -> bool:
	var wants_throw: bool = Input.is_action_just_pressed(&"subweapon") \
		or (Input.is_action_just_pressed(&"attack") and Input.is_action_pressed(&"move_up"))
	if wants_throw and _can_throw_subweapon():
		_change_state(State.THROW)
		return true
	if Input.is_action_just_pressed(&"subweapon"):
		Audio.play_sfx(&"no_hearts")  # Dedicated button pressed but can't throw.
		return false
	if Input.is_action_just_pressed(&"attack") and weapon != null:
		_change_state(State.ATTACK)
		return true
	return false


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


func _set_crouch_shape(crouching: bool) -> void:
	var rect_shape := body_shape.shape as RectangleShape2D
	var size: Vector2 = CROUCH_SHAPE_SIZE if crouching else STAND_SHAPE_SIZE
	rect_shape.size = size
	body_shape.position.y = -size.y * 0.5


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
			if weapon == null:
				return
			if weapon.is_frame_active(sprite.frame):
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
			_change_state(State.CROUCH if Input.is_action_pressed(&"move_down") else State.IDLE)
		else:
			_change_state(State.FALL)


func _configure_weapon_hitbox() -> void:
	var rect_shape := weapon_shape.shape as RectangleShape2D
	rect_shape.size = weapon.hitbox_size
	var offset: Vector2 = weapon.crouch_hitbox_offset if _is_crouch_attack else weapon.hitbox_offset
	weapon_shape.position = Vector2(offset.x * facing, offset.y)
	weapon_hitbox.damage = weapon.damage
	weapon_hitbox.knockback_force = weapon.knockback


func _can_throw_subweapon() -> bool:
	var sub: SubWeaponData = get_current_subweapon()
	if sub == null or sub.projectile_scene == null or hearts < sub.heart_cost:
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
	projectile.global_position = global_position + Vector2(sub.spawn_offset.x * facing, sub.spawn_offset.y)
	# Projectiles live in the world, not under the player, so they don't
	# move with us. The player's parent is the room's actor container.
	get_parent().add_child(projectile)
	projectile.launch(facing)
	projectile.hitbox.hit_landed.connect(_on_weapon_hit_landed.bind(0.03))
	_active_projectiles.append(projectile)
	Audio.play_sfx(sub.throw_sfx)


func _cycle_subweapon() -> void:
	if subweapons.size() < 2:
		return
	subweapon_index = (subweapon_index + 1) % subweapons.size()
	Events.player_subweapon_changed.emit(get_current_subweapon())


func _on_melee_hit_landed(_hurtbox: Hurtbox) -> void:
	# Hit-stop length is a per-weapon tuning value (heavier weapons = longer).
	GameFeel.hit_stop(weapon.hit_stop if weapon else 0.05)


func _on_weapon_hit_landed(_hurtbox: Hurtbox, stop_time: float) -> void:
	GameFeel.hit_stop(stop_time)


func _on_hit_received(hitbox: Hitbox) -> void:
	if state == State.DEAD:
		return
	var dealt: int = health.take_damage(hitbox.damage)
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
# Presentation
# ---------------------------------------------------------------------------
func _play(anim: StringName, restart: bool = false) -> void:
	if restart or sprite.animation != anim:
		sprite.play(anim)
		if restart:
			sprite.frame = 0


func _on_health_changed(current: int, maximum: int) -> void:
	Events.player_health_changed.emit(current, maximum)


func _broadcast_stats() -> void:
	Events.player_health_changed.emit(health.current_health, health.max_health)
	Events.player_mp_changed.emit(mp, max_mp)
	Events.player_hearts_changed.emit(hearts)
	Events.player_subweapon_changed.emit(get_current_subweapon())
