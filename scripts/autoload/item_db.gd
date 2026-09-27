## Registry of every [ItemData] in the project, keyed by id (autoload: [code]ItemDB[/code]).
##
## Save files, shop lists and world pickups all refer to items by their
## stable [member ItemData.id] rather than by resource path, so renaming or
## moving a `.tres` can never invalidate a save. This node is what turns an
## id back into the resource.
##
## Content is authored, not registered: dropping a new `.tres` into one of
## [constant ITEM_DIRS] is all it takes. Duplicate or missing ids are
## reported as errors at boot rather than failing silently much later.
extends Node

## Directories scanned at startup. Add to this when a new item category
## gets its own folder.
const ITEM_DIRS: PackedStringArray = [
	"res://resources/weapons",
	"res://resources/subweapons",
	"res://resources/armor",
	"res://resources/accessories",
	"res://resources/consumables",
	"res://resources/relics",
]

var _by_id: Dictionary[StringName, ItemData] = {}


func _ready() -> void:
	for directory: String in ITEM_DIRS:
		_scan(directory)


## The item with [param id], or null if nothing is registered under it.
func get_item(id: StringName) -> ItemData:
	return _by_id.get(id)


func has_item(id: StringName) -> bool:
	return _by_id.has(id)


## Every registered item, sorted by display name — the order shops and
## debug listings want.
func all_items() -> Array[ItemData]:
	var items: Array[ItemData] = []
	items.assign(_by_id.values())
	items.sort_custom(func(a: ItemData, b: ItemData) -> bool: return a.display_name < b.display_name)
	return items


## Every registered item that `is` [param type], e.g.
## [code]ItemDB.items_of_type(ArmorData)[/code].
func items_of_type(type: Script) -> Array[ItemData]:
	return all_items().filter(func(item: ItemData) -> bool: return is_instance_of(item, type))


## Resolve a list of ids to items, skipping (and reporting) unknown ones.
func resolve_all(ids: Array) -> Array[ItemData]:
	var items: Array[ItemData] = []
	for id: Variant in ids:
		var item: ItemData = get_item(StringName(id))
		if item == null:
			push_warning("ItemDB: save refers to unknown item id '%s'; skipping." % id)
			continue
		items.append(item)
	return items


func _scan(directory: String) -> void:
	if not DirAccess.dir_exists_absolute(directory):
		return
	for file_name: String in DirAccess.get_files_at(directory):
		# Exported builds convert .tres to binary and leave a .remap behind;
		# the original path is what ResourceLoader still expects.
		var name: String = file_name.trim_suffix(".remap")
		if not (name.ends_with(".tres") or name.ends_with(".res")):
			continue
		var item := ResourceLoader.load(directory.path_join(name)) as ItemData
		if item == null:
			continue
		_register(item, directory.path_join(name))


func _register(item: ItemData, path: String) -> void:
	if item.id.is_empty():
		push_error("ItemDB: '%s' has no id; it can never be saved or bought." % path)
		return
	if _by_id.has(item.id):
		push_error("ItemDB: duplicate item id '%s' (%s and %s)."
			% [item.id, _by_id[item.id].resource_path, path])
		return
	_by_id[item.id] = item
