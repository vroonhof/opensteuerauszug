#!/usr/bin/env python3
"""Run a command locally on a repo ref and publish results to GitHub."""

import argparse
import json
import os
import subprocess
import tempfile
import time
import urllib.request
import zipfile


def run(cmd, cwd=None, check=True, capture_output=False):
    result = subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        text=True,
        shell=isinstance(cmd, str),
        capture_output=capture_output,
    )
    return result


def github_request(method, url, token, payload=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, method=method, headers=headers, data=data)
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def zip_results(base_dir, paths, output_path):
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zipper:
        for path in paths:
            full_path = os.path.join(base_dir, path)
            if not os.path.exists(full_path):
                raise FileNotFoundError(f"Result path not found: {path}")
            if os.path.isdir(full_path):
                for root, _, files in os.walk(full_path):
                    for name in files:
                        file_path = os.path.join(root, name)
                        rel_path = os.path.relpath(file_path, base_dir)
                        zipper.write(file_path, rel_path)
            else:
                zipper.write(full_path, path)


def confirm_or_exit(prompt):
    response = input(f"{prompt} [y/N]: ").strip().lower()
    if response != "y":
        raise SystemExit("Aborted before running the command.")


def main():
    parser = argparse.ArgumentParser(
        description="Run a command locally and publish results to GitHub.",
    )
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--ref", help="Branch, tag, or SHA to run.")
    parser.add_argument("--pr", type=int, help="Pull request number to run.")
    parser.add_argument("--command", required=True, help="Command to run.")
    parser.add_argument(
        "--result-path",
        action="append",
        default=[],
        help="Relative path to include in the uploaded artifact (repeatable).",
    )
    parser.add_argument(
        "--show-diff",
        action="store_true",
        help="Show a diff before running the command.",
    )
    parser.add_argument(
        "--artifact-branch",
        default="local-action-artifacts",
        help="Branch to store artifacts (only used with --upload-artifacts).",
    )
    parser.add_argument(
        "--artifact-name",
        default="local-run",
        help="Base name for the artifact zip.",
    )
    parser.add_argument(
        "--check-name",
        default="local-action",
        help="Name of the GitHub check run.",
    )
    parser.add_argument(
        "--upload-artifacts",
        action="store_true",
        help="Upload artifacts to the artifact branch.",
    )
    parser.add_argument(
        "--confirm-upload",
        action="store_true",
        help="Confirm upload to GitHub (required to create a check run).",
    )
    parser.add_argument(
        "--print-check-summary",
        action="store_true",
        default=True,
        help="Print the text that will be uploaded to GitHub (default).",
    )
    parser.add_argument(
        "--no-print-check-summary",
        action="store_false",
        dest="print_check_summary",
        help="Disable printing the check summary.",
    )
    args = parser.parse_args()

    if not args.repo:
        raise SystemExit("--repo or GITHUB_REPOSITORY is required")

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required")
    if args.upload_artifacts and not args.confirm_upload:
        raise SystemExit("--confirm-upload is required when --upload-artifacts is set")

    repo_info = github_request(
        "GET",
        f"https://api.github.com/repos/{args.repo}",
        token,
    )
    if args.pr:
        pull_info = github_request(
            "GET",
            f"https://api.github.com/repos/{args.repo}/pulls/{args.pr}",
            token,
        )
        ref = pull_info["head"]["ref"]
        head_sha = pull_info["head"]["sha"]
        clone_repo = pull_info["head"]["repo"]["full_name"]
        base_ref = pull_info["base"]["ref"]
    else:
        ref = args.ref or repo_info["default_branch"]
        head_sha = None
        clone_repo = args.repo
        base_ref = None

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    run_id = f"{timestamp}-{int(time.time())}"

    with tempfile.TemporaryDirectory(prefix="local-action-") as temp_dir:
        repo_dir = os.path.join(temp_dir, "repo")
        clone_url = f"https://x-access-token:{token}@github.com/{clone_repo}.git"
        run(["git", "clone", "--branch", ref, "--depth", "1", clone_url, repo_dir])

        if args.show_diff:
            if args.pr and base_ref:
                base_url = f"https://x-access-token:{token}@github.com/{args.repo}.git"
                run(["git", "fetch", base_url, base_ref, "--depth", "1"], cwd=repo_dir)
                diff_range = "FETCH_HEAD...HEAD"
            else:
                run(
                    ["git", "fetch", "origin", ref, "--depth", "1"],
                    cwd=repo_dir,
                    check=False,
                )
                diff_range = "HEAD~1..HEAD"
            diff_output = run(
                ["git", "diff", diff_range],
                cwd=repo_dir,
                check=False,
                capture_output=True,
            ).stdout
            print("--- git diff ---")
            print(diff_output)
            confirm_or_exit("Proceed with running the command?")

        command_result = run(
            args.command,
            cwd=repo_dir,
            check=False,
            capture_output=True,
        )
        success = command_result.returncode == 0

        if not head_sha:
            head_sha = run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_dir,
                capture_output=True,
            ).stdout.strip()

        artifact_dir = os.path.join(repo_dir, "local-action-results", run_id)
        os.makedirs(artifact_dir, exist_ok=True)

        log_path = os.path.join(artifact_dir, "command.log")
        with open(log_path, "w", encoding="utf-8") as log_file:
            log_file.write(command_result.stdout)
            if command_result.stderr:
                log_file.write("\n--- stderr ---\n")
                log_file.write(command_result.stderr)

        if args.result_path and args.upload_artifacts:
            zip_path = os.path.join(artifact_dir, f"{args.artifact_name}.zip")
            zip_results(repo_dir, args.result_path, zip_path)

        details_url = None
        if args.upload_artifacts:
            run(["git", "checkout", "-B", args.artifact_branch], cwd=repo_dir)
            run(["git", "add", "local-action-results"], cwd=repo_dir)
            run(
                [
                    "git",
                    "commit",
                    "-m",
                    f"Add local run artifacts {run_id}",
                ],
                cwd=repo_dir,
                check=False,
            )
            run(["git", "push", "origin", args.artifact_branch], cwd=repo_dir)

        artifact_path = f"local-action-results/{run_id}/"
        if args.upload_artifacts:
            details_url = (
                f"https://github.com/{args.repo}/tree/{args.artifact_branch}/{artifact_path}"
            )
        summary_lines = [
            f"Ref: `{ref}`",
            "Artifacts: not uploaded",
            f"Exit code: {command_result.returncode}",
        ]
        if details_url:
            summary_lines[2] = f"Artifacts: {details_url}"
        if command_result.stderr:
            summary_lines.append("")
            summary_lines.append("Stderr:")
            summary_lines.append(command_result.stderr.rstrip())
        else:
            summary_lines.append("")
            summary_lines.append("Stderr: (none)")
        if args.print_check_summary:
            print("--- check summary ---")
            print("\n".join(summary_lines))

        if args.confirm_upload:
            check_payload = {
                "name": args.check_name,
                "head_sha": head_sha,
                "status": "completed",
                "conclusion": "success" if success else "failure",
                "details_url": details_url,
                "output": {
                    "title": f"Local run on {ref}",
                    "summary": "\n".join(summary_lines),
                },
            }
            github_request(
                "POST",
                f"https://api.github.com/repos/{args.repo}/check-runs",
                token,
                check_payload,
            )

    if not success:
        raise SystemExit(command_result.returncode)


if __name__ == "__main__":
    main()
