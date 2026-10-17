#!/usr/bin/env bash
# Build the web UI once, then serve the dashboard on http://127.0.0.1:8152/ (loopback only).
set -e
cd "$(dirname "$0")"
ASSETS="${ASSETS:-$HOME/3d-assets}"
[ -f config/sources.json ] || sed "s#__ASSETS__#$ASSETS#g" config/sources.example.json > config/sources.json
[ -d web/dist ] || (cd web && npm ci && npx vite build)
BLENDER="${BLENDER:-$(command -v blender || echo /snap/bin/blender)}" exec node server.mjs
