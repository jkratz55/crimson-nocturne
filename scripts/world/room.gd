## Root script for a room (one screen-group of the castle map).
##
## Responsibilities:
## - Define the room's pixel bounds and feed them to the [RoomCamera].
## - Start the room's music and announce the area name.
## - Spawn floating damage numbers for anything hit inside the room.
##
## Future work (full Metroidvania): doors/transitions call into a
## map/world manager that swaps rooms and keeps the player instance.
class_name Room
extends Node2D

@export var display_name: String = "Room"
## Room size in tiles. The camera is clamped to this rectangle.
@export var size_in_tiles: Vector2i = Vector2i(64, 18)
@export var tile_size: int = 16
@export var music: AudioStream
@export var damage_number_scene: PackedScene
@export var player: Player
@export var camera: RoomCamera


func _ready() -> void:
	if camera:
		camera.set_room_bounds(get_bounds())
		camera.target = player
		camera.global_position = player.global_position if player else Vector2.ZERO
		camera.reset_smoothing()
	if music:
		Audio.play_music(music)
	Events.damage_dealt.connect(_on_damage_dealt)
	Events.area_entered.emit.call_deferred(display_name)


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
