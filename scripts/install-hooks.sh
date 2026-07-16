#!/usr/bin/env bash
# Install the pre-push hook into one repo, or every active repo under a directory.
#
#   ./install-hooks.sh /path/to/repo
#   ./install-hooks.sh --all /Users/tom/Developer
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="$HERE/hooks/pre-push"

install_one() {
  local repo="$1"
  [ -d "$repo/.git" ] || return 0
  install -m 0755 "$HOOK" "$repo/.git/hooks/pre-push"
  echo "  installed: $repo"
}

if [ "${1:-}" = "--all" ]; then
  root="${2:?usage: install-hooks.sh --all <dir>}"
  # -print -prune so we don't descend into a repo's own submodules/vendor dirs.
  find "$root" -maxdepth 3 -type d -name .git -print | while read -r g; do
    install_one "$(dirname "$g")"
  done
else
  install_one "${1:?usage: install-hooks.sh <repo>}"
fi
