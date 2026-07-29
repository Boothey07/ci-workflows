import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from rollout_repositories import (  # noqa: E402
    discovered_repositories,
    explicit_repositories,
    mac_runner_repositories,
    runner_repo_label,
    sync_repository,
    sync_repository_with_retry,
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


def test_mac_runner_repositories_normalizes_names(monkeypatch):
    monkeypatch.setenv("MAC_RUNNER_REPOSITORIES", "bjj-health-app, Boothey07/ios-app")

    assert mac_runner_repositories() == {"Boothey07/bjj-health-app", "Boothey07/ios-app"}


def test_runner_repo_label_is_lowercase_and_safe():
    assert runner_repo_label("Boothey07/BatteryControl") == "batterycontrol"
    assert runner_repo_label("Boothey07/bjj-health-app") == "bjj-health-app"


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


def test_discovery_uses_total_count_across_short_pages(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTO_DISCOVERY", "false")
    github = FakeGitHub(
        [
            (200, {"total_count": 2, "repositories": [{"name": "malformed"}]}),
            (
                200,
                {
                    "total_count": 2,
                    "repositories": [
                        {
                            "name": "new-private",
                            "full_name": "Boothey07/new-private",
                            "created_at": "2026-07-29T00:00:01Z",
                            "private": True,
                            "archived": False,
                            "fork": False,
                            "owner": {"login": "Boothey07"},
                        }
                    ],
                },
            ),
        ]
    )

    assert discovered_repositories(github) == {"Boothey07/new-private"}


def test_sync_refuses_repository_outside_owner():
    github = FakeGitHub([(200, {"owner": {"login": "OtherOwner"}})])

    with pytest.raises(RuntimeError, match="outside Boothey07"):
        sync_repository(github, "OtherOwner/unsafe")


def test_sync_retries_transient_repository_failure(monkeypatch):
    calls = []

    def flaky_sync(github, repo):
        calls.append(repo)
        if len(calls) < 3:
            raise RuntimeError("temporary API failure")

    monkeypatch.setattr("rollout_repositories.sync_repository", flaky_sync)
    monkeypatch.setattr("rollout_repositories.time.sleep", lambda delay: None)

    sync_repository_with_retry(object(), "Boothey07/example")

    assert calls == ["Boothey07/example"] * 3
