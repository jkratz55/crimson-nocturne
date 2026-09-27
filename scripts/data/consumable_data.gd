## A stackable, single-use item — the merchant's stock in trade (SPEC 4.7).
##
## Consumables are the one inventory entry that is counted rather than owned
## once, so [GameManager] keeps them in their own quantity map.
class_name ConsumableData
extends ItemData

@export_group("Effect")
## Hit points restored on use. 0 for items that do something else.
@export_range(0, 9999) var heal_amount: int = 0
## Hearts restored on use, clamped to the player's current maximum.
@export_range(0, 999) var heart_amount: int = 0
@export var use_sfx: StringName = &"heart_pickup"
