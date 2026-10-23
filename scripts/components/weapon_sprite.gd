## Draws a held weapon over the [AnimatedSprite2D] it is a child of, frame
## for frame.
##
## Weapon art is not part of the body's animation: the body swings
## bare-handed, and each weapon look ships its own [SpriteFrames] whose
## animations share the body's names and frame counts (the hero pipeline
## writes one per sword, [code]blade_<look>_frames.tres[/code]). This node
## never plays on its own. It shows the body's current animation and frame
## out of the held sheet, flipped and offset like the body, and hides while
## that sheet has no such animation, so a weapon appears only on the
## animations drawn for it.
##
## As a child it inherits the body's transform and modulate (the i-frame
## blink) and draws with the body's material (the hurt flash).
class_name WeaponSprite
extends AnimatedSprite2D

var _body: AnimatedSprite2D


func _ready() -> void:
	_body = get_parent() as AnimatedSprite2D
	if _body == null:
		push_error("WeaponSprite must be a child of an AnimatedSprite2D.")
		return
	use_parent_material = true
	_body.animation_changed.connect(_sync)
	_body.frame_changed.connect(_sync)
	_sync()


## Hold the weapon drawn by [param frames] (null: nothing in hand).
func hold(frames: SpriteFrames) -> void:
	sprite_frames = frames
	_sync()


func _process(_delta: float) -> void:
	# Facing can flip without a frame change (turning to face an attacker).
	if visible and _body != null:
		flip_h = _body.flip_h


func _sync() -> void:
	if _body == null:
		return
	var anim: StringName = _body.animation
	visible = sprite_frames != null and sprite_frames.has_animation(anim)
	if not visible:
		return
	if animation != anim:
		animation = anim
	frame = mini(_body.frame, sprite_frames.get_frame_count(anim) - 1)
	flip_h = _body.flip_h
	offset = _body.offset
	centered = _body.centered
