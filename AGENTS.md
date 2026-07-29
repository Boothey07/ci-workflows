<!-- oak-policy:start -->
## Agent Git policy

This repository uses the Oak Policy gateway. These rules apply to every coding model and
harness.

- Use `oak-git` for branch creation, pushes, pull-request creation, review status, and merges.
- Do not run raw `git push`, `gh pr merge`, force pushes, admin bypasses, or `--no-verify`.
- Protected branches are `main`, `master`, `dev`, `develop`, `release/**`.
- Topic branches must match `<type>/<issue>-<slug>` where type is one of `feat|fix|chore|docs|refactor|test|perf|ci|deps|hotfix`.
- Run repository-defined formatting, linting, builds, and tests before `oak-git push`.
- After each push, run `oak-git review-status --wait 900`.
- Address every actionable CodeRabbit or human review thread, push fixes, and repeat.
- Merge only with `oak-git merge`; a denied operation must be reported, never bypassed.
- Required CI check patterns: `*Quality Gate*`.

Normal flow:

1. `oak-git start <type>/<issue>-<slug>`
2. Make and locally validate the change.
3. Commit using normal local Git commands.
4. `oak-git push`
5. `oak-git pr-open --title "<conventional commit title>"`
6. `oak-git review-status --wait 900`
7. Fix all blockers and repeat the review cycle.
8. `oak-git merge`
<!-- oak-policy:end -->
