#!/usr/bin/env python3
"""Continuously attach central CI to managed and newly-created private repos."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from bootstrap_repo import (
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


def explicit_repositories() -> set[str]:
    raw = os.environ.get("MANAGED_REPOSITORIES", "")
    names = {item.strip() for item in raw.replace(",", "\n").splitlines() if item.strip()}
    return {name if "/" in name else f"{OWNER}/{name}" for name in names}


def discovered_repositories(github: GitHub) -> set[str]:
    if os.environ.get("DISABLE_AUTO_DISCOVERY", "false").lower() == "true":
        return set()
    cutoff = datetime.fromisoformat(DISCOVER_AFTER.replace("Z", "+00:00")).astimezone(UTC)
    repositories: set[str] = set()
    page = 1
    while True:
        status, body = github.request("GET", f"/installation/repositories?per_page=100&page={page}")
        if status != 200 or not isinstance(body, dict):
            raise RuntimeError(f"cannot list App repositories: {body}")
        batch = body.get("repositories", [])
        for repo in batch:
            created = datetime.fromisoformat(repo["created_at"].replace("Z", "+00:00"))
            if (
                repo.get("owner", {}).get("login") == OWNER
                and repo.get("private")
                and not repo.get("archived")
                and not repo.get("fork")
                and repo["name"] not in EXCLUDED
                and created >= cutoff
            ):
                repositories.add(repo["full_name"])
        if len(batch) < 100:
            break
        page += 1
    return repositories


def sync_repository(github: GitHub, repo: str) -> None:
    status, metadata = github.request("GET", f"/repos/{repo}")
    if status != 200 or not isinstance(metadata, dict):
        raise RuntimeError(f"cannot inspect {repo}: {metadata}")
    if metadata.get("archived"):
        return
    branch = metadata["default_branch"]
    profile = detect_profile(github.root_files(repo, branch))
    labels = f"self-hosted,linux,x64,vps,{repo.split('/', 1)[1]}"
    runs_on = runner_json("self-hosted", labels)
    files: dict[str, str | None] = {
        ".github/workflows/ci.yml": render_ci(profile, runs_on, branch),
        ".github/workflows/post-merge.yml": render_post_merge(profile, runs_on, branch),
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


def main() -> int:
    github = GitHub(auth_token())
    repositories = explicit_repositories() | discovered_repositories(github)
    failures = []
    for repo in sorted(repositories):
        try:
            sync_repository(github, repo)
        except Exception as error:
            failures.append(f"{repo}: {error}")
    if failures:
        raise RuntimeError("; ".join(failures))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
