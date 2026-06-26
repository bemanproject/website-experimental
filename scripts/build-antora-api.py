#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

from __future__ import annotations

import argparse
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path


WEBSITE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPOS_ROOT = WEBSITE_ROOT.parent
DEFAULT_WORK_ROOT = WEBSITE_ROOT / "build" / "antora-api-work"
DEFAULT_OUTPUT_DIR = WEBSITE_ROOT / "build" / "antora-api"
DEFAULT_CACHE_DIR = WEBSITE_ROOT / "build" / "antora-cache"

LIBRARIES = [
    {
        "repo": "optional",
        "component": "beman.optional",
        "title": "beman.optional",
        "mrdocs_config": "docs/mrdocs.yml",
    },
    {
        "repo": "cstring_view",
        "component": "beman.cstring_view",
        "title": "beman.cstring_view",
        "mrdocs_config": "docs/mrdocs.yml",
        "generated_mrdocs_config": """# $schema: https://mrdocs.com/docs/mrdocs/develop/_attachments/mrdocs.schema.json
# yaml-language-server: $schema=https://mrdocs.com/docs/mrdocs/develop/_attachments/mrdocs.schema.json

---
source-root: ..
input:
  - ../include
exclude:
  - ../tests/**
  - ../examples/**
includes:
  - ../include
file-patterns:
  - '*.hpp'
include-symbols:
  - 'beman::cstring_like'
  - 'beman::basic_cstring_view'
  - 'beman::cstring_view'
  - 'beman::u8cstring_view'
  - 'beman::u16cstring_view'
  - 'beman::u32cstring_view'
  - 'beman::wcstring_view'
  - 'beman::literals::cstring_view_literals::**'
multipage: true
generator: adoc
output: adoc
""",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repos-root",
        type=Path,
        default=DEFAULT_REPOS_ROOT,
        help="path to folder containing Beman library repositories",
    )
    parser.add_argument(
        "--work-root",
        type=Path,
        default=DEFAULT_WORK_ROOT,
        help="temporary Antora workspace",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="destination for generated Antora API HTML",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help="Antora cache directory",
    )
    parser.add_argument(
        "--site-url",
        default="http://localhost:8000/api/reference",
        help="public URL for the embedded Antora API reference",
    )
    parser.add_argument(
        "--clone-missing",
        action="store_true",
        help="clone missing library repositories before building API reference",
    )
    parser.add_argument(
        "--update-repos",
        action="store_true",
        help="update checked out library repositories before building API reference",
    )
    return parser.parse_args()


def run_command(*args, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(*args, **kwargs)  # nosec B603,B607


def require_tool(name: str, install_hint: str) -> None:
    if shutil.which(name):
        return
    raise SystemExit(f"Missing required tool: {name}\n{install_hint}")


def check_tools() -> None:
    require_tool("git", "Install git and ensure it is on PATH.")
    require_tool("mrdocs", "Install MrDocs and ensure it is on PATH.")
    require_tool("npx", "Install Node.js/npm and run npm install in website/.")


def ensure_source_repo(repo_path: Path, repo_name: str, clone_missing: bool, update_repos: bool) -> None:
    repo_url = f"https://github.com/bemanproject/{repo_name}"
    if not repo_path.exists() and clone_missing:
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        run_command(["git", "clone", "--branch", "main", "--single-branch", repo_url, str(repo_path)], check=True)

    if not repo_path.exists():
        raise SystemExit(f"Missing library checkout: {repo_path}")

    if update_repos:
        run_command(["git", "fetch", "origin", "main"], cwd=repo_path, check=True)
        run_command(["git", "checkout", "main"], cwd=repo_path, check=True)
        run_command(["git", "pull", "--ff-only", "origin", "main"], cwd=repo_path, check=True)


def copy_repo(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns(
            ".git",
            "build",
            "docs/html",
            "docs/latex",
            "docs/build",
            "__pycache__",
        ),
    )


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def write_mrdocs_helpers(repo_root: Path) -> None:
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    wrapper = scripts_dir / "generate-antora-reference.sh"
    write_text(
        wrapper,
        "\n".join(
            [
                "#!/bin/sh",
                "set -eu",
                "mrdocs docs/mrdocs.yml --generator=adoc --output=build/mrdocs-reference",
                "python3 scripts/fix-mrdocs-antora.py docs/build/mrdocs-reference",
                "",
            ]
        ),
    )
    wrapper.chmod(0o755)
    write_text(
        scripts_dir / "fix-mrdocs-antora.py",
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
        ),
    )


def write_antora_component(repo_root: Path, library: dict) -> None:
    mrdocs_config = repo_root / library["mrdocs_config"]
    if not mrdocs_config.exists() and library.get("generated_mrdocs_config"):
        write_text(mrdocs_config, library["generated_mrdocs_config"])
    if not mrdocs_config.exists():
        raise SystemExit(f"Missing MrDocs config for {library['component']}: {mrdocs_config}")

    write_mrdocs_helpers(repo_root)
    write_text(
        repo_root / "modules" / "ROOT" / "nav.adoc",
        "\n".join(
            [
                "* xref:index.adoc[API Reference]",
                "",
            ]
        ),
    )
    write_text(
        repo_root / "antora.yml",
        "\n".join(
            [
                f"name: {library['component']}",
                f"title: {library['title']}",
                "version: ~",
                "start_page: ROOT:index.adoc",
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
        ),
    )


def init_git_repo(repo_root: Path, component: str) -> None:
    run_command(["git", "init", "--quiet"], cwd=repo_root, check=True)
    run_command(["git", "config", "user.name", "Beman Antora API"], cwd=repo_root, check=True)
    run_command(["git", "config", "user.email", "beman-antora-api@example.invalid"], cwd=repo_root, check=True)
    run_command(["git", "add", "."], cwd=repo_root, check=True)
    run_command(["git", "commit", "--quiet", "-m", f"Create {component} Antora API content"], cwd=repo_root, check=True)


def write_playbook(work_root: Path, output_dir: Path, site_url: str) -> Path:
    supplemental_ui = write_supplemental_ui(work_root)
    sources = []
    for library in LIBRARIES:
        source_dir = work_root / "sources" / library["repo"]
        sources.extend(
            [
                f"    - url: {source_dir.as_posix()}",
                "      branches: HEAD",
            ]
        )

    playbook = work_root / "antora-playbook.yml"
    write_text(
        playbook,
        "\n".join(
            [
                "site:",
                "  title: Beman API Reference",
                f"  url: {site_url.rstrip('/')}",
                "  start_page: beman.optional::index.adoc",
                "",
                "content:",
                "  sources:",
                *sources,
                "",
                "antora:",
                "  extensions:",
                "    - '@antora/collector-extension'",
                "",
                "ui:",
                "  bundle:",
                "    url: https://gitlab.com/antora/antora-ui-default/-/jobs/artifacts/HEAD/raw/build/ui-bundle.zip?job=bundle-stable",
                "    snapshot: true",
                f"  supplemental_files: {supplemental_ui.as_posix()}",
                "",
                "output:",
                f"  dir: {output_dir.as_posix()}",
                "",
            ]
        ),
    )
    return playbook


def write_supplemental_ui(work_root: Path) -> Path:
    supplemental_ui = work_root / "supplemental-ui"
    write_text(
        supplemental_ui / "partials" / "header-content.hbs",
        "\n".join(
            [
                '<header class="header beman-api-header">',
                '  <nav class="navbar">',
                '    <div class="navbar-brand">',
                '      <a class="navbar-item beman-api-brand" href="/api/reference/">',
                '        <img src="/img/beman_logo.png" alt="The Beman Project Logo">',
                "        <span>Beman API Reference</span>",
                "      </a>",
                '      <button class="navbar-burger" aria-controls="topbar-nav" aria-expanded="false" aria-label="Toggle main menu">',
                "        <span></span>",
                "        <span></span>",
                "        <span></span>",
                "      </button>",
                "    </div>",
                '    <div id="topbar-nav" class="navbar-menu">',
                '      <div class="navbar-end">',
                '        <a class="navbar-item" href="/">Home</a>',
                '        <a class="navbar-item" href="/docs/">Docs</a>',
                '        <a class="navbar-item" href="/api/">API Reference</a>',
                '        <a class="navbar-item" href="/libraries/">Libraries</a>',
                '        <a class="navbar-item" href="/talks/">Talks</a>',
                '        <a class="navbar-item" href="/blog/">Blog</a>',
                "      </div>",
                "    </div>",
                "  </nav>",
                "</header>",
                "",
            ]
        ),
    )
    write_text(
        supplemental_ui / "partials" / "footer-content.hbs",
        "\n".join(
            [
                '<footer class="footer beman-api-footer">',
                "  <p>Copyright (C) The Beman Project. API reference generated with MrDocs and Antora.</p>",
                "</footer>",
                "",
            ]
        ),
    )
    write_text(
        supplemental_ui / "partials" / "head-styles.hbs",
        "\n".join(
            [
                '    <link rel="stylesheet" href="{{{uiRootPath}}}/css/site.css">',
                '    <link rel="stylesheet" href="{{{uiRootPath}}}/css/beman-api.css?v=1">',
                "",
            ]
        ),
    )
    write_text(
        supplemental_ui / "css" / "beman-api.css",
        "\n".join(
            [
                ":root {",
                "  --navbar-background: #fff;",
                "  --navbar-font-color: #1c1e21;",
                "  --navbar_hover-background: #f5f6f7;",
                "  --navbar-button-background: #2e8555;",
                "  --navbar-button-font-color: #fff;",
                "  --link-font-color: #2e8555;",
                "  --link_hover-font-color: #29784c;",
                "}",
                "",
                ".beman-api-header {",
                "  background: rgba(255, 255, 255, 0.97);",
                "  border-bottom: 1px solid #ebedf0;",
                "  box-shadow: none;",
                "  color: #1c1e21;",
                "}",
                "",
                ".beman-api-header .navbar {",
                "  background: rgba(255, 255, 255, 0.97);",
                "  color: #1c1e21;",
                "}",
                "",
                ".beman-api-header .navbar-brand .navbar-item,",
                ".beman-api-header .navbar-end .navbar-item {",
                "  color: #1c1e21;",
                "}",
                "",
                ".beman-api-header .navbar-end > a.navbar-item:hover {",
                "  background: #f5f6f7;",
                "  color: #2e8555;",
                "}",
                "",
                ".beman-api-header .navbar-burger span {",
                "  background-color: #1c1e21;",
                "}",
                "",
                ".beman-api-brand {",
                "  gap: 0.55rem;",
                "  font-weight: 700;",
                "}",
                "",
                ".beman-api-brand img {",
                "  width: 30px;",
                "  height: 30px;",
                "}",
                "",
                ".beman-api-footer {",
                "  background: #303846;",
                "  color: #fff;",
                "}",
                "",
                ".beman-api-footer p {",
                "  color: rgba(255, 255, 255, 0.85);",
                "}",
                "",
            ]
        ),
    )
    return supplemental_ui


def write_mkdocs_api_index(content_root: Path) -> None:
    lines = [
        "---",
        "title: API Reference",
        "---",
        "",
        "# API Reference",
        "",
        "Generated API reference is built by Antora from MrDocs AsciiDoc output and served inside the MkDocs site.",
        "",
        '<div class="api-library-grid">',
    ]
    for library in LIBRARIES:
        lines.extend(
            [
                '<article class="api-library-card">',
                f'  <h2>{library["title"]}</h2>',
                f'  <p>Reference pages generated from <code>{library["repo"]}/{library["mrdocs_config"]}</code>.</p>',
                f'  <a href="reference/{library["component"]}/index.html">Open API reference</a>',
                "</article>",
            ]
        )
    lines.extend(["</div>", ""])
    write_text(content_root / "api" / "index.md", "\n".join(lines))


def append_library_links(content_root: Path) -> None:
    for library in LIBRARIES:
        overview = content_root / "docs" / "Libraries" / library["repo"] / "index.md"
        if not overview.exists():
            continue
        content = overview.read_text()
        if "api/reference/" in content:
            continue
        content += (
            "\n\n## API Reference\n\n"
            f"[Open generated API reference](../../../api/reference/{library['component']}/index.html).\n"
        )
        overview.write_text(content)


def build_antora(playbook: Path, cache_dir: Path) -> None:
    run_command(
        [
            "npx",
            "antora",
            "generate",
            str(playbook),
            "--clean",
            "--stacktrace",
            "--cache-dir",
            str(cache_dir),
        ],
        cwd=WEBSITE_ROOT,
        check=True,
    )


def main() -> None:
    args = parse_args()
    check_tools()

    work_root = args.work_root.resolve()
    output_dir = args.output_dir.resolve()
    content_root = output_dir.parent.parent if output_dir.name == "reference" else output_dir.parent

    shutil.rmtree(work_root, ignore_errors=True)
    work_root.mkdir(parents=True, exist_ok=True)
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    for library in LIBRARIES:
        source_repo = args.repos_root / library["repo"]
        ensure_source_repo(source_repo, library["repo"], args.clone_missing, args.update_repos)
        staged_repo = work_root / "sources" / library["repo"]
        copy_repo(source_repo, staged_repo)
        write_antora_component(staged_repo, library)
        init_git_repo(staged_repo, library["component"])

    write_mkdocs_api_index(content_root)
    append_library_links(content_root)
    playbook = write_playbook(work_root, output_dir, args.site_url)
    build_antora(playbook, args.cache_dir.resolve())
    print(f"Built Antora API reference: {output_dir}")


if __name__ == "__main__":
    main()
