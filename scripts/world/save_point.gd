## The shrine in a save room (SPEC 4.4.2).
##
## Standing in its light and pressing Up opens the slot picker; confirming
## writes the whole run to disk, fully restores HP and hearts, and makes this
## spot the place death sends you back to.
##
## Up is the classic Castlevania "use the thing you are standing on" input and
## does nothing else in gameplay, so it needs no binding of its own. The save
## point never touches a menu directly: it announces itself on [Events] and
## whatever is drawing UI answers.
##
## Scene contract: an [Area2D] root (this script) with a [CollisionShape2D],
## an [AnimatedSprite2D] named `Sprite` and a [Label] named `Prompt`.
class_name SavePoint
extends Node2D

## Where the player is put down on respawn, relative to this node.
@export var respawn_offset: Vector2 = Vector2(0.0, 0.0)
## Shown above the shrine while the player is standing in it.
@export var prompt_format: String = "%s  SAVE"

@onready var area: Area2D = $Area
@onready var prompt: Label = $Prompt

var _player: Player


func _ready() -> void:
	add_to_group(&"save_points")
	prompt.visible = false
	area.body_entered.connect(_on_body_entered)
	area.body_exited.connect(_on_body_exited)
	Controls.device_changed.connect(_on_device_changed)
	_refresh_prompt()


func _unhandled_input(event: InputEvent) -> void:
	if _player == null or not event.is_action_pressed(&"move_up"):
		return
	# Only from a standing rest: mid-swing or mid-jump is a misfire.
	if _player.state != Player.State.IDLE or not _player.is_on_floor():
		return
	get_viewport().set_input_as_handled()
	Events.save_point_activated.emit(_room_id(), global_position + respawn_offset)


## The id the checkpoint is filed under — the containing [Room]'s, so a save
## survives the room being reloaded around it.
func _room_id() -> StringName:
	var room := owner as Room
	return room.room_id if room != null else &""


func _on_body_entered(body: Node2D) -> void:
	var player := body as Player
	if player == null:
		return
	_player = player
	prompt.visible = true


func _on_body_exited(body: Node2D) -> void:
	if body == _player:
		_player = null
		prompt.visible = false


func _on_device_changed(_device: Controls.Device) -> void:
	_refresh_prompt()


func _refresh_prompt() -> void:
	prompt.text = prompt_format % Controls.get_action_label(&"move_up")
