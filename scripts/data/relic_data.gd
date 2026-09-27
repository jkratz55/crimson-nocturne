## A relic that permanently unlocks a traversal ability (SPEC 4.1).
##
## Picking one up adds [member ability] to [member GameManager.unlocked_abilities],
## which is what the player checks before double-jumping and what the save
## file persists. Relics are never unequipped — holding one is the unlock.
class_name RelicData
extends ItemData

## Ability id granted on pickup. See [constant GameManager.ABILITY_DOUBLE_JUMP]
## and friends for the ids the player currently honours.
@export var ability: StringName = &""
