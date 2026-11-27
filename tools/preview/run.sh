#!/usr/bin/env bash
# systemd ExecStart for poketactics-preview.service (docs/72). Installed as a copy
# under ~/.local/share/poketactics-preview/bin so it never changes under a checkout.
set -euo pipefail
. "${POKETACTICS_PREVIEW_ENV:-$HOME/.config/poketactics-preview/env}"
cd "$PREVIEW_WORKTREE"
args=(tools/acceptance/server.py --host "$PREVIEW_HOST" --port "$PREVIEW_PORT")
# HTTPS needs a server.py that knows --tls-port (docs/72); older commits run http only.
if [ -n "${PREVIEW_TLS_PORT:-}" ] && [ -s "$PREVIEW_CERT_DIR/server-chain.crt" ] \
   && grep -q -- '--tls-port' tools/acceptance/server.py; then
  args+=(--tls-port "$PREVIEW_TLS_PORT" --tls-cert "$PREVIEW_CERT_DIR/server-chain.crt"
         --tls-key "$PREVIEW_CERT_DIR/server.key" --ca-cert "$PREVIEW_CERT_DIR/ca.crt")
fi
# Android shell APK download (/app, docs/73), on server.py versions that know --app-dir.
if [ -n "${PREVIEW_APP_DIR:-}" ] && grep -q -- '--app-dir' tools/acceptance/server.py; then
  args+=(--app-dir "$PREVIEW_APP_DIR")
fi
export POKETACTICS_SAVE_DIR="$PREVIEW_SAVE_DIR" PYTHONUNBUFFERED=1
echo "preview: $(git rev-parse --short HEAD) $(git log -1 --format=%s | cut -c1-80)"
exec "$PREVIEW_PYTHON" "${args[@]}"
