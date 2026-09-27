## Validates untrusted JSON before any live run state is changed.
class_name SaveData
extends RefCounted

const NUMBER_LIMIT: float = 1_000_000_000.0
const NAME_ARRAYS: Array[String] = ["inventory", "collected_world_items",
	"defeated_bosses", "unlocked_abilities", "explored_rooms"]


static func valid_number(value: Variant, minimum: float = 0.0,
		maximum: float = NUMBER_LIMIT, integer: bool = true) -> bool:
	if value is not int and value is not float:
		return false
	var number: float = float(value)
	return is_finite(number) and number >= minimum and number <= maximum \
		and (not integer or number == floor(number))


static func valid_name(value: Variant) -> bool:
	return value is String and not value.is_empty() and value.length() <= 256


## Missing fields are supported for older saves; present fields must be valid.
static func valid_run(data: Dictionary) -> bool:
	for key: String in ["gold", "hearts", "max_hearts", "current_hp"]:
		if data.has(key) and not valid_number(data[key]):
			return false
	if data.has("play_time") and not valid_number(data.play_time, 0.0, NUMBER_LIMIT, false):
		return false
	if data.has("stats"):
		if data.stats is not Dictionary:
			return false
		for key: String in ["level", "experience", "strength", "constitution", "defense", "luck"]:
			if data.stats.has(key) and not valid_number(data.stats[key]):
				return false
		if data.stats.has("level") and not valid_number(data.stats.level, 1, PlayerStats.MAX_LEVEL):
			return false
	for key: String in NAME_ARRAYS:
		if not data.has(key):
			continue
		if data[key] is not Array:
			return false
		for value: Variant in data[key]:
			if not valid_name(value):
				return false
	for key: String in ["consumables", "equipped"]:
		if not data.has(key):
			continue
		if data[key] is not Dictionary:
			return false
		for id: Variant in data[key]:
			if not valid_name(id):
				return false
			if key == "consumables":
				if not valid_number(data[key][id]):
					return false
			elif not id.is_valid_int() or not valid_name(data[key][id]):
				return false
	if data.has("checkpoint_room") and data.checkpoint_room is not String:
		return false
	if data.has("checkpoint_position"):
		if data.checkpoint_position is not Dictionary:
			return false
		for axis: String in ["x", "y"]:
			if data.checkpoint_position.has(axis) and not valid_number(
					data.checkpoint_position[axis], -NUMBER_LIMIT, NUMBER_LIMIT, false):
				return false
	return true


static func valid_payload(payload: Dictionary, supported_version: int) -> bool:
	if not valid_number(payload.get("format_version"), 1, supported_version):
		return false
	if not valid_number(payload.get("saved_at"), 0.0, 10_000_000_000.0) or payload.get("data") is not Dictionary:
		return false
	var data: Dictionary = payload.data
	# A recognized character sheet distinguishes a save from arbitrary JSON.
	if data.get("stats") is not Dictionary or not data.stats.has("level"):
		return false
	return valid_run(data)
