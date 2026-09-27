## Vesper's level, experience and four base stats (SPEC 4.3).
##
## This is the *base* character sheet only. Equipment bonuses are layered on
## top by [GameManager], which is what gameplay actually reads — so a ring
## can never be baked into the saved stats by accident.
##
## Every number here is a tunable placeholder from the spec. They live as
## constants rather than exports because there is exactly one player.
class_name PlayerStats
extends RefCounted

## Stats at level 1. Constitution is chosen so max HP starts at 80, which is
## what the Phase 1 prototype was tuned against.
const BASE_STRENGTH: int = 5
const BASE_CONSTITUTION: int = 6
const BASE_DEFENSE: int = 2
const BASE_LUCK: int = 4

## Gains per level-up (SPEC 4.3 placeholder: +2 CON / +1 STR / +1 DEF / +1 LCK).
const GAIN_STRENGTH: int = 1
const GAIN_CONSTITUTION: int = 2
const GAIN_DEFENSE: int = 1
const GAIN_LUCK: int = 1

## Hit points = [constant BASE_HP] + Constitution * [constant HP_PER_CONSTITUTION].
const BASE_HP: int = 50
const HP_PER_CONSTITUTION: int = 5

const MAX_LEVEL: int = 99

var level: int = 1
## Experience banked towards the *next* level, not a lifetime total.
var experience: int = 0
var strength: int = BASE_STRENGTH
var constitution: int = BASE_CONSTITUTION
var defense: int = BASE_DEFENSE
var luck: int = BASE_LUCK


## Experience needed to get from [param from_level] to the next one:
## ceil(50 * level ^ 1.5), per SPEC 4.3.
static func xp_for_level(from_level: int) -> int:
	return ceili(50.0 * pow(float(maxi(1, from_level)), 1.5))


## Experience still needed for the next level-up, or 0 at the cap.
func xp_to_next_level() -> int:
	if level >= MAX_LEVEL:
		return 0
	return maxi(0, xp_for_level(level) - experience)


## Bank [param amount] experience, levelling up as many times as it covers.
## Returns the number of levels gained (0 if none).
func add_experience(amount: int) -> int:
	if amount <= 0 or level >= MAX_LEVEL:
		return 0
	experience += amount
	var gained: int = 0
	while level < MAX_LEVEL and experience >= xp_for_level(level):
		experience -= xp_for_level(level)
		level += 1
		gained += 1
		_apply_level_gains()
	if level >= MAX_LEVEL:
		experience = 0
	return gained


## Base max HP from Constitution. Equipment CON is added by [GameManager].
func max_hp_for(total_constitution: int) -> int:
	return BASE_HP + total_constitution * HP_PER_CONSTITUTION


func to_dict() -> Dictionary:
	return {
		"level": level,
		"experience": experience,
		"strength": strength,
		"constitution": constitution,
		"defense": defense,
		"luck": luck,
	}


## Rebuild from a save file. Unknown or missing keys fall back to the
## level-1 defaults rather than erroring, so an older save still loads.
static func from_dict(data: Dictionary) -> PlayerStats:
	var stats := PlayerStats.new()
	stats.level = clampi(int(data.get("level", 1)), 1, MAX_LEVEL)
	stats.experience = maxi(0, int(data.get("experience", 0)))
	stats.strength = int(data.get("strength", BASE_STRENGTH))
	stats.constitution = int(data.get("constitution", BASE_CONSTITUTION))
	stats.defense = int(data.get("defense", BASE_DEFENSE))
	stats.luck = int(data.get("luck", BASE_LUCK))
	return stats


func _apply_level_gains() -> void:
	strength += GAIN_STRENGTH
	constitution += GAIN_CONSTITUTION
	defense += GAIN_DEFENSE
	luck += GAIN_LUCK
