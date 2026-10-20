## Shared, purely visual menu flourishes.
class_name MenuFx
extends RefCounted

## SotN windows grow open from their horizontal centre line.
const OPEN_TICKS: float = 16.0


## An empty copy of a window's frame that grows open in its place. It never
## takes input, and frees itself (handing the window back) when fully open.
class UnfoldFrame extends NinePatchRect:
	## Never shorter than the two 6-px nine-patch margins.
	const MIN_HEIGHT: float = 12.0

	## The real window, hidden until this frame has finished opening.
	var window: Control
	## The window's own modulate alpha, put back when it is shown again.
	var window_alpha: float = 1.0

	## [param t] runs 0 -> 1. Every step lands on whole pixels, centred on the
	## window's middle line, so the border never shimmers.
	func set_progress(t: float) -> void:
		if not is_instance_valid(window):
			queue_free()
			return
		var full: Vector2 = window.size
		var h: float = maxf(minf(MIN_HEIGHT, full.y), roundf(full.y * t))
		position = Vector2(window.position.x, window.position.y + floorf((full.y - h) * 0.5))
		size = Vector2(full.x, h)
		if t >= 1.0:
			release()

	## Show the real window again and remove this frame.
	func release() -> void:
		if is_instance_valid(window):
			window.modulate.a = window_alpha
		window = null
		var parent: Node = get_parent()
		if parent != null:
			parent.remove_child(self)
		queue_free()


## Unfold [param windows] vertically from their centre over [constant OPEN_TICKS].
## The way SotN does it: an empty frame grows open and the window's contents
## appear once it is fully open, so no text is ever scaled. Input is never held
## back (the menu is live from the first frame; only its frames are still
## growing). Returns the tween, bound to [param owner], so it runs whenever the
## owner does, including while the tree is paused.
static func unfold(owner: Node, windows: Array[Control]) -> Tween:
	reset(windows)
	var tween: Tween = owner.create_tween().set_parallel(true) \
		.set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_OUT)
	var any: bool = false
	for window: Control in windows:
		var frame: UnfoldFrame = _make_frame(window)
		if frame == null:
			continue
		frame.set_progress(0.0)
		tween.tween_method(frame.set_progress, 0.0, 1.0, OPEN_TICKS / 60.0)
		any = true
	if not any:
		# A tween with nothing to do would error; give it a no-op step.
		tween.tween_interval(0.0)
	return tween


## Show [param windows] at full size at once and drop any frame still opening
## (e.g. when a menu closes mid-unfold).
static func reset(windows: Array[Control]) -> void:
	for window: Control in windows:
		window.scale = Vector2.ONE
		var parent: Node = window.get_parent()
		if parent == null:
			continue
		for child: Node in parent.get_children():
			var frame := child as UnfoldFrame
			if frame != null and frame.window == window:
				frame.release()


## The opening frame for [param window]: a copy of its nine-patch, placed just
## under it among its siblings. Null if the window is not a nine-patch.
static func _make_frame(window: Control) -> UnfoldFrame:
	var patch := window as NinePatchRect
	var parent: Node = window.get_parent()
	if patch == null or parent == null:
		return null
	var frame := UnfoldFrame.new()
	frame.name = String(window.name) + "Unfold"
	frame.texture = patch.texture
	frame.region_rect = patch.region_rect
	frame.draw_center = patch.draw_center
	frame.patch_margin_left = patch.patch_margin_left
	frame.patch_margin_top = patch.patch_margin_top
	frame.patch_margin_right = patch.patch_margin_right
	frame.patch_margin_bottom = patch.patch_margin_bottom
	frame.axis_stretch_horizontal = patch.axis_stretch_horizontal
	frame.axis_stretch_vertical = patch.axis_stretch_vertical
	frame.self_modulate = patch.self_modulate
	frame.mouse_filter = Control.MOUSE_FILTER_IGNORE
	frame.window = window
	frame.window_alpha = window.modulate.a
	window.modulate.a = 0.0
	parent.add_child(frame)
	parent.move_child(frame, window.get_index())
	return frame
