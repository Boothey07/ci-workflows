#!/usr/bin/env bash
#
# apply-rulesets.sh — the one-command enforcement flip.
#
# THIS SCRIPT DOES NOTHING USEFUL ON GITHUB FREE.
#
# Branch protection and rulesets are disabled on private repos unless the account
# is on Pro/Team/Enterprise. Every call below will 403 with:
#
#   "Upgrade to GitHub Pro or make this repository public to enable this feature."
#
# It is committed now, inert, so that the day Pro is purchased enforcement is a
# single command rather than a project. Run with --check first.
#
# Usage:
#   ./apply-rulesets.sh --check          # report what would happen; changes nothing
#   ./apply-rulesets.sh --apply          # create/update rulesets on every active repo
#   ./apply-rulesets.sh --apply --repo X # just one repo
#
set -euo pipefail

OWNER="Boothey07"
MODE="check"
ONLY_REPO=""

while [ $# -gt 0 ]; do
  case "$1" in
    --check) MODE="check" ;;
    --apply) MODE="apply" ;;
    --repo)  ONLY_REPO="${2:-}"; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

# Checks that must pass before a PR can merge. These names must match the job
# names produced by the reusable workflows, or the ruleset will wait forever on
# a check that never reports.
REQUIRED_CHECKS=(
  "PR hygiene"
  "Secrets"
  "Lint"
  "Format"
)

ruleset_payload() {
  local branch="$1"
  local contexts="" c
  for c in "${REQUIRED_CHECKS[@]}"; do
    contexts="$contexts{\"context\":\"$c\"},"
  done
  contexts="${contexts%,}"

  cat <<JSON
{
  "name": "protect-$branch",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["refs/heads/$branch"], "exclude": [] } },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "required_linear_history" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": true,
        "allowed_merge_methods": ["squash"]
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": [ $contexts ]
      }
    }
  ],
  "bypass_actors": []
}
JSON
}

# NOTE: bypass_actors is deliberately empty. As a solo dev the temptation is to
# add yourself; a ruleset you can bypass at will is decoration, not enforcement.

if [ -n "$ONLY_REPO" ]; then
  repos=("$ONLY_REPO")
else
  # No mapfile: macOS ships bash 3.2, where it doesn't exist.
  repos=()
  while IFS= read -r line; do
    [ -n "$line" ] && repos+=("$line")
  done < <(gh repo list "$OWNER" --limit 100 --no-archived \
    --json name,isFork --jq '.[] | select(.isFork==false) | .name' | sort)
fi

echo "mode=$MODE  repos=${#repos[@]}"
echo

fail=0
for repo in "${repos[@]}"; do
  for branch in main dev; do
    if ! gh api "repos/$OWNER/$repo/git/ref/heads/$branch" --silent 2>/dev/null; then
      printf '  %-28s %-5s  no such branch — skipped\n' "$repo" "$branch"
      continue
    fi

    if [ "$MODE" = "check" ]; then
      if out=$(gh api "repos/$OWNER/$repo/rulesets" --jq 'length' 2>&1); then
        printf '  %-28s %-5s  WOULD APPLY (existing rulesets: %s)\n' "$repo" "$branch" "$out"
      else
        printf '  %-28s %-5s  BLOCKED: %s\n' "$repo" "$branch" \
          "$(printf '%s' "$out" | grep -o 'Upgrade to GitHub [A-Za-z]*' | head -1 || echo 'see error')"
        fail=1
      fi
      continue
    fi

    existing=$(gh api "repos/$OWNER/$repo/rulesets" --jq \
      ".[] | select(.name==\"protect-$branch\") | .id" 2>/dev/null || true)

    if [ -n "$existing" ]; then
      if ruleset_payload "$branch" | gh api -X PUT "repos/$OWNER/$repo/rulesets/$existing" --input - --silent 2>/dev/null; then
        printf '  %-28s %-5s  updated\n' "$repo" "$branch"
      else
        printf '  %-28s %-5s  FAILED to update\n' "$repo" "$branch"; fail=1
      fi
    else
      if ruleset_payload "$branch" | gh api -X POST "repos/$OWNER/$repo/rulesets" --input - --silent 2>/dev/null; then
        printf '  %-28s %-5s  created\n' "$repo" "$branch"
      else
        printf '  %-28s %-5s  FAILED to create (Free plan? private repo?)\n' "$repo" "$branch"; fail=1
      fi
    fi
  done
done

echo
if [ $fail -ne 0 ] && [ "$MODE" = "check" ]; then
  cat <<'EOF'
Enforcement is unavailable on this plan.

  GitHub Free + private repo = no rulesets, no protected branches.
  Nothing can prevent a direct `git push main` today.

  Fix: buy GitHub Pro (~$4/mo), then re-run:  ./apply-rulesets.sh --apply
EOF
fi
exit 0
