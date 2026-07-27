"""Repository installation helpers."""

from __future__ import annotations

from pathlib import Path

from .config import Policy, find_repo_root
from .errors import ConfigurationError
from .process import run


def install_hook(policy: Policy, root: Path | None = None) -> Path:
    repo = root or find_repo_root()
    if not repo:
        raise ConfigurationError("Hook installation must run inside a Git repository")
    hook_dir = repo / ".oak" / "hooks"
    hook_dir.mkdir(parents=True, exist_ok=True)
    hook = hook_dir / "pre-push"
    hook.write_text(
        "#!/usr/bin/env sh\n"
        "# Managed by oak-policy. Do not duplicate policy logic here.\n"
        'exec oak-git hook pre-push "$@"\n',
        encoding="utf-8",
    )
    hook.chmod(0o755)
    run(["git", "config", "--local", "core.hooksPath", ".oak/hooks"], cwd=repo)
    return hook
