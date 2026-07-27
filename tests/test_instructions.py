from __future__ import annotations

from pathlib import Path

from oak_policy.adapters import load_adapter
from oak_policy.instructions import END, START, install


def test_instruction_generation_is_idempotent(policy: dict, tmp_path: Path) -> None:
    path = tmp_path / "CLAUDE.md"
    path.write_text("# Existing project guidance\n", encoding="utf-8")

    install(policy, "claude-code", tmp_path)
    install(policy, "claude-code", tmp_path)

    content = path.read_text(encoding="utf-8")
    assert content.startswith("# Existing project guidance")
    assert content.count(START) == 1
    assert content.count(END) == 1
    assert "oak-git merge" in content


def test_shared_agents_file_does_not_duplicate_policy(policy: dict, tmp_path: Path) -> None:
    install(policy, "codex", tmp_path)
    install(policy, "opencode", tmp_path)
    content = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert content.count(START) == 1


def test_every_configured_harness_loads_a_thin_adapter(policy: dict) -> None:
    for config in policy["agents"]["harnesses"].values():
        adapter = load_adapter(config["adapter"])
        assert adapter["instruction_file"] in {"AGENTS.md", "CLAUDE.md"}
