# Automatic CI bootstrap

`scripts/bootstrap_repo.py` attaches the standard caller workflows to a
repository owned by the personal `Boothey07` account. It uses the GitHub API,
detects a simple project profile, and writes:

- `.github/workflows/ci.yml` for pull requests;
- `.github/workflows/post-merge.yml` for pushes to `main` or `dev`.

The tool is dependency-free and defaults to GitHub-hosted runners. A private
repository can opt into the VPS runner with:

```sh
GH_TOKEN=... python scripts/bootstrap_repo.py Boothey07/example \
  --runner self-hosted \
  --runner-labels self-hosted,linux,x64,vps,example
```

Use `--dry-run` to inspect profile detection. Existing caller workflows are
left untouched unless `--force` is supplied.

## Personal-account automation

The scheduled `Synchronize managed repositories` workflow keeps the explicit
repository set in the `MANAGED_REPOSITORIES` secret synchronized in a single
commit per repository. Private repositories created after the configured
cutover date are enrolled automatically.

The central reviewer service provisions missing repository-scoped VPS runners
for managed private repositories and owns review, repair, readiness, and merge
progression through the GitHub App. Repository Actions are deliberately limited
to CI and post-merge validation; no elevated `pull_request_target` caller is
installed in consumer repositories.
