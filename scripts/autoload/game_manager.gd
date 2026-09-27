## The run: everything about Vesper that outlives a room (autoload: [code]GameManager[/code]).
##
## Level, experience, stats, gold, hearts, the inventory, what is equipped in
## each of the seven slots, which unique world items have been taken, which
## bosses are dead, which traversal abilities are unlocked, which rooms the
## map has revealed, and where the last save point was. [SaveManager] writes
## exactly this and nothing else (SPEC 3).
##
## [b]Why it owns the numbers and the player node does not[/b][br]
## The player scene is destroyed and rebuilt on every room change and every
## death. Anything stored on it would have to be copied out and back; anything
## stored here simply survives. The [Player] reads through to this node for
## hearts, equipment and its stats, and keeps only what is genuinely physical
## (position, velocity, current HP, the state machine).
##
## [b]Base vs. effective stats[/b][br]
## [member stats] is the character sheet a level-up writes to. What combat
## actually reads is [method get_strength] and friends, which layer the
## equipped items on top: every flat bonus is summed first, then the
## percentage bonuses are applied to that subtotal. Equipment is therefore
## never baked into the save.
extends Node

## Equipment slots. The order is the order the menu lists them in.
enum Slot {
	PRIMARY_WEAPON,   ## Swung by the Attack button.
	SECONDARY_WEAPON, ## Swung by the Secondary Attack button (SPEC 4.1).
	SUBWEAPON,        ## The heart-powered throw.
	ARMOR,
	NECKLACE,
	RING_1,
	RING_2,
}

## Ability ids granted by relics (SPEC 4.1). The player checks these before
## allowing the move; a save stores the unlocked set.
const ABILITY_DOUBLE_JUMP: StringName = &"double_jump"
const ABILITY_LONG_DASH: StringName = &"long_dash"

const STARTING_MAX_HEARTS: int = 20
const HEART_MAX_UP_AMOUNT: int = 5
const ABSOLUTE_MAX_HEARTS: int = 99

## Slots an accessory may occupy, by [enum AccessoryData.Slot].
const ACCESSORY_SLOTS: Dictionary[int, Array] = {
	AccessoryData.Slot.NECKLACE: [Slot.NECKLACE],
	AccessoryData.Slot.RING: [Slot.RING_1, Slot.RING_2],
}

## The character sheet. Replaced wholesale by a load; mutated by level-ups.
var stats: PlayerStats = PlayerStats.new()
var gold: int = 0
var hearts: int = 0
var max_hearts: int = STARTING_MAX_HEARTS
## HP carried across room changes. Save points restore it to full (SPEC 4.4.2).
var current_hp: int = 0
var play_time: float = 0.0

## Unique items owned, by id. Consumables are counted separately.
var inventory: Array[StringName] = []
## Consumable id -> how many are held.
var consumables: Dictionary[StringName, int] = {}
## Unique world pickups already taken, so they never respawn (SPEC 4.7).
var collected_world_items: Array[StringName] = []
## Bosses already beaten, so they are not re-fought (SPEC 4.5).
var defeated_bosses: Array[StringName] = []
var unlocked_abilities: Array[StringName] = []
## Rooms revealed on the map, for the Phase 3 fog of war (SPEC 4.4.3).
var explored_rooms: Array[StringName] = []

## Room id of the last save point used, and the exact spot in it.
var checkpoint_room: StringName = &""
var checkpoint_position: Vector2 = Vector2.ZERO
## Save slot this run came from / will default to. -1 = never saved.
var current_slot: int = -1

var _equipped: Dictionary[int, ItemData] = {}


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_PAUSABLE
	start_new_game()


func _process(delta: float) -> void:
	play_time += delta


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------
## Wipe the run back to a fresh level 1. Called at boot and by "New Game";
## a subsequent [method apply_save_data] overwrites all of it.
func start_new_game() -> void:
	stats = PlayerStats.new()
	gold = 0
	max_hearts = STARTING_MAX_HEARTS
	hearts = max_hearts
	play_time = 0.0
	inventory.clear()
	consumables.clear()
	collected_world_items.clear()
	defeated_bosses.clear()
	unlocked_abilities.clear()
	explored_rooms.clear()
	_equipped.clear()
	checkpoint_room = &""
	checkpoint_position = Vector2.ZERO
	current_slot = -1
	current_hp = get_max_hp()
	_announce_everything()


## Give the player the loadout authored on the player scene, once, at the
## start of a new game.
##
## The player node is rebuilt on every room change and every death, so this
## runs often — but only an inventory that is still completely empty counts
## as a new game. Otherwise a loaded save, or a weapon the player chose to
## take off, would be quietly overwritten on the next respawn.
func seed_starting_loadout(items: Array[ItemData]) -> void:
	if not inventory.is_empty():
		return
	for item: ItemData in items:
		if item == null:
			continue
		add_item(item, false)
		var slot: int = default_slot_for(item)
		if slot != -1 and get_equipped(slot) == null:
			equip(slot, item, false)
	Events.inventory_changed.emit()
	_announce_equipment()
	_refresh_derived()


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
## Add [param item] to the inventory. Consumables stack; everything else is
## owned once. Returns false if a unique item was already held.
func add_item(item: ItemData, announce: bool = true) -> bool:
	if item == null:
		return false
	if item is ConsumableData:
		consumables[item.id] = consumables.get(item.id, 0) + 1
	elif inventory.has(item.id):
		return false
	else:
		inventory.append(item.id)
	if item is RelicData:
		unlock_ability((item as RelicData).ability)
	if announce:
		Events.inventory_changed.emit()
	return true


## Spend one [param item] from the consumable stack. Returns false when none
## are held.
func consume(item: ConsumableData) -> bool:
	if item == null or consumables.get(item.id, 0) <= 0:
		return false
	consumables[item.id] -= 1
	if consumables[item.id] <= 0:
		consumables.erase(item.id)
	Events.inventory_changed.emit()
	return true


func owns(item_id: StringName) -> bool:
	return inventory.has(item_id) or consumables.get(item_id, 0) > 0


func count_of(item_id: StringName) -> int:
	if consumables.has(item_id):
		return consumables[item_id]
	return 1 if inventory.has(item_id) else 0


## Everything owned that can go in [param slot], in inventory order. This is
## what the equip menu lists.
func items_for_slot(slot: Slot) -> Array[ItemData]:
	var result: Array[ItemData] = []
	for id: StringName in inventory:
		var item: ItemData = ItemDB.get_item(id)
		if item != null and can_equip(slot, item):
			result.append(item)
	return result


## Every consumable held, paired with its count, for the menu and shop.
func held_consumables() -> Array[ItemData]:
	var result: Array[ItemData] = []
	for id: StringName in consumables:
		var item: ItemData = ItemDB.get_item(id)
		if item != null:
			result.append(item)
	result.sort_custom(func(a: ItemData, b: ItemData) -> bool: return a.display_name < b.display_name)
	return result


# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------
## The item in [param slot], or null.
func get_equipped(slot: int) -> ItemData:
	return _equipped.get(slot)


func get_primary_weapon() -> WeaponData:
	return get_equipped(Slot.PRIMARY_WEAPON) as WeaponData


func get_secondary_weapon() -> WeaponData:
	return get_equipped(Slot.SECONDARY_WEAPON) as WeaponData


func get_subweapon() -> SubWeaponData:
	return get_equipped(Slot.SUBWEAPON) as SubWeaponData


## Whether [param item] is the right shape for [param slot].
func can_equip(slot: int, item: ItemData) -> bool:
	match slot:
		Slot.PRIMARY_WEAPON, Slot.SECONDARY_WEAPON:
			return item is WeaponData
		Slot.SUBWEAPON:
			return item is SubWeaponData
		Slot.ARMOR:
			return item is ArmorData
		Slot.NECKLACE:
			return item is AccessoryData and (item as AccessoryData).slot == AccessoryData.Slot.NECKLACE
		Slot.RING_1, Slot.RING_2:
			return item is AccessoryData and (item as AccessoryData).slot == AccessoryData.Slot.RING
	return false


## The slot an item goes in by default (the first free one for rings), or
## -1 for items that are not equipment at all.
func default_slot_for(item: ItemData) -> int:
	if item is WeaponData:
		return Slot.PRIMARY_WEAPON if get_equipped(Slot.PRIMARY_WEAPON) == null else Slot.SECONDARY_WEAPON
	if item is SubWeaponData:
		return Slot.SUBWEAPON
	if item is ArmorData:
		return Slot.ARMOR
	if item is AccessoryData:
		for slot: int in ACCESSORY_SLOTS[(item as AccessoryData).slot]:
			if get_equipped(slot) == null:
				return slot
		return ACCESSORY_SLOTS[(item as AccessoryData).slot][0]
	return -1


## Put [param item] (or null, to empty the slot) into [param slot].
##
## The same physical item can only be worn once, so equipping something that
## is already in another slot *moves* it rather than cloning it — the classic
## "one ring, two ring fingers" problem. Returns false if it does not fit.
func equip(slot: int, item: ItemData, announce: bool = true) -> bool:
	if item != null and not can_equip(slot, item):
		return false
	if item != null and not inventory.has(item.id):
		return false
	if get_equipped(slot) == item:
		return true
	if item != null:
		for other: int in _equipped.keys():
			if other != slot and _equipped[other] == item:
				_set_slot(other, null, announce)
	_set_slot(slot, item, announce)
	if announce:
		_refresh_derived()
	return true


func unequip(slot: int) -> void:
	equip(slot, null)


## Swap whatever is in the two weapon hands.
func swap_weapon_hands() -> void:
	var primary: ItemData = get_equipped(Slot.PRIMARY_WEAPON)
	var secondary: ItemData = get_equipped(Slot.SECONDARY_WEAPON)
	_set_slot(Slot.PRIMARY_WEAPON, secondary, true)
	_set_slot(Slot.SECONDARY_WEAPON, primary, true)
	_refresh_derived()


## Move to the next owned sub-weapon (the Switch Sub-weapon button).
func cycle_subweapon(step: int = 1) -> void:
	var owned: Array[ItemData] = items_for_slot(Slot.SUBWEAPON)
	if owned.size() < 2:
		return
	var index: int = owned.find(get_subweapon())
	equip(Slot.SUBWEAPON, owned[posmod(index + step, owned.size())])


# ---------------------------------------------------------------------------
# Effective stats
# ---------------------------------------------------------------------------
func get_strength() -> int:
	return _total("strength")


func get_constitution() -> int:
	return _total("constitution")


func get_defense() -> int:
	return _total("defense")


func get_luck() -> int:
	return _total("luck")


## Max HP from the effective Constitution (SPEC 4.3).
func get_max_hp() -> int:
	return stats.max_hp_for(get_constitution())


## Flat bonus contributed by [param slot] alone, for the menu's compare view.
func get_slot_defense(slot: int) -> int:
	var armor := get_equipped(slot) as ArmorData
	return armor.defense if armor != null else 0


# ---------------------------------------------------------------------------
# Experience, gold and hearts
# ---------------------------------------------------------------------------
## Bank experience and level up as far as it goes. Returns levels gained.
func add_experience(amount: int) -> int:
	var gained: int = stats.add_experience(amount)
	Events.player_experience_changed.emit(stats.experience, stats.xp_to_next_level(), stats.level)
	if gained > 0:
		# Classic Castlevania courtesy: a level-up is also a full heal. It has
		# to be applied before the broadcast, because that is what makes the
		# player's health component pick the new value up.
		if current_hp > 0:
			current_hp = stats.max_hp_for(get_constitution())
		_refresh_derived()
		Events.player_leveled_up.emit(stats.level)
	return gained


## Add (or, with a negative amount, spend) gold. Gold can never go negative:
## the shop must check [method can_afford] first (SPEC 5.3).
func add_gold(amount: int) -> void:
	gold = maxi(0, gold + amount)
	Events.player_gold_changed.emit(gold)


func can_afford(amount: int) -> bool:
	return gold >= amount


## Take [param amount] gold if it is there. Returns false without spending
## anything if it is not.
func spend_gold(amount: int) -> bool:
	if not can_afford(amount):
		return false
	add_gold(-amount)
	return true


func add_hearts(amount: int) -> void:
	hearts = clampi(hearts + amount, 0, max_hearts)
	Events.player_hearts_changed.emit(hearts, max_hearts)


## A "Heart Max Up" pickup (SPEC 4.2.2): raise the ceiling and top up by the
## same amount, so the reward is felt immediately.
func raise_max_hearts(amount: int = HEART_MAX_UP_AMOUNT) -> void:
	var before: int = max_hearts
	max_hearts = mini(ABSOLUTE_MAX_HEARTS, max_hearts + amount)
	hearts = mini(max_hearts, hearts + (max_hearts - before))
	Events.player_hearts_changed.emit(hearts, max_hearts)


# ---------------------------------------------------------------------------
# World progress flags
# ---------------------------------------------------------------------------
## Record that a unique world pickup has been taken. Returns false if it had
## already been collected (which is how a pickup knows to delete itself).
func collect_world_item(item_id: StringName) -> bool:
	if item_id.is_empty() or collected_world_items.has(item_id):
		return false
	collected_world_items.append(item_id)
	Events.world_item_collected.emit(item_id)
	return true


func is_world_item_collected(item_id: StringName) -> bool:
	return collected_world_items.has(item_id)


func mark_boss_defeated(boss_id: StringName) -> void:
	if not boss_id.is_empty() and not defeated_bosses.has(boss_id):
		defeated_bosses.append(boss_id)


func is_boss_defeated(boss_id: StringName) -> bool:
	return defeated_bosses.has(boss_id)


func unlock_ability(ability: StringName) -> void:
	if ability.is_empty() or unlocked_abilities.has(ability):
		return
	unlocked_abilities.append(ability)
	Events.ability_unlocked.emit(ability)


func has_ability(ability: StringName) -> bool:
	return unlocked_abilities.has(ability)


## Reveal a room on the map. Returns false if it was already known.
func mark_room_explored(room_id: StringName) -> bool:
	if room_id.is_empty() or explored_rooms.has(room_id):
		return false
	explored_rooms.append(room_id)
	return true


func is_room_explored(room_id: StringName) -> bool:
	return explored_rooms.has(room_id)


## Remember where to respawn, and fully restore HP and hearts (SPEC 4.4.2).
func set_checkpoint(room_id: StringName, position: Vector2) -> void:
	checkpoint_room = room_id
	checkpoint_position = position
	current_hp = get_max_hp()
	hearts = max_hearts
	Events.player_hearts_changed.emit(hearts, max_hearts)
	Events.player_stats_changed.emit()


## Come back from the dead at the last save point. There is deliberately no
## penalty — no lost XP, gold or items (SPEC 4.4.2, confirmed) — so this only
## refills what was spent staying alive.
func respawn() -> void:
	current_hp = get_max_hp()
	hearts = max_hearts
	Events.player_hearts_changed.emit(hearts, max_hearts)
	Events.player_stats_changed.emit()


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------
## The complete run as plain JSON-safe values (SPEC 3).
func to_save_data() -> Dictionary:
	var equipped := {}
	for slot: int in _equipped:
		if _equipped[slot] != null:
			equipped[str(slot)] = String(_equipped[slot].id)
	var plain_consumables := {}
	for id: StringName in consumables:
		plain_consumables[String(id)] = consumables[id]
	return {
		"stats": stats.to_dict(),
		"gold": gold,
		"hearts": hearts,
		"max_hearts": max_hearts,
		"current_hp": current_hp,
		"play_time": play_time,
		"inventory": _to_string_array(inventory),
		"consumables": plain_consumables,
		"equipped": equipped,
		"collected_world_items": _to_string_array(collected_world_items),
		"defeated_bosses": _to_string_array(defeated_bosses),
		"unlocked_abilities": _to_string_array(unlocked_abilities),
		"explored_rooms": _to_string_array(explored_rooms),
		"checkpoint_room": String(checkpoint_room),
		"checkpoint_position": {"x": checkpoint_position.x, "y": checkpoint_position.y},
	}


## Replace the whole run with [param data]. Anything missing falls back to a
## new-game default rather than erroring, so a save written by an earlier
## build still loads.
func apply_save_data(data: Dictionary) -> bool:
	if not SaveData.valid_run(data):
		return false
	stats = PlayerStats.from_dict(data.get("stats", {}))
	gold = maxi(0, int(data.get("gold", 0)))
	max_hearts = clampi(int(data.get("max_hearts", STARTING_MAX_HEARTS)), 1, ABSOLUTE_MAX_HEARTS)
	hearts = clampi(int(data.get("hearts", max_hearts)), 0, max_hearts)
	play_time = float(data.get("play_time", 0.0))

	inventory.clear()
	for id: StringName in _to_name_array(data.get("inventory", [])):
		var item: ItemData = ItemDB.get_item(id)
		if item != null and item is not ConsumableData and not inventory.has(id):
			inventory.append(id)
	consumables.clear()
	var saved_consumables: Dictionary = data.get("consumables", {})
	for id: Variant in saved_consumables:
		if ItemDB.get_item(StringName(id)) is ConsumableData and int(saved_consumables[id]) > 0:
			consumables[StringName(id)] = int(saved_consumables[id])
	collected_world_items = _to_name_array(data.get("collected_world_items", []))
	defeated_bosses = _to_name_array(data.get("defeated_bosses", []))
	unlocked_abilities = _to_name_array(data.get("unlocked_abilities", []))
	explored_rooms = _to_name_array(data.get("explored_rooms", []))

	_equipped.clear()
	var saved_equipment: Dictionary = data.get("equipped", {})
	for slot: int in Slot.values():
		var id: String = saved_equipment.get(str(slot), "")
		var item: ItemData = ItemDB.get_item(StringName(id))
		if item != null:
			equip(slot, item, false)

	checkpoint_room = StringName(data.get("checkpoint_room", ""))
	var saved_position: Dictionary = data.get("checkpoint_position", {})
	checkpoint_position = Vector2(float(saved_position.get("x", 0.0)), float(saved_position.get("y", 0.0)))
	# HP is clamped last: it depends on the Constitution we just restored.
	current_hp = clampi(int(data.get("current_hp", get_max_hp())), 1, get_max_hp())
	_announce_everything()
	return true


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
func _set_slot(slot: int, item: ItemData, announce: bool) -> void:
	if item == null:
		_equipped.erase(slot)
	else:
		_equipped[slot] = item
	if not announce:
		return
	Events.player_equipment_changed.emit(slot, item)
	match slot:
		Slot.PRIMARY_WEAPON:
			Events.player_weapon_changed.emit(item as WeaponData)
		Slot.SUBWEAPON:
			Events.player_subweapon_changed.emit(item as SubWeaponData)


## Base stat plus every equipped item's flat bonus, then the percentages.
func _total(stat: String) -> int:
	var flat: int = stats.get(stat)
	var percent: float = 0.0
	for slot: int in _equipped:
		var item: ItemData = _equipped[slot]
		if item == null:
			continue
		flat += item.get("%s_bonus" % stat)
		percent += item.get("%s_percent" % stat)
		if stat == "defense" and item is ArmorData:
			flat += (item as ArmorData).defense
	return maxi(0, roundi(flat * (1.0 + percent)))


## Stats or equipment moved: re-clamp derived values and tell everyone.
func _refresh_derived() -> void:
	current_hp = clampi(current_hp, 0, get_max_hp())
	Events.player_stats_changed.emit()


func _announce_equipment() -> void:
	for slot: int in Slot.values():
		Events.player_equipment_changed.emit(slot, get_equipped(slot))
	Events.player_weapon_changed.emit(get_primary_weapon())
	Events.player_subweapon_changed.emit(get_subweapon())


func _announce_everything() -> void:
	Events.player_gold_changed.emit(gold)
	Events.player_hearts_changed.emit(hearts, max_hearts)
	Events.player_experience_changed.emit(stats.experience, stats.xp_to_next_level(), stats.level)
	Events.inventory_changed.emit()
	_announce_equipment()
	Events.player_stats_changed.emit()


func _to_string_array(names: Array[StringName]) -> Array:
	var result := []
	for name: StringName in names:
		result.append(String(name))
	return result


func _to_name_array(values: Variant) -> Array[StringName]:
	var result: Array[StringName] = []
	if values is Array:
		for value: Variant in values:
			result.append(StringName(value))
	return result
