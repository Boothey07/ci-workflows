"""Command-line interfaces for oak-policy and oak-git."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

from .config import default_policy_path, find_repo_root, load_policy
from .errors import OakPolicyError, PolicyDenied
from .gateway import (
    merge,
    open_pull_request,
    pre_push_hook,
    push,
    review_status,
    start_branch,
    validate_working_branch,
    wait_for_review,
)
from .install import install_hook
from .instructions import install as install_instructions
from .instructions import render
from .models import Decision
from .process import run


def _print_decision(decision: Decision, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(decision.as_dict(), indent=2, sort_keys=True))
        return
    label = "READY" if decision.ready else "BLOCKED"
    print(f"{decision.operation.upper()}: {label}")
    for blocker in decision.blockers:
        print(f"  - {blocker}")
    for warning in decision.warnings:
        print(f"  ! {warning}")
    if decision.details.get("url"):
        print(f"  {decision.details['url']}")


def _load(args: argparse.Namespace) -> dict[str, Any]:
    explicit = Path(args.policy).resolve() if getattr(args, "policy", None) else None
    return load_policy(explicit=explicit)


def _add_policy_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--policy",
        help="Explicit policy overlay. Defaults to .oak/policy.yaml over the bundled policy.",
    )


def build_git_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oak-git",
        description="Guarded Git and GitHub operations for agents and humans.",
    )
    _add_policy_argument(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="Create a policy-compliant topic branch")
    start.add_argument("branch")

    validate = sub.add_parser("validate", help="Validate the current branch and linked issue")
    validate.add_argument("--offline", action="store_true", help="Skip the GitHub issue lookup")
    validate.add_argument("--json", action="store_true")

    push_parser = sub.add_parser("push", help="Push the current topic branch without force options")
    push_parser.add_argument("--remote")

    pr_open = sub.add_parser("pr-open", help="Open a policy-compliant pull request")
    pr_open.add_argument("--base")
    pr_open.add_argument("--title")
    pr_open.add_argument("--body")
    pr_open.add_argument("--draft", action="store_true")

    status = sub.add_parser("review-status", help="Evaluate CI, CodeRabbit, and review threads")
    status.add_argument("--wait", type=int, default=0, metavar="SECONDS")
    status.add_argument("--json", action="store_true")

    merge_parser = sub.add_parser("merge", help="Merge only when every configured gate passes")
    merge_parser.add_argument("--dry-run", action="store_true")
    merge_parser.add_argument("--json", action="store_true")

    hook = sub.add_parser("hook", help="Entry point for portable Git hooks")
    hook_sub = hook.add_subparsers(dest="hook_name", required=True)
    hook_sub.add_parser("pre-push")
    return parser


def git_main(argv: list[str] | None = None) -> None:
    args = build_git_parser().parse_args(argv)
    try:
        policy = _load(args)
        if args.command == "start":
            start_branch(args.branch, policy)
            print(f"Created branch {args.branch}")
        elif args.command == "validate":
            decision = validate_working_branch(policy, check_issue=not args.offline)
            _print_decision(decision, as_json=args.json)
            if not decision.ready:
                raise SystemExit(1)
        elif args.command == "push":
            push(policy, args.remote)
            print("Push accepted by Oak Policy")
        elif args.command == "pr-open":
            url = open_pull_request(
                policy,
                base=args.base,
                title=args.title,
                body=args.body,
                draft=args.draft,
            )
            print(url)
        elif args.command == "review-status":
            decision = (
                wait_for_review(policy, args.wait) if args.wait > 0 else review_status(policy)
            )
            _print_decision(decision, as_json=args.json)
            if not decision.ready:
                raise SystemExit(1)
        elif args.command == "merge":
            decision = merge(policy, dry_run=args.dry_run)
            _print_decision(decision, as_json=args.json)
        elif args.command == "hook" and args.hook_name == "pre-push":
            decision = pre_push_hook(policy)
            if not decision.ready:
                _print_decision(decision, as_json=False)
                raise SystemExit(1)
    except PolicyDenied as exc:
        print(f"OAK POLICY BLOCKED: {exc}", file=sys.stderr)
        for blocker in exc.blockers:
            print(f"  - {blocker}", file=sys.stderr)
        raise SystemExit(1) from exc
    except OakPolicyError as exc:
        print(f"oak-git: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _doctor(policy: dict[str, Any]) -> int:
    root = find_repo_root()
    checks: list[tuple[str, bool, str]] = [
        ("policy", True, str(default_policy_path())),
        ("git", shutil.which("git") is not None, shutil.which("git") or "not found"),
        ("gh", shutil.which("gh") is not None, shutil.which("gh") or "not found"),
        ("repository", root is not None, str(root) if root else "not inside a Git repository"),
    ]
    if shutil.which("gh"):
        auth = run(["gh", "auth", "status"], check=False)
        checks.append(("GitHub authentication", auth.returncode == 0, auth.stderr.strip()))
    if root:
        hooks_path = run(
            ["git", "config", "--local", "--get", "core.hooksPath"],
            cwd=root,
            check=False,
        ).stdout.strip()
        checks.append(("portable hook", hooks_path == ".oak/hooks", hooks_path or "not installed"))

    harnesses = policy["agents"]["harnesses"]
    for name, config in harnesses.items():
        executable = shutil.which(config["command"])
        checks.append((f"harness:{name}", executable is not None, executable or "not installed"))

    for name, ok, detail in checks:
        print(f"{'OK' if ok else 'MISSING':7} {name}: {detail}")
    return 0 if all(ok for _, ok, _ in checks[:5]) else 1


def build_policy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oak-policy",
        description="Manage the shared Oak Policy configuration and harness adapters.",
    )
    _add_policy_argument(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="Load and validate the effective policy")
    validate.add_argument("--show", action="store_true")

    sub.add_parser("doctor", help="Check policy, GitHub CLI, hooks, and configured harnesses")

    generate = sub.add_parser("generate", help="Render or install harness instructions")
    generate.add_argument("--harness", default="all")
    generate.add_argument("--write", action="store_true")

    install_parser = sub.add_parser("install", help="Install hook and generated instructions")
    install_parser.add_argument("--harness", default="all")
    return parser


def _selected_harnesses(policy: dict[str, Any], requested: str) -> list[str]:
    known = sorted(policy["agents"]["harnesses"])
    if requested == "all":
        return known
    if requested not in known:
        raise OakPolicyError(f"Unknown harness '{requested}'. Known harnesses: {', '.join(known)}")
    return [requested]


def policy_main(argv: list[str] | None = None) -> None:
    args = build_policy_parser().parse_args(argv)
    try:
        policy = _load(args)
        if args.command == "validate":
            print(f"Policy v{policy['version']} is valid")
            if args.show:
                print(yaml.safe_dump(policy, sort_keys=False).rstrip())
        elif args.command == "doctor":
            raise SystemExit(_doctor(policy))
        elif args.command == "generate":
            harnesses = _selected_harnesses(policy, args.harness)
            if not args.write:
                print(render(policy).rstrip())
            else:
                for harness in harnesses:
                    print(f"installed {harness}: {install_instructions(policy, harness)}")
        elif args.command == "install":
            print(f"installed hook: {install_hook(policy)}")
            for harness in _selected_harnesses(policy, args.harness):
                print(f"installed {harness}: {install_instructions(policy, harness)}")
    except OakPolicyError as exc:
        print(f"oak-policy: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
