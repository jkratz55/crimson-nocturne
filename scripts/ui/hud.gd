## Status display: the compact top-left cluster (sub-weapon medallion, HP
## number and gauge, hearts, MP gauge, "LV n"), a top-right ledger that shows
## NEXT and gold for a few seconds whenever either changes, a one-line notice
## slot for weapon swaps, pickups and save confirmations, the LEVEL UP word and
## the area-name banner.
##
## Purely reactive — it only listens to [Events] and never queries the player
## or [GameManager] directly, so it works unchanged in any room or menu scene.
class_name HUD
extends CanvasLayer

@export var bar_tween_time: float = 0.25
## How long a notice stays up before fading.
@export var notice_hold_time: float = 1.8
## At or below this fraction of max HP the HP digits blink red.
@export_range(0.0, 1.0) var low_hp_fraction: float = 0.25

## Low-HP blink colour (255, 96, 96) and period: 16 ticks at 60 Hz per phase.
const HP_LOW_COLOR: Color = Color(1.0, 0.376, 0.376)
const HP_BLINK_INTERVAL: float = 16.0 / 60.0
## Area banner timing: wait 32 ticks, unfold over 15, hold, fold shut over 24.
const BANNER_DELAY: float = 32.0 / 60.0
const BANNER_GROW: float = 15.0 / 60.0
const BANNER_HOLD: float = 2.0
const BANNER_COLLAPSE: float = 24.0 / 60.0
## The banner box unfolds from this size (and folds back to this height). The
## minimum height equals its StyleBoxTexture's top + bottom margins, so the
## border and hairline rows are always drawn whole.
const BANNER_MIN_SIZE: Vector2i = Vector2i(140, 20)
## Ledger (NEXT / gold): fade in, hold, fade out — about 3 s in all.
const LEDGER_FADE_IN: float = 0.15
const LEDGER_HOLD: float = 2.4
const LEDGER_FADE_OUT: float = 0.6
## LEVEL UP, in 60 Hz ticks: fade in, then hold (rising 1 px every 2 ticks
## for the first LEVEL_UP_RISE_TICKS, flickering for the last
## LEVEL_UP_FLICKER_TICKS), then gone.
const LEVEL_UP_FADE_TICKS: int = 4
const LEVEL_UP_HOLD_TICKS: int = 72
const LEVEL_UP_RISE_TICKS: int = 16
const LEVEL_UP_RISE_PX: int = 8
const LEVEL_UP_FLICKER_TICKS: int = 16

@onready var hp_bar: TextureProgressBar = %HPBar
@onready var mp_bar: TextureProgressBar = %MPBar
@onready var hp_label: Label = %HPLabel
@onready var hearts_label: Label = %HeartsLabel
@onready var level_label: Label = %LevelLabel
@onready var xp_label: Label = %XPLabel
@onready var gold_label: Label = %GoldLabel
@onready var ledger: PanelContainer = %Ledger
@onready var subweapon_icon: TextureRect = %SubweaponIcon
@onready var notice_label: Label = %WeaponLabel
@onready var area_title: Label = %AreaTitle
@onready var level_up_label: Label = %LevelUpLabel

var _hp_tween: Tween
var _title_tween: Tween
var _notice_tween: Tween
var _ledger_tween: Tween
var _level_up_tween: Tween
var _hp_low: bool = false
var _hp_blink_time: float = 0.0
## Last values the ledger was given; -1 until the first broadcast. Room loads
## and respawns re-broadcast the same values, which must not pop the ledger.
var _last_level: int = -1
var _last_to_next: int = -1
var _last_gold: int = -1
## The banner's full rect (centre-anchored offsets) and the LEVEL UP word's
## resting offsets, both as authored in the scene.
var _banner_center: Vector2
var _banner_full: Vector2i
var _level_up_top: float
var _level_up_bottom: float


func _ready() -> void:
	area_title.modulate.a = 0.0
	notice_label.modulate.a = 0.0
	ledger.modulate.a = 0.0
	level_up_label.modulate.a = 0.0
	_banner_center = Vector2((area_title.offset_left + area_title.offset_right) * 0.5,
			(area_title.offset_top + area_title.offset_bottom) * 0.5)
	_banner_full = Vector2i(roundi(area_title.offset_right - area_title.offset_left),
			roundi(area_title.offset_bottom - area_title.offset_top))
	_level_up_top = level_up_label.offset_top
	_level_up_bottom = level_up_label.offset_bottom
	Events.player_health_changed.connect(_on_health_changed)
	Events.player_mp_changed.connect(_on_mp_changed)
	Events.player_hearts_changed.connect(_on_hearts_changed)
	Events.player_gold_changed.connect(_on_gold_changed)
	Events.player_experience_changed.connect(_on_experience_changed)
	Events.player_leveled_up.connect(_on_leveled_up)
	Events.player_weapon_changed.connect(_on_weapon_changed)
	Events.player_subweapon_changed.connect(_on_subweapon_changed)
	Events.notice_posted.connect(_show_notice)
	Events.area_entered.connect(_on_area_entered)


func _process(delta: float) -> void:
	if not _hp_low:
		return
	_hp_blink_time += delta
	var lit: bool = int(_hp_blink_time / HP_BLINK_INTERVAL) % 2 == 0
	if lit:
		hp_label.add_theme_color_override(&"font_color", HP_LOW_COLOR)
	else:
		hp_label.remove_theme_color_override(&"font_color")


func _on_health_changed(current: int, maximum: int) -> void:
	hp_bar.max_value = maximum
	hp_label.text = str(current)
	if _hp_tween and _hp_tween.is_valid():
		_hp_tween.kill()
	_hp_tween = create_tween()
	_hp_tween.tween_property(hp_bar, "value", float(current), bar_tween_time)
	# Visual only: the HP digits blink red while the player is near death.
	var low: bool = current > 0 and maximum > 0 and float(current) <= float(maximum) * low_hp_fraction
	if low != _hp_low:
		_hp_low = low
		_hp_blink_time = 0.0
		if not low:
			hp_label.remove_theme_color_override(&"font_color")


func _on_mp_changed(current: int, maximum: int) -> void:
	mp_bar.max_value = maximum
	mp_bar.value = current


func _on_hearts_changed(current: int, _maximum: int) -> void:
	# The medallion has room for the count only; the ceiling is on the stats tab.
	hearts_label.text = str(current)


func _on_gold_changed(current: int) -> void:
	gold_label.text = str(current)
	var changed: bool = _last_gold >= 0 and current != _last_gold
	_last_gold = current
	_fit_ledger()
	if changed:
		_show_ledger()


func _on_experience_changed(_current: int, to_next: int, level: int) -> void:
	level_label.text = "LV %d" % level
	xp_label.text = "MAX" if to_next <= 0 else "NEXT %d" % to_next
	var changed: bool = _last_level >= 0 and (level != _last_level or to_next != _last_to_next)
	_last_level = level
	_last_to_next = to_next
	_fit_ledger()
	if changed:
		_show_ledger()


## The ledger hugs its contents and stays flush with the screen's right
## margin, whatever the width of the numbers in it.
func _fit_ledger() -> void:
	var size_needed: Vector2 = ledger.get_combined_minimum_size()
	ledger.offset_left = ledger.offset_right - size_needed.x
	ledger.offset_bottom = ledger.offset_top + size_needed.y


## Fade the ledger in, hold it, fade it out. A change while it is up just
## restarts the hold.
func _show_ledger() -> void:
	if _ledger_tween and _ledger_tween.is_valid():
		_ledger_tween.kill()
	_ledger_tween = create_tween()
	_ledger_tween.tween_property(ledger, "modulate:a", 1.0, LEDGER_FADE_IN)
	_ledger_tween.tween_interval(LEDGER_HOLD)
	_ledger_tween.tween_property(ledger, "modulate:a", 0.0, LEDGER_FADE_OUT)


## The title-font LEVEL UP word: it fades in, rises a few pixels, holds,
## flickers and goes. The new level shows on the plate's "LV n".
func _on_leveled_up(_level: int) -> void:
	if _level_up_tween and _level_up_tween.is_valid():
		_level_up_tween.kill()
	var total: int = LEVEL_UP_FADE_TICKS + LEVEL_UP_HOLD_TICKS
	_set_level_up_tick(0.0)
	_level_up_tween = create_tween()
	_level_up_tween.tween_method(_set_level_up_tick, 0.0, float(total), float(total) / 60.0)
	_level_up_tween.tween_callback(_hide_level_up)


## One LEVEL UP frame at tick `t`. The word only ever moves by whole pixels.
func _set_level_up_tick(t: float) -> void:
	var tick: int = floori(t)
	var held: int = tick - LEVEL_UP_FADE_TICKS
	# 1 px up every (rise ticks / rise px) ticks of the hold, from LEVEL_UP_RISE_PX below rest.
	var risen: int = clampi(floori(float(maxi(held, 0)) * float(LEVEL_UP_RISE_PX) / float(LEVEL_UP_RISE_TICKS)),
			0, LEVEL_UP_RISE_PX)
	var dy: float = float(LEVEL_UP_RISE_PX - risen)
	level_up_label.offset_top = _level_up_top + dy
	level_up_label.offset_bottom = _level_up_bottom + dy
	var alpha: float = 1.0
	var flicker_from: int = LEVEL_UP_HOLD_TICKS - LEVEL_UP_FLICKER_TICKS
	if tick < LEVEL_UP_FADE_TICKS:
		alpha = float(tick + 1) / float(LEVEL_UP_FADE_TICKS + 1)
	elif held >= flicker_from:
		# full / half alpha, switching every 2 ticks
		alpha = 1.0 if posmod(held - flicker_from, 4) < 2 else 0.5
	level_up_label.modulate.a = alpha


func _hide_level_up() -> void:
	level_up_label.modulate.a = 0.0
	level_up_label.offset_top = _level_up_top
	level_up_label.offset_bottom = _level_up_bottom


## Flash the weapon's name under the status frame, then fade it out again.
## Item names keep their own (mixed) case, as in SotN's menus and notices.
func _on_weapon_changed(weapon: WeaponData) -> void:
	if weapon != null:
		_show_notice(weapon.display_name)


func _on_subweapon_changed(subweapon: SubWeaponData) -> void:
	subweapon_icon.texture = subweapon.icon if subweapon else null


## One shared slot for weapon swaps, pickups and save confirmations. A new
## notice replaces whatever was there rather than queueing behind it. The
## label draws its own small window (a StyleBoxTexture) and hugs its text,
## so it is shrunk back to its minimum size for every new line.
func _show_notice(text: String) -> void:
	if text.is_empty():
		return
	notice_label.text = text
	notice_label.reset_size()
	if _notice_tween and _notice_tween.is_valid():
		_notice_tween.kill()
	_notice_tween = create_tween()
	_notice_tween.tween_property(notice_label, "modulate:a", 1.0, 0.15)
	_notice_tween.tween_interval(notice_hold_time)
	_notice_tween.tween_property(notice_label, "modulate:a", 0.0, 0.6)


## The area-name banner: after a short wait the empty box unfolds from its
## centre, the name appears once it is open, then the name goes and the box
## folds shut again (SotN's stage-name box, without the slice dissolve). The
## box is resized, never scaled: its StyleBoxTexture keeps the border and
## hairline rows whole at every size, both edges land on whole pixels, and
## the text is never drawn while the size changes. Visual only; the total
## stays under 3.5 s.
func _on_area_entered(display_name: String) -> void:
	area_title.text = display_name.to_upper()
	if _title_tween and _title_tween.is_valid():
		_title_tween.kill()
	area_title.scale = Vector2.ONE
	area_title.visible_characters = 0
	_set_banner_unfold(0.0)
	area_title.modulate.a = 0.0
	_title_tween = create_tween()
	_title_tween.tween_interval(BANNER_DELAY)
	_title_tween.tween_method(_set_banner_unfold, 0.0, 1.0, BANNER_GROW)
	_title_tween.parallel().tween_property(area_title, "modulate:a", 1.0, BANNER_GROW)
	_title_tween.tween_callback(_show_banner_text.bind(true))
	_title_tween.tween_interval(BANNER_HOLD)
	_title_tween.tween_callback(_show_banner_text.bind(false))
	_title_tween.tween_method(_set_banner_fold, 0.0, 1.0, BANNER_COLLAPSE)
	_title_tween.parallel().tween_property(area_title, "modulate:a", 0.0, BANNER_COLLAPSE)


## Unfold progress 0..1 (ease-out): from the minimum size to the full box.
func _set_banner_unfold(t: float) -> void:
	var e: float = 1.0 - (1.0 - t) * (1.0 - t)
	_set_banner_size(lerpf(float(BANNER_MIN_SIZE.x), float(_banner_full.x), e),
			lerpf(float(BANNER_MIN_SIZE.y), float(_banner_full.y), e))


## Fold progress 0..1 (ease-in): full width, height down to the minimum.
func _set_banner_fold(t: float) -> void:
	_set_banner_size(float(_banner_full.x),
			lerpf(float(_banner_full.y), float(BANNER_MIN_SIZE.y), t * t))


## Size the box about its authored centre. Width and height are rounded to
## even numbers, so both edges sit on the pixel grid.
func _set_banner_size(w: float, h: float) -> void:
	var half_w: float = float(roundi(w * 0.5))
	var half_h: float = float(roundi(h * 0.5))
	area_title.offset_left = _banner_center.x - half_w
	area_title.offset_right = _banner_center.x + half_w
	area_title.offset_top = _banner_center.y - half_h
	area_title.offset_bottom = _banner_center.y + half_h


func _show_banner_text(shown: bool) -> void:
	area_title.visible_characters = -1 if shown else 0
