from __future__ import annotations

import io
from pathlib import Path

from oak_policy.gateway import ZERO_SHA, _waiting_can_help, pre_push_hook
from oak_policy.models import Decision


def test_pre_push_blocks_protected_branch(
    policy: dict,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("oak_policy.gateway.require_repo", lambda: tmp_path)
    monkeypatch.setattr("oak_policy.gateway.record", lambda *args, **kwargs: None)
    stream = io.StringIO(f"refs/heads/main {'1' * 40} refs/heads/main {ZERO_SHA}\n")
    decision = pre_push_hook(policy, stream)
    assert not decision.ready
    assert decision.blockers == ["direct push to protected branch 'main' is prohibited"]


def test_pre_push_accepts_new_policy_compliant_topic_branch(
    policy: dict,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("oak_policy.gateway.require_repo", lambda: tmp_path)
    monkeypatch.setattr("oak_policy.gateway.record", lambda *args, **kwargs: None)
    branch = "feat/4-agent-git-policy-gateway"
    stream = io.StringIO(f"refs/heads/{branch} {'1' * 40} refs/heads/{branch} {ZERO_SHA}\n")
    decision = pre_push_hook(policy, stream)
    assert decision.ready


def test_pre_push_rejects_invalid_topic_branch(
    policy: dict,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("oak_policy.gateway.require_repo", lambda: tmp_path)
    monkeypatch.setattr("oak_policy.gateway.record", lambda *args, **kwargs: None)
    stream = io.StringIO(f"refs/heads/random {'1' * 40} refs/heads/random {ZERO_SHA}\n")
    decision = pre_push_hook(policy, stream)
    assert not decision.ready
    assert any("does not match" in blocker for blocker in decision.blockers)


def test_review_wait_stops_for_actionable_threads() -> None:
    decision = Decision(
        ready=False,
        operation="merge",
        blockers=["1 review conversation(s) remain unresolved"],
        details={"unresolved_threads": 1, "checks": []},
    )
    assert not _waiting_can_help(decision)


def test_review_wait_stops_for_draft_even_when_mergeability_is_unknown() -> None:
    decision = Decision(
        ready=False,
        operation="merge",
        blockers=["PR #5 is still a draft"],
        details={
            "mergeable": "UNKNOWN",
            "unresolved_threads": 0,
            "checks": [],
        },
    )
    assert not _waiting_can_help(decision)


def test_review_wait_continues_for_missing_or_pending_checks() -> None:
    missing = Decision(
        ready=False,
        operation="merge",
        blockers=["CodeRabbit check matching '*CodeRabbit*' is missing"],
        details={"unresolved_threads": 0, "checks": []},
    )
    pending = Decision(
        ready=False,
        operation="merge",
        blockers=["check 'Quality Gate' is still in_progress"],
        details={
            "unresolved_threads": 0,
            "checks": [{"name": "Quality Gate", "status": "IN_PROGRESS", "conclusion": ""}],
        },
    )
    assert _waiting_can_help(missing)
    assert _waiting_can_help(pending)
