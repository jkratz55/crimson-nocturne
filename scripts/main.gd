## Game root: owns the current room, HUD, menus and overlays; handles pause
## and the death -> respawn loop.
##
## In a full game this node would also own a RoomManager (room streaming and
## transitions) and the title screen.
extends Node

@export var restart_delay: float = 2.5
@export var fade_time: float = 0.8

@onready var pause_menu: PauseMenu = $PauseMenu
@onready var save_menu: SaveMenu = $SaveMenu
@onready var fade: ColorRect = %Fade
@onready var death_label: Label = %DeathLabel
@onready var pause_label: Label = %PauseLabel

var _is_restarting: bool = false


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	death_label.visible = false
	pause_label.visible = false
	Events.player_died.connect(_on_player_died)
	Controls.pad_disconnected.connect(_on_pad_disconnected)
	fade.color.a = 1.0
	create_tween().tween_property(fade, "color:a", 0.0, fade_time)


func _unhandled_input(event: InputEvent) -> void:
	# The menus are modal: they run their own pause and eat the input.
	if pause_menu.is_open or save_menu.is_open:
		return
	if event.is_action_pressed(&"pause") and not _is_restarting:
		_set_paused(not get_tree().paused)
		get_viewport().set_input_as_handled()


func _set_paused(paused: bool, message: String = "- PAUSED -") -> void:
	get_tree().paused = paused
	pause_label.text = message
	pause_label.visible = paused


## Losing the pad mid-jump would leave the player watching Vesper walk into a
## skeleton, so freeze the game and say what happened. Any pause input (or a
## reconnected pad's Start button) resumes.
func _on_pad_disconnected() -> void:
	if _is_restarting or get_tree().paused or pause_menu.is_open or save_menu.is_open:
		return
	_set_paused(true, "CONTROLLER DISCONNECTED")


## Death costs nothing but the walk back (SPEC 4.4.2): HP and hearts are
## refilled, everything earned since the last save is kept, and the room is
## rebuilt with the player standing at the last shrine they used.
func _on_player_died() -> void:
	if _is_restarting:
		return
	_is_restarting = true
	await get_tree().create_timer(restart_delay * 0.4).timeout
	death_label.visible = true
	await get_tree().create_timer(restart_delay * 0.6).timeout
	var tween: Tween = create_tween()
	tween.tween_property(fade, "color:a", 1.0, fade_time)
	await tween.finished
	GameFeel.clear_hit_stop()
	Controls.stop_rumble()
	GameManager.respawn()
	get_tree().reload_current_scene()
