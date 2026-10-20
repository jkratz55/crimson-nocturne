## SotN-style afterimage trail: ghost copies of a sprite's current frame that
## darken, shift toward blue-violet and flicker at 30 Hz as they fade.
##
## While [member emitting] is on, a snapshot of [member source] (its frame
## texture, transform and flip) is taken every [member interval_ticks] and put
## into a fixed ring of [constant SLOTS] [Sprite2D]s, so nothing is allocated
## after [method _ready]. Each ghost then ages on its own: red and green fall
## every tick and blue rises, and it is drawn at 50% opacity (the PS1 average
## blend) from its first tick, so even the newest ghost never reads as a
## second, solid hero. Only the ghosts whose slot parity is opposite to the
## tick parity are drawn on any tick, which is the characteristic flicker.
##
## Vesper is a dark sprite, and a darkening multiply on a dark sprite vanishes
## into a dark wall, so the ghosts draw through a tiny shader of their own that
## lifts every texel to at least [constant LIGHT_FLOOR] before the tint. The
## source sprite itself is never given this material.
##
## Visual only. The node is [member CanvasItem.top_level], so it ignores the
## owner's movement and draws in world space, at [member trail_z] (one under
## the player). Ghosts carry their tint in their own materials and never read
## the source's modulate, so the source's i-frame blink and hurt flash cannot
## leak into the trail.
class_name AfterimageTrail
extends Node2D

const SLOTS: int = 6
## Colour model, in the PS1's 128 = 1.0 units.
const FADE_PER_TICK: float = 5.0 / 128.0
## Blue starts rising almost at once, so the newest ghost already reads cool.
const BLUE_START: float = 124.0 / 128.0
const BLUE_PER_TICK: float = 6.0 / 128.0
const BLUE_MAX: float = 240.0 / 128.0
## Below this red/green level a ghost is half-blended: with the head start
## below, that is every ghost from its first drawn tick.
const HALF_BLEND_BELOW: float = 120.0 / 128.0
## Ghosts start this many ticks into the fade (red/green about 0.80).
const TINT_HEAD_START_TICKS: float = 5.0
## Ghost-only light floor (see the class docs).
const LIGHT_FLOOR: Color = Color(0.22, 0.24, 0.40)
const GHOST_SHADER_CODE: String = """
shader_type canvas_item;
uniform vec4 tint = vec4(1.0);
uniform vec3 light_floor = vec3(0.0);
void fragment() {
	vec4 tex = texture(TEXTURE, UV);
	COLOR = vec4(max(tex.rgb, light_floor) * tint.rgb, tex.a * tint.a);
}
"""

## Compiled once and shared by every trail.
static var _ghost_shader: Shader

## The sprite to copy. Set by the owner before (or right after) adding the trail.
@export var source: AnimatedSprite2D
## Ticks (1/60 s of game time) between snapshots.
@export_range(1.0, 10.0, 0.5) var interval_ticks: float = 3.0
## A ghost disappears after this many ticks (15 = 0.25 s).
@export_range(4.0, 30.0, 1.0) var life_ticks: float = 15.0
## Absolute z index of the ghosts; the owner usually sets its own z - 1.
@export var trail_z: int = 9

## While true, new ghosts are snapshotted. Existing ghosts always finish fading.
var emitting: bool = false:
	set(value):
		if value and not emitting:
			_until_snapshot = 0.0   # the first ghost lands on the very next tick
		emitting = value

var _ghosts: Array[Sprite2D] = []
## One material per ghost: each carries its own tint.
var _materials: Array[ShaderMaterial] = []
## Ghost age in ticks; negative means the slot is free.
var _ages: PackedFloat32Array = PackedFloat32Array()
var _next_slot: int = 0
var _until_snapshot: float = 0.0
var _clock: float = 0.0


func _ready() -> void:
	top_level = true
	global_transform = Transform2D.IDENTITY
	z_as_relative = false
	z_index = trail_z
	_ages.resize(SLOTS)
	if _ghost_shader == null:
		_ghost_shader = Shader.new()
		_ghost_shader.code = GHOST_SHADER_CODE
	for i: int in SLOTS:
		var mat := ShaderMaterial.new()
		mat.shader = _ghost_shader
		mat.set_shader_parameter(&"light_floor", Vector3(LIGHT_FLOOR.r, LIGHT_FLOOR.g, LIGHT_FLOOR.b))
		var ghost := Sprite2D.new()
		ghost.visible = false
		ghost.material = mat
		add_child(ghost)
		_ghosts.append(ghost)
		_materials.append(mat)
		_ages[i] = -1.0


## Hide every ghost at once (e.g. on a respawn or a teleport).
func clear() -> void:
	for i: int in SLOTS:
		_ages[i] = -1.0
		_ghosts[i].visible = false


func _physics_process(delta: float) -> void:
	# Ticks of game time, so hit-stop freezes the trail with everything else.
	var ticks: float = delta * 60.0
	_clock += ticks
	if emitting and is_instance_valid(source):
		_until_snapshot -= ticks
		if _until_snapshot <= 0.0:
			_until_snapshot += interval_ticks
			_snapshot()
	var parity: int = int(_clock) % 2
	for i: int in SLOTS:
		if _ages[i] < 0.0:
			continue
		_ages[i] += ticks
		if _ages[i] >= life_ticks:
			_ages[i] = -1.0
			_ghosts[i].visible = false
			continue
		_tint(i, _ages[i])
		_ghosts[i].visible = i % 2 != parity


func _snapshot() -> void:
	var frames: SpriteFrames = source.sprite_frames
	if frames == null or not frames.has_animation(source.animation):
		return
	var ghost: Sprite2D = _ghosts[_next_slot]
	ghost.texture = frames.get_frame_texture(source.animation, source.frame)
	ghost.centered = source.centered
	ghost.offset = source.offset
	ghost.flip_h = source.flip_h
	ghost.flip_v = source.flip_v
	ghost.global_transform = source.global_transform
	_ages[_next_slot] = 0.0
	_tint(_next_slot, 0.0)
	ghost.visible = false   # the flicker decides on the next tick
	_next_slot = (_next_slot + 1) % SLOTS


## Darken red/green every tick, push blue up once dim, then half-blend. The
## tint goes to the ghost's own material (blue may exceed 1.0).
func _tint(slot: int, age: float) -> void:
	var rg: float = maxf(0.0, 1.0 - FADE_PER_TICK * (age + TINT_HEAD_START_TICKS))
	var blue: float = 1.0
	if rg < BLUE_START:
		var ticks_dim: float = (BLUE_START - rg) / FADE_PER_TICK
		blue = minf(BLUE_MAX, 1.0 + BLUE_PER_TICK * ticks_dim)
	var alpha: float = 0.5 if rg < HALF_BLEND_BELOW else 1.0
	_materials[slot].set_shader_parameter(&"tint", Color(rg, rg, blue, alpha))
