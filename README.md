# ci-workflows

Central reusable GitHub Actions workflows for the `Boothey07` repos.

**This repo is public on purpose.** It holds only workflow YAML — no secrets.
Sharing reusable workflows *out of* a private repo on the Free plan runs into
access-policy friction; public sidesteps it entirely and costs nothing.

## Use it

```yaml
name: CI
on:
  pull_request:
    branches: [main, dev]

jobs:
  hygiene:
    uses: Boothey07/ci-workflows/.github/workflows/pr-hygiene.yml@v1.4
  secrets:
    uses: Boothey07/ci-workflows/.github/workflows/secrets.yml@v1.4
  python:
    uses: Boothey07/ci-workflows/.github/workflows/python-ci.yml@v1.4
    with:
      paths: "api/"
      python-versions: '["3.11","3.12","3.13"]'
```

**Pin `@v1.4`.** Pinning consumers to a moving `main` means one bad edit here
breaks every repo at once.

### Tag history — read before pinning

Moving or deleting a published tag is a force-push, so bad tags are superseded
rather than rewritten. They are left in place deliberately; this table is the
record.

| Tag | Use? | Why |
|---|---|---|
| `v1` | ❌ | gitleaks 403s — a reusable workflow does not inherit the caller's `permissions:` |
| `v1.1` | ⚠️ | Works, but every Lint/Format job is mislabelled "(advisory)" whether blocking or not |
| `v1.2` | ⚠️ | Adds `strict-lint`; same mislabelling |
| `v1.3` | ❌ | **Junk — identical to v1.2.** Tagged from the wrong commit after a failed commit. Ignore. |
| `v1.4` | ✅ | Correct labels; `apply-rulesets.sh` requires check names that actually report |

## What's here

| Workflow | Purpose |
|---|---|
| `python-ci.yml` | ruff lint + format, byte-compile matrix, optional pytest/coverage, advisory mypy + pip-audit |
| `node-ci.yml` | npm install / lint / build / test |
| `pr-hygiene.yml` | branch naming, Conventional-Commit PR title, verified linked issue |
| `secrets.yml` | gitleaks (GitHub's own scanning is public-only without GHAS) |
| `guard.yml` | files an issue on a direct push to `main`/`dev` — **detection, not prevention** |

| Script | Purpose |
|---|---|
| `scripts/apply-rulesets.sh` | The enforcement flip. **Inert on Free** — every call 403s. Run `--check` to see. |
| `scripts/install-hooks.sh` | Installs the `pre-push` speed bump locally |

See [CONTRIBUTING.md](CONTRIBUTING.md) for the conventions and an honest account
of what is and isn't actually enforced.

## Runners

`runs-on` defaults to `["ubuntu-latest"]`. Where a self-hosted runner is
registered for a repo, pass `runs-on: '["self-hosted","linux","vps"]'` to stay off
billed minutes.

Private repos get 2000 Actions minutes/month and **macOS bills at 10×**, so iOS
builds are the expensive ones. Note that personal accounts cannot have
account-level runners — GitHub scopes them per-repo unless you use an
organization, so each repo needs its own registration.

<!-- guard negative test -->
