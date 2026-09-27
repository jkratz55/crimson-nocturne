## A unique thing lying in the castle: a weapon on a plinth, a ring in a
## chest, a relic behind a false wall, a Heart Max Up in a dead end.
##
## Unlike a [Pickup], which is rolled from a drop table and forgotten, a world
## item is taken exactly once for the whole game (SPEC 4.7). That is what
## [member world_item_id] is for: it goes into the save file, and on every
## later visit the node deletes itself before the player ever sees it.
##
## Scene contract: an [Area2D] root (this script) with a [CollisionShape2D]
## and a [Sprite2D] named `Sprite`.
class_name WorldItem
extends Area2D

## What taking it does.
enum Grant {
	ITEM,          ## Put [member item] in the inventory.
	HEART_MAX_UP,  ## Raise the heart ceiling by [member amount] (SPEC 4.2.2).
	GOLD,          ## A fixed purse rather than a random drop.
}

## Unique id remembered in the save file. Two world items must never share
## one, or taking either will make both disappear.
@export var world_item_id: StringName = &""
@export var grant: Grant = Grant.ITEM
## The item handed over when [member grant] is [constant Grant.ITEM]. Its icon
## is used for the sprite if the scene does not set one.
@export var item: ItemData
## Hearts of capacity, or gold, for the other two grants.
@export_range(0, 9999) var amount: int = 5
## Sprite to draw. Leave it null for an [constant Grant.ITEM] and the item's
## own icon is used; the other grants have no item, so they need one here.
@export var icon_override: Texture2D
## Equip the item immediately if its slot is empty. Off for things the player
## should choose to wear.
@export var auto_equip: bool = true
@export var bob_height: float = 2.0
@export var bob_speed: float = 2.4
@export var collect_sfx: StringName = &"heart_pickup"

@onready var sprite: Sprite2D = $Sprite

var _age: float = 0.0
var _origin: float = 0.0
var _taken: bool = false


func _ready() -> void:
	if world_item_id.is_empty():
		push_warning("WorldItem at %s has no world_item_id; it will respawn on every load."
			% global_position)
	elif GameManager.is_world_item_collected(world_item_id):
		queue_free()
		return
	_origin = position.y
	if icon_override != null:
		sprite.texture = icon_override
	elif item != null and sprite.texture == null:
		sprite.texture = item.icon
	body_entered.connect(_on_body_entered)


func _process(delta: float) -> void:
	_age += delta
	position.y = _origin + sin(_age * bob_speed) * bob_height


func _on_body_entered(body: Node2D) -> void:
	var player := body as Player
	if _taken or player == null or player.state == Player.State.DEAD:
		return
	_taken = true
	# Record it first: the grant may open a menu or a dialogue later, and the
	# item must already count as taken by then.
	GameManager.collect_world_item(world_item_id)
	Audio.play_sfx(collect_sfx)
	Events.notice_posted.emit(_apply_grant())
	queue_free()


## Hand over the goods and return the line the HUD should show.
func _apply_grant() -> String:
	match grant:
		Grant.HEART_MAX_UP:
			GameManager.raise_max_hearts(amount)
			return "HEART MAX +%d" % amount
		Grant.GOLD:
			GameManager.add_gold(amount)
			return "%d GOLD" % amount
	if item == null:
		return ""
	GameManager.add_item(item)
	if auto_equip:
		var slot: int = GameManager.default_slot_for(item)
		if slot != -1 and GameManager.get_equipped(slot) == null:
			GameManager.equip(slot, item)
	return item.display_name.to_upper()
