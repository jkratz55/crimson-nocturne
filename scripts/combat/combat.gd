## The one place damage is worked out (SPEC 4.2.2).
##
## Both directions go through [method compute_damage]: the player's swings
## (Strength vs. the enemy's Defense) and everything that hurts the player
## (the attacker's power vs. the player's Defense). Keeping it static and
## side-effect free means the unit tests can check the curve without a scene.
##
## [b]Placeholder formula[/b] — the spec marks it as a starting point to
## rebalance once there is real content:
## [codeblock]
## core = base_damage + floor(attack_power * 0.5) - floor(defense * 0.5)
## dealt = max(1, round(core * random(0.9 .. 1.1)))
## [/codeblock]
class_name Combat
extends RefCounted

## Fractional spread applied to the result (0.1 = +/-10%).
const VARIANCE: float = 0.1


## Damage one hit should remove, before invincibility and other gates.
##
## [param roll] is the variance multiplier. Leave it at its default and one
## is rolled; pass an explicit value (1.0, 0.9, 1.1) for deterministic tests.
static func compute_damage(base_damage: int, attack_power: int, defense: int,
		roll: float = NAN) -> int:
	var core: int = base_damage + floori(attack_power * 0.5) - floori(defense * 0.5)
	var multiplier: float = roll if is_finite(roll) else randf_range(1.0 - VARIANCE, 1.0 + VARIANCE)
	return maxi(1, roundi(core * multiplier))


## The damage range [min, max] a hit can land in, for menus and tooltips.
static func damage_range(base_damage: int, attack_power: int, defense: int) -> Vector2i:
	return Vector2i(
		compute_damage(base_damage, attack_power, defense, 1.0 - VARIANCE),
		compute_damage(base_damage, attack_power, defense, 1.0 + VARIANCE))
