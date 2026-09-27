## Run in separate processes with --prepare, then --continue, then --new-game.
## Uses its own directory, never normal player slots.
extends Node

var _failures: int = 0


func _ready() -> void:
	SaveManager.save_directory = "user://tests/cold_start"
	DirAccess.make_dir_recursive_absolute(SaveManager.save_directory)
	get_tree().create_timer(15.0, true, false, true).timeout.connect(
		func() -> void: get_tree().quit(1))
	_run.call_deferred()


func _check(ok: bool, message: String) -> void:
	if not ok:
		_failures += 1
	print("  [%s] %s" % ["ok" if ok else "FAIL", message])


func _run() -> void:
	var args: PackedStringArray = OS.get_cmdline_user_args()
	if args.has("--prepare"):
		for slot: int in SaveManager.SLOT_COUNT:
			SaveManager.delete_slot(slot)
		GameManager.start_new_game()
		GameManager.add_gold(777)
		GameManager.add_item(ItemDB.get_item(&"ruby_ring"))
		GameManager.equip(GameManager.Slot.RING_1, ItemDB.get_item(&"ruby_ring"))
		GameManager.add_item(ItemDB.get_item(&"leap_stone"))
		GameManager.collect_world_item(&"hall_leap_stone")
		GameManager.set_checkpoint(&"crimson_hall", Vector2(104, 256))
		_check(SaveManager.save_to_slot(1), "saved run for the next process")
	elif args.has("--continue") or args.has("--new-game"):
		_check(GameManager.gold == 0, "fresh process begins without prior in-memory progress")
		var main_path: String = ProjectSettings.get_setting("application/run/main_scene")
		var scene := load(main_path) as PackedScene
		var title := scene.instantiate() as TitleMenu
		_check(title != null, "application entry point is the title screen")
		if title == null:
			get_tree().quit(1)
			return
		get_tree().root.add_child(title)
		get_tree().current_scene = title
		if args.has("--new-game"):
			await _send(&"move_down")
		# Confirm through the same input path used by the keyboard/controller.
		await _send(&"attack")
		await get_tree().process_frame
		await get_tree().process_frame
		var player := get_tree().get_first_node_in_group(&"player") as Player
		_check(player != null, "title enters gameplay")
		_check(player != null and player.state != Player.State.ATTACK
			and player.state != Player.State.JUMP, "title confirmation does not trigger a gameplay action")
		if args.has("--continue"):
			_check(GameManager.gold == 777 and GameManager.current_slot == 1,
				"Continue restores the disk save across processes")
			_check(GameManager.get_equipped(GameManager.Slot.RING_1) == ItemDB.get_item(&"ruby_ring"),
				"saved equipment survives player instantiation")
			_check(player != null and player.can_double_jump(), "saved ability restored")
			_check(player != null and player.global_position.distance_to(Vector2(104, 256)) < 2.0,
				"saved checkpoint restored")
			_check(get_tree().current_scene.get_node_or_null("World/CastleHall/WorldItems/hall_leap_stone") == null,
				"collected world item stays absent")
		else:
			_check(GameManager.gold == 0 and GameManager.current_slot == -1,
				"New Game starts a fresh run")
			_check(SaveManager.get_slot_info(1).gold == 777, "New Game preserves existing disk saves")
			_check(player != null and player.weapon != null, "New Game seeds starting equipment")
			for slot: int in SaveManager.SLOT_COUNT:
				SaveManager.delete_slot(slot)
	else:
		_check(false, "pass --prepare, --continue, or --new-game")
	Audio.stop_music(0.0)
	for child: Node in Audio.get_children():
		if child is AudioStreamPlayer:
			child.stop()
	await get_tree().create_timer(0.2, true, false, true).timeout
	for i: int in 4:
		await get_tree().process_frame
	print("COLD START TEST: %d failures" % _failures)
	get_tree().quit(1 if _failures else 0)


func _send(action: StringName) -> void:
	var event := InputEventAction.new()
	event.action = action
	event.pressed = true
	Input.parse_input_event(event)
	await get_tree().process_frame
	event = InputEventAction.new()
	event.action = action
	event.pressed = false
	Input.parse_input_event(event)
	await get_tree().process_frame
