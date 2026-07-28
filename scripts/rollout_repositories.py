#!/usr/bin/env python3
"""Continuously attach central CI to managed and newly-created private repos."""

from __future__ import annotations

import os
import time
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
    repositories = {name if "/" in name else f"{OWNER}/{name}" for name in names}
    invalid = sorted(repo for repo in repositories if repo.split("/", 1)[0] != OWNER)
    if invalid:
        raise ValueError(
            f"MANAGED_REPOSITORIES contains repositories outside {OWNER}: {', '.join(invalid)}"
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
