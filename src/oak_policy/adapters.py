"""Load thin harness adapter metadata."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .errors import ConfigurationError


def _source_root() -> Path:
    return Path(__file__).resolve().parents[2]


def adapter_path(name: str) -> Path:
    candidates = [
        _source_root() / "adapters" / f"{name}.json",
        Path(sys.prefix) / "share" / "oak-policy" / "adapters" / f"{name}.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ConfigurationError(f"Cannot find harness adapter '{name}'")


def load_adapter(name: str) -> dict[str, Any]:
    try:
        adapter = json.loads(adapter_path(name).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Harness adapter '{name}' is not valid JSON") from exc
    if adapter.get("name") != name:
        raise ConfigurationError(f"Harness adapter '{name}' has a mismatched name")
    if not adapter.get("command") or not adapter.get("instruction_file"):
        raise ConfigurationError(
            f"Harness adapter '{name}' must define command and instruction_file"
        )
    return adapter
