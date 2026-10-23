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
	SaveManager.save_directory = "user://tests/smoke_test_%d" % OS.get_process_id()
	DirAccess.make_dir_recursive_absolute(SaveManager.save_directory)
	get_tree().create_timer(90.0, true, false, true).timeout.connect(
		func() -> void:
			push_error("Test watchdog timed out.")
			get_tree().quit(1))
	_run.call_deferred()


func _run() -> void:
	seed(12345)
	_main = (load("res://scenes/main.tscn") as PackedScene).instantiate()
	add_child(_main)
	await _frames(10)

	_player = get_tree().get_first_node_in_group(&"player") as Player
	_check(_player != null, "player exists and is in the 'player' group")
	var room := _main.get_node("World/CastleHall") as Room
	_check(room != null and room.camera != null and room.player == _player, "room exports (camera, player) resolved")
	# Keep the relic isolated until its own scenario; earlier knockback and
	# movement checks can cross its position.
	var relic := room.get_node("WorldItems/hall_leap_stone") as WorldItem
	relic.set_deferred(&"monitoring", false)
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
	var blade: WeaponSprite = _player.weapon_sprite
	_check(blade.visible and blade.sprite_frames == _player.weapon.weapon_frames,
		"the sword is drawn over the bare-handed swing")
	_check(_blade_in_step(), "and holds the body's frame (%s %d)" % [blade.animation, blade.frame])
	await _frames(5)
	_check(_player.sprite.frame > 0 and _blade_in_step(),
		"frame for frame through the swing (%s %d)" % [blade.animation, blade.frame])
	await _seconds(0.5)
	_check(_player.state != Player.State.ATTACK, "attack recovers to neutral")
	_check(not blade.visible, "the sword is put away after the swing")

	# --- Sub-weapon ---------------------------------------------------------------
	var hearts_before: int = _player.hearts
	await _tap(&"subweapon", 0.03)
	await _seconds(0.4)
	_check(_player.hearts == hearts_before - 1, "dagger costs 1 heart (%d -> %d)" % [hearts_before, _player.hearts])
	await _tap(&"switch_subweapon", 0.03)
	_check(_player.get_current_subweapon().display_name == "Axe", "sub-weapon cycles to Axe")
	# The classic Up + Attack throw has to survive the "is up the dominant
	# direction?" rule that keeps a tilted stick from throwing by accident.
	await _seconds(0.4)
	var hearts_up: int = _player.hearts
	Input.action_press(&"move_up")
	await _tap(&"attack", 0.03)
	await _seconds(0.4)
	Input.action_release(&"move_up")
	_check(_player.hearts < hearts_up, "Up + Attack throws the sub-weapon (%d -> %d)"
		% [hearts_up, _player.hearts])

	# --- ... and fails quietly with no hearts left --------------------------
	await _seconds(0.4)
	var hearts_saved: int = _player.hearts
	GameManager.add_hearts(-hearts_saved)
	_check(_player.hearts == 0, "heart pool emptied")
	await _tap(&"subweapon", 0.03)
	await _frames(4)
	_check(_player.state != Player.State.THROW, "a throw with no hearts does not start")
	_check(_player.hearts == 0, "and costs nothing")
	GameManager.add_hearts(hearts_saved)
	_check(_player.hearts == hearts_saved, "hearts restored for the rest of the run")
	await _seconds(0.3)

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
	fake_hit.damage = 20
	fake_hit.attack_power = 4
	_player.add_child(fake_hit)
	_player.hurtbox.hit_received.emit(fake_hit)
	await _frames(2)
	# 20 base + floor(4/2) - floor(DEF/2), +/-10%: the exact number is rolled.
	var expected: Vector2i = Combat.damage_range(20, 4, GameManager.get_defense())
	var taken: int = hp_before - _player.health.current_health
	_check(taken >= expected.x and taken <= expected.y,
		"damage follows the formula (%d in %d..%d)" % [taken, expected.x, expected.y])
	_check(_player.hurtbox.is_invincible, "player gets i-frames after a hit")
	_check(_player.state == Player.State.HURT, "and is knocked into the hurt state")
	_check(_player.velocity != Vector2.ZERO, "with knockback applied (%.0f, %.0f)"
		% [_player.velocity.x, _player.velocity.y])

	# --- Crouching shrinks the hurtbox, not just the sprite ----------------
	# The hit above knocked him into the air; wait out the stun and the landing.
	await _seconds(1.0)
	var hurt_rect := _player.hurt_shape.shape as RectangleShape2D
	var standing_height: float = hurt_rect.size.y
	Input.action_press(&"move_down")
	await _seconds(0.2)
	_check(_player.state == Player.State.CROUCH, "player crouches")
	_check(hurt_rect.size.y < standing_height,
		"crouching shrinks the hurtbox (%.0f -> %.0f px)" % [standing_height, hurt_rect.size.y])
	Input.action_release(&"move_down")
	await _seconds(0.2)
	_check(is_equal_approx(hurt_rect.size.y, standing_height), "standing restores it")

	# --- Pause menu: equipping the whip in the main hand -------------------
	var menu := _main.get_node("PauseMenu") as PauseMenu
	_check(GameManager.items_for_slot(GameManager.Slot.PRIMARY_WEAPON).size() == 2,
		"player carries two melee weapons")
	_check(_player.weapon.display_name == "Short Sword", "short sword in the main hand on spawn")
	_check(_player.secondary_weapon != null and _player.secondary_weapon.display_name == "Crimson Lash",
		"the whip starts in the off hand")
	await _send_action(&"pause_menu")
	_check(menu.is_open and get_tree().paused, "pause menu opens and pauses the game")
	# Right hand -> the carried column -> past "- REMOVE -" to the whip.
	await _send_action(&"attack")
	await _send_action(&"move_down")
	await _send_action(&"move_down")
	await _send_action(&"attack")
	_check(_player.weapon.display_name == "Crimson Lash",
		"menu equips the whip (%s)" % _player.weapon.display_name)
	await _send_action(&"attack_secondary")
	_check(menu._tab == PauseMenu.Tab.STATS, "the shoulder button pages to the stats tab")
	var stats_rows := menu.get_node("Root/Panel/Stats/StatsLeft") as VBoxContainer
	_check(stats_rows.get_child_count() > 0, "the stats tab drew its rows")
	await _send_action(&"switch_subweapon")
	_check(menu._tab == PauseMenu.Tab.EQUIPMENT, "and pages back")
	await _send_action(&"pause_menu")
	_check(not menu.is_open and not get_tree().paused, "pause menu closes and resumes the game")

	# --- The whip swings its own animation ---------------------------------
	await _seconds(0.3)
	await _tap(&"attack", 0.03)
	await _frames(2)
	_check(_player.sprite.animation == &"attack_whip", "whip plays its own swing (%s)" % _player.sprite.animation)
	_check(not _player.weapon_sprite.visible, "with no blade drawn over its lash")
	await _seconds(0.1)
	var whip_shape := _player.weapon_shape.shape as RectangleShape2D
	_check(is_equal_approx(whip_shape.size.x, 46.0), "whip hitbox is the long one (%.0f px)" % whip_shape.size.x)
	await _seconds(0.6)
	Input.action_press(&"move_down")
	await _tap(&"attack", 0.03)
	await _frames(2)
	_check(_player.sprite.animation == &"attack_whip_crouch",
		"crouching whip swing (%s)" % _player.sprite.animation)
	Input.action_release(&"move_down")
	await _seconds(0.6)
	await _tap(&"jump", 0.12)
	await _seconds(0.12)
	await _tap(&"attack", 0.03)
	await _frames(2)
	_check(_player.sprite.animation == &"attack_whip_air",
		"aerial whip swing (%s)" % _player.sprite.animation)
	await _seconds(1.0)

	# --- ... and reaches further than the sword ----------------------------
	for e: Node in get_tree().get_nodes_in_group(&"enemies"):
		e.queue_free()
	_player.hurtbox.disable()  # no stray i-frame timer left pending at exit
	Input.action_press(&"move_right")
	await _seconds(0.1)
	Input.action_release(&"move_right")
	await _seconds(0.4)
	var hits: Array[int] = [0]
	var target := _spawn_test_target(_player.global_position + Vector2(50.0, -30.0))
	target.hit_received.connect(func(_hitbox: Hitbox) -> void: hits[0] += 1)
	GameManager.equip(GameManager.Slot.PRIMARY_WEAPON, ItemDB.get_item(&"short_sword"))
	await _tap(&"attack", 0.03)
	await _seconds(0.5)
	_check(hits[0] == 0, "sword falls short of a target 50px away")
	GameManager.equip(GameManager.Slot.PRIMARY_WEAPON, ItemDB.get_item(&"crimson_lash"))
	await _tap(&"attack", 0.03)
	await _seconds(0.7)
	_check(hits[0] == 1, "whip reaches it (%d hit(s))" % hits[0])

	# --- The off hand swings on its own button -----------------------------
	GameManager.equip(GameManager.Slot.SECONDARY_WEAPON, ItemDB.get_item(&"short_sword"))
	await _seconds(0.4)
	await _tap(&"attack_secondary", 0.03)
	await _frames(2)
	_check(_player.state == Player.State.ATTACK, "secondary attack enters the attack state")
	_check(_player.sprite.animation == &"attack",
		"and swings the off-hand weapon's animation (%s)" % _player.sprite.animation)
	await _seconds(0.5)
	target.queue_free()
	await _frames(2)

	# --- Experience, levelling and gold ------------------------------------
	var xp_before: int = GameManager.stats.experience
	var level_before: int = GameManager.stats.level
	var skeleton := (load("res://scenes/enemies/skeleton.tscn") as PackedScene).instantiate() as Enemy
	skeleton.gold_drop_chance = 1.0   # make the random drop deterministic
	_player.get_parent().add_child(skeleton)
	skeleton.global_position = _player.global_position + Vector2(200.0, -40.0)
	await _frames(2)
	var reward: int = skeleton.experience
	skeleton.health.take_damage(9999)
	await _frames(3)
	_check(GameManager.stats.experience == xp_before + reward
		or GameManager.stats.level > level_before,
		"killing an enemy banks its experience (+%d)" % reward)
	var coins: int = 0
	for node: Node in _player.get_parent().get_children():
		var pickup := node as Pickup
		if pickup != null and pickup.kind == Pickup.Kind.GOLD:
			coins += 1
	_check(coins > 0, "a guaranteed gold roll dropped a coin")

	var gold_before: int = GameManager.gold
	GameManager.add_gold(250)
	_check(GameManager.gold == gold_before + 250, "gold is tracked")

	# Enough experience to cross a level boundary, whatever level we are at.
	var hp_max_before: int = GameManager.get_max_hp()
	_player.health.take_damage(30)
	await _frames(2)
	_check(_player.health.current_health < hp_max_before, "Vesper is wounded going in")
	var levels: int = GameManager.add_experience(PlayerStats.xp_for_level(GameManager.stats.level))
	await _frames(2)
	_check(levels >= 1, "enough experience levels Vesper up")
	_check(GameManager.get_max_hp() > hp_max_before,
		"the level-up raised max HP (%d -> %d)" % [hp_max_before, GameManager.get_max_hp()])
	_check(_player.health.current_health == GameManager.get_max_hp(), "and healed him to full")
	_check(_player.health.max_health == GameManager.get_max_hp(), "the health component tracked it")

	# --- A unique world item, and the ability it unlocks --------------------
	_check(is_instance_valid(relic), "the Leap Stone is in the room")
	_check(not GameManager.has_ability(GameManager.ABILITY_DOUBLE_JUMP),
		"the double jump starts locked")
	_check(not _player.can_double_jump(), "so the player refuses it")
	if not is_instance_valid(relic):
		get_tree().quit(1)
		return
	relic.set_deferred(&"monitoring", true)
	_player.global_position = relic.global_position
	await _frames(4)
	_check(GameManager.has_ability(GameManager.ABILITY_DOUBLE_JUMP),
		"walking onto the relic unlocks the double jump")
	_check(_player.can_double_jump(), "and the player honours it")
	_check(GameManager.is_world_item_collected(&"hall_leap_stone"),
		"the pickup is recorded so it never respawns")
	await _frames(2)
	_check(not is_instance_valid(relic), "and the node removed itself")

	# --- Saving at the shrine ----------------------------------------------
	var save_menu := _main.get_node("SaveMenu") as SaveMenu
	var slot: int = SaveManager.SLOT_COUNT - 1
	var had_save: bool = SaveManager.has_save(slot)
	var backup := PackedByteArray()
	if had_save:
		backup = FileAccess.get_file_as_bytes(SaveManager.slot_path(slot))
		SaveManager.delete_slot(slot)

	var shrine := room.get_node("SavePoint") as SavePoint
	_check(shrine != null, "the room has a save shrine")
	GameManager.add_hearts(-5)
	_player.health.take_damage(20)
	await _frames(2)
	Events.save_point_activated.emit(shrine._room_id(), shrine.global_position)
	await _frames(3)
	_check(save_menu.is_open and get_tree().paused, "the shrine opens the slot picker")
	for i: int in slot:
		await _send_action(&"move_down")
	await _send_action(&"attack")
	await _seconds(1.4)
	_check(not save_menu.is_open and not get_tree().paused, "it closes again after writing")
	_check(SaveManager.has_save(slot), "slot %d was written" % (slot + 1))
	_check(GameManager.checkpoint_room == room.room_id, "the shrine became the checkpoint")
	_check(GameManager.hearts == GameManager.max_hearts, "saving refilled the heart pool")
	_check(_player.health.current_health == GameManager.get_max_hp(), "and restored HP to full")

	# Reloading it must bring the same run back.
	var saved_gold: int = GameManager.gold
	var saved_level: int = GameManager.stats.level
	GameManager.add_gold(9999)
	_check(SaveManager.load_from_slot(slot), "the slot loads back")
	await _frames(2)
	_check(GameManager.gold == saved_gold and GameManager.stats.level == saved_level,
		"and restores the run as it was (%dG, LV %d)" % [GameManager.gold, GameManager.stats.level])

	# Respawn: the room puts the player back on the shrine, refilled.
	_player.global_position = _player.global_position + Vector2(-80.0, 0.0)
	GameManager.current_hp = 5
	GameManager.respawn()
	await _frames(2)
	_check(room.place_player_at_checkpoint(), "the room knows where to put him back")
	_check(_player.global_position.distance_to(GameManager.checkpoint_position) < 1.0,
		"and stands him on the shrine")
	_check(_player.health.current_health == GameManager.get_max_hp(),
		"respawning costs nothing but the walk back")

	SaveManager.delete_slot(slot)
	if had_save:
		var restore := FileAccess.open(SaveManager.slot_path(slot), FileAccess.WRITE)
		restore.store_buffer(backup)
		restore.close()

	# --- Controller: prompts, sticks and hot-plugging -----------------------
	_check(not Controls.is_using_pad(), "prompts start on the keyboard")
	var device_changes: Array[int] = [0]
	Controls.device_changed.connect(func(_d: Controls.Device) -> void: device_changes[0] += 1)

	var jump_y: float = _player.global_position.y
	await _send_pad_button(JOY_BUTTON_A)
	_check(Controls.is_using_pad(), "pad input switches the prompts to the pad")
	_check(device_changes[0] == 1, "the device change is announced once")
	await _seconds(0.2)
	_check(_player.global_position.y < jump_y - 15.0, "the pad's bottom face button jumps")
	await _seconds(1.0)

	# Sticks are read as directions, and a diagonal must not read as crouch.
	var run_x: float = _player.global_position.x
	_send_pad_axis(JOY_AXIS_LEFT_X, 0.8)
	await _seconds(0.4)
	_check(_player.global_position.x > run_x + 20.0, "the left stick runs (%.1f -> %.1f)"
		% [run_x, _player.global_position.x])
	_send_pad_axis(JOY_AXIS_LEFT_Y, 0.6)
	await _frames(4)
	_check(_player.state != Player.State.CROUCH, "running with the stick tilted low does not crouch")
	_send_pad_axis(JOY_AXIS_LEFT_X, 0.0)
	await _frames(6)
	_check(_player.state == Player.State.CROUCH, "pushing the stick down does crouch")
	_send_pad_axis(JOY_AXIS_LEFT_Y, 0.0)
	await _frames(4)

	# The same button has different names on different pads.
	Controls.force_device(Controls.Device.PLAYSTATION)
	_check(Controls.get_action_label(&"attack") == "SQUARE"
		and Controls.get_action_label(&"jump") == "CROSS"
		and Controls.get_action_label(&"pause") == "OPTIONS", "PlayStation prompts")
	Controls.force_device(Controls.Device.XBOX)
	_check(Controls.get_action_label(&"attack") == "X"
		and Controls.get_action_label(&"jump") == "A"
		and Controls.get_action_label(&"pause_menu") == "BACK", "Xbox prompts")

	# The menu advertises the pad's buttons and backs out with B / Circle.
	await _send_action(&"pause_menu")
	var hint := menu.get_node("Root/Panel/Hint") as Label
	_check(menu.is_open and hint.text.contains("A EQUIP") and hint.text.contains("B CLOSE"),
		"menu hint names the pad's buttons (%s)" % hint.text)
	await _send_pad_button(JOY_BUTTON_B)
	_check(not menu.is_open and not get_tree().paused, "B / Circle backs out of the menu")

	# Rumble must be a harmless no-op with no pad attached.
	Controls.rumble(0.5, 0.5, 0.1)
	GameFeel.impact_rumble(0.08)
	_check(not Controls.has_pad(), "rumble is a no-op when no pad is connected")

	# Losing the pad mid-fight freezes the game instead of stranding the player.
	Controls.pad_disconnected.emit()
	await _frames(2)
	var pause_label := _main.get_node("Overlay/PauseLabel") as Label
	_check(get_tree().paused and pause_label.visible and pause_label.text == "CONTROLLER DISCONNECTED",
		"losing the pad pauses and says so")
	await _send_action(&"pause")
	_check(not get_tree().paused, "the game resumes after the pad is back")
	Controls.auto_detect_device()

	# Stop the music so its stream is released before the engine shuts down.
	Audio.stop_music(0.0)
	await _frames(3)

	print("")
	print("SMOKE TEST %s (%d failure(s))" % ["PASSED" if _failures == 0 else "FAILED", _failures])
	GameFeel.clear_hit_stop()
	get_tree().quit(1 if _failures > 0 else 0)


func _check(condition: bool, label: String) -> void:
	print(("  [ok]   " if condition else "  [FAIL] ") + label)
	if not condition:
		_failures += 1


## The weapon overlay shows exactly what the body shows: animation, frame, facing.
func _blade_in_step() -> bool:
	var blade: WeaponSprite = _player.weapon_sprite
	return blade.visible and blade.animation == _player.sprite.animation \
		and blade.frame == _player.sprite.frame and blade.flip_h == _player.sprite.flip_h \
		and blade.offset == _player.sprite.offset


## Send an action as an input *event*, which is what UI nodes listen for
## (unlike [method Input.action_press], which only sets the polled state).
func _send_action(action: StringName) -> void:
	for pressed: bool in [true, false]:
		var event := InputEventAction.new()
		event.action = action
		event.pressed = pressed
		Input.parse_input_event(event)
		await _frames(2)


## Press and release a pad button as real input events.
func _send_pad_button(button: JoyButton) -> void:
	for pressed: bool in [true, false]:
		var event := InputEventJoypadButton.new()
		event.device = 0
		event.button_index = button
		event.pressed = pressed
		event.pressure = 1.0 if pressed else 0.0
		Input.parse_input_event(event)
		await _frames(2)


## Hold an analog axis at [param value] (it stays there until set again).
func _send_pad_axis(axis: JoyAxis, value: float) -> void:
	var event := InputEventJoypadMotion.new()
	event.device = 0
	event.axis = axis
	event.axis_value = value
	Input.parse_input_event(event)


## A bare hurtbox standing in for an enemy, for exact weapon-reach checks.
func _spawn_test_target(world_position: Vector2) -> Hurtbox:
	var target := Hurtbox.new()
	target.collision_layer = 1 << 4   # enemy_hurtbox
	target.collision_mask = 1 << 5    # player_attack
	var shape := CollisionShape2D.new()
	var rect := RectangleShape2D.new()
	rect.size = Vector2(8.0, 16.0)
	shape.shape = rect
	target.add_child(shape)
	_player.get_parent().add_child(target)
	target.global_position = world_position
	return target


func _tap(action: StringName, hold: float) -> void:
	Input.action_press(action)
	await _seconds(hold)
	Input.action_release(action)


func _frames(count: int) -> void:
	for i: int in count:
		await get_tree().physics_frame


func _seconds(duration: float) -> void:
	await get_tree().create_timer(duration, true, true).timeout
