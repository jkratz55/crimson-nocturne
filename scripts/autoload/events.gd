## Global signal bus (autoload: [code]Events[/code]).
##
## Decouples gameplay systems from presentation systems. Gameplay code
## emits facts ("the player's HP changed", "an enemy died") and anything
## that cares — HUD, audio, achievements, save system — subscribes without
## the emitter needing a reference to it.
##
## Rule of thumb: only put signals here that are genuinely cross-cutting.
## Parent/child communication should stay as regular node signals.
extends Node

# --- Player -----------------------------------------------------------------

## Emitted whenever the player's hit points change (damage, heal, respawn).
signal player_health_changed(current: int, maximum: int)

## Emitted whenever the player's magic points change.
signal player_mp_changed(current: int, maximum: int)

## Emitted whenever the player's heart count (sub-weapon ammo) changes.
signal player_hearts_changed(current: int)

## Emitted when the equipped sub-weapon changes. [param subweapon] may be null.
signal player_subweapon_changed(subweapon: SubWeaponData)

## Emitted once when the player's HP reaches zero.
signal player_died

# --- Combat -----------------------------------------------------------------

## Emitted when any enemy is destroyed.
signal enemy_killed(enemy: Enemy)

## Emitted whenever damage is dealt to anything, for floating damage numbers.
## [param is_player] is true when the player was the one who got hurt.
signal damage_dealt(amount: int, world_position: Vector2, is_player: bool)

# --- Presentation -----------------------------------------------------------

## Ask the active camera to shake.
signal camera_shake_requested(strength: float, duration: float)

## Show an area title card (e.g. "CASTLE ENTRANCE") on the HUD overlay.
signal area_entered(display_name: String)
