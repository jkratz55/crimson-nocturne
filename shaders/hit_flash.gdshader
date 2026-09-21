// Hit flash: blends the sprite toward a solid colour while keeping its alpha.
// Driven from GDScript via the `flash_amount` uniform (0 = normal, 1 = solid).
// Materials using this shader are `resource_local_to_scene` so every
// instance can flash independently.
shader_type canvas_item;

uniform float flash_amount : hint_range(0.0, 1.0) = 0.0;
uniform vec4 flash_color : source_color = vec4(1.0, 1.0, 1.0, 1.0);

void fragment() {
	vec4 tex = texture(TEXTURE, UV) * COLOR;
	COLOR = vec4(mix(tex.rgb, flash_color.rgb, flash_amount), tex.a);
}
