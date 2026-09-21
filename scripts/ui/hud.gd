## Status display: HP / MP bars, HP number, heart count and sub-weapon icon.
##
## Purely reactive — it only listens to [Events] and never queries the
## player directly, so it works unchanged in any room or menu scene.
class_name HUD
extends CanvasLayer

@export var bar_tween_time: float = 0.25

@onready var hp_bar: TextureProgressBar = %HPBar
@onready var mp_bar: TextureProgressBar = %MPBar
@onready var hp_label: Label = %HPLabel
@onready var hearts_label: Label = %HeartsLabel
@onready var subweapon_icon: TextureRect = %SubweaponIcon
@onready var area_title: Label = %AreaTitle

var _hp_tween: Tween
var _title_tween: Tween


func _ready() -> void:
	area_title.modulate.a = 0.0
	Events.player_health_changed.connect(_on_health_changed)
	Events.player_mp_changed.connect(_on_mp_changed)
	Events.player_hearts_changed.connect(_on_hearts_changed)
	Events.player_subweapon_changed.connect(_on_subweapon_changed)
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


func _on_hearts_changed(current: int) -> void:
	hearts_label.text = str(current)


func _on_subweapon_changed(subweapon: SubWeaponData) -> void:
	subweapon_icon.texture = subweapon.icon if subweapon else null


func _on_area_entered(display_name: String) -> void:
	area_title.text = display_name.to_upper()
	if _title_tween and _title_tween.is_valid():
		_title_tween.kill()
	_title_tween = create_tween()
	_title_tween.tween_property(area_title, "modulate:a", 1.0, 0.6)
	_title_tween.tween_interval(2.0)
	_title_tween.tween_property(area_title, "modulate:a", 0.0, 0.8)
