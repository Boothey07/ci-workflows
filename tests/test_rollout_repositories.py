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

ROLLOUT_WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "rollout.yml"


class FakeGitHub:
    def __init__(self, responses):
        self.responses = iter(responses)

    def request(self, method, path):
        return next(self.responses)


class RecordingSyncGitHub:
    def __init__(self):
        self.files = None

    def request(self, method, path):
        assert method == "GET"
        assert path == "/repos/Boothey07/odds-workshop"
        return 200, {
            "owner": {"login": "Boothey07"},
            "archived": False,
            "default_branch": "main",
        }

    def root_files(self, repo, branch):
        assert repo == "Boothey07/odds-workshop"
        assert branch == "main"
        return {
            "backend/pyproject.toml",
            "package.json",
            "package-lock.json",
            "OddsWorkshop/OddsWorkshop.xcodeproj/project.pbxproj",
            "backend/tests/test_store.py",
        }

    def write_files(self, repo, branch, files, message, force):
        self.files = files
        return {path: "updated" for path in files}


def test_explicit_repositories_reject_other_owners(monkeypatch):
    monkeypatch.setenv("MANAGED_REPOSITORIES", "example,OtherOwner/unsafe")

    with pytest.raises(ValueError, match="outside Boothey07"):
        explicit_repositories()


def test_mac_runner_repositories_normalizes_names(monkeypatch):
    monkeypatch.setenv("MAC_RUNNER_REPOSITORIES", "bjj-health-app, Boothey07/ios-app")

    assert mac_runner_repositories() == {"Boothey07/bjj-health-app", "Boothey07/ios-app"}


def test_rollout_workflow_passes_mac_runner_repository_secret():
    workflow = ROLLOUT_WORKFLOW.read_text()

    assert "MAC_RUNNER_REPOSITORIES: ${{ secrets.MAC_RUNNER_REPOSITORIES }}" in workflow


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


def test_odds_workshop_rollout_preserves_repo_specific_release_gates(monkeypatch):
    github = RecordingSyncGitHub()
    monkeypatch.setenv("MAC_RUNNER_REPOSITORIES", "Boothey07/odds-workshop")

    sync_repository(github, "Boothey07/odds-workshop")

    assert github.files is not None
    ci = github.files[".github/workflows/ci.yml"]
    post_merge = github.files[".github/workflows/post-merge.yml"]

    for workflow in (ci, post_merge):
        assert "python: [\"3.12\", \"3.13\"]" in workflow
        assert "uses: ./.github/actions/backend-ci" in workflow
        assert "npm ci && npx playwright-core install chromium" in workflow
        assert "npm test --if-present && npm run test:e2e" in workflow
        assert "runs-on: [self-hosted, macOS, odds-workshop]" in workflow
        assert "./scripts/test-ios.sh" in workflow
        assert "cancel-in-progress: true" in workflow

    assert "required-jobs: hygiene,secrets,python,frontend,ios" in ci
    assert "required-jobs: secrets,python,frontend,ios" in post_merge
