"""Generate identical policy guidance for every supported harness."""

from __future__ import annotations

from pathlib import Path

from .adapters import load_adapter
from .config import Policy, find_repo_root
from .errors import ConfigurationError

START = "<!-- oak-policy:start -->"
END = "<!-- oak-policy:end -->"


def render(policy: Policy) -> str:
    types = "|".join(policy["branches"]["types"])
    protected = ", ".join(f"`{value}`" for value in policy["repository"]["protected_branches"])
    required = ", ".join(f"`{value}`" for value in policy["checks"]["required"]) or "none"
    return f"""\
{START}
## Agent Git policy

This repository uses the Oak Policy gateway. These rules apply to every coding model and
harness.

- Use `oak-git` for branch creation, pushes, pull-request creation, review status, and merges.
- Do not run raw `git push`, `gh pr merge`, force pushes, admin bypasses, or `--no-verify`.
- Protected branches are {protected}.
- Topic branches must match `<type>/<issue>-<slug>` where type is one of `{types}`.
- Run repository-defined formatting, linting, builds, and tests before `oak-git push`.
- After each push, run `oak-git review-status --wait 900`.
- Address every actionable CodeRabbit or human review thread, push fixes, and repeat.
- Merge only with `oak-git merge`; a denied operation must be reported, never bypassed.
- Required CI check patterns: {required}.

Normal flow:

1. `oak-git start <type>/<issue>-<slug>`
2. Make and locally validate the change.
3. Commit using normal local Git commands.
4. `oak-git push`
5. `oak-git pr-open --title "<conventional commit title>"`
6. `oak-git review-status --wait 900`
7. Fix all blockers and repeat the review cycle.
8. `oak-git merge`
{END}
"""


def target_for_harness(policy: Policy, harness: str, root: Path) -> Path:
    config = policy["agents"]["harnesses"].get(harness)
    if not config:
        known = ", ".join(sorted(policy["agents"]["harnesses"]))
        raise ConfigurationError(f"Unknown harness '{harness}'. Known harnesses: {known}")
    adapter = load_adapter(config["adapter"])
    return root / config.get("instruction_file", adapter["instruction_file"])


def has_managed_block(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    return START in text and END in text


def install(policy: Policy, harness: str, root: Path | None = None) -> Path:
    repo = root or find_repo_root()
    if not repo:
        raise ConfigurationError("Instruction generation must run inside a Git repository")
    path = target_for_harness(policy, harness, repo)
    generated = render(policy).strip() + "\n"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if START in existing and END in existing:
        prefix, remainder = existing.split(START, 1)
        _, suffix = remainder.split(END, 1)
        content = prefix.rstrip() + "\n\n" + generated + suffix.lstrip()
    elif existing.strip():
        content = existing.rstrip() + "\n\n" + generated
    else:
        content = generated
    path.write_text(content, encoding="utf-8")
    return path
