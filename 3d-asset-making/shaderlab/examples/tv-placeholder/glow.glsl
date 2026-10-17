// Fake glow card behind the screen (additive, unlit): falloff from the screen's rectangle, no post effect needed.
void surface(inout Surface s, vec2 uv, float t) {
  vec2 d = max(abs(uv - 0.5) - vec2(0.32, 0.28), 0.0);
  float g = exp(-length(d) * 14.0);
  s.albedo = vec3(0.0);
  s.emission = uTint * g * uStrength * uOn;
}
