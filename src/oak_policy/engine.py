"""Pure policy evaluation logic."""

from __future__ import annotations

import fnmatch
import re
from typing import Any

from .models import Check, Decision, PullRequestSnapshot


def matches_any(value: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(value, pattern) for pattern in patterns)


def is_protected(branch: str, policy: dict[str, Any]) -> bool:
    return matches_any(branch, policy["repository"]["protected_branches"])


def is_bot_branch(branch: str, policy: dict[str, Any]) -> bool:
    return matches_any(branch, policy["branches"].get("bot_patterns", []))


def branch_pattern(policy: dict[str, Any]) -> re.Pattern[str]:
    types = "|".join(re.escape(value) for value in policy["branches"]["types"])
    slug = policy["branches"]["slug_pattern"]
    issue = r"[0-9]+-" if policy["branches"]["require_issue"] else ""
    return re.compile(rf"^(?:{types})/{issue}{slug}$")


def validate_branch(
    branch: str,
    policy: dict[str, Any],
    *,
    allow_protected: bool = False,
) -> Decision:
    blockers: list[str] = []
    if is_protected(branch, policy) and not allow_protected:
        blockers.append(f"'{branch}' is protected; work must happen on a topic branch")
    elif (
        not is_protected(branch, policy)
        and not is_bot_branch(branch, policy)
        and not branch_pattern(policy).fullmatch(branch)
    ):
        expected = (
            "<type>/<issue>-<slug>" if policy["branches"]["require_issue"] else "<type>/<slug>"
        )
        blockers.append(f"branch '{branch}' does not match {expected}")
    return Decision(
        ready=not blockers,
        operation="validate-branch",
        blockers=blockers,
        details={"branch": branch},
    )


def allowed_targets(source: str, policy: dict[str, Any]) -> list[str]:
    for rule in policy["pull_requests"]["target_rules"]:
        if fnmatch.fnmatchcase(source, rule["source"]):
            return list(rule["targets"])
    return []


def validate_target(source: str, target: str, policy: dict[str, Any]) -> Decision:
    allowed = allowed_targets(source, policy)
    blockers = (
        []
        if target in allowed
        else [f"branch '{source}' may target {', '.join(allowed) or 'no branches'}, not '{target}'"]
    )
    return Decision(
        ready=not blockers,
        operation="validate-target",
        blockers=blockers,
        details={"source": source, "target": target, "allowed_targets": allowed},
    )


def _check_is_success(check: Check, policy: dict[str, Any]) -> bool:
    allowed = {value.upper() for value in policy["checks"]["success_conclusions"]}
    return check.status.upper() == "COMPLETED" and check.conclusion.upper() in allowed


def _required_check_blockers(checks: tuple[Check, ...], policy: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for pattern in policy["checks"]["required"]:
        matches = [check for check in checks if fnmatch.fnmatchcase(check.name, pattern)]
        if not matches:
            blockers.append(f"required check matching '{pattern}' is missing")
        elif not any(_check_is_success(check, policy) for check in matches):
            states = ", ".join(
                f"{check.name}={check.status}/{check.conclusion or 'PENDING'}" for check in matches
            )
            blockers.append(f"required check matching '{pattern}' is not successful ({states})")

    coderabbit = policy["reviews"]["coderabbit"]
    if coderabbit["required"]:
        for pattern in coderabbit["check_patterns"]:
            matches = [check for check in checks if fnmatch.fnmatchcase(check.name, pattern)]
            if not matches:
                blockers.append(f"CodeRabbit check matching '{pattern}' is missing")
            elif not any(_check_is_success(check, policy) for check in matches):
                blockers.append(f"CodeRabbit check matching '{pattern}' is not successful")
    return blockers


def evaluate_pull_request(
    snapshot: PullRequestSnapshot,
    policy: dict[str, Any],
) -> Decision:
    """Evaluate all merge conditions without performing side effects."""
    blockers: list[str] = []
    warnings: list[str] = []

    branch = validate_branch(snapshot.head_branch, policy)
    blockers.extend(branch.blockers)

    target = validate_target(snapshot.head_branch, snapshot.base_branch, policy)
    blockers.extend(target.blockers)

    pr_policy = policy["pull_requests"]
    if snapshot.state.upper() != "OPEN":
        blockers.append(f"PR #{snapshot.number} is {snapshot.state.lower()}, not open")
    if pr_policy["deny_drafts"] and snapshot.is_draft:
        blockers.append(f"PR #{snapshot.number} is still a draft")
    if pr_policy["require_mergeable"] and snapshot.mergeable.upper() != "MERGEABLE":
        blockers.append(
            f"PR #{snapshot.number} is not mergeable (GitHub reports {snapshot.mergeable})"
        )
    if pr_policy["require_current_head_sha"] and snapshot.head_sha != snapshot.local_sha:
        blockers.append("local HEAD is not the commit currently attached to the PR")
    if pr_policy["require_up_to_date"] and not snapshot.base_is_ancestor:
        blockers.append(f"branch is not up to date with '{snapshot.base_branch}'")

    blockers.extend(_required_check_blockers(snapshot.checks, policy))

    success = {value.upper() for value in policy["checks"]["success_conclusions"]}
    for check in snapshot.checks:
        status = check.status.upper()
        conclusion = check.conclusion.upper()
        if policy["checks"]["block_any_pending"] and status != "COMPLETED":
            blockers.append(f"check '{check.name}' is still {status.lower()}")
        elif (
            policy["checks"]["block_any_failure"]
            and status == "COMPLETED"
            and conclusion not in success
        ):
            result = conclusion.lower() or "without a result"
            blockers.append(f"check '{check.name}' concluded {result}")

    if policy["reviews"]["require_no_unresolved_threads"] and snapshot.unresolved_threads:
        blockers.append(f"{snapshot.unresolved_threads} review conversation(s) remain unresolved")

    # Preserve order while removing duplicate messages.
    blockers = list(dict.fromkeys(blockers))
    return Decision(
        ready=not blockers,
        operation="merge",
        blockers=blockers,
        warnings=warnings,
        details={
            "pr": snapshot.number,
            "url": snapshot.url,
            "state": snapshot.state,
            "mergeable": snapshot.mergeable,
            "head_branch": snapshot.head_branch,
            "base_branch": snapshot.base_branch,
            "head_sha": snapshot.head_sha,
            "base_is_ancestor": snapshot.base_is_ancestor,
            "checks": [
                {
                    "name": check.name,
                    "status": check.status,
                    "conclusion": check.conclusion,
                }
                for check in snapshot.checks
            ],
            "unresolved_threads": snapshot.unresolved_threads,
        },
    )
