## Headless smoke test: boots the main scene, drives the player with
## simulated input and asserts the core loop works.
##
## Run from the project root (it is a scene, not a --script SceneTree, so
## autoloads such as Events/Audio are registered before gameplay scripts compile):
##   godot --headless --path . res://tests/smoke_test.tscn
##
## Exit code 0 = all checks passed, 1 = at least one failure. Suitable for CI.
extends Node

var _failures: int = 0
var _main: Node
var _player: Player


func _ready() -> void:
	_run.call_deferred()


func _run() -> void:
	_main = (load("res://scenes/main.tscn") as PackedScene).instantiate()
	add_child(_main)
	await _frames(10)

	_player = get_tree().get_first_node_in_group(&"player") as Player
	_check(_player != null, "player exists and is in the 'player' group")
	var room := _main.get_node("World/CastleHall") as Room
	_check(room != null and room.camera != null and room.player == _player, "room exports (camera, player) resolved")
	var ground := room.get_node("Tiles") as TileMapLayer
	_check(ground.get_used_cells().size() > 200, "ground tilemap decoded (%d cells)" % ground.get_used_cells().size())

	# --- Landing on the floor -------------------------------------------------
	await _seconds(0.6)
	_check(_player.is_on_floor(), "player rests on the floor")
	_check(absf(_player.global_position.y - 256.0) < 2.0, "player feet at floor height (y=%.1f)" % _player.global_position.y)

	# --- Running ------------------------------------------------------------------
	var start_x: float = _player.global_position.x
	Input.action_press(&"move_right")
	await _seconds(0.5)
	Input.action_release(&"move_right")
	_check(_player.global_position.x > start_x + 30.0, "player runs right (%.1f -> %.1f)" % [start_x, _player.global_position.x])

	# --- Jumping ------------------------------------------------------------------
	var floor_y: float = _player.global_position.y
	await _tap(&"jump", 0.25)
	_check(_player.global_position.y < floor_y - 20.0, "player jumps (y=%.1f)" % _player.global_position.y)
	await _seconds(1.0)
	_check(_player.is_on_floor(), "player lands again")

	# --- Attack -------------------------------------------------------------------
	await _tap(&"attack", 0.03)
	await _frames(2)
	_check(_player.state == Player.State.ATTACK, "attack state entered")
	await _seconds(0.5)
	_check(_player.state != Player.State.ATTACK, "attack recovers to neutral")

	# --- Sub-weapon ---------------------------------------------------------------
	var hearts_before: int = _player.hearts
	await _tap(&"subweapon", 0.03)
	await _seconds(0.4)
	_check(_player.hearts == hearts_before - 1, "dagger costs 1 heart (%d -> %d)" % [hearts_before, _player.hearts])
	await _tap(&"switch_subweapon", 0.03)
	_check(_player.get_current_subweapon().display_name == "Axe", "sub-weapon cycles to Axe")

	# --- Backdash -----------------------------------------------------------------
	await _seconds(0.3)
	var bx: float = _player.global_position.x
	await _tap(&"backdash", 0.03)
	await _seconds(0.3)
	_check(_player.global_position.x < bx - 10.0, "backdash moves backwards (%.1f -> %.1f)" % [bx, _player.global_position.x])

	# --- Enemies spawn and can be killed -----------------------------------------
	await _seconds(6.0)
	var enemies: Array[Node] = get_tree().get_nodes_in_group(&"enemies")
	_check(enemies.size() > 0, "spawners produced enemies (%d alive)" % enemies.size())
	var kills: Array[int] = [0]
	Events.enemy_killed.connect(func(_e: Enemy) -> void: kills[0] += 1)
	for e: Node in enemies:
		var enemy := e as Enemy
		enemy.health.take_damage(9999)
	await _frames(5)
	_check(kills[0] == enemies.size(), "enemies die and report kills (%d)" % kills[0])

	# --- Hit-stop always recovers (regression: time scale used to get stuck) ----
	GameFeel.hit_stop(0.05)
	GameFeel.hit_stop(0.02)
	await get_tree().create_timer(0.3, true, false, true).timeout
	_check(is_equal_approx(Engine.time_scale, 1.0), "hit-stop releases time scale (%.2f)" % Engine.time_scale)

	# --- Taking damage ------------------------------------------------------------
	var hp_before: int = _player.health.current_health
	var fake_hit := Hitbox.new()
	fake_hit.damage = 7
	_player.add_child(fake_hit)
	_player.hurtbox.hit_received.emit(fake_hit)
	await _frames(2)
	_check(_player.health.current_health == hp_before - 7, "player takes damage")
	_check(_player.hurtbox.is_invincible, "player gets i-frames after a hit")

	print("")
	print("SMOKE TEST %s (%d failure(s))" % ["PASSED" if _failures == 0 else "FAILED", _failures])
	GameFeel.clear_hit_stop()
	get_tree().quit(1 if _failures > 0 else 0)


func _check(condition: bool, label: String) -> void:
	print(("  [ok]   " if condition else "  [FAIL] ") + label)
	if not condition:
		_failures += 1


func _tap(action: StringName, hold: float) -> void:
	Input.action_press(action)
	await _seconds(hold)
	Input.action_release(action)


func _frames(count: int) -> void:
	for i: int in count:
		await get_tree().physics_frame


func _seconds(duration: float) -> void:
	await get_tree().create_timer(duration, true, true).timeout
