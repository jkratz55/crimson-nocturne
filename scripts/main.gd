## Game root: owns the current room, HUD and overlays; handles pause and
## the death -> restart loop.
##
## In a full game this node would also own a RoomManager (room streaming
## and transitions), save/load and menus.
extends Node

@export var restart_delay: float = 2.5
@export var fade_time: float = 0.8

@onready var fade: ColorRect = %Fade
@onready var death_label: Label = %DeathLabel
@onready var pause_label: Label = %PauseLabel

var _is_restarting: bool = false


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	death_label.visible = false
	pause_label.visible = false
	Events.player_died.connect(_on_player_died)
	fade.color.a = 1.0
	create_tween().tween_property(fade, "color:a", 0.0, fade_time)


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed(&"pause") and not _is_restarting:
		get_tree().paused = not get_tree().paused
		pause_label.visible = get_tree().paused
		get_viewport().set_input_as_handled()


func _on_player_died() -> void:
	_is_restarting = true
	await get_tree().create_timer(restart_delay * 0.4).timeout
	death_label.visible = true
	await get_tree().create_timer(restart_delay * 0.6).timeout
	var tween: Tween = create_tween()
	tween.tween_property(fade, "color:a", 1.0, fade_time)
	await tween.finished
	GameFeel.clear_hit_stop()
	get_tree().reload_current_scene()
