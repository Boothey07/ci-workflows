# Working conventions

These apply to every active repo under `Boothey07`.

## Read this first: what is and isn't enforced

**Nothing here is enforced by GitHub today.** The account is on the Free plan and
every repo is private, and that combination disables branch protection *and*
rulesets:

```
GET repos/Boothey07/<any-private-repo>/rulesets
→ 403 "Upgrade to GitHub Pro or make this repository public to enable this feature."
```

So a direct `git push main` **cannot be blocked**. What exists instead:

| Layer | What it does | Can you bypass it? |
|---|---|---|
| CI checks on PRs | Run and report red/green | Yes — by not opening a PR |
| `pre-push` hook | Refuses pushes to `main`/`dev` locally | Yes — `git push --no-verify` |
| `guard.yml` | Files an issue after a direct push | It's detection, not prevention |
| **Rulesets** | **Would actually block** | **Requires GitHub Pro (~$4/mo)** |

Everything below is written so that buying Pro and running
`scripts/apply-rulesets.sh --apply` turns convention into enforcement with no
other changes. Until then this is a smoke alarm, not a lock.

## Branch model

```
topic branch → PR → dev (integration) → PR → main (production)
```

`main` is what deploys. `dev` is where work integrates. Only `hotfix/*` may
target `main` directly.

## Branch naming

```
<type>/<issue#>-<slug>
```

```
feat/42-injury-tracker
fix/17-readiness-delta
chore/8-bump-ruff
```

Types: `feat` `fix` `chore` `docs` `refactor` `test` `perf` `ci` `deps` `hotfix`

The issue number is not decoration — CI resolves it through the API and fails the
PR if the issue doesn't exist, is already closed, or is actually a PR. **This means
filing the issue before you branch.** It's the rule most likely to feel like
friction; it's also the one that makes the history searchable a year later.

Bot branches (`dependabot/*`, `coderabbitai/*`, `renovate/*`) are exempt.

## Commits and PR titles

Commits on your own topic branch are yours — go wild.

The **PR title** must be a Conventional Commit, because merges are squash-only and
the PR title becomes the commit message on `dev`/`main`:

```
feat(ios): add injury tracker
fix(api): report readiness delta only vs a true previous day
```

## Merging

Squash only. Linear history. Delete the branch after merge.

## The checks

| Check | Blocks? | Notes |
|---|---|---|
| PR hygiene | yes | branch name, PR title, linked issue |
| Secrets (gitleaks) | yes | GitHub's own scanning is public-repo-only without GHAS |
| Lint (`ruff check`) | yes | |
| Compile | yes | byte-compiles every module |
| Test | only where tests exist | see below |
| Format (`ruff format --check`) | advisory by default | `strict-format: true` to enforce |
| Types (`mypy`) | advisory | blocking `mypy` on untyped code trains you to ignore CI |
| Dependency audit | advisory | |

**On formatting:** `format` starts advisory for the same reason as `mypy`. The
existing repos are not `ruff format` clean — `bjj-health-app/api` alone had 3 files
that would be reformatted. A gate that is red from day one on pre-existing code
gets ignored, not fixed. The path to strict is: format the repo in one dedicated
commit, then set `strict-format: true` for that repo. Do it per-repo, when the
repo is quiet — not in the middle of a stack of open PRs, where reformatting
guarantees conflicts.

**On tests:** only four repos have a real suite — `system-configs` (47 test files),
`openclaw-workspace` (42), `briefing-suite` (25), `bjj-readiness-platform` (9).
Everywhere else, `run-tests` stays `false`. A green "Test" job that ran nothing is
worse than no job, because it reads as coverage.

`CodeQL` is absent on purpose: free for public repos only, GHAS pricing on private.

## Local setup

```bash
ci-workflows/scripts/install-hooks.sh --all ~/Developer
```

## Adding CI to a repo

Copy `templates/ci.yml` to `.github/workflows/ci.yml` and adjust `with:`. Consumers
pin `@v1` so one bad edit here can't break every repo at once.
