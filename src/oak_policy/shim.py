"""Process-level git and gh shims used by oak-agent."""

from __future__ import annotations

import os
import sys

from .process import real_binary


def _deny(message: str) -> int:
    print(f"OAK POLICY BLOCKED: {message}", file=sys.stderr)
    return 77


def git_shim(args: list[str]) -> int:
    if os.environ.get("OAK_GATEWAY_INTERNAL") == "1":
        os.execv(real_binary("git"), ["git", *args])
    command = next((arg for arg in args if not arg.startswith("-")), "")
    if command == "push":
        return _deny("raw `git push` is disabled in agent sessions; use `oak-git push`")
    if command in {"receive-pack", "upload-archive"}:
        return _deny(f"raw `git {command}` is not permitted in agent sessions")
    os.execv(real_binary("git"), ["git", *args])
    return 0


def gh_shim(args: list[str]) -> int:
    if os.environ.get("OAK_GATEWAY_INTERNAL") == "1":
        os.execv(real_binary("gh"), ["gh", *args])
    if len(args) >= 2 and args[0:2] == ["pr", "merge"]:
        return _deny("raw `gh pr merge` is disabled; use `oak-git merge`")
    if args and args[0] == "api":
        joined = " ".join(args).lower()
        merge_markers = ("/merge", "mergepullrequest", "enablepullrequestautomerge")
        if any(marker in joined for marker in merge_markers):
            return _deny("direct GitHub merge API calls are disabled; use `oak-git merge`")
        for index, arg in enumerate(args):
            if (
                arg in {"-X", "--method"}
                and index + 1 < len(args)
                and args[index + 1].upper() in {"PUT", "PATCH", "DELETE"}
            ):
                return _deny("mutating GitHub API calls require an explicit gateway command")
    os.execv(real_binary("gh"), ["gh", *args])
    return 0


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {"git", "gh"}:
        print("usage: python -m oak_policy.shim <git|gh> [args...]", file=sys.stderr)
        raise SystemExit(2)
    command, args = sys.argv[1], sys.argv[2:]
    raise SystemExit(git_shim(args) if command == "git" else gh_shim(args))


if __name__ == "__main__":
    main()
