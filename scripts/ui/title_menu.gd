## Application entry: restore a run before its world is instantiated.
class_name TitleMenu
extends Control

const GAME_SCENE: String = "res://scenes/main.tscn"

@onready var options: VBoxContainer = %Options
@onready var message: Label = %Message
@onready var hint: Label = %Hint

var _row: int = 0
var _choosing_slot: bool = false
var _starting: bool = false


func _ready() -> void:
	get_tree().paused = false
	GameManager.set_process(false)
	GameFeel.clear_hit_stop()
	Controls.device_changed.connect(_on_device_changed)
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
	message.text = ""
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
		message.text = "NO READABLE SAVE IN THIS SLOT."
		return
	# Only the Crimson Hall is shipped. Refuse unsupported rooms before
	# changing the run; extend this routing when more room scenes are added.
	if info.room != &"" and info.room != &"crimson_hall":
		message.text = "THIS SAVE'S ROOM IS UNAVAILABLE."
		return
	if not SaveManager.load_from_slot(slot):
		message.text = "THE SAVE COULD NOT BE LOADED."
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
		message.text = "THE GAME COULD NOT BE OPENED."


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
		label.text = ("> " if i == _row else "  ") + rows[i]
		label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		label.add_theme_color_override(&"font_color",
			Color(0.94, 0.78, 0.36) if i == _row else Color(0.72, 0.70, 0.80))
		options.add_child(label)
	hint.text = "%s SELECT   %s CONFIRM   %s BACK" % [
		Controls.get_action_label(&"move_down"),
		Controls.get_action_label(&"jump" if Controls.is_using_pad() else &"attack"),
		Controls.get_action_label(&"backdash" if Controls.is_using_pad() else &"pause")]


func _on_device_changed(_device: Controls.Device) -> void:
	_refresh()
