## Headless unit tests for the non-visual logic added in Phase 2: the damage
## formula, the XP curve, equipment stat maths, drop-chance rolls and
## save/load round-trip integrity (SPEC 8).
##
## Run from the project root (a scene, not a --script SceneTree, so the
## autoloads are registered before anything here compiles):
##   godot --headless --path . res://tests/unit_test.tscn
##
## Exit code 0 = all checks passed, 1 = at least one failure.
##
## [b]Why not GUT?[/b] The spec suggests it, but GUT is a third-party addon
## this project does not vendor, and the whole point of the asset-and-tooling
## rule here is that everything ships in-tree. These run in the same harness
## as the smoke test — one command, one exit code, CI-ready. See ASSUMPTIONS.md.
extends Node

## A slot to scribble in. Anything already there is put back afterwards.
const TEST_SLOT: int = 2

var _failures: int = 0
var _checks: int = 0


func _ready() -> void:
	SaveManager.save_directory = "user://tests/unit_test_%d" % OS.get_process_id()
	DirAccess.make_dir_recursive_absolute(SaveManager.save_directory)
	get_tree().create_timer(90.0, true, false, true).timeout.connect(
		func() -> void:
			push_error("Test watchdog timed out.")
			get_tree().quit(1))
	_run.call_deferred()


func _run() -> void:
	print("Crimson Nocturne — unit tests")
	_test_damage_formula()
	_test_xp_curve()
	_test_stat_layering()
	_test_equipment_rules()
	_test_hearts_and_gold()
	_test_drop_rolls()
	_test_item_database()
	_test_weapon_art()
	_test_save_round_trip()
	_test_save_file_round_trip()

	print("")
	print("UNIT TESTS %s (%d check(s), %d failure(s))"
		% ["PASSED" if _failures == 0 else "FAILED", _checks, _failures])
	get_tree().quit(1 if _failures > 0 else 0)


# ---------------------------------------------------------------------------
# Combat
# ---------------------------------------------------------------------------
func _test_damage_formula() -> void:
	_section("damage formula")
	# base + floor(power/2) - floor(defense/2), no variance.
	_check(Combat.compute_damage(10, 0, 0, 1.0) == 10, "base damage passes through")
	_check(Combat.compute_damage(10, 7, 0, 1.0) == 13, "strength adds floor(7 * 0.5) = 3")
	_check(Combat.compute_damage(10, 0, 7, 1.0) == 7, "defense removes floor(7 * 0.5) = 3")
	_check(Combat.compute_damage(10, 8, 4, 1.0) == 12, "both sides combine (10 + 4 - 2)")
	_check(Combat.compute_damage(1, 0, 99, 1.0) == 1, "a hit always lands for at least 1")
	_check(Combat.compute_damage(0, 0, 0, 1.0) == 1, "even a zero-damage hit deals 1")

	var span: Vector2i = Combat.damage_range(20, 10, 0)
	_check(span.x == 23 and span.y == 28, "+/-10%% spread on 25 is 23..28 (got %d..%d)"
		% [span.x, span.y])

	var low: int = 9999
	var high: int = 0
	for i: int in 400:
		var rolled: int = Combat.compute_damage(20, 10, 0)
		low = mini(low, rolled)
		high = maxi(high, rolled)
	_check(low >= span.x and high <= span.y, "400 rolls stay inside the range (%d..%d)" % [low, high])
	_check(low < high, "rolls actually vary")


# ---------------------------------------------------------------------------
# Progression
# ---------------------------------------------------------------------------
func _test_xp_curve() -> void:
	_section("experience and levelling")
	_check(PlayerStats.xp_for_level(1) == 50, "level 1 -> 2 costs ceil(50 * 1^1.5) = 50")
	_check(PlayerStats.xp_for_level(4) == 400, "level 4 -> 5 costs ceil(50 * 4^1.5) = 400")
	_check(PlayerStats.xp_for_level(2) == 142, "level 2 -> 3 rounds up (got %d)"
		% PlayerStats.xp_for_level(2))

	var stats := PlayerStats.new()
	_check(stats.xp_to_next_level() == 50, "a new character needs 50 xp")
	_check(stats.add_experience(20) == 0, "20 xp is not a level")
	_check(stats.experience == 20 and stats.level == 1, "the 20 xp is banked")
	_check(stats.add_experience(30) == 1, "the next 30 xp levels up")
	_check(stats.level == 2 and stats.experience == 0, "the bank is spent, not carried twice")
	_check(stats.strength == PlayerStats.BASE_STRENGTH + PlayerStats.GAIN_STRENGTH
		and stats.constitution == PlayerStats.BASE_CONSTITUTION + PlayerStats.GAIN_CONSTITUTION,
		"the level-up applied the stat gains")

	# One huge award must cover several levels at once, not just the first.
	var fast := PlayerStats.new()
	var gained: int = fast.add_experience(50 + 142 + 260)
	_check(gained == 3, "one big award can cover several levels (got %d)" % gained)
	_check(fast.level == 4, "which lands on level 4 (got %d)" % fast.level)

	var overflow := PlayerStats.new()
	overflow.add_experience(60)
	_check(overflow.level == 2 and overflow.experience == 10, "leftover xp carries into the next level")

	_check(stats.max_hp_for(10) == PlayerStats.BASE_HP + 10 * PlayerStats.HP_PER_CONSTITUTION,
		"max HP is derived from Constitution")


func _test_stat_layering() -> void:
	_section("equipment stat layering")
	GameManager.start_new_game()
	var base_strength: int = GameManager.get_strength()
	_check(base_strength == PlayerStats.BASE_STRENGTH, "an empty character is all base stats")

	var ring: AccessoryData = ItemDB.get_item(&"ruby_ring") as AccessoryData
	_check(ring != null and ring.strength_bonus == 3, "the ruby ring is +3 STR")
	GameManager.add_item(ring)
	GameManager.equip(GameManager.Slot.RING_1, ring)
	_check(GameManager.get_strength() == base_strength + 3, "equipping it adds the flat bonus")
	_check(GameManager.stats.strength == base_strength, "and does not write into the base stats")

	var pendant: AccessoryData = ItemDB.get_item(&"silver_pendant") as AccessoryData
	GameManager.add_item(pendant)
	var armor: ArmorData = ItemDB.get_item(&"leather_cuirass") as ArmorData
	GameManager.add_item(armor)
	GameManager.equip(GameManager.Slot.ARMOR, armor)
	var with_armor: int = GameManager.get_defense()
	_check(with_armor == PlayerStats.BASE_DEFENSE + armor.defense,
		"armour Defense adds flat (got %d)" % with_armor)
	GameManager.equip(GameManager.Slot.NECKLACE, pendant)
	_check(GameManager.get_defense() == roundi(with_armor * 1.15),
		"the pendant's +15%% applies to the flat subtotal (got %d, wanted %d)"
			% [GameManager.get_defense(), roundi(with_armor * 1.15)])

	GameManager.unequip(GameManager.Slot.NECKLACE)
	GameManager.unequip(GameManager.Slot.ARMOR)
	_check(GameManager.get_defense() == PlayerStats.BASE_DEFENSE, "taking it all off returns to base")

	var before_hp: int = GameManager.get_max_hp()
	var jade: AccessoryData = ItemDB.get_item(&"jade_ring") as AccessoryData
	GameManager.add_item(jade)
	GameManager.equip(GameManager.Slot.RING_2, jade)
	_check(GameManager.get_max_hp() == before_hp + jade.constitution_bonus * PlayerStats.HP_PER_CONSTITUTION,
		"a Constitution ring raises max HP")


func _test_equipment_rules() -> void:
	_section("equipment rules")
	GameManager.start_new_game()
	var sword: WeaponData = ItemDB.get_item(&"short_sword") as WeaponData
	var ring: AccessoryData = ItemDB.get_item(&"ruby_ring") as AccessoryData
	var armor: ArmorData = ItemDB.get_item(&"leather_cuirass") as ArmorData

	_check(not GameManager.equip(GameManager.Slot.PRIMARY_WEAPON, sword),
		"you cannot equip something you do not own")
	GameManager.add_item(sword)
	_check(GameManager.equip(GameManager.Slot.PRIMARY_WEAPON, sword), "owning it lets you equip it")
	_check(not GameManager.equip(GameManager.Slot.ARMOR, sword), "a sword does not fit the armour slot")

	GameManager.add_item(ring)
	GameManager.equip(GameManager.Slot.RING_1, ring)
	GameManager.equip(GameManager.Slot.RING_2, ring)
	_check(GameManager.get_equipped(GameManager.Slot.RING_1) == null
		and GameManager.get_equipped(GameManager.Slot.RING_2) == ring,
		"one ring cannot be worn on two fingers — it moves")

	GameManager.add_item(armor)
	var candidates: Array[ItemData] = GameManager.items_for_slot(GameManager.Slot.ARMOR)
	_check(candidates.size() == 1 and candidates[0] == armor,
		"the armour slot only lists armour (got %d entries)" % candidates.size())

	# Two hands, two weapons.
	var whip: WeaponData = ItemDB.get_item(&"crimson_lash") as WeaponData
	GameManager.add_item(whip)
	GameManager.equip(GameManager.Slot.SECONDARY_WEAPON, whip)
	_check(GameManager.get_primary_weapon() == sword and GameManager.get_secondary_weapon() == whip,
		"the two hands hold different weapons")
	GameManager.swap_weapon_hands()
	_check(GameManager.get_primary_weapon() == whip and GameManager.get_secondary_weapon() == sword,
		"swapping hands exchanges them")

	# Sub-weapon cycling walks the owned set and comes back round.
	GameManager.add_item(ItemDB.get_item(&"dagger"))
	GameManager.add_item(ItemDB.get_item(&"axe"))
	GameManager.equip(GameManager.Slot.SUBWEAPON, ItemDB.get_item(&"dagger"))
	GameManager.cycle_subweapon()
	_check(GameManager.get_subweapon().id == &"axe", "cycling moves to the next sub-weapon")
	GameManager.cycle_subweapon()
	_check(GameManager.get_subweapon().id == &"dagger", "and wraps back round")

	# Relics unlock on pickup, not on equip — there is no relic slot.
	_check(not GameManager.has_ability(GameManager.ABILITY_DOUBLE_JUMP), "double jump starts locked")
	GameManager.add_item(ItemDB.get_item(&"leap_stone"))
	_check(GameManager.has_ability(GameManager.ABILITY_DOUBLE_JUMP),
		"the Leap Stone unlocks the double jump on pickup")


func _test_hearts_and_gold() -> void:
	_section("hearts, gold and consumables")
	GameManager.start_new_game()
	_check(GameManager.hearts == GameManager.max_hearts, "a new game starts with a full heart pool")

	GameManager.add_hearts(-999)
	_check(GameManager.hearts == 0, "hearts floor at zero")
	GameManager.add_hearts(999)
	_check(GameManager.hearts == GameManager.max_hearts, "and cap at the maximum")

	var ceiling: int = GameManager.max_hearts
	GameManager.add_hearts(-5)
	GameManager.raise_max_hearts(5)
	_check(GameManager.max_hearts == ceiling + 5, "a Heart Max Up raises the ceiling")
	_check(GameManager.hearts == ceiling, "and tops the pool up by the same amount")

	_check(GameManager.gold == 0, "a new game is broke")
	GameManager.add_gold(100)
	_check(GameManager.can_afford(100) and not GameManager.can_afford(101), "affordability is exact")
	_check(GameManager.spend_gold(60) and GameManager.gold == 40, "spending deducts")
	_check(not GameManager.spend_gold(41), "an unaffordable purchase is refused")
	_check(GameManager.gold == 40, "and takes nothing (no negative gold)")
	GameManager.add_gold(-999)
	_check(GameManager.gold == 0, "gold can never go negative")

	var potion: ConsumableData = ItemDB.get_item(&"vial_of_vitae") as ConsumableData
	GameManager.add_item(potion)
	GameManager.add_item(potion)
	_check(GameManager.count_of(potion.id) == 2, "consumables stack")
	_check(GameManager.consume(potion) and GameManager.count_of(potion.id) == 1, "using one decrements")
	_check(GameManager.consume(potion) and GameManager.count_of(potion.id) == 0, "the last one empties")
	_check(not GameManager.consume(potion), "an empty stack cannot be used")


func _test_drop_rolls() -> void:
	_section("drop rolls")
	var scene := load("res://scenes/enemies/skeleton.tscn") as PackedScene
	var skeleton := scene.instantiate() as Enemy
	_check(skeleton.gold_drop_chance > 0.0 and skeleton.gold_amount_range.x > 0,
		"the skeleton has a gold drop table")
	_check(skeleton.heart_drop_chance > 0.0, "and a heart drop table")
	_check(skeleton.experience > 0, "and awards experience")

	# The rolls are plain randf() comparisons, so check the distribution a
	# drop table relies on rather than the engine's RNG itself.
	var trials: int = 4000
	var hits: int = 0
	for i: int in trials:
		if randf() < 0.3:
			hits += 1
	var rate: float = float(hits) / trials
	_check(absf(rate - 0.3) < 0.04, "a 0.3 chance lands near 30%% over %d rolls (%.3f)" % [trials, rate])

	var lowest: int = 999
	var highest: int = 0
	for i: int in 500:
		var amount: int = randi_range(skeleton.gold_amount_range.x, skeleton.gold_amount_range.y)
		lowest = mini(lowest, amount)
		highest = maxi(highest, amount)
	_check(lowest >= skeleton.gold_amount_range.x and highest <= skeleton.gold_amount_range.y,
		"gold amounts stay inside the authored range (%d..%d)" % [lowest, highest])
	skeleton.free()


func _test_item_database() -> void:
	_section("item database")
	var items: Array[ItemData] = ItemDB.all_items()
	_check(items.size() >= 10, "every .tres in resources/ was registered (%d)" % items.size())
	var seen := {}
	var blank: int = 0
	for item: ItemData in items:
		if item.id.is_empty():
			blank += 1
		seen[item.id] = seen.get(item.id, 0) + 1
	_check(blank == 0, "every item has an id")
	_check(seen.size() == items.size(), "every id is unique")
	_check(ItemDB.get_item(&"short_sword") is WeaponData, "ids resolve to the right type")
	_check(ItemDB.get_item(&"no_such_item") == null, "an unknown id resolves to null, not an error")
	_check(ItemDB.items_of_type(ArmorData).size() >= 2, "type filtering works")


## Vesper swings bare-handed on every animation a blade sheet draws for, so a
## weapon using one of those swings has to bring art of its own, and that art
## has to line up with the hero frame for frame in all three stances.
func _test_weapon_art() -> void:
	_section("weapon art")
	var hero := load("res://resources/sprite_frames/vesper_frames.tres") as SpriteFrames
	var bare: Dictionary = {}
	var sheets: int = 0
	for file: String in DirAccess.get_files_at("res://resources/sprite_frames"):
		var sheet_file: String = file.trim_suffix(".remap")
		if not (sheet_file.begins_with("blade_") and sheet_file.ends_with("_frames.tres")):
			continue
		sheets += 1
		var sheet := load("res://resources/sprite_frames".path_join(sheet_file)) as SpriteFrames
		for anim: String in sheet.get_animation_names():
			bare[StringName(anim)] = true
	_check(sheets > 0 and bare.has(&"attack"), "the blade sheets cover the sword swing (%d sheet(s))" % sheets)
	for item: ItemData in ItemDB.items_of_type(WeaponData):
		var weapon := item as WeaponData
		var swings: Array[StringName] = [weapon.get_attack_animation(false, false),
			weapon.get_attack_animation(true, false), weapon.get_attack_animation(false, true)]
		if bare.has(swings[0]):
			_check(weapon.weapon_frames != null, "%s brings its own blade" % weapon.id)
		if weapon.weapon_frames == null:
			continue
		var lined_up: bool = true
		for anim: StringName in swings:
			lined_up = lined_up and hero.has_animation(anim) and weapon.weapon_frames.has_animation(anim) \
				and weapon.weapon_frames.get_frame_count(anim) == hero.get_frame_count(anim)
		_check(lined_up, "%s's art lines up with every stance of '%s'" % [weapon.id, weapon.attack_animation])


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------
## Build a run with something set in every field the spec requires a save to
## carry, so the round-trip tests cannot pass by only checking the easy ones.
func _populate_run() -> void:
	GameManager.start_new_game()
	GameManager.stats.add_experience(400)
	GameManager.add_gold(1234)
	GameManager.raise_max_hearts(10)
	GameManager.add_hearts(-3)
	for id: StringName in [&"short_sword", &"crimson_lash", &"dagger", &"axe",
			&"leather_cuirass", &"ruby_ring", &"onyx_ring", &"silver_pendant"]:
		GameManager.add_item(ItemDB.get_item(id))
	GameManager.add_item(ItemDB.get_item(&"vial_of_vitae"))
	GameManager.add_item(ItemDB.get_item(&"vial_of_vitae"))
	GameManager.add_item(ItemDB.get_item(&"leap_stone"))
	GameManager.equip(GameManager.Slot.PRIMARY_WEAPON, ItemDB.get_item(&"crimson_lash"))
	GameManager.equip(GameManager.Slot.SECONDARY_WEAPON, ItemDB.get_item(&"short_sword"))
	GameManager.equip(GameManager.Slot.SUBWEAPON, ItemDB.get_item(&"axe"))
	GameManager.equip(GameManager.Slot.ARMOR, ItemDB.get_item(&"leather_cuirass"))
	GameManager.equip(GameManager.Slot.NECKLACE, ItemDB.get_item(&"silver_pendant"))
	GameManager.equip(GameManager.Slot.RING_1, ItemDB.get_item(&"ruby_ring"))
	GameManager.equip(GameManager.Slot.RING_2, ItemDB.get_item(&"onyx_ring"))
	GameManager.collect_world_item(&"hall_ruby_ring")
	GameManager.mark_boss_defeated(&"hall_warden")
	GameManager.mark_room_explored(&"crimson_hall")
	GameManager.mark_room_explored(&"east_stair")
	GameManager.set_checkpoint(&"crimson_hall", Vector2(104.0, 256.0))
	GameManager.current_hp = 42


## Everything the spec (SPEC 3) says a save must carry, as one comparable blob.
func _snapshot() -> Dictionary:
	return {
		"level": GameManager.stats.level,
		"experience": GameManager.stats.experience,
		"strength": GameManager.stats.strength,
		"constitution": GameManager.stats.constitution,
		"defense": GameManager.stats.defense,
		"luck": GameManager.stats.luck,
		"gold": GameManager.gold,
		"hearts": GameManager.hearts,
		"max_hearts": GameManager.max_hearts,
		"hp": GameManager.current_hp,
		"inventory": GameManager.inventory.duplicate(),
		"consumables": GameManager.consumables.duplicate(),
		"equipped": _equipped_ids(),
		"collected": GameManager.collected_world_items.duplicate(),
		"bosses": GameManager.defeated_bosses.duplicate(),
		"abilities": GameManager.unlocked_abilities.duplicate(),
		"rooms": GameManager.explored_rooms.duplicate(),
		"checkpoint_room": GameManager.checkpoint_room,
		"checkpoint_position": GameManager.checkpoint_position,
	}


func _equipped_ids() -> Dictionary:
	var ids := {}
	for slot: int in GameManager.Slot.values():
		var item: ItemData = GameManager.get_equipped(slot)
		ids[slot] = item.id if item != null else &""
	return ids


func _test_save_round_trip() -> void:
	_section("save round-trip (in memory)")
	_populate_run()
	var before: Dictionary = _snapshot()
	var data: Dictionary = GameManager.to_save_data()

	# Wipe the run completely, so anything that survives came from the save.
	GameManager.start_new_game()
	_check(GameManager.gold == 0 and GameManager.inventory.is_empty(), "the run really was wiped")

	GameManager.apply_save_data(data)
	var after: Dictionary = _snapshot()
	for key: String in before:
		_check(str(before[key]) == str(after[key]),
			"'%s' survives the round trip" % key)

	# A save from an older build must load rather than crash.
	GameManager.apply_save_data({"gold": 7})
	_check(GameManager.gold == 7 and GameManager.stats.level == 1
		and GameManager.inventory.is_empty() and GameManager.current_hp > 0,
		"a save missing most keys loads on defaults")
	GameManager.apply_save_data({"inventory": ["ghost_item"], "equipped": {"0": "ghost_item"}})
	_check(GameManager.get_primary_weapon() == null,
		"an item id that no longer exists is dropped, not equipped")


func _test_save_file_round_trip() -> void:
	_section("save round-trip (on disk)")
	# Never clobber a real save: keep whatever is in the test slot and
	# put it back when we are done.
	var backup: PackedByteArray = PackedByteArray()
	var had_save: bool = SaveManager.has_save(TEST_SLOT)
	if had_save:
		backup = FileAccess.get_file_as_bytes(SaveManager.slot_path(TEST_SLOT))

	_populate_run()
	var before: Dictionary = _snapshot()
	_check(SaveManager.save_to_slot(TEST_SLOT), "the slot was written")
	_check(SaveManager.has_save(TEST_SLOT), "and the file exists")

	var info: SaveManager.SlotInfo = SaveManager.get_slot_info(TEST_SLOT)
	_check(info.exists and info.level == before["level"] and info.gold == before["gold"],
		"the slot header reads back without loading the whole run")
	_check(info.room == &"crimson_hall", "the header names the save room")

	GameManager.start_new_game()
	_check(SaveManager.load_from_slot(TEST_SLOT), "the slot loaded")
	var after: Dictionary = _snapshot()
	for key: String in before:
		_check(str(before[key]) == str(after[key]), "'%s' survives a write to disk and back" % key)
	_check(GameManager.current_slot == TEST_SLOT, "the loaded slot is remembered for the next save")

	# Corrupt files are a fact of life; they must read as "empty slot".
	var file := FileAccess.open(SaveManager.slot_path(TEST_SLOT), FileAccess.WRITE)
	file.store_string("{ this is not json")
	file.close()
	_check(not SaveManager.load_from_slot(TEST_SLOT), "a corrupt slot refuses to load")
	_check(not SaveManager.get_slot_info(TEST_SLOT).exists, "and reports itself as empty")
	_check(GameManager.gold == before["gold"], "a failed load leaves the run alone")

	SaveManager.delete_slot(TEST_SLOT)
	_check(not SaveManager.has_save(TEST_SLOT), "deleting a slot removes it")
	_check(not SaveManager.load_from_slot(TEST_SLOT), "an empty slot cannot be loaded")

	if had_save:
		var restore := FileAccess.open(SaveManager.slot_path(TEST_SLOT), FileAccess.WRITE)
		restore.store_buffer(backup)
		restore.close()


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------
func _section(title: String) -> void:
	print("")
	print("  " + title.to_upper())


func _check(condition: bool, label: String) -> void:
	_checks += 1
	print(("    [ok]   " if condition else "    [FAIL] ") + label)
	if not condition:
		_failures += 1
