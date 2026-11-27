#!/usr/bin/env bash
# poketactics-preview-update.service (timer, every 2 min): move the preview worktree
# to the newest main and restart the preview when it changed (docs/72).
set -euo pipefail
. "${POKETACTICS_PREVIEW_ENV:-$HOME/.config/poketactics-preview/env}"
cd "$PREVIEW_WORKTREE"
branch=${PREVIEW_BRANCH:-main}
timeout 60 git fetch --quiet origin "$branch" || echo "fetch failed; using the refs already here" >&2
target=$(git rev-parse "origin/$branch")
# A local main that already contains origin/main (committed on this machine, push
# still pending) is newer: follow it too.
local_ref=$(git rev-parse --verify -q "refs/heads/$branch" || true)
if [ -n "$local_ref" ] && git merge-base --is-ancestor "$target" "$local_ref"; then target=$local_ref; fi
current=$(git rev-parse HEAD)
[ "$current" = "$target" ] && exit 0
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "preview worktree has local edits; not updating" >&2
  exit 1
fi
git checkout --quiet --detach "$target"
echo "preview updated $(git rev-parse --short "$current") -> $(git rev-parse --short "$target")"
systemctl --user restart poketactics-preview.service
