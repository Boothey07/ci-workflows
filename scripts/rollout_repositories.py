#!/usr/bin/env python3
"""Continuously attach central CI to managed and newly-created private repos."""

from __future__ import annotations

import os
import re
import time
from datetime import UTC, datetime

from bootstrap_repo import (
    CI_WORKFLOWS_REF,
    GitHub,
    auth_token,
    detect_profile,
    render_ci,
    render_post_merge,
    runner_json,
)

OWNER = os.environ.get("REPOSITORY_OWNER", "Boothey07")
DISCOVER_AFTER = os.environ.get("AUTO_DISCOVER_AFTER", "2026-07-29T00:00:00Z")
EXCLUDED = {"ci-workflows", "ci-pr-reviewer", "ci-pr-reviewer-ui"}
ODDS_WORKSHOP_REPO = f"{OWNER}/odds-workshop"


def render_odds_workshop_ci(default_branch: str) -> str:
    """Render the repo-specific PR gate that Odds Workshop requires."""
    branches = "[master]" if default_branch == "master" else "[main, dev]"
    return f'''# Managed by Boothey07/ci-workflows with an Odds Workshop-specific profile.
# Keep uv-managed backend execution, browser E2E, and native iOS verification blocking.
name: CI

on:
  pull_request:
    branches: {branches}

concurrency:
  group: odds-workshop-${{{{ github.workflow }}}}-${{{{ github.ref }}}}
  cancel-in-progress: true

permissions:
  contents: read
  issues: read
  pull-requests: read

jobs:
  hygiene:
    uses: Boothey07/ci-workflows/.github/workflows/pr-hygiene.yml@{CI_WORKFLOWS_REF}
    with:
      runs-on: '["self-hosted","odds-workshop"]'

  secrets:
    uses: Boothey07/ci-workflows/.github/workflows/secrets.yml@{CI_WORKFLOWS_REF}
    with:
      runs-on: '["self-hosted","odds-workshop"]'

  python:
    name: Backend · Python ${{{{ matrix.python }}}}
    strategy:
      fail-fast: false
      matrix:
        python: ["3.12", "3.13"]
    runs-on: [self-hosted, odds-workshop]
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
      - uses: ./.github/actions/backend-ci
        with:
          python-version: ${{{{ matrix.python }}}}

  frontend:
    uses: Boothey07/ci-workflows/.github/workflows/node-ci.yml@{CI_WORKFLOWS_REF}
    with:
      runs-on: '["self-hosted","odds-workshop"]'
      working-directory: "."
      install-command: "npm ci && npx playwright-core install chromium"
      lint-command: "npm run lint --if-present"
      build-command: "npm run build --if-present"
      test-command: "npm test --if-present && npm run test:e2e"

  ios:
    name: iOS · Xcode unit + UI smoke
    runs-on: [self-hosted, macOS, odds-workshop]
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
      - name: Run native tests on the simulator
        run: ./scripts/test-ios.sh

  quality-gate:
    name: Quality Gate
    if: always()
    needs: [hygiene, secrets, python, frontend, ios]
    uses: Boothey07/ci-workflows/.github/workflows/quality-gate.yml@{CI_WORKFLOWS_REF}
    with:
      results: ${{{{ toJSON(needs) }}}}
      required-jobs: hygiene,secrets,python,frontend,ios
      runs-on: '["self-hosted","odds-workshop"]'
'''


def render_odds_workshop_post_merge(default_branch: str) -> str:
    """Render the exact-main release gate used before Odds Workshop deploys."""
    branches = "[master]" if default_branch == "master" else "[main, dev]"
    return f'''# Managed by Boothey07/ci-workflows with an Odds Workshop-specific profile.
# Verify the exact merged commit with backend, browser E2E, secrets, and native iOS gates.
name: Post-merge CI

on:
  push:
    branches: {branches}
  workflow_dispatch:

concurrency:
  group: odds-workshop-${{{{ github.workflow }}}}-${{{{ github.ref }}}}
  cancel-in-progress: true

permissions:
  contents: read
  issues: read
  pull-requests: read

jobs:
  secrets:
    uses: Boothey07/ci-workflows/.github/workflows/secrets.yml@{CI_WORKFLOWS_REF}
    with:
      runs-on: '["self-hosted","odds-workshop"]'

  python:
    name: Backend · Python ${{{{ matrix.python }}}}
    strategy:
      fail-fast: false
      matrix:
        python: ["3.12", "3.13"]
    runs-on: [self-hosted, odds-workshop]
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
      - uses: ./.github/actions/backend-ci
        with:
          python-version: ${{{{ matrix.python }}}}

  frontend:
    uses: Boothey07/ci-workflows/.github/workflows/node-ci.yml@{CI_WORKFLOWS_REF}
    with:
      runs-on: '["self-hosted","odds-workshop"]'
      working-directory: "."
      install-command: "npm ci && npx playwright-core install chromium"
      lint-command: "npm run lint --if-present"
      build-command: "npm run build --if-present"
      test-command: "npm test --if-present && npm run test:e2e"

  ios:
    name: iOS · Xcode unit + UI smoke
    runs-on: [self-hosted, macOS, odds-workshop]
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
      - name: Run native tests on the simulator
        run: ./scripts/test-ios.sh

  quality-gate:
    name: Quality Gate
    if: always()
    needs: [secrets, python, frontend, ios]
    uses: Boothey07/ci-workflows/.github/workflows/quality-gate.yml@{CI_WORKFLOWS_REF}
    with:
      results: ${{{{ toJSON(needs) }}}}
      required-jobs: secrets,python,frontend,ios
      runs-on: '["self-hosted","odds-workshop"]'
'''


def runner_repo_label(repo: str) -> str:
    """Return the stable repo-specific runner label used by repo-scoped runners."""
    name = repo.split("/", 1)[1]
    label = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    if not label:
        raise ValueError(f"cannot derive runner label for {repo}")
    return label


def explicit_repositories() -> set[str]:
    raw = os.environ.get("MANAGED_REPOSITORIES", "")
    names = {item.strip() for item in raw.replace(",", "\n").splitlines() if item.strip()}
    repositories = {name if "/" in name else f"{OWNER}/{name}" for name in names}
    invalid = sorted(repo for repo in repositories if repo.split("/", 1)[0] != OWNER)
    if invalid:
        raise ValueError(
            f"MANAGED_REPOSITORIES contains repositories outside {OWNER}: {', '.join(invalid)}"
        )
    return repositories


def mac_runner_repositories() -> set[str]:
    raw = os.environ.get("MAC_RUNNER_REPOSITORIES", "")
    names = {item.strip() for item in raw.replace(",", "\n").splitlines() if item.strip()}
    repositories = {name if "/" in name else f"{OWNER}/{name}" for name in names}
    invalid = sorted(repo for repo in repositories if repo.split("/", 1)[0] != OWNER)
    if invalid:
        raise ValueError(
            f"MAC_RUNNER_REPOSITORIES contains repositories outside {OWNER}: {', '.join(invalid)}"
        )
    return repositories


def discovered_repositories(github: GitHub) -> set[str]:
    if os.environ.get("DISABLE_AUTO_DISCOVERY", "false").lower() == "true":
        return set()
    cutoff = datetime.fromisoformat(DISCOVER_AFTER.replace("Z", "+00:00")).astimezone(UTC)
    repositories: set[str] = set()
    listed = 0
    page = 1
    while True:
        status, body = github.request("GET", f"/installation/repositories?per_page=100&page={page}")
        if status != 200 or not isinstance(body, dict):
            raise RuntimeError(f"cannot list App repositories: {body}")
        batch = body.get("repositories", [])
        if not isinstance(batch, list):
            raise RuntimeError(f"invalid App repository page: {body}")
        listed += len(batch)
        for repo in batch:
            created_at = repo.get("created_at")
            name = repo.get("name")
            full_name = repo.get("full_name")
            if not all(isinstance(value, str) and value for value in (created_at, name, full_name)):
                continue
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if (
                repo.get("owner", {}).get("login") == OWNER
                and repo.get("private")
                and not repo.get("archived")
                and not repo.get("fork")
                and name not in EXCLUDED
                and created >= cutoff
            ):
                repositories.add(full_name)
        total_count = body.get("total_count")
        if isinstance(total_count, int):
            if listed >= total_count:
                break
            if not batch:
                raise RuntimeError(
                    f"App repository listing stopped at {listed}/{total_count} repositories"
                )
        elif len(batch) < 100:
            break
        page += 1
    return repositories


def sync_repository(github: GitHub, repo: str) -> None:
    status, metadata = github.request("GET", f"/repos/{repo}")
    if status != 200 or not isinstance(metadata, dict):
        raise RuntimeError(f"cannot inspect {repo}: {metadata}")
    if metadata.get("owner", {}).get("login") != OWNER:
        raise RuntimeError(f"refusing to manage repository outside {OWNER}: {repo}")
    if metadata.get("archived"):
        return
    branch = metadata["default_branch"]

    if repo == ODDS_WORKSHOP_REPO:
        files: dict[str, str | None] = {
            ".github/workflows/ci.yml": render_odds_workshop_ci(branch),
            ".github/workflows/post-merge.yml": render_odds_workshop_post_merge(branch),
            ".github/workflows/pr-review.yml": None,
            ".github/workflows/auto-merge.yml": None,
        }
    else:
        profile = detect_profile(github.root_files(repo, branch))
        repo_label = runner_repo_label(repo)
        labels = f"self-hosted,linux,x64,vps,{repo_label}"
        runs_on = runner_json("self-hosted", labels)
        mac_runs_on = None
        if profile.apple and repo in mac_runner_repositories():
            mac_labels = f"self-hosted,macOS,ARM64,ios,{repo_label}"
            mac_runs_on = runner_json("self-hosted", mac_labels)
        files = {
            ".github/workflows/ci.yml": render_ci(profile, runs_on, branch, mac_runs_on),
            ".github/workflows/post-merge.yml": render_post_merge(
                profile, runs_on, branch, mac_runs_on
            ),
            ".github/workflows/pr-review.yml": None,
            ".github/workflows/auto-merge.yml": None,
        }

    results = github.write_files(
        repo,
        branch,
        files,
        "ci: synchronize unattended quality automation",
        force=True,
    )
    changed = ", ".join(f"{path}={result}" for path, result in results.items())
    print(f"{repo}: {changed}")


def sync_repository_with_retry(
    github: GitHub,
    repo: str,
    *,
    attempts: int = 3,
) -> None:
    for attempt in range(1, attempts + 1):
        try:
            sync_repository(github, repo)
            return
        except Exception:
            if attempt == attempts:
                raise
            delay = 2 ** (attempt - 1)
            print(f"{repo}: sync attempt {attempt}/{attempts} failed; retrying in {delay}s")
            time.sleep(delay)


def main() -> int:
    github = GitHub(auth_token())
    repositories = explicit_repositories() | discovered_repositories(github)
    failures = []
    for repo in sorted(repositories):
        try:
            sync_repository_with_retry(github, repo)
        except Exception as error:
            failures.append(f"{repo}: {error}")
    if failures:
        raise RuntimeError("; ".join(failures))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
