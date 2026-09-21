## "Juice" helpers (autoload: [code]GameFeel[/code]).
##
## Hit-stop (a few frames of near-frozen time on impact) and screen shake
## are what make melee combat feel weighty. Keeping them in one place means
## designers can tune or globally disable them (e.g. an accessibility
## "reduce screen shake" option) without touching combat code.
##
## [b]Implementation note[/b]: hit-stop is tracked against the real-time
## clock ([method Time.get_ticks_usec]) in [method _process] rather than with
## awaited timers. Overlapping hit-stops simply extend the deadline, and there
## is no way for a race between timers to leave [member Engine.time_scale]
## stuck in slow motion.
extends Node

## Master switches, intended to be exposed in an options menu later.
@export var hit_stop_enabled: bool = true
@export var screen_shake_enabled: bool = true

const FROZEN_TIME_SCALE: float = 0.05

## Real-time deadline (microseconds) at which hit-stop ends; 0 = inactive.
var _hit_stop_until_usec: int = 0


func _ready() -> void:
	# Must keep ticking while the world is (nearly) frozen or paused.
	process_mode = Node.PROCESS_MODE_ALWAYS


func _process(_delta: float) -> void:
	if _hit_stop_until_usec != 0 and Time.get_ticks_usec() >= _hit_stop_until_usec:
		_hit_stop_until_usec = 0
		Engine.time_scale = 1.0


## Freeze gameplay for [param duration] real-time seconds.
## Calls during an active hit-stop extend it if they end later.
func hit_stop(duration: float) -> void:
	if not hit_stop_enabled or duration <= 0.0:
		return
	var until: int = Time.get_ticks_usec() + int(duration * 1_000_000.0)
	_hit_stop_until_usec = maxi(_hit_stop_until_usec, until)
	Engine.time_scale = FROZEN_TIME_SCALE


## Cancel any active hit-stop immediately (e.g. before a scene change).
func clear_hit_stop() -> void:
	_hit_stop_until_usec = 0
	Engine.time_scale = 1.0


## Request a camera shake. The active [RoomCamera] listens via [Events].
func shake(strength: float, duration: float = 0.2) -> void:
	if screen_shake_enabled:
		Events.camera_shake_requested.emit(strength, duration)
