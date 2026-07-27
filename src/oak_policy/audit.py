"""Append-only local audit records for gateway decisions."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import find_repo_root
from .process import run


def _audit_path(root: Path) -> Path:
    git_path = run(["git", "rev-parse", "--git-path", "oak-policy"], cwd=root).stdout.strip()
    directory = Path(git_path)
    if not directory.is_absolute():
        directory = root / directory
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "audit.jsonl"


def record(operation: str, outcome: str, details: dict[str, Any]) -> None:
    """Record a policy decision without adding generated files to the repository."""
    root = find_repo_root()
    if not root:
        return
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "operation": operation,
        "outcome": outcome,
        "harness": os.environ.get("OAK_HARNESS", "direct"),
        "pid": os.getpid(),
        "details": details,
    }
    path = _audit_path(root)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True) + "\n")
