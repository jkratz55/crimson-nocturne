## Start a looping [AnimatedSprite2D] at an arbitrary point of its cycle.
##
## Picking a random [i]frame[/i] is biased whenever the frames are not all the
## same length: a heart's idle is a 40-tick hold and then an 8-tick glint in
## three frames, so a random frame lands inside the glint three times in four,
## and drops spawned together keep glinting together. Picking a random
## [i]tick[/i] of the whole cycle and walking the frame durations to it gives
## every moment of the loop the same chance. Visual only.
class_name AnimPhase
extends RefCounted


## Total length of [param anim]'s current animation, in its duration units
## (ticks for the SheetBuilder frames, which play at speed 60).
static func cycle_length(anim: AnimatedSprite2D) -> float:
	var frames: SpriteFrames = anim.sprite_frames
	if frames == null or not frames.has_animation(anim.animation):
		return 0.0
	var total: float = 0.0
	for i: int in frames.get_frame_count(anim.animation):
		total += frames.get_frame_duration(anim.animation, i)
	return total


## Put [param anim] at [param tick] (wrapped) of its current animation's
## cycle, keeping it playing.
static func seek(anim: AnimatedSprite2D, tick: float) -> void:
	var total: float = cycle_length(anim)
	if total <= 0.0:
		return
	var frames: SpriteFrames = anim.sprite_frames
	var count: int = frames.get_frame_count(anim.animation)
	var left: float = fposmod(tick, total)
	for i: int in count:
		var duration: float = frames.get_frame_duration(anim.animation, i)
		if left < duration:
			anim.set_frame_and_progress(i, left / duration)
			return
		left -= duration
	anim.set_frame_and_progress(count - 1, 0.0)


## Put [param anim] at a uniformly random moment of its cycle, drawn from
## [param rng] (a private generator, so the gameplay rolls never move).
static func randomize_phase(anim: AnimatedSprite2D, rng: RandomNumberGenerator) -> void:
	var total: float = cycle_length(anim)
	if total > 0.0:
		seek(anim, rng.randf() * total)
