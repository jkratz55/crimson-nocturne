## The SotN menu cursor bar: a dark crimson strip behind the selected row
## whose red channel pulses 64 -> 96 -> 64 over [constant PERIOD_TICKS].
##
## Purely visual. The menu that owns it only moves it and shows or hides it;
## it pulses on its own while visible (menus run while the tree is paused, and
## the bar inherits their process mode).
class_name SelectionBar
extends ColorRect

const PERIOD_TICKS: float = 64.0
const RED_LOW: float = 64.0 / 255.0
const RED_HIGH: float = 96.0 / 255.0
const GREEN: float = 4.0 / 255.0
const BLUE: float = 14.0 / 255.0

var _time: float = 0.0


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	_apply()


func _process(delta: float) -> void:
	if not is_visible_in_tree():
		return
	_time += delta
	_apply()


func _apply() -> void:
	# Triangle wave 0 -> 1 -> 0 over one period.
	var tri: float = 1.0 - absf(fmod(_time * 60.0 / (PERIOD_TICKS * 0.5), 2.0) - 1.0)
	color = Color(lerpf(RED_LOW, RED_HIGH, tri), GREEN, BLUE, color.a)
