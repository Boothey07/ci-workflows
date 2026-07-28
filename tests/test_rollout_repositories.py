import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from rollout_repositories import (  # noqa: E402
    discovered_repositories,
    explicit_repositories,
    sync_repository,
)


class FakeGitHub:
    def __init__(self, responses):
        self.responses = iter(responses)

    def request(self, method, path):
        return next(self.responses)


def test_explicit_repositories_reject_other_owners(monkeypatch):
    monkeypatch.setenv("MANAGED_REPOSITORIES", "example,OtherOwner/unsafe")

    with pytest.raises(ValueError, match="outside Boothey07"):
        explicit_repositories()


def test_discovery_skips_malformed_repository_entries(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTO_DISCOVERY", "false")
    github = FakeGitHub(
        [
            (
                200,
                {
                    "repositories": [
                        {"name": "missing-fields"},
                        {
                            "name": "new-private",
                            "full_name": "Boothey07/new-private",
                            "created_at": "2026-07-29T00:00:01Z",
                            "private": True,
                            "archived": False,
                            "fork": False,
                            "owner": {"login": "Boothey07"},
                        },
                    ]
                },
            )
        ]
    )

    assert discovered_repositories(github) == {"Boothey07/new-private"}


def test_sync_refuses_repository_outside_owner():
    github = FakeGitHub([(200, {"owner": {"login": "OtherOwner"}})])

    with pytest.raises(RuntimeError, match="outside Boothey07"):
        sync_repository(github, "OtherOwner/unsafe")
