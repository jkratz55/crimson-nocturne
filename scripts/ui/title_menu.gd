## Application entry: restore a run before its world is instantiated.
class_name TitleMenu
extends Control

const GAME_SCENE: String = "res://scenes/main.tscn"
const COLOR_ROW: Color = Color(0.72, 0.70, 0.80)
const COLOR_HIGHLIGHT: Color = Color(0.94, 0.78, 0.36)
## The selected option's text over the selection bar (the theme's white).
const COLOR_SELECTED: Color = Color(0.94, 0.94, 0.97)
## The selection bar: 11 px tall like every menu's, starting 2 px above the
## row so the caps on the row's top line sit centred on it.
const BAR_HEIGHT: float = 11.0
const BAR_LEAD: float = 2.0

@onready var options: VBoxContainer = %Options
@onready var message: Label = %Message
@onready var hint: Label = %Hint
## SotN-style pulsing bar behind the selected option (optional node).
@onready var _bar: Control = get_node_or_null(^"%TitleBar") as Control

var _row: int = 0
var _choosing_slot: bool = false
var _starting: bool = false


func _ready() -> void:
	get_tree().paused = false
	GameManager.set_process(false)
	GameFeel.clear_hit_stop()
	Controls.device_changed.connect(_on_device_changed)
	# The rows are rebuilt on every move; place the bar once they are laid out.
	options.sort_children.connect(_place_bar)
	_show_message("")
	_refresh()


func _unhandled_input(event: InputEvent) -> void:
	if _starting:
		return
	# Changing scenes detaches this node immediately, so consume input first.
	get_viewport().set_input_as_handled()
	if event.is_action_pressed(&"move_down"):
		_row = posmod(_row + 1, SaveManager.SLOT_COUNT + 1 if _choosing_slot else 3)
	elif event.is_action_pressed(&"move_up"):
		_row = posmod(_row - 1, SaveManager.SLOT_COUNT + 1 if _choosing_slot else 3)
	elif event.is_action_pressed(&"backdash") or event.is_action_pressed(&"pause"):
		_choosing_slot = false
		_row = 0
	elif event.is_action_pressed(&"attack") or event.is_action_pressed(&"jump"):
		_confirm()
	else:
		return
	if not _starting:
		_refresh()


func _confirm() -> void:
	_show_message("")
	if _choosing_slot:
		if _row == SaveManager.SLOT_COUNT:
			_choosing_slot = false
			_row = 0
		else:
			_load_slot(_row)
		return
	match _row:
		0:
			_load_slot(SaveManager.most_recent_slot())
		1:
			GameManager.start_new_game()
			_start_game()
		2:
			_choosing_slot = true
			_row = maxi(0, SaveManager.most_recent_slot())


func _load_slot(slot: int) -> void:
	var info: SaveManager.SlotInfo = SaveManager.get_slot_info(slot)
	if not info.exists:
		_show_message("NO READABLE SAVE IN THIS SLOT.")
		return
	# Only the Crimson Hall is shipped. Refuse unsupported rooms before
	# changing the run; extend this routing when more room scenes are added.
	if info.room != &"" and info.room != &"crimson_hall":
		_show_message("THIS SAVE'S ROOM IS UNAVAILABLE.")
		return
	if not SaveManager.load_from_slot(slot):
		_show_message("THE SAVE COULD NOT BE LOADED.")
		return
	_start_game()


func _start_game() -> void:
	_starting = true
	# Confirm is also a gameplay action: do not carry it into the new room.
	Input.action_release(&"attack")
	Input.action_release(&"jump")
	GameManager.set_process(true)
	if get_tree().change_scene_to_file(GAME_SCENE) != OK:
		_starting = false
		GameManager.set_process(false)
		_show_message("THE GAME COULD NOT BE OPENED.")


## The status line sits on a notice plate sized to its text, shown only while
## there is something to say (an empty plate would float over the spires).
func _show_message(text: String) -> void:
	message.text = text
	message.visible = not text.is_empty()


## Behind the selected row, after the VBox has laid the rows out (visual only).
func _place_bar() -> void:
	if _bar == null:
		return
	var rows: Array[Node] = options.get_children()
	if _row >= rows.size():
		_bar.visible = false
		return
	var row := rows[_row] as Control
	_bar.visible = true
	# One text line tall like every menu's bar, with the row's caps (its top
	# 7 px) centred on it.
	_bar.position.y = options.position.y + row.position.y - BAR_LEAD
	_bar.size.y = BAR_HEIGHT


func _refresh() -> void:
	for child: Node in options.get_children():
		options.remove_child(child)
		child.queue_free()
	var rows: Array[String] = []
	if _choosing_slot:
		for info: SaveManager.SlotInfo in SaveManager.get_all_slot_info():
			rows.append("SLOT %d  %s" % [info.slot + 1, info.summary()])
		rows.append("BACK")
	else:
		rows.assign(["CONTINUE", "NEW GAME", "LOAD SLOT"])
	for i: int in rows.size():
		var label := Label.new()
		# With the selection bar marking the row, the text stays put (no "> "
		# prefix) and turns white; without it, fall back to the old marker.
		var selected: bool = i == _row
		if _bar == null:
			label.text = ("> " if selected else "  ") + rows[i]
		else:
			label.text = rows[i]
		label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		var selected_color: Color = COLOR_SELECTED if _bar != null else COLOR_HIGHLIGHT
		label.add_theme_color_override(&"font_color", selected_color if selected else COLOR_ROW)
		options.add_child(label)
	hint.text = "%s SELECT   %s CONFIRM   %s BACK" % [
		Controls.get_action_label(&"move_down"),
		Controls.get_action_label(&"jump" if Controls.is_using_pad() else &"attack"),
		Controls.get_action_label(&"backdash" if Controls.is_using_pad() else &"pause")]


func _on_device_changed(_device: Controls.Device) -> void:
	_refresh()
