// Lab self-test content: slow gradient + a moving bar, a pixel grid that fades out when pixels get smaller than the
// screen's own pixels (fwidth), loop period 4 s.
void surface(inout Surface s, vec2 uv, float t) {
  float ph = fract(t / 4.0) * 6.2831853;
  vec3 c = mix(vec3(0.05, 0.2, 0.5), vec3(0.1, 0.6, 0.7), uv.y + 0.15 * sin(ph + uv.x * 3.0));
  c += vec3(1.0, 0.8, 0.4) * smoothstep(0.03, 0.0, abs(uv.x - fract(t / 4.0)));
  vec2 px = uv * vec2(160.0, 90.0);
  float cell = fwidth(px.x);
  float grid = mix(0.85 + 0.15 * smoothstep(0.5, 0.35, abs(fract(px.x) - 0.5)), 1.0, smoothstep(0.3, 0.8, cell));
  c *= grid;
  s.emission = c * uTint * uGain * uOn;
  s.albedo = vec3(0.02);
  s.roughness = 0.08;
}
