## Base class for everything that can sit in Vesper's inventory.
##
## Every concrete item type ([WeaponData], [SubWeaponData], [ArmorData],
## [AccessoryData], [ConsumableData], [RelicData]) extends this, so the
## inventory, equip menu, shop and save file can all treat items uniformly.
##
## [b]Identity[/b][br]
## [member id] is what save files and shop lists store — never the resource
## path, which would break the moment a file is renamed or moved. It must be
## unique across the whole project; [ItemDB] refuses duplicates at boot.
##
## [b]Stat modifiers[/b][br]
## Any item may carry flat and percentage modifiers to the four stats
## (SPEC 4.3). They only count while the item is equipped, and are applied
## by [GameManager]: all flat bonuses are summed first, then the percentages
## are applied to that subtotal.
class_name ItemData
extends Resource

@export var id: StringName = &""
@export var display_name: String = "Item"
@export_multiline var description: String = ""
## Icon shown in the equip menu, shop and HUD.
@export var icon: Texture2D
## Merchant price in gold. 0 means "not sold in any shop".
@export_range(0, 999999) var price: int = 0

@export_group("Stat Modifiers")
@export_subgroup("Flat")
@export_range(-99, 99) var strength_bonus: int = 0
@export_range(-99, 99) var constitution_bonus: int = 0
@export_range(-99, 99) var defense_bonus: int = 0
@export_range(-99, 99) var luck_bonus: int = 0
@export_subgroup("Percent")
## Fractions, not percentages: 0.1 means +10%.
@export_range(-1.0, 3.0, 0.01) var strength_percent: float = 0.0
@export_range(-1.0, 3.0, 0.01) var constitution_percent: float = 0.0
@export_range(-1.0, 3.0, 0.01) var defense_percent: float = 0.0
@export_range(-1.0, 3.0, 0.01) var luck_percent: float = 0.0


## Human-readable summary of this item's modifiers, for the menu and shop.
## Empty when the item changes no stats.
func get_modifier_text() -> String:
	var parts := PackedStringArray()
	for row: Array in _modifier_rows():
		var flat: int = row[1]
		var percent: float = row[2]
		if flat != 0:
			parts.append("%s%d %s" % ["+" if flat > 0 else "", flat, row[0]])
		if not is_zero_approx(percent):
			parts.append("%s%d%% %s" % ["+" if percent > 0.0 else "", roundi(percent * 100.0), row[0]])
	return "  ".join(parts)


## True when the item changes no stats at all.
func has_modifiers() -> bool:
	for row: Array in _modifier_rows():
		if row[1] != 0 or not is_zero_approx(row[2]):
			return true
	return false


## [[label, flat, percent], ...] in the canonical stat order.
func _modifier_rows() -> Array[Array]:
	return [
		["STR", strength_bonus, strength_percent],
		["CON", constitution_bonus, constitution_percent],
		["DEF", defense_bonus, defense_percent],
		["LCK", luck_bonus, luck_percent],
	]
