#!/usr/bin/env python3
"""render.py: the ONE shared renderer for 3D assets (Blender 5.2, headless Cycles, lit like the game).

Stop writing your own render scripts: this one loads any .blend (linked libraries resolve) or .glb, hides helpers,
frames the asset, lights it like the game's three.js game (sun + sky, Khronos PBR Neutral, exposure 0) at day,
dusk, night and rain, and writes thumbnails, sheets and review contact sheets. It never saves the input.

RUN (the build box: blender; prefix MV_BLENDER_GPU=1 to let it use the GPU, see DEVICE):
  blender -b --factory-startup -noaudio --python render.py -- <mode> [input] [options]
  python3 render.py --help            (prints this text)

MODES
  thumb <file>      The asset's dashboard thumbnail: one three-quarter view (azimuth 35, elevation 20) per state.
                    --states day,dawn,dusk,night,rain (default, a design decision; any subset). Writes <dir of file>/renders/<stem>.png
                    for day and <stem>-dawn.png, <stem>-dusk.png, <stem>-night.png, <stem>-rain.png (or into --out DIR).
  sheet <file>      Component sheet: front34, rear34, side, top at --size each (default 1280) -> SHEET.jpg beside
                    the file (or --out FILE.jpg). --states day (default) adds one row per extra state.
                    An upright, thin part (a door, a window unit: plan size under a quarter of its height) gets
                    high34 (45 deg up, 35 deg off its broad face) in place of top, which would be a strip.
  round <file>      Assembled-asset review: 6 day views (front34, rear34, side, top, under34, nose crop), front34 +
                    side at dusk, night and rain, and --interior N views from inside (default 2, at day and night;
                    skipped when the asset has no floor/roof to stand under) -> --out rounds/ROUND-<n>.jpg
                    (default <dir of file>/rounds/ROUND-<next n>.jpg), labelled tiles, tile size --size (default 960).
  versions          LOD check: --files original.blend,near.glb,mid.glb,far.glb --dist 14,24,70 ('near.glb+bogies.glb'
                    = two files shown together as one column). One game camera per
                    distance (vertical fov 40, 1920x1080 screen, chase angle), every file at the same framing, one row
                    per distance, cropped to the asset at TRUE screen pixels (small crops are enlarged by whole
                    pixels, labelled xN) -> --out FILE.jpg (default <dir of first file>/versions/VERSIONS.jpg).
                    The chase camera stands 40 deg off --front, 17 deg up. A part that faces ONE way (a door on the
                    +y flank) needs --front +y (or -y ...), else the camera may stand behind it; --az DEG / --el DEG
                    set the camera's direction outright. Files with the same name in different folders
                    (before/door.blend,after/door.blend) are labelled by folder and keep separate tiles.
  beforeafter       --before X --after Y: the same camera(s) side by side -> --out FILE.jpg (default
                    <dir of after>/BEFORE-AFTER.jpg). --views front34 (default; any view names) --states day.
  EVERY picture mode also writes its tiles WITHOUT labels into a folder named like the picture (--out X.jpg ->
                    X/<view>-<state>.png; beforeafter: X/before-<view>-<state>.png and X/after-...; versions:
                    X/<label>-<dist>m.png): same camera, no text. Give THESE to a blind judge, never a crop of the
                    labelled sheet. --no-tiles removes the folder after composing.
  lodcmp            --original X.blend|glb --versions near.glb,mid.glb,far.glb [--views front34,side,rear34,top]
                    [--states day,dusk,night] [--at-switch]: every version against the original from the same
                    cameras and the same light state; the ORIGINAL's asset lights light every version (versions'
                    own light empties are ignored, so a version without lit windows shows dark glass at night).
                    Filled frame (960 px, the asset filling it): day uses --views; dusk and night use
                    --state-views (default front34,side). Per view and version: mean CIE76 dE and luminance drift on
                    the pixels both cover, mean RGB delta, the share of pixels with dE > 12, regions (16 px cells
                    mean dE > 25, joined), the silhouette change; material colour and gloss from Cycles' diffuse and
                    glossy colour passes (day only); a masked difference picture (magenta = dE > 12, cyan = only one
                    covers, yellow = a failing region).
                    --at-switch also renders each version at the distance where the game shows it, through the game
                    camera (--screen 1920x1080, --fov 40, chase view az -40 el 17), cropped to the asset at TRUE
                    pixels, judged on those pixels (region cell = crop/40, 3-16 px): near at --near-dist, mid at
                    R0-hyst, far at R1-hyst, all from scripts/switch.json --family (city-kit: 7.5, 18, 64 m;
                    train: 7.5, 92, 292 m; distance = surface distance, as the game measures it), every state.
                    -> LODCMP.jpg (day), LODCMP-dusk.jpg, LODCMP-night.jpg, LODCMP-switch.jpg beside the original
                    (or --out) + lodcmp.json beside it: results[version].filled[state][view] and
                    results[version].switch[state] = metrics + blobs[], each region with box_px (x0, y0, x1, y1
                    from the top-left of its tile) and place (blender_xyz, gltf_xyz, normal_blender, object, objects,
                    hits, box_blender, box_gltf: a 3x3 ray-cast grid on the VERSION), so the LOD tool can lock those
                    vertices and simplify again. EXIT 4 when any version breaks a limit (see LODCMP LIMITS).

  inspect <file>    Close-ups where faults live: one 1280x720 sheet per joint at <= --mmpx (default 1.0 mm/px):
                    --views N (default 3) tinted views around the joint, picked for the clearest line of sight, 1 low
                    view along the seam, 1 view as rendered (Cycles, materials, --state day|dusk|night: speckle,
                    flicker, missing UVs show here), an x-ray tile with --xray. The two parts are tinted orange and blue
                    with cavity shading, neighbours see-through grey (--isolate hides them); everything is cut to a box
                    round the joint, so nothing else hides it. Which places (any mix):
                      --part NAMES      every joint of these objects (comma list, globs, name#k, parts.json names)
                      --relations [--parts A,B]  joints of recorded relations (parts.json host/relations or kit3d's
                                        scene property); none recorded -> joints of --parts by proximity
                      --from FILES      places in a kit3d check.json, a mesh_integrity json (FLOATING, GAPS, FLICKER,
                                        LOOKED INTO, lost, turned-over / duplicate faces, inside-out parts, flipped copies,
                                        back-to-back places, parts moved against the reference; glTF frame
                                        converted), a sweep.json (only if it has places)
                                        or an earlier inspect.json: the same places with the SAME cameras,
                                        windows and tiles (before/after, clean/faulted, last round/this round)
                      --at x,y,z[;x,y,z]  points, Blender world
                      --round           joints of every instance changed since the previous round (--since: a .blend,
                                        .glb or fingerprints.json; default the newest rounds/ROUND-*.blend beside the
                                        file) + the newest rounds/ROUND-*/integrity.json + *check*.json beside it
                    A joint = where two parts come within --joint-tol (0.012 m); long seams are cut into pieces so each
                    sheet keeps the mm/px; --max-places (30) caps the sheets (the rest are listed as skipped).
                    -> --out DIR (default <dir of file>/inspect): p01.jpg ... + inspect.json (per place: xyz, glTF xyz,
                    parts, instances, kind, source, mm/px, window, views with direction and clear line of sight,
                    measured: touch/inside/hover share and min/median/max signed mm, + = off the host) +
                    fingerprints.json (for the next --round). The sheets carry colours, names and mm/px only, never a
                    measurement or why the place was picked (blind framing for luna_review.py --questions).
                    the build box: numpy inside Blender starts a thread per core: run it as `OPENBLAS_NUM_THREADS=1 systemd-run
                    --user --scope -p MemoryMax=12G -p MemorySwapMax=0 nice -n 10 blender -b -t 8 ...` (a car, 970
                    parts, 24 places: 77-129 s wall, 1.6-1.8 GB peak; without the thread cap it took 374 s).

OPTIONS
  --out PATH            output file (sheet/round/versions/beforeafter) or directory (thumb)
  --states LIST         day,dawn,dusk,night,rain (thumb default all five; sheet/beforeafter default day)
  --size PX             tile width (thumb/sheet 1280, round 960, beforeafter 1280); height = width * 3/4
  --samples N           Cycles samples (default 32, OIDN denoise on)
  --views LIST          sheet/beforeafter views: front34,rear34,side,top,under34,nose,front,rear,top34
  --interior N          round: number of interior views (default 2; 0 = none)
  --n N                 round number for the default ROUND-<n>.jpg name
  --front +x|-x|+y|-y   which way the asset faces (default +x: the nose is at max X); `--front -y` and `--front=-y` both work
  --focus x,y,z,radius  sheet/beforeafter: frame a cube of that half-size around the point (metres) instead of the
                        whole asset: the close-up of a tall or long asset's head, door or base (write --focus=0,-0.3,3.6,0.4
                        when x is negative)
  --region GLOBS        sheet/beforeafter: frame the objects whose names match (comma separated, e.g. 'LP_head*,LP_optic*');
                        the rest of the asset stays in the picture around them
  --night-prop NAMES    the asset's OWN night property (comma list, e.g. lp_night): set on the scene and view layers to
                        the state's light share (night 1, dusk 0.4, day 0), like idle_night; --wet-prop NAMES the same for rain
  --labels A,B          versions: the column labels, one per file (default: from the file names)
  --collection NAME     render only this collection (repeatable); default = everything renderable
  --hide GLOBS          extra object/collection name globs to hide, comma separated (e.g. "stand_*,Cage*")
  --helpers REGEX       collections treated as helpers and hidden (default: STAGE|REVIEW|CMP_|LOD_|EXPORT_|BAKE|
                        HELPER|GUIDE|WIDGET|_ prefixes, case-insensitive); --helpers '' keeps them all
  --keep-file-lights    keep the file's own Blender lights (default: hidden; review rigs are not the asset)
  --no-mount-lights     do not use mount.light.* empties as cabin lights when no light.* empties exist
  --no-ground           no ground plane
  --az DEG --el DEG     thumb camera override (relative to the front)
  --dist LIST           versions distances in metres (default: asset.json lods switch distances, else 14,24,70)
  --screen WxH --fov D  versions screen and vertical fov (default 1920x1080, 40 = the game camera)
  --device auto|gpu|cpu (default auto: OPTIX, else CUDA, else CPU) --threads N (CPU threads, default 8, max 8)
  --title TEXT          sheet title (default: file name + Kyiv time)
  --no-tiles            delete the per-view PNGs after composing (default: kept in <out stem>/ beside the jpg)
  --strict / --no-strict  round: exit 3 (after writing the sheet) on floating bodies, FLICKER faults, GAPS or
                        textured meshes without UVs (default strict). --no-integrity skips the check.
                        --no-look skips the advisory LOOK lines (look.py: edges in px, flat shading, colour
                        spread, calm/busy cells, outline; RT_CHECK lines + the sheet header; never fails the round).
  --at-switch [--family F] [--switch R0,R1 --hyst M --near-dist M] --state-views LIST
                        lodcmp: game-distance pass (default off) and dusk/night views. Distances come from
                        scripts/switch.json (the one place; --family train|building|city-kit, default city-kit
                        = the city kit 24,70 / 6, near 7.5 m; train = placements.json 100,300 / 8);
                        explicit --switch/--hyst/--near-dist override it. versions --dist falls back to the
                        same file (asset.json lods switch distances first).
  --max-de --max-lum --max-albedo --max-gloss --max-cell --blob-share --max-hot
                        lodcmp limits (defaults 10, 0.08, 0.10, 0.25, 25, 0.01, 1.0 = off; see LODCMP LIMITS)

LODCMP LIMITS (any one fails the version, exit 4; measured 2026-10-13 on a car + a car near/mid/far, 4 views each)
  mean dE > 10       CIE76 on the pixels both cover. Roof-only top views (geometry + bake, no glass): 2.7-7.1;
                     glass-heavy views with only glass/colour drift: 6.2-8.5; views with a lost or broken part: 10-13.
  luminance +-8 %    the beauty pass (OPTIMIZE.md item 7's 8 %); a car near rear34 +9 %, everything else within 6 %.
  material +-10 %    luminance of Cycles' Diffuse Color pass = base x (1 - metallic): lighting cannot hide a baked
                     metallic/colour error. a car near (steel baked white, metallic 0.23 vs 0.55): +12..+20 %;
                     its mid/far: +3..+6 %; a car near (paler paint): +14 %.
  gloss +-25 %       Glossy Color pass: a car near/mid/far lost a third (-31..-38 %); a car versions within 5 %.
  a region           16 px cells (>= 50 % covered) with mean dE > 25, joined; one >= 1 % of the asset fails, with its
                     box drawn yellow on the difference picture and darker/lighter named. Caught: a car clerestory
                     windows baked to dark boxes (side view, roof strip, L* -18..-23, dE 27-29, 1.8-3.4 %); a car's
                     broken gangway end on all three versions (rear34, 10-13 %, dE 33-37); flat grey glass (dE 25-27).
  per state         the same limits for day, dusk and night, filled and at-switch (material/gloss: day only).
                     Night is not loosened on purpose: lit windows and lamps are the strongest colour at distance.
                     2026-10-13: night luminance -21..-51 % on all six versions = real (versions have no cabin glow:
                     mid/far glass dark, a car near windscreen dark, a car far no lit windows); dusk side -8..-21 %
                     (lost window glow on the shadow side). At switch, day: a car mid 18 m and far 64 m pass; a car
                     near 12 m (nose glass, dE 27) and a car at every distance (lighter front end, 6 %, dE 27-29) fail.
  pixels dE > 12     reported, not a limit (glass reflections dominate it: 17-38 % on every version).
  thin features      scripts/_thin.py, on every pair (orange = lost, green = added on the difference picture): a pixel is a
                     feature when it stands out from its surroundings (dE > 18 against the mean of a window 1/25 of the
                     asset wide); it is kept when the version shows that colour (dE < 14) within 3 px. Lost or added
                     pixels are joined; a piece of >= 0.04 % of the asset (and >= 12 px) that is >= 3 px thick is a
                     broken feature. Made because a test run near passed every limit above with white patches in its red
                     stripe and torn chrome trims (2026-10-13). ADVISORY by default (set on a train car alone);
                     --thin-fail makes it count, --no-thin skips it.
  Not a judgement of beauty: a pointer to open the boxes large. Pass --max-* to loosen per asset, and say why.

ROUND GEOMETRY CHECK
  round writes the rendered geometry (every instance, linked libraries included) to <tiles>/geometry-check.glb and
  runs ~/.claude/skills/3d-modelling/scripts/mesh_integrity.py --from-below on it in the background while the GPU
  renders (output: <tiles>/integrity.txt, integrity.json). Its BODIES/GAPS/FLICKER/LOOKED INTO/RESULT lines and a
  UV check (an image texture sampled through UVs on a mesh with no UV map) are printed (RT_CHECK) and written into
  the sheet header. The tiles (960 px, about 1 cm a pixel on a 10 m car) cannot show slits, blinking, speckle or back faces: this check can.

LOOK (all modes; matches src/world/Environment.js + day-night.js)
  Cycles, 32 spp + OIDN, view transform Khronos PBR Neutral, look None, exposure 0 (game: NeutralToneMapping 1.0).
  day   sun 2.7 (game DirectionalLight 2.7, noon colour #fff7e7) at 45 deg, 2.5 deg soft shadow; Sky Texture
        (MULTIPLE_SCATTERING, probed; gradient fallback) scaled so the sky lights a horizontal surface like the
        game's hemisphere + environment fill.
  dusk  sun 4 deg, warm #ffb26b; sky peach toward the sun, lavender away, zenith #676b9d (game 17:45 keys).
        Asset lights at 40 %.
  night no sun; deep-blue world (#13243f horizon, #03091c zenith) very dim; moon 0.12 #b9d0ff; asset lights on.
  rain  overcast grey sky, no sun; every material darker (base x0.75) and glossier (roughness x0.4, clamped) on
        in-memory values only (restored after; the file is never saved); ground wet.
  The sun follows the camera (from ~35 deg to the camera's left/right, so the visible long side is lit); the
  ground is a concrete-grey plane at the asset's lowest point, hidden for the underside view (a bounce light
  from below lights it instead).

ASSET LIGHTS (night 100 %, dusk 40 %)
  The shader library's night is switched with them: every state sets the attributes idle_night (the same share: night 1,
  dusk 0.4, dawn 0.3, day 0) and idle_wet (rain 1) on this render's scene and view layers, which the shared kinds read
  (glass.window `glow`, lamp.emissive `night`). In memory only.
  Every empty named light.<kind>.<n> (also inside linked/instanced collections) becomes a real light. Read from its
  custom properties, else from asset.json "lights" (beside the file or one folder up, matched by "name"):
  type point|spot|area, color/colour (#hex, [r,g,b] sRGB) or kelvin, watts/power (Blender W) or intensity
  (three.js candela, W = 4*pi*cd), cone/spot_angle (deg), radius. Spots aim along the empty's -Z (an unrotated
  head* empty aims along the front, 8 deg down). Defaults by kind: head* spot 1000 W 45 deg; tail*/red*/stop* red
  point 8 W; marker* 8 W; street*/post*/pole* spot 400 W 110 deg; sign*/screen* 10 W; anything else (cabin, saloon,
  ceiling, lamp ...) point 30 W; colour 2700 K as the eye sees it (warm white; a raw blackbody renders 2700 K plain
  orange). With no light.* empties, mount.light.* empties (fixture mounts) become 30 W 2700 K cabin
  lights 0.1 m below the mount, or just under the ceiling when the mount sits above it (--no-mount-lights to skip).
  Interior views keep the asset's lights on in every state (a running car keeps its saloon lit); exteriors use the
  state's level. Emissive materials always show.

DEVICE
  auto tries OPTIX then CUDA then CPU (<= 8 threads). the build box's blender is a launcher that HIDES
  the GPU unless MV_BLENDER_GPU=1 (other GPU jobs may own it): check `nvidia-smi` and
  `python3 <films>/scripts/gpu_guests.py`, then run
  `MV_BLENDER_GPU=1 nice -n 10 blender -b ...`. Under 2.5 GB free VRAM it falls back to CPU.
  The compositor stays on the CPU (no GPU context for "CPU" renders).

EXAMPLES (the build box)
  B=blender; R=~/.claude/skills/3d-asset-making/scripts/render.py
  MV_BLENDER_GPU=1 nice -n 10 $B -b --factory-startup -noaudio --python $R -- thumb car.blend --states day,dusk,night,rain
  MV_BLENDER_GPU=1 nice -n 10 $B -b --factory-startup -noaudio --python $R -- sheet components/bogie_frame/bogie_frame.blend
  MV_BLENDER_GPU=1 nice -n 10 $B -b --factory-startup -noaudio --python $R -- round original/car.blend --out rounds/ROUND-4.jpg
  MV_BLENDER_GPU=1 nice -n 10 $B -b --factory-startup -noaudio --python $R -- versions \\
      --files original/car.blend,export/car-near.glb,export/car-mid.glb,export/car-far.glb --dist 14,24,70 --out v.jpg
  MV_BLENDER_GPU=1 nice -n 10 $B -b --factory-startup -noaudio --python $R -- beforeafter --before old.glb --after new.glb

Every render prints `RT_RENDER <secs>s <path>`; the end prints `RT_DONE <mode> <total secs>s <output>`.
Composing uses the system python3 + Pillow (this same file, `python3 render.py --compose spec.json`); without
Pillow the sheet is composed in Blender without labels.
"""
import fnmatch, glob, json, math, os, re, subprocess, sys, tempfile, time

try:
    import bpy
    from mathutils import Matrix, Vector
    import numpy as np
except ImportError:
    bpy = None

HELPERS_RE = r'^(STAGE|REVIEW|CMP_|LOD_|EXPORT_|BAKE|HELPER|GUIDE|WIDGET|_)'
# lodcmp limits (version against original, same camera, day): see the LODCMP section of the docstring for why
LODCMP_MAX_DE, LODCMP_MAX_LUM, LODCMP_MAX_HOT, LODCMP_MAX_CELL = 10.0, 0.08, 1.0, 25.0
LODCMP_MAX_ALBEDO, LODCMP_MAX_GLOSS, LODCMP_BLOB_SHARE = 0.10, 0.25, 0.01
VIEWS = {   # azimuth from the front axis (counter-clockwise seen from above), elevation, lens mm
    'front34': (35, 20), 'rear34': (215, 20), 'side': (90, 4), 'top': (-90, 88), 'top34': (300, 50),
    'under34': (25, -35), 'front': (0, 6), 'rear': (180, 6), 'side2': (270, 4), 'nose': (25, 8),
}
FRONT_AZ = {'+x': 0, '+y': 90, '-x': 180, '-y': 270}
T0 = time.time()


def log(*a):
    print('RT', *a, flush=True)


def srgb2lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hexlin(h):
    h = h.lstrip('#')
    return tuple(srgb2lin(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4))


def kelvin_lin(k):
    """Perceived (eye-adapted) warm white for a colour temperature: the Tanner Helland fit used directly as linear RGB.
    The raw unadapted blackbody (Blender's Light.temperature) renders 2700 K as plain orange (linear 1 : 0.42 : 0.10)."""
    t = k / 100.0
    r = 255 if t <= 66 else 329.698727446 * (t - 60) ** -0.1332047592
    g = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * (t - 60) ** -0.0755148492
    b = 255 if t >= 66 else (0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307)
    c = [min(255, max(0, v)) / 255 for v in (r, g, b)]
    m = max(c)
    return tuple(v / m for v in c)


# ----------------------------------------------------------------------------------------------- composing (no bpy)
def compose(spec):
    """spec: {out, title, rows: [[{path, label, scale?}...]...], quality}. Pillow, system python."""
    from PIL import Image, ImageDraw, ImageFont

    def font(sz):
        for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/TTF/DejaVuSans.ttf'):
            if os.path.exists(p):
                return ImageFont.truetype(p, sz)
        try:
            return ImageFont.load_default(size=sz)
        except TypeError:
            return ImageFont.load_default()
    rows = []
    for row in spec['rows']:
        ims = []
        for t in row:
            if not t.get('path'):   # a text-only tile (legend)
                im = Image.new('RGB', tuple(t['size']), (40, 40, 44))
                ims.append((im, t.get('label', '')))
                continue
            im = Image.open(t['path'])
            if im.mode == 'RGBA':
                bg = Image.new('RGB', im.size, (62, 64, 68)); bg.paste(im, mask=im.getchannel('A')); im = bg
            im = im.convert('RGB')
            k = t.get('scale') or 1
            if k != 1:
                im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))),
                               Image.NEAREST if k > 1 else Image.LANCZOS)
            ims.append((im, t.get('label', '')))
        rows.append(ims)
    gap = 4
    W = max(sum(im.width for im, _ in r) + gap * (len(r) - 1) for r in rows)
    hdr = spec.get('header') or []
    th = (40 if spec.get('title') else 0) + 26 * len(hdr) + (8 if hdr else 0)
    H = th + sum(max(im.height for im, _ in r) for r in rows) + gap * (len(rows) - 1)
    S = Image.new('RGB', (W, H), (22, 22, 24))
    D = ImageDraw.Draw(S, 'RGBA')
    if spec.get('title'):
        D.text((10, 8), spec['title'], fill=(235, 235, 235), font=font(22))
    for i, line in enumerate(hdr):   # check results: faults red, the rest grey
        bad = 'FAULT' in line or line.startswith('STRICT')
        D.text((10, 40 + 26 * i), line[:400], fill=(255, 110, 100) if bad else (190, 200, 190), font=font(17))
    y = th
    for r in rows:
        x = 0
        for im, lab in r:
            S.paste(im, (x, y))
            if lab:
                f = font(max(14, min(26, im.width // 40)))
                bb = D.textbbox((0, 0), lab, font=f)
                D.rectangle((x, y, x + bb[2] + 16, y + bb[3] + 12), fill=(0, 0, 0, 150))
                D.text((x + 8, y + 5), lab, fill=(255, 226, 90), font=f)
            x += im.width + gap
        y += max(im.height for im, _ in r) + gap
    os.makedirs(os.path.dirname(os.path.abspath(spec['out'])), exist_ok=True)
    S.save(spec['out'], quality=spec.get('quality', 90))
    print('RT_SHEET', spec['out'], S.size, flush=True)


# ----------------------------------------------------------------------------------------------------------- args
def switch_family(family=None):
    """scripts/switch.json, the one place for game-version switch distances (see its 'about')."""
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'switch.json')) as f:
        d = json.load(f)
    fam = family or d.get('default_family')
    sw = dict(d['families'][fam], family=fam)
    h = sw['hysteresis']
    sw['appears'] = [sw['near_m'], max(sw['near_m'], sw['near_mid'][0] - h), max(sw['near_m'], sw['mid_far'][0] - h)]
    return sw


def join_front(argv):
    """['--front', '-y'] -> ['--front=-y']: argparse reads a separate '-y' as an option ("expected one argument")."""
    out, i = [], 0
    while i < len(argv):
        if argv[i] == '--front' and i + 1 < len(argv) and argv[i + 1] in FRONT_AZ:
            out.append('--front=' + argv[i + 1]); i += 2
        else:
            out.append(argv[i]); i += 1
    return out


def parse(argv):
    import argparse
    argv = join_front(list(argv))
    p = argparse.ArgumentParser(prog='render.py', add_help=False)
    p.add_argument('mode', choices=['thumb', 'sheet', 'round', 'versions', 'beforeafter', 'lodcmp', 'inspect'])
    p.add_argument('input', nargs='?')
    p.add_argument('--out'); p.add_argument('--states'); p.add_argument('--size', type=int)
    p.add_argument('--samples', type=int, default=32); p.add_argument('--views'); p.add_argument('--interior', type=int, default=2)
    p.add_argument('--n', type=int); p.add_argument('--front', default='+x', choices=list(FRONT_AZ))
    p.add_argument('--collection', action='append'); p.add_argument('--hide', default='')
    p.add_argument('--focus'); p.add_argument('--region'); p.add_argument('--night-prop', default=''); p.add_argument('--wet-prop', default='')
    p.add_argument('--labels')
    p.add_argument('--helpers', default=HELPERS_RE); p.add_argument('--keep-file-lights', action='store_true')
    p.add_argument('--no-mount-lights', action='store_true'); p.add_argument('--no-ground', action='store_true')
    p.add_argument('--az', type=float); p.add_argument('--el', type=float)
    p.add_argument('--files'); p.add_argument('--dist'); p.add_argument('--screen', default='1920x1080')
    p.add_argument('--fov', type=float, default=40.0); p.add_argument('--before'); p.add_argument('--after')
    p.add_argument('--device', default='auto', choices=['auto', 'gpu', 'cpu']); p.add_argument('--threads', type=int, default=8)
    p.add_argument('--title'); p.add_argument('--no-tiles', action='store_true')
    p.add_argument('--strict', dest='strict', action='store_true', default=True)
    p.add_argument('--no-strict', dest='strict', action='store_false'); p.add_argument('--no-integrity', action='store_true'); p.add_argument('--no-look', action='store_true')
    p.add_argument('--original'); p.add_argument('--versions')
    p.add_argument('--max-de', type=float, default=LODCMP_MAX_DE); p.add_argument('--max-lum', type=float, default=LODCMP_MAX_LUM)
    p.add_argument('--max-hot', type=float, default=LODCMP_MAX_HOT); p.add_argument('--max-cell', type=float, default=LODCMP_MAX_CELL)
    p.add_argument('--max-albedo', type=float, default=LODCMP_MAX_ALBEDO); p.add_argument('--blob-share', type=float, default=LODCMP_BLOB_SHARE)
    p.add_argument('--max-gloss', type=float, default=LODCMP_MAX_GLOSS)
    p.add_argument('--thin-fail', action='store_true', help='lodcmp: the thin-feature test (scripts/_thin.py) fails the version; default: advisory')
    p.add_argument('--no-thin', action='store_true')
    p.add_argument('--at-switch', action='store_true'); p.add_argument('--switch')
    p.add_argument('--hyst', type=float); p.add_argument('--near-dist', type=float)
    p.add_argument('--family'); p.add_argument('--state-views')
    # inspect
    p.add_argument('--part'); p.add_argument('--relations', action='store_true'); p.add_argument('--parts')
    p.add_argument('--from', dest='from_'); p.add_argument('--at'); p.add_argument('--mmpx', type=float, default=1.0)
    p.add_argument('--xray', action='store_true'); p.add_argument('--isolate', action='store_true')
    p.add_argument('--state', default='day', choices=['day', 'dusk', 'night']); p.add_argument('--round', action='store_true')
    p.add_argument('--since'); p.add_argument('--max-places', type=int, default=30)
    p.add_argument('--joint-tol', type=float, default=0.012); p.add_argument('--parts-json')
    a = p.parse_args(argv)
    if a.mode == 'inspect' and not (a.input and (a.part or a.relations or a.from_ or a.at or a.round)):
        p.error('inspect needs a file and --part, --relations, --from, --at or --round')
    # switch distances: ONE place, scripts/switch.json (--family; explicit --switch/--hyst/--near-dist still win)
    sw = switch_family(a.family)
    a.switch = a.switch or '%g,%g' % (sw['near_mid'][0], sw['mid_far'][0])
    a.hyst = sw['hysteresis'] if a.hyst is None else a.hyst
    a.near_dist = sw['near_m'] if a.near_dist is None else a.near_dist
    a.switch_family = sw
    if a.mode in ('thumb', 'sheet', 'round') and not a.input:
        p.error(a.mode + ' needs an input file')
    if a.mode == 'versions' and not a.files:
        p.error('versions needs --files a,b,c')
    if a.mode == 'beforeafter' and not (a.before and a.after):
        p.error('beforeafter needs --before and --after')
    if a.mode == 'lodcmp' and not (a.original and a.versions):
        p.error('lodcmp needs --original X and --versions a,b,c')
    return a


# ------------------------------------------------------------------------------------------------------- loading
def refuse_save(*_):
    raise RuntimeError('render.py never saves: the input file must stay untouched')


def new_coll(name):
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c


def hidden_by(name, A):
    if A.helpers and re.search(A.helpers, name, re.I):
        return True
    return any(fnmatch.fnmatch(name, g) for g in A.hide_globs)


def load_blend(path, A, group):
    """Link the file's render-visible content into `group` (local collection). Linked data keeps its libraries, so
    nested component libraries resolve relative to their own files. Nothing is written back."""
    with bpy.data.libraries.load(path, link=True) as (src, dst):
        dst.scenes = list(src.scenes)
    scenes = [s for s in dst.scenes if s]
    lib = scenes[0].library if scenes else None
    best, objs = None, []
    for sc in scenes:   # the scene with the most visible renderable objects
        cand = []

        def walk(lc, inside):
            c = lc.collection
            if lc.exclude or c.hide_render:
                return
            if c != sc.collection and hidden_by(c.name, A):
                log('hide collection', c.name)
                return
            ok = inside or not A.collection or c.name in A.collection
            if ok:
                for o in c.objects:
                    if o.hide_render or hidden_by(o.name, A):
                        continue
                    if o.type == 'CAMERA' or (o.type == 'LIGHT' and not A.keep_file_lights):
                        continue
                    cand.append(o)
            for ch in lc.children:
                walk(ch, ok)
        walk(sc.view_layers[0].layer_collection, not A.collection)
        n = sum(1 for o in cand if o.type != 'EMPTY' or o.instance_collection)
        if best is None or n > best[0]:
            best, objs = (n, sc), cand
    seen = set()
    for o in objs:
        if o.name_full not in seen:
            seen.add(o.name_full)
            group.objects.link(o)
    if not best or best[0] == 0:
        # a library/component file: no scene content, collections only (e.g. C.<component>)
        with bpy.data.libraries.load(path, link=True) as (src, dst):
            dst.collections = list(src.collections)
        cols = [c for c in dst.collections if c]
        child = {ch.name_full for c in cols for ch in c.children}
        roots = [c for c in cols if c.name_full not in child and not hidden_by(c.name, A)]
        stem = os.path.splitext(os.path.basename(path))[0]
        pick = [c for c in roots if c.name in ('C.' + stem, stem)] or roots
        if A.collection:
            pick = [c for c in cols if c.name in A.collection]
        for c in pick:
            e = bpy.data.objects.new('inst_' + c.name, None)
            e.instance_type = 'COLLECTION'
            e.instance_collection = c
            group.objects.link(e)
        log('library file: instanced collections', [c.name for c in pick])
    for l in bpy.data.libraries:
        if getattr(l, 'is_missing', False):
            log('WARNING missing library', l.filepath)
    log('loaded', path, len(group.objects), 'objects,', len(bpy.data.libraries), 'libraries')


def load_glb(path, A, group):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    for o in set(bpy.data.objects) - before:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        group.objects.link(o)
        if (o.type == 'LIGHT' and not A.keep_file_lights) or o.type == 'CAMERA' or hidden_by(o.name, A):
            o.hide_render = True
            o.hide_viewport = True
    log('imported', path, len(group.objects), 'objects')


def load(path, A, name):
    """One input = one collection; 'a.glb+b.glb' loads several files into the same one (e.g. car + bogies)."""
    group = new_coll(name)
    for p in path.split('+'):
        if p.lower().endswith(('.glb', '.gltf')):
            load_glb(p, A, group)
        else:
            load_blend(p, A, group)
    return group


def localize():
    """Make linked data local in memory (needed only to edit materials for the wet pass). Never saved."""
    for _ in range(4):
        n = 0
        for idc in (bpy.data.collections, bpy.data.objects, bpy.data.meshes, bpy.data.curves,
                    bpy.data.materials):
            for i in list(idc):
                if i.library:
                    try:
                        i.make_local(); n += 1
                    except Exception:
                        pass
        if not n:
            break


def show_groups(groups, on):
    for g in groups:
        g.hide_render = g not in on
        g.hide_viewport = g not in on
    bpy.context.view_layer.update()


# ------------------------------------------------------------------------------------------------------ geometry
GEOM = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'CURVES', 'POINTCLOUD', 'VOLUME'}


def instances():
    dg = bpy.context.evaluated_depsgraph_get()
    for inst in dg.object_instances:
        yield inst.object, inst.matrix_world.copy()


def bounds_points():
    pts = []
    for ob, M in instances():
        if ob.type in GEOM and ob.name not in ('RT_ground',) and not ob.name.startswith('RT_'):
            m = np.array(M)
            bb = np.array([list(v) for v in ob.bound_box] + [[0, 0, 0]])[:8]
            pts.append(bb @ m[:3, :3].T + m[:3, 3])
    if not pts:
        raise SystemExit('RT ERROR: nothing renderable found (all hidden? use --collection / --helpers "")')
    P = np.concatenate(pts)
    return P


def focus_points(A, P):
    """The points the camera frames. Default: the whole asset (P). --focus x,y,z,radius: a cube of that half-size
    around the point (world metres). --region GLOBS: the bounds of the objects whose names match (comma separated;
    collection instances by the instancing object's name). A 3.7 m lamp post on a 1280 px tile is 2.9 mm a pixel and a
    tenth of the frame: its head, door and base cannot be judged without this. Everything else stays in the picture."""
    if getattr(A, 'focus', None):
        try:
            x, y, z, r = (float(v) for v in A.focus.split(','))
        except ValueError:
            raise SystemExit('RT ERROR: --focus wants x,y,z,radius in metres (e.g. --focus=0,-0.35,3.6,0.45)')
        c = np.array([x, y, z])
        return c + r * np.array([[i, j, k] for i in (-1, 1) for j in (-1, 1) for k in (-1, 1)], float)
    if getattr(A, 'region', None):
        globs = [g for g in A.region.split(',') if g]; pts = []
        for ob, M in instances():
            if ob.type in GEOM and not ob.name.startswith('RT_') and any(fnmatch.fnmatch(ob.name, g) for g in globs):
                m = np.array(M); bb = np.array([list(v) for v in ob.bound_box])
                pts.append(bb @ m[:3, :3].T + m[:3, 3])
        if not pts:
            raise SystemExit('RT ERROR: --region %s matches no visible object' % A.region)
        Q = np.concatenate(pts); log('region %s: %d objects' % (A.region, len(pts)), Q.min(0).round(3).tolist(), Q.max(0).round(3).tolist())
        return Q
    return P


def fit_camera(cam, P, az, el, aspect, fill=0.9, lens=50.0):
    """Exact framing: camera along (az, el) around the points' box centre, every point inside fill*frame."""
    d = Vector((math.cos(math.radians(el)) * math.cos(math.radians(az)),
                math.cos(math.radians(el)) * math.sin(math.radians(az)), math.sin(math.radians(el))))
    rot = (-d).to_track_quat('-Z', 'Y')
    cam.rotation_euler = rot.to_euler()
    cam.data.type = 'PERSP'; cam.data.sensor_fit = 'AUTO'; cam.data.sensor_width = 36; cam.data.lens = lens
    R = np.array(rot.to_matrix())
    c = (P.min(0) + P.max(0)) / 2
    q = (P - c) @ R
    tx = math.tan(cam.data.angle / 2) * fill if aspect >= 1 else math.tan(cam.data.angle / 2) * fill * aspect
    ty = tx / aspect if aspect >= 1 else math.tan(cam.data.angle / 2) * fill
    Ax, Bx = (q[:, 0] + tx * q[:, 2]).max(), (q[:, 0] - tx * q[:, 2]).min()
    Ay, By = (q[:, 1] + ty * q[:, 2]).max(), (q[:, 1] - ty * q[:, 2]).min()
    D = max((Ax - Bx) / (2 * tx), (Ay - By) / (2 * ty), 0.05)
    loc = c + R @ np.array([(Ax + Bx) / 2, (Ay + By) / 2, D])
    cam.location = Vector(loc.tolist())
    near = float((D - q[:, 2]).min())
    cam.data.clip_start = max(0.01, min(0.5, near * 0.5))
    cam.data.clip_end = max(5000.0, D * 20)
    return Vector(c.tolist()), D


def ray(scene, o, d):
    dg = bpy.context.evaluated_depsgraph_get()
    hit, loc, *_ = scene.ray_cast(dg, Vector(o), Vector(d))
    return loc if hit else None


# ------------------------------------------------------------------------------------------------------- shading
def sock(node, name, kind, out=False):
    for s in (node.outputs if out else node.inputs):
        if s.name == name and s.type == kind:
            return s
    raise KeyError(name)


def mix_node(nt, blend='MIX'):
    m = nt.nodes.new('ShaderNodeMix')
    m.data_type = 'RGBA'; m.blend_type = blend; m.clamp_result = True
    return m, sock(m, 'Factor', 'VALUE'), sock(m, 'A', 'RGBA'), sock(m, 'B', 'RGBA'), sock(m, 'Result', 'RGBA', True)


def math_node(nt, op, b=None, clamp=False):
    m = nt.nodes.new('ShaderNodeMath'); m.operation = op; m.use_clamp = clamp
    if b is not None:
        m.inputs[1].default_value = b
    return m


def maprange(nt, src, a, b, c=0.0, d=1.0):
    m = nt.nodes.new('ShaderNodeMapRange'); m.clamp = True
    m.inputs['From Min'].default_value = a; m.inputs['From Max'].default_value = b
    m.inputs['To Min'].default_value = c; m.inputs['To Max'].default_value = d
    nt.links.new(src, m.inputs['Value'])
    return m.outputs['Result']


def world_new(name):
    w = bpy.data.worlds.new(name)
    try:
        w.use_nodes = True
    except Exception:
        pass
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    bg = nt.nodes.new('ShaderNodeBackground'); out = nt.nodes.new('ShaderNodeOutputWorld')
    nt.links.new(bg.outputs[0], out.inputs[0])
    return w, nt, bg


def world_gradient(name, zenith, horizon, ground, away=None, sundir=None, glow=None):
    """Sky by direction: horizon->zenith, below-horizon ground colour; optional horizon colour that turns from
    `away` (opposite the sun) to `horizon` (toward it) and a warm glow lobe around the sun."""
    w, nt, bg = world_new(name)
    tc = nt.nodes.new('ShaderNodeTexCoord'); dirv = tc.outputs['Generated']
    sep = nt.nodes.new('ShaderNodeSeparateXYZ'); nt.links.new(dirv, sep.inputs[0])
    hcol = None
    if sundir is not None:
        dot = nt.nodes.new('ShaderNodeVectorMath'); dot.operation = 'DOT_PRODUCT'
        nt.links.new(dirv, dot.inputs[0]); dot.inputs[1].default_value = tuple(sundir)
        dout = sock(dot, 'Value', 'VALUE', True)
    if away is not None and sundir is not None:
        f = math_node(nt, 'POWER', 1.6); nt.links.new(maprange(nt, dout, -1, 1), f.inputs[0])
        m, fac, a, b, res = mix_node(nt)
        nt.links.new(f.outputs[0], fac); a.default_value = (*away, 1); b.default_value = (*horizon, 1)
        hcol = res
    t = math_node(nt, 'POWER', 0.65); nt.links.new(maprange(nt, sep.outputs['Z'], 0.0, 0.7), t.inputs[0])
    m, fac, a, b, sky = mix_node(nt)
    nt.links.new(t.outputs[0], fac)
    if hcol is not None:
        nt.links.new(hcol, a)
    else:
        a.default_value = (*horizon, 1)
    b.default_value = (*zenith, 1)
    m2, fac2, a2, b2, col = mix_node(nt)
    nt.links.new(maprange(nt, sep.outputs['Z'], 0.0, -0.12), fac2); nt.links.new(sky, a2); b2.default_value = (*ground, 1)
    if glow is not None and sundir is not None:
        gcol, gk, gs = glow
        p = math_node(nt, 'MAXIMUM', 0.0); nt.links.new(dout, p.inputs[0])
        q = math_node(nt, 'POWER', gk); nt.links.new(p.outputs[0], q.inputs[0])
        r = math_node(nt, 'MULTIPLY', gs); nt.links.new(q.outputs[0], r.inputs[0])
        m3, fac3, a3, b3, col3 = mix_node(nt, 'ADD'); m3.clamp_result = False
        nt.links.new(r.outputs[0], fac3); nt.links.new(col, a3); b3.default_value = (*gcol, 1)
        col = col3
    nt.links.new(col, bg.inputs['Color'])
    return w, bg


def world_sky(name, sun_el, sun_az):
    """Blender's Sky Texture (types probed; MULTIPLE_SCATTERING preferred), sun disc off (the lamp is the sun)."""
    w, nt, bg = world_new(name)
    sky = nt.nodes.new('ShaderNodeTexSky')
    types = [i.identifier for i in sky.bl_rna.properties['sky_type'].enum_items]
    for t in ('MULTIPLE_SCATTERING', 'NISHITA', 'SINGLE_SCATTERING', 'HOSEK_WILKIE', 'PREETHAM'):
        if t in types:
            sky.sky_type = t
            break
    else:
        return None, None, None
    for k, v in (('sun_disc', False), ('sun_elevation', math.radians(sun_el)),
                 ('sun_rotation', math.radians((90.0 - sun_az) % 360)), ('altitude', 0.0),
                 ('air_density', 1.0), ('aerosol_density', 1.0), ('ozone_density', 1.0), ('turbidity', 2.5)):
        if hasattr(sky, k):
            try:
                setattr(sky, k, v)
            except Exception:
                pass
    if hasattr(sky, 'sun_direction') and sky.sky_type in ('HOSEK_WILKIE', 'PREETHAM'):
        sky.sun_direction = sun_vec(sun_el, sun_az)
    nt.links.new(sky.outputs['Color'], bg.inputs['Color'])
    return w, bg, sky.sky_type


# Blender 5.2 Sky Texture: sun_rotation 0 puts the sun toward +Y, 90 deg toward +X (probed), so rotation = 90 - azimuth.


def sun_vec(el, az):
    return Vector((math.cos(math.radians(el)) * math.cos(math.radians(az)),
                   math.cos(math.radians(el)) * math.sin(math.radians(az)), math.sin(math.radians(el))))


def sky_irradiance(world):
    """Effective radiance E/pi that the world gives a horizontal, upward surface (tiny equirect render, CPU)."""
    sc = bpy.data.scenes.new('RT_calib')
    sc.render.engine = 'CYCLES'; sc.cycles.device = 'CPU'; sc.cycles.samples = 4; sc.cycles.use_denoising = False
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 96, 48, 100
    sc.world = world
    cd = bpy.data.cameras.new('RT_calib'); cd.type = 'PANO'
    try:
        cd.panorama_type = 'EQUIRECTANGULAR'
    except Exception:
        cd.cycles.panorama_type = 'EQUIRECTANGULAR'
    co = bpy.data.objects.new('RT_calib', cd); sc.collection.objects.link(co); sc.camera = co
    co.rotation_euler = (math.pi / 2, 0, 0)
    sc.render.image_settings.file_format = 'OPEN_EXR'; sc.render.image_settings.color_depth = '32'
    p = os.path.join(TMP, 'calib-%s.exr' % world.name)
    sc.render.filepath = p
    bpy.ops.render.render(write_still=True, scene=sc.name)
    img = bpy.data.images.load(p)
    a = np.array(img.pixels[:]).reshape(img.size[1], img.size[0], 4)
    bpy.data.images.remove(img); bpy.data.objects.remove(co); bpy.data.cameras.remove(cd); bpy.data.scenes.remove(sc)
    H = a.shape[0]
    lum = a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722
    e = np.radians(-90 + (np.arange(H) + 0.5) * 180 / H)   # rows bottom->top
    wgt = np.clip(np.sin(e), 0, None) * np.cos(e)
    E = (lum.mean(1) * wgt).sum() * (math.pi / H) * 2 * math.pi
    return E / math.pi


STATES = {
    # target: effective sky radiance on an upward surface (game hemisphere/pi + environment fill)
    'day':   dict(sun=2.7, sun_col='#fff7e7', sun_el=45, sun_daz=35, sun_angle=2.5, target=0.42, lights=0.0),
    'dusk':  dict(sun=1.7, sun_col='#ffb26b', sun_el=4, sun_daz=75, sun_angle=1.2, target=0.16, lights=0.4,
                  zenith='#676b9d', horizon='#f0a878', away='#9a8db0', ground='#2b2a33', glow=('#ffb26b', 6, 1.6)),
    'dawn':  dict(sun=1.5, sun_col='#ffc9a0', sun_el=6, sun_daz=-75, sun_angle=1.2, target=0.18, lights=0.3,
                  zenith='#7487b8', horizon='#f3c3a6', away='#a7a6c4', ground='#2f2e36', glow=('#ffc9a0', 6, 1.5)),
    'night': dict(sun=0.2, sun_col='#b9d0ff', sun_el=35, sun_daz=-70, sun_angle=1.0, target=0.06, lights=1.0,
                  zenith='#03091c', horizon='#13243f', ground='#05070c'),
    'rain':  dict(sun=0.0, target=0.50, lights=0.0, zenith='#b8c0c8', horizon='#8f989f', ground='#3a3d40', wet=True),
}


class Stage:
    """Our lighting + ground + camera; asset content lives in its own collections."""

    def __init__(self, A, sc):
        self.A, self.sc = A, sc
        self.col = new_coll('RT_stage')
        cd = bpy.data.cameras.new('RT_cam')
        self.cam = bpy.data.objects.new('RT_cam', cd); self.col.objects.link(self.cam); sc.camera = self.cam
        self.sun = self._light('RT_sun', 'SUN')
        self.bounce = self._light('RT_bounce', 'SUN'); self.bounce.data.energy = 0
        self.bounce.rotation_euler = (math.pi, 0, 0)   # points up
        self.worlds = {}
        self.ground = None
        self.asset_lights = []

    def _light(self, name, kind):
        ld = bpy.data.lights.new(name, kind)
        o = bpy.data.objects.new(name, ld); self.col.objects.link(o)
        return o

    def make_ground(self, zmin, radius):
        if self.A.no_ground:
            return
        bpy.ops.mesh.primitive_plane_add(size=20000.0, location=(0, 0, zmin - 0.003))   # edge beyond the horizon
        g = bpy.context.object; g.name = 'RT_ground'
        for c in list(g.users_collection):
            c.objects.unlink(g)
        self.col.objects.link(g)
        m = bpy.data.materials.new('RT_concrete'); nt = m.node_tree
        b = nt.nodes['Principled BSDF']
        noise = nt.nodes.new('ShaderNodeTexNoise'); noise.inputs['Scale'].default_value = 0.6
        noise.inputs['Detail'].default_value = 6
        mx, fac, a, bb, res = mix_node(nt)
        fac.default_value = 1.0
        ramp = maprange(nt, noise.outputs['Fac'], 0.3, 0.7, 0.88, 1.08)
        mm, f2, a2, b2, r2 = mix_node(nt, 'MULTIPLY'); f2.default_value = 1.0
        a2.default_value = (*hexlin('#8a8885'), 1)
        comb = nt.nodes.new('ShaderNodeCombineColor')
        for i in range(3):
            nt.links.new(ramp, comb.inputs[i])
        nt.links.new(comb.outputs[0], b2); nt.links.new(r2, b.inputs['Base Color'])
        b.inputs['Roughness'].default_value = 0.85
        g.data.materials.append(m)
        self.ground, self.ground_bsdf = g, b

    def set_ground_wet(self, wet):
        if self.ground:
            self.ground_bsdf.inputs['Roughness'].default_value = 0.18 if wet else 0.85
            nt = self.ground_bsdf.id_data
            for n in nt.nodes:
                if n.bl_idname == 'ShaderNodeMix' and n.blend_type == 'MULTIPLY':
                    sock(n, 'A', 'RGBA').default_value = (*hexlin('#5d5c5a' if wet else '#8a8885'), 1)

    def world_for(self, state, sun_az):
        S = STATES[state]
        key = (state, round(sun_az) if state in ('day', 'dusk', 'dawn') else 0)
        if key in self.worlds:
            return self.worlds[key]
        w = bg = None
        if state == 'day' and self.A.sky != 'gradient':
            w, bg, kind = world_sky('RT_day_%d' % key[1], S['sun_el'], sun_az)
            if w is None:
                log('no sky texture type; gradient fallback')
        if w is None:
            if state == 'day':
                w, bg = world_gradient('RT_day', hexlin('#4b91c4'), hexlin('#a8d7ee'), hexlin('#6c6656'))
            else:
                sd = sun_vec(S['sun_el'], sun_az) if 'away' in S else None
                w, bg = world_gradient('RT_' + state, hexlin(S['zenith']), hexlin(S['horizon']), hexlin(S['ground']),
                                       away=hexlin(S['away']) if 'away' in S else None, sundir=sd,
                                       glow=(hexlin(S['glow'][0]), S['glow'][1], S['glow'][2]) if 'glow' in S else None)
        bg.inputs['Strength'].default_value = 1.0
        e = sky_irradiance(w)
        bg.inputs['Strength'].default_value = S['target'] / max(e, 1e-6)
        log('world', w.name, 'raw %.4f -> strength %.4f' % (e, bg.inputs['Strength'].default_value))
        self.worlds[key] = w
        return w

    def light_for(self, state, cam_az, under=False, lights=None):
        S = STATES[state]
        sun_az = cam_az + S.get('sun_daz', 0)
        self.sc.world = self.world_for(state, sun_az)
        if S['sun'] > 0:
            self.sun.hide_render = False
            self.sun.data.energy = S['sun']; self.sun.data.color = hexlin(S['sun_col'])
            self.sun.data.angle = math.radians(S['sun_angle'])
            self.sun.rotation_euler = (-sun_vec(S['sun_el'], sun_az)).to_track_quat('-Z', 'Y').to_euler()
        else:
            self.sun.hide_render = True
        self.bounce.data.energy = (1.6 * max(S['target'] / 0.42, 0.05)) if under else 0.0
        self.bounce.data.color = hexlin('#d8d2c4')
        k = S['lights'] if lights is None else lights
        for o, w, g in self.asset_lights:
            o.hide_render = k <= 0 or (g is not None and g.hide_render)
            o.data.energy = w * k
        # the shared shader kinds read the view-layer attributes idle_night / idle_wet (glass.window glow,
        # lamp.emissive night): the same share as the asset lights, so library glow is on at night (1) and dusk (0.4)
        # --night-prop / --wet-prop: an asset's OWN state properties (the lamp's lp_night) get the same values
        own_n = [x for x in (getattr(self.A, 'night_prop', '') or '').split(',') if x]
        own_w = [x for x in (getattr(self.A, 'wet_prop', '') or '').split(',') if x]
        for holder in [self.sc] + list(self.sc.view_layers):
            holder['idle_night'] = float(k); holder['idle_wet'] = 1.0 if S.get('wet') else 0.0
            for x in own_n: holder[x] = float(k)
            for x in own_w: holder[x] = 1.0 if S.get('wet') else 0.0
        self.sc.update_tag(); bpy.context.view_layer.update()
        self.set_ground_wet(S.get('wet', False))
        if self.ground:
            self.ground.hide_render = under


# ---------------------------------------------------------------------------------------------------- asset lights
def area_size(ld, size, size_y=None):
    """AREA light size from the empty's properties: size (m) square, or size + size_y / size [x, y] = a rectangle
    (a 0.12 x 0.47 m optic is ONE light, x along the empty's X, y along its Y)."""
    if hasattr(size, '__len__') and not isinstance(size, str) and len(size) >= 2:
        size, size_y = size[0], size[1]
    ld.size = float(size)
    if size_y is not None and float(size_y) > 0 and abs(float(size_y) - float(size)) > 1e-9:
        ld.shape = 'RECTANGLE'; ld.size_y = float(size_y)
    return ld


KIND_DEFAULTS = [   # (prefixes, type, watts, cone deg, colour)
    (('head',), 'SPOT', 1000, 45, None), (('tail', 'red', 'stop', 'brake'), 'POINT', 8, 0, (1.0, 0.04, 0.02)),
    (('marker',), 'POINT', 8, 0, None), (('street', 'post', 'pole', 'flood'), 'SPOT', 400, 110, None),
    (('sign', 'screen', 'display'), 'POINT', 10, 0, None),
]


def asset_json_lights(path):
    d = os.path.dirname(os.path.abspath(path))
    for p in (os.path.join(d, 'asset.json'), os.path.join(os.path.dirname(d), 'asset.json')):
        try:
            L = json.load(open(p)).get('lights')
        except Exception:
            continue
        if isinstance(L, dict):
            L = [dict(v, name=k) for k, v in L.items()]
        if L:
            log('asset.json lights from', p, len(L))
            return {x.get('name'): x for x in L if isinstance(x, dict)}
    return {}


def make_asset_lights(stage, A, inputs, groups):
    """Per input group (its lights show only when its group renders)."""
    for p, g in zip(inputs, groups):
        show_groups(groups, [g])
        make_group_lights(stage, A, asset_json_lights(p.split('+')[0]), g)
    show_groups(groups, groups)
    log('asset lights:', len(stage.asset_lights))


def make_group_lights(stage, A, js, group):
    found, mounts = [], []
    for ob, M in instances():
        if ob.type != 'EMPTY':
            continue
        nm = ob.name
        if re.match(r'^light\.[^.]+', nm, re.I):
            found.append((ob, M))
        elif re.match(r'^mount\.light\.', nm, re.I):
            mounts.append((ob, M))
    use_mounts = not found and mounts and not A.no_mount_lights
    if use_mounts:
        log('no light.* empties; %d mount.light.* empties become 30 W 2700 K cabin lights' % len(mounts))
    src = found if found else (mounts if use_mounts else [])
    fx = FRONT_VEC[A.front]
    for ob, M in src:
        nm = ob.name
        base = re.sub(r'\.\d{3}$', '', nm)
        kind = nm.split('.')[1].lower() if not use_mounts else 'cabin'
        P = {k.lower(): ob[k] for k in ob.keys() if not k.startswith('_')} if hasattr(ob, 'keys') else {}
        J = js.get(nm) or js.get(base) or {}
        get = lambda *ks, d=None: next((P[k] for k in ks if k in P), next((J[k] for k in ks if k in J), d))
        typ, watts, cone, col = 'POINT', 30, 0, None
        for pre, t, w, c, cl in KIND_DEFAULTS:
            if kind.startswith(pre):
                typ, watts, cone, col = t, w, c, cl
                break
        typ = str(get('type', 'light_type', d=typ)).upper()
        typ = typ if typ in ('POINT', 'SPOT', 'AREA') else 'POINT'
        w = get('watts', 'power', 'energy')
        if w is None and get('intensity') is not None:
            w = 4 * math.pi * float(get('intensity'))
        watts = float(w) if w is not None else watts
        c = get('color', 'colour')
        if isinstance(c, str) and c.startswith('#'):
            col = hexlin(c)
        elif isinstance(c, (list, tuple)) or (hasattr(c, '__len__') and len(c) >= 3):
            v = [float(x) for x in list(c)[:3]]
            v = [x / 255 for x in v] if max(v) > 1 else v
            col = tuple(srgb2lin(x) for x in v)
        k = get('kelvin', 'temperature')
        if col is None:
            col = kelvin_lin(float(k) if k else 2700)
        cone = float(get('cone', 'spot_angle', 'angle', 'spot_size', d=cone) or cone)
        cone = math.degrees(cone) if 0 < cone <= 3.2 else cone
        ld = bpy.data.lights.new('RT_' + nm, typ)
        ld.energy = watts; ld.color = col
        if typ in ('POINT', 'SPOT'):
            ld.shadow_soft_size = float(get('radius', d=0.06))
        if typ == 'SPOT':
            ld.spot_size = math.radians(cone or 45); ld.spot_blend = float(get('blend', 'spot_blend', d=0.4))
        if typ == 'AREA':
            area_size(ld, get('size', d=0.3), get('size_y'))
        lo = bpy.data.objects.new('RT_' + nm, ld); stage.col.objects.link(lo)
        loc, rot, _ = M.decompose()
        if use_mounts:   # a fixture hangs below its mount; a mount at/above the ceiling would light the roof void
            loc = loc + Vector((0, 0, -0.1))
            up = ray(bpy.context.scene, loc - Vector((0, 0, 1.5)), (0, 0, 1))
            if up is not None and up.z < loc.z + 0.1:
                loc = Vector((loc.x, loc.y, up.z - 0.15))
        lo.location = loc
        aim = rot @ Vector((0, 0, -1))
        if typ != 'POINT' and kind.startswith('head') and abs(aim.z) > 0.95:
            aim = Vector((fx[0], fx[1], -math.tan(math.radians(8)))).normalized()
        lo.rotation_euler = aim.to_track_quat('-Z', 'Y').to_euler()
        stage.asset_lights.append((lo, watts, group))


FRONT_VEC = {'+x': (1, 0), '-x': (-1, 0), '+y': (0, 1), '-y': (0, -1)}


# ----------------------------------------------------------------------------------------------------------- wet
class Wet:
    """Rain look on in-memory materials: base colour x0.75, roughness x0.4 (clamped). Undone after rain views."""

    def __init__(self):
        self.undo = []

    def apply(self):
        localize()
        n = 0
        for m in bpy.data.materials:
            if m.library or not m.node_tree or m.name.startswith('RT_'):
                continue
            nt = m.node_tree
            for b in [x for x in nt.nodes if x.bl_idname == 'ShaderNodeBsdfPrincipled']:
                tr = b.inputs.get('Transmission Weight') or b.inputs.get('Transmission')
                if tr and not tr.is_linked and tr.default_value > 0.5:
                    continue
                bc, rg = b.inputs['Base Color'], b.inputs['Roughness']
                if bc.is_linked:
                    src = bc.links[0].from_socket
                    mx, fac, a, bb, res = mix_node(nt, 'MULTIPLY'); fac.default_value = 1.0
                    bb.default_value = (0.75, 0.75, 0.75, 1)
                    nt.links.new(src, a); nt.links.new(res, bc)
                    self.undo.append(('link', nt, mx, src, bc))
                else:
                    v = tuple(bc.default_value); self.undo.append(('val', bc, v))
                    bc.default_value = (v[0] * 0.75, v[1] * 0.75, v[2] * 0.75, v[3])
                if rg.is_linked:
                    src = rg.links[0].from_socket
                    mm = math_node(nt, 'MULTIPLY', 0.4); mm.use_clamp = True
                    nt.links.new(src, mm.inputs[0]); nt.links.new(mm.outputs[0], rg)
                    self.undo.append(('link', nt, mm, src, rg))
                else:
                    v = rg.default_value; self.undo.append(('val', rg, v))
                    rg.default_value = min(1.0, max(0.03, v * 0.4))
                n += 1
        left = len({s.material.name_full for ob, M in instances() if ob.type in GEOM
                    for s in ob.original.material_slots if s.material and s.material.library})
        log('wet pass on %d BSDFs%s' % (n, ', %d linked materials left dry' % left if left else ''))

    def restore(self):
        for u in reversed(self.undo):
            if u[0] == 'val':
                u[1].default_value = u[2]
            else:
                _, nt, node, src, dst = u
                nt.nodes.remove(node); nt.links.new(src, dst)
        self.undo = []


# -------------------------------------------------------------------------------------------------------- render
def setup_render(A, sc, w, h):
    sc.render.engine = 'CYCLES'
    cy = sc.cycles
    dev = 'CPU'
    if A.device != 'cpu':
        free = None
        try:
            out = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
                                          text=True, timeout=10)
            free = max(int(x) for x in out.split())
        except Exception:
            pass
        pr = bpy.context.preferences.addons['cycles'].preferences
        if free is not None and free < 2500:
            log('GPU has only %d MiB free: CPU' % free)
        else:
            for t in ('OPTIX', 'CUDA'):
                try:
                    pr.compute_device_type = t
                    pr.refresh_devices()
                except Exception:
                    continue
                gpus = [d for d in pr.devices if d.type == t]
                if gpus:
                    for d in pr.devices:
                        d.use = d.type == t
                    dev = t
                    break
        if dev == 'CPU':
            hint = ' (CUDA_VISIBLE_DEVICES is empty: on the build box run with MV_BLENDER_GPU=1)' \
                if os.environ.get('CUDA_VISIBLE_DEVICES', None) == '' else ''
            log('no usable GPU, CPU render' + hint)
            if A.device == 'gpu':
                raise SystemExit('RT ERROR: --device gpu but no GPU' + hint)
    cy.device = 'GPU' if dev != 'CPU' else 'CPU'
    sc.render.threads_mode = 'FIXED'; sc.render.threads = max(1, min(8, A.threads))
    try:
        sc.render.compositor_device = 'CPU'
    except Exception:
        pass
    sc.render.use_compositing = False; sc.render.use_sequencer = False
    cy.samples = A.samples; cy.use_adaptive_sampling = True; cy.adaptive_threshold = 0.02; cy.seed = 7
    cy.use_denoising = True
    try:
        cy.denoiser = 'OPENIMAGEDENOISE'; cy.denoising_input_passes = 'RGB_ALBEDO_NORMAL'
        cy.denoising_use_gpu = dev != 'CPU'
    except Exception:
        pass
    cy.max_bounces = 8; cy.diffuse_bounces = 3; cy.glossy_bounces = 4; cy.transmission_bounces = 8
    cy.transparent_max_bounces = 64; cy.caustics_reflective = False; cy.caustics_refractive = False
    cy.blur_glossy = 1.0; cy.sample_clamp_indirect = 10.0
    sc.render.use_persistent_data = True
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = w, h, 100
    sc.render.film_transparent = False
    vs = sc.view_settings
    try:
        vs.view_transform = 'Khronos PBR Neutral'
    except TypeError:
        vs.view_transform = 'AgX'; log('WARNING no Khronos PBR Neutral view transform; AgX')
    vs.look = 'None'; vs.exposure = 0.0; vs.gamma = 1.0
    im = sc.render.image_settings
    im.file_format = 'PNG'; im.color_mode = 'RGB'; im.color_depth = '8'; im.compression = 15
    log('device', dev, 'samples', A.samples, '%dx%d' % (w, h))
    return dev


TIMES = []
EXIT_CODE, FAIL_REASONS = 0, []


def render(sc, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sc.render.filepath = path
    t = time.time()
    bpy.ops.render.render(write_still=True)
    dt = time.time() - t
    TIMES.append(dt)
    print('RT_RENDER %.1fs %s' % (dt, path), flush=True)
    return path


def compose_out(rows, out, title, keep_tiles=True, header=None):
    spec = dict(out=out, title=title, rows=rows, header=header or [])
    sp = os.path.join(TMP, 'compose.json')
    json.dump(spec, open(sp, 'w'))
    ok = False
    for py in ('/usr/bin/python3', 'python3'):
        try:
            r = subprocess.run([py, os.path.abspath(__file__), '--compose', sp], capture_output=True, text=True, timeout=300)
            print(r.stdout.strip(), r.stderr.strip()[-800:], flush=True)
            if r.returncode == 0:
                ok = True
                break
        except Exception as e:
            log('compose via', py, 'failed', e)
    if not ok:
        compose_blender(rows, out)
    if not keep_tiles:
        for r in rows:
            for t in r:
                try:
                    os.remove(t['path'])
                except (OSError, KeyError):
                    pass


def compose_blender(rows, out):
    """Fallback without Pillow: numpy grid, no labels."""
    def arr(t):
        if not t.get('path'):
            w, h = t['size']; return np.zeros((h, w, 4), np.float32)
        i = bpy.data.images.load(t['path'])
        return np.array(i.pixels[:]).reshape(i.size[1], i.size[0], 4)[::-1]
    arrs = [[arr(t) for t in r] for r in rows]
    H = sum(max(a.shape[0] for a in r) for r in arrs); W = max(sum(a.shape[1] for a in r) for r in arrs)
    S = np.zeros((H, W, 4), np.float32); S[..., 3] = 1; y = 0
    for r in arrs:
        x = 0
        for a in r:
            S[y:y + a.shape[0], x:x + a.shape[1]] = a; x += a.shape[1]
        y += max(a.shape[0] for a in r)
    img = bpy.data.images.new('RT_sheet', W, H)
    img.pixels = S[::-1].ravel()
    img.filepath_raw = out; img.file_format = 'JPEG'; img.save()
    log('composed in Blender (no labels):', out)


# -------------------------------------------------------------------------------------------------------- views
def view_az(A, name, az=None):
    a, e = VIEWS[name]
    return (az if az is not None else a) + FRONT_AZ[A.front], e


def nose_points(A, P):
    """Box around the front end: the last ~22 % of the length (1.5-5 m)."""
    lo, hi = P.min(0), P.max(0)
    ax = 0 if A.front in ('+x', '-x') else 1
    L = hi[ax] - lo[ax]
    c = min(5.0, max(1.5, 0.22 * L))
    blo, bhi = lo.copy(), hi.copy()
    if A.front[0] == '+':
        blo[ax] = hi[ax] - c
    else:
        bhi[ax] = lo[ax] + c
    return np.array([[x, y, z] for x in (blo[0], bhi[0]) for y in (blo[1], bhi[1]) for z in (blo[2], bhi[2])])


def shoot(stage, A, P, view, state, path, aspect, lens=50.0, fill=0.9):
    az, el = view_az(A, view)
    pts = nose_points(A, P) if view == 'nose' else P
    stage.light_for(state, az, under=(el < 0))
    fit_camera(stage.cam, pts, az, el, aspect, fill=fill if view != 'nose' else 1.0, lens=lens)
    return render(stage.sc, path)


def interior_cams(stage, A, P, n):
    """Camera poses inside the asset: eye 1.6 m above the floor found by ray casts, along and across the long axis."""
    sc = stage.sc
    lo, hi = P.min(0), P.max(0)
    ax = 0 if (hi[0] - lo[0]) >= (hi[1] - lo[1]) else 1
    oth = 1 - ax
    L, Wd, c = hi[ax] - lo[ax], hi[oth] - lo[oth], (lo + hi) / 2
    hide = stage.ground.hide_viewport if stage.ground else None
    if stage.ground:
        stage.ground.hide_viewport = True
    bpy.context.view_layer.update()
    floors, ceils = [], []
    for f in (0.3, 0.45, 0.6, 0.75):
        p = c.copy(); p[ax] = lo[ax] + f * L; p[2] = lo[2] + 0.55 * (hi[2] - lo[2])
        d = ray(sc, p, (0, 0, -1)); u = ray(sc, p, (0, 0, 1))
        if d is not None and u is not None:
            floors.append(d.z); ceils.append(u.z)
    if stage.ground:
        stage.ground.hide_viewport = hide
    if not floors:
        log('interior: no floor + roof found above/below the centre line; no interior views')
        return []
    floor, ceil = float(np.median(floors)), float(np.median(ceils))
    eye = min(floor + 1.6, ceil - 0.2) if ceil - floor > 0.6 else (floor + ceil) / 2
    log('interior: floor %.2f ceiling %.2f eye %.2f' % (floor, ceil, eye))
    sgn = 1 if A.front[0] == '+' else -1
    poses = [(0.12, 0.0, 0, -4), (0.72, 0.22, 200, -6), (0.5, -0.25, 70, -3), (0.3, 0.25, -25, -5)]
    out = []
    for i in range(n):
        fpos, lat, yaw, pitch = poses[i % len(poses)]
        if sgn < 0:
            fpos, yaw = 1 - fpos, yaw + 180
        p = c.copy(); p[ax] = lo[ax] + fpos * L; p[oth] = c[oth] + lat * Wd; p[2] = eye
        base = 0 if ax == 0 else 90
        out.append((Vector(p.tolist()), base + yaw, pitch))
    return out


def shoot_interior(stage, pose, state, path):
    """Inside, the asset's own lights are on in every state (a running car keeps its saloon lit)."""
    loc, yaw, pitch = pose
    stage.light_for(state, yaw + 180, lights=1.0)
    cam = stage.cam
    cam.data.type = 'PERSP'; cam.data.lens = 16; cam.data.sensor_width = 36; cam.data.sensor_fit = 'AUTO'
    cam.data.clip_start = 0.03; cam.data.clip_end = 5000
    d = Vector((math.cos(math.radians(pitch)) * math.cos(math.radians(yaw)),
                math.cos(math.radians(pitch)) * math.sin(math.radians(yaw)), math.sin(math.radians(pitch))))
    cam.location = loc; cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    return render(stage.sc, path)


# ------------------------------------------------------------------------------------------------ geometry check
def integrity_script():
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, '..', '..', '3d-modelling', 'scripts', 'mesh_integrity.py'),
              os.path.expanduser('~/.claude/skills/3d-modelling/scripts/mesh_integrity.py')):
        if os.path.exists(p):
            return os.path.abspath(p)
    return None


def write_geometry_glb(path):
    """Geometry-only GLB of what renders (every evaluated instance, world transforms applied, Z-up -> glTF Y-up), one
    node per instance named after its object: the input for mesh_integrity.py. Linked/instanced content included."""
    cache, nodes, meshes, acc, views, blob = {}, [], [], [], [], bytearray()

    def add(arr, target, comp, typ, mm=False):
        while len(blob) % 4:
            blob.append(0)
        b = arr.tobytes()
        views.append({'buffer': 0, 'byteOffset': len(blob), 'byteLength': len(b), 'target': target})
        blob.extend(b)
        a = {'bufferView': len(views) - 1, 'componentType': comp, 'count': int(arr.shape[0]) if typ == 'VEC3' else int(arr.size), 'type': typ}
        if mm:
            a['min'] = arr.min(0).tolist(); a['max'] = arr.max(0).tolist()
        acc.append(a)
        return len(acc) - 1
    for ob, M in instances():
        if ob.type not in GEOM or ob.name.startswith('RT_'):
            continue
        key = ob.name_full
        if key not in cache:
            try:
                me = ob.to_mesh()
            except Exception:
                me = None
            if me is None:
                cache[key] = None
                continue
            me.calc_loop_triangles()
            co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get('co', co)
            tri = np.empty(len(me.loop_triangles) * 3, np.int32); me.loop_triangles.foreach_get('vertices', tri)
            ob.to_mesh_clear()
            cache[key] = (co.reshape(-1, 3), tri.reshape(-1, 3)) if len(tri) else None
        if cache[key] is None:
            continue
        co, tri = cache[key]
        m = np.array(M)
        w = co @ m[:3, :3].T + m[:3, 3]
        if np.linalg.det(m[:3, :3]) < 0:
            tri = tri[:, ::-1]
        w = np.ascontiguousarray(np.stack([w[:, 0], w[:, 2], -w[:, 1]], 1), np.float32)
        ip = add(w, 34962, 5126, 'VEC3', True)
        ii = add(np.ascontiguousarray(tri.ravel(), np.uint32), 34963, 5125, 'SCALAR')
        meshes.append({'primitives': [{'attributes': {'POSITION': ip}, 'indices': ii}]})
        nodes.append({'name': ob.name, 'mesh': len(meshes) - 1})
    while len(blob) % 4:
        blob.append(0)
    js = json.dumps({'asset': {'version': '2.0', 'generator': 'render.py geometry check'}, 'scene': 0,
                     'scenes': [{'nodes': list(range(len(nodes)))}], 'nodes': nodes, 'meshes': meshes,
                     'accessors': acc, 'bufferViews': views, 'buffers': [{'byteLength': len(blob)}]}).encode()
    js += b' ' * ((4 - len(js) % 4) % 4)
    import struct
    with open(path, 'wb') as f:
        f.write(struct.pack('<4sII', b'glTF', 2, 12 + 8 + len(js) + 8 + len(blob)))
        f.write(struct.pack('<I4s', len(js), b'JSON')); f.write(js)
        f.write(struct.pack('<I4s', len(blob), b'BIN\x00')); f.write(bytes(blob))
    return len(nodes)


def uv_faults():
    """Meshes whose material samples an image through UVs while the mesh has no UV map (three.js: speckle/one colour)."""
    bad, seen = [], set()
    for ob, M in instances():
        o = ob.original
        if o.type != 'MESH' or o.name_full in seen or o.name.startswith('RT_'):
            continue
        seen.add(o.name_full)
        if len(o.data.uv_layers):
            continue
        for sl in o.material_slots:
            m = sl.material
            if not (m and m.node_tree):
                continue
            for n in m.node_tree.nodes:
                if n.bl_idname == 'ShaderNodeTexImage' and n.image:
                    v = n.inputs['Vector']
                    src = v.links[0].from_node.bl_idname if v.is_linked else None
                    if src in (None, 'ShaderNodeUVMap') or (src == 'ShaderNodeTexCoord' and v.links[0].from_socket.name == 'UV'):
                        bad.append('%s (%s)' % (o.name, m.name))
                        break
            else:
                continue
            break
    return bad


def integrity_start(A, td):
    """Start mesh_integrity.py on the rendered geometry in the background (it runs on up to 8 CPU cores while the GPU
    renders; about half a minute on a 371k-triangle assembly)."""
    if A.no_integrity:
        return None
    mi = integrity_script()
    if not mi:
        log('WARNING mesh_integrity.py not found; geometry check skipped')
        return None
    g = os.path.join(td, 'geometry-check.glb')
    t = time.time(); n = write_geometry_glb(g)
    log('geometry check: %d parts written in %.1fs, mesh_integrity.py running in the background' % (n, time.time() - t))
    jp = os.path.join(td, 'integrity.json'); lp = os.path.join(td, 'integrity.txt')
    # --seen-to near (2026-10-14): also list faces that blink where the near version is drawn farthest (train 248 m,
    # depth step 7.3 mm with the game's 0.5 m near plane); advisory, the 2 mm FLICKER stays the strict gate
    proc = subprocess.Popen(['/usr/bin/python3' if os.path.exists('/usr/bin/python3') else 'python3', mi, g, '--from-below',
                             '--seen-to', 'near', '--family', getattr(A, 'family', None) or 'train',
                             '--json', jp], stdout=open(lp, 'w'), stderr=subprocess.STDOUT)
    return dict(proc=proc, json=jp, txt=lp, glb=g, t=time.time(), uv=uv_faults())


def integrity_finish(A, chk):
    """Wait for the check; return header lines for the sheet and register strict failures."""
    global EXIT_CODE
    if chk is None:
        return ['geometry check: skipped (--no-integrity or mesh_integrity.py missing)']
    chk['proc'].wait()
    dt = time.time() - chk['t']
    txt = open(chk['txt']).read().splitlines()
    keep = [l.strip() for l in txt if l.strip().startswith(('BODIES', 'floating', 'NON-MANIFOLD', 'WATERTIGHT', 'inside out', 'GAPS', 'FLICKER', 'AT DISTANCE', 'LOOKED INTO', 'RESULT'))]
    for l in txt:
        if l.strip().startswith(('BODIES', 'floating', 'NON-MANIFOLD', 'turned over', 'WATERTIGHT', 'inside out', 'GAPS', 'gap ', 'FLICKER', 'blinks', 'AT DISTANCE', 'LOOKED', 'RESULT')):
            print('RT_CHECK', l.strip()[:300], flush=True)
    try:
        J = json.load(open(chk['json']))
    except Exception:
        J = {}
        keep.append('FAULT: mesh_integrity.py gave no result (see %s)' % chk['txt'])
    faults = []
    nb = len(J.get('bodies', [])) if J else 0
    if nb > 1:
        faults.append('%d floating bodies' % (nb - 1))
    fl = J.get('flicker', {})
    if fl.get('largest_same_m2', 0) > 1e-4:
        faults.append('FLICKER %d coplanar pairs' % fl.get('same_facing_pairs', 0))
    if J.get('gap_count', 0):
        faults.append('GAPS %d pairs' % J['gap_count'])
    if J.get('non_manifold', {}).get('inside_out_parts', 0):
        faults.append('%d closed parts inside out' % J['non_manifold']['inside_out_parts'])
    if chk['uv']:
        faults.append('%d textured meshes without UVs: %s' % (len(chk['uv']), ', '.join(chk['uv'][:6])))
        print('RT_CHECK UV FAULT', ', '.join(chk['uv'][:20]), flush=True)
    else:
        keep.append('UV: every textured mesh has UVs')
    log('geometry check finished in %.0fs (%s)' % (dt, chk['txt']))
    keep = ['geometry check (mesh_integrity.py --from-below, %.0fs): ' % dt + (keep[0] if keep else '')] + keep[1:]
    if faults and A.strict:
        keep.append('STRICT FAIL: ' + '; '.join(faults))
        EXIT_CODE = 3; FAIL_REASONS.append('round geometry check: ' + '; '.join(faults))
    elif faults:
        keep.append('(not strict) would fail: ' + '; '.join(faults))
    return keep


# ------------------------------------------------------------------------------------------------ lodcmp metrics
def load_rgba(path):
    im = bpy.data.images.load(path)
    a = np.array(im.pixels[:], np.float32).reshape(im.size[1], im.size[0], 4)
    bpy.data.images.remove(im)
    return a


def to_lab(rgb):
    """display sRGB (0..1) -> CIE Lab (D65)."""
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]], np.float32)
    xyz = lin @ M.T / np.array([0.95047, 1.0, 1.08883], np.float32)
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1), lin


def save_rgb(arr, path):
    h, w = arr.shape[:2]
    img = bpy.data.images.new('RT_diff', w, h)
    px = np.ones((h, w, 4), np.float32); px[..., :3] = np.clip(arr, 0, 1)
    img.pixels = px.ravel()
    img.filepath_raw = path; img.file_format = 'PNG'; img.save()
    bpy.data.images.remove(img)


def load_passes(exr):
    """DiffCol / GlossCol (linear) from a multilayer EXR, bottom-up like Blender images; None when unreadable."""
    try:
        import OpenImageIO as oiio
        out, want = {}, {'DiffCol': ('Diffuse Color', 'DiffCol'), 'GlossCol': ('Glossy Color', 'GlossCol')}
        n = oiio.ImageBuf(exr).nsubimages
        for sub in range(max(1, n)):   # Blender 5.2 writes each pass as its own EXR part ("ViewLayer.Diffuse Color.R")
            buf = oiio.ImageBuf(exr, sub, 0)
            names = list(buf.spec().channelnames)
            for key, alias in want.items():
                idx = [next((i for i, nm in enumerate(names) if any(nm.endswith(a + '.' + c) for a in alias)), None) for c in 'RGB']
                if None not in idx and key not in out:
                    out[key] = np.asarray(buf.get_pixels(oiio.FLOAT))[::-1][..., idx]
        missing = [k for k in want if k not in out]
        if missing:
            raise KeyError('no %s pass' % missing)
        return out
    except Exception as e:
        log('WARNING material passes unreadable (%s): %s' % (exr, e))
        return None


def blobs(dE, both, dL, cell=16, thr=20.0):
    """Connected regions of 16 px cells (>= 50 % covered) whose mean dE > thr: local differences, largest first."""
    H, W = dE.shape; gh, gw = H // cell, W // cell
    d = dE[:gh * cell, :gw * cell].reshape(gh, cell, gw, cell); b = both[:gh * cell, :gw * cell].reshape(gh, cell, gw, cell)
    l = dL[:gh * cell, :gw * cell].reshape(gh, cell, gw, cell)
    cov = b.mean((1, 3)); n = np.maximum(b.sum((1, 3)), 1)
    md = (d * b).sum((1, 3)) / n; ml = (l * b).sum((1, 3)) / n
    hot = (cov >= 0.5) & (md > thr)
    seen = np.zeros_like(hot); out = []
    for y0 in range(gh):
        for x0 in range(gw):
            if hot[y0, x0] and not seen[y0, x0]:
                st, cells = [(y0, x0)], []
                seen[y0, x0] = True
                while st:
                    y, x = st.pop(); cells.append((y, x))
                    for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                        if 0 <= yy < gh and 0 <= xx < gw and hot[yy, xx] and not seen[yy, xx]:
                            seen[yy, xx] = True; st.append((yy, xx))
                ys, xs = [c[0] for c in cells], [c[1] for c in cells]
                out.append(dict(share=len(cells) * cell * cell / max(1, int(both.sum())),
                                dE=float(np.mean([md[c] for c in cells])), dL=float(np.mean([ml[c] for c in cells])),
                                box_px=[min(xs) * cell, H - (max(ys) + 1) * cell, (max(xs) + 1) * cell, H - min(ys) * cell]))
    out.sort(key=lambda b: -b['share'] * b['dE'])
    return out


def compare_pair(po, pv, out_png, A, pix_de=12.0, eo=None, ev=None, bcell=16):
    """Version vs original seen by the same camera (display-referred, what the viewer sees). Metrics on the pixels
    covered in BOTH (alpha > 0.5); silhouette change reported separately. Writes the masked difference picture."""
    o, v = load_rgba(po), load_rgba(pv)
    mo, mv = o[..., 3] > 0.5, v[..., 3] > 0.5
    both, xor = mo & mv, mo ^ mv
    lo, lino = to_lab(o[..., :3]); lv, linv = to_lab(v[..., :3])
    dE = np.sqrt(((lo - lv) ** 2).sum(-1))
    Y = lambda lin: lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    n = int(both.sum())
    if n < 50:
        return dict(pixels=n, error='version and original do not overlap on screen')
    yo, yv = float(Y(lino)[both].mean()), float(Y(linv)[both].mean())
    hot = (dE > pix_de) & both
    bl = blobs(dE, both, lv[..., 0] - lo[..., 0], cell=bcell)
    big = [b for b in bl if b['share'] >= A.blob_share]
    r = dict(pixels=n, mean_dE=float(dE[both].mean()), p95_dE=float(np.percentile(dE[both], 95)),
             lum_original=yo, lum_version=yv, lum_drift=(yv - yo) / max(yo, 1e-6),
             rgb_delta_255=[float(x) for x in ((v[..., :3] - o[..., :3])[both].mean(0) * 255)],
             hot_share=float(hot.sum()) / n, blobs=bl[:8], worst_cell_dE=max([b['dE'] for b in big], default=0.0),
             silhouette_change=float(xor.sum()) / max(1, int((mo | mv).sum())))
    if eo is not None and ev is not None:   # material: what the BSDF is, not how it is lit (base x (1 - metallic) etc.)
        for p, k in (('DiffCol', 'albedo'), ('GlossCol', 'gloss')):
            a, b = float(Y(eo[p])[both].mean()), float(Y(ev[p])[both].mean())
            r[k + '_original'], r[k + '_version'], r[k + '_drift'] = a, b, (b - a) / max(a, 1e-4)
    # picture: the original dimmed grey; magenta where |dE| > pix_de (brighter = larger), cyan where only one covers
    g = (o[..., :3].mean(-1, keepdims=True) * 0.45) * np.ones(3, np.float32)
    g[~mo] = 0.08
    k = np.clip((dE - pix_de) / 30.0, 0, 1)[..., None] * 0.6 + 0.4
    g = np.where(hot[..., None], np.array([1.0, 0.15, 0.85], np.float32) * k, g)
    g = np.where(xor[..., None], np.array([0.1, 0.9, 1.0], np.float32), g)
    if not getattr(A, 'no_thin', False):   # thin features (a stripe, a trim line): scripts/_thin.py
        if os.path.dirname(os.path.abspath(__file__)) not in sys.path: sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import _thin
        th = _thin.thin_features(o, v)
        if 'error' not in th:
            H_ = o.shape[0]
            g = np.where(th.pop('lost_mask')[..., None], np.array([1.0, 0.55, 0.0], np.float32), g)       # orange: a feature the version lost
            g = np.where(th.pop('added_mask')[..., None], np.array([0.3, 1.0, 0.2], np.float32), g)      # green: one it added
            for k_ in ('lost_pieces', 'added_pieces'):       # rows are bottom-up here: boxes from the top-left like blobs[]
                for b in th[k_]: x0, y0, x1, y1 = b['box_px']; b['box_px'] = [x0, H_ - y1, x1, H_ - y0]
            r['thin'] = th
    for b in big[:6]:   # yellow boxes round the regions that count
        x0, y0, x1, y1 = b['box_px']; H = g.shape[0]
        yb0, yb1 = H - y1, H - y0
        for t in range(2):
            g[max(yb0 - t, 0), x0:x1] = g[min(yb1 - 1 + t, H - 1), x0:x1] = (1, 0.9, 0.1)
            g[yb0:yb1, max(x0 - t, 0)] = g[yb0:yb1, min(x1 - 1 + t, g.shape[1] - 1)] = (1, 0.9, 0.1)
    save_rgb(g, out_png)
    return r


def verdict(r, A):
    why = []
    if 'error' in r:
        return [r['error']]
    if r['mean_dE'] > A.max_de:
        why.append('mean dE %.1f > %.1f' % (r['mean_dE'], A.max_de))
    if abs(r['lum_drift']) > A.max_lum:
        why.append('luminance %+.0f %% (limit %.0f %%)' % (r['lum_drift'] * 100, A.max_lum * 100))
    if r['hot_share'] > A.max_hot:   # off by default (1.0): glass reflections dominate it
        why.append('%.0f %% of pixels dE > 12 (limit %.0f %%)' % (r['hot_share'] * 100, A.max_hot * 100))
    big = [b for b in r['blobs'] if b['share'] >= A.blob_share and b['dE'] > A.max_cell][:3]
    if big:
        why.append('region(s) ' + ', '.join('%.1f %% of the asset dE %.0f %s (L* %+.0f) at x %d-%d y %d-%d px' % (
            b['share'] * 100, b['dE'], 'darker' if b['dL'] < -5 else 'lighter' if b['dL'] > 5 else 'other colour', b['dL'],
            b['box_px'][0], b['box_px'][2], b['box_px'][1], b['box_px'][3]) for b in big))
    th = r.get('thin') or {}
    if th.get('fail'):
        msg = 'thin features: ' + '; '.join(th['fail'])
        if getattr(A, 'thin_fail', False): why.append(msg)
        else: r['advisory'] = [msg + ' (ADVISORY: --thin-fail makes it count)']
    if 'albedo_drift' in r and abs(r['albedo_drift']) > A.max_albedo:
        why.append('material colour (diffuse pass, base x (1 - metallic)) %+.0f %% (limit %.0f %%)' % (
            r['albedo_drift'] * 100, A.max_albedo * 100))
    if 'gloss_drift' in r and abs(r['gloss_drift']) > A.max_gloss:
        why.append('gloss (glossy-colour pass) %+.0f %% (limit %.0f %%)' % (r['gloss_drift'] * 100, A.max_gloss * 100))
    return why


# ---------------------------------------------------------------------------------------------------------- modes
def kyiv_now():
    try:
        os.environ.setdefault('TZ', 'Europe/Kyiv'); time.tzset()
    except Exception:
        pass
    return time.strftime('%Y-%m-%d %H:%M Kyiv')


def tiles_dir(out):
    d = os.path.splitext(out)[0]
    os.makedirs(d, exist_ok=True)
    return d


def prepare(A, paths, wet_needed):
    sc = bpy.context.scene
    groups = [load(p, A, 'RT_asset_%d' % i) for i, p in enumerate(paths)]
    bpy.context.view_layer.update()
    stage = Stage(A, sc)
    show_groups(groups, groups)
    P = bounds_points()
    lo, hi = P.min(0), P.max(0)
    log('bounds', lo.round(3).tolist(), hi.round(3).tolist())
    stage.make_ground(float(lo[2]), float(np.linalg.norm(hi - lo)) / 2)
    make_asset_lights(stage, A, paths, groups)
    return sc, stage, groups, P


def mode_thumb(A):
    states = (A.states or 'day,dawn,dusk,night,rain').split(',')     # a design decision: every light state by default
    size = A.size or 1280
    sc, stage, groups, P = prepare(A, [A.input], 'rain' in states)
    setup_render(A, sc, size, size * 3 // 4)
    stem = os.path.splitext(os.path.basename(A.input))[0]
    od = A.out or os.path.join(os.path.dirname(os.path.abspath(A.input)), 'renders')
    if od.lower().endswith('.png'):
        od = os.path.dirname(od)
    az, el = view_az(A, 'front34', A.az)
    el = A.el if A.el is not None else el
    outs = []
    wet = Wet()
    for st in [s for s in states if s != 'rain'] + [s for s in states if s == 'rain']:
        if st == 'rain':
            wet.apply()
        stage.light_for(st, az)
        fit_camera(stage.cam, P, az, el, 4 / 3)
        outs.append(render(sc, os.path.join(od, stem + ('' if st == 'day' else '-' + st) + '.png')))
    wet.restore()
    return outs[0] if outs else od


def upright_views(A, P, views):
    """An upright, thin part (a door, a window unit, a sign: its smaller plan size under a quarter of its height) seen
    straight from above is a strip and a shadow. Its default sheet swaps 'top' for 'high34': 45 deg up, 35 deg off
    the normal of its broad face, on the side --front names when the thin axis is the front axis (else + side)."""
    lo, hi = P.min(0), P.max(0); d = hi - lo
    thin = 0 if d[0] < d[1] else 1
    if 'top' not in views or min(d[0], d[1]) >= 0.25 * d[2]:
        return views
    az0 = 90.0 * thin + (180.0 if A.front == '-' + 'xy'[thin] else 0.0)
    VIEWS['high34'] = (az0 - 35 - FRONT_AZ[A.front], 45)        # view_az adds the front azimuth back
    log('sheet: upright part (%.2f m thin, %.2f m tall): the top tile is replaced by high34 (from %s%s, 45 deg up)'
        % (min(d[0], d[1]), d[2], '-' if az0 >= 180 else '+', 'xy'[thin]))
    return ['high34' if v == 'top' else v for v in views]


def mode_sheet(A):
    states = (A.states or 'day').split(',')
    views = (A.views or 'front34,rear34,side,top').split(',')
    size = A.size or 1280
    sc, stage, groups, P = prepare(A, [A.input], 'rain' in states)
    P = focus_points(A, P)
    if not A.views:
        views = upright_views(A, P, views)
    setup_render(A, sc, size, size * 3 // 4)
    out = A.out or os.path.join(os.path.dirname(os.path.abspath(A.input)), 'SHEET.jpg')
    td = tiles_dir(out)
    rows, wet = [], Wet()
    for st in states:
        if st == 'rain':
            wet.apply()
        row = []
        for v in views:
            row.append(dict(path=shoot(stage, A, P, v, st, os.path.join(td, '%s-%s.png' % (v, st)), 4 / 3),
                            label='%s · %s' % (v, st)))
        if st == 'rain':
            wet.restore()
        for i in range(0, len(row), 2):
            rows.append(row[i:i + 2])
    compose_out(rows, out, A.title or '%s   %s' % (os.path.basename(A.input), kyiv_now()), not A.no_tiles)
    return out


def next_round(d):
    ns = [int(m.group(1)) for f in glob.glob(os.path.join(d, 'ROUND-*.jpg'))
          for m in [re.search(r'ROUND-(\d+)\.jpg$', f)] if m]
    return max(ns) + 1 if ns else 1


def mode_round(A):
    size = A.size or 960
    sc, stage, groups, P = prepare(A, [A.input], True)
    setup_render(A, sc, size, size * 3 // 4)
    if A.out:
        out = A.out
    else:
        d = os.path.join(os.path.dirname(os.path.abspath(A.input)), 'rounds')
        out = os.path.join(d, 'ROUND-%d.jpg' % (A.n or next_round(d)))
    td = tiles_dir(out)
    chk = integrity_start(A, td)
    tiles = []
    for v in ('front34', 'rear34', 'side', 'top', 'under34', 'nose'):
        tiles.append(dict(path=shoot(stage, A, P, v, 'day', os.path.join(td, '%s-day.png' % v), 4 / 3),
                          label=v + ' · day'))
    poses = interior_cams(stage, A, P, A.interior) if A.interior > 0 else []
    for i, pose in enumerate(poses):
        tiles.append(dict(path=shoot_interior(stage, pose, 'day', os.path.join(td, 'interior%d-day.png' % (i + 1))),
                          label='interior %d · day, lights on' % (i + 1)))
    for st in ('dusk', 'night'):
        for v in ('front34', 'side'):
            tiles.append(dict(path=shoot(stage, A, P, v, st, os.path.join(td, '%s-%s.png' % (v, st)), 4 / 3),
                              label='%s · %s' % (v, st)))
        if st == 'night':
            for i, pose in enumerate(poses):
                tiles.append(dict(path=shoot_interior(stage, pose, 'night',
                                                      os.path.join(td, 'interior%d-night.png' % (i + 1))),
                                  label='interior %d · night' % (i + 1)))
    wet = Wet(); wet.apply()
    for v in ('front34', 'side'):
        tiles.append(dict(path=shoot(stage, A, P, v, 'rain', os.path.join(td, '%s-rain.png' % v), 4 / 3),
                          label='%s · rain' % v))
    wet.restore()
    header = integrity_finish(A, chk)
    try:      # materials, as authored (wet/night restored above): pbr_check in-process, no bake (~1.6 s); never fails the sheet
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import pbr_check
        pr = pbr_check.check_blend(collection=getattr(A, 'collection', None))
        header.append('materials (pbr_check, no bake): ' + pr.result + ('' if pr.ok else ': ' + ' | '.join(
            f'{f.rule} {f.group}' + (f' {f.share:.0%}' if f.share is not None else '') for f in pr.errors()[:5])))
    except Exception as e:
        header.append(f'materials (pbr_check): not run ({e})')
    if not getattr(A, 'no_look', False):      # advisory look measures (3d-modelling/scripts/look/look.py, ~35 s; system python3: it needs PIL, and runs its own Blender); never fails the sheet
        try:
            import subprocess
            lk = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '3d-modelling', 'scripts', 'look', 'look.py')
            lp = subprocess.run(['/usr/bin/python3', lk, os.path.abspath(A.input), '--out', os.path.join(td, 'look'), '--family', getattr(A, 'family', None) or 'train',
                                 '--front', getattr(A, 'front', None) or '+x'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=1800)
            ll = [l.strip() for l in lp.stdout.splitlines() if l.startswith(('LOOK', 'RESULT'))]
            for l in ll:
                print('RT_CHECK', l[:300], flush=True)
            header.append('look (advisory, look.py): ' + (' | '.join(l[:110] for l in ll[-1:] + ll[:5]) if ll else 'no output: ' + lp.stdout[-200:]))
        except Exception as e:
            header.append(f'look (look.py): not run ({e})')
    cols = 4
    rows = [tiles[i:i + cols] for i in range(0, len(tiles), cols)]
    compose_out(rows, out, A.title or '%s   round %s   %s' % (os.path.basename(A.input),
                re.sub(r'\D', '', os.path.basename(out)) or '?', kyiv_now()), not A.no_tiles, header)
    return out


def pixel_ray(sc, cam, u, v, w, h):
    """World ray through pixel (u, v) of a saved image (top-left origin, w x h), render border/crop respected."""
    R = sc.render
    if R.use_border and R.use_crop_to_border:
        fx = R.border_min_x + (u / w) * (R.border_max_x - R.border_min_x)
        fy = R.border_max_y - (v / h) * (R.border_max_y - R.border_min_y)
    else:
        fx, fy = u / w, 1 - v / h
    tr, br, bl, tl = cam.data.view_frame(scene=sc)
    p = bl + (br - bl) * fx + (tl - bl) * fy
    M = cam.matrix_world
    return M.translation.copy(), (M.to_3x3() @ p).normalized()


def region_places(sc, cam, blist, w, h):
    """3D place of each region on the visible version: rays through the box centre and a 3 x 3 grid inside it.
    Blender Z-up and glTF Y-up (x, z, -y) coordinates, the object hit, and the box of all hits."""
    dg = bpy.context.evaluated_depsgraph_get()
    for b in blist:
        x0, y0, x1, y1 = b['box_px']
        pts = [((x0 + x1) / 2, (y0 + y1) / 2)] + [(x0 + (x1 - x0) * i / 4, y0 + (y1 - y0) * j / 4) for i in (1, 2, 3) for j in (1, 2, 3)]
        hits = []
        for u, v in pts:
            o, d = pixel_ray(sc, cam, u, v, w, h)
            hit, loc, nrm, idx, ob, mat = sc.ray_cast(dg, o, d)
            if hit:
                hits.append((loc, nrm, ob.name if ob else ''))
        if not hits:
            b['place'] = None
            continue
        c = hits[0]
        H = np.array([list(hh[0]) for hh in hits])
        g = lambda p: [round(float(p[0]), 3), round(float(p[2]), 3), round(float(-p[1]), 3)]
        b['place'] = dict(blender_xyz=[round(float(x), 3) for x in c[0]], gltf_xyz=g(c[0]), normal_blender=[round(float(x), 3) for x in c[1]],
                          object=c[2], hits=len(hits), objects=sorted({hh[2] for hh in hits}),
                          box_blender=[[round(float(x), 3) for x in H.min(0)], [round(float(x), 3) for x in H.max(0)]],
                          box_gltf=[[round(float(H[:, 0].min()), 3), round(float(H[:, 2].min()), 3), round(float(-H[:, 1].max()), 3)],
                                    [round(float(H[:, 0].max()), 3), round(float(H[:, 2].max()), 3), round(float(-H[:, 1].min()), 3)]])
    return blist


def version_role(lab, i):
    for k in ('near', 'mid', 'far'):
        if k in lab.lower():
            return k
    return ('near', 'mid', 'far')[min(i, 2)]


def mode_lodcmp(A):
    """Each game version against the original, per light state: (1) the asset filling the frame from fixed views,
    (2) with --at-switch, through the game camera at the closest distance the game shows that version."""
    global EXIT_CODE
    vers = [v for v in A.versions.split(',') if v]
    files = [A.original] + vers
    views = (A.views or 'front34,side,rear34,top').split(',')
    sviews = (A.state_views or 'front34,side').split(',')
    states = (A.states or 'day,dusk,night').split(',')
    size = A.size or 960
    A.no_ground = True   # the silhouette is the mask: no ground in the picture
    sc, stage, groups, P = prepare(A, files, False)
    # lights belong to the asset, not to a version: every version is lit by the ORIGINAL's lights (the game does that)
    keep = []
    for o, w, g in stage.asset_lights:
        if g == groups[0]:
            keep.append((o, w, None))
        else:
            bpy.data.objects.remove(o)
    stage.asset_lights = keep
    log('lodcmp: %d light(s) from the original light every version' % len(keep))
    setup_render(A, sc, size, size * 3 // 4)
    sc.render.film_transparent = True; sc.render.image_settings.color_mode = 'RGBA'
    vl = sc.view_layers[0]; vl.use_pass_diffuse_color = True; vl.use_pass_glossy_color = True
    out = A.out or os.path.join(os.path.dirname(os.path.abspath(A.original.split('+')[0])), 'LODCMP.jpg')
    td = tiles_dir(out)
    labels = ['original'] + [label_of(v) for v in vers]
    if len(set(labels)) < len(labels):
        labels = ['original'] + ['v%d-%s' % (i + 1, l) for i, l in enumerate(labels[1:])]
    res = {l: dict(filled={}, switch={}) for l in labels[1:]}
    sheets, t_cmp = {}, [0.0]

    def save_exr(path):
        im = sc.render.image_settings
        if hasattr(im, 'media_type'):
            im.media_type = 'MULTI_LAYER_IMAGE'
        im.file_format = 'OPEN_EXR_MULTILAYER'; im.color_depth = '16'; im.exr_codec = 'DWAA'
        bpy.data.images['Render Result'].save_render(path, scene=sc)
        if hasattr(im, 'media_type'):
            im.media_type = 'IMAGE'
        im.file_format = 'PNG'; im.color_mode = 'RGBA'; im.color_depth = '8'
        return load_passes(path)

    def judge(lab, key, po, pv, diff, eo=None, ev=None, cell=16, wh=None):
        t = time.time()
        r = compare_pair(po, pv, diff, A, eo=eo, ev=ev, bcell=cell)
        if 'error' not in r:
            show_groups(groups, [groups[labels.index(lab)]])
            region_places(sc, stage.cam, r['blobs'], *wh)
        t_cmp[0] += time.time() - t
        r['fail'] = verdict(r, A)
        if 'error' not in r:
            log('lodcmp %s %s: dE %.2f lum %+.1f%% albedo %s gloss %s hot %.0f%% region %.0f %s | %s' % (
                lab, key, r['mean_dE'], r['lum_drift'] * 100,
                '%+.0f%%' % (r['albedo_drift'] * 100) if 'albedo_drift' in r else '-',
                '%+.0f%%' % (r['gloss_drift'] * 100) if 'gloss_drift' in r else '-', r['hot_share'] * 100,
                r['worst_cell_dE'], ['%.1f%%/dE%.0f/L%+.0f@%s' % (b['share'] * 100, b['dE'], b['dL'],
                                     b['place']['gltf_xyz'] if b.get('place') else '-') for b in r['blobs'][:3]],
                '; '.join(r['fail']) or 'ok'))
            for a_ in r.get('advisory', []): log('lodcmp %s %s: %s' % (lab, key, a_))
        return r

    def diff_label(lab, r, extra=''):
        if 'error' in r:
            return '%s: %s' % (lab, r['error'])
        return '%s %s%s: dE %.1f  lum %+.0f%%%s  region %.0f' % (
            'FAIL' if r['fail'] else 'ok', lab, extra, r['mean_dE'], r['lum_drift'] * 100,
            '  albedo %+.0f%%' % (r['albedo_drift'] * 100) if 'albedo_drift' in r else '', r['worst_cell_dE'])

    # (1) filled frame, per state
    for st in states:
        rows = []
        for view in (views if st == 'day' else sviews):
            az, el = view_az(A, view)
            fit_camera(stage.cam, P, az, el, 4 / 3)
            paths, passes = {}, {}
            for lab, g in zip(labels, groups):
                show_groups(groups, [g])
                stage.light_for(st, az, under=el < 0)
                paths[lab] = render(sc, os.path.join(td, '%s-%s-%s.png' % (lab, view, st)))
                if st == 'day':   # material passes do not depend on the light: day only
                    passes[lab] = save_exr(os.path.join(td, '%s-%s.exr' % (lab, view)))
            top = [dict(path=paths['original'], label='original · %s · %s' % (view, st))]
            bot = [dict(size=[size, size * 3 // 4], label='magenta dE>12 · cyan silhouette · yellow region')]
            for lab in labels[1:]:
                dp = os.path.join(td, 'diff-%s-%s-%s.png' % (lab, view, st))
                r = judge(lab, '%s/%s' % (view, st), paths['original'], paths[lab], dp,
                          passes.get('original'), passes.get(lab), 16, (size, size * 3 // 4))
                res[lab]['filled'].setdefault(st, {})[view] = r
                top.append(dict(path=paths[lab], label='%s · %s · %s' % (lab, view, st)))
                bot.append(dict(path=dp, label=diff_label(lab, r)) if 'error' not in r else
                           dict(size=[size, size * 3 // 4], label=diff_label(lab, r)))
            rows += [top, bot]
        sheets[st] = rows
    # (2) at the game's switch distances, through the game camera
    if A.at_switch:
        R0, R1 = (float(x) for x in A.switch.split(','))
        Wf, Hf = (int(x) for x in A.screen.lower().split('x'))
        sc.render.resolution_x, sc.render.resolution_y = Wf, Hf
        cam = stage.cam
        cam.data.type = 'PERSP'; cam.data.sensor_fit = 'VERTICAL'; cam.data.angle_y = math.radians(A.fov)
        cam.data.clip_start = 0.3; cam.data.clip_end = 5000
        lo, hi = P.min(0), P.max(0); ctr = (lo + hi) / 2; rad = float(np.linalg.norm(hi - lo)) / 2
        az, el = -40 + FRONT_AZ[A.front], 17.0
        dvec = sun_vec(el, az)
        dist = {'near': A.near_dist, 'mid': R0 - A.hyst, 'far': R1 - A.hyst}
        rows = []
        from bpy_extras.object_utils import world_to_camera_view
        for st in states:
            row = []
            for i, lab in enumerate(labels[1:]):
                role = version_role(lab, i); d = dist[role]
                cam.location = Vector(ctr.tolist()) + dvec * (d + rad)
                cam.rotation_euler = (-dvec).to_track_quat('-Z', 'Y').to_euler()
                bpy.context.view_layer.update()
                uv = [world_to_camera_view(sc, cam, Vector(p.tolist())) for p in P]
                u0 = max(0.0, min(x.x for x in uv)); u1 = min(1.0, max(x.x for x in uv))
                v0 = max(0.0, min(x.y for x in uv)); v1 = min(1.0, max(x.y for x in uv))
                mu, mv = (u1 - u0) * 0.06 + 4 / Wf, (v1 - v0) * 0.06 + 4 / Hf
                sc.render.use_border = True; sc.render.use_crop_to_border = True
                sc.render.border_min_x, sc.render.border_max_x = max(0, u0 - mu), min(1, u1 + mu)
                sc.render.border_min_y, sc.render.border_max_y = max(0, v0 - mv), min(1, v1 + mv)
                pw = round((sc.render.border_max_x - sc.render.border_min_x) * Wf)
                ph = round((sc.render.border_max_y - sc.render.border_min_y) * Hf)
                pp = {}
                for who in ('original', lab):
                    show_groups(groups, [groups[labels.index(who)]])
                    stage.light_for(st, az)
                    pp[who] = render(sc, os.path.join(td, 'switch-%s-%s-%gm-%s.png' % (who, lab, d, st)))
                dp = os.path.join(td, 'diff-switch-%s-%gm-%s.png' % (lab, d, st))
                cell = int(min(16, max(3, round(min(pw, ph) / 40))))
                r = judge(lab, 'switch %g m/%s' % (d, st), pp['original'], pp[lab], dp, cell=cell, wh=(pw, ph))
                r.update(distance_m=d, role=role, screen=[Wf, Hf], crop_px=[pw, ph], cell_px=cell,
                         shown_range_m={'near': [0, R0 + A.hyst], 'mid': [R0 - A.hyst, R1 + A.hyst],
                                        'far': [R1 - A.hyst, None]}[role])
                res[lab]['switch'][st] = r
                k = 1.0 if 250 <= ph <= 420 else (float(min(8, max(1, round(320 / max(ph, 1))))) if ph < 250 else 360 / ph)
                tag = ' (x%d px)' % k if k > 1 else ''
                row += [dict(path=pp['original'], label='original @ %g m · %s%s' % (d, st, tag), scale=k),
                        dict(path=pp[lab], label='%s @ %g m · %s' % (lab, d, st), scale=k),
                        dict(path=dp, label=diff_label(lab, r), scale=k) if 'error' not in r else
                        dict(size=[pw, ph], label=diff_label(lab, r), scale=k)]
            rows.append(row)
        sc.render.use_border = False
        sheets['switch'] = rows
    # verdicts and outputs
    header, summary = [], {}
    for lab in labels[1:]:
        fails = []
        for st, vs in res[lab]['filled'].items():
            fails += ['%s/%s: %s' % (v, st, '; '.join(r['fail'])) for v, r in vs.items() if r.get('fail')]
        for st, r in res[lab]['switch'].items():
            if r.get('fail'):
                fails.append('switch %g m/%s: %s' % (r['distance_m'], st, '; '.join(r['fail'])))
        day = [r for r in res[lab]['filled'].get('day', {}).values() if 'error' not in r]
        adv = ['%s/%s: %s' % (v, st, a_) for st, vs in res[lab]['filled'].items() for v, r in vs.items() for a_ in r.get('advisory', [])] + \
              ['switch %g m/%s: %s' % (r['distance_m'], st, a_) for st, r in res[lab]['switch'].items() for a_ in r.get('advisory', [])]
        summary[lab] = dict(res[lab], fail=fails, advisory=adv,
                            mean_dE_day=float(np.mean([r['mean_dE'] for r in day])) if day else None,
                            lum_drift_day=float(np.mean([r['lum_drift'] for r in day])) if day else None)
        header.append('%s %s: %d check(s) failed%s%s' % ('FAULT' if fails else 'ok', lab, len(fails),
                      ('  | ' + ' | '.join(fails)) if fails else '', ('  | %d advisory (thin features)' % len(adv)) if adv else ''))
        if fails:
            EXIT_CODE = 4; FAIL_REASONS.append('%s differs from the original in %d check(s)' % (lab, len(fails)))
    header.append('limits: mean dE %.0f, luminance %.0f %%, material colour %.0f %%, gloss %.0f %%, a region >= %.0f %% of the asset with dE > %.0f (same camera and light state, display sRGB, CIE76; material = day diffuse/glossy colour passes)' % (
        A.max_de, A.max_lum * 100, A.max_albedo * 100, A.max_gloss * 100, A.blob_share * 100, A.max_cell))
    jp = os.path.join(os.path.dirname(out), 'lodcmp.json')
    json.dump(dict(original=A.original, versions=dict(zip(labels[1:], vers)), views=views, state_views=sviews, states=states,
                   size=[size, size * 3 // 4], at_switch=dict(switch_m=A.switch, hysteresis_m=A.hyst, near_m=A.near_dist,
                   fov=A.fov, screen=A.screen, camera='chase az -40 el 17 from the front, distance = surface distance + bounding radius')
                   if A.at_switch else None,
                   limits=dict(mean_dE=A.max_de, lum_drift=A.max_lum, albedo_drift=A.max_albedo, gloss_drift=A.max_gloss,
                               hot_share=A.max_hot, region_dE=A.max_cell, region_share=A.blob_share, pixel_dE=12),
                   region_place_note='each region (blobs[]) has box_px (x0, y0, x1, y1 from the top-left of its tile) and place: '
                   'blender_xyz / gltf_xyz of the ray hit at the box centre on the VERSION, the objects hit and box_gltf of 10 hits',
                   results=summary, compare_seconds=round(t_cmp[0], 1)), open(jp, 'w'), indent=1)
    log('lodcmp metrics + ray casts %.1fs, json %s' % (t_cmp[0], jp))
    base = os.path.splitext(out)[0]
    title = 'lodcmp  original | %s  %s' % (' | '.join(labels[1:]), kyiv_now())
    for key, rows in sheets.items():
        o = out if key == 'day' else '%s-%s.jpg' % (base, key)
        compose_out(rows, o, (A.title or title) + ('' if key == 'day' else '   [%s]' % key), not A.no_tiles, header)
    return out


def lod_dists(paths):
    for p in paths:
        d = os.path.dirname(os.path.abspath(p))
        for j in (os.path.join(d, 'asset.json'), os.path.join(os.path.dirname(d), 'asset.json')):
            try:
                J = json.load(open(j))
            except Exception:
                continue
            L = J.get('lods') or J.get('lod') or J.get('versions') or {}
            ds = []
            if isinstance(L, dict):
                L = list(L.values())
            for x in L if isinstance(L, list) else []:
                if isinstance(x, dict):
                    for k in ('switch_distance_m', 'from_m', 'switch_m', 'from', 'distance', 'min_distance'):
                        if isinstance(x.get(k), (int, float)) and x[k] > 0:
                            ds.append(float(x[k])); break
            if ds:
                log('LOD switch distances from', j, ds)
                return sorted(set(ds))
    sw = switch_family(None)
    log('LOD distances from scripts/switch.json family', sw['family'], sw['appears'])
    return [float(x) for x in sw['appears']]


def label_of(p):
    s = os.path.splitext(os.path.basename(p.split('+')[0]))[0]
    return s.rsplit('-', 1)[-1] if '-' in s else s


def version_labels(files, given=None):
    """given ('before,after', --labels): one label per file, used as written (a deliverable named
    'lamp-platform-original.blend' otherwise reads "original" beside "before"). Else one label per file, all different: label_of(), and when two files share it (before/part.blend, after/part.blend)
    the folder is put in front, then a number. The tile of each file is named after its label: two files with one
    label wrote ONE tile, and the sheet showed the second model in both columns."""
    if given:
        labs = [x.strip() for x in given.split(',')]
        if len(labs) != len(files) or len(set(labs)) < len(labs) or not all(labs):
            raise SystemExit('RT ERROR: --labels wants %d different names, comma separated (got %r)' % (len(files), given))
        return labs
    labs = [label_of(f) for f in files]
    if len(set(labs)) < len(labs):
        labs = ['%s/%s' % (os.path.basename(os.path.dirname(os.path.abspath(f.split('+')[0]))), l) for f, l in zip(files, labs)]
    if len(set(labs)) < len(labs):
        labs = ['%d %s' % (i + 1, l) for i, l in enumerate(labs)]
    return labs


def mode_versions(A):
    files = [f.strip() for f in A.files.split(',') if f.strip()]
    dists = [float(x) for x in A.dist.split(',')] if A.dist else lod_dists(files)
    W, H = (int(x) for x in A.screen.lower().split('x'))
    sc, stage, groups, P = prepare(A, files, False)
    setup_render(A, sc, W, H)
    out = A.out or os.path.join(os.path.dirname(os.path.abspath(files[0].split('+')[0])), 'versions', 'VERSIONS.jpg')
    td = tiles_dir(out)
    lo, hi = P.min(0), P.max(0)
    c = (lo + hi) / 2
    cam = stage.cam
    cam.data.type = 'PERSP'; cam.data.sensor_fit = 'VERTICAL'; cam.data.angle_y = math.radians(A.fov)
    cam.data.clip_start = 0.3; cam.data.clip_end = 5000
    az = A.az if A.az is not None else -40 + FRONT_AZ[A.front]
    el = A.el if A.el is not None else 17.0
    d = sun_vec(el, az)
    labels = version_labels(files, getattr(A, 'labels', None))
    rows = []
    for dist in dists:
        cam.location = Vector(c.tolist()) + d * dist
        cam.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
        bpy.context.view_layer.update()
        # crop to the union of all versions on screen, at true pixels
        from bpy_extras.object_utils import world_to_camera_view
        uv = [world_to_camera_view(sc, cam, Vector(p.tolist())) for p in P]
        u0 = max(0.0, min(x.x for x in uv)); u1 = min(1.0, max(x.x for x in uv))
        v0 = max(0.0, min(x.y for x in uv)); v1 = min(1.0, max(x.y for x in uv))
        mu, mv = (u1 - u0) * 0.06 + 4 / W, (v1 - v0) * 0.06 + 4 / H
        sc.render.use_border = True; sc.render.use_crop_to_border = True
        sc.render.border_min_x, sc.render.border_max_x = max(0, u0 - mu), min(1, u1 + mu)
        sc.render.border_min_y, sc.render.border_max_y = max(0, v0 - mv), min(1, v1 + mv)
        ph = (sc.render.border_max_y - sc.render.border_min_y) * H
        k = 1.0
        if ph < 300:
            k = float(min(8, math.ceil(300 / max(ph, 1))))
        elif ph > 700:
            k = 700 / ph
        row = []
        for f, g, lb in zip(files, groups, labels):
            show_groups(groups, [g])
            stage.light_for('day', az)
            p = render(sc, os.path.join(td, '%s-%gm.png' % (re.sub(r'[^A-Za-z0-9._-]+', '_', lb), dist)))
            lab = '%s @ %g m' % (lb, dist) + (' (x%d px)' % k if k > 1 else '')
            row.append(dict(path=p, label=lab, scale=k))
        rows.append(row)
    sc.render.use_border = False
    compose_out(rows, out, A.title or 'versions  %s  (game camera: fov %g, %dx%d)  %s' % (
        ' | '.join(labels), A.fov, W, H, kyiv_now()), not A.no_tiles)
    return out


def mode_beforeafter(A):
    states = (A.states or 'day').split(',')
    views = (A.views or 'front34').split(',')
    size = A.size or 1280
    files = [A.before, A.after]
    sc, stage, groups, P = prepare(A, files, 'rain' in states)
    P = focus_points(A, P)
    setup_render(A, sc, size, size * 3 // 4)
    out = A.out or os.path.join(os.path.dirname(os.path.abspath(A.after)), 'BEFORE-AFTER.jpg')
    td = tiles_dir(out)
    rows, wet = [], Wet()
    for st in states:
        if st == 'rain':
            wet.apply()
        for v in views:
            row = []
            for tag, f, g in zip(('before', 'after'), files, groups):
                show_groups(groups, [g])
                row.append(dict(path=shoot(stage, A, P, v, st, os.path.join(td, '%s-%s-%s.png' % (tag, v, st)), 4 / 3),
                                label='%s: %s · %s · %s' % (tag, os.path.basename(f), v, st)))
            rows.append(row)
        if st == 'rain':
            wet.restore()
    compose_out(rows, out, A.title or 'before | after   %s' % kyiv_now(), not A.no_tiles)
    return out


# ------------------------------------------------------------------------------------------------- inspect (close-ups)
# R3 of the toolkit research notes: a 25 m car on a 650 px tile is 3.8 cm/px, so 1-10 mm faults are
# sub-pixel on a round sheet; cropping to the region is what lets a VLM see them (ViCrop). One sheet per joint (segment).
INSPECT_TINT = {'a': (1.0, 0.40, 0.06, 1.0), 'b': (0.10, 0.40, 1.0, 1.0), 'ghost': (0.70, 0.70, 0.70, 0.25),
                'other': (0.70, 0.70, 0.70, 1.0)}
INSPECT_BG = (0.82, 0.87, 0.93)
INSPECT_W, INSPECT_H, INSPECT_GAP = 1280, 720, 4
INSPECT_MIN_WIN = 0.12   # m: a smaller box loses what the joint belongs to (a 6 cm box of a handrail end read as nothing)


def i_gltf2bl(p):
    return np.array([float(p[0]), -float(p[2]), float(p[1])])


def i_bl2gltf(p):
    return [round(float(p[0]), 4), round(float(p[2]), 4), round(float(-p[1]), 4)]


def i_unit(v, fallback=(0.0, 0.0, 1.0)):
    v = np.asarray(v, float); n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else np.asarray(fallback, float)


class InspectGeo:
    """World geometry of every rendered instance (modifiers applied, instancing realised): bounds for every instance,
    world triangles, BVH and surface samples built lazily per instance."""

    def __init__(self):
        from mathutils.bvhtree import BVHTree
        self.BVH = BVHTree
        self.mesh, self.inst, by_name = {}, [], {}
        for ob, M in instances():
            if ob.type not in GEOM or ob.name.startswith('RT_'):
                continue
            src = ob.name_full
            if src not in self.mesh:
                try:
                    me = ob.to_mesh()
                except Exception:
                    me = None
                if me is None:
                    self.mesh[src] = None
                    continue
                me.calc_loop_triangles()
                co = np.empty(len(me.vertices) * 3, np.float64); me.vertices.foreach_get('co', co)
                tri = np.empty(len(me.loop_triangles) * 3, np.int64); me.loop_triangles.foreach_get('vertices', tri)
                mats = sorted({s.material.name for s in ob.original.material_slots if s.material})
                uvh = b''
                if me.uv_layers.active is not None and len(me.loops):
                    uv = np.empty(len(me.loops) * 2, np.float32); me.uv_layers.active.data.foreach_get('uv', uv)
                    uvh = np.round(uv, 4).tobytes()
                import hashlib
                uvh = hashlib.sha1(uvh).digest()
                ob.to_mesh_clear()
                self.mesh[src] = (co.reshape(-1, 3), tri.reshape(-1, 3), mats, uvh) if len(tri) else None
            if self.mesh[src] is None:
                continue
            m = np.array(M)
            co = self.mesh[src][0]
            w = co @ m[:3, :3].T + m[:3, 3]
            o = ob.original
            part = o.get('part') or o.get('kit3d_part') if hasattr(o, 'get') else None
            d = dict(name=ob.name, src=src, M=m, lo=w.min(0), hi=w.max(0), part=str(part) if part else None, _w=None,
                     _bvh=None, flip=np.linalg.det(m[:3, :3]) < 0)
            self.inst.append(d)
            by_name.setdefault(ob.name, []).append(d)
        for nm, L in by_name.items():   # stable keys: name#k ordered by position
            L.sort(key=lambda d: tuple(np.round((d['lo'] + d['hi']) / 2, 3)))
            for k, d in enumerate(L):
                d['key'] = nm if len(L) == 1 else '%s#%d' % (nm, k)
        self.by_key = {d['key']: d for d in self.inst}
        self.LO = np.array([d['lo'] for d in self.inst]); self.HI = np.array([d['hi'] for d in self.inst])
        log('inspect: %d instances of %d meshes' % (len(self.inst), sum(1 for v in self.mesh.values() if v)))

    def world(self, d):
        if d['_w'] is None:
            co, tri = self.mesh[d['src']][:2]
            w = co @ d['M'][:3, :3].T + d['M'][:3, 3]
            d['_w'] = (w, tri[:, ::-1] if d['flip'] else tri)
        return d['_w']

    def bvh(self, d):
        if d['_bvh'] is None:
            w, tri = self.world(d)
            d['_bvh'] = self.BVH.FromPolygons(w.tolist(), tri.tolist(), all_triangles=True)
        return d['_bvh']

    def near_box(self, lo, hi, pad=0.0):
        m = np.all(self.HI >= lo - pad, 1) & np.all(self.LO <= hi + pad, 1)
        return [self.inst[i] for i in np.nonzero(m)[0]]

    def tris_in(self, d, lo, hi):
        w, tri = self.world(d)
        T = w[tri]
        m = np.all(T.max(1) >= lo, 1) & np.all(T.min(1) <= hi, 1)
        return T[m]

    def sample(self, d, lo, hi, step=0.004, cap=5000, seed=7):
        """Points spread by area on the triangles of d inside the box, with their face normals."""
        T = self.tris_in(d, lo, hi)
        if not len(T):
            return np.zeros((0, 3)), np.zeros((0, 3))
        cr = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]); ar = np.linalg.norm(cr, axis=1) / 2
        ok = ar > 1e-12; T, cr, ar = T[ok], cr[ok], ar[ok]
        if not len(T):
            return np.zeros((0, 3)), np.zeros((0, 3))
        nrm = cr / (2 * ar[:, None])
        n = int(min(cap, max(len(T), ar.sum() / (step * step))))
        rng = np.random.default_rng(seed)
        idx = rng.choice(len(T), n, p=ar / ar.sum()) if n > len(T) else np.arange(len(T))
        u, v = rng.random(len(idx)), rng.random(len(idx)); f = u + v > 1; u[f], v[f] = 1 - u[f], 1 - v[f]
        if n <= len(T):
            u[:], v[:] = 1 / 3, 1 / 3
        P = T[idx, 0] + (T[idx, 1] - T[idx, 0]) * u[:, None] + (T[idx, 2] - T[idx, 0]) * v[:, None]
        P = np.concatenate([P, T.reshape(-1, 3)[:: max(1, len(T) * 3 // 1500)]]) if len(T) < 4000 else P
        N = np.concatenate([nrm[idx], np.repeat(nrm, 3, 0)[:: max(1, len(T) * 3 // 1500)]]) if len(T) < 4000 else nrm[idx]
        return P, N

    def nearest(self, d, p, maxd=1.0):
        r = self.bvh(d).find_nearest(Vector(p.tolist()), maxd)
        return (None, None, None) if r[0] is None else (np.array(r[0]), np.array(r[1]), float(r[3]))

    def contacts(self, a, b, tol, around=None, radius=None):
        """Points where a and b come within tol: midpoint, b's normal there, signed distance of a from b (+ = outside b,
        - = inside b). Sampled on both surfaces inside the overlap of their padded bounds (or a ball around a point)."""
        lo = np.maximum(a['lo'], b['lo']) - tol; hi = np.minimum(a['hi'], b['hi']) + tol
        if around is not None:
            lo = np.maximum(lo, around - radius); hi = np.minimum(hi, around + radius)
        if np.any(lo > hi):
            return []
        out = []
        for src, dst, sgn in ((a, b, 1), (b, a, -1)):
            P, N = self.sample(src, lo, hi)
            if not len(P):
                continue
            bv = self.bvh(dst)
            for p, nn in zip(P, N):
                r = bv.find_nearest(Vector(p.tolist()), tol)
                if r[0] is None:
                    continue
                q, qn = np.array(r[0]), np.array(r[1])
                if sgn > 0:   # a's point against b's surface: b's normal is the host normal
                    out.append((0.5 * (p + q), qn, float(np.dot(p - q, qn))))
                else:         # b's point against a's surface: host normal is b's own face normal at p
                    out.append((0.5 * (p + q), nn, float(np.dot(q - p, nn))))
        return out


def i_clusters(pts, cell=0.04):
    """Connected groups of points on a grid (26-neighbourhood); list of index arrays, largest first."""
    if not len(pts):
        return []
    keys = [tuple(k) for k in np.floor(np.asarray(pts) / cell).astype(int)]
    cells = {}
    for i, k in enumerate(keys):
        cells.setdefault(k, []).append(i)
    todo, out = set(cells), []
    while todo:
        st, got = [todo.pop()], []
        while st:
            k = st.pop(); got += cells[k]
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        n = (k[0] + dx, k[1] + dy, k[2] + dz)
                        if n in todo:
                            todo.discard(n); st.append(n)
        out.append(np.array(got))
    out.sort(key=lambda g: -len(g))
    return out


def i_frame(P, normals, fallback_n=None):
    """Joint frame from contact points: centre, host normal n, seam direction t (main axis in the plane of n), b."""
    P = np.asarray(P)
    c = np.median(P, 0) if len(P) else np.zeros(3)
    n = i_unit(np.mean(normals, 0)) if len(normals) else i_unit(fallback_n if fallback_n is not None else (0, 0, 1))
    if len(P) >= 3:
        Q = P - P.mean(0); Q = Q - np.outer(Q @ n, n)
        _, s, vt = np.linalg.svd(Q, full_matrices=False)
        t = i_unit(vt[0])
    else:
        t = None
    if t is None or abs(np.dot(t, n)) > 0.9:
        t = i_unit(np.cross(n, (0, 0, 1) if abs(n[2]) < 0.9 else (1, 0, 0)))
    t = i_unit(t - np.dot(t, n) * n); b = i_unit(np.cross(n, t))
    ext = float((P @ t).max() - (P @ t).min()) if len(P) else 0.0
    wid = float((P @ b).max() - (P @ b).min()) if len(P) else 0.0
    return c, n, t, b, ext, wid


def i_stats(ds):
    """Signed distances of the joint's points: how much of it touches (|d| <= 0.3 mm), enters, or hovers."""
    if not len(ds):
        return {}
    d = np.asarray(ds)
    return dict(points=int(len(d)), touch_share=round(float((np.abs(d) <= 3e-4).mean()), 3),
                inside_share=round(float((d < -3e-4).mean()), 3), hover_share=round(float((d > 3e-4).mean()), 3),
                min_mm=round(float(d.min()) * 1000, 2), median_mm=round(float(np.median(d)) * 1000, 2),
                max_mm=round(float(d.max()) * 1000, 2))


def i_find_parts(G, spec):
    """Instances for a comma list of object names, globs, 'name#k' keys or parts.json part names; a bare name with no
    exact match takes its numbered copies (name.001 ...)."""
    out = []
    for s in [x.strip() for x in spec.split(',') if x.strip()]:
        hit = [d for d in G.inst if d['key'] == s or d['name'] == s or d['part'] == s or fnmatch.fnmatchcase(d['name'], s)]
        if not hit:
            hit = [d for d in G.inst if re.sub(r'\.\d{3}$', '', d['name']) == s]
        if not hit:
            log('inspect: no instance matches %r' % s)
        out += [d for d in hit if d not in out]
    return out


def i_nearest_inst(G, p, name=None, k=2, pad=0.15):
    cand = [d for d in G.near_box(p, p, pad) if name is None or d['name'] == name
            or re.sub(r'\.\d{3}$', '', d['name']) == re.sub(r'\.\d{3}$', '', name)]
    if not cand and name is not None:
        cand = [d for d in G.inst if d['name'] == name]
    sc = []
    for d in cand:
        q, _, dist = G.nearest(d, p, 2.0)
        if q is not None:
            sc.append((dist, d))
    sc.sort(key=lambda x: x[0])
    return [d for _, d in sc[:k]]


def i_load_places(path):
    """Places from a kit3d check.json, a mesh_integrity json, a sweep.json, or an earlier inspect.json.
    Returns [{xyz (Blender), parts [names], kind, value, source, box?}] and a note."""
    J = json.load(open(path))
    base = os.path.basename(path)
    out = []
    if isinstance(J, dict) and 'bodies' in J and ('flicker' in J or 'gaps' in J):   # mesh_integrity.py (glTF frame)
        for b in J.get('bodies', [])[1:]:
            if b.get('held') in ('held', 'inherited'):      # mesh_integrity --held-by: sits where the original holds it, or floats there too: not a place to look at
                continue
            lo, hi = i_gltf2bl(b['min']), i_gltf2bl(b['max'])
            out.append(dict(xyz=(lo + hi) / 2, parts=b.get('names', [])[:2], kind='floating', value=b.get('gap_m'),
                            source=base, box=[np.minimum(lo, hi), np.maximum(lo, hi)]))
        for g in J.get('gaps', []):
            out.append(dict(xyz=i_gltf2bl(g['centre']), parts=g.get('names', [])[:2], kind='gap', value=g.get('gap_m'),
                            source=base))
        for f in (J.get('flicker') or {}).get('places', []):
            out.append(dict(xyz=i_gltf2bl(f['centre']), parts=f.get('names', [])[:2], kind='flicker',
                            value=f.get('overlap_m2'), source=base))
        li = J.get('looked_into') or {}
        if li.get('back_share', 0) > 0.05:
            for pl in li.get('places', []):
                lo, hi = i_gltf2bl(pl['min']), i_gltf2bl(pl['max'])
                out.append(dict(xyz=(lo + hi) / 2, parts=[], kind='looked_into', value=pl.get('share'), source=base))
        for rg in (J.get('against') or {}).get('lost_regions', []):
            lo, hi = i_gltf2bl(rg['min']), i_gltf2bl(rg['max'])
            out.append(dict(xyz=(lo + hi) / 2, parts=[], kind='lost', value=rg.get('share_of_seen'), source=base))
        nm = J.get('non_manifold') or {}   # mesh_integrity >= 2026-10-13 03:14: turned-over faces, duplicates, inside-out parts
        for t in nm.get('turned_places', []):
            out.append(dict(xyz=i_gltf2bl(t['centre']), parts=[t['name']] if t.get('name') else [], kind='turned',
                            value=t.get('edges'), source=base))
        for t in nm.get('duplicate_places', [])[:8]:
            out.append(dict(xyz=i_gltf2bl(t['centre']), parts=[t['name']] if t.get('name') else [], kind='duplicate',
                            value=t.get('area_m2'), source=base))
        for t in nm.get('inside_out_places', []):
            out.append(dict(xyz=i_gltf2bl(t['centre']), parts=list(t.get('names', []))[:2], kind='inside_out',
                            value=t.get('volume_m3'), source=base))
        # mesh_integrity >= 2026-10-13 03:50: a face with its flipped copy, the largest back-to-back places, parts moved
        # against the reference (flipped copies first: they are the likely faults; plain back-to-back is mostly contact)
        fk = (J.get('flicker') or {})
        for t in fk.get('flipped_duplicate_places', []):
            out.append(dict(xyz=i_gltf2bl(t['centre']), parts=list(t.get('names', []))[:2], kind='flipped_copy',
                            value=t.get('flipped_duplicate_m2'), source=base))
        for t in [t for t in fk.get('back_to_back_places', []) if not t.get('flipped_duplicate_pairs')][:5]:
            out.append(dict(xyz=i_gltf2bl(t['centre']), parts=list(t.get('names', []))[:2], kind='back_to_back',
                            value=t.get('overlap_m2'), source=base))
        for t in (J.get('against') or {}).get('moved_places', [])[:12]:
            out.append(dict(xyz=i_gltf2bl(t['centre']), parts=list(t.get('names', []))[:2], kind='moved',
                            value=t.get('distance_m'), source=base))
        return out, 'mesh_integrity: %d places' % len(out)
    if isinstance(J, dict) and 'places' in J and isinstance(J.get('places'), list) and J.get('tool') == 'render.py inspect':
        for p in J['places']:
            out.append(dict(xyz=np.array(p['xyz']), parts=p.get('parts', [])[:2], kind=p.get('kind', 'again'),
                            value=p.get('value'), source=base, keys=p.get('instances'), reuse=p))
        return out, 'earlier inspect: %d places' % len(out)
    is_sweep = isinstance(J, dict) and 'views' in J and 'totals' in J
    gltf = is_sweep
    XYZ = ('blender_xyz', 'xyz', 'world', 'world_xyz', 'at', 'pos', 'position', 'point', 'centre', 'center', 'gltf_xyz')

    def walk(x, ctx):
        if isinstance(x, dict):
            v = next(((k, x[k]) for k in XYZ if isinstance(x.get(k), (list, tuple)) and len(x[k]) == 3
                      and all(isinstance(t, (int, float)) for t in x[k])), None)
            if v:
                k, p = v
                p = i_gltf2bl(p) if (k == 'gltf_xyz' or (gltf and k != 'blender_xyz')) else np.array(p, float)
                parts = x.get('parts') or x.get('names') or x.get('pair') or [y for y in (x.get('part'), x.get('host') or x.get('to')) if y]
                val = next((x[k2] for k2 in ('value_m', 'measured_m', 'depth_m', 'gap_m', 'value', 'measured') if k2 in x), None)
                out.append(dict(xyz=p, parts=[str(s) for s in parts][:2], kind=str(x.get('kind') or x.get('check') or x.get('rule') or ctx),
                                value=val, source=base, msg=x.get('msg') or x.get('why')))
                return
            for k, y in x.items():
                if k not in ('views',) or not is_sweep:
                    walk(y, k if isinstance(k, str) else ctx)
        elif isinstance(x, list):
            for y in x:
                walk(y, ctx)
    walk(J, 'place')
    if is_sweep and not out:
        return [], 'sweep.json has no world places (only views by distance/azimuth): use mesh_integrity FLICKER places instead'
    return out, '%s: %d places' % ('sweep' if is_sweep else 'check', len(out))


def i_parts_json(A):
    p = A.parts_json
    if not p:
        d = os.path.dirname(os.path.abspath(A.input))
        for c in (d, os.path.dirname(d), os.path.dirname(os.path.dirname(d))):
            if os.path.exists(os.path.join(c, 'parts.json')):
                p = os.path.join(c, 'parts.json'); break
    if not p:
        return None, []
    J = json.load(open(p))
    L = J.get('parts', J) if isinstance(J, dict) else J
    if isinstance(L, dict):
        L = [dict(v, part=k) if isinstance(v, dict) else {'part': k} for k, v in L.items()]
    return p, [x for x in L if isinstance(x, dict) and (x.get('part') or x.get('name'))]


def i_relations(A, plan):
    """(part, host) pairs: parts.json `host` + `relations[].host/to`, and kit3d's scene property if the file has one."""
    pairs = []
    for x in plan:
        nm = x.get('part') or x.get('name')
        for r in x.get('relations') or []:
            h = r.get('host') or r.get('to') or x.get('host') if isinstance(r, dict) else None
            if h and h != 'free':
                pairs.append((nm, h, r.get('kind') if isinstance(r, dict) else None))
        if x.get('host') and x['host'] != 'free' and not any(p[0] == nm for p in pairs):
            pairs.append((nm, x['host'], None))
    for s in bpy.data.scenes:
        for key in ('kit3d_relations', 'relations'):
            v = s.get(key) if hasattr(s, 'get') else None
            if isinstance(v, str):
                try:
                    v = json.loads(v)
                except Exception:
                    v = None
            for r in (v or []):
                try:
                    pairs.append((r.get('part'), r.get('host') or r.get('to'), r.get('kind')))
                except AttributeError:
                    pass
    seen, out = set(), []
    for p in pairs:
        if p[0] and p[1] and (p[0], p[1]) not in seen:
            seen.add((p[0], p[1])); out.append(p)
    return out


def i_fingerprints(G):
    import hashlib
    fp = {}
    for d in G.inst:
        w, tri = G.world(d)
        h = hashlib.sha1()
        h.update(np.round(w, 4).astype(np.float32).tobytes()); h.update(str(len(tri)).encode())
        h.update('|'.join(G.mesh[d['src']][2]).encode()); h.update(G.mesh[d['src']][3])
        fp[d['key']] = h.hexdigest()[:16]
        d['_w'] = None   # keep memory flat
    return fp


def i_since_fingerprints(A, G):
    """Fingerprints of the previous round: --since a .json (fingerprints/inspect.json) or a .blend/.glb (loaded and
    fingerprinted here), default the newest rounds/ROUND-*.blend beside the file that is not the file itself."""
    s = A.since
    if not s:
        d = os.path.join(os.path.dirname(os.path.abspath(A.input)), 'rounds')
        cands = sorted(glob.glob(os.path.join(d, 'ROUND-*.blend')), key=os.path.getmtime)
        cands = [c for c in cands if os.path.abspath(c) != os.path.abspath(A.input)]
        s = cands[-1] if cands else None
    if not s:
        return None, None
    if s.endswith('.json'):
        J = json.load(open(s))
        return J.get('fingerprints', J), s
    grp = load(os.path.abspath(s), A, 'RT_since')
    others = [c for c in bpy.context.scene.collection.children if c.name.startswith('RT_asset_')]
    for c in others:
        c.hide_viewport = True
    bpy.context.view_layer.update()
    G2 = InspectGeo(); fp = i_fingerprints(G2)
    for c in others:
        c.hide_viewport = False
    grp.hide_viewport = True; grp.hide_render = True
    bpy.context.view_layer.update()
    return fp, s


def i_place_from_point(G, p, names, tol, kind, value, source, box=None, keys=None):
    """A place given by a point (and maybe the two parts' names): the two instances, their contact near the point."""
    if keys and all(k in G.by_key for k in keys[:2]):
        ab = [G.by_key[k] for k in keys[:2]]
    else:
        ab = []
        for nm in names[:2]:
            r = i_nearest_inst(G, p, nm, 1)
            if r and r[0] not in ab:
                ab.append(r[0])
        if len(ab) < 2:
            for d in i_nearest_inst(G, p, None, 4):
                if d not in ab:
                    ab.append(d)
                if len(ab) == 2:
                    break
    if not ab:
        return None
    a = ab[0]; b = ab[1] if len(ab) > 1 else None
    if b is not None and np.prod(b['hi'] - b['lo'] + 1e-3) < np.prod(a['hi'] - a['lo'] + 1e-3):
        a, b = b, a   # the larger one is the host
    rad = 0.25 if box is None else max(0.1, float(np.max(box[1] - box[0])) * 0.6)
    C = G.contacts(a, b, tol, around=p, radius=rad) if b is not None else []
    if C:
        P = np.array([c[0] for c in C]); N = np.array([c[1] for c in C]); D = [c[2] for c in C]
        c, n, t, bb, ext, wid = i_frame(P, N)
        c = p if np.linalg.norm(c - p) > rad else c
    else:
        fb = None
        if b is not None:
            q, qn, _ = G.nearest(b, p, 2.0)
            fb = qn
        c, n, t, bb, ext, wid = i_frame(np.zeros((0, 3)), [], fb)
        c = np.asarray(p, float); D = []
        if box is not None:
            ext = float(np.max(box[1] - box[0]))
    return dict(a=a, b=b, c=c, n=n, t=t, bv=bb, ext=max(ext, 0.02), stats=i_stats(D), kind=kind, value=value,
                source=source, P=None)


def i_joint_places(G, a, others, tol, kind, source):
    """Every joint between instance a and each of `others` (default: everything within tol of a)."""
    out = []
    for b in others:
        if b is a:
            continue
        C = G.contacts(a, b, tol)
        if len(C) < 3:
            continue
        P = np.array([c[0] for c in C]); N = np.array([c[1] for c in C]); D = np.array([c[2] for c in C])
        aa, bb = (a, b) if np.prod(a['hi'] - a['lo'] + 1e-3) <= np.prod(b['hi'] - b['lo'] + 1e-3) else (b, a)
        if aa is not a:
            D = -D
        for g in i_clusters(P):
            if len(g) < 3:
                continue
            c, n, t, bv, ext, wid = i_frame(P[g], N[g])
            out.append(dict(a=aa, b=bb, c=c, n=n, t=t, bv=bv, ext=max(ext, 0.02), stats=i_stats(D[g]), kind=kind,
                            value=None, source=source, P=P[g], D=D[g]))
    return out


def i_segments(pl, seg_max):
    """Split a long joint into pieces no longer than seg_max along its seam, so each sheet keeps <= the mm/px limit."""
    if pl['ext'] <= seg_max or pl.get('P') is None:
        pl['segment'] = '1/1'
        return [pl]
    P, D = pl['P'], pl['D']
    s = (P - pl['c']) @ pl['t']; lo, hi = s.min(), s.max()
    k = int(math.ceil((hi - lo) / seg_max)); out = []
    for i in range(k):
        m = (s >= lo + i * (hi - lo) / k - 1e-9) & (s <= lo + (i + 1) * (hi - lo) / k + 1e-9)
        if m.sum() < 2:
            continue
        q = dict(pl); q['P'], q['D'] = P[m], D[m]
        q['c'] = np.median(P[m], 0); q['ext'] = float(s[m].max() - s[m].min()) + 0.01
        q['stats'] = i_stats(D[m]); q['segment'] = '%d/%d' % (i + 1, k)
        out.append(q)
    return out


def i_cam_pose(cam, c, d, t, dist, scale, clip=None):
    f = -i_unit(d)
    up = np.array([0.0, 0, 1]) if abs(f[2]) < 0.9 else i_unit(t)
    r = i_unit(np.cross(f, up)); u = np.cross(r, f)
    R = Matrix(((r[0], u[0], -f[0]), (r[1], u[1], -f[1]), (r[2], u[2], -f[2])))
    cam.matrix_world = Matrix.Translation(Vector((c + i_unit(d) * dist).tolist())) @ R.to_4x4()
    cam.data.type = 'ORTHO'; cam.data.ortho_scale = scale; cam.data.sensor_fit = 'AUTO'
    cam.data.clip_start = 0.0005; cam.data.clip_end = clip or max(10.0, dist * 4)


def i_dir(pl, az, el):
    a, e = math.radians(az), math.radians(el)
    return i_unit(math.cos(e) * (math.cos(a) * pl['t'] + math.sin(a) * pl['bv']) + math.sin(e) * pl['n'])


INSPECT_CANDS = [(az, el) for el in (35, 60, 15, 82, 5) for az in range(0, 360, 30)]
INSPECT_GRAZE = [(az, el) for az in (0, 180) for el in (0, 2)]   # edge-on to the host: a gap shows as a strip of background


def i_visibility(sc, pl, d, dist):
    """Share of the joint's points (up to 9) from which a ray toward the camera is unblocked for `dist` (None = to
    the sky). In the chunk scene this is the line of sight inside the cut box; in the full asset it says whether
    the joint can be seen from outside (lit, not inside a body)."""
    P = pl.get('P')
    pts = [pl['c']] if P is None or not len(P) else list(P[np.linspace(0, len(P) - 1, min(9, len(P))).astype(int)])
    dg = bpy.context.evaluated_depsgraph_get(); free = 0
    for p in pts:
        o = p + pl['n'] * 0.0015 + d * 0.0015
        hit = (sc.ray_cast(dg, Vector(o.tolist()), Vector(d.tolist()), distance=dist)[0] if dist
               else sc.ray_cast(dg, Vector(o.tolist()), Vector(d.tolist()))[0])
        free += 0 if hit else 1
    return free / len(pts)


def i_outside(sc, G, pl, r):
    """Per INSPECT_CANDS direction: the share of rays (to the sky, through the whole asset) that leave from points on
    the orange part's surface within r of the joint: where the joint can be seen from outside, lit by the sky."""
    P, N = G.sample(pl['a'], pl['c'] - r, pl['c'] + r, step=0.01, cap=400)
    if len(P) > 12:
        k = np.linspace(0, len(P) - 1, 12).astype(int); P, N = P[k], N[k]
    if not len(P):
        P, N = np.array([pl['c']]), np.array([pl['n']])
    dg = bpy.context.evaluated_depsgraph_get(); out = []
    for az, el in INSPECT_CANDS:
        d = i_dir(pl, az, el); free = n = 0
        for p, nn in zip(P, N):   # two-sided: decals and cards often face the other way
            n += 1
            o = p + nn * (0.002 if np.dot(nn, d) >= 0 else -0.002) + d * 0.001
            free += 0 if sc.ray_cast(dg, Vector(o.tolist()), Vector(d.tolist()))[0] else 1
        out.append(free / max(n, 1))
    return out


def i_choose_views(sc, pl, h, nviews, outside):
    """Directions with the clearest line of sight to the joint inside its cut box, favouring ones it can also be seen
    from outside the asset (`outside`: visibility in the full asset per INSPECT_CANDS), spread >= 55 deg apart;
    plus the grazing view along the seam."""
    cand = []
    for k, (az, el) in enumerate(INSPECT_CANDS):
        d = i_dir(pl, az, el)
        bias = {35: 0.06, 60: 0.04, 15: 0.02, 82: 0.0, 5: 0.0}[el] + (0.03 if az in (90, 270) else 0)
        cand.append((i_visibility(sc, pl, d, h * 3.5) + 0.5 * outside[k] + bias, az, el, d))
    cand.sort(key=lambda x: -x[0])
    pick = []
    for s, az, el, d in cand:
        if all(math.degrees(math.acos(max(-1, min(1, float(np.dot(d, q[3])))))) >= 55 for q in pick):
            pick.append((s, az, el, d))
        if len(pick) == nviews:
            break
    graze = []
    for az, el in INSPECT_GRAZE:
        d = i_dir(pl, az, el)
        graze.append((i_visibility(sc, pl, d, h * 3.5), az, el, d))
    graze.sort(key=lambda x: -x[0])
    return pick, graze[0]


def i_proxies(G, pl, h, isolate, coll):
    """Chunk of every instance inside the cube (centre, half size h) as a new local mesh, tinted: a orange, b blue,
    the rest ghosted (or left out with --isolate). Cut with bisect so nothing outside the cube can hide the joint."""
    import bmesh
    c = pl['c']; lo, hi = c - h, c + h
    made = []
    for d in G.near_box(lo, hi):
        role = 'a' if d is pl['a'] else 'b' if d is pl['b'] else ('skip' if isolate else 'ghost')
        if role == 'skip':
            continue
        T = G.tris_in(d, lo - 0.002, hi + 0.002)
        if not len(T):
            continue
        bm = bmesh.new()
        vs = [bm.verts.new(p) for p in T.reshape(-1, 3).tolist()]
        for i in range(len(T)):
            try:
                bm.faces.new((vs[3 * i], vs[3 * i + 1], vs[3 * i + 2]))
            except ValueError:
                pass
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
        for ax in range(3):
            for sgn in (1, -1):
                no = [0.0, 0.0, 0.0]; no[ax] = float(sgn)
                co = (hi if sgn > 0 else lo).tolist()
                geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
                bmesh.ops.bisect_plane(bm, geom=geom, plane_co=co, plane_no=no, clear_outer=True)
        if not bm.faces:
            bm.free(); continue
        me = bpy.data.meshes.new('RT_ins_' + d['key']); bm.to_mesh(me); bm.free()
        ob = bpy.data.objects.new('RT_ins_' + d['key'], me); coll.objects.link(ob)
        ob.color = INSPECT_TINT[role]
        made.append(ob)
    return made


def i_wb_setup(sc, xray=False, light_dir=None):
    sc.render.engine = 'BLENDER_WORKBENCH'
    sh = sc.display.shading
    sh.light = 'STUDIO'; sh.color_type = 'OBJECT'; sh.show_cavity = True; sh.cavity_type = 'BOTH'
    sh.cavity_ridge_factor = 1.0; sh.cavity_valley_factor = 1.6; sh.curvature_ridge_factor = 1.0
    sh.curvature_valley_factor = 1.0; sh.show_shadows = True; sh.shadow_intensity = 0.35
    sh.show_specular_highlight = True; sh.show_xray = xray; sh.xray_alpha = 0.45; sh.show_backface_culling = False
    try:
        sc.display.render_aa = '16'
    except Exception:
        pass
    if light_dir is not None:
        sc.display.light_direction = tuple(light_dir)
    sc.view_settings.view_transform = 'Standard'; sc.view_settings.look = 'None'


INSPECT_WORLD = None


def i_render_wb(sc, path, xray=False, light_dir=None):
    global INSPECT_WORLD
    keep = (sc.world, sc.view_settings.view_transform)
    if INSPECT_WORLD is None:
        INSPECT_WORLD = bpy.data.worlds.new('RT_inspect_bg'); INSPECT_WORLD.color = INSPECT_BG
    sc.world = INSPECT_WORLD
    i_wb_setup(sc, xray, light_dir)
    render(sc, path)
    sc.render.engine = 'CYCLES'; sc.world = keep[0]
    try:
        sc.view_settings.view_transform = keep[1]
    except TypeError:
        pass
    return path


def i_compose(spec_tiles, legend, out, cols):
    spec = dict(out=out, tiles=spec_tiles, legend=legend, cols=cols, w=INSPECT_W, h=INSPECT_H, gap=INSPECT_GAP)
    sp = os.path.join(TMP, 'inspect-compose.json'); json.dump(spec, open(sp, 'w'))
    for py in ('/usr/bin/python3', 'python3'):
        try:
            r = subprocess.run([py, os.path.abspath(__file__), '--compose-inspect', sp], capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                return True
            print(r.stdout.strip()[-400:], r.stderr.strip()[-800:], flush=True)
        except Exception as e:
            log('inspect compose via', py, 'failed', e)
    return False


def compose_inspect(spec):
    """One inspect sheet, exactly within w x h (Luna's 720p cap): tiles in a grid, labels on each, a legend tile."""
    from PIL import Image, ImageDraw, ImageFont

    def font(sz):
        for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/TTF/DejaVuSans.ttf'):
            if os.path.exists(p):
                return ImageFont.truetype(p, sz)
        return ImageFont.load_default()
    W, H, gap, cols = spec['w'], spec['h'], spec['gap'], spec['cols']
    tiles = spec['tiles'] + [None]
    rows = int(math.ceil(len(tiles) / cols))
    tw, th = (W - gap * (cols - 1)) // cols, (H - gap * (rows - 1)) // rows
    S = Image.new('RGB', (W, H), (22, 22, 24)); D = ImageDraw.Draw(S, 'RGBA')
    for i, t in enumerate(tiles):
        x, y = (i % cols) * (tw + gap), (i // cols) * (th + gap)
        if t is None:   # legend
            f = font(15); yy = y + 8
            for line in spec['legend']:
                col = (255, 140, 60) if line.startswith('orange') else (110, 170, 255) if line.startswith('blue') else (225, 225, 225)
                D.text((x + 10, yy), line[:60], fill=col, font=f); yy += 21
            continue
        im = Image.open(t['path']).convert('RGB')
        if im.size != (tw, th):
            im = im.crop((0, 0, min(im.width, tw), min(im.height, th)))
        S.paste(im, (x, y))
        f = font(14); lab = t.get('label', '')
        if lab:
            bb = D.textbbox((0, 0), lab, font=f)
            D.rectangle((x, y, x + bb[2] + 12, y + bb[3] + 8), fill=(0, 0, 0, 160))
            D.text((x + 6, y + 3), lab, fill=(255, 226, 90), font=f)
    S.save(spec['out'], quality=90)
    print('RT_SHEET', spec['out'], S.size, flush=True)


def mode_inspect(A):
    """Close-ups at <= --mmpx on joints and flagged places (see INSPECT in the docstring)."""
    t_start = time.time()
    sc, stage, groups, P = prepare(A, [A.input], False)
    out = A.out or os.path.join(os.path.dirname(os.path.abspath(A.input)), 'inspect')
    os.makedirs(os.path.join(out, 'tiles'), exist_ok=True)
    nviews = int(A.views) if A.views and str(A.views).isdigit() else 3
    G = InspectGeo()
    tol = A.joint_tol
    cols = 3 if (nviews + 2 + (1 if A.xray else 0)) <= 5 else 4
    ntiles = nviews + 2 + (1 if A.xray else 0)
    rows = int(math.ceil((ntiles + 1) / cols))
    tw, th = (INSPECT_W - INSPECT_GAP * (cols - 1)) // cols, (INSPECT_H - INSPECT_GAP * (rows - 1)) // rows
    win_max = tw * A.mmpx / 1000.0
    seg_max = win_max / 1.35
    notes, raw = [], []
    plan_path, plan = i_parts_json(A)
    fp_now = i_fingerprints(G)
    changed = None
    if A.round:
        fp_prev, since = i_since_fingerprints(A, G)
        if fp_prev is None:
            notes.append('round: no previous round found (rounds/ROUND-*.blend or --since): every part counts as changed')
            changed = list(fp_now)
        else:
            changed = [k for k, v in fp_now.items() if fp_prev.get(k) != v]
            notes.append('round: %d of %d instances changed since %s: %s' % (len(changed), len(fp_now), since, ', '.join(changed[:12])))
        if len(changed) > 2 * A.max_places:
            notes.append('round: %d changed instances is more than 2 x --max-places: their joints are skipped; '
                         'name them with --part or --relations --parts' % len(changed))
            changed = []
        d0 = os.path.dirname(os.path.abspath(A.input))
        flagged = sorted(glob.glob(os.path.join(d0, 'rounds', 'ROUND-*', 'integrity.json')), key=os.path.getmtime)[-1:]
        flagged += [p for p in glob.glob(os.path.join(d0, '*check*.json')) + glob.glob(os.path.join(d0, 'sweep*', 'sweep.json'))]
        A.from_ = ','.join([x for x in (A.from_ or '').split(',') if x] + flagged)
    # 1. flagged places from files
    for f in [x for x in (A.from_ or '').split(',') if x]:
        try:
            L, msg = i_load_places(f)
        except Exception as e:
            notes.append('could not read %s: %s' % (f, e)); continue
        notes.append(msg)
        for x in L:
            pl = i_place_from_point(G, x['xyz'], x.get('parts', []), tol, x['kind'], x.get('value'), x['source'],
                                    x.get('box'), x.get('keys'))
            if pl:
                pl['msg'] = x.get('msg')
                r = x.get('reuse')
                if r:   # the same place, frame and cameras as the earlier inspect (before/after, clean/faulted)
                    pl['reuse'] = r; pl['c'] = np.array(r['xyz'], float); pl['n'] = np.array(r['normal'], float)
                    pl['t'] = np.array(r['seam'], float); pl['bv'] = i_unit(np.cross(pl['n'], pl['t']))
                    pl['segment'] = r.get('segment', '1/1'); pl['ext'] = r.get('extent_m', pl['ext'])
                raw.append(pl)
    # 2. points
    for s in [x for x in (A.at or '').split(';') if x.strip()]:
        p = np.array([float(v) for v in s.split(',')])
        pl = i_place_from_point(G, p, [], tol, 'point', None, '--at')
        if pl:
            raw.append(pl)
    # 3. joints of named parts / relations / changed parts
    pairs = []
    if A.relations:
        rel = i_relations(A, plan)
        only = set(x.strip() for x in (A.parts or '').split(',') if x.strip())
        for p_, h_, k_ in rel:
            if only and p_ not in only and h_ not in only:
                continue
            for a in i_find_parts(G, p_):
                hosts = i_find_parts(G, h_)
                pairs.append((a, hosts, 'relation' + ('/' + k_ if k_ else '')))
        if not rel:
            notes.append('--relations: no relations recorded (parts.json %s, no kit3d_relations scene property): '
                         'joints found by proximity instead' % (plan_path or 'missing'))
            for a in i_find_parts(G, A.parts or ''):
                pairs.append((a, None, 'contact'))
    if A.part:
        for a in i_find_parts(G, A.part):
            pairs.append((a, None, 'contact'))
    if changed is not None:
        keys = set(changed)
        rel = i_relations(A, plan) if plan or A.relations else []
        for k in sorted(keys):
            a = G.by_key.get(k)
            if a is None:
                continue
            hosts = [h for p_, h_, _ in rel if p_ in (a['name'], a['part']) for h in i_find_parts(G, h_)]
            pairs.append((a, hosts or None, 'changed'))
    for a, hosts, kind in pairs:
        others = hosts if hosts else [d for d in G.near_box(a['lo'], a['hi'], tol) if d is not a]
        raw += i_joint_places(G, a, others, tol, kind, 'joint')
    # dedupe (same pair, centres within 2 cm), segment, cap
    places, seen = [], []
    for pl in raw:
        key = (pl['a']['key'], pl['b']['key'] if pl['b'] else None)
        if any(k == key and np.linalg.norm(pl['c'] - c) < 0.02 for k, c in seen):
            continue
        seen.append((key, pl['c']))
        places += [pl] if pl.get('reuse') else i_segments(pl, seg_max)
    def prio(pl):   # flagged places first, then joints of changed parts, then the ones hovering most
        st = pl['stats']
        hov = (st.get('median_mm') or 0) if st.get('hover_share', 0) > 0.5 else 0
        return (0 if pl['source'] != 'joint' else 1, 0 if pl['kind'] == 'changed' else 1, -hov, -st.get('hover_share', 0))
    places.sort(key=prio)
    flagged = [pl for pl in places if pl['source'] != 'joint']
    groups_ = {}
    for pl in places:
        if pl['source'] == 'joint':
            groups_.setdefault(pl['a']['key'], []).append(pl)
    rr, k = [], 0
    while any(k < len(g) for g in groups_.values()):   # round robin over parts, each part's worst joint first
        rr += sorted([g[k] for g in groups_.values() if k < len(g)], key=prio); k += 1
    places = flagged + rr
    skipped = places[A.max_places:]; places = places[:A.max_places]
    log('inspect: %d places (%d skipped over --max-places %d), tiles %dx%d, window <= %.3f m' % (
        len(places), len(skipped), A.max_places, tw, th, win_max))
    # pass 1, full asset: from which directions can each joint be seen from outside (the look tile needs light)
    setup_render(A, sc, tw, th)
    if stage.ground:
        stage.ground.hide_render = True; stage.ground.hide_viewport = True
    bpy.context.view_layer.update()
    outside = [None if pl.get('reuse') else i_outside(sc, G, pl, float(min(win_max, max(INSPECT_MIN_WIN, pl['ext'] * 1.35 + 0.02))) / 2)
               for pl in places]
    # pass 2, tinted chunk cut round each joint (Workbench: fast, cavity shading, colours per part)
    pcoll = new_coll('RT_inspect')
    for g in groups:
        g.hide_viewport = True; g.hide_render = True
    jobs, res, part_cov = [], [], {}
    for i, pl in enumerate(places, 1):
        pid = 'p%02d' % i
        r = pl.get('reuse')
        win = float(r['window_m']) if r else float(min(win_max, max(INSPECT_MIN_WIN, pl['ext'] * 1.35 + 0.02)))
        h = max(0.04, win * 0.62)
        for o in list(pcoll.objects):
            me = o.data; bpy.data.objects.remove(o); bpy.data.meshes.remove(me)
        i_proxies(G, pl, h, A.isolate, pcoll)
        bpy.context.view_layer.update()
        if r:
            V = {v['name']: v for v in r['views']}
            pick = [(V[k].get('clear', 0), V[k].get('az'), V[k].get('el'), np.array(V[k]['dir'], float))
                    for k in sorted(V) if k.startswith('view')]
            graze = (V['along'].get('clear', 0), V['along'].get('az'), V['along'].get('el'), np.array(V['along']['dir'], float))
        else:
            pick, graze = i_choose_views(sc, pl, h, nviews, outside[i - 1])
        tiles, views = [], []
        for j, (s, az, el, d) in enumerate(pick, 1):
            i_cam_pose(stage.cam, pl['c'], d, pl['t'], h * 2.2 + 0.05, win)
            p = i_render_wb(sc, os.path.join(out, 'tiles', '%s-v%d.png' % (pid, j)), light_dir=(-0.45, 0.45, 0.77))
            tiles.append(dict(path=p, label='view %d · %.2f mm/px' % (j, win / tw * 1000)))
            views.append(dict(name='view%d' % j, kind='tinted', dir=[round(float(x), 3) for x in d], az=az, el=el,
                              mmpx=round(win / tw * 1000, 3), clear=round(float(s), 2)))
        s, az, el, d = graze
        gw = float(min(win_max, max(0.04, win * 0.75)))
        hov = (pl['stats'].get('median_mm') or 0) / 1000 if pl['stats'].get('hover_share', 0) > 0.3 else 0
        if hov > 3e-4 and not r:   # measured stand-off picks the zoom (>= 12 px across the gap); never printed
            gw = float(max(0.04, min(gw, tw * hov / 12)))
        if r:
            gw = float(next(v for v in r['views'] if v['name'] == 'along')['mmpx']) * tw / 1000
        i_cam_pose(stage.cam, pl['c'], d, pl['t'], h * 2.2 + 0.05, gw)
        p = i_render_wb(sc, os.path.join(out, 'tiles', '%s-along.png' % pid), light_dir=(-0.45, 0.45, 0.77))
        tiles.append(dict(path=p, label='along the seam, low · %.2f mm/px' % (gw / tw * 1000)))
        views.append(dict(name='along', kind='tinted', dir=[round(float(x), 3) for x in d], az=az, el=el,
                          mmpx=round(gw / tw * 1000, 3), clear=round(float(s), 2)))
        if A.xray:
            s, az, el, d = pick[0]
            i_cam_pose(stage.cam, pl['c'], d, pl['t'], h * 2.2 + 0.05, win)
            p = i_render_wb(sc, os.path.join(out, 'tiles', '%s-xray.png' % pid), xray=True)
            tiles.append(dict(path=p, label='x-ray · %.2f mm/px' % (win / tw * 1000)))
            views.append(dict(name='xray', kind='xray', dir=[round(float(x), 3) for x in d], mmpx=round(win / tw * 1000, 3)))
        # the look: from the candidate seen best from outside (ties: the chunk's best view 1)
        if r:
            lv = next(v for v in r['views'] if v['name'] == 'look')
            look, lclear = np.array(lv['dir'], float), lv.get('seen_from_outside', 0)
        else:
            ko = int(np.argmax([outside[i - 1][k] + (0.01 if (INSPECT_CANDS[k][0], INSPECT_CANDS[k][1]) == pick[0][1:3] else 0)
                                for k in range(len(INSPECT_CANDS))]))
            look, lclear = i_dir(pl, *INSPECT_CANDS[ko]), outside[i - 1][ko]
        jobs.append(dict(pid=pid, pl=pl, tiles=tiles, views=views, win=win, h=h, look=look, look_clear=lclear, npick=len(pick),
                         same_as=r['id'] if r else None))
    # pass 3, the real look of every joint in one go (Cycles, materials, the state's light): no visibility change
    # between these renders, so Cycles keeps its scene (a toggle forces a full rebuild: 16 s a tile on a car)
    for o in list(pcoll.objects):
        me = o.data; bpy.data.objects.remove(o); bpy.data.meshes.remove(me)
    pcoll.hide_viewport = True; pcoll.hide_render = True
    for g in groups:
        g.hide_viewport = False; g.hide_render = False
    lamp = bpy.data.objects.new('RT_inspect_lamp', bpy.data.lights.new('RT_inspect_lamp', 'SUN'))
    stage.col.objects.link(lamp); lamp.data.angle = math.radians(8)
    lamp.data.energy = {'day': 1.2, 'dusk': 0.6, 'night': 0.3}[A.state]   # under a car or in a recess the state's sun never arrives
    bpy.context.view_layer.update()
    for jb in jobs:
        pl, d, win = jb['pl'], jb['look'], jb['win']
        i_cam_pose(stage.cam, pl['c'], d, pl['t'], jb['h'] + 0.01, win)
        stage.light_for(A.state, math.degrees(math.atan2(d[1], d[0])), under=bool(d[2] < -0.2))
        ld = i_unit(-d + 0.25 * pl['n'] + 0.2 * np.cross(d, pl['n']))   # a lamp just off the camera axis
        lamp.rotation_euler = Vector(ld.tolist()).to_track_quat('-Z', 'Y').to_euler()
        if stage.ground:
            stage.ground.hide_render = True
        p = render(sc, os.path.join(out, 'tiles', '%s-look.png' % jb['pid']))
        jb['tiles'].insert(jb['npick'] + 1, dict(path=p, label='as rendered, %s + lamp · %.2f mm/px' % (A.state, win / tw * 1000)))
        jb['views'].append(dict(name='look', kind='cycles-' + A.state, dir=[round(float(x), 3) for x in d],
                                mmpx=round(win / tw * 1000, 3), seen_from_outside=round(float(jb['look_clear']), 2)))
    for jb in jobs:
        pid, pl, win, h, tiles, views = jb['pid'], jb['pl'], jb['win'], jb['h'], jb['tiles'], jb['views']
        legend = ['orange: ' + pl['a']['key'], 'blue: ' + (pl['b']['key'] if pl['b'] else '(none)'),
                  'grey: neighbours (see-through)' if not A.isolate else 'others hidden',
                  'cut out to a %.0f cm box' % (h * 200), 'place %s, seam piece %s' % (pid, pl.get('segment', '1/1'))]
        sheet = os.path.join(out, '%s.jpg' % pid)
        i_compose(tiles, legend, sheet, cols)
        e = dict(id=pid, image=os.path.basename(sheet), xyz=[round(float(x), 4) for x in pl['c']], gltf_xyz=i_bl2gltf(pl['c']),
                 normal=[round(float(x), 3) for x in pl['n']], seam=[round(float(x), 3) for x in pl['t']],
                 parts=[pl['a']['name']] + ([pl['b']['name']] if pl['b'] else []),
                 instances=[pl['a']['key']] + ([pl['b']['key']] if pl['b'] else []),
                 plan_parts=[pl['a']['part'], pl['b']['part'] if pl['b'] else None],
                 kind=pl['kind'], source=pl['source'], value=pl.get('value'), msg=pl.get('msg'), segment=pl.get('segment', '1/1'),
                 extent_m=round(float(pl['ext']), 3), window_m=round(win, 3), mmpx=round(win / tw * 1000, 3),
                 measured=pl['stats'], views=views, tiles=[t['path'] for t in tiles], same_as=jb['same_as'])
        res.append(e)
        for k in e['instances']:
            part_cov.setdefault(k, dict(places=[], rendered=0))
            part_cov[k]['places'].append(pid); part_cov[k]['rendered'] += 1
        log('inspect %s %s | %s  %.2f mm/px  %s' % (pid, e['parts'], pl['kind'], e['mmpx'], pl['stats']))
    for pl in skipped:
        for k in [pl['a']['key']] + ([pl['b']['key']] if pl['b'] else []):
            part_cov.setdefault(k, dict(places=[], rendered=0))
            part_cov[k]['skipped'] = part_cov[k].get('skipped', 0) + 1
    J = dict(tool='render.py inspect', file=A.input, when=kyiv_now(), mmpx_limit=A.mmpx, tile_px=[tw, th],
             sheet_px=[INSPECT_W, INSPECT_H], state=A.state, isolate=A.isolate, xray=A.xray, joint_tol_m=tol,
             parts_json=plan_path, notes=notes, places=res,
             skipped=[dict(parts=[pl['a']['name']] + ([pl['b']['name']] if pl['b'] else []), xyz=[round(float(x), 4) for x in pl['c']],
                           kind=pl['kind'], measured=pl['stats']) for pl in skipped],
             coverage={k: dict(v, complete=not v.get('skipped')) for k, v in part_cov.items()},
             changed=changed if changed is not None else None, seconds=round(time.time() - t_start, 1))
    json.dump(J, open(os.path.join(out, 'inspect.json'), 'w'), indent=1)
    json.dump(dict(file=A.input, when=kyiv_now(), fingerprints=fp_now), open(os.path.join(out, 'fingerprints.json'), 'w'))
    for n in notes:
        log('inspect note:', n)
    print('RT_INSPECT %d places, %d sheets, %d skipped -> %s' % (len(res), len(res), len(skipped), os.path.join(out, 'inspect.json')), flush=True)
    return os.path.join(out, 'inspect.json')


def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print(__doc__)
        return
    A = parse(argv)
    A.hide_globs = [g for g in A.hide.split(',') if g]
    A.sky = 'auto'
    for k in ('input', 'before', 'after', 'original'):
        if getattr(A, k):
            setattr(A, k, os.path.abspath(getattr(A, k)))
    if A.versions:
        A.versions = ','.join('+'.join(os.path.abspath(x) for x in f.strip().split('+')) for f in A.versions.split(','))
    if A.files:
        A.files = ','.join('+'.join(os.path.abspath(x) for x in f.strip().split('+')) for f in A.files.split(','))
    if A.out:
        A.out = os.path.abspath(A.out)
    global TMP
    TMP = tempfile.mkdtemp(prefix='rt-render-')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if refuse_save not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(refuse_save)
    out = {'thumb': mode_thumb, 'sheet': mode_sheet, 'round': mode_round, 'versions': mode_versions,
           'beforeafter': mode_beforeafter, 'lodcmp': mode_lodcmp, 'inspect': mode_inspect}[A.mode](A)
    print('RT_DONE %s %.1fs (renders %.1fs, %d views) %s' % (A.mode, time.time() - T0, sum(TIMES), len(TIMES), out),
          flush=True)
    if EXIT_CODE:
        print('RT_FAIL exit %d: %s' % (EXIT_CODE, '; '.join(FAIL_REASONS)), flush=True)
        sys.exit(EXIT_CODE)


TMP = tempfile.gettempdir()

if __name__ == '__main__' or bpy is not None:
    if bpy is None:
        if len(sys.argv) > 2 and sys.argv[1] == '--compose':
            compose(json.load(open(sys.argv[2])))
        elif len(sys.argv) > 2 and sys.argv[1] == '--compose-inspect':
            compose_inspect(json.load(open(sys.argv[2])))
        else:
            print(__doc__)
    else:
        try:
            main()
        except SystemExit as e:
            if e.code not in (None, 0):
                print(e, flush=True)
                sys.exit(1 if not isinstance(e.code, int) else e.code)
        except Exception:   # Blender exits 0 after a traceback in --python; a check must not
            import traceback
            traceback.print_exc()
            print('RT_FAIL exit 2: crashed', flush=True)
            sys.exit(2)
