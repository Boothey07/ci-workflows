# ci-workflows

Central CI and agent Git policy for the `Boothey07` repositories.

**This repository is public on purpose.** It contains reusable workflow and
policy code, never repository secrets. Sharing reusable workflows *out of* a
private repository on the Free plan creates access-policy friction; public
sidesteps it and costs nothing.

It has two related parts:

```text
GitHub Actions                    Oak Policy
├── lint/build/test/security      ├── one YAML policy
├── PR hygiene                    ├── oak-git guarded operations
├── CodeRabbit status             ├── oak-agent process guards
└── aggregate Quality Gate        └── shared harness instructions
```

GitHub remains the only forge. Oak Policy provides deterministic guardrails for
Claude Code, Codex, OpenCode, Reasonix, ZCode, terminals, and IDEs without
duplicating rules in each harness.

## Install Oak Policy

Python 3.11+, Git, and an authenticated GitHub CLI are required.

```bash
python -m pip install "git+https://github.com/Boothey07/ci-workflows.git"
cd /path/to/repository
oak-policy install --harness all
oak-policy doctor
```

Then launch a supported agent through the common boundary:

```bash
oak-agent claude-code
oak-agent codex
oak-agent opencode
oak-agent reasonix
oak-agent zcode
```

The launcher:

- generates the same managed instruction block for the selected harness;
- places guarded `git` and `gh` shims first on that process's `PATH`;
- blocks raw pushes and raw GitHub merges;
- directs all binding decisions to `oak-git`;
- leaves read-only Git/GitHub commands and local commits available.

The normal flow is:

```bash
oak-git start feat/42-description
# edit, format, lint, test, git add, git commit
oak-git push
oak-git pr-open --title "feat(scope): description"
oak-git review-status --wait 900
oak-git merge
```

`oak-git merge` refuses unless the current PR is open, non-draft, mergeable,
current, up to date, green, reviewed by CodeRabbit, and free of unresolved
review threads. It never uses `--admin`.

See [Agent policy and threat model](docs/agent-policy.md) for configuration,
failure behaviour, bypass boundaries, and rollout.

## What's here

| Workflow | Purpose |
|---|---|
| `python-ci.yml` | ruff lint + format, byte-compile matrix, optional pytest/coverage, advisory mypy + pip-audit |
| `node-ci.yml` | npm install / lint / build / test |
| `pr-hygiene.yml` | branch naming, Conventional-Commit PR title, verified linked issue |
| `secrets.yml` | gitleaks (GitHub's own scanning is public-only without GHAS) |
| `quality-gate.yml` | collapses named upstream jobs into one required result |
| `guard.yml` | files an issue on a direct push to `main` or `dev` — detection, not prevention |

| Component | Purpose |
|---|---|
| `policy/default.yaml` | single source of policy for CI, Git operations, and harness guidance |
| `oak-policy` | validates policy, installs hooks, generates instructions, and diagnoses setup |
| `oak-git` | guarded branch, push, PR, review-status, and merge commands |
| `oak-agent` | process-level launcher and raw `git push`/`gh pr merge` guard |
| `.oak/policy.yaml` | optional per-repository overlay |
| `scripts/apply-rulesets.sh` | enforcement flip; inert on Free because its calls return 403 |
| `scripts/install-hooks.sh` | legacy speed bump; `oak-policy install` supersedes it |

See [CONTRIBUTING.md](CONTRIBUTING.md) for the conventions and an honest account
of what is and is not actually enforced.

## Add CI to a repository

Copy `templates/ci.yml` to `.github/workflows/ci.yml`, adjust the language inputs,
and pin a released tag. `v1.1` is the stable legacy workflow release; the Oak
Policy and aggregate-gate release will be tagged `v2` after validation.

The important caller-side aggregation is:

```yaml
quality-gate:
  name: Quality Gate
  if: always()
  needs: [hygiene, secrets, python]
  uses: Boothey07/ci-workflows/.github/workflows/quality-gate.yml@v2
  with:
    results: ${{ toJSON(needs) }}
    required-jobs: hygiene,secrets,python
```

Pin a tag rather than moving `main`; one bad central edit must not break every
consumer at once.

## Runners

`runs-on` defaults to `["ubuntu-latest"]`. Where a self-hosted runner is
registered for a repository, pass
`runs-on: '["self-hosted","linux","vps"]'` to stay off billed minutes.

Private repositories get an included Actions allowance and macOS jobs use a
higher multiplier, so iOS builds are the expensive ones. Personal accounts
cannot have account-level runners: GitHub scopes them per repository unless an
organization owns them.
