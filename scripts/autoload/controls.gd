## Controller awareness (autoload: [code]Controls[/code]).
##
## Godot normalises Xbox, PlayStation and most other pads onto one SDL button
## layout — button 0 is always the bottom face button, 2 is always the left
## one — so a single Input Map already drives all of them. This node owns the
## parts that mapping does not cover:
##
## - [b]Which device is in the player's hands.[/b] The same physical button is
##   "X" on an Xbox pad and "SQUARE" on a DualSense, so prompts have to follow
##   the hardware. Picking up the keyboard switches back.
## - [b]Rumble[/b], in one place so it can be tuned, scaled, or turned off.
## - [b]Hot-plugging[/b]: a pad dying mid-fight must not silently strand the
##   player mid-jump (see [signal pad_disconnected]).
##
## Stick *feel* deliberately lives with the thing being controlled rather than
## here — see [method Player._move_input].
extends Node

## Prompt sets. Unrecognised pads fall back to the Xbox names, which are the
## most common convention on PC.
enum Device { KEYBOARD, XBOX, PLAYSTATION }

## Emitted when the player switches between keyboard and pad, or between pads
## of different brands. Anything drawing button prompts should listen.
signal device_changed(device: Device)

## Emitted when the pad that was in use disappeared (unplugged, flat battery).
signal pad_disconnected

## Sticks jitter around centre, so only a deliberate push counts as "the
## player picked the pad back up".
const STICK_WAKE_THRESHOLD: float = 0.5

const SONY_VENDOR_ID: int = 0x054C
const MICROSOFT_VENDOR_ID: int = 0x045E

## Button name per action for each [enum Device], in enum order. (A `var`
## rather than a `const`: built-in array constructors are not constant
## expressions in GDScript.)
var _labels: Dictionary[StringName, PackedStringArray] = {
	&"move_left": PackedStringArray(["ARROWS", "DPAD", "DPAD"]),
	&"move_right": PackedStringArray(["ARROWS", "DPAD", "DPAD"]),
	&"move_up": PackedStringArray(["UP", "DPAD UP", "DPAD UP"]),
	&"move_down": PackedStringArray(["DOWN", "DPAD", "DPAD"]),
	&"jump": PackedStringArray(["SPACE", "A", "CROSS"]),
	&"attack": PackedStringArray(["X", "X", "SQUARE"]),
	&"attack_secondary": PackedStringArray(["V", "RB", "R1"]),
	&"subweapon": PackedStringArray(["C", "Y", "TRIANGLE"]),
	&"backdash": PackedStringArray(["SHIFT", "B", "CIRCLE"]),
	&"switch_subweapon": PackedStringArray(["Q", "LB", "L1"]),
	&"pause_menu": PackedStringArray(["E", "BACK", "SHARE"]),
	&"pause": PackedStringArray(["ESC", "START", "OPTIONS"]),
}

## Master switch, intended for an options menu alongside GameFeel's.
@export var rumble_enabled: bool = true
## Scales every rumble request, so "weak / strong / off" is one number.
@export_range(0.0, 2.0, 0.05) var rumble_strength: float = 1.0

## Prompt set currently being shown. Read it, set it with [method force_device].
var device: Device = Device.KEYBOARD

## Joypad id being used, or -1 when there is none.
var _pad_device: int = -1
## Cleared by [method force_device] so an explicit choice sticks.
var _auto_detect: bool = true


func _ready() -> void:
	# Must keep working while the game is paused (menus show prompts too).
	process_mode = Node.PROCESS_MODE_ALWAYS
	Input.joy_connection_changed.connect(_on_joy_connection_changed)
	# A pad plugged in at boot is almost certainly what the player is holding.
	var pads: Array[int] = Input.get_connected_joypads()
	if not pads.is_empty():
		_use_pad(pads[0])


func _input(event: InputEvent) -> void:
	# Never consumes anything: this only watches which device is in use.
	if event is InputEventKey or event is InputEventMouseButton:
		_detected(Device.KEYBOARD)
	elif event is InputEventJoypadButton:
		_use_pad((event as InputEventJoypadButton).device)
	elif event is InputEventJoypadMotion:
		var motion := event as InputEventJoypadMotion
		if absf(motion.axis_value) >= STICK_WAKE_THRESHOLD:
			_use_pad(motion.device)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
## Name of the button bound to [param action] on the device in use, for
## on-screen prompts ("SQUARE", "LB/RB", "ESC"...).
func get_action_label(action: StringName) -> String:
	var names: PackedStringArray = _labels.get(action, PackedStringArray())
	if int(device) >= names.size():
		return String(action).to_upper()
	return names[int(device)]


## True while button prompts should show pad buttons rather than keys.
func is_using_pad() -> bool:
	return device != Device.KEYBOARD


## Is the pad we would rumble actually attached right now? Asked of the
## engine rather than trusting a remembered id, which can outlive the pad.
func has_pad() -> bool:
	return _pad_device >= 0 and Input.get_connected_joypads().has(_pad_device)


## Pin the prompt set (an options menu "Button prompts: Xbox / PlayStation"),
## which also stops auto-detection from overriding the choice.
func force_device(new_device: Device) -> void:
	_auto_detect = false
	_set_device(new_device)


## Go back to following whatever the player last touched.
func auto_detect_device() -> void:
	_auto_detect = true
	if _pad_device >= 0:
		_use_pad(_pad_device)


## Rumble the pad in use. [param weak] drives the high-frequency motor,
## [param strong] the low-frequency one (both 0..1). No-op without a pad.
func rumble(weak: float, strong: float, duration: float) -> void:
	if not rumble_enabled or duration <= 0.0 or not has_pad():
		return
	Input.start_joy_vibration(
		_pad_device,
		clampf(weak * rumble_strength, 0.0, 1.0),
		clampf(strong * rumble_strength, 0.0, 1.0),
		duration)


## Stop the motors now (scene changes, death, quitting).
func stop_rumble() -> void:
	if has_pad():
		Input.stop_joy_vibration(_pad_device)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
func _use_pad(device_id: int) -> void:
	_pad_device = device_id
	_detected(_detect_brand(device_id))


## USB vendor ids are authoritative; the driver-reported name is the fallback
## for third-party pads that report someone else's ids (or none at all).
func _detect_brand(device_id: int) -> Device:
	# An input event can outlive the pad that sent it (disconnect races), and
	# asking about a pad that is gone is an error, so assume a generic pad.
	if not Input.get_connected_joypads().has(device_id):
		return Device.XBOX
	var info: Dictionary = Input.get_joy_info(device_id)
	match int(info.get("vendor_id", 0)):
		SONY_VENDOR_ID:
			return Device.PLAYSTATION
		MICROSOFT_VENDOR_ID:
			return Device.XBOX
	var name: String = "%s %s" % [Input.get_joy_name(device_id), info.get("raw_name", "")]
	name = name.to_lower()
	for needle: String in ["playstation", "dualshock", "dualsense", "sony", "ps3", "ps4", "ps5"]:
		if name.contains(needle):
			return Device.PLAYSTATION
	return Device.XBOX


func _detected(new_device: Device) -> void:
	if _auto_detect:
		_set_device(new_device)


func _set_device(new_device: Device) -> void:
	if new_device == device:
		return
	device = new_device
	device_changed.emit(device)


func _on_joy_connection_changed(device_id: int, connected: bool) -> void:
	if connected:
		_use_pad(device_id)
		return
	if device_id != _pad_device:
		return
	var remaining: Array[int] = Input.get_connected_joypads()
	if remaining.is_empty():
		_pad_device = -1
		_detected(Device.KEYBOARD)
		pad_disconnected.emit()
	else:
		_use_pad(remaining[0])
