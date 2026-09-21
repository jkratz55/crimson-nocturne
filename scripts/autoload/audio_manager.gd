## Central audio service (autoload: [code]Audio[/code]).
##
## - Sound effects are referenced by short [StringName] ids so gameplay
##   scripts and data resources don't hard-code file paths.
## - A fixed pool of [AudioStreamPlayer]s is reused round-robin, which
##   avoids allocating nodes during combat and caps simultaneous voices.
## - Music plays on its own player on the "Music" bus with fade in/out.
##
## Runs with [constant Node.PROCESS_MODE_ALWAYS] so music keeps playing
## while the game is paused.
extends Node

const SFX_BUS: StringName = &"SFX"
const MUSIC_BUS: StringName = &"Music"
const VOICE_COUNT: int = 12

## Registry of every sound effect in the game, keyed by id.
var _library: Dictionary[StringName, AudioStream] = {
	&"sword_swing": preload("res://assets/audio/sfx/sword_swing.wav"),
	&"hit": preload("res://assets/audio/sfx/hit.wav"),
	&"enemy_death": preload("res://assets/audio/sfx/enemy_death.wav"),
	&"player_hurt": preload("res://assets/audio/sfx/player_hurt.wav"),
	&"player_death": preload("res://assets/audio/sfx/player_death.wav"),
	&"jump": preload("res://assets/audio/sfx/jump.wav"),
	&"land": preload("res://assets/audio/sfx/land.wav"),
	&"backdash": preload("res://assets/audio/sfx/backdash.wav"),
	&"heart_pickup": preload("res://assets/audio/sfx/heart_pickup.wav"),
	&"dagger_throw": preload("res://assets/audio/sfx/dagger_throw.wav"),
	&"axe_throw": preload("res://assets/audio/sfx/axe_throw.wav"),
	&"candle_break": preload("res://assets/audio/sfx/candle_break.wav"),
	&"bone_throw": preload("res://assets/audio/sfx/bone_throw.wav"),
	&"bat_screech": preload("res://assets/audio/sfx/bat_screech.wav"),
	&"no_hearts": preload("res://assets/audio/sfx/no_hearts.wav"),
}

var _voices: Array[AudioStreamPlayer] = []
var _next_voice: int = 0
var _music_player: AudioStreamPlayer
var _music_tween: Tween


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	for i: int in VOICE_COUNT:
		var voice := AudioStreamPlayer.new()
		voice.bus = SFX_BUS
		add_child(voice)
		_voices.append(voice)
	_music_player = AudioStreamPlayer.new()
	_music_player.bus = MUSIC_BUS
	add_child(_music_player)


## Play a registered sound effect.
## [param pitch_variance] randomises pitch by +/- that fraction, which keeps
## frequently repeated sounds (sword swings, hits) from sounding robotic.
func play_sfx(id: StringName, pitch_variance: float = 0.05, volume_db: float = 0.0) -> void:
	var stream: AudioStream = _library.get(id)
	if stream == null:
		push_warning("Audio: unknown sfx id '%s'" % id)
		return
	var voice: AudioStreamPlayer = _voices[_next_voice]
	_next_voice = (_next_voice + 1) % _voices.size()
	voice.stream = stream
	voice.volume_db = volume_db
	voice.pitch_scale = 1.0 + randf_range(-pitch_variance, pitch_variance)
	voice.play()


## Cross-fade to [param stream]. Does nothing if it is already playing.
func play_music(stream: AudioStream, fade_time: float = 1.0) -> void:
	if _music_player.stream == stream and _music_player.playing:
		return
	if stream is AudioStreamOggVorbis:
		(stream as AudioStreamOggVorbis).loop = true
	_kill_music_tween()
	_music_player.stream = stream
	_music_player.volume_db = -40.0
	_music_player.play()
	_music_tween = create_tween()
	_music_tween.tween_property(_music_player, "volume_db", 0.0, fade_time)


## Fade the current track out and stop it.
func stop_music(fade_time: float = 1.0) -> void:
	_kill_music_tween()
	_music_tween = create_tween()
	_music_tween.tween_property(_music_player, "volume_db", -40.0, fade_time)
	_music_tween.tween_callback(_music_player.stop)


func _kill_music_tween() -> void:
	if _music_tween and _music_tween.is_valid():
		_music_tween.kill()
