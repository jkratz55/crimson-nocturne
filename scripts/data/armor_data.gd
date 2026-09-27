## Body armour: the equipment slot that mainly buys raw Defense (SPEC 4.3).
##
## Elemental resistances are deferred (the spec marks them MAY); when they
## arrive they belong here as a typed dictionary of element -> multiplier.
class_name ArmorData
extends ItemData

@export_group("Protection")
## Added to the player's Defense stat on top of any [ItemData] modifiers.
## Kept separate so a suit of armour reads as "Defense 12" in the menu
## rather than as an anonymous bonus.
@export_range(0, 999) var defense: int = 0
