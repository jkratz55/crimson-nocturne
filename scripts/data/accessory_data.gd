## Necklaces and rings: pure stat-modifier equipment (SPEC 4.3).
##
## [member slot] decides where it can go. Two ring slots exist, and the same
## ring resource may not occupy both at once — [method GameManager.equip]
## moves it rather than duplicating it.
class_name AccessoryData
extends ItemData

enum Slot { NECKLACE, RING }

@export var slot: Slot = Slot.RING
