## The slot picker a [SavePoint] opens (SPEC 3, 4.4.2).
##
## Three slots, each showing what is in it — level, play time, gold — so the
## player can tell them apart before overwriting one. Confirming writes the
## run through [SaveManager], makes this shrine the respawn point, and fully
## restores HP and hearts, which is what the candle in a Castlevania save
## room has always done.
##
## Modal in the same way [PauseMenu] is: it pauses the tree itself and marks
## every input it sees as handled.
class_name SaveMenu
extends CanvasLayer

signal opened
signal closed

const COLOR_ROW: Color = Color(0.72, 0.70, 0.80)
const COLOR_HIGHLIGHT: Color = Color(0.94, 0.78, 0.36)
const COLOR_EMPTY: Color = Color(0.45, 0.43, 0.55)
const ROW_HEIGHT: float = 22.0

@export var cursor_texture: Texture2D

@onready var _slot_list: VBoxContainer = %SlotList
@onready var _message: Label = %Message
@onready var _hint: Label = %Hint

var is_open: bool = false

var _row: int = 0
var _room_id: StringName = &""
var _spawn_position: Vector2 = Vector2.ZERO
## Set while the confirmation line is up and input is ignored.
var _committing: bool = false


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	visible = false
	Events.save_point_activated.connect(open)
	Controls.device_changed.connect(_on_device_changed)
	_refresh_hint()


func _unhandled_input(event: InputEvent) -> void:
	if not is_open:
		return
	if _committing:
		get_viewport().set_input_as_handled()
		return
	if event.is_action_pressed(&"backdash") or event.is_action_pressed(&"pause") \
			or event.is_action_pressed(&"pause_menu"):
		close()
	elif event.is_action_pressed(&"move_down"):
		_move(1)
	elif event.is_action_pressed(&"move_up"):
		_move(-1)
	elif event.is_action_pressed(&"attack") or event.is_action_pressed(&"jump") \
			or event.is_action_pressed(&"subweapon"):
		_commit()
	get_viewport().set_input_as_handled()


## Show the picker for a save point in [param room_id] at [param spawn_position].
func open(room_id: StringName, spawn_position: Vector2) -> void:
	if is_open or get_tree().paused:
		return
	_room_id = room_id
	_spawn_position = spawn_position
	_row = GameManager.current_slot if GameManager.current_slot >= 0 else maxi(0, SaveManager.most_recent_slot())
	_committing = false
	_message.text = ""
	_refresh()
	is_open = true
	visible = true
	get_tree().paused = true
	Audio.play_sfx(&"menu_select", 0.0, -3.0)
	opened.emit()


func close() -> void:
	if not is_open:
		return
	is_open = false
	visible = false
	get_tree().paused = false
	Audio.play_sfx(&"menu_move", 0.0, -3.0)
	closed.emit()


func _move(step: int) -> void:
	_row = posmod(_row + step, SaveManager.SLOT_COUNT)
	Audio.play_sfx(&"menu_move", 0.03, -6.0)
	_refresh()


func _commit() -> void:
	_committing = true
	# The checkpoint has to be in place before the write, or the file would
	# remember the previous shrine.
	var previous_run: Dictionary = GameManager.to_save_data()
	GameManager.set_checkpoint(_room_id, _spawn_position)
	var ok: bool = SaveManager.save_to_slot(_row)
	if not ok:
		GameManager.apply_save_data(previous_run)
		_committing = false
		_message.text = "SAVE FAILED. PICK A SLOT TO RETRY."
		return
	_message.text = "THE NIGHT IS RECORDED."
	Audio.play_sfx(&"menu_select", 0.0)
	_refresh()
	await get_tree().create_timer(1.1, true, false, true).timeout
	if ok:
		Events.notice_posted.emit("GAME SAVED")
	close()


func _refresh() -> void:
	for child: Node in _slot_list.get_children():
		_slot_list.remove_child(child)
		child.queue_free()
	for info: SaveManager.SlotInfo in SaveManager.get_all_slot_info():
		_slot_list.add_child(_make_row(info, info.slot == _row))


func _make_row(info: SaveManager.SlotInfo, selected: bool) -> Control:
	var row := HBoxContainer.new()
	row.custom_minimum_size = Vector2(0.0, ROW_HEIGHT)
	row.add_theme_constant_override(&"separation", 4)

	var cursor := TextureRect.new()
	cursor.texture = cursor_texture
	cursor.visible = selected
	cursor.custom_minimum_size = Vector2(7.0, 9.0)
	cursor.stretch_mode = TextureRect.STRETCH_KEEP_CENTERED
	cursor.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	row.add_child(cursor)

	var color: Color = COLOR_HIGHLIGHT if selected else (COLOR_ROW if info.exists else COLOR_EMPTY)
	var name_label := Label.new()
	name_label.text = "SLOT %d" % (info.slot + 1)
	name_label.custom_minimum_size = Vector2(56.0, 0.0)
	name_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	name_label.add_theme_color_override(&"font_color", color)
	row.add_child(name_label)

	var summary := Label.new()
	summary.text = info.summary()
	summary.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	summary.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	summary.clip_text = true
	summary.add_theme_color_override(&"font_color", color)
	row.add_child(summary)
	return row


func _on_device_changed(_device: Controls.Device) -> void:
	_refresh_hint()


func _refresh_hint() -> void:
	var on_pad: bool = Controls.is_using_pad()
	_hint.text = "%s PICK   %s SAVE   %s LEAVE" % [
		Controls.get_action_label(&"move_down"),
		Controls.get_action_label(&"jump" if on_pad else &"attack"),
		Controls.get_action_label(&"backdash" if on_pad else &"pause_menu"),
	]
