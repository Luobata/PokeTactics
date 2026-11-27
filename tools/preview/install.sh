#!/usr/bin/env bash
# Install / refresh the always-on phone preview (docs/72) as systemd --user units.
#
#   tools/preview/install.sh            # defaults: http :8820, https :8821
#   PREVIEW_PORT=8830 PREVIEW_TLS_PORT=8831 tools/preview/install.sh
#
# Creates (idempotently):
#   <repo>/../PokeTactics-preview          detached worktree that follows main
#   ~/.local/share/poketactics-preview/    venv (Pillow), bin/ copies, saves/, certs/
#   ~/.config/poketactics-preview/env      settings read by run.sh / update.sh
#   ~/.config/systemd/user/poketactics-preview{,-update}.{service,timer}
# Needs `loginctl enable-linger $USER` once so the units start at boot without a login.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(git -C "$here" rev-parse --path-format=absolute --git-common-dir | sed 's#/\.git$##')
data=${PREVIEW_DATA:-$HOME/.local/share/poketactics-preview}
conf_dir=$HOME/.config/poketactics-preview
env_file=$conf_dir/env
units=$HOME/.config/systemd/user

if [ -f "$env_file" ]; then . "$env_file"; fi
PREVIEW_PORT=${PREVIEW_PORT:-8820}
PREVIEW_TLS_PORT=${PREVIEW_TLS_PORT-8821}
PREVIEW_HOST=${PREVIEW_HOST:-0.0.0.0}
PREVIEW_BRANCH=${PREVIEW_BRANCH:-main}
PREVIEW_WORKTREE=${PREVIEW_WORKTREE:-$(dirname "$repo")/PokeTactics-preview}
PREVIEW_SAVE_DIR=${PREVIEW_SAVE_DIR:-$data/saves}
PREVIEW_CERT_DIR=${PREVIEW_CERT_DIR:-$data/certs}
PREVIEW_PYTHON=${PREVIEW_PYTHON:-$data/venv/bin/python}

port_owner() { ss -Hltnp "sport = :$1" 2>/dev/null | head -1; }
running=$(systemctl --user is-active poketactics-preview.service 2>/dev/null || true)
for port in "$PREVIEW_PORT" ${PREVIEW_TLS_PORT:+"$PREVIEW_TLS_PORT"}; do
  owner=$(port_owner "$port")
  if [ -n "$owner" ] && [ "$running" != active ]; then
    echo "port $port is already in use: $owner" >&2
    exit 1
  fi
done

mkdir -p "$data/bin" "$PREVIEW_SAVE_DIR" "$conf_dir" "$units"
if [ ! -e "$PREVIEW_WORKTREE/.git" ]; then
  git -C "$repo" fetch --quiet origin "$PREVIEW_BRANCH" || true
  git -C "$repo" worktree add --detach "$PREVIEW_WORKTREE" "origin/$PREVIEW_BRANCH"
fi
if [ ! -x "$PREVIEW_PYTHON" ]; then
  python3 -m venv "$data/venv"
  "$data/venv/bin/python" -m pip install --quiet pillow
fi
"$PREVIEW_PYTHON" -c 'import PIL' || { echo "Pillow missing in $PREVIEW_PYTHON (set PIP_INDEX_URL and re-run)" >&2; exit 1; }

if [ -n "$PREVIEW_TLS_PORT" ]; then
  # Certificate names: every IPv4 of this machine (LAN + VPN), plus localhost.
  names=${PREVIEW_TLS_NAMES:-"$(hostname -I | tr ' ' '\n' | grep -E '^[0-9]+(\.[0-9]+){3}$' | tr '\n' ' ')localhost 127.0.0.1"}
  # shellcheck disable=SC2086
  "$here/make_cert.sh" "$PREVIEW_CERT_DIR" $names
fi

install -m 755 "$here/run.sh" "$here/update.sh" "$here/make_cert.sh" "$data/bin/"
cat > "$env_file" <<EOF
# PokeTactics phone preview (docs/72); read by run.sh and update.sh. Re-run install.sh after edits.
PREVIEW_PORT=$PREVIEW_PORT
PREVIEW_TLS_PORT=$PREVIEW_TLS_PORT
PREVIEW_HOST=$PREVIEW_HOST
PREVIEW_BRANCH=$PREVIEW_BRANCH
PREVIEW_WORKTREE=$PREVIEW_WORKTREE
PREVIEW_SAVE_DIR=$PREVIEW_SAVE_DIR
PREVIEW_CERT_DIR=$PREVIEW_CERT_DIR
PREVIEW_PYTHON=$PREVIEW_PYTHON
EOF

cat > "$units/poketactics-preview.service" <<EOF
[Unit]
Description=PokeTactics phone preview (follows $PREVIEW_BRANCH): http :$PREVIEW_PORT${PREVIEW_TLS_PORT:+ / https :$PREVIEW_TLS_PORT}
After=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
ExecStart=$data/bin/run.sh
Restart=always
RestartSec=3
TimeoutStopSec=10

[Install]
WantedBy=default.target
EOF
cat > "$units/poketactics-preview-update.service" <<EOF
[Unit]
Description=Move the PokeTactics preview worktree to the newest $PREVIEW_BRANCH and restart it

[Service]
Type=oneshot
ExecStart=$data/bin/update.sh
EOF
cat > "$units/poketactics-preview-update.timer" <<EOF
[Unit]
Description=Check for new $PREVIEW_BRANCH commits for the PokeTactics preview every 2 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=2min
RandomizedDelaySec=15s

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable poketactics-preview.service poketactics-preview-update.timer >/dev/null
systemctl --user restart poketactics-preview.service
systemctl --user start poketactics-preview-update.timer
loginctl show-user "$USER" -p Linger 2>/dev/null | grep -q yes \
  || echo "note: run 'loginctl enable-linger $USER' so the preview starts at boot" >&2
for _ in $(seq 1 40); do
  curl -fsS -o /dev/null "http://127.0.0.1:$PREVIEW_PORT/play" && break
  sleep 0.5
done
echo "preview http://$(hostname -I | awk '{print $1}'):$PREVIEW_PORT/play  (worktree $PREVIEW_WORKTREE @ $(git -C "$PREVIEW_WORKTREE" rev-parse --short HEAD))"
if [ -n "$PREVIEW_TLS_PORT" ]; then
  echo "https  https://$(hostname -I | awk '{print $1}'):$PREVIEW_TLS_PORT/play  (needs the CA from /ca.crt on the phone)"
fi
