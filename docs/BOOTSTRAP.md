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

The scheduled `Synchronize managed repositories` workflow keeps the explicit
repository set in the `MANAGED_REPOSITORIES` secret synchronized in a single
commit per repository. Private repositories created after the configured
cutover date are enrolled automatically.

The central reviewer service provisions missing repository-scoped VPS runners
for managed private repositories and owns review, repair, readiness, and merge
progression. Repository Actions are limited to CI and post-merge validation,
which avoids duplicate review/merge runs and notification spam.
