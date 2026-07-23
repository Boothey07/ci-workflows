"""Git and GitHub operations guarded by the shared policy engine."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any, TextIO

from .audit import record
from .config import Policy, find_repo_root
from .engine import (
    allowed_targets,
    evaluate_pull_request,
    is_bot_branch,
    is_protected,
    validate_branch,
    validate_target,
)
from .errors import CommandError, PolicyDenied
from .models import Check, Decision, PullRequestSnapshot
from .process import run

ZERO_SHA = "0" * 40


def require_repo() -> Path:
    root = find_repo_root()
    if not root:
        raise CommandError("This operation must run inside a Git repository")
    return root


def current_branch(root: Path) -> str:
    branch = run(["git", "branch", "--show-current"], cwd=root).stdout.strip()
    if not branch:
        raise PolicyDenied("Detached HEAD is not permitted for agent Git operations")
    return branch


def local_sha(root: Path) -> str:
    return run(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()


def ensure_clean(root: Path) -> None:
    if run(["git", "status", "--porcelain"], cwd=root).stdout.strip():
        raise PolicyDenied("Working tree is not clean")


def _issue_number(branch: str) -> int | None:
    match = re.match(r"^[a-z][a-z0-9-]*/([0-9]+)-", branch)
    return int(match.group(1)) if match else None


def validate_issue(branch: str, policy: Policy, root: Path) -> Decision:
    if not policy["branches"]["require_issue"] or is_bot_branch(branch, policy):
        return Decision(ready=True, operation="validate-issue", details={"branch": branch})
    number = _issue_number(branch)
    if number is None:
        return Decision(
            ready=False,
            operation="validate-issue",
            blockers=[f"branch '{branch}' does not contain an issue number"],
        )
    result = run(
        ["gh", "issue", "view", str(number), "--json", "number,state,url"],
        cwd=root,
        check=False,
    )
    if result.returncode != 0:
        return Decision(
            ready=False,
            operation="validate-issue",
            blockers=[f"issue #{number} does not exist or cannot be read"],
        )
    issue = json.loads(result.stdout)
    blockers = [] if issue["state"].upper() == "OPEN" else [f"issue #{number} is not open"]
    return Decision(
        ready=not blockers,
        operation="validate-issue",
        blockers=blockers,
        details=issue,
    )


def validate_working_branch(policy: Policy, *, check_issue: bool = True) -> Decision:
    root = require_repo()
    branch = current_branch(root)
    decision = validate_branch(branch, policy)
    if decision.ready and check_issue:
        issue = validate_issue(branch, policy, root)
        decision.blockers.extend(issue.blockers)
        decision.details["issue"] = issue.details
        decision.ready = not decision.blockers
    return decision


def start_branch(branch: str, policy: Policy) -> None:
    root = require_repo()
    decision = validate_branch(branch, policy)
    if not decision.ready:
        raise PolicyDenied("Branch creation denied", decision.blockers)
    issue = validate_issue(branch, policy, root)
    if not issue.ready:
        raise PolicyDenied("Branch creation denied", issue.blockers)
    exists = run(
        ["git", "show-ref", "--verify", f"refs/heads/{branch}"],
        cwd=root,
        check=False,
    )
    if exists.returncode == 0:
        raise PolicyDenied(f"Local branch '{branch}' already exists")
    run(["git", "switch", "-c", branch], cwd=root)
    record("start", "allowed", {"branch": branch})


def push(policy: Policy, remote: str | None = None) -> None:
    root = require_repo()
    branch = current_branch(root)
    decision = validate_working_branch(policy)
    if not decision.ready:
        record("push", "denied", decision.as_dict())
        raise PolicyDenied("Push denied", decision.blockers)
    remote_name = remote or policy["repository"]["remote"]
    run(["git", "push", "--set-upstream", remote_name, f"HEAD:refs/heads/{branch}"], cwd=root)
    record("push", "allowed", {"branch": branch, "remote": remote_name, "sha": local_sha(root)})


def open_pull_request(
    policy: Policy,
    *,
    base: str | None,
    title: str | None,
    body: str | None,
    draft: bool,
) -> str:
    root = require_repo()
    branch = current_branch(root)
    branch_decision = validate_working_branch(policy)
    if not branch_decision.ready:
        raise PolicyDenied("Pull request denied", branch_decision.blockers)

    targets = allowed_targets(branch, policy)
    target = base or (targets[0] if targets else None)
    if not target:
        raise PolicyDenied(f"No pull-request target is configured for '{branch}'")
    target_decision = validate_target(branch, target, policy)
    if not target_decision.ready:
        raise PolicyDenied("Pull request denied", target_decision.blockers)

    existing = run(
        ["gh", "pr", "view", branch, "--json", "url,state"],
        cwd=root,
        check=False,
    )
    if existing.returncode == 0:
        data = json.loads(existing.stdout)
        if data["state"].upper() == "OPEN":
            return str(data["url"])

    args = ["gh", "pr", "create", "--base", target, "--head", branch]
    if title:
        args.extend(["--title", title])
    if body:
        args.extend(["--body", body])
    elif title:
        args.extend(["--body", ""])
    else:
        args.append("--fill")
    if draft:
        args.append("--draft")
    result = run(args, cwd=root)
    url = result.stdout.strip()
    record("pr-open", "allowed", {"branch": branch, "base": target, "url": url})
    return url


def _normalize_checks(raw_checks: list[dict[str, Any]]) -> tuple[Check, ...]:
    checks: list[Check] = []
    for item in raw_checks:
        name = str(item.get("name") or item.get("context") or "unnamed check")
        if "state" in item and "status" not in item:
            state = str(item.get("state") or "PENDING").upper()
            status = "COMPLETED" if state != "PENDING" else "PENDING"
            conclusion = "" if state == "PENDING" else state
        else:
            status = str(item.get("status") or "PENDING").upper()
            conclusion = str(item.get("conclusion") or "").upper()
        checks.append(Check(name=name, status=status, conclusion=conclusion))
    return tuple(checks)


def _repo_identity(root: Path) -> tuple[str, str]:
    value = run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
        cwd=root,
    )
    owner, repo = value.stdout.strip().split("/", 1)
    return owner, repo


def _unresolved_threads(root: Path, number: int) -> int:
    owner, repo = _repo_identity(root)
    query = """
      query($owner:String!, $repo:String!, $number:Int!, $cursor:String) {
        repository(owner:$owner, name:$repo) {
          pullRequest(number:$number) {
            reviewThreads(first:100, after:$cursor) {
              nodes { isResolved }
              pageInfo { hasNextPage endCursor }
            }
          }
        }
      }
    """
    count = 0
    cursor: str | None = None
    while True:
        args = [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-f",
            f"owner={owner}",
            "-f",
            f"repo={repo}",
            "-F",
            f"number={number}",
        ]
        if cursor:
            args.extend(["-f", f"cursor={cursor}"])
        data = json.loads(run(args, cwd=root).stdout)
        threads = data["data"]["repository"]["pullRequest"]["reviewThreads"]
        count += sum(not node["isResolved"] for node in threads["nodes"])
        page = threads["pageInfo"]
        if not page["hasNextPage"]:
            return count
        cursor = page["endCursor"]


def _base_is_ancestor(root: Path, remote: str, base: str, head: str) -> bool:
    result = run(
        ["git", "fetch", "--quiet", "--no-tags", remote, f"{base}:refs/remotes/{remote}/{base}"],
        cwd=root,
        check=False,
    )
    if result.returncode != 0:
        return False
    return (
        run(
            ["git", "merge-base", "--is-ancestor", f"refs/remotes/{remote}/{base}", head],
            cwd=root,
            check=False,
        ).returncode
        == 0
    )


def pull_request_snapshot(policy: Policy) -> PullRequestSnapshot:
    root = require_repo()
    raw = run(
        [
            "gh",
            "pr",
            "view",
            "--json",
            (
                "number,state,isDraft,mergeable,headRefName,baseRefName,"
                "headRefOid,statusCheckRollup,url"
            ),
        ],
        cwd=root,
    )
    data = json.loads(raw.stdout)
    head = local_sha(root)
    return PullRequestSnapshot(
        number=int(data["number"]),
        state=str(data["state"]),
        is_draft=bool(data["isDraft"]),
        mergeable=str(data["mergeable"]),
        head_branch=str(data["headRefName"]),
        base_branch=str(data["baseRefName"]),
        head_sha=str(data["headRefOid"]),
        local_sha=head,
        checks=_normalize_checks(data.get("statusCheckRollup") or []),
        unresolved_threads=_unresolved_threads(root, int(data["number"])),
        base_is_ancestor=_base_is_ancestor(
            root,
            policy["repository"]["remote"],
            str(data["baseRefName"]),
            head,
        ),
        url=str(data["url"]),
    )


def review_status(policy: Policy) -> Decision:
    decision = evaluate_pull_request(pull_request_snapshot(policy), policy)
    record("review-status", "allowed" if decision.ready else "denied", decision.as_dict())
    return decision


def wait_for_review(policy: Policy, timeout: int, interval: int = 15) -> Decision:
    deadline = time.monotonic() + timeout
    decision = review_status(policy)
    while not decision.ready and _waiting_can_help(decision) and time.monotonic() < deadline:
        time.sleep(min(interval, max(1, int(deadline - time.monotonic()))))
        decision = review_status(policy)
    return decision


def _waiting_can_help(decision: Decision) -> bool:
    if decision.details.get("unresolved_threads", 0):
        return False
    permanent_markers = (
        "is still a draft",
        "local HEAD",
        "not up to date",
        "review conversation",
        "may target",
        "does not match",
        "concluded failure",
        "concluded cancelled",
        "concluded timed_out",
    )
    if any(marker in blocker for blocker in decision.blockers for marker in permanent_markers):
        return False
    if decision.details.get("mergeable", "").upper() == "UNKNOWN":
        return True
    checks = decision.details.get("checks", [])
    if any(check["status"].upper() != "COMPLETED" for check in checks):
        return True
    return any("is missing" in blocker for blocker in decision.blockers)


def merge(policy: Policy, *, dry_run: bool = False) -> Decision:
    root = require_repo()
    ensure_clean(root)
    decision = review_status(policy)
    if not decision.ready:
        record("merge", "denied", decision.as_dict())
        raise PolicyDenied("Merge denied", decision.blockers)
    if dry_run:
        record("merge", "dry-run", decision.as_dict())
        return decision

    number = str(decision.details["pr"])
    method = f"--{policy['merge']['method']}"
    args = ["gh", "pr", "merge", number, method]
    if policy["merge"]["delete_branch"]:
        args.append("--delete-branch")
    run(args, cwd=root)
    record("merge", "allowed", decision.as_dict())
    return decision


def pre_push_hook(policy: Policy, stream: TextIO | None = None) -> Decision:
    """Evaluate refs received by Git's pre-push hook."""
    root = require_repo()
    blockers: list[str] = []
    input_stream = stream or sys.stdin
    for line in input_stream:
        fields = line.split()
        if len(fields) != 4:
            continue
        local_ref, local_ref_sha, remote_ref, remote_ref_sha = fields
        branch = remote_ref.removeprefix("refs/heads/")
        if is_protected(branch, policy):
            blockers.append(f"direct push to protected branch '{branch}' is prohibited")
            continue
        branch_decision = validate_branch(branch, policy)
        blockers.extend(branch_decision.blockers)
        if remote_ref_sha != ZERO_SHA and local_ref_sha != ZERO_SHA:
            is_fast_forward = (
                run(
                    ["git", "merge-base", "--is-ancestor", remote_ref_sha, local_ref_sha],
                    cwd=root,
                    check=False,
                ).returncode
                == 0
            )
            if not is_fast_forward:
                blockers.append(f"non-fast-forward push to '{branch}' is prohibited")
        if local_ref == "(delete)":
            blockers.append(f"deleting remote branch '{branch}' through raw Git is prohibited")
    decision = Decision(
        ready=not blockers,
        operation="pre-push",
        blockers=list(dict.fromkeys(blockers)),
    )
    record("pre-push", "allowed" if decision.ready else "denied", decision.as_dict())
    return decision
