"""Safe subprocess helpers and real-binary discovery."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from .errors import CommandError


def real_binary(name: str) -> str:
    """Resolve a command while excluding the Oak shim directory from PATH."""
    override = os.environ.get(f"OAK_REAL_{name.upper()}")
    if override:
        return override

    shim_dir = os.environ.get("OAK_SHIM_DIR")
    entries = os.environ.get("PATH", os.defpath).split(os.pathsep)
    if shim_dir:
        resolved_shim = Path(shim_dir).resolve()
        entries = [entry for entry in entries if entry and Path(entry).resolve() != resolved_shim]
    resolved = shutil.which(name, path=os.pathsep.join(entries))
    if not resolved:
        raise CommandError(f"Required command is unavailable: {name}")
    return resolved


def run(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    input_text: str | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command with captured UTF-8 output and a concise error."""
    command = list(args)
    if command and command[0] in {"git", "gh"}:
        command[0] = real_binary(command[0])

    merged_env = os.environ.copy()
    merged_env["OAK_GATEWAY_INTERNAL"] = "1"
    if env:
        merged_env.update(env)
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        input=input_text,
        env=merged_env,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        display = " ".join(args)
        raise CommandError(f"`{display}` failed: {detail}")
    return result
