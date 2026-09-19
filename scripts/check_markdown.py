#!/usr/bin/env python3
"""Validate repository-local Markdown references without external dependencies."""

from __future__ import annotations

import html
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit


FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
REFERENCE_LINK_RE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(?:<([^>]+)>|(\S+))")
HTML_ANCHOR_TAG_RE = re.compile(r"<a\b[^>]*>", re.IGNORECASE)
HTML_ANCHOR_ATTRIBUTE_RE = re.compile(
    r"\b(?:id|name)\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s\"'=<>`]+))",
    re.IGNORECASE,
)
ATTRIBUTE_ANCHOR_RE = re.compile(r"\{#([A-Za-z][A-Za-z0-9_.:-]*)\}")
IGNORED_DIRECTORIES = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}


def markdown_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for candidate in root.rglob("*.md"):
        relative_parts = candidate.relative_to(root).parts
        if any(part in IGNORED_DIRECTORIES or part == ".worktrees" for part in relative_parts):
            continue
        files.append(candidate)
    return sorted(files)


def read_repository_file(path: Path, root: Path) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("path escapes the repository")
    return resolved.read_text(encoding="utf-8")


def visible_markdown_lines(text: str) -> list[tuple[int, str]]:
    visible: list[tuple[int, str]] = []
    fence: tuple[str, int] | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        marker = FENCE_RE.match(line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = (token[0], len(token))
            elif (
                token[0] == fence[0]
                and len(token) >= fence[1]
                and not line[marker.end() :].strip(" \t")
            ):
                fence = None
            continue
        if fence is None:
            visible.append((line_number, line))
    return visible


def github_slug(heading: str) -> str:
    heading = re.sub(r"<[^>]+>", "", heading)
    heading = re.sub(r"[`*_~]", "", heading)
    heading = html.unescape(heading).strip().lower()
    heading = re.sub(r"\s", "-", heading)
    heading = re.sub(r"[^\w\-\s]", "", heading, flags=re.UNICODE)
    return heading


def anchors(lines: list[tuple[int, str]]) -> tuple[set[str], list[tuple[int, str]]]:
    available: set[str] = set()
    generated_counts: Counter[str] = Counter()
    explicit_locations: dict[str, int] = {}
    duplicates: list[tuple[int, str]] = []

    for line_number, line in lines:
        heading = HEADING_RE.match(line)
        if heading:
            base = github_slug(heading.group(1))
            count = generated_counts[base]
            generated_counts[base] += 1
            available.add(base if count == 0 else f"{base}-{count}")

        explicit = []
        for tag in HTML_ANCHOR_TAG_RE.finditer(line):
            explicit.extend(
                next(value for value in match.groups() if value is not None)
                for match in HTML_ANCHOR_ATTRIBUTE_RE.finditer(tag.group())
            )
        explicit.extend(ATTRIBUTE_ANCHOR_RE.findall(line))
        for anchor in explicit:
            if anchor in explicit_locations:
                duplicates.append((line_number, anchor))
            else:
                explicit_locations[anchor] = line_number
            available.add(anchor)

    return available, duplicates


def link_targets(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    targets: list[tuple[int, str]] = []
    for line_number, line in lines:
        cursor = 0
        while True:
            start = line.find("](", cursor)
            if start < 0:
                break
            position = start + 2
            while position < len(line) and line[position].isspace():
                position += 1
            if position < len(line) and line[position] == "<":
                end = line.find(">", position + 1)
                if end >= 0:
                    targets.append((line_number, line[position + 1 : end]))
                    cursor = end + 1
                    continue
            else:
                depth = 0
                escaped = False
                target: list[str] = []
                while position < len(line):
                    character = line[position]
                    if escaped:
                        target.append(character)
                        escaped = False
                    elif character == "\\":
                        escaped = True
                    elif character == "(":
                        depth += 1
                        target.append(character)
                    elif character == ")":
                        if depth == 0:
                            break
                        depth -= 1
                        target.append(character)
                    elif character.isspace() and depth == 0:
                        break
                    else:
                        target.append(character)
                    position += 1
                if target:
                    targets.append((line_number, "".join(target)))
            cursor = start + 2

        for match in REFERENCE_LINK_RE.finditer(line):
            targets.append((line_number, match.group(1) or match.group(2)))
    return targets


def check_repository(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    documents: dict[Path, tuple[list[tuple[int, str]], set[str]]] = {}

    for markdown in markdown_files(root):
        relative = markdown.relative_to(root)
        try:
            lines = visible_markdown_lines(read_repository_file(markdown, root))
        except (OSError, UnicodeError, ValueError) as error:
            errors.append(f"{relative}: cannot read Markdown inside repository: {error}")
            continue
        available, duplicates = anchors(lines)
        documents[markdown.resolve()] = (lines, available)
        for line_number, anchor in duplicates:
            errors.append(f"{relative}:{line_number}: duplicate explicit anchor '#{anchor}'")

    for markdown, (lines, _) in documents.items():
        relative = markdown.relative_to(root)
        for line_number, raw_target in link_targets(lines):
            target = html.unescape(raw_target)
            split = urlsplit(target)
            if split.scheme or split.netloc:
                continue

            decoded_path = unquote(split.path)
            if decoded_path:
                candidate = (markdown.parent / decoded_path).resolve()
            else:
                candidate = markdown

            if not candidate.is_relative_to(root):
                errors.append(f"{relative}:{line_number}: repository path escapes root: {target}")
                continue
            if not candidate.exists():
                errors.append(f"{relative}:{line_number}: missing repository path: {target}")
                continue
            if split.fragment and candidate.suffix.lower() == ".md":
                target_document = documents.get(candidate)
                if target_document is None:
                    try:
                        target_lines = visible_markdown_lines(read_repository_file(candidate, root))
                    except (OSError, UnicodeError, ValueError) as error:
                        errors.append(
                            f"{relative}:{line_number}: cannot read Markdown target {target}: {error}"
                        )
                        continue
                    target_anchors, _ = anchors(target_lines)
                else:
                    _, target_anchors = target_document
                fragment = unquote(split.fragment)
                if re.fullmatch(r"L\d+(?:-L\d+)?", fragment):
                    continue
                if fragment not in target_anchors:
                    errors.append(f"{relative}:{line_number}: missing Markdown anchor: {target}")

    return errors


def main() -> int:
    repository_root = Path(__file__).resolve().parent.parent
    errors = check_repository(repository_root)
    if errors:
        for error in errors:
            print(error)
        print(f"Markdown validation failed with {len(errors)} error(s).", file=sys.stderr)
        return 1
    count = len(markdown_files(repository_root))
    print(f"Markdown validation passed for {count} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
