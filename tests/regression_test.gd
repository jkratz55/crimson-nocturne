## Regressions for save validation, durable writes, death and projectile impact.
extends Node

var _failures: int = 0
var _checks: int = 0


func _ready() -> void:
	SaveManager.save_directory = "user://tests/regression_%d" % OS.get_process_id()
	DirAccess.make_dir_recursive_absolute(SaveManager.save_directory)
	get_tree().create_timer(30.0, true, false, true).timeout.connect(
		func() -> void: get_tree().quit(1))
	_run.call_deferred()


func _run() -> void:
	_test_invalid_saves()
	_test_equipment()
	_test_atomic_save()
	await _test_death()
	await _test_projectile()
	await _test_title()
	Audio.stop_music(0.0)
	for child: Node in Audio.get_children():
		if child is AudioStreamPlayer:
			child.stop()
	await get_tree().create_timer(0.2, true, false, true).timeout
	for i: int in 4:
		await get_tree().process_frame
	print("REGRESSION TESTS: %d checks, %d failures" % [_checks, _failures])
	get_tree().quit(1 if _failures else 0)


func _check(ok: bool, label: String) -> void:
	_checks += 1
	if not ok:
		_failures += 1
	print("  [%s] %s" % ["ok" if ok else "FAIL", label])


func _write_payload(payload: Variant) -> void:
	var file := FileAccess.open(SaveManager.slot_path(0), FileAccess.WRITE)
	file.store_string(JSON.stringify(payload))
	file.close()


func _test_invalid_saves() -> void:
	GameManager.start_new_game()
	GameManager.add_gold(100)
	var original: Dictionary = GameManager.to_save_data()
	var payload: Dictionary = {"format_version": 1, "saved_at": 1, "data": original.duplicate(true)}
	for invalid: Variant in [{"unrelated": true}, [],
		{"format_version": 99, "saved_at": 1, "data": original},
		{"format_version": 1, "saved_at": 1, "data": []}]:
		_write_payload(invalid)
		_check(not SaveManager.load_from_slot(0), "invalid envelope rejected")
		_check(GameManager.to_save_data() == original and GameManager.current_slot == -1,
			"rejected save leaves run and slot untouched")
	for field: String in ["stats", "inventory", "consumables", "equipped", "checkpoint_position",
		"gold", "checkpoint_room"]:
		var broken: Dictionary = payload.duplicate(true)
		broken.data[field] = [null] if field != "inventory" else [7]
		_write_payload(broken)
		_check(not SaveManager.load_from_slot(0), "wrong type rejected: " + field)
		_check(GameManager.to_save_data() == original, "validation is transactional")
	_check(not GameManager.apply_save_data({"gold": 12, "consumables": []})
		and GameManager.to_save_data() == original, "direct application validates before mutation")
	_write_payload({"format_version": 1, "saved_at": 1, "data": {"stats": {"level": 2}, "gold": 7}})
	_check(SaveManager.load_from_slot(0) and GameManager.gold == 7, "older partial saves retain defaults")
	SaveManager.delete_slot(0)


func _test_equipment() -> void:
	GameManager.apply_save_data({"inventory": ["ruby_ring", "ruby_ring"],
		"equipped": {"5": "ruby_ring", "6": "ruby_ring", "0": "short_sword", "3": "ruby_ring"}})
	_check(GameManager.get_strength() == 8, "loaded duplicate ring contributes only once")
	_check(GameManager.inventory.size() == 1, "loaded inventory is unique")
	_check(GameManager.get_primary_weapon() == null, "unowned weapon is not equipped")
	_check(GameManager.get_equipped(GameManager.Slot.ARMOR) == null, "wrong slot is not equipped")
	GameManager.apply_save_data({"inventory": ["ghost_item"], "equipped": {"0": "ghost_item"}})
	_check(GameManager.inventory.is_empty(), "removed content is skipped safely")


func _test_atomic_save() -> void:
	GameManager.start_new_game()
	GameManager.add_gold(20)
	_check(SaveManager.save_to_slot(0), "first save written")
	var original: PackedByteArray = FileAccess.get_file_as_bytes(SaveManager.slot_path(0))
	GameManager.add_gold(10)
	_check(SaveManager.save_to_slot(0), "second generation written")
	_check(FileAccess.get_file_as_bytes(SaveManager.slot_path(0) + ".bak") == original,
		"previous generation preserved byte for byte")
	_write_payload({"bad": true})
	_check(SaveManager.load_from_slot(0) and GameManager.gold == 20, "corrupt primary recovers backup")
	SaveManager.delete_slot(0)
	_check(not SaveManager.get_slot_info(0).exists, "deleting a slot also removes recovery files")
	GameManager.add_gold(10)
	_check(SaveManager.save_to_slot(0), "valid primary restored")
	original = FileAccess.get_file_as_bytes(SaveManager.slot_path(0))
	# A directory at the temporary path simulates inability to create a file.
	DirAccess.make_dir_absolute(SaveManager.slot_path(0) + ".tmp")
	GameManager.current_slot = -1
	var saved_signals: Array[int] = [0]
	var on_saved: Callable = func(_slot: int) -> void: saved_signals[0] += 1
	Events.game_saved.connect(on_saved)
	_check(not SaveManager.save_to_slot(0), "failed temporary write reports failure")
	_check(GameManager.current_slot == -1 and saved_signals[0] == 0,
		"failed write does not commit slot or announce success")
	_check(FileAccess.get_file_as_bytes(SaveManager.slot_path(0)) == original,
		"failed write preserves previous slot")
	Events.game_saved.disconnect(on_saved)
	DirAccess.remove_absolute(SaveManager.slot_path(0) + ".tmp")
	# Fail backup installation after a successful temporary write.
	DirAccess.make_dir_absolute(SaveManager.slot_path(0) + ".bak")
	_check(not SaveManager.save_to_slot(0), "backup replacement failure aborts save")
	_check(FileAccess.get_file_as_bytes(SaveManager.slot_path(0)) == original,
		"backup failure also preserves primary")
	DirAccess.remove_absolute(SaveManager.slot_path(0) + ".bak")
	SaveManager.delete_slot(0)


func _test_death() -> void:
	GameManager.start_new_game()
	var actor := preload("res://scenes/player/player.tscn").instantiate() as Player
	add_child(actor)
	actor.set_physics_process(false)
	var hitbox := Hitbox.new()
	hitbox.damage = 999
	add_child(hitbox)
	actor._on_hit_received(hitbox)
	GameManager.add_experience(50)
	_check(actor.state == Player.State.DEAD and actor.health.current_health == 0
		and GameManager.current_hp == 0, "posthumous level-up does not revive player")
	GameManager.equip(GameManager.Slot.PRIMARY_WEAPON, null)
	_check(actor.state == Player.State.DEAD and actor.health.current_health == 0,
		"equipment stat changes cannot revive player")
	GameManager.respawn()
	_check(actor.state == Player.State.DEAD, "old body stays dead while respawn prepares new body")
	actor.queue_free()
	hitbox.queue_free()
	await get_tree().process_frame
	var replacement := preload("res://scenes/player/player.tscn").instantiate() as Player
	add_child(replacement)
	_check(replacement.state != Player.State.DEAD and replacement.health.current_health == GameManager.get_max_hp(),
		"replacement player spawns alive with full HP")
	replacement.queue_free()
	GameFeel.clear_hit_stop()
	await get_tree().process_frame


func _test_projectile() -> void:
	var world := Node2D.new()
	world.position = Vector2(100, 50)
	add_child(world)
	var dagger := preload("res://scenes/projectiles/dagger.tscn").instantiate() as Projectile
	world.add_child(dagger)
	dagger.position = Vector2(20, 30)
	var first := Hurtbox.new()
	var second := Hurtbox.new()
	world.add_child(first)
	world.add_child(second)
	dagger.hitbox.register_hit(first)
	_check(not dagger.hitbox.can_hit(second), "impacted dagger cannot hit a second target")
	dagger._impact()
	await get_tree().process_frame
	await get_tree().process_frame
	_check(world.get_child_count() == 3, "repeated impact creates only one effect")
	var effect := world.get_child(2) as Node2D
	_check(effect != null and effect.global_position == Vector2(120, 80), "impact respects transformed parent")
	var axe := preload("res://scenes/projectiles/axe.tscn").instantiate() as Projectile
	world.add_child(axe)
	axe.hitbox.register_hit(first)
	_check(axe.hitbox.can_hit(second) and not axe.hitbox.can_hit(first), "piercing still hits each target once")
	world.queue_free()
	await get_tree().process_frame


func _test_title() -> void:
	GameManager.start_new_game()
	GameManager.add_gold(321)
	GameManager.set_checkpoint(&"crimson_hall", Vector2(104, 256))
	SaveManager.save_to_slot(1)
	GameManager.start_new_game()
	var title := preload("res://scenes/ui/title_menu.tscn").instantiate() as TitleMenu
	get_tree().root.add_child(title)
	get_tree().current_scene = title
	_check(not GameManager.is_processing(), "title suspends play-time tracking")
	title._load_slot(2)
	_check(not title._starting and GameManager.gold == 0, "empty slot stays on title without changing run")
	# Exercise the Load Slot menu and its confirm path.
	title._row = 2
	title._confirm()
	_check(title._choosing_slot, "Load Slot opens the picker")
	title._row = 1
	title._confirm()
	await get_tree().process_frame
	await get_tree().process_frame
	var player := get_tree().get_first_node_in_group(&"player") as Player
	_check(player != null and GameManager.gold == 321 and GameManager.current_slot == 1,
		"title loads run before instantiating gameplay")
	_check(player.global_position.distance_to(Vector2(104, 256)) < 2.0, "loaded player begins at saved shrine")
	var save_menu := get_tree().current_scene.get_node("SaveMenu") as SaveMenu
	player.health.take_damage(10)
	var hp_before: int = player.health.current_health
	var checkpoint_before: Vector2 = GameManager.checkpoint_position
	save_menu.open(&"crimson_hall", Vector2(200, 256))
	_check(save_menu._row == 1, "save menu defaults to the active run's slot")
	DirAccess.make_dir_absolute(SaveManager.slot_path(1) + ".tmp")
	save_menu._commit()
	_check(save_menu.is_open and not save_menu._committing, "failed save permits retry")
	_check(GameManager.checkpoint_position == checkpoint_before and player.health.current_health == hp_before,
		"failed shrine save restores prior checkpoint and HP")
	save_menu.close()
	DirAccess.remove_absolute(SaveManager.slot_path(1) + ".tmp")
	SaveManager.delete_slot(1)
