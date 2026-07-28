#!/usr/bin/env python3
"""Attach the standard CI caller workflows to a personal-account repository.

The tool is deliberately dependency-free so it can run from a VPS timer, a
developer workstation, or a future GitHub App service.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

API = "https://api.github.com"


@dataclass(frozen=True)
class RepoProfile:
    name: str
    python: bool
    node: bool
    tests: bool


def detect_profile(files: set[str]) -> RepoProfile:
    basenames = {name.rsplit("/", 1)[-1] for name in files}
    python = bool(basenames & {"pyproject.toml", "setup.py", "setup.cfg", "Pipfile"}) or any(
        name.startswith(("requirements", "environment")) and name.endswith((".txt", ".yml", ".yaml"))
        for name in basenames
    ) or any(path.endswith(".py") for path in files)
    node = "package.json" in basenames
    tests = any(
        part.startswith(("test", "tests"))
        for path in files
        for part in path.split("/")
    )
    name = "python-node" if python and node else "python" if python else "node" if node else "generic"
    return RepoProfile(name=name, python=python, node=node, tests=tests)


def runner_json(mode: str, labels: str) -> str:
    if mode == "hosted":
        return '["ubuntu-latest"]'
    values = [value.strip() for value in labels.split(",") if value.strip()]
    if not values:
        raise ValueError("self-hosted mode requires --runner-labels")
    return json.dumps(values, separators=(",", ":"))


def render_ci(profile: RepoProfile, runs_on: str, default_branch: str = "main") -> str:
    jobs: list[str] = []
    required: list[str] = ["hygiene", "secrets"]
    jobs.extend(
        [
            "  hygiene:\n"
            "    uses: Boothey07/ci-workflows/.github/workflows/pr-hygiene.yml@v2\n"
            f"    with:\n      runs-on: '{runs_on}'\n",
            "  secrets:\n"
            "    uses: Boothey07/ci-workflows/.github/workflows/secrets.yml@v2\n"
            f"    with:\n      runs-on: '{runs_on}'\n",
        ]
    )
    if profile.python:
        required.append("python")
        jobs.append(
            "  python:\n"
            "    uses: Boothey07/ci-workflows/.github/workflows/python-ci.yml@v2\n"
            "    with:\n"
            "      paths: \".\"\n"
            "      lint-paths: \".\"\n"
            "      python-versions: '[\"3.11\",\"3.12\",\"3.13\"]'\n"
            f"      runs-on: '{runs_on}'\n"
            f"      run-tests: {'true' if profile.tests else 'false'}\n"
        )
    if profile.node:
        required.append("frontend")
        jobs.append(
            "  frontend:\n"
            "    uses: Boothey07/ci-workflows/.github/workflows/node-ci.yml@v2\n"
            "    with:\n"
            f"      runs-on: '{runs_on}'\n"
            "      install-command: \"npm ci\"\n"
            "      lint-command: \"npm run lint --if-present\"\n"
            "      build-command: \"npm run build --if-present\"\n"
            "      test-command: \"npm test --if-present\"\n"
        )
    jobs.append(
        "  quality-gate:\n"
        "    name: Quality Gate\n"
        "    if: always()\n"
        f"    needs: [{', '.join(required)}]\n"
        "    uses: Boothey07/ci-workflows/.github/workflows/quality-gate.yml@v2\n"
        "    with:\n"
        "      results: ${{ toJSON(needs) }}\n"
        f"      required-jobs: {','.join(required)}\n"
        f"      runs-on: '{runs_on}'\n"
    )
    branches = "[master]" if default_branch == "master" else "[main, dev]"
    return (
        "# Managed by Boothey07/ci-workflows. Edit the profile inputs, not the reusable jobs.\n"
        "name: CI\n\n"
        f"on:\n  pull_request:\n    branches: {branches}\n\n"
        "permissions:\n  contents: read\n  issues: read\n  pull-requests: read\n\n"
        "jobs:\n"
        + "\n".join(jobs)
    )


def render_post_merge(profile: RepoProfile, runs_on: str, default_branch: str = "main") -> str:
    ci = render_ci(profile, runs_on, default_branch)
    body = ci.replace("name: CI", "name: Post-merge CI", 1)
    branches = "[master]" if default_branch == "master" else "[main, dev]"
    body = body.replace(
        f"  pull_request:\n    branches: {branches}",
        f"  push:\n    branches: {branches}\n  workflow_dispatch:",
    )
    hygiene_start = body.index("  hygiene:\n")
    hygiene_end = body.index("\n\n  secrets:", hygiene_start)
    body = body[:hygiene_start] + body[hygiene_end + 2 :]
    body = body.replace("needs: [hygiene, ", "needs: [")
    body = body.replace("required-jobs: hygiene,", "required-jobs: ")
    return body


def render_auto_merge(default_branch: str = "main", runs_on: str = '["ubuntu-latest"]') -> str:
    branches = "[master]" if default_branch == "master" else "[main, dev]"
    return (
        "# Managed by Boothey07/ci-workflows.\n"
        "# This workflow is opt-in: apply the 'automerge' label to a trusted PR.\n"
        "name: Auto-merge\n\n"
        "on:\n"
        "  pull_request_target:\n"
        f"    branches: {branches}\n"
        "    types: [opened, synchronize, reopened, ready_for_review, labeled]\n\n"
        "permissions:\n"
        "  contents: write\n"
        "  pull-requests: write\n"
        "  checks: read\n\n"
        "jobs:\n"
        "  auto-merge:\n"
        "    uses: Boothey07/ci-workflows/.github/workflows/auto-merge.yml@v3\n"
        f"    with:\n      runs-on: '{runs_on}'\n"
        "    secrets: inherit\n"
    )


def render_pr_review(
    default_branch: str = "main",
    runs_on: str = '["ubuntu-latest"]',
    model: str = "openai/pr-review-minimax",
    api_base: str = "http://127.0.0.1:4000/v1",
) -> str:
    branches = "[master]" if default_branch == "master" else "[main, dev]"
    return (
        "# Managed by Boothey07/ci-workflows.\n"
        "# Self-hosted PR review through the VPS LiteLLM gateway.\n"
        "name: PR Review\n\n"
        "on:\n"
        "  pull_request_target:\n"
        f"    branches: {branches}\n"
        "    types: [opened, reopened, synchronize, review_requested]\n\n"
        "permissions:\n"
        "  contents: read\n"
        "  pull-requests: write\n"
        "  issues: write\n\n"
        "jobs:\n"
        "  review:\n"
        "    uses: Boothey07/ci-pr-reviewer/.github/workflows/pr-review.yml@v3\n"
        "    with:\n"
        f"      runs-on: '{runs_on}'\n"
        f"      model: '{model}'\n"
        f"      api-base: '{api_base}'\n"
        "      mark-ready: true\n"
        "    secrets: inherit\n"
    )


class GitHub:
    def __init__(self, token: str):
        self.token = token

    def request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict | list]:
        url = API + path
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            try:
                body = json.load(error)
            except json.JSONDecodeError:
                body = {"message": error.read().decode(errors="replace")}
            return error.code, body

    def root_files(self, repo: str, branch: str) -> set[str]:
        encoded = urllib.parse.quote(branch, safe="")
        status, body = self.request("GET", f"/repos/{repo}/git/ref/heads/{encoded}")
        if status == 409:
            return set()
        if status == 404:
            status, body = self.request("GET", f"/repos/{repo}/contents?ref={encoded}")
            if status == 409:
                return set()
            if status != 200 or not isinstance(body, list):
                raise RuntimeError(f"cannot inspect {repo}: {body}")
            return {entry["name"] for entry in body if entry.get("type") == "file"}
        if status != 200 or not isinstance(body, dict):
            raise RuntimeError(f"cannot inspect {repo}: {body}")
        commit_sha = body["object"]["sha"]
        status, body = self.request("GET", f"/repos/{repo}/git/commits/{commit_sha}")
        if status != 200 or not isinstance(body, dict):
            raise RuntimeError(f"cannot inspect {repo}: {body}")
        tree_sha = body["tree"]["sha"]
        status, body = self.request("GET", f"/repos/{repo}/git/trees/{tree_sha}?recursive=1")
        if status != 200 or not isinstance(body, dict):
            raise RuntimeError(f"cannot inspect {repo}: {body}")
        return {entry["path"] for entry in body.get("tree", []) if entry.get("type") == "blob"}

    def write_file(self, repo: str, branch: str, path: str, content: str, message: str, force: bool) -> str:
        encoded = urllib.parse.quote(path, safe="/")
        query = urllib.parse.urlencode({"ref": branch})
        status, existing = self.request("GET", f"/repos/{repo}/contents/{encoded}?{query}")
        sha = existing.get("sha") if status == 200 and isinstance(existing, dict) else None
        if status not in (200, 404):
            raise RuntimeError(f"cannot inspect {repo}/{path}: {existing}")
        if sha and not force:
            return "exists"
        payload = {"message": message, "content": base64.b64encode(content.encode()).decode(), "branch": branch}
        if sha:
            payload["sha"] = sha
        status, result = self.request("PUT", f"/repos/{repo}/contents/{encoded}", payload)
        if status not in (200, 201):
            raise RuntimeError(f"cannot write {repo}/{path}: {result}")
        return "updated" if sha else "created"


def auth_token() -> str:
    if os.environ.get("GH_TOKEN"):
        return os.environ["GH_TOKEN"]
    return subprocess.check_output(["gh", "auth", "token"], text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("--branch", default=None, help="default branch; detected when omitted")
    parser.add_argument("--runner", choices=("hosted", "self-hosted"), default="hosted")
    parser.add_argument("--runner-labels", default="self-hosted,linux,x64,vps", help="comma-separated labels")
    parser.add_argument("--force", action="store_true", help="replace existing caller workflows")
    parser.add_argument(
        "--auto-merge",
        action="store_true",
        help="also install the opt-in owner-only auto-merge workflow",
    )
    parser.add_argument(
        "--pr-review",
        action="store_true",
        help="also install the self-hosted PR-Agent/Ollama review workflow",
    )
    parser.add_argument(
        "--pr-review-only",
        action="store_true",
        help="install only the self-hosted PR reviewer caller; leave existing CI unchanged",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    token = auth_token()
    github = GitHub(token)
    branch = args.branch
    if branch is None:
        status, repo_data = github.request("GET", f"/repos/{args.repo}")
        if status != 200:
            raise RuntimeError(f"cannot inspect {args.repo}: {repo_data}")
        branch = repo_data["default_branch"]
    profile = detect_profile(github.root_files(args.repo, branch))
    runs_on = runner_json(args.runner, args.runner_labels)
    files = {} if args.pr_review_only else {
        ".github/workflows/ci.yml": render_ci(profile, runs_on, branch),
        ".github/workflows/post-merge.yml": render_post_merge(profile, runs_on, branch),
    }
    if args.auto_merge:
        files[".github/workflows/auto-merge.yml"] = render_auto_merge(branch, runs_on)
    if args.pr_review or args.pr_review_only:
        files[".github/workflows/pr-review.yml"] = render_pr_review(branch, runs_on)
    print(f"{args.repo}: profile={profile.name} branch={branch} runner={args.runner}")
    if args.dry_run:
        print("dry-run: would write " + ", ".join(files))
        return 0
    for path, content in files.items():
        result = github.write_file(args.repo, branch, path, content, "ci: attach reusable quality gates", args.force)
        print(f"{path}: {result}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
