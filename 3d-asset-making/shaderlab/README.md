# Shader Lab: design and prototype animated and close-up surfaces before building them

For anything whose LOOK is a shader rather than geometry: TV and information screens, displays, lamps and signs,
glowing glass, water, animated adverts, blinking status lights, holograms. It also covers a surface the player sees
up close enough that its material carries it (brushed metal, frosted glass, wet stone).

The idea is borrowed from dev.shaders.app (a node-and-code GLSL IDE on threepipe): **a whole look is one small,
readable data file plus GLSL**. You change it, render it, look at it and change it again, in seconds and on the
game's own three.js revision. Here that is `spec.json` + `*.glsl`, rendered headless to contact sheets and real-speed
clips, or opened as an interactive page with live sliders for a person.

## Files
- `surface.js`: attaches a surface program to a three.js material by material name. **The game imports this same file**,
  so what was prototyped is what ships. Contract in its header: `void surface(inout Surface s, vec2 uv, float t)`, where
  `Surface {albedo, roughness, metalness, emission, alpha}` arrives with the material's own values.
- `lab.html` / `lab.js`: the page. `lab.mjs`: the CLI (static server plus headless Chrome over the DevTools protocol; no
  npm packages but `three`).
- `examples/tv-placeholder/`: a self-test (box TV, animated screen, glow card).

Setup once per machine: `cd <this folder> && npm install` (three is pinned to the game's revision, r186 here; change it with your game).

```
node lab.mjs render SPEC.json --out DIR [--times 8] [--clip front|all|none] [--seconds 4] [--fps 24] [--size 960x540] [--look game|dark|studio] [--bloom on|off] [--gpu]
node lab.mjs serve  SPEC.json [--port 8790]      # prints the page URL (127.0.0.1); orbit, scrub time, sliders, "copy uniforms"
```
`render` writes `sheet-<view>.png` (one row of frames over the loop), `<view>.mp4` (real speed) and `result.json`
(errors, triangles, materials, the game views' real pixel sizes). It **exits 2 on a GLSL error or a material missing
from the scene**, and prints the compiler's message with the offending lines. It also **exits 2 when a program outputs
NaN or Inf anywhere on its part at any moment of the loop** (sampled about 8 times a second before any frame is drawn;
no model calls). NaN/Inf blends as black and bloom smears it into a big black rectangle (an old-TV prop: the
flash `exp(-(T - 10.0) * 10.0)` overflowed at T < 1.1 inside a branch `step()` discarded; GLSL evaluates both sides of
`mix()`, and `mix(c, Inf, 0.0)` is NaN). Clamp such arguments: `exp(-max(x, 0.0) * k)`, `pow(max(x, 0.0), p)`,
`a / max(b, 1e-4)`. `surface.js` also zeroes a non-finite value at runtime, so a case the sampling missed (another
uniform setting, a moment between samples) shows as a missing glow for a frame, not a black block. With swiftshader (the default; no GPU
needed) a 960x540 frame takes about 0.1 s.

## spec.json
```jsonc
{
  "title": "...",
  "model": "tv.glb",                       // optional, relative to the spec; the GLB's material NAMES are the contract
  "primitives": [ {"shape": "box|plane|cylinder|sphere", "size": [..], "position": [..], "rotation": [deg..],
                   "material": "screen", "color": "#..", "roughness": 0.5, "metalness": 0} ],   // optional, for blockouts
  "programs": { "screen": {"glsl": "screen.glsl", "uniforms": {"uGain": 2.0, "uTint": "#9fd8ff", "uOn": 1},
                           "ranges": {"uGain": [0, 6]}, "unlit": false, "blending": "additive", "side": "double"} },
  "look": "game",                          // game (the game's own renderer and light) | dark (a dim room) | studio
  "context": "room",                       // none | floor | room (floor + back wall, to judge spill and glow)
  "lights": [ {"type": "point|spot", "color": "#9cf", "intensity": 2, "position": [..], "distance": 3} ],
  "bloom": {"strength": 0.5, "radius": 0.5, "threshold": 1.0},   // or false; the GAME HAS NO BLOOM (see below)
  "views": [ {"name": "front", "dir": [0, 0.05, 1]}, {"name": "close", "position": [..], "target": [..], "fov": 30},
             {"name": "game", "game": {"distance": 12, "fov": 62, "heightPx": 1688, "dir": [0.3, 0.35, 1], "zoom": 6}} ],
  "clip": {"seconds": 4}
}
```
A `game` view renders the frame the phone renders (portrait, `heightPx` tall, the game's fov at the game's distance) and
crops it to the object, enlarged with no smoothing by `zoom`. **That crop is the truth about what the player can read.**
`result.json` gives its size in real pixels.

## The method: design first, then build (in this order)
1. **Where and how is it seen?** From the game's camera (read it from the game's code: for example a chase camera
   30 m + 0.32 m per metre of train behind, zoom 0.35–4, portrait fov about 62°, maxPixelRatio 2), work out how
   many pixels tall the object is at the ordinary ride, at the closest zoom and at a station dwell. Put those as `game`
   views in the spec on day one. Below about 40 px, nothing finer than about 1/10 of its height survives. Design the
   content for that size and add finer detail only for the close views.
2. **Write `DESIGN.md` before any GLSL:** what it is for and where it stands; its **states** (off, standby, booting,
   on, showing content X) and what switches them; the content **storyboard** as a loop (period in seconds, beat by
   beat); the palette, with emission levels as numbers; what reads at game size and what only up close; how it glows
   in day light and at night; its per-pixel cost.
3. **Build it as layers, one at a time, looking at each** (a screen as the example):
   - **content**: shapes from SDFs (box, circle, rounded box, line), smooth edges by `fwidth`, motion from periodic
     functions of `t` whose periods divide the loop (`fract(t / T)`), hash noise for life. No procedural text: for
     text use a glyph atlas texture; in this game prefer icons and shapes.
   - **display physics**: the pixel or subpixel grid only where a cell covers more than about a pixel (fade it by
     `fwidth`, or it moirés), the backlight's slight unevenness and edge falloff, a faint refresh band. Keep these subtle.
   - **glass**: the screen is a LIT material, albedo near black, roughness 0.05–0.15, so the room's reflection lies over
     the picture and the off screen reads as black glass, not a flat black card.
   - **emission level**: tone mapping (NeutralToneMapping in the game) flattens anything far above 1. Give highlights
     1.5–3 and the body of the picture 0.6–1.2, or it turns into a flat pastel slab.
   - **glow**: the game has **no bloom pass**, so glow is geometry. A slightly larger card behind or around the screen,
     unlit, additive, `exp(-k * distance-to-rectangle)`, no depth write. Light spill on the surroundings is a point or
     spot light only where it matters (each costs every lit pixel), otherwise a baked spill decal. Check that the bloom
     look and the no-bloom look both read as "on".
4. **Check:** render sheets of every view plus the `game` view, and a clip at real speed. Look at the frames enlarged,
   in the `game` and the `dark` look. Watch the game-size clip for flicker, crawling edges or aliasing (temporal
   artefacts don't show in stills). Fix and render again; the loop takes seconds.
5. **Cost:** count the per-pixel work (texture fetches, loop iterations, transcendental functions). On a phone the
   screen covers few pixels at ride distance, so its cost is small there. The close views are where it costs. No loop
   longer than about 16 steps, at most two texture fetches, and nothing animated on a material that covers half the
   screen.
6. **Hand to the game:** the GLB carries the material names (`screen`, `glow`). The `.glsl` files and the uniforms
   (the page's "copy uniforms") go next to it. The game calls `attachByName(gltf.scene, programs)` and advances `uTime`
   from its own clock (and sets `uOn` from game state).
   **Every extra render pass runs the program too** (a selective-bloom emissive-only render, an override material, a
   picking or depth copy): a pass that rebuilds materials from `emissive × emissiveMap` draws the GLB's baked fallback
   still over the live picture (the viewer's bloom: a frozen second picture, smeared and hazed). Give the
   pass the program in its emission-only form (`attachSurface`, sharing the uniforms), or bloom the finished frame.

## Modelling contract for a screen-like part (Blender side)
- **glTF flips V**: Blender's v = 1 (top of the picture) arrives in the program as `uv.y = 0`. A program written with
  y up starts with `uv.y = 1.0 - uv.y;` (primitives in the lab are not flipped; GLB models are). Found on a TV that showed upside down.
- The visible face is its own mesh or material slot named for its program (`screen`), UV 0..1 exactly over the active
  picture area, no stretch (UV aspect = the physical aspect, noted in DESIGN.md so content isn't squashed), facing +Y
  or as documented.
- The bezel/glass edge geometry carries the reflection, so give it a small chamfer; a sharp box edge catches no light.
- A glow card, if used, is a separate quad with material `glow`, slightly in front of or behind the screen, sized to its
  falloff.
