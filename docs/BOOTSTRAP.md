# Automatic CI bootstrap

`scripts/bootstrap_repo.py` attaches the standard caller workflows to a
repository owned by the personal `Boothey07` account. It uses the GitHub API,
detects a simple project profile, and writes:

- `.github/workflows/ci.yml` for pull requests;
- `.github/workflows/post-merge.yml` for pushes to `main` or `dev`.
- optionally `.github/workflows/auto-merge.yml` for guarded owner-only merges.

The tool is dependency-free and defaults to GitHub-hosted runners. A private
repository can opt into the VPS runner with:

```sh
GH_TOKEN=... python scripts/bootstrap_repo.py Boothey07/example \
  --runner self-hosted \
  --runner-labels self-hosted,linux,x64,vps,example
```

Use `--dry-run` to inspect profile detection. Existing caller workflows are
left untouched unless `--force` is supplied.

Automatic merging is deliberately opt-in. Pass `--auto-merge` only after the
repository has the desired CI checks. A PR must be non-draft, owner-authored,
labelled `automerge`, and green for its current commit before it is squash
merged.

## Personal-account automation

The first rollout uses this tool explicitly against a small cohort. Once the
profiles are stable, run it from a VPS timer that periodically lists active
repositories and bootstraps only repositories missing the managed workflow.
That provides automatic onboarding without requiring an organization. A
GitHub App/webhook can replace the timer later without changing the bootstrap
logic.

The default is intentionally GitHub-hosted CI. Repository-level VPS runners
are opt-in because each personal-account repository needs its own runner
registration and self-hosted jobs must remain limited to private, trusted code.
