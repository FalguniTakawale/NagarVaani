#!/usr/bin/env bash
# Auto-commit and push any pending changes in the NagarVaani repo.
# Runs as a Stop hook after each turn. Silently does nothing if there is
# nothing to commit, so it's safe to fire every turn.
set -euo pipefail
cd "/Users/falgunitakawale/Desktop/projects/NagarVaani"

git add -A

# Nothing staged relative to HEAD — no-op.
if git diff --cached --quiet; then
  exit 0
fi

git commit -q -m "Auto-commit: session changes ($(date '+%Y-%m-%d %H:%M'))" \
  -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"

if git push -q 2>/tmp/nv-autopush-err.log; then
  echo '{"systemMessage": "Auto-committed and pushed changes to GitHub."}'
else
  echo '{"systemMessage": "Auto-committed changes locally, but push to GitHub failed — check network/auth (see /tmp/nv-autopush-err.log)."}'
fi
