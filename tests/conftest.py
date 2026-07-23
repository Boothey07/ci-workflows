from __future__ import annotations

from pathlib import Path

import pytest

from oak_policy.config import default_policy_path, load_policy


@pytest.fixture
def policy() -> dict:
    return load_policy(start=Path.cwd(), explicit=default_policy_path())
