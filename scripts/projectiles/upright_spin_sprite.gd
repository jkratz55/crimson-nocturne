## Shows a spinning projectile through pre-rotated frames instead of
## rotating its pixels.
##
## The parent (a [Projectile]) keeps rotating at its own [code]spin_speed[/code],
## and its hitbox turns with it, so the hit geometry is exactly what it would
## be with a plain rotated sprite. This sprite cancels that rotation, so it
## stays upright in the world, and shows the frame drawn at the parent's
## current angle: frame [code]k[/code] of the strip is the art turned
## clockwise by [code]k * TAU / hframes[/code]. Rotating 1x pixel art in-engine
## shreds it; pre-rotated frames keep it crisp and keep the light fixed.
##
## A left throw turns the parent counter-clockwise and sets [member flip_h],
## which mirrors the clockwise strip into a counter-clockwise spin, so the
## same frame index (from the size of the angle) is right both ways.
class_name UprightSpinSprite
extends Sprite2D


func _ready() -> void:
	_follow_parent()


func _process(_delta: float) -> void:
	_follow_parent()


func _follow_parent() -> void:
	var parent_2d := get_parent() as Node2D
	if parent_2d == null or hframes <= 0:
		return
	var turn: float = parent_2d.rotation
	rotation = -turn
	var step: float = TAU / float(hframes)
	frame = posmod(roundi(absf(turn) / step), hframes)
