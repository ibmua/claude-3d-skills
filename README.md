# Claude Code skills for 3D asset making

Two [Claude Code skills](https://docs.claude.com/en/docs/claude-code/skills) and an asset dashboard:

- [`3d-asset-making/`](3d-asset-making/SKILL.md): the whole job of making a 3D asset end to end (reuse search, plan in
  numbers, build with Blender, day/night looks, game LODs judged in pixels, maker and cost record). Tools in
  `scripts/`, a Shader Lab in `shaderlab/`, references in `references/`.
- [`3d-modelling/`](3d-modelling/SKILL.md): keeping every version of a model one sound object: the kit3d part library
  (place by relation, pass by measurement), a Python + numpy `.glb` checker (floating parts, open edges, flipped and
  blinking faces, LOD loss) and look measures.
- [`3d-asset-making/dashboard/`](3d-asset-making/dashboard/README.md): a local asset dashboard (fresh renders of every
  GLB and `.blend` in your folders, a three.js inspector, runs with live API cost):
  `ASSETS=~/3d-assets ./start.sh` → http://127.0.0.1:8152/.

Install: copy both skill folders into `~/.claude/skills/`. Needs Blender 5.2, Python 3 with numpy, Node 22+.
Default launch split: plan with Opus at effort `xhigh`, then model in a fresh Opus worker at effort `low`.

A few parts call into a project's own tools (Blender bridge launcher, vision reviewer, shader library, the game's
switch distances and material contract): see "Project hooks" at the end of `3d-asset-making/SKILL.md`.
Published from a private skills collection; no assets are included.
