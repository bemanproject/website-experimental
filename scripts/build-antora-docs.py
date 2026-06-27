#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

from __future__ import annotations

import argparse
import posixpath
import re
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path

import yaml


WEBSITE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPOS_ROOT = WEBSITE_ROOT.parent
DEFAULT_WORK_ROOT = WEBSITE_ROOT / "build" / "antora-docs-work"
DEFAULT_OUTPUT_DIR = WEBSITE_ROOT / "build" / "docs"
DEFAULT_CACHE_DIR = WEBSITE_ROOT / "build" / "antora-cache"
MANIFEST_PATH = WEBSITE_ROOT / "scripts" / "sync-external-docs.yaml"

PROJECT_DOCS = [
    ("README.md", "index.adoc", "Beman Docs"),
    ("beman_library_maturity_model.md", "beman_library_maturity_model.adoc", "Beman Library Maturity Model"),
    ("beman_standard.md", "beman_standard.adoc", "Beman Standard"),
    ("mission.md", "mission.adoc", "Mission"),
    ("faq.md", "faq.adoc", "FAQ"),
    ("governance.md", "governance.adoc", "Governance"),
    ("code_of_conduct.md", "code_of_conduct.adoc", "Code of Conduct"),
]

SPECIAL_LABELS = {
    "debug-ci": "Debugging CI",
    "using_exemplar": "Using Exemplar",
    "using_cstring_view": "Guide",
    "design_rationale": "Design Rationale",
}

MRDOCS_CONFIG_PATH = "docs/mrdocs.yml"
MRDOCS_EXTRA_INCLUDES = {
    "task": ["../../execution/include"],
}


def render_mrdocs_config(repo_name: str, staged_repo: Path) -> str:
    includes = ["../include", *MRDOCS_EXTRA_INCLUDES.get(repo_name, [])]
    include_lines = "\n".join(f"  - {include}" for include in includes)
    return f"""# $schema: https://mrdocs.com/docs/mrdocs/develop/_attachments/mrdocs.schema.json
# yaml-language-server: $schema=https://mrdocs.com/docs/mrdocs/develop/_attachments/mrdocs.schema.json

---
source-root: ..
input:
  - ../include
exclude:
  - ../include/beman/{repo_name}/detail
  - ../tests/**
  - ../examples/**
exclude-patterns:
  - ../include/**/detail/**
  - ../tests/**
  - ../examples/**
includes:
{include_lines}
file-patterns:
  - '*.hpp'
  - '*.h'
include-symbols:
  - 'beman::**'
implementation-defined:
  - 'beman::detail'
  - 'beman::*::detail'
  - 'beman::*::detail::**'
multipage: true
generator: adoc
output: adoc
"""

MARKDOWN_LINK_RE = re.compile(
    r"(?P<prefix>!?\[[^\]]*\]\()(?P<href>[^\s)]+)(?P<suffix>(?:\s+[^)]*)?\))"
)
GITHUB_BLOB_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/blob/(?P<branch>[^/]+)/(?P<path>.+)$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repos-root", type=Path, default=DEFAULT_REPOS_ROOT)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--site-url", default="http://localhost:8000/docs")
    parser.add_argument("--clone-missing", action="store_true")
    parser.add_argument("--update-repos", action="store_true")
    parser.add_argument("--skip-api-reference", action="store_true")
    return parser.parse_args()


def run_command(*args, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(*args, **kwargs)  # nosec B603,B607


def require_tool(name: str, install_hint: str) -> None:
    if shutil.which(name):
        return
    raise SystemExit(f"Missing required tool: {name}\n{install_hint}")


def check_tools(skip_api_reference: bool) -> None:
    require_tool("git", "Install git and ensure it is on PATH.")
    require_tool("pandoc", "Install Pandoc and ensure it is on PATH.")
    require_tool("npx", "Install Node.js/npm and run npm install in website/.")
    if not skip_api_reference:
        require_tool("mrdocs", "Install MrDocs and ensure it is on PATH.")


def load_manifest() -> dict:
    return yaml.safe_load(MANIFEST_PATH.read_text()) or {}


def parse_file_entry(entry) -> tuple[Path, Path]:
    if isinstance(entry, str):
        source_rel = Path(entry)
        target_rel = (
            Path(*source_rel.parts[1:])
            if source_rel.parts and source_rel.parts[0] == "docs"
            else source_rel
        )
        return source_rel, target_rel.with_suffix(".adoc")
    if isinstance(entry, dict) and len(entry) == 1:
        [(source, target)] = entry.items()
        return Path(source), Path(target).with_suffix(".adoc")
    raise ValueError(f"Unsupported file entry: {entry!r}")


def make_sidebar_label(target_name: str) -> str:
    stem = Path(target_name).stem
    if stem.lower() == "readme":
        return "README"
    if stem.lower() == "overview":
        return "Guide"
    if stem in SPECIAL_LABELS:
        return SPECIAL_LABELS[stem]
    return stem.replace("_", " ").replace("-", " ").title()


def component_name(repo_name: str) -> str:
    return f"beman.{repo_name}"


def ensure_source_repo(
    repo_path: Path, repo_name: str, clone_missing: bool, update_repos: bool
) -> None:
    repo_url = f"https://github.com/bemanproject/{repo_name}"
    if not repo_path.exists() and clone_missing:
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        run_command(
            ["git", "clone", "--branch", "main", "--single-branch", repo_url, str(repo_path)],
            check=True,
        )

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


def prepare_staged_mrdocs_inputs(staged_repo: Path, repo_name: str) -> Path:
    if repo_name == "transform_view":
        write_text(
            staged_repo
            / "include"
            / "beman"
            / "transform_view"
            / "config_generated.hpp",
            "\n".join(
                [
                    "// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception",
                    "",
                    "#ifndef BEMAN_TRANSFORM_VIEW_CONFIG_GENERATED_HPP",
                    "#define BEMAN_TRANSFORM_VIEW_CONFIG_GENERATED_HPP",
                    "",
                    "#define BEMAN_TRANSFORM_VIEW_USE_MODULES() 0",
                    "",
                    "#endif",
                    "",
                ]
            ),
        )

    mrdocs_config = staged_repo / MRDOCS_CONFIG_PATH
    if not mrdocs_config.exists():
        write_text(mrdocs_config, render_mrdocs_config(repo_name, staged_repo))
    return mrdocs_config


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def strip_frontmatter(content: str) -> str:
    if not content.startswith("---\n"):
        return content
    end = content.find("\n---\n", 4)
    if end == -1:
        return content
    return content[end + len("\n---\n") :].lstrip("\n")


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
        or href.startswith("//")
        or bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", href))
    )


def normalize_repo_relative_path(path: str) -> str:
    return path.removeprefix("./")


def rewrite_markdown_links_outside_fences(content: str, replacer) -> str:
    rewritten_blocks = []
    in_fence = False
    for line in content.splitlines(keepends=True):
        if re.match(r"^\s*(```|~~~)", line):
            in_fence = not in_fence
            rewritten_blocks.append(line)
            continue
        rewritten_blocks.append(line if in_fence else MARKDOWN_LINK_RE.sub(replacer, line))
    return "".join(rewritten_blocks)


def rewrite_github_blob_image_links(content: str) -> str:
    def replace(match: re.Match) -> str:
        if not match.group("prefix").startswith("!"):
            return match.group(0)

        href = match.group("href")
        pathless_href, suffix = split_link_target(href)
        github_match = GITHUB_BLOB_URL_RE.match(pathless_href)
        if not github_match:
            return match.group(0)

        href = (
            "https://raw.githubusercontent.com/"
            f"{github_match.group('owner')}/"
            f"{github_match.group('repo')}/"
            f"{github_match.group('branch')}/"
            f"{github_match.group('path')}"
            f"{suffix}"
        )
        return f"{match.group('prefix')}{href}{match.group('suffix')}"

    return rewrite_markdown_links_outside_fences(content, replace)


def github_relative_url(repo_url: str, repo_branch: str, path: str, is_image: bool) -> str:
    if is_image:
        return f"{repo_url}/raw/{repo_branch}/{path}"
    kind = "tree" if path.endswith("/") or "." not in Path(path).name else "blob"
    return f"{repo_url}/{kind}/{repo_branch}/{path}"


def rewrite_library_markdown_links(
    content: str,
    repo_url: str,
    repo_branch: str,
    source_link_map: dict[str, str],
    source_rel: Path,
) -> str:
    source_dir = source_rel.parent.as_posix()

    def candidate_repo_paths(path: str) -> list[str]:
        normalized = normalize_repo_relative_path(path)
        candidates = [normalized]
        if source_dir and source_dir != ".":
            candidates.append(posixpath.normpath(posixpath.join(source_dir, path)))
        return list(dict.fromkeys(candidates))

    def replace(match: re.Match) -> str:
        href = match.group("href")
        if href.startswith("`") and href.endswith("`"):
            href = href[1:-1]
        if is_external_or_anchor(href):
            return match.group(0)

        path, suffix = split_link_target(href)
        candidates = candidate_repo_paths(path)
        synced_path = next((candidate for candidate in candidates if candidate in source_link_map), "")
        if synced_path:
            href = source_link_map[synced_path] + suffix
        else:
            href = github_relative_url(
                repo_url,
                repo_branch,
                candidates[-1],
                is_image=match.group("prefix").startswith("!"),
            )
            if suffix:
                href += suffix

        return f"{match.group('prefix')}{href}{match.group('suffix')}"

    return rewrite_markdown_links_outside_fences(content, replace)


def rewrite_project_markdown_links(
    content: str, source_rel: Path, source_link_map: dict[str, str]
) -> str:
    replacements = {
        "](/images/": "](images/",
        "](../images/": "](images/",
    }
    for old, new in replacements.items():
        content = content.replace(old, new)
    content = rewrite_github_blob_image_links(content)
    source_dir = source_rel.parent.as_posix()

    def candidate_project_paths(path: str) -> list[str]:
        normalized = normalize_repo_relative_path(path).removeprefix("docs/")
        candidates = [normalized]
        if source_dir and source_dir != ".":
            candidates.append(posixpath.normpath(posixpath.join(source_dir, normalized)))
        return list(dict.fromkeys(candidates))

    def replace(match: re.Match) -> str:
        href = match.group("href")
        if is_external_or_anchor(href) or match.group("prefix").startswith("!"):
            return match.group(0)

        path, suffix = split_link_target(href)
        synced_path = next(
            (
                candidate
                for candidate in candidate_project_paths(path)
                if candidate in source_link_map
            ),
            "",
        )
        if not synced_path:
            return match.group(0)

        href = source_link_map[synced_path] + suffix
        return f"{match.group('prefix')}{href}{match.group('suffix')}"

    return rewrite_markdown_links_outside_fences(content, replace)


def normalize_adoc_heading_sequence(content: str) -> str:
    lines = []
    previous_level = 1
    in_delimited_block = False
    for line in content.splitlines():
        if line.strip() in {"----", "....", "===="}:
            in_delimited_block = not in_delimited_block
            lines.append(line)
            continue

        match = re.match(r"^(={2,6})\s+(.+)$", line)
        if match and not in_delimited_block:
            level = len(match.group(1))
            if level > previous_level + 1:
                level = previous_level + 1
                line = f"{'=' * level} {match.group(2)}"
            previous_level = level
        lines.append(line)
    return "\n".join(lines) + ("\n" if content.endswith("\n") else "")


def postprocess_pandoc_adoc(content: str) -> str:
    content = content.replace("link:xref:", "xref:")
    content = re.sub(r"link:([A-Za-z0-9_./-]+\.adoc)(#[^\[]*)?\[", r"xref:\1\2[", content)
    content = content.replace("\\_", "_")
    return content


def convert_markdown_to_adoc_content(markdown: str, title: str, scratch: Path) -> str:
    scratch.parent.mkdir(parents=True, exist_ok=True)
    temp_md = scratch.with_suffix(".tmp.md")
    temp_adoc = scratch.with_suffix(".tmp.adoc")
    temp_md.write_text(markdown)
    try:
        run_command(
            [
                "pandoc",
                "-f",
                "gfm",
                "-t",
                "asciidoc",
                "--wrap=none",
                "-o",
                str(temp_adoc),
                str(temp_md),
            ],
            check=True,
        )
        content = postprocess_pandoc_adoc(temp_adoc.read_text())
    finally:
        temp_md.unlink(missing_ok=True)
        temp_adoc.unlink(missing_ok=True)

    content = normalize_adoc_heading_sequence(content)
    if not content.lstrip().startswith("= "):
        content = f"= {title}\n\n{content}"
    return content


def strip_adoc_document_title(content: str) -> str:
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if not line.startswith("= "):
            return content
        body = lines[index + 1 :]
        while body and not body[0].strip():
            body = body[1:]
        return "\n".join(body) + ("\n" if body else "")
    return content


def convert_markdown_to_adoc(markdown: str, target: Path, title: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(convert_markdown_to_adoc_content(markdown, title, target))


def convert_readme_to_overview_body(markdown: str, scratch: Path, title: str) -> str:
    return strip_adoc_document_title(
        convert_markdown_to_adoc_content(markdown, title, scratch)
    )


def legacy_readme_targets() -> dict[str, str]:
    return {
        "README.md": "index.adoc",
        "readme.md": "index.adoc",
        "./README.md": "index.adoc",
        "./readme.md": "index.adoc",
    }


def init_git_repo(repo_root: Path, message: str) -> None:
    run_command(["git", "init", "--quiet"], cwd=repo_root, check=True)
    run_command(["git", "config", "user.name", "Beman Antora Docs"], cwd=repo_root, check=True)
    run_command(["git", "config", "user.email", "beman-antora-docs@example.invalid"], cwd=repo_root, check=True)
    run_command(["git", "add", "."], cwd=repo_root, check=True)
    run_command(["git", "commit", "--quiet", "-m", message], cwd=repo_root, check=True)


def build_library_docs(manifest: dict, repos_root: Path, clone_missing: bool, update_repos: bool) -> list[dict]:
    libraries = []
    for repo_name, raw_config in manifest.items():
        config = raw_config or {}
        repo_path = repos_root / repo_name
        ensure_source_repo(repo_path, repo_name, clone_missing, update_repos)

        readme_source = (
            Path("README.md") if (repo_path / "README.md").exists() else None
        )
        docs = []
        for entry in config.get("files", []):
            source_rel, target_rel = parse_file_entry(entry)
            docs.append(
                {
                    "source_rel": source_rel,
                    "target_rel": target_rel,
                    "label": make_sidebar_label(target_rel.name),
                }
            )

        libraries.append(
            {
                "repo": repo_name,
                "repo_path": repo_path,
                "component": component_name(repo_name),
                "title": f"beman.{repo_name}",
                "readme_source": readme_source,
                "docs": docs,
                "repo_url": f"https://github.com/bemanproject/{repo_name}",
                "repo_branch": "main",
                "has_api": (repo_path / "include").exists(),
            }
        )
    return libraries


def write_global_nav(libraries: list[dict], skip_api_reference: bool) -> str:
    lines = [
        "* Project",
        "** xref:beman:ROOT:index.adoc[Overview]",
        "** xref:beman:ROOT:beman_library_maturity_model.adoc[Beman Library Maturity Model]",
        "** xref:beman:ROOT:beman_standard.adoc[Beman Standard]",
        "** xref:beman:ROOT:mission.adoc[Mission]",
        "** xref:beman:ROOT:faq.adoc[FAQ]",
        "** xref:beman:ROOT:governance.adoc[Governance]",
        "** xref:beman:ROOT:code_of_conduct.adoc[Code of Conduct]",
        "* Libraries",
    ]
    for library in libraries:
        lines.append(f"** {library['title']}")
        lines.append(f"*** xref:{library['component']}:ROOT:index.adoc[Overview]")
        for doc in library["docs"]:
            lines.append(
                f"*** xref:{library['component']}:ROOT:{doc['target_rel'].as_posix()}[{doc['label']}]"
            )
        if library["has_api"] and not skip_api_reference:
            lines.append(f"*** xref:{library['component']}:ROOT:reference/index.adoc[API Reference]")
    return "\n".join(lines) + "\n"


def write_project_component(work_root: Path, global_nav: str) -> Path:
    component_root = work_root / "sources" / "beman-docs"
    pages_root = component_root / "modules" / "ROOT" / "pages"
    assets_root = component_root / "modules" / "ROOT" / "assets" / "images" / "images"
    assets_root.mkdir(parents=True, exist_ok=True)
    for source in (WEBSITE_ROOT / "static" / "images").rglob("*"):
        if source.is_file():
            target = assets_root / source.relative_to(WEBSITE_ROOT / "static" / "images")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    for source in (WEBSITE_ROOT / "docs" / "images").rglob("*"):
        if source.is_file():
            target = assets_root / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    source_link_map = {
        source_name: target_name for source_name, target_name, _title in PROJECT_DOCS
    }
    for source_name, target_name, title in PROJECT_DOCS:
        markdown = strip_frontmatter((WEBSITE_ROOT / "docs" / source_name).read_text())
        markdown = rewrite_project_markdown_links(
            markdown, Path(source_name), source_link_map
        )
        convert_markdown_to_adoc(markdown, pages_root / target_name, title)

    write_text(component_root / "modules" / "ROOT" / "nav.adoc", global_nav)
    write_text(
        component_root / "antora.yml",
        "\n".join(
            [
                "name: beman",
                "title: Beman Project",
                "version: latest",
                "display_version: latest",
                "start_page: ROOT:index.adoc",
                "nav:",
                "  - modules/ROOT/nav.adoc",
                "",
            ]
        ),
    )
    init_git_repo(component_root, "Create Beman project Antora docs")
    return component_root


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
                "if ! mrdocs docs/mrdocs.yml --generator=adoc --output=build/mrdocs-reference --ignore-failures --ignore-map-errors; then",
                "  test -f docs/build/mrdocs-reference/index.adoc",
                "fi",
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
                "import posixpath",
                "import re",
                "import sys",
                "",
                "root = Path(sys.argv[1])",
                "",
                "def safe_component(name):",
                "    stem = Path(name).stem",
                "    suffix = ''.join(Path(name).suffixes)",
                "    if not stem.startswith('_'):",
                "        return name",
                "    leading = len(stem) - len(stem.lstrip('_'))",
                "    safe_stem = '_'.join(['underscore'] * leading + [stem.lstrip('_') or 'symbol'])",
                "    return safe_stem + suffix",
                "",
                "def safe_target_path(target):",
                "    return '/'.join(safe_component(part) for part in target.split('/'))",
                "",
                "for path in sorted(root.rglob('*'), key=lambda p: len(p.relative_to(root).parts), reverse=True):",
                "    safe_name = safe_component(path.name)",
                "    if safe_name != path.name:",
                "        path.rename(path.with_name(safe_name))",
                "",
                "def rewrite_xref(match):",
                "    target = match.group(1)",
                "    anchor = match.group(2) or ''",
                "    if ':' in target:",
                "        return match.group(0)",
                "    normalized = posixpath.normpath(target).lstrip('./')",
                "    while normalized.startswith('../'):",
                "        normalized = normalized[3:]",
                "    if normalized.startswith('reference/'):",
                "        normalized = normalized.removeprefix('reference/')",
                "    normalized = safe_target_path(normalized)",
                "    return f'xref:reference/{normalized}{anchor}['",
                "",
                "for path in root.rglob('*.adoc'):",
                "    content = path.read_text()",
                "    content = re.sub(r'xref:([A-Za-z0-9_./-]+\\.adoc)(#[^\\[]*)?\\[', rewrite_xref, content)",
                "    path.write_text(content)",
                "",
            ]
        ),
    )


def write_library_component(
    work_root: Path, library: dict, global_nav: str, skip_api_reference: bool
) -> Path:
    staged_repo = work_root / "sources" / library["repo"]
    copy_repo(library["repo_path"], staged_repo)

    pages_root = staged_repo / "modules" / "ROOT" / "pages"
    pages_root.mkdir(parents=True, exist_ok=True)
    source_link_map = legacy_readme_targets() if library["readme_source"] else {}
    source_link_map.update(
        {
            doc["source_rel"].as_posix(): doc["target_rel"].as_posix()
            for doc in library["docs"]
        }
    )

    overview_lines = [
        f"= {library['title']}",
        "",
        f"* Repository: {library['repo_url']}",
    ]
    for doc in library["docs"]:
        overview_lines.append(f"* xref:{doc['target_rel'].as_posix()}[{doc['label']}]")
    if library["has_api"] and not skip_api_reference:
        overview_lines.append("* xref:reference/index.adoc[API Reference]")

    index_content = "\n".join(overview_lines) + "\n"
    if library["readme_source"]:
        readme_source = staged_repo / library["readme_source"]
        if readme_source.exists():
            markdown = strip_frontmatter(readme_source.read_text())
            markdown = rewrite_github_blob_image_links(markdown)
            markdown = rewrite_library_markdown_links(
                markdown,
                library["repo_url"],
                library["repo_branch"],
                source_link_map,
                library["readme_source"],
            )
            readme_body = convert_readme_to_overview_body(
                markdown, pages_root / "index-readme.adoc", library["title"]
            )
            if readme_body.strip():
                index_content += "\n" + readme_body
    write_text(pages_root / "index.adoc", index_content)

    for doc in library["docs"]:
        source = staged_repo / doc["source_rel"]
        if not source.exists():
            print(f"Missing library markdown source: {source}")
            continue
        markdown = strip_frontmatter(source.read_text())
        markdown = rewrite_github_blob_image_links(markdown)
        markdown = rewrite_library_markdown_links(
            markdown,
            library["repo_url"],
            library["repo_branch"],
            source_link_map,
            doc["source_rel"],
        )
        convert_markdown_to_adoc(markdown, pages_root / doc["target_rel"], doc["label"])

    write_text(staged_repo / "modules" / "ROOT" / "nav.adoc", global_nav)
    antora_lines = [
        f"name: {library['component']}",
        f"title: {library['title']}",
        "version: latest",
        "display_version: latest",
        "start_page: ROOT:index.adoc",
        "nav:",
        "  - modules/ROOT/nav.adoc",
    ]

    if library["has_api"] and not skip_api_reference:
        mrdocs_config = prepare_staged_mrdocs_inputs(staged_repo, library["repo"])
        if mrdocs_config.exists():
            write_mrdocs_helpers(staged_repo)
            antora_lines.extend(
                [
                    "ext:",
                    "  collector:",
                    "    - clean:",
                    "        dir: docs/build/mrdocs-reference",
                    "      run:",
                    "        command: scripts/generate-antora-reference.sh",
                    "      scan:",
                    "        dir: docs/build/mrdocs-reference",
                    "        into: modules/ROOT/pages/reference",
                    "        files: '**/*.adoc'",
                ]
            )
        else:
            print(f"Skipping API reference for {library['title']}: missing {mrdocs_config}")

    write_text(staged_repo / "antora.yml", "\n".join(antora_lines) + "\n")
    init_git_repo(staged_repo, f"Create {library['title']} Antora docs")
    return staged_repo


def write_supplemental_ui(work_root: Path) -> Path:
    supplemental_ui = work_root / "supplemental-ui"
    write_text(
        supplemental_ui / "partials" / "header-content.hbs",
        "\n".join(
            [
                '<header class="header site-header">',
                '  <nav class="navbar site-nav" aria-label="Main navigation">',
                '    <a class="brand" href="{{{siteRootPath}}}/../">',
                '      <img src="{{{siteRootPath}}}/../img/beman_logo.png" alt="The Beman Project Logo">',
                "      <span>The Beman Project</span>",
                "    </a>",
                '    <button class="navbar-burger site-nav-toggle" aria-controls="topbar-nav" aria-expanded="false" aria-label="Toggle main menu">',
                "      <span></span>",
                "      <span></span>",
                "      <span></span>",
                "    </button>",
                '    <div class="nav-menu navbar-menu" id="topbar-nav">',
                '      <div class="nav-links navbar-end">',
                '        <a class="navbar-item" href="{{{siteRootPath}}}/../">Home</a>',
                '        <a class="navbar-item active" href="{{{siteRootPath}}}/">Docs</a>',
                '        <a class="navbar-item" href="{{{siteRootPath}}}/../libraries/">Libraries</a>',
                '        <a class="navbar-item" href="{{{siteRootPath}}}/../talks/">Talks</a>',
                '        <a class="navbar-item" href="{{{siteRootPath}}}/../blog/">Blog</a>',
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
                '<footer class="site-footer">',
                "  <div>",
                "    <h2>Community</h2>",
                '    <a href="https://discord.com/invite/BKpNyJgSbm">Discord</a>',
                '    <a href="https://discourse.bemanproject.org/">Discourse</a>',
                "  </div>",
                "  <div>",
                "    <h2>More</h2>",
                '    <a href="https://github.com/bemanproject">GitHub</a>',
                "  </div>",
                "  <p>Copyright (C) The Beman Project. Built with Antora.</p>",
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
                '    <link rel="stylesheet" href="{{{uiRootPath}}}/css/beman-docs.css?v=6">',
                "",
            ]
        ),
    )
    write_text(
        supplemental_ui / "css" / "beman-docs.css",
        "\n".join(
            [
                ":root {",
                "  --ifm-color-primary: #2e8555;",
                "  --ifm-color-primary-dark: #29784c;",
                "  --ifm-color-content: #1c1e21;",
                "  --ifm-color-content-secondary: #525860;",
                "  --ifm-color-emphasis-100: #f5f6f7;",
                "  --ifm-color-emphasis-200: #ebedf0;",
                "  --ifm-color-emphasis-300: #dadde1;",
                "  --page-max: 1320px;",
                "  --content-max: 900px;",
                "  --nav-height: 60px;",
                "  --body-font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;",
                "  color-scheme: light;",
                "}",
                "",
                "*, *::before, *::after { box-sizing: border-box; }",
                "",
                "body.article {",
                "  display: flex;",
                "  flex-direction: column;",
                "  height: 100dvh;",
                "  min-height: 100vh;",
                "  margin: 0;",
                "  padding-top: 0;",
                "  overflow: hidden;",
                "  color: var(--ifm-color-content);",
                "  font-family: var(--body-font-family);",
                "  font-size: 16px;",
                "  line-height: 1.65;",
                "  background: #fff;",
                "}",
                "",
                "a { color: var(--ifm-color-primary); text-decoration: none; }",
                "a:hover { text-decoration: underline; }",
                "",
                ".site-header.header {",
                "  display: block;",
                "  flex: 0 0 var(--nav-height);",
                "  position: static;",
                "  top: 0;",
                "  z-index: 20;",
                "  height: var(--nav-height);",
                "  border-bottom: 1px solid var(--ifm-color-emphasis-200);",
                "  background: rgba(255, 255, 255, 0.97);",
                "  box-shadow: none;",
                "}",
                ".site-nav.navbar {",
                "  display: flex;",
                "  position: static;",
                "  align-items: center;",
                "  max-width: var(--page-max);",
                "  height: 100%;",
                "  min-height: 0;",
                "  margin: 0 auto;",
                "  padding: 0 1rem;",
                "  gap: 1rem;",
                "  background: transparent;",
                "}",
                ".brand {",
                "  display: inline-flex;",
                "  align-items: center;",
                "  gap: 0.6rem;",
                "  color: var(--ifm-color-content);",
                "  font-weight: 700;",
                "  white-space: nowrap;",
                "}",
                ".brand:hover { text-decoration: none; }",
                ".brand img { width: 32px; height: 32px; }",
                ".nav-menu.navbar-menu {",
                "  display: flex;",
                "  position: static;",
                "  align-items: center;",
                "  justify-content: space-between;",
                "  flex: 1;",
                "  height: auto;",
                "  min-height: 0;",
                "  min-width: 0;",
                "  padding: 0;",
                "  background: transparent;",
                "  box-shadow: none;",
                "}",
                ".nav-links { display: flex; align-items: center; gap: 0.2rem; }",
                ".nav-links a.navbar-item {",
                "  padding: 0.45rem 0.75rem;",
                "  border-radius: 4px;",
                "  color: var(--ifm-color-content);",
                "  font-weight: 500;",
                "}",
                ".nav-links a.navbar-item:hover, .nav-links a.navbar-item.active {",
                "  color: var(--ifm-color-primary);",
                "  text-decoration: none;",
                "  background: transparent;",
                "}",
                ".site-nav-toggle {",
                "  display: none;",
                "  margin-left: auto;",
                "  border: 1px solid var(--ifm-color-emphasis-300);",
                "  border-radius: 4px;",
                "  background: #fff;",
                "  padding: 0.35rem 0.6rem;",
                "  color: var(--ifm-color-content);",
                "  font: inherit;",
                "}",
                ".site-nav-toggle span {",
                "  display: block;",
                "  width: 1rem;",
                "  height: 2px;",
                "  border-radius: 999px;",
                "  background: var(--ifm-color-content);",
                "}",
                ".site-nav-toggle span + span { margin-top: 0.25rem; }",
                ".site-nav-toggle.is-active span:nth-child(1) { transform: translateY(6px) rotate(45deg); }",
                ".site-nav-toggle.is-active span:nth-child(2) { opacity: 0; }",
                ".site-nav-toggle.is-active span:nth-child(3) { transform: translateY(-6px) rotate(-45deg); }",
                "",
                ".body {",
                "  display: grid;",
                "  grid-template-columns: minmax(210px, 260px) minmax(0, var(--content-max)) minmax(160px, 220px);",
                "  gap: 2rem;",
                "  flex: 1 1 auto;",
                "  max-width: var(--page-max);",
                "  width: 100%;",
                "  min-height: 0;",
                "  margin: 0 auto;",
                "  padding: 1rem;",
                "  overflow: hidden;",
                "}",
                ".nav-container { position: static; width: auto; min-height: 0; grid-column: 1; }",
                ".nav-container .nav {",
                "  position: static;",
                "  height: 100%;",
                "  max-height: none;",
                "  width: auto;",
                "  overflow: auto;",
                "  background: transparent;",
                "  color: var(--ifm-color-content-secondary);",
                "  font-size: 0.88rem;",
                "}",
                ".nav-container .panels { display: block; }",
                ".nav-panel-menu { display: block; position: static; visibility: visible; transform: none; }",
                ".nav-panel-explore { display: none; }",
                ".nav-menu .title { display: none; }",
                ".nav-list { list-style: none; margin: 0; padding: 0; }",
                ".nav-list .nav-list { margin-left: 0.75rem; padding-left: 0.75rem; border-left: 1px solid var(--ifm-color-emphasis-200); }",
                ".nav-item { margin: 0.15rem 0; }",
                ".nav-link, .nav-text {",
                "  display: block;",
                "  padding: 0.2rem 1.25rem 0.2rem 0;",
                "  color: var(--ifm-color-content-secondary);",
                "  line-height: 1.45;",
                "}",
                ".nav-text { font-weight: 600; }",
                ".nav-link:hover, .nav-item.is-current-page > .nav-link, .nav-item.is-current-path > .nav-link, .nav-item.is-current-path > .nav-text {",
                "  color: var(--ifm-color-primary);",
                "  font-weight: 600;",
                "  text-decoration: none;",
                "}",
                ".nav-item-toggle {",
                "  top: 0.25rem;",
                "  right: 0;",
                "  width: 1rem;",
                "  height: 1rem;",
                "}",
                ".nav-item-toggle::before { background: var(--ifm-color-content-secondary); }",
                ".nav-menu-toggle { display: none !important; }",
                "",
                "main.article { grid-column: 2 / 4; min-width: 0; min-height: 0; overflow: hidden; padding: 0; }",
                "main.article .content {",
                "  display: grid;",
                "  grid-template-columns: minmax(0, var(--content-max)) minmax(180px, 220px);",
                "  gap: 2rem;",
                "  align-items: start;",
                "  height: 100%;",
                "  min-height: 0;",
                "  max-width: none;",
                "  overflow: hidden;",
                "  padding: 0;",
                "}",
                "article.doc { grid-column: 1; grid-row: 1; min-width: 0; max-width: none; height: 100%; overflow-x: hidden; overflow-y: auto; padding-right: 0.5rem; color: var(--ifm-color-content); scrollbar-gutter: stable; }",
                "article.doc h1.page:first-child { margin-top: 0; }",
                "article.doc h1, article.doc h2, article.doc h3 { color: var(--ifm-color-content); }",
                "article.doc p, article.doc li { overflow-wrap: anywhere; }",
                "article.doc code {",
                "  padding: 0.1rem 0.25rem;",
                "  border-radius: 4px;",
                "  background: var(--ifm-color-emphasis-100);",
                "  font-size: 0.92em;",
                "  overflow-wrap: anywhere;",
                "}",
                "article.doc img { max-width: 100%; height: auto; }",
                "article.doc pre { max-width: 100%; overflow-x: auto; border-radius: 6px; background: #f6f8fa; }",
                "article.doc table.tableblock { display: block; width: 100%; overflow-x: auto; border-collapse: collapse; }",
                "article.doc th, article.doc td { border-color: var(--ifm-color-emphasis-300); }",
                ".toolbar { display: none; }",
                "",
                "aside.toc.sidebar {",
                "  position: static;",
                "  grid-column: 2;",
                "  grid-row: 1;",
                "  height: 100%;",
                "  max-height: none;",
                "  width: auto;",
                "  min-width: 0;",
                "  overflow: auto;",
                "  color: var(--ifm-color-content-secondary);",
                "  font-size: 0.88rem;",
                "}",
                ".toc-menu h3 { margin-top: 0; color: var(--ifm-color-content); font-size: 0.9rem; }",
                ".toc-menu ul { list-style: none; margin: 0; padding: 0; }",
                ".toc-menu a { color: var(--ifm-color-content-secondary); }",
                ".toc-menu a.is-active, .toc-menu a:hover { color: var(--ifm-color-primary); text-decoration: none; }",
                "",
                ".site-footer {",
                "  display: none;",
                "  grid-template-columns: repeat(2, minmax(0, 180px)) 1fr;",
                "  gap: 1.5rem;",
                "  margin: 0;",
                "  padding: 2rem max(1rem, calc((100vw - var(--page-max)) / 2 + 1rem));",
                "  background: #303846;",
                "  color: #fff;",
                "}",
                ".site-footer h2 { margin: 0 0 0.5rem; font-size: 1rem; color: #fff; }",
                ".site-footer a { display: block; color: #fff; }",
                ".site-footer p { align-self: end; justify-self: end; margin: 0; color: rgba(255,255,255,0.8); }",
                "",
                "@media (max-width: 1100px) {",
                "  .body { grid-template-columns: minmax(190px, 240px) minmax(0, 1fr); }",
                "  main.article { grid-column: 2; }",
                "  main.article .content { display: block; overflow: hidden; }",
                "  aside.toc.sidebar { display: none; }",
                "}",
                "@media (max-width: 760px) {",
                "  body.article { height: auto; min-height: 100vh; overflow: auto; }",
                "  .site-header.header { flex: none; height: auto; }",
                "  .site-nav.navbar { flex-wrap: wrap; min-height: var(--nav-height); }",
                "  .site-nav-toggle { display: inline-flex; flex-direction: column; align-items: center; justify-content: center; width: 2.75rem; height: 2.75rem; }",
                "  .nav-menu.navbar-menu { display: none; flex-basis: 100%; flex-direction: column; align-items: stretch; padding-bottom: 0.75rem; }",
                "  .nav-menu.navbar-menu.is-active { display: flex; }",
                "  .nav-links { align-items: stretch; flex-direction: column; width: 100%; margin-left: 0; }",
                "  .body { display: block; position: relative; min-height: 0; overflow: visible; padding-top: 1.25rem; }",
                "  .toolbar { display: flex; position: static; height: auto; margin-bottom: 1rem; padding: 0; background: transparent; box-shadow: none; }",
                "  .toolbar .home-link, .toolbar .breadcrumbs, .toolbar .edit-this-page { display: none; }",
                "  .toolbar .nav-toggle { display: inline-flex; align-items: center; justify-content: space-between; width: 100%; min-height: 2.75rem; margin: 0; padding: 0.65rem 0.85rem; border: 1px solid var(--ifm-color-emphasis-300); border-radius: 6px; background: #fff; color: var(--ifm-color-content); font-weight: 600; }",
                "  .toolbar .nav-toggle::before { content: 'Docs navigation'; }",
                "  .toolbar .nav-toggle::after { content: ''; width: 0.55rem; height: 0.55rem; border-right: 2px solid currentColor; border-bottom: 2px solid currentColor; transform: rotate(45deg); transition: transform 0.15s ease; }",
                "  .toolbar .nav-toggle.is-active::after { transform: rotate(-135deg); }",
                "  .nav-container { display: none; position: absolute; top: calc(1.25rem + 2.75rem + 0.75rem); left: 1rem; right: 1rem; z-index: 30; width: auto; margin-bottom: 0; visibility: visible; }",
                "  .nav-container.is-active { display: block; }",
                "  .nav-container .nav { height: auto !important; max-height: min(70vh, 34rem); margin-bottom: 0; padding: 0.75rem 0 1rem; border: 1px solid var(--ifm-color-emphasis-200); border-radius: 6px; background: #fff; overflow: auto; }",
                "  .nav-container .panels { height: auto; }",
                "  .nav-panel-menu { overflow: visible; }",
                "  .nav-menu { min-height: 0; padding: 0 1rem; }",
                "  main.article { overflow: visible; }",
                "  main.article .content { overflow: visible; }",
                "  article.doc { height: auto; overflow: visible; padding-right: 0; }",
                "  .site-footer { grid-template-columns: 1fr; }",
                "  .site-footer p { justify-self: start; }",
                "}",
                "",
            ]
        ),
    )
    return supplemental_ui


def write_playbook(
    work_root: Path, output_dir: Path, site_url: str, sources: list[Path]
) -> Path:
    supplemental_ui = write_supplemental_ui(work_root)
    source_lines = []
    for source in sources:
        source_lines.extend([f"    - url: {source.as_posix()}", "      branches: HEAD"])

    playbook = work_root / "antora-playbook.yml"
    write_text(
        playbook,
        "\n".join(
            [
                "site:",
                "  title: Beman Docs",
                f"  url: {site_url.rstrip('/')}",
                "  start_page: beman:ROOT:index.adoc",
                "",
                "content:",
                "  sources:",
                *source_lines,
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
    check_tools(args.skip_api_reference)

    work_root = args.work_root.resolve()
    output_dir = args.output_dir.resolve()
    shutil.rmtree(work_root, ignore_errors=True)
    shutil.rmtree(output_dir, ignore_errors=True)
    work_root.mkdir(parents=True, exist_ok=True)
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    libraries = build_library_docs(
        load_manifest(),
        args.repos_root.resolve(),
        clone_missing=args.clone_missing,
        update_repos=args.update_repos,
    )
    global_nav = write_global_nav(libraries, args.skip_api_reference)

    sources = [write_project_component(work_root, global_nav)]
    for library in libraries:
        sources.append(
            write_library_component(
                work_root,
                library,
                global_nav,
                skip_api_reference=args.skip_api_reference,
            )
        )

    playbook = write_playbook(work_root, output_dir, args.site_url, sources)
    build_antora(playbook, args.cache_dir.resolve())
    print(f"Built unified Antora docs: {output_dir}")


if __name__ == "__main__":
    main()
