## The pause menu (SPEC 5.2): equipment, stats, map and system settings.
##
## Opening it pauses the tree (the menu itself runs with
## [constant Node.PROCESS_MODE_ALWAYS]) and takes over input: while it is
## open every action is swallowed here so nothing leaks into gameplay.
##
## [b]Controls[/b][br]
## Up/Down move the cursor, Left/Right switch column, Attack or Jump confirms,
## and Equip-menu, Pause or Backdash closes — so on a pad that is the
## console-standard bottom face button to confirm and right face button to
## cancel. The shoulder buttons page between tabs. The hint line names
## whichever buttons the player is actually holding.
##
## [b]Where the content comes from[/b][br]
## Nothing here is authored twice: the slot list is [enum GameManager.Slot],
## the candidates for a slot are whatever the inventory holds that fits it,
## and every number shown is read back off [GameManager] and the item
## resources. Adding a weapon, a ring or a whole new item type needs no
## change in this file.
class_name PauseMenu
extends CanvasLayer

signal opened
signal closed

enum Tab { EQUIPMENT, STATS, MAP, SYSTEM }

## Focused column on the equipment tab.
const SLOTS: int = 0
const ITEMS: int = 1

## The equipment tab's rows: the seven real slots, plus a pseudo-slot at the
## end for consumables, which are used rather than worn.
const CONSUMABLE_ROW: int = 7
const SLOT_LABELS: PackedStringArray = [
	"RIGHT HAND", "LEFT HAND", "SUB-WEAPON", "ARMOUR", "NECKLACE", "RING I", "RING II", "ITEMS",
]

## Held-direction auto-repeat, in seconds (delay before the first repeat,
## then the interval between them).
const REPEAT_DELAY: float = 0.35
const REPEAT_INTERVAL: float = 0.09

const SLOT_ROW_HEIGHT: float = 11.0
const ITEM_ROW_HEIGHT: float = 16.0
const COLOR_ITEM: Color = Color(0.72, 0.70, 0.80)
const COLOR_HIGHLIGHT: Color = Color(0.94, 0.78, 0.36)
## Highlight of the column that doesn't have focus.
const COLOR_INACTIVE: Color = Color(0.58, 0.50, 0.46)
const COLOR_EMPTY: Color = Color(0.45, 0.43, 0.55)
const COLOR_GOOD: Color = Color(0.55, 0.85, 0.55)

@export var cursor_texture: Texture2D
@export var equipped_texture: Texture2D

@onready var _tab_bar: HBoxContainer = %TabBar
@onready var _pages: Dictionary[Tab, Control] = {
	Tab.EQUIPMENT: %Equipment,
	Tab.STATS: %Stats,
	Tab.MAP: %Map,
	Tab.SYSTEM: %System,
}
@onready var _slot_list: VBoxContainer = %SlotList
@onready var _item_list: VBoxContainer = %ItemList
@onready var _item_scroll: ScrollContainer = %ItemScroll
@onready var _slot_header: Label = %SlotHeader
@onready var _item_header: Label = %ItemHeader
@onready var _stats_left: VBoxContainer = %StatsLeft
@onready var _stats_right: VBoxContainer = %StatsRight
@onready var _map_body: Label = %MapBody
@onready var _system_list: VBoxContainer = %SystemList
@onready var _info_name: Label = %InfoName
@onready var _info_description: Label = %InfoDescription
@onready var _info_stats: Label = %InfoStats
@onready var _hint: Label = %Hint

var is_open: bool = false

var _tab: Tab = Tab.EQUIPMENT
## Focused column on the equipment tab: [constant SLOTS] or [constant ITEMS].
var _column: int = SLOTS
var _slot_row: int = 0
var _item_row: int = 0
var _system_row: int = 0
## Candidates currently listed for the focused slot. A null entry is the
## "take it off" row, which every real slot gets.
var _candidates: Array[ItemData] = []
## Set once the player dies so the menu can't be opened during the restart.
var _locked: bool = false
var _held_direction: int = 0
var _repeat_timer: float = 0.0
var _tab_labels: Array[Label] = []
var _system_rows: Array[Label] = []


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	visible = false
	_build_tab_bar()
	_build_system_rows()
	Events.player_died.connect(_on_player_died)
	Controls.device_changed.connect(_on_device_changed)
	_refresh_hint()


func _process(delta: float) -> void:
	if not is_open:
		return
	# Vertical navigation is polled (rather than event-driven) so holding a
	# direction auto-repeats, which is what every console menu does.
	var direction: int = int(Input.is_action_pressed(&"move_down")) - int(Input.is_action_pressed(&"move_up"))
	if direction == 0:
		_held_direction = 0
	elif direction != _held_direction:
		_held_direction = direction
		_repeat_timer = REPEAT_DELAY
		_move_cursor(direction)
	else:
		_repeat_timer -= delta
		if _repeat_timer <= 0.0:
			_repeat_timer = REPEAT_INTERVAL
			_move_cursor(direction)


func _unhandled_input(event: InputEvent) -> void:
	if not is_open:
		if event.is_action_pressed(&"pause_menu"):
			open()
			get_viewport().set_input_as_handled()
		return
	if event.is_action_pressed(&"pause_menu") or event.is_action_pressed(&"pause"):
		close()
	elif event.is_action_pressed(&"backdash"):
		_cancel()
	elif event.is_action_pressed(&"switch_subweapon"):
		_change_tab(-1)
	elif event.is_action_pressed(&"attack_secondary"):
		_change_tab(1)
	elif event.is_action_pressed(&"move_left"):
		_horizontal(-1)
	elif event.is_action_pressed(&"move_right"):
		_horizontal(1)
	elif event.is_action_pressed(&"attack") or event.is_action_pressed(&"jump") \
			or event.is_action_pressed(&"subweapon"):
		_confirm()
	# Modal: nothing that happens while the menu is up reaches the game.
	get_viewport().set_input_as_handled()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
## Pause the game and show the menu. Does nothing while the player is dead,
## or if the game is already paused by the pause button.
func open() -> void:
	if is_open or _locked or get_tree().paused:
		return
	var player := get_tree().get_first_node_in_group(&"player") as Player
	if player == null or player.state == Player.State.DEAD:
		return
	_tab = Tab.EQUIPMENT
	_column = SLOTS
	_slot_row = 0
	_held_direction = 0
	_refresh_all()
	is_open = true
	visible = true
	get_tree().paused = true
	Audio.play_sfx(&"menu_select", 0.0, -3.0)
	opened.emit()


## Hide the menu and resume the game.
func close() -> void:
	if not is_open:
		return
	is_open = false
	visible = false
	get_tree().paused = false
	Audio.play_sfx(&"menu_move", 0.0, -3.0)
	closed.emit()


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------
## Back out one level: from the item column to the slot column, and from the
## slot column out of the menu entirely.
func _cancel() -> void:
	if _tab == Tab.EQUIPMENT and _column == ITEMS:
		_column = SLOTS
		Audio.play_sfx(&"menu_move", 0.03, -6.0)
		_refresh_equipment()
		return
	close()


func _change_tab(step: int) -> void:
	_tab = posmod(_tab + step, Tab.size()) as Tab
	_column = SLOTS
	_system_row = 0
	Audio.play_sfx(&"menu_move", 0.03, -6.0)
	_refresh_all()


func _horizontal(step: int) -> void:
	match _tab:
		Tab.EQUIPMENT:
			var wanted: int = clampi(_column + step, SLOTS, ITEMS)
			# The consumable row has no "equip" side; confirming uses the item.
			if wanted == _column or (wanted == ITEMS and _candidates.is_empty()):
				return
			_column = wanted
			Audio.play_sfx(&"menu_move", 0.03, -6.0)
			_refresh_equipment()
		Tab.SYSTEM:
			_adjust_setting(step)
		_:
			pass


func _move_cursor(direction: int) -> void:
	match _tab:
		Tab.EQUIPMENT:
			if _column == SLOTS:
				_slot_row = posmod(_slot_row + direction, SLOT_LABELS.size())
			elif not _candidates.is_empty():
				_item_row = posmod(_item_row + direction, _candidates.size())
			else:
				return
			Audio.play_sfx(&"menu_move", 0.03, -6.0)
			_refresh_equipment()
		Tab.SYSTEM:
			_system_row = posmod(_system_row + direction, _system_rows.size())
			Audio.play_sfx(&"menu_move", 0.03, -6.0)
			_refresh_system()
		_:
			pass


func _confirm() -> void:
	match _tab:
		Tab.EQUIPMENT:
			_confirm_equipment()
		Tab.SYSTEM:
			_adjust_setting(1)
		_:
			pass


func _confirm_equipment() -> void:
	if _column == SLOTS:
		if _candidates.is_empty():
			return
		_column = ITEMS
		Audio.play_sfx(&"menu_select", 0.0)
		_refresh_equipment()
		return
	var chosen: ItemData = _candidates[_item_row] if _item_row < _candidates.size() else null
	if _slot_row == CONSUMABLE_ROW:
		_use_consumable(chosen as ConsumableData)
	else:
		GameManager.equip(_slot_row, chosen)
		Audio.play_sfx(&"menu_select", 0.0)
	_refresh_equipment()


func _use_consumable(item: ConsumableData) -> void:
	var player := get_tree().get_first_node_in_group(&"player") as Player
	if item == null or player == null or not GameManager.consume(item):
		return
	if item.heal_amount > 0:
		player.heal(item.heal_amount)
	if item.heart_amount > 0:
		GameManager.add_hearts(item.heart_amount)
	Audio.play_sfx(item.use_sfx, 0.0)
	Events.notice_posted.emit(item.display_name.to_upper())


# ---------------------------------------------------------------------------
# Equipment tab
# ---------------------------------------------------------------------------
## Everything that could go in the highlighted row, cursor included. Real
## slots get a leading null ("take it off"); the consumable row does not.
func _collect_candidates() -> Array[ItemData]:
	if _slot_row == CONSUMABLE_ROW:
		return GameManager.held_consumables()
	var list: Array[ItemData] = [null]
	list.append_array(GameManager.items_for_slot(_slot_row as GameManager.Slot))
	return list


func _refresh_equipment() -> void:
	_candidates = _collect_candidates()
	_item_row = clampi(_item_row, 0, maxi(0, _candidates.size() - 1))
	_fill_slot_list()
	_fill_item_list()
	_slot_header.add_theme_color_override(
		&"font_color", COLOR_HIGHLIGHT if _column == SLOTS else COLOR_EMPTY)
	_item_header.add_theme_color_override(
		&"font_color", COLOR_HIGHLIGHT if _column == ITEMS else COLOR_EMPTY)
	_item_header.text = "CARRIED" if _slot_row != CONSUMABLE_ROW else "PROVISIONS"
	_scroll_to_item_row()
	_update_info()


func _fill_slot_list() -> void:
	_clear(_slot_list)
	for row: int in SLOT_LABELS.size():
		var equipped: ItemData = null if row == CONSUMABLE_ROW else GameManager.get_equipped(row)
		var value: String = "-"
		if row == CONSUMABLE_ROW:
			var carried: int = GameManager.held_consumables().size()
			value = "%d KIND%s" % [carried, "" if carried == 1 else "S"]
		elif equipped != null:
			value = equipped.display_name
		var selected: bool = row == _slot_row
		var color: Color = COLOR_ITEM
		if selected:
			color = COLOR_HIGHLIGHT if _column == SLOTS else COLOR_INACTIVE
		elif equipped == null and row != CONSUMABLE_ROW:
			color = COLOR_EMPTY
		_slot_list.add_child(_make_slot_row(SLOT_LABELS[row], value, selected, color))


func _fill_item_list() -> void:
	_clear(_item_list)
	if _candidates.is_empty():
		_item_list.add_child(_make_item_row("- NONE CARRIED -", null, "", false, false, COLOR_EMPTY))
		return
	var equipped: ItemData = null if _slot_row == CONSUMABLE_ROW else GameManager.get_equipped(_slot_row)
	for i: int in _candidates.size():
		var item: ItemData = _candidates[i]
		var selected: bool = i == _item_row
		var color: Color = COLOR_ITEM
		if selected:
			color = COLOR_HIGHLIGHT if _column == ITEMS else COLOR_INACTIVE
		elif item == null:
			color = COLOR_EMPTY
		var label: String = item.display_name if item != null else "- REMOVE -"
		var suffix: String = ""
		if item is ConsumableData:
			suffix = "x%d" % GameManager.count_of(item.id)
		_item_list.add_child(_make_item_row(
			label, item.icon if item != null else null, suffix,
			selected and _column == ITEMS, item != null and item == equipped, color))


## Keep the highlighted row inside the scroll window.
func _scroll_to_item_row() -> void:
	if _candidates.is_empty():
		return
	var top: float = _item_row * ITEM_ROW_HEIGHT
	var view: float = _item_scroll.size.y
	var offset: float = _item_scroll.scroll_vertical
	if top < offset:
		_item_scroll.scroll_vertical = int(top)
	elif top + ITEM_ROW_HEIGHT > offset + view:
		_item_scroll.scroll_vertical = int(top + ITEM_ROW_HEIGHT - view)


## One line in the equipped column: "RING I        Ruby Ring".
func _make_slot_row(label: String, value: String, selected: bool, color: Color) -> Control:
	var row := HBoxContainer.new()
	row.custom_minimum_size = Vector2(0.0, SLOT_ROW_HEIGHT)
	row.add_theme_constant_override(&"separation", 2)

	var cursor := TextureRect.new()
	cursor.texture = cursor_texture
	cursor.visible = selected
	cursor.custom_minimum_size = Vector2(7.0, 9.0)
	cursor.stretch_mode = TextureRect.STRETCH_KEEP_CENTERED
	cursor.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	row.add_child(cursor)

	var name_label := Label.new()
	name_label.text = label
	name_label.custom_minimum_size = Vector2(66.0, 0.0)
	name_label.add_theme_color_override(&"font_color", COLOR_EMPTY if not selected else color)
	row.add_child(name_label)

	var value_label := Label.new()
	value_label.text = value.to_upper()
	value_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	value_label.clip_text = true
	value_label.add_theme_color_override(&"font_color", color)
	row.add_child(value_label)
	return row


## One line in the carried column: cursor, icon, name, count, equipped diamond.
func _make_item_row(label: String, icon: Texture2D, suffix: String,
		selected: bool, equipped: bool, color: Color) -> Control:
	var row := HBoxContainer.new()
	row.custom_minimum_size = Vector2(0.0, ITEM_ROW_HEIGHT)
	row.add_theme_constant_override(&"separation", 3)

	var cursor := TextureRect.new()
	cursor.texture = cursor_texture
	cursor.visible = selected
	cursor.custom_minimum_size = Vector2(7.0, 9.0)
	cursor.stretch_mode = TextureRect.STRETCH_KEEP_CENTERED
	cursor.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	row.add_child(cursor)

	var icon_rect := TextureRect.new()
	icon_rect.texture = icon
	icon_rect.custom_minimum_size = Vector2(16.0, 16.0)
	icon_rect.stretch_mode = TextureRect.STRETCH_KEEP_CENTERED
	icon_rect.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	row.add_child(icon_rect)

	var name_label := Label.new()
	name_label.text = label.to_upper()
	name_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	name_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	name_label.clip_text = true
	name_label.add_theme_color_override(&"font_color", color)
	row.add_child(name_label)

	if not suffix.is_empty():
		var count := Label.new()
		count.text = suffix
		count.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		count.add_theme_color_override(&"font_color", color)
		row.add_child(count)

	var marker := TextureRect.new()
	marker.texture = equipped_texture
	marker.visible = equipped
	marker.custom_minimum_size = Vector2(7.0, 7.0)
	marker.stretch_mode = TextureRect.STRETCH_KEEP_CENTERED
	marker.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	row.add_child(marker)
	return row


# ---------------------------------------------------------------------------
# Stats tab
# ---------------------------------------------------------------------------
func _refresh_stats() -> void:
	var stats: PlayerStats = GameManager.stats
	var to_next: int = stats.xp_to_next_level()
	_fill_labels(_stats_left, [
		["LEVEL", str(stats.level)],
		["EXPERIENCE", str(stats.experience)],
		["TO NEXT LEVEL", "MAX" if to_next <= 0 else str(to_next)],
		["", ""],
		["HIT POINTS", "%d / %d" % [GameManager.current_hp, GameManager.get_max_hp()]],
		["HEARTS", "%d / %d" % [GameManager.hearts, GameManager.max_hearts]],
		["GOLD", str(GameManager.gold)],
		["PLAY TIME", SaveManager.SlotInfo.format_play_time(GameManager.play_time)],
	])
	_fill_labels(_stats_right, [
		["STRENGTH", _stat_text("strength", GameManager.get_strength())],
		["CONSTITUTION", _stat_text("constitution", GameManager.get_constitution())],
		["DEFENSE", _stat_text("defense", GameManager.get_defense())],
		["LUCK", _stat_text("luck", GameManager.get_luck())],
		["", ""],
		["ATTACK", _attack_text()],
		["RELICS", str(GameManager.unlocked_abilities.size())],
		["ROOMS SEEN", str(GameManager.explored_rooms.size())],
	])
	_info_name.text = "VESPER"
	_info_description.text = "Base stats rise with each level.\nBracketed numbers are what your gear adds."
	_info_stats.text = ""


## "12 (+4)" — the base number, then what the gear contributes.
func _stat_text(stat: String, total: int) -> String:
	var base: int = GameManager.stats.get(stat)
	if total == base:
		return str(base)
	return "%d (%s%d)" % [base, "+" if total > base else "", total - base]


## The damage range the equipped hand would deal to an undefended target.
func _attack_text() -> String:
	var weapon: WeaponData = GameManager.get_primary_weapon()
	if weapon == null:
		return "-"
	var span: Vector2i = Combat.damage_range(weapon.damage, GameManager.get_strength(), 0)
	return "%d - %d" % [span.x, span.y]


func _fill_labels(box: VBoxContainer, rows: Array) -> void:
	_clear(box)
	for entry: Array in rows:
		var row := HBoxContainer.new()
		row.custom_minimum_size = Vector2(0.0, 10.0)
		var name_label := Label.new()
		name_label.text = entry[0]
		name_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		name_label.add_theme_color_override(&"font_color", COLOR_EMPTY)
		row.add_child(name_label)
		var value_label := Label.new()
		value_label.text = entry[1]
		value_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
		value_label.add_theme_color_override(&"font_color", COLOR_ITEM)
		row.add_child(value_label)
		box.add_child(row)


# ---------------------------------------------------------------------------
# Map tab
# ---------------------------------------------------------------------------
## A placeholder until the castle has more than one room: the real fog-of-war
## map belongs to the first wing (SPEC 4.4.3), but the data it will draw from
## — [member GameManager.explored_rooms] — is already being recorded and saved.
func _refresh_map() -> void:
	var rooms: Array[StringName] = GameManager.explored_rooms
	if rooms.is_empty():
		_map_body.text = "NO ROOMS CHARTED"
	else:
		var names := PackedStringArray()
		for room: StringName in rooms:
			names.append(String(room).replace("_", " ").to_upper())
		_map_body.text = "\n".join(names)
	_info_name.text = "CHART"
	_info_description.text = "%d room(s) walked.\nSave rooms and boss chambers are marked once the castle opens up." % rooms.size()
	_info_stats.text = ""


# ---------------------------------------------------------------------------
# System tab
# ---------------------------------------------------------------------------
## Rows are (label, read, write) triples so adding a setting is one entry.
func _build_system_rows() -> void:
	_system_rows.clear()
	_clear(_system_list)
	for i: int in _system_settings().size():
		var row := HBoxContainer.new()
		row.custom_minimum_size = Vector2(0.0, 12.0)
		var cursor := TextureRect.new()
		cursor.name = &"Cursor"
		cursor.texture = cursor_texture
		cursor.custom_minimum_size = Vector2(7.0, 9.0)
		cursor.stretch_mode = TextureRect.STRETCH_KEEP_CENTERED
		cursor.size_flags_vertical = Control.SIZE_SHRINK_CENTER
		row.add_child(cursor)
		var label := Label.new()
		label.name = &"Name"
		label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(label)
		var value := Label.new()
		value.name = &"Value"
		value.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
		value.custom_minimum_size = Vector2(90.0, 0.0)
		row.add_child(value)
		_system_list.add_child(row)
		_system_rows.append(label)


## [label, current value as text, step function] for each settings row.
func _system_settings() -> Array[Array]:
	return [
		["MUSIC", _volume_text(Audio.MUSIC_BUS)],
		["SOUND", _volume_text(Audio.SFX_BUS)],
		["SCREEN SHAKE", "ON" if GameFeel.screen_shake_enabled else "OFF"],
		["HIT STOP", "ON" if GameFeel.hit_stop_enabled else "OFF"],
		["RUMBLE", "ON" if Controls.rumble_enabled else "OFF"],
		["BUTTON PROMPTS", _prompt_text()],
	]


func _refresh_system() -> void:
	var settings: Array[Array] = _system_settings()
	for i: int in _system_list.get_child_count():
		var row: Control = _system_list.get_child(i) as Control
		var selected: bool = i == _system_row
		(row.get_node(^"Cursor") as TextureRect).visible = selected
		var name_label := row.get_node(^"Name") as Label
		name_label.text = settings[i][0]
		name_label.add_theme_color_override(&"font_color", COLOR_HIGHLIGHT if selected else COLOR_ITEM)
		var value_label := row.get_node(^"Value") as Label
		value_label.text = settings[i][1]
		value_label.add_theme_color_override(&"font_color", COLOR_HIGHLIGHT if selected else COLOR_ITEM)
	_info_name.text = "SYSTEM"
	_info_description.text = "Left and right change a setting.\nKey bindings live in Project Settings > Input Map for now."
	_info_stats.text = ""


func _adjust_setting(step: int) -> void:
	match _system_row:
		0:
			_step_volume(Audio.MUSIC_BUS, step)
		1:
			_step_volume(Audio.SFX_BUS, step)
		2:
			GameFeel.screen_shake_enabled = not GameFeel.screen_shake_enabled
		3:
			GameFeel.hit_stop_enabled = not GameFeel.hit_stop_enabled
		4:
			Controls.rumble_enabled = not Controls.rumble_enabled
		5:
			_step_prompts(step)
	Audio.play_sfx(&"menu_move", 0.03, -6.0)
	_refresh_system()


## Bus volume as a 0..10 notch, which is what the row shows and steps.
func _volume_notch(bus: StringName) -> int:
	var index: int = AudioServer.get_bus_index(bus)
	if index < 0:
		return 10
	if AudioServer.is_bus_mute(index):
		return 0
	return clampi(roundi(db_to_linear(AudioServer.get_bus_volume_db(index)) * 10.0), 0, 10)


func _volume_text(bus: StringName) -> String:
	var notch: int = _volume_notch(bus)
	return "OFF" if notch == 0 else ("|".repeat(notch) + "%d" % notch)


func _step_volume(bus: StringName, step: int) -> void:
	var index: int = AudioServer.get_bus_index(bus)
	if index < 0:
		return
	var notch: int = clampi(_volume_notch(bus) + step, 0, 10)
	AudioServer.set_bus_mute(index, notch == 0)
	if notch > 0:
		AudioServer.set_bus_volume_db(index, linear_to_db(notch / 10.0))


func _prompt_text() -> String:
	match Controls.device:
		Controls.Device.PLAYSTATION:
			return "PLAYSTATION"
		Controls.Device.XBOX:
			return "XBOX"
	return "KEYBOARD"


## Cycle auto-detect -> Xbox -> PlayStation -> auto-detect.
func _step_prompts(step: int) -> void:
	var order: Array[Controls.Device] = [
		Controls.Device.KEYBOARD, Controls.Device.XBOX, Controls.Device.PLAYSTATION]
	var next: int = posmod(order.find(Controls.device) + step, order.size())
	if order[next] == Controls.Device.KEYBOARD:
		Controls.auto_detect_device()
		Controls.force_device(Controls.Device.KEYBOARD)
	else:
		Controls.force_device(order[next])


# ---------------------------------------------------------------------------
# Chrome
# ---------------------------------------------------------------------------
func _build_tab_bar() -> void:
	_tab_labels.clear()
	_clear(_tab_bar)
	for tab: Tab in Tab.values():
		var label := Label.new()
		label.text = Tab.keys()[tab]
		_tab_bar.add_child(label)
		_tab_labels.append(label)


func _refresh_all() -> void:
	for tab: Tab in _pages:
		_pages[tab].visible = tab == _tab
	for i: int in _tab_labels.size():
		_tab_labels[i].add_theme_color_override(
			&"font_color", COLOR_HIGHLIGHT if i == _tab else COLOR_EMPTY)
	match _tab:
		Tab.EQUIPMENT:
			_refresh_equipment()
		Tab.STATS:
			_refresh_stats()
		Tab.MAP:
			_refresh_map()
		Tab.SYSTEM:
			_refresh_system()
	_refresh_hint()


## The info box describes whatever the cursor is on: the item that would be
## equipped, or the one already in the slot when the cursor is on the left.
func _update_info() -> void:
	var item: ItemData = null
	if _column == ITEMS and _item_row < _candidates.size():
		item = _candidates[_item_row]
	elif _slot_row != CONSUMABLE_ROW:
		item = GameManager.get_equipped(_slot_row)
	if item == null:
		_info_name.text = "NOTHING EQUIPPED" if _column == SLOTS else "REMOVE"
		_info_description.text = "" if _column == SLOTS else "Leave the slot empty."
		_info_stats.text = ""
		return
	_info_name.text = item.display_name.to_upper()
	_info_description.text = item.description
	_info_stats.text = _item_stats_text(item)


func _item_stats_text(item: ItemData) -> String:
	var parts := PackedStringArray()
	if item is WeaponData:
		var weapon := item as WeaponData
		var span: Vector2i = Combat.damage_range(weapon.damage, GameManager.get_strength(), 0)
		parts.append("DAMAGE %d-%d" % [span.x, span.y])
		parts.append("REACH %d" % roundi(weapon.get_reach()))
		parts.append("SPEED %.2f" % weapon.speed_scale)
	elif item is SubWeaponData:
		var sub := item as SubWeaponData
		parts.append("HEARTS %d" % sub.heart_cost)
		parts.append("ON SCREEN %d" % sub.max_active)
		if sub.damage > 0:
			parts.append("DAMAGE %d" % sub.damage)
	elif item is ArmorData:
		parts.append("DEFENSE %d" % (item as ArmorData).defense)
	elif item is ConsumableData:
		var consumable := item as ConsumableData
		if consumable.heal_amount > 0:
			parts.append("HEALS %d" % consumable.heal_amount)
		if consumable.heart_amount > 0:
			parts.append("HEARTS %d" % consumable.heart_amount)
	if item.has_modifiers():
		parts.append(item.get_modifier_text())
	return "   ".join(parts)


func _on_device_changed(_device: Controls.Device) -> void:
	_refresh_hint()
	if is_open and _tab == Tab.SYSTEM:
		_refresh_system()


## Name the buttons the player is actually holding. On a pad the idiomatic
## pair is confirm = bottom face button, cancel = right face button; on the
## keyboard it is the attack key and the key that opened the menu.
func _refresh_hint() -> void:
	var on_pad: bool = Controls.is_using_pad()
	var confirm: StringName = &"jump" if on_pad else &"attack"
	var cancel: StringName = &"backdash" if on_pad else &"pause_menu"
	_hint.text = "%s MOVE   %s/%s TABS   %s EQUIP   %s CLOSE" % [
		Controls.get_action_label(&"move_down"),
		Controls.get_action_label(&"switch_subweapon"),
		Controls.get_action_label(&"attack_secondary"),
		Controls.get_action_label(confirm),
		Controls.get_action_label(cancel),
	]


func _on_player_died() -> void:
	_locked = true
	close()


func _clear(container: Node) -> void:
	for child: Node in container.get_children():
		container.remove_child(child)
		child.queue_free()
