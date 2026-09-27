## Status display: HP / MP bars, HP number, hearts, level and experience,
## gold, the sub-weapon medallion, and a one-line notice slot used for weapon
## swaps, pickups and save confirmations.
##
## Purely reactive — it only listens to [Events] and never queries the player
## or [GameManager] directly, so it works unchanged in any room or menu scene.
class_name HUD
extends CanvasLayer

@export var bar_tween_time: float = 0.25
## How long a notice stays up before fading.
@export var notice_hold_time: float = 1.8

@onready var hp_bar: TextureProgressBar = %HPBar
@onready var mp_bar: TextureProgressBar = %MPBar
@onready var hp_label: Label = %HPLabel
@onready var hearts_label: Label = %HeartsLabel
@onready var level_label: Label = %LevelLabel
@onready var xp_label: Label = %XPLabel
@onready var gold_label: Label = %GoldLabel
@onready var subweapon_icon: TextureRect = %SubweaponIcon
@onready var notice_label: Label = %WeaponLabel
@onready var area_title: Label = %AreaTitle

var _hp_tween: Tween
var _title_tween: Tween
var _notice_tween: Tween


func _ready() -> void:
	area_title.modulate.a = 0.0
	notice_label.modulate.a = 0.0
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


func _on_health_changed(current: int, maximum: int) -> void:
	hp_bar.max_value = maximum
	hp_label.text = str(current)
	if _hp_tween and _hp_tween.is_valid():
		_hp_tween.kill()
	_hp_tween = create_tween()
	_hp_tween.tween_property(hp_bar, "value", float(current), bar_tween_time)


func _on_mp_changed(current: int, maximum: int) -> void:
	mp_bar.max_value = maximum
	mp_bar.value = current


func _on_hearts_changed(current: int, _maximum: int) -> void:
	# The medallion has room for the count only; the ceiling is on the stats tab.
	hearts_label.text = str(current)


func _on_gold_changed(current: int) -> void:
	gold_label.text = str(current)


func _on_experience_changed(_current: int, to_next: int, level: int) -> void:
	level_label.text = "LV %d" % level
	xp_label.text = "MAX" if to_next <= 0 else "NEXT %d" % to_next


func _on_leveled_up(level: int) -> void:
	_show_notice("LEVEL %d" % level)


## Flash the weapon's name under the status frame, then fade it out again.
func _on_weapon_changed(weapon: WeaponData) -> void:
	if weapon != null:
		_show_notice(weapon.display_name.to_upper())


func _on_subweapon_changed(subweapon: SubWeaponData) -> void:
	subweapon_icon.texture = subweapon.icon if subweapon else null


## One shared slot for weapon swaps, pickups, level-ups and save confirmations.
## A new notice replaces whatever was there rather than queueing behind it.
func _show_notice(text: String) -> void:
	if text.is_empty():
		return
	notice_label.text = text
	if _notice_tween and _notice_tween.is_valid():
		_notice_tween.kill()
	_notice_tween = create_tween()
	_notice_tween.tween_property(notice_label, "modulate:a", 1.0, 0.15)
	_notice_tween.tween_interval(notice_hold_time)
	_notice_tween.tween_property(notice_label, "modulate:a", 0.0, 0.6)


func _on_area_entered(display_name: String) -> void:
	area_title.text = display_name.to_upper()
	if _title_tween and _title_tween.is_valid():
		_title_tween.kill()
	_title_tween = create_tween()
	_title_tween.tween_property(area_title, "modulate:a", 1.0, 0.6)
	_title_tween.tween_interval(2.0)
	_title_tween.tween_property(area_title, "modulate:a", 0.0, 0.8)
