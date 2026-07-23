"""Launch any configured coding harness behind the same process-level guards."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path

from .adapters import load_adapter
from .config import find_repo_root, load_policy
from .errors import OakPolicyError
from .instructions import install as install_instructions
from .process import real_binary, run


def _write_shims(root: Path) -> Path:
    value = run(["git", "rev-parse", "--git-path", "oak-policy/shims"], cwd=root).stdout.strip()
    shim_dir = Path(value)
    if not shim_dir.is_absolute():
        shim_dir = root / shim_dir
    shim_dir.mkdir(parents=True, exist_ok=True)
    python = shlex.quote(sys.executable)
    for command in ("git", "gh"):
        path = shim_dir / command
        path.write_text(
            f'#!/usr/bin/env sh\nexec {python} -m oak_policy.shim {command} "$@"\n',
            encoding="utf-8",
        )
        path.chmod(0o755)
    return shim_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oak-agent",
        description="Launch a coding harness with Oak Policy Git guards.",
    )
    parser.add_argument("harness", help="Configured harness name, such as claude-code or codex")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed to the harness")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        root = find_repo_root()
        if not root:
            raise OakPolicyError("oak-agent must launch from inside a Git repository")
        policy = load_policy(root)
        harness = policy["agents"]["harnesses"].get(args.harness)
        if not harness:
            known = ", ".join(sorted(policy["agents"]["harnesses"]))
            raise OakPolicyError(f"Unknown harness '{args.harness}'. Known harnesses: {known}")

        install_instructions(policy, args.harness, root)
        adapter = load_adapter(harness["adapter"])
        shim_dir = _write_shims(root)
        env = os.environ.copy()
        env["OAK_HARNESS"] = args.harness
        env["OAK_SHIM_DIR"] = str(shim_dir)
        env["OAK_REAL_GIT"] = real_binary("git")
        env["OAK_REAL_GH"] = real_binary("gh")
        env["PATH"] = f"{shim_dir}{os.pathsep}{env.get('PATH', '')}"

        executable = harness.get("command", adapter["command"])
        resolved = real_binary(executable)
        os.execvpe(resolved, [executable, *args.args], env)
    except OakPolicyError as exc:
        print(f"oak-agent: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
