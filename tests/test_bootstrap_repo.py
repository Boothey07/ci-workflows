import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.bootstrap_repo import (  # noqa: E402
    RepoProfile,
    detect_profile,
    render_auto_merge,
    render_ci,
    render_post_merge,
    render_pr_review,
)


def test_detects_python_node_and_tests_in_nested_paths():
    profile = detect_profile({"api/server.py", "web/package.json", "tests/test_api.py"})

    assert profile == RepoProfile(name="python-node", python=True, node=True, tests=True)


def test_rendered_ci_has_only_detected_required_jobs():
    workflow = render_ci(RepoProfile("python", True, False, False), '["ubuntu-latest"]')

    assert "jobs:\n" in workflow
    assert "pull-requests: read" in workflow
    assert "python-ci.yml@v9" in workflow
    assert "node-ci.yml@v9" not in workflow
    assert "required-jobs: hygiene,secrets,python" in workflow
    assert "run-tests: false" in workflow


def test_post_merge_removes_pr_only_hygiene():
    workflow = render_post_merge(RepoProfile("node", False, True, False), '["ubuntu-latest"]')

    assert "workflow_dispatch:" in workflow
    assert "  hygiene:" not in workflow
    assert "required-jobs: secrets,frontend" in workflow


def test_master_repositories_use_master_branch_filters():
    workflow = render_post_merge(
        RepoProfile("generic", False, False, False), '["ubuntu-latest"]', "master"
    )

    assert "branches: [master]" in workflow
    assert "branches: [main, dev]" not in workflow


def test_auto_merge_is_opt_in_and_uses_default_branch():
    workflow = render_auto_merge("master", '["self-hosted","linux","x64","vps","example"]')

    assert "pull_request_target:" in workflow
    assert "workflow_run:" in workflow
    assert "branches: [master]" in workflow
    assert "types: [opened, synchronize, reopened, ready_for_review, labeled]" in workflow
    assert "auto-merge.yml@v9" in workflow
    assert "runs-on: ubuntu-latest" in workflow
    assert "reviewer_app_private_key: ${{ secrets.REVIEWER_APP_PRIVATE_KEY }}" in workflow


def test_pr_review_uses_local_model_and_runner():
    workflow = render_pr_review("master", '["self-hosted","linux","x64","vps","ci"]')

    assert "pull_request_target:" in workflow
    assert "branches: [master]" in workflow
    assert "types: [opened, reopened, synchronize, ready_for_review, review_requested]" in workflow
    assert "ci-pr-reviewer/.github/workflows/pr-review.yml@v5" in workflow
    assert "openai/pr-review-minimax" in workflow
    assert 'runs-on: \'["self-hosted","linux","x64","vps","ci"]\'' in workflow
    assert "mark-ready: true" in workflow
    assert "auto-merge: true" in workflow
    assert "auto-fix: true" in workflow
    assert "reviewer_app_private_key: ${{ secrets.REVIEWER_APP_PRIVATE_KEY }}" in workflow
