#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

import argparse
import os
import shutil
import subprocess  # nosec B404
import tempfile
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "build", "serve"])
    parser.add_argument(
        "--repos-root",
        help="path to folder containing external repos (default: parent of website repo)",
        type=str,
        default="",
    )
    parser.add_argument(
        "--clone-missing",
        help="clone missing repositories listed in REPO_DOCS",
        action="store_true",
    )
    parser.add_argument(
        "--update-repos",
        help="update already checked out repositories to their configured branch tip",
        action="store_true",
    )
    parser.add_argument(
        "--skip-builds",
        help="skip running external repo build commands and only sync existing docs outputs",
        action="store_true",
    )
    parser.add_argument(
        "--work-root",
        help="persistent temporary workspace root (default: system temp dir)",
        type=str,
        default="",
    )
    parser.add_argument(
        "--pages-root",
        help="path to the gh-pages worktree/output directory (default: repo_root/build)",
        type=str,
        default="",
    )
    return parser.parse_args()


def run_command(*args, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(*args, **kwargs)  # nosec B603,B607


def list_tracked_files(repo_root: Path, *paths: str) -> list[Path]:
    result = run_command(
        ["git", "-C", str(repo_root), "ls-files", "-z", "--", *paths],
        check=True,
        capture_output=True,
    )
    entries = [entry for entry in result.stdout.decode().split("\0") if entry]
    return [repo_root / entry for entry in entries]


def copy_tracked_tree(repo_root: Path, stage_root: Path):
    for source in list_tracked_files(repo_root, "."):
        relative_path = source.relative_to(repo_root)
        target = stage_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def stage_repo_content(repo_root: Path, stage_root: Path):
    copy_tracked_tree(repo_root, stage_root)

    node_modules = repo_root / "node_modules"
    if node_modules.exists():
        (stage_root / "node_modules").symlink_to(node_modules)

    for directory in [stage_root / "docs" / "Libraries", stage_root / "static"]:
        directory.mkdir(parents=True, exist_ok=True)


def sync_external_docs(repo_root: Path, stage_root: Path, args):
    cmd = [
        "python3",
        str(repo_root / "scripts" / "sync-external-docs.py"),
        "--output-root",
        str(stage_root),
    ]
    if args.repos_root:
        cmd.extend(["--repos-root", args.repos_root])
    if args.clone_missing:
        cmd.append("--clone-missing")
    if args.update_repos:
        cmd.append("--update-repos")
    if args.skip_builds:
        cmd.append("--skip-builds")
    run_command(cmd, cwd=repo_root, check=True)


def git_worktree_list(repo_root: Path) -> list[dict[str, str]]:
    output = run_command(
        ["git", "-C", str(repo_root), "worktree", "list", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    worktrees = []
    entry: dict[str, str] = {}
    for line in output.splitlines():
        if not line:
            if entry:
                worktrees.append(entry)
                entry = {}
            continue
        key, _, value = line.partition(" ")
        entry[key] = value
    if entry:
        worktrees.append(entry)
    return worktrees


def find_branch_worktree(
    repo_root: Path, branch: str, target_worktree: Path
) -> Path | None:
    branch_ref = f"refs/heads/{branch}"
    target_resolved = target_worktree.resolve()

    for worktree in git_worktree_list(repo_root):
        worktree_path = Path(worktree["worktree"]).resolve()
        if worktree.get("branch") == branch_ref and worktree_path != target_resolved:
            return worktree_path
    return None


def remove_worktree_if_present(repo_root: Path, worktree_path: Path):
    worktree_resolved = worktree_path.resolve()
    for worktree in git_worktree_list(repo_root):
        if Path(worktree["worktree"]).resolve() == worktree_resolved:
            run_command(
                [
                    "git",
                    "-C",
                    str(repo_root),
                    "worktree",
                    "remove",
                    "--force",
                    str(worktree_path),
                ],
                check=True,
            )
            break
    shutil.rmtree(worktree_path, ignore_errors=True)


def is_git_worktree(path: Path) -> bool:
    if not path.exists():
        return False
    return (
        run_command(
            ["git", "-C", str(path), "rev-parse", "--git-dir"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def is_dirty_worktree(path: Path) -> bool:
    return bool(
        run_command(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )


def confirm_replacing_legacy_pages_root(path: Path):
    message = (
        f"Warning: {path} exists and is not a git worktree.\n"
        "It looks like a legacy local build output directory.\n"
        "Delete it and replace it with a gh-pages worktree? [y/N]: "
    )
    if not os.isatty(0):
        raise SystemExit(
            f"{path} exists and is not a git worktree. "
            "Rerun interactively to approve deletion, remove it manually, "
            "or use --pages-root to target a different path."
        )
    response = input(message).strip().lower()
    if response not in {"y", "yes"}:
        raise SystemExit("Aborted before replacing legacy build directory.")


def confirm_moving_branch_worktree(branch: str, source: Path, target: Path):
    dirty_note = ""
    if is_dirty_worktree(source):
        dirty_note = (
            "\nThe existing worktree has uncommitted changes that will be discarded."
        )
    message = (
        f"Branch '{branch}' is already checked out in worktree: {source}\n"
        f"Move that worktree to {target}?{dirty_note} [y/N]: "
    )
    if not os.isatty(0):
        raise SystemExit(
            f"Branch '{branch}' is already checked out in worktree: {source}. "
            f"Rerun interactively to approve moving it to {target}, or remove it manually."
        )
    response = input(message).strip().lower()
    if response not in {"y", "yes"}:
        raise SystemExit(
            f"Aborted before moving '{branch}' worktree from {source} to {target}."
        )


def ensure_pages_worktree(repo_root: Path, pages_root: Path, branch: str):
    if pages_root.exists() and not is_git_worktree(pages_root):
        confirm_replacing_legacy_pages_root(pages_root)
        shutil.rmtree(pages_root, ignore_errors=True)

    existing_branch_worktree = find_branch_worktree(repo_root, branch, pages_root)
    if existing_branch_worktree:
        confirm_moving_branch_worktree(branch, existing_branch_worktree, pages_root)
        remove_worktree_if_present(repo_root, existing_branch_worktree)

    remote_ref = f"refs/remotes/origin/{branch}"
    local_ref = f"refs/heads/{branch}"
    existing_worktree = pages_root.exists() and is_git_worktree(pages_root)
    local_exists_before_fetch = (
        run_command(
            ["git", "-C", str(repo_root), "show-ref", "--verify", "--quiet", local_ref]
        ).returncode
        == 0
    )

    fetch_result = run_command(
        ["git", "-C", str(repo_root), "fetch", "origin", branch],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    fetch_failed = fetch_result.returncode != 0

    remote_exists = (
        run_command(
            ["git", "-C", str(repo_root), "show-ref", "--verify", "--quiet", remote_ref]
        ).returncode
        == 0
    )
    local_exists = (
        run_command(
            ["git", "-C", str(repo_root), "show-ref", "--verify", "--quiet", local_ref]
        ).returncode
        == 0
    )

    if fetch_failed and not (
        existing_worktree or local_exists_before_fetch or local_exists
    ):
        raise SystemExit(
            f"Failed to fetch origin/{branch} and no local '{branch}' branch/worktree is available."
        )

    if not existing_worktree:
        remove_worktree_if_present(repo_root, pages_root)

        if remote_exists:
            if local_exists:
                run_command(
                    [
                        "git",
                        "-C",
                        str(repo_root),
                        "branch",
                        "-f",
                        branch,
                        f"origin/{branch}",
                    ],
                    check=True,
                )
            else:
                run_command(
                    [
                        "git",
                        "-C",
                        str(repo_root),
                        "branch",
                        "--track",
                        branch,
                        f"origin/{branch}",
                    ],
                    check=True,
                )
            run_command(
                [
                    "git",
                    "-C",
                    str(repo_root),
                    "worktree",
                    "add",
                    "--force",
                    str(pages_root),
                    branch,
                ],
                check=True,
            )
            run_command(
                ["git", "-C", str(pages_root), "reset", "--hard", f"origin/{branch}"],
                check=True,
            )
        elif local_exists:
            run_command(
                [
                    "git",
                    "-C",
                    str(repo_root),
                    "worktree",
                    "add",
                    "--force",
                    str(pages_root),
                    branch,
                ],
                check=True,
            )
            run_command(
                ["git", "-C", str(pages_root), "reset", "--hard", branch],
                check=True,
            )
        else:
            run_command(
                [
                    "git",
                    "-C",
                    str(repo_root),
                    "worktree",
                    "add",
                    "--detach",
                    str(pages_root),
                ],
                check=True,
            )
            run_command(
                ["git", "-C", str(pages_root), "checkout", "--orphan", branch],
                check=True,
            )
            run_command(
                ["git", "-C", str(pages_root), "rm", "-rf", "."],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    elif fetch_failed:
        print(
            f"Warning: failed to fetch origin/{branch}; reusing local worktree state."
        )


def prepare_stage_workspace(stage_root: Path, build_root: Path):
    shutil.rmtree(stage_root, ignore_errors=True)
    shutil.rmtree(build_root, ignore_errors=True)
    stage_root.parent.mkdir(parents=True, exist_ok=True)


def sync_build_output(build_root: Path, pages_root: Path):
    run_command(
        [
            "rsync",
            "-a",
            "--delete",
            "--exclude=.git",
            f"{build_root}/",
            f"{pages_root}/",
        ],
        check=True,
    )
    (pages_root / ".nojekyll").touch()
    shutil.rmtree(build_root, ignore_errors=True)


def run_docusaurus(repo_root: Path, stage_root: Path, out_dir: Path, command: str):
    env = os.environ.copy()
    env["BEMAN_WEBSITE_BRANCH"] = (
        run_command(
            ["git", "-C", str(repo_root), "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        or "main"
    )

    if command == "start":
        cmd = ["yarn", "docusaurus", "start"]
    elif command == "build":
        cmd = ["yarn", "docusaurus", "build", "--out-dir", str(out_dir)]
    else:
        cmd = ["yarn", "docusaurus", "serve", "--dir", str(out_dir)]

    run_command(cmd, cwd=stage_root, check=True, env=env)


def main():
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    default_work_root = Path(tempfile.gettempdir()) / "beman-website-work"
    work_root = Path(args.work_root) if args.work_root else default_work_root
    pages_root = Path(args.pages_root) if args.pages_root else repo_root / "build"
    stage_root = work_root / "site"
    build_root = work_root / "_build"

    prepare_stage_workspace(stage_root, build_root)
    stage_repo_content(repo_root, stage_root)
    sync_external_docs(repo_root, stage_root, args)

    ensure_pages_worktree(repo_root, pages_root, "gh-pages")

    if args.command == "start":
        run_docusaurus(repo_root, stage_root, build_root, "start")
        return

    run_docusaurus(repo_root, stage_root, build_root, "build")
    sync_build_output(build_root, pages_root)

    if args.command == "serve":
        run_docusaurus(repo_root, stage_root, pages_root, "serve")
    else:
        print(f"Built site output: {pages_root}")


if __name__ == "__main__":
    main()
