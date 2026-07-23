"""Structured inputs and outputs for policy decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    conclusion: str


@dataclass(frozen=True)
class PullRequestSnapshot:
    number: int
    state: str
    is_draft: bool
    mergeable: str
    head_branch: str
    base_branch: str
    head_sha: str
    local_sha: str
    checks: tuple[Check, ...] = ()
    unresolved_threads: int = 0
    base_is_ancestor: bool = True
    url: str = ""


@dataclass
class Decision:
    ready: bool
    operation: str
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
