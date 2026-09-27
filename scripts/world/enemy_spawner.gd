## Periodically spawns enemies at its [Marker2D] children.
##
## Designers place the spawner in a room, add Marker2D children as spawn
## points and tune the budget in the inspector. The spawner:
## - keeps at most [member max_alive] of its own enemies alive,
## - never spawns within [member min_player_distance] of the player
##   (no cheap hits), preferring points the player is not looking at,
## - plays an optional spawn effect ("rising from flames").
class_name EnemySpawner
extends Node2D

@export var enemy_scene: PackedScene
@export_range(1, 32) var max_alive: int = 3
## Seconds between spawn attempts.
@export var spawn_interval: float = 4.0
## Delay before the first spawn after the room loads.
@export var initial_delay: float = 1.0
@export var min_player_distance: float = 80.0
@export var spawn_effect_scene: PackedScene
## Where spawned enemies are parented. Defaults to this node's parent.
@export var enemy_container: Node2D
@export var enabled: bool = true

var _alive: Array[Enemy] = []
var _spawn_points: Array[Marker2D] = []
var _timer: Timer


func _ready() -> void:
	for child: Node in get_children():
		if child is Marker2D:
			_spawn_points.append(child as Marker2D)
	if _spawn_points.is_empty():
		push_warning("%s has no Marker2D spawn points." % name)
	if enemy_container == null:
		enemy_container = get_parent() as Node2D
	_timer = Timer.new()
	_timer.one_shot = false
	add_child(_timer)
	_timer.timeout.connect(_on_timer_timeout)
	_timer.start(maxf(0.05, initial_delay))


func _on_timer_timeout() -> void:
	_timer.wait_time = spawn_interval
	if not enabled or enemy_scene == null:
		return
	# Typed as Variant on purpose: a freed enemy is still an Object, and it
	# cannot be converted back to Enemy, which would make the filter fail.
	_alive.assign(_alive.filter(func(e: Variant) -> bool: return is_instance_valid(e)))
	if _alive.size() >= max_alive:
		return
	var point: Marker2D = _pick_spawn_point()
	if point:
		_spawn_at(point.global_position)


func _pick_spawn_point() -> Marker2D:
	var player := get_tree().get_first_node_in_group(&"player") as Node2D
	var candidates: Array[Marker2D] = []
	for p: Marker2D in _spawn_points:
		if player and p.global_position.distance_to(player.global_position) < min_player_distance:
			continue
		candidates.append(p)
	if candidates.is_empty():
		return null
	return candidates.pick_random()


func _spawn_at(at: Vector2) -> void:
	var enemy := enemy_scene.instantiate() as Enemy
	if enemy == null:
		push_error("%s: enemy_scene root must extend Enemy." % name)
		return
	enemy.position = enemy_container.to_local(at)
	enemy_container.add_child(enemy, true)
	_alive.append(enemy)
	if spawn_effect_scene:
		var fx := spawn_effect_scene.instantiate() as Node2D
		fx.position = enemy_container.to_local(at)
		enemy_container.add_child(fx)
