# Asset dashboard (127.0.0.1:8152)

The viewer the `3d-asset-making` skill hands assets to: a grid of fresh renders of every GLB and `.blend` in the
folders you list, and a three.js inspector on click (geometry check, materials, parts, versions side by side, the
maker and API cost from the asset's `asset.json` `made_with` record).

```bash
ASSETS=~/3d-assets ./start.sh      # first run: writes config/sources.json, builds web/, serves http://127.0.0.1:8152/
```

Needs Node 22+, Blender on `PATH` (or `BLENDER=/path/to/blender`), Python 3 with numpy for the geometry check.

| Part | File | Owns |
|---|---|---|
| Sources | `config/sources.json` | every asset folder; add an entry and it renders. A `*` path segment expands to each match and becomes the group |
| Server | `server.mjs` (no npm deps) | scan on request (no background load), render/export queue, `/api/catalog`, path-guarded file serving |
| Thumbnails | `blender/render_glb.py` | Workbench three-quarter view |
| .blend → GLB | `blender/export_blend.py` | on click, cached by code + input stamp |
| Geometry check | `integrity.mjs` | runs `../../3d-modelling/scripts/mesh_integrity.py` on open |
| Web UI | `web/src/` | Vite + React + TS, built to `web/dist` |

`stubs/` stand in for two files a game supplies: its picture-effects list (`stubs/picture-effects.json`) and its
shader-library binder (`stubs/shader-library/`). Point `web/vite.config.ts` at your own to use them.

Optional: `PORT`, `HOST` (default 127.0.0.1; keep it on loopback or a LAN address), `SOURCES` (another config file),
`CACHE` (render/export cache, default `cache/`), `PRICES_URL` (price table for the Runs view, see
`../references/TOOLS.md`). Only the code is published: no assets, renders, runs or configs.
