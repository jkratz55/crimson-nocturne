## Reads and writes save slots (autoload: [code]SaveManager[/code]).
##
## The payload is whatever [method GameManager.to_save_data] returns, wrapped
## in a small header. Format is [b]JSON[/b] (SPEC 3 offers a choice of three;
## the reasoning is in ASSUMPTIONS.md): it is diffable, it survives a class
## being renamed, and — unlike `ResourceSaver` — loading one can never
## instantiate a script, so a hand-edited save is a wrong save, not an
## arbitrary-code-execution hole.
##
## Slots are numbered 0..[constant SLOT_COUNT] - 1. Every read is defensive:
## a missing, truncated or foreign file reports "empty slot" rather than
## taking the game down.
extends Node

const SLOT_COUNT: int = 3
const SAVE_DIR: String = "user://saves"
const FORMAT_VERSION: int = 1

## Tests may redirect saves without touching player slots.
var save_directory: String = SAVE_DIR
var last_error: String = ""

## Enough to draw a slot in a load menu without loading the whole run.
class SlotInfo extends RefCounted:
	var slot: int = -1
	var exists: bool = false
	var level: int = 1
	var gold: int = 0
	var play_time: float = 0.0
	var room: StringName = &""
	var saved_at: int = 0

	## "LV 7   0:42:11   1240G"
	func summary() -> String:
		if not exists:
			return "- EMPTY -"
		return "LV %d   %s   %dG" % [level, format_play_time(play_time), gold]

	static func format_play_time(seconds: float) -> String:
		var total: int = int(seconds)
		return "%d:%02d:%02d" % [total / 3600, (total / 60) % 60, total % 60]


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	DirAccess.make_dir_recursive_absolute(save_directory)


## Absolute path of [param slot]'s file.
func slot_path(slot: int) -> String:
	return "%s/slot_%d.json" % [save_directory, slot]


func has_save(slot: int) -> bool:
	return FileAccess.file_exists(slot_path(slot))


## Write the current run to [param slot]. Returns false (and pushes an error)
## if the file could not be written.
func save_to_slot(slot: int) -> bool:
	if slot < 0 or slot >= SLOT_COUNT:
		push_error("SaveManager: slot %d is out of range." % slot)
		return false
	var payload := {
		"format_version": FORMAT_VERSION,
		"saved_at": int(Time.get_unix_time_from_system()),
		"data": GameManager.to_save_data(),
	}
	last_error = ""
	if not SaveData.valid_payload(payload, FORMAT_VERSION):
		return _save_failed("The current run could not be saved.")
	var path: String = slot_path(slot)
	var temporary: String = path + ".tmp"
	var file := FileAccess.open(temporary, FileAccess.WRITE)
	if file == null:
		return _save_failed("Could not create the temporary save.")
	file.store_string(JSON.stringify(payload, "\t"))
	file.flush()
	var write_error: Error = file.get_error()
	file.close()
	if write_error != OK or _read_path(temporary).is_empty():
		return _save_failed("Could not finish writing the save.")
	# Keep the previous valid generation. Never replace a good backup with
	# a corrupt primary, and never remove the primary before replacement.
	if not _read_path(path).is_empty():
		var backup_temporary: String = path + ".bak.tmp"
		if DirAccess.copy_absolute(path, backup_temporary) != OK:
			return _save_failed("Could not preserve the previous save.")
		if _read_path(backup_temporary).is_empty() or DirAccess.rename_absolute(
				backup_temporary, path + ".bak") != OK:
			return _save_failed("Could not finish the save backup.")
	if DirAccess.rename_absolute(temporary, path) != OK:
		return _save_failed("Could not replace the save slot.")

	GameManager.current_slot = slot
	Events.game_saved.emit(slot)
	return true


## Load [param slot] into [GameManager]. Returns false if the slot is empty
## or unreadable, leaving the current run untouched.
func load_from_slot(slot: int) -> bool:
	var payload: Dictionary = _read(slot)
	if payload.is_empty():
		return false
	if not GameManager.apply_save_data(payload["data"]):
		return false
	GameManager.current_slot = slot
	Events.game_loaded.emit(slot)
	return true


## Delete [param slot]'s file, if any.
func delete_slot(slot: int) -> void:
	if slot < 0 or slot >= SLOT_COUNT:
		return
	for suffix: String in ["", ".bak", ".tmp", ".bak.tmp"]:
		var path: String = slot_path(slot) + suffix
		if FileAccess.file_exists(path):
			DirAccess.remove_absolute(path)


## Header information for [param slot], for a load menu.
func get_slot_info(slot: int) -> SlotInfo:
	var info := SlotInfo.new()
	info.slot = slot
	var payload: Dictionary = _read(slot)
	if payload.is_empty():
		return info
	var data: Dictionary = payload.get("data", {})
	var stats: Dictionary = data.get("stats", {})
	info.exists = true
	info.level = int(stats.get("level", 1))
	info.gold = int(data.get("gold", 0))
	info.play_time = float(data.get("play_time", 0.0))
	info.room = StringName(data.get("checkpoint_room", ""))
	info.saved_at = int(payload.get("saved_at", 0))
	return info


## Every slot's header, index 0 first.
func get_all_slot_info() -> Array[SlotInfo]:
	var all: Array[SlotInfo] = []
	for slot: int in SLOT_COUNT:
		all.append(get_slot_info(slot))
	return all


## The most recently written slot, or -1 when nothing has been saved. This is
## what a "Continue" button should use.
func most_recent_slot() -> int:
	var best: int = -1
	var best_time: int = -1
	for info: SlotInfo in get_all_slot_info():
		if info.exists and info.saved_at > best_time:
			best_time = info.saved_at
			best = info.slot
	return best


## Parsed slot file, or an empty dictionary for "nothing usable here".
func _read(slot: int) -> Dictionary:
	if slot < 0 or slot >= SLOT_COUNT:
		return {}
	var payload: Dictionary = _read_path(slot_path(slot))
	if payload.is_empty():
		payload = _read_path(slot_path(slot) + ".bak")
	return payload


func _read_path(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {}
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	var text: String = file.get_as_text()
	file.close()
	var json := JSON.new()
	if json.parse(text) != OK or json.data is not Dictionary:
		return {}
	var payload: Dictionary = json.data
	return payload if SaveData.valid_payload(payload, FORMAT_VERSION) else {}


func _save_failed(message: String) -> bool:
	last_error = message
	return false
