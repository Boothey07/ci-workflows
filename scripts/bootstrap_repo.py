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
# Pin every managed-workflow ref in one place so the hourly rollout sync and
# the bootstrap tool can never drift from the current ci-workflows release tag.
CI_WORKFLOWS_REF = os.environ.get("CI_WORKFLOWS_REF", "v15")


@dataclass(frozen=True)
class RepoProfile:
    name: str
    python: bool
    node: bool
    tests: bool
    apple: bool = False
    apple_working_directory: str = ""
    apple_scheme: str = ""
    apple_build_system: str = ""
    pnpm: bool = False
    node_working_directory: str = "."


def detect_profile(files: set[str]) -> RepoProfile:
    basenames = {name.rsplit("/", 1)[-1] for name in files}
    python = (
        bool(basenames & {"pyproject.toml", "setup.py", "setup.cfg", "Pipfile"})
        or any(
            name.startswith(("requirements", "environment"))
            and name.endswith((".txt", ".yml", ".yaml"))
            for name in basenames
        )
        or any(path.endswith(".py") for path in files)
    )
    package_jsons = sorted(path for path in files if path.endswith("package.json"))
    node = bool(package_jsons)
    node_working_directory = "."
    if "package.json" not in files and package_jsons:
        lock_names = ("package-lock.json", "pnpm-lock.yaml", "yarn.lock")
        locked_projects = []
        for package_json in package_jsons:
            directory = package_json.rsplit("/", 1)[0]
            if any(f"{directory}/{lock_name}" in files for lock_name in lock_names):
                locked_projects.append(directory)
        node_working_directory = locked_projects[0] if locked_projects else package_jsons[0].rsplit("/", 1)[0]
    selected_pnpm_lock = (
        "pnpm-lock.yaml"
        if node_working_directory == "."
        else f"{node_working_directory}/pnpm-lock.yaml"
    )
    pnpm = selected_pnpm_lock in files
    tests = any(
        part.lower().startswith(("test", "tests")) for path in files for part in path.split("/")
    )
    apple_dir, apple_scheme = detect_apple_project(files)
    apple_build_system = (
        "swift-package" if apple_dir == "." and "Package.swift" in files else "xcodebuild"
    ) if apple_dir else ""
    parts = []
    if python:
        parts.append("python")
    if node:
        parts.append("node")
    if apple_dir:
        parts.append("apple")
    name = "-".join(parts) if parts else "generic"
    return RepoProfile(
        name=name,
        python=python,
        node=node,
        tests=tests,
        apple=bool(apple_dir),
        apple_working_directory=apple_dir,
        apple_scheme=apple_scheme,
        apple_build_system=apple_build_system,
        pnpm=pnpm,
        node_working_directory=node_working_directory,
    )


def detect_apple_project(files: set[str]) -> tuple[str, str]:
    """Return (working_directory, scheme) for an iOS/macOS project, if obvious."""
    if ("project.yml" in files or "project.yaml" in files) and any(
        path.startswith("Sources/") for path in files
    ):
        info_plists = sorted(
            path
            for path in files
            if path.startswith("Sources/")
            and path.count("/") >= 2
            and path.endswith("/Info.plist")
        )
        if info_plists:
            return ".", info_plists[0].split("/", 2)[1]
        app_sources = sorted(
            path
            for path in files
            if path.startswith("Sources/")
            and path.count("/") >= 2
            and path.endswith((".swift", ".plist", ".entitlements"))
        )
        if app_sources:
            return ".", app_sources[0].split("/", 2)[1]
        return ".", ""

    project_yamls = sorted(
        path
        for path in files
        if path.endswith(("/project.yml", "/project.yaml"))
        and path.startswith(("ios/", "macos/", "iOS/", "macOS/"))
    )
    if project_yamls:
        directory = project_yamls[0].rsplit("/", 1)[0]
        return directory, directory.rsplit("/", 1)[-1]

    xcode_projects = sorted(
        path
        for path in files
        if path.endswith(".xcodeproj/project.pbxproj")
        and path.startswith(("ios/", "macos/", "iOS/", "macOS/"))
    )
    if xcode_projects:
        project_dir = xcode_projects[0].rsplit(".xcodeproj/", 1)[0] + ".xcodeproj"
        directory = project_dir.rsplit("/", 1)[0]
        project_name = project_dir.rsplit("/", 1)[-1].removesuffix(".xcodeproj")
        return directory, project_name

    if any(path.startswith(("ios/", "macos/", "iOS/", "macOS/")) for path in files):
        return "ios" if any(path.startswith(("ios/", "iOS/")) for path in files) else "macos", ""

    if "Package.swift" in files and any(path.startswith("Sources/") for path in files):
        return ".", ""

    return "", ""


def runner_json(mode: str, labels: str) -> str:
    if mode == "hosted":
        return '["ubuntu-latest"]'
    values = [value.strip() for value in labels.split(",") if value.strip()]
    if not values:
        raise ValueError("self-hosted mode requires --runner-labels")
    return json.dumps(values, separators=(",", ":"))


def render_ci(
    profile: RepoProfile,
    runs_on: str,
    default_branch: str = "main",
    apple_runs_on: str | None = None,
) -> str:
    jobs: list[str] = []
    required: list[str] = ["hygiene", "secrets"]
    jobs.extend(
        [
            "  hygiene:\n"
            f"    uses: Boothey07/ci-workflows/.github/workflows/pr-hygiene.yml@{CI_WORKFLOWS_REF}\n"
            f"    with:\n      runs-on: '{runs_on}'\n",
            "  secrets:\n"
            f"    uses: Boothey07/ci-workflows/.github/workflows/secrets.yml@{CI_WORKFLOWS_REF}\n"
            f"    with:\n      runs-on: '{runs_on}'\n",
        ]
    )
    if profile.python:
        required.append("python")
        jobs.append(
            "  python:\n"
            f"    uses: Boothey07/ci-workflows/.github/workflows/python-ci.yml@{CI_WORKFLOWS_REF}\n"
            "    with:\n"
            '      paths: "."\n'
            '      lint-paths: "."\n'
            '      python-versions: \'["3.11","3.12","3.13"]\'\n'
            f"      runs-on: '{runs_on}'\n"
            f"      run-tests: {'true' if profile.tests else 'false'}\n"
        )
    if profile.node:
        required.append("frontend")
        # pnpm workspaces need pnpm install, not npm ci (which fails without a
        # package-lock.json and ignores workspace deps).
        if profile.pnpm:
            install_cmd = "npm install -g pnpm && pnpm install"
        else:
            install_cmd = "npm ci"
        jobs.append(
            "  frontend:\n"
            f"    uses: Boothey07/ci-workflows/.github/workflows/node-ci.yml@{CI_WORKFLOWS_REF}\n"
            "    with:\n"
            f"      runs-on: '{runs_on}'\n"
            f'      working-directory: "{profile.node_working_directory}"\n'
            f'      install-command: "{install_cmd}"\n'
            '      lint-command: "npm run lint --if-present"\n'
            '      build-command: "npm run build --if-present"\n'
            '      test-command: "npm test --if-present"\n'
        )
    if profile.apple and apple_runs_on:
        required.append("apple")
        apple_working_directory = profile.apple_working_directory or "."
        apple_scheme = profile.apple_scheme
        apple_build_system = profile.apple_build_system or "xcodebuild"
        xcodegen = "false" if apple_build_system == "swift-package" else "true"
        jobs.append(
            "  apple:\n"
            f"    uses: Boothey07/ci-workflows/.github/workflows/apple-ci.yml@{CI_WORKFLOWS_REF}\n"
            "    with:\n"
            f"      runs-on: '{apple_runs_on}'\n"
            f'      build-system: "{apple_build_system}"\n'
            f'      working-directory: "{apple_working_directory}"\n'
            f'      scheme: "{apple_scheme}"\n'
            f"      xcodegen: {xcodegen}\n"
            f"      run-tests: {'true' if profile.tests else 'false'}\n"
        )
    jobs.append(
        "  quality-gate:\n"
        "    name: Quality Gate\n"
        "    if: always()\n"
        f"    needs: [{', '.join(required)}]\n"
        f"    uses: Boothey07/ci-workflows/.github/workflows/quality-gate.yml@{CI_WORKFLOWS_REF}\n"
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
        "jobs:\n" + "\n".join(jobs)
    )


def render_post_merge(
    profile: RepoProfile,
    runs_on: str,
    default_branch: str = "main",
    apple_runs_on: str | None = None,
) -> str:
    ci = render_ci(profile, runs_on, default_branch, apple_runs_on)
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


class GitHub:
    def __init__(self, token: str):
        self.token = token

    def request(
        self, method: str, path: str, payload: dict | None = None
    ) -> tuple[int, dict | list]:
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

    def write_file(
        self, repo: str, branch: str, path: str, content: str, message: str, force: bool
    ) -> str:
        encoded = urllib.parse.quote(path, safe="/")
        query = urllib.parse.urlencode({"ref": branch})
        status, existing = self.request("GET", f"/repos/{repo}/contents/{encoded}?{query}")
        sha = existing.get("sha") if status == 200 and isinstance(existing, dict) else None
        if status not in (200, 404):
            raise RuntimeError(f"cannot inspect {repo}/{path}: {existing}")
        if sha and not force:
            return "exists"
        payload = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        status, result = self.request("PUT", f"/repos/{repo}/contents/{encoded}", payload)
        if status not in (200, 201):
            raise RuntimeError(f"cannot write {repo}/{path}: {result}")
        return "updated" if sha else "created"

    def write_files(
        self,
        repo: str,
        branch: str,
        files: dict[str, str | None],
        message: str,
        force: bool,
    ) -> dict[str, str]:
        """Write all managed files in one commit, skipping unchanged content."""
        changed: dict[str, str | None] = {}
        results: dict[str, str] = {}
        for path, content in files.items():
            encoded = urllib.parse.quote(path, safe="/")
            query = urllib.parse.urlencode({"ref": branch})
            status, existing = self.request("GET", f"/repos/{repo}/contents/{encoded}?{query}")
            if status == 200 and isinstance(existing, dict):
                if content is None:
                    changed[path] = None
                    results[path] = "deleted"
                    continue
                current = base64.b64decode(existing["content"]).decode()
                if current == content:
                    results[path] = "unchanged"
                    continue
                if not force:
                    results[path] = "exists"
                    continue
                changed[path] = content
                results[path] = "updated"
            elif status == 404:
                if content is None:
                    results[path] = "absent"
                    continue
                changed[path] = content
                results[path] = "created"
            else:
                raise RuntimeError(f"cannot inspect {repo}/{path}: {existing}")

        conflicts = sorted(path for path, result in results.items() if result == "exists")
        if conflicts:
            raise RuntimeError(
                "managed workflows differ and were not changed without --force: "
                + ", ".join(conflicts)
            )
        if not changed:
            return results

        encoded_branch = urllib.parse.quote(branch, safe="")
        status, ref = self.request("GET", f"/repos/{repo}/git/ref/heads/{encoded_branch}")
        if status != 200 or not isinstance(ref, dict):
            raise RuntimeError(f"cannot read {repo}@{branch}: {ref}")
        parent_sha = ref["object"]["sha"]
        status, parent = self.request("GET", f"/repos/{repo}/git/commits/{parent_sha}")
        if status != 200 or not isinstance(parent, dict):
            raise RuntimeError(f"cannot read parent commit for {repo}: {parent}")

        tree_entries = []
        for path, content in changed.items():
            if content is None:
                tree_entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
                continue
            status, blob = self.request(
                "POST",
                f"/repos/{repo}/git/blobs",
                {"content": content, "encoding": "utf-8"},
            )
            if status != 201 or not isinstance(blob, dict):
                raise RuntimeError(f"cannot create blob for {repo}/{path}: {blob}")
            tree_entries.append(
                {"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]}
            )

        status, tree = self.request(
            "POST",
            f"/repos/{repo}/git/trees",
            {"base_tree": parent["tree"]["sha"], "tree": tree_entries},
        )
        if status != 201 or not isinstance(tree, dict):
            raise RuntimeError(f"cannot create tree for {repo}: {tree}")
        status, commit = self.request(
            "POST",
            f"/repos/{repo}/git/commits",
            {"message": message, "tree": tree["sha"], "parents": [parent_sha]},
        )
        if status != 201 or not isinstance(commit, dict):
            raise RuntimeError(f"cannot create commit for {repo}: {commit}")
        status, result = self.request(
            "PATCH",
            f"/repos/{repo}/git/refs/heads/{encoded_branch}",
            {"sha": commit["sha"], "force": False},
        )
        if status != 200:
            raise RuntimeError(f"cannot update {repo}@{branch}: {result}")
        return results


def auth_token() -> str:
    if os.environ.get("GH_TOKEN"):
        return os.environ["GH_TOKEN"]
    return subprocess.check_output(["gh", "auth", "token"], text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("--branch", default=None, help="default branch; detected when omitted")
    parser.add_argument("--runner", choices=("hosted", "self-hosted"), default="hosted")
    parser.add_argument(
        "--runner-labels", default="self-hosted,linux,x64,vps", help="comma-separated labels"
    )
    parser.add_argument("--force", action="store_true", help="replace existing caller workflows")
    parser.add_argument(
        "--enable-apple-ci",
        action="store_true",
        help="Attach Apple/Xcode CI when an Apple project is detected.",
    )
    parser.add_argument(
        "--mac-runner-labels",
        default="self-hosted,macOS,ARM64,ios",
        help="comma-separated labels for the repo-scoped macOS runner",
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
    apple_runs_on = (
        runner_json("self-hosted", args.mac_runner_labels) if args.enable_apple_ci else None
    )
    files = {
        ".github/workflows/ci.yml": render_ci(profile, runs_on, branch, apple_runs_on),
        ".github/workflows/post-merge.yml": render_post_merge(
            profile, runs_on, branch, apple_runs_on
        ),
    }
    print(f"{args.repo}: profile={profile.name} branch={branch} runner={args.runner}")
    if args.dry_run:
        print("dry-run: would write " + ", ".join(files))
        return 0
    results = github.write_files(
        args.repo,
        branch,
        files,
        "ci: attach reusable quality gates",
        args.force,
    )
    for path, result in results.items():
        print(f"{path}: {result}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
