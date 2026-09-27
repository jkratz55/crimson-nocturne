## Bone-throwing skeleton.
##
## Patrols back and forth, turning at walls and ledges. When the player is
## within [member detection_range] it turns to face them and lobs a bone
## in an arc, then resumes patrolling after [member throw_cooldown].
class_name Skeleton
extends Enemy

enum AIState { WALK, THROW }

@export var walk_speed: float = 26.0
## Horizontal / vertical distance at which the skeleton notices the player.
@export var detection_range: Vector2 = Vector2(150.0, 48.0)
@export var throw_cooldown: float = 2.4
@export var bone_scene: PackedScene
## Where the bone spawns relative to the feet (facing right).
@export var bone_spawn_offset: Vector2 = Vector2(6.0, -34.0)

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
	if ai_state == AIState.THROW and sprite.animation == &"attack" and sprite.frame == 2 and not _has_thrown:
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
	# Getting hit interrupts a throw wind-up.
	if ai_state == AIState.THROW and not _has_thrown:
		ai_state = AIState.WALK
		_throw_timer = throw_cooldown * 0.5
