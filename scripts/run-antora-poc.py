#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

from __future__ import annotations

import argparse
import re
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path


WEBSITE_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = WEBSITE_ROOT.parent
OPTIONAL_REPO = WORKSPACE_ROOT / "optional"
WORK_ROOT = WEBSITE_ROOT / "build" / "antora-poc-work"
POC_REPO = WORK_ROOT / "optional-src"
POC_SITE = WEBSITE_ROOT / "build" / "antora-poc"
ANTORA_CACHE = WEBSITE_ROOT / "build" / "antora-cache"
PLAYBOOK = WEBSITE_ROOT / "antora-playbook.poc.yml"
OPTIONAL_REPO_URL = "https://github.com/bemanproject/optional"
MARKDOWN_LINK_RE = re.compile(
    r"(?P<prefix>!?\[[^\]]*\]\()(?P<href>[^\s)]+)(?P<suffix>(?:\s+[^)]*)?\))"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["build", "serve"], default="build")
    parser.add_argument("--port", type=int, default=8000)
    return parser.parse_args()


def run_command(*args, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(*args, **kwargs)  # nosec B603


def require_tool(name: str, install_hint: str) -> str:
    resolved = shutil.which(name)
    if resolved:
        return resolved
    raise SystemExit(f"Missing required tool: {name}\n{install_hint}")


def check_tools() -> None:
    require_tool(
        "pandoc",
        "Install in the beman environment with: micromamba install -n beman -c conda-forge pandoc",
    )
    require_tool(
        "mrdocs",
        "Install MrDocs v0.8.0 and ensure its bin directory is on PATH.",
    )
    require_tool("git", "Install git and ensure it is on PATH.")
    require_tool("npx", "Install Node.js/npm and run npm install in website/.")


def copy_optional_repo() -> None:
    if not OPTIONAL_REPO.exists():
        raise SystemExit(f"Missing optional checkout: {OPTIONAL_REPO}")
    if POC_REPO.exists():
        shutil.rmtree(POC_REPO)
    POC_REPO.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        OPTIONAL_REPO,
        POC_REPO,
        ignore=shutil.ignore_patterns(".git", "build", "docs/html", "docs/latex"),
    )


def split_link_target(href: str) -> tuple[str, str]:
    for separator in ("#", "?"):
        if separator in href:
            path, rest = href.split(separator, 1)
            return path, separator + rest
    return href, ""


def is_external_or_anchor(href: str) -> bool:
    return (
        not href
        or href.startswith("#")
        or href.startswith("/")
        or href.startswith("//")
        or bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", href))
    )


def normalize_repo_path(path: str) -> str:
    while path.startswith("./"):
        path = path[2:]
    return path


def github_url(path: str, is_image: bool) -> str:
    path = normalize_repo_path(path)
    if is_image:
        return f"{OPTIONAL_REPO_URL}/raw/main/{path}"
    kind = "tree" if path.endswith("/") or "." not in Path(path).name else "blob"
    return f"{OPTIONAL_REPO_URL}/{kind}/main/{path}"


def rewrite_markdown_links(content: str) -> str:
    local_pages = {
        "README.md": "readme.adoc",
        "docs/overview.md": "guide.adoc",
    }

    def replace(match: re.Match) -> str:
        href = match.group("href")
        if href.startswith("`") and href.endswith("`"):
            href = href[1:-1]
        if is_external_or_anchor(href):
            return match.group(0)

        path, suffix = split_link_target(href)
        normalized = normalize_repo_path(path)
        if normalized in local_pages:
            href = local_pages[normalized] + suffix
        else:
            href = github_url(path, match.group("prefix").startswith("!"))
            if suffix:
                href += suffix

        return f"{match.group('prefix')}{href}{match.group('suffix')}"

    blocks: list[str] = []
    in_fence = False
    for line in content.splitlines(keepends=True):
        if re.match(r"^\s*(```|~~~)", line):
            in_fence = not in_fence
            blocks.append(line)
            continue
        blocks.append(line if in_fence else MARKDOWN_LINK_RE.sub(replace, line))
    return "".join(blocks)


def convert_markdown_to_adoc(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_source = target.with_suffix(".md.tmp")
    temp_source.write_text(rewrite_markdown_links(source.read_text()))
    try:
        run_command(
            [
                "pandoc",
                "--from",
                "gfm",
                "--to",
                "asciidoc",
                "--wrap=none",
                str(temp_source),
                "-o",
                str(target),
            ],
            check=True,
        )
    finally:
        temp_source.unlink(missing_ok=True)
    normalize_converted_adoc(target)


def normalize_converted_adoc(target: Path) -> None:
    content = target.read_text()
    content = re.sub(r"link:(readme|guide)\.adoc\[([^\]]*)\]", r"xref:\1.adoc[\2]", content)
    target.write_text(content)


def write_antora_component() -> None:
    root_module = POC_REPO / "modules" / "ROOT"
    manual_pages = POC_REPO / "modules" / "manual" / "pages"
    root_module.mkdir(parents=True, exist_ok=True)
    manual_pages.mkdir(parents=True, exist_ok=True)
    write_mrdocs_helpers()
    (POC_REPO / "modules" / "ROOT" / "nav.adoc").write_text(
        "\n".join(
            [
                "* xref:manual:index.adoc[Overview]",
                "* xref:manual:readme.adoc[README]",
                "* xref:manual:guide.adoc[Guide]",
                "* xref:index.adoc[API Reference]",
                "",
            ]
        )
    )
    (manual_pages / "index.adoc").write_text(
        "\n".join(
            [
                "= beman.optional",
                "",
                "Links:",
                "",
                "* xref:readme.adoc[README]",
                "* xref:guide.adoc[Guide]",
                "* xref:ROOT:index.adoc[API Reference]",
                f"* {OPTIONAL_REPO_URL}[Repository]",
                "",
            ]
        )
    )
    convert_markdown_to_adoc(POC_REPO / "README.md", manual_pages / "readme.adoc")
    convert_markdown_to_adoc(POC_REPO / "docs" / "overview.md", manual_pages / "guide.adoc")
    (POC_REPO / "antora.yml").write_text(
        "\n".join(
            [
                "name: beman.optional",
                "title: beman.optional",
                "version: ~",
                "start_page: manual:index.adoc",
                "nav:",
                "  - modules/ROOT/nav.adoc",
                "ext:",
                "  collector:",
                "    - clean:",
                "        dir: docs/build/mrdocs-reference",
                "      run:",
                "        command: scripts/generate-antora-reference.sh",
                "      scan:",
                "        dir: docs/build/mrdocs-reference",
                "        into: modules/ROOT/pages",
                "        files: '**/*.adoc'",
                "",
            ]
        )
    )


def write_mrdocs_helpers() -> None:
    scripts_dir = POC_REPO / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    wrapper = scripts_dir / "generate-antora-reference.sh"
    wrapper.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                "set -eu",
                "mrdocs docs/mrdocs.yml --generator=adoc --output=build/mrdocs-reference",
                "python3 scripts/fix-mrdocs-antora.py docs/build/mrdocs-reference",
                "",
            ]
        )
    )
    wrapper.chmod(0o755)
    (scripts_dir / "fix-mrdocs-antora.py").write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "from pathlib import Path",
                "import sys",
                "",
                "root = Path(sys.argv[1])",
                "for path in list(root.rglob('_.adoc')):",
                "    path.rename(path.with_name('underscore.adoc'))",
                "for path in root.rglob('*.adoc'):",
                "    content = path.read_text()",
                "    content = content.replace('/_.adoc', '/underscore.adoc')",
                "    path.write_text(content)",
                "",
            ]
        )
    )


def init_git_repo() -> None:
    run_command(["git", "init", "--quiet"], cwd=POC_REPO, check=True)
    run_command(["git", "config", "user.name", "Beman Antora POC"], cwd=POC_REPO, check=True)
    run_command(["git", "config", "user.email", "beman-antora-poc@example.invalid"], cwd=POC_REPO, check=True)
    run_command(["git", "add", "."], cwd=POC_REPO, check=True)
    run_command(["git", "commit", "--quiet", "-m", "Create Antora POC content"], cwd=POC_REPO, check=True)


def build_antora() -> None:
    run_command(
        [
            "npx",
            "antora",
            "generate",
            str(PLAYBOOK),
            "--clean",
            "--stacktrace",
            "--cache-dir",
            str(ANTORA_CACHE),
        ],
        cwd=WEBSITE_ROOT,
        check=True,
    )


def serve_site(port: int) -> None:
    run_command(
        [sys.executable, "-m", "http.server", str(port), "--directory", str(POC_SITE)],
        check=True,
    )


def main() -> None:
    args = parse_args()
    check_tools()
    copy_optional_repo()
    write_antora_component()
    init_git_repo()
    build_antora()
    print(f"Built Antora POC: {POC_SITE}")
    if args.command == "serve":
        serve_site(args.port)


if __name__ == "__main__":
    main()
