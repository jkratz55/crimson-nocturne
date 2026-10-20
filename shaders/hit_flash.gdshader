// Hit flash: the SotN palette flash (a CLUT swap there), as a canvas_item shader.
// Driven from GDScript:
//   flash_amount  0 = normal .. 1 = full flash
//   flash_color   the flash colour
//   flash_mode    0 = solid: blend toward flash_color, but leave each
//                     material's darkest tone (its sel-out outline, luma under
//                     outline_luma) alone, so a white flash keeps the silhouette
//                 1 = tint: multiply toward flash_color (with some gain), so a
//                     coloured flash keeps the form and its dark outlines
//   outline_luma  solid mode: texels darker than this keep their colour
//   keep_edges    solid mode: also keep every texel next to transparency (the
//                 contour), for dark sprites whose interior sits under
//                 outline_luma too (the player sets this and a lower luma)
// Alpha is never touched.
//
// In a Godot 4 canvas_item fragment(), COLOR already holds texture * modulate,
// so the texture must not be sampled and multiplied in again (that squared
// every colour of every sprite using this shader).
//
// Materials using this shader are `resource_local_to_scene` (or built at
// runtime) so every instance can flash independently.
shader_type canvas_item;

uniform float flash_amount : hint_range(0.0, 1.0) = 0.0;
uniform vec4 flash_color : source_color = vec4(1.0, 1.0, 1.0, 1.0);
uniform int flash_mode = 0;
uniform float outline_luma = 0.16;
uniform bool keep_edges = false;

const float TINT_GAIN = 1.6;

void fragment() {
	vec4 tex = COLOR;
	vec3 rgb;
	if (flash_mode == 1) {
		rgb = min(tex.rgb * mix(vec3(1.0), flash_color.rgb * TINT_GAIN, flash_amount), vec3(1.0));
	} else {
		float lit = step(outline_luma, dot(tex.rgb, vec3(0.299, 0.587, 0.114)));
		if (keep_edges) {
			vec2 px = TEXTURE_PIXEL_SIZE;
			float a = min(
				min(textureLod(TEXTURE, UV + vec2(px.x, 0.0), 0.0).a, textureLod(TEXTURE, UV - vec2(px.x, 0.0), 0.0).a),
				min(textureLod(TEXTURE, UV + vec2(0.0, px.y), 0.0).a, textureLod(TEXTURE, UV - vec2(0.0, px.y), 0.0).a));
			lit *= step(0.5, a);
		}
		rgb = mix(tex.rgb, flash_color.rgb, flash_amount * lit);
	}
	COLOR = vec4(rgb, tex.a);
}
