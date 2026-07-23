# Agent policy and threat model

## Objective

Oak Policy moves the unavailable private-repository ruleset behaviour into one
deterministic gateway used by coding agents:

```text
Claude Code ─┐
Codex ───────┤
OpenCode ────┤
Reasonix ────┼── oak-agent ── oak-git ── Git / GitHub
ZCode ───────┘
```

The model receives written guidance, but executable code makes the decision.
Harness adapters contain filenames and launch metadata only; they do not own
branch, check, review, or merge rules.

## Trust boundaries

Oak Policy protects operations performed through `oak-agent` and `oak-git`.

It blocks:

- raw pushes from an agent session;
- protected-branch pushes through `oak-git` or the installed hook;
- invalid branch names and closed or missing linked issues;
- force/non-fast-forward pushes through the supported route;
- direct `gh pr merge` and known GitHub merge API mutations from an agent session;
- merges with missing, pending, or failed checks;
- stale local/PR SHAs;
- branches behind their target;
- draft, unmergeable, or incorrectly targeted PRs;
- unresolved CodeRabbit or human review conversations.

It cannot stop:

- a merge clicked in GitHub's web UI;
- raw credentials used outside the launcher;
- `git push --no-verify` outside a guarded session;
- a harness deliberately launched without `oak-agent`;
- modification or removal of repository-local policy by an administrator.

GitHub's direct-push guard remains the detection layer for those out-of-band
changes. GitHub Pro rulesets remain the only way to move this boundary onto the
private GitHub repository itself.

## Policy resolution

The complete default is `policy/default.yaml`. A repository may add a partial
overlay at `.oak/policy.yaml`.

Example for a repository that intentionally has no `dev` branch:

```yaml
pull_requests:
  target_rules:
    - source: "hotfix/**"
      targets: [main]
    - source: "**"
      targets: [main]
```

Example for repositories where CodeRabbit is not installed yet:

```yaml
reviews:
  coderabbit:
    required: false
```

Example for a staged CI rollout:

```yaml
checks:
  required:
    - "*Lint*"
    - "*Test*"
```

The effective configuration is schema-checked:

```bash
oak-policy validate --show
```

## Installation

Install once:

```bash
python -m pip install "git+https://github.com/Boothey07/ci-workflows.git"
```

Install into a clone:

```bash
oak-policy install --harness all
```

That command:

1. installs `.oak/hooks/pre-push`;
2. sets the clone's `core.hooksPath` to `.oak/hooks`;
3. inserts one marker-managed policy block into `CLAUDE.md` or `AGENTS.md`;
4. preserves all existing project-specific instructions outside that block.

Instruction generation is idempotent. Codex, OpenCode, Reasonix, and ZCode may
share `AGENTS.md` without duplicating the policy.

## Agent launch

```bash
oak-agent claude-code
oak-agent codex
```

The configured harness commands can be overridden in `.oak/policy.yaml`.
`oak-agent` creates local runtime shims outside the tracked tree, puts them first
on `PATH`, records the harness identity, and replaces itself with the harness
process.

The shims allow ordinary read-only Git use and local commits, while redirecting
remote pushes and merges to `oak-git`.

## Review and merge state

`oak-git review-status --json` returns a portable result:

```json
{
  "ready": false,
  "operation": "merge",
  "blockers": [
    "check 'CI / Quality Gate' is still in_progress",
    "1 review conversation(s) remain unresolved"
  ],
  "details": {
    "pr": 42,
    "head_sha": "abc123"
  }
}
```

Every harness can use the same loop:

```text
push
  → wait for review
  → fix CodeRabbit and CI blockers
  → push again
  → repeat
  → merge through the gateway
```

`oak-git merge --dry-run` runs the complete evaluation without changing GitHub.

## Audit

Decisions are appended under the clone's Git metadata:

```text
.git/oak-policy/audit.jsonl
```

The log records time, operation, outcome, harness identity, process ID, and
decision details. It is local and untracked, so no repository grows generated
audit files or leaks local machine paths.

## Rollout

1. Release this repository as `v2`.
2. Install Oak Policy on the primary development machine.
3. Add the aggregate quality gate to one low-risk consumer repository.
4. Add a repository overlay matching its branch and CodeRabbit state.
5. Launch one harness through `oak-agent`.
6. Prove unsafe pushes and merges are denied.
7. Prove the CodeRabbit fix/push/re-review loop completes.
8. Roll out consumer CI and hooks repository by repository.
9. Keep the direct-push audit workflow on protected-by-convention branches.

Do not require `*Quality Gate*` in a repository until that repository reports
the check. A required check that never runs creates a permanently blocked
gateway rather than a useful control.
