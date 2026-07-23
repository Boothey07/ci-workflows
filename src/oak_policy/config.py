"""Policy discovery, loading, merging, and validation."""

from __future__ import annotations

import copy
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .adapters import load_adapter
from .errors import ConfigurationError

Policy = dict[str, Any]


def _source_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_policy_path() -> Path:
    """Find the bundled default policy in a source checkout or installed package."""
    candidates = [
        _source_root() / "policy" / "default.yaml",
        Path(sys.prefix) / "share" / "oak-policy" / "policy" / "default.yaml",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ConfigurationError("Cannot find the bundled policy/default.yaml")


def schema_path() -> Path:
    candidates = [
        _source_root() / "policy" / "schema.json",
        Path(sys.prefix) / "share" / "oak-policy" / "policy" / "schema.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ConfigurationError("Cannot find the bundled policy/schema.json")


def find_repo_root(start: Path | None = None) -> Path | None:
    """Walk upward to the nearest Git working tree."""
    current = (start or Path.cwd()).resolve()
    for path in (current, *current.parents):
        if (path / ".git").exists():
            return path
    return None


def _load_yaml(path: Path) -> Policy:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Policy file does not exist: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigurationError(f"Policy must be a YAML mapping: {path}")
    return raw


def _deep_merge(base: Policy, overlay: Policy) -> Policy:
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def validate_policy(policy: Policy) -> None:
    """Validate the structural invariants used by the engine."""
    schema = json.loads(schema_path().read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(policy),
        key=lambda item: [str(part) for part in item.path],
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.path) or "<root>"
        raise ConfigurationError(f"Policy schema error at {location}: {error.message}")

    required_sections = {
        "repository",
        "branches",
        "pull_requests",
        "checks",
        "reviews",
        "merge",
        "agents",
    }
    if policy.get("version") != 1:
        raise ConfigurationError("Only policy version 1 is supported")
    missing = sorted(required_sections - policy.keys())
    if missing:
        raise ConfigurationError(f"Policy is missing sections: {', '.join(missing)}")

    branches = policy["branches"]
    if not isinstance(branches.get("types"), list) or not branches["types"]:
        raise ConfigurationError("branches.types must be a non-empty list")
    if len(set(branches["types"])) != len(branches["types"]):
        raise ConfigurationError("branches.types contains duplicates")
    try:
        re.compile(branches["slug_pattern"])
    except (KeyError, re.error) as exc:
        raise ConfigurationError("branches.slug_pattern is not a valid regular expression") from exc

    protected = policy["repository"].get("protected_branches")
    if not isinstance(protected, list) or not protected:
        raise ConfigurationError("repository.protected_branches must be a non-empty list")

    target_rules = policy["pull_requests"].get("target_rules")
    if not isinstance(target_rules, list) or not target_rules:
        raise ConfigurationError("pull_requests.target_rules must be a non-empty list")
    for rule in target_rules:
        if not isinstance(rule, dict) or not rule.get("source") or not rule.get("targets"):
            raise ConfigurationError(
                "Each pull_requests.target_rules item needs source and targets"
            )

    if policy["merge"].get("method") not in {"merge", "rebase", "squash"}:
        raise ConfigurationError("merge.method must be merge, rebase, or squash")

    for harness, config in policy["agents"]["harnesses"].items():
        adapter = load_adapter(config["adapter"])
        if adapter["name"] != config["adapter"]:
            raise ConfigurationError(f"Harness '{harness}' has an invalid adapter")


def load_policy(start: Path | None = None, explicit: Path | None = None) -> Policy:
    """Load defaults, then overlay the repository policy if one exists."""
    policy = _load_yaml(default_policy_path())
    override: Path | None = explicit
    if override is None and os.environ.get("OAK_POLICY"):
        override = Path(os.environ["OAK_POLICY"])
    if override is None:
        root = find_repo_root(start)
        candidate = root / ".oak" / "policy.yaml" if root else None
        if candidate and candidate.is_file():
            override = candidate
    if override is not None:
        policy = _deep_merge(policy, _load_yaml(override))
    validate_policy(policy)
    return policy
