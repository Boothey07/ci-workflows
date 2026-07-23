from __future__ import annotations

from dataclasses import replace

from oak_policy.engine import (
    allowed_targets,
    evaluate_pull_request,
    validate_branch,
    validate_target,
)
from oak_policy.models import Check, PullRequestSnapshot


def good_snapshot() -> PullRequestSnapshot:
    return PullRequestSnapshot(
        number=42,
        state="OPEN",
        is_draft=False,
        mergeable="MERGEABLE",
        head_branch="feat/4-agent-git-policy-gateway",
        base_branch="dev",
        head_sha="abc123",
        local_sha="abc123",
        checks=(
            Check(name="CI / Quality Gate", status="COMPLETED", conclusion="SUCCESS"),
            Check(name="CodeRabbit", status="COMPLETED", conclusion="SUCCESS"),
        ),
        unresolved_threads=0,
        base_is_ancestor=True,
        url="https://github.com/example/repo/pull/42",
    )


def test_branch_policy_accepts_existing_convention(policy: dict) -> None:
    assert validate_branch("feat/4-agent-git-policy-gateway", policy).ready
    assert validate_branch("hotfix/91-api-outage", policy).ready


def test_branch_policy_rejects_protected_and_unrecognised_branches(policy: dict) -> None:
    assert not validate_branch("main", policy).ready
    assert not validate_branch("feature/no-issue", policy).ready
    assert not validate_branch("fix/missing-issue", policy).ready


def test_bot_branches_are_exempt(policy: dict) -> None:
    assert validate_branch("dependabot/pip/ruff-1.0", policy).ready


def test_target_rules_match_branch_model(policy: dict) -> None:
    assert allowed_targets("feat/4-agent-git-policy-gateway", policy) == ["dev", "develop"]
    assert validate_target("feat/4-agent-git-policy-gateway", "dev", policy).ready
    assert validate_target("hotfix/91-api-outage", "main", policy).ready
    assert not validate_target("feat/4-agent-git-policy-gateway", "main", policy).ready


def test_merge_decision_accepts_fully_green_pr(policy: dict) -> None:
    decision = evaluate_pull_request(good_snapshot(), policy)
    assert decision.ready
    assert decision.blockers == []


def test_merge_decision_blocks_missing_required_check(policy: dict) -> None:
    snapshot = replace(
        good_snapshot(),
        checks=(Check(name="CodeRabbit", status="COMPLETED", conclusion="SUCCESS"),),
    )
    decision = evaluate_pull_request(snapshot, policy)
    assert not decision.ready
    assert any("Quality Gate" in blocker and "missing" in blocker for blocker in decision.blockers)


def test_merge_decision_blocks_failure_pending_stale_and_threads(policy: dict) -> None:
    snapshot = replace(
        good_snapshot(),
        head_sha="new",
        local_sha="old",
        checks=(
            Check(name="CI / Quality Gate", status="COMPLETED", conclusion="FAILURE"),
            Check(name="CodeRabbit", status="IN_PROGRESS", conclusion=""),
        ),
        unresolved_threads=2,
        base_is_ancestor=False,
    )
    decision = evaluate_pull_request(snapshot, policy)
    assert not decision.ready
    combined = "\n".join(decision.blockers)
    assert "local HEAD" in combined
    assert "not up to date" in combined
    assert "failure" in combined
    assert "still in_progress" in combined
    assert "2 review conversation(s)" in combined


def test_merge_decision_blocks_draft_and_wrong_target(policy: dict) -> None:
    snapshot = replace(good_snapshot(), is_draft=True, base_branch="main")
    decision = evaluate_pull_request(snapshot, policy)
    assert not decision.ready
    assert any("draft" in blocker for blocker in decision.blockers)
    assert any("may target" in blocker for blocker in decision.blockers)
