## Bone-throwing skeleton.
##
## Patrols back and forth, turning at walls and ledges. When the player is
## within [member detection_range] it turns to face them and lobs a bone
## in an arc, then resumes patrolling after [member throw_cooldown].
##
## On death it breaks apart the SotN way: six bone pieces fly off away from
## the blow, spinning, and each bursts into a small flame after its own delay.
class_name Skeleton
extends Enemy

enum AIState { WALK, THROW }

## Frame of the "attack" animation on which the bone leaves the hand. The
## frames before it are the interruptible wind-up (startup 15 ticks = 0.25 s);
## it must match ATTACK_RELEASE_FRAME in tools/asset_pipeline/enemies.py.
const THROW_RELEASE_FRAME: int = 3

## Death pieces, one row per animation in [member part_frames] (values from
## assets/sprites/skeleton_parts.json, which enemies.py writes): where each
## piece's centre sits relative to the feet (facing right), its launch
## velocity in px/s (+x = away from the blow), spin in degrees per tick and
## the tick it bursts on. The staggered bursts are the point.
const PART_NAMES: Array[StringName] = [&"skull", &"ribcage", &"pelvis", &"arm", &"leg_a", &"leg_b"]
const PART_ATTACH: Array[Vector2] = [
	Vector2(5, -37), Vector2(1, -31), Vector2(-1, -22), Vector2(5, -23), Vector2(3, -11), Vector2(-1, -11)]
const PART_VELOCITY: Array[Vector2] = [
	Vector2(45, -300), Vector2(105, -180), Vector2(90, -120), Vector2(60, -180), Vector2(120, -240),
	Vector2(105, -52.5)]
const PART_SPIN_DEG_PER_TICK: Array[float] = [22.5, 11.25, 6.3, 2.8, 5.6, 1.4]
const PART_POP_TICKS: Array[float] = [48.0, 32.0, 20.0, 12.0, 24.0, 16.0]

@export var walk_speed: float = 26.0
## Horizontal / vertical distance at which the skeleton notices the player.
@export var detection_range: Vector2 = Vector2(150.0, 48.0)
@export var throw_cooldown: float = 2.4
@export var bone_scene: PackedScene
## Where the bone spawns relative to the feet (facing right).
@export var bone_spawn_offset: Vector2 = Vector2(6.0, -34.0)

@export_group("Death")
## One single-frame animation per piece (see [constant PART_NAMES]). Without
## it the skeleton falls back to the plain death flame.
@export var part_frames: SpriteFrames = preload("res://resources/sprite_frames/skeleton_parts_frames.tres")
## The small fire puff each piece bursts into.
@export var part_pop_scene: PackedScene = preload("res://scenes/fx/fire_pop.tscn")

@onready var ledge_ray: RayCast2D = $LedgeRay

var ai_state: AIState = AIState.WALK
var _throw_timer: float = 1.0
var _has_thrown: bool = false


func _ready() -> void:
	super._ready()
	sprite.frame_changed.connect(_on_frame_changed)
	sprite.animation_finished.connect(_on_animation_finished)
	_set_facing(-1 if randf() < 0.5 else 1)
	sprite.play(&"walk")


func _ai_process(delta: float) -> void:
	_throw_timer = maxf(0.0, _throw_timer - delta)
	match ai_state:
		AIState.WALK:
			_walk()
		AIState.THROW:
			velocity.x = move_toward(velocity.x, 0.0, 400.0 * delta)


func _walk() -> void:
	if is_on_floor() and (is_on_wall() or not ledge_ray.is_colliding()):
		_set_facing(-facing)
	velocity.x = facing * walk_speed
	if sprite.animation != &"walk":
		sprite.play(&"walk")

	if _throw_timer <= 0.0 and bone_scene and has_live_target() and is_on_floor():
		var to_player: Vector2 = target.global_position - global_position
		if absf(to_player.x) <= detection_range.x and absf(to_player.y) <= detection_range.y:
			_set_facing(1 if to_player.x > 0.0 else -1)
			_start_throw()


func _start_throw() -> void:
	ai_state = AIState.THROW
	_has_thrown = false
	sprite.play(&"attack")


func _set_facing(dir: int) -> void:
	super._set_facing(dir)
	if is_node_ready():
		ledge_ray.position.x = absf(ledge_ray.position.x) * facing


func _on_frame_changed() -> void:
	if ai_state == AIState.THROW and sprite.animation == &"attack" and sprite.frame == THROW_RELEASE_FRAME \
			and not _has_thrown:
		_has_thrown = true
		var bone := bone_scene.instantiate() as Projectile
		get_parent().add_child(bone)
		bone.global_position = global_position + Vector2(bone_spawn_offset.x * facing, bone_spawn_offset.y)
		bone.hitbox.attack_power = attack_power
		bone.launch(facing)
		Audio.play_sfx(&"bone_throw")


func _on_animation_finished() -> void:
	if sprite.animation == &"attack":
		ai_state = AIState.WALK
		_throw_timer = throw_cooldown * randf_range(0.8, 1.3)


func _on_hurt(_hitbox: Hitbox) -> void:
	# Getting hit interrupts a throw wind-up (gameplay, unchanged).
	#
	# Visual only: a skeleton that was already walking flinches; _walk()
	# resumes "walk" once the stun ends. The "attack" animation is never
	# replaced, so an interrupted wind-up (or a throw past its release, or a
	# second hit while an interrupted wind-up is still playing out) runs on
	# exactly as before the flinch existed, and its animation_finished still
	# re-rolls the cooldown. The AI timing and the global RNG draws are the
	# same as without the flinch on every path.
	var interrupted: bool = ai_state == AIState.THROW and not _has_thrown
	if interrupted:
		ai_state = AIState.WALK
		_throw_timer = throw_cooldown * 0.5
	elif ai_state == AIState.WALK and sprite.animation != &"attack" \
			and sprite.sprite_frames.has_animation(&"hurt"):
		sprite.play(&"hurt")


## Visual only (see [method Enemy._spawn_death_visuals]): the break-apart.
func _spawn_death_visuals() -> void:
	if part_frames == null or get_parent() == null:
		super._spawn_death_visuals()
		return
	var away: float = _death_push_direction()
	var flash_shader: Shader = null
	var own := sprite.material as ShaderMaterial
	if own != null:
		flash_shader = own.shader
	for i: int in PART_NAMES.size():
		var part_name: StringName = PART_NAMES[i]
		if not part_frames.has_animation(part_name):
			continue
		var part := BonePart.new()
		part.texture = part_frames.get_frame_texture(part_name, 0)
		part.flip_h = facing < 0
		part.velocity = Vector2(PART_VELOCITY[i].x * away, PART_VELOCITY[i].y)
		part.spin_speed = deg_to_rad(PART_SPIN_DEG_PER_TICK[i] * 60.0) * away
		part.life = PART_POP_TICKS[i] / 60.0
		part.pop_scene = part_pop_scene
		part.floor_y = global_position.y
		part.z_index = z_index
		if flash_shader != null:
			var mat := ShaderMaterial.new()
			mat.shader = flash_shader
			part.material = mat
		get_parent().add_child(part)
		part.global_position = global_position + Vector2(PART_ATTACH[i].x * facing, PART_ATTACH[i].y)
