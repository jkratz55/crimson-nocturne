## Root script for a room (one screen-group of the castle map).
##
## Responsibilities:
## - Define the room's pixel bounds and feed them to the [RoomCamera].
## - Start the room's music and announce the area name.
## - Spawn floating damage numbers for anything hit inside the room.
## - Bring the backdrop to life with [AmbientFx] (visual only).
##
## Future work (full Metroidvania): doors/transitions call into a
## map/world manager that swaps rooms and keeps the player instance.
class_name Room
extends Node2D

## Stable id for save data: the checkpoint the player last used, and the
## fog-of-war record of which rooms have been seen (SPEC 3, 4.4.3). Unlike
## [member display_name] it is never shown, so it can stay put while the
## room's name changes.
@export var room_id: StringName = &"room"
@export var display_name: String = "Room"
## Room size in tiles. The camera is clamped to this rectangle.
@export var size_in_tiles: Vector2i = Vector2i(64, 18)
@export var tile_size: int = 16
@export var music: AudioStream
@export var damage_number_scene: PackedScene
@export var player: Player
@export var camera: RoomCamera


func _ready() -> void:
	GameManager.mark_room_explored(room_id)
	place_player_at_checkpoint()
	if camera:
		camera.set_room_bounds(get_bounds())
		camera.target = player
		camera.global_position = player.global_position if player else Vector2.ZERO
		camera.reset_smoothing()
	if music:
		Audio.play_music(music)
	Events.damage_dealt.connect(_on_damage_dealt)
	Events.area_entered.emit.call_deferred(display_name)
	# Motes in the moon shafts, twinkling stars, a far bat: drawn inside the
	# backdrop's own Parallax2D layers, never touching gameplay.
	AmbientFx.populate(self)


## Put the player back on the save point they last used, if it is in this
## room. Called before the camera is set up so it does not snap afterwards.
## Returns true if the player was actually moved.
func place_player_at_checkpoint() -> bool:
	if player == null or GameManager.checkpoint_room != room_id:
		return false
	player.global_position = GameManager.checkpoint_position
	return true


## Room rectangle in world pixels.
func get_bounds() -> Rect2i:
	return Rect2i(Vector2i(global_position), size_in_tiles * tile_size)


func _on_damage_dealt(amount: int, world_position: Vector2, is_player: bool) -> void:
	if damage_number_scene == null:
		return
	var number := damage_number_scene.instantiate() as DamageNumber
	number.position = to_local(world_position)
	add_child(number)
	number.setup(amount, is_player)
