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

## Emitted whenever the player's heart count (sub-weapon ammo) changes, or
## when the maximum moves because a "Heart Max Up" was collected.
signal player_hearts_changed(current: int, maximum: int)

## Emitted when the equipped melee weapon changes. [param weapon] may be null.
signal player_weapon_changed(weapon: WeaponData)

## Emitted when the equipped sub-weapon changes. [param subweapon] may be null.
signal player_subweapon_changed(subweapon: SubWeaponData)

## Emitted once when the player's HP reaches zero.
signal player_died

# --- Progression & economy --------------------------------------------------

## Emitted whenever the player's gold changes.
signal player_gold_changed(current: int)

## Emitted whenever experience is banked. [param to_next] is what is still
## needed for the next level, and is 0 at the level cap.
signal player_experience_changed(current: int, to_next: int, level: int)

## Emitted once per level gained, after the new stats are in effect.
signal player_leveled_up(level: int)

## Emitted when the effective stats change for any reason — a level-up, a
## ring going on or coming off, a fresh game.
signal player_stats_changed

## Emitted when an item is equipped or unequipped.
## [param slot] is a [enum GameManager.Slot]; [param item] may be null.
signal player_equipment_changed(slot: int, item: ItemData)

## Emitted when anything is added to or removed from the inventory.
signal inventory_changed

## Emitted when a unique world item is picked up, so already-collected
## pickups can remove themselves on the next visit.
signal world_item_collected(item_id: StringName)

## Emitted when a traversal ability is unlocked (SPEC 4.1 gating).
signal ability_unlocked(ability: StringName)

# --- Save data --------------------------------------------------------------

## Emitted after the game is written to [param slot].
signal game_saved(slot: int)

## Emitted after [param slot] has been loaded into [GameManager], before the
## world has been rebuilt around it.
signal game_loaded(slot: int)

## A [SavePoint] was activated. The UI answers by opening the slot picker;
## the save point itself never touches a menu.
signal save_point_activated(room_id: StringName, spawn_position: Vector2)

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

## Show a one-line notice on the HUD ("LEAP STONE", "GAME SAVED", ...).
signal notice_posted(text: String)
