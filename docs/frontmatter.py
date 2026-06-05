"""
docs/frontmatter.py
===================
Build YAML front-matter blocks from :class:`~analysis.analysis_types.FileAnalysis`.

The front-matter string is suitable for Obsidian-compatible markdown notes
and carries structured metadata (file path, language, complexity, tags).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

import yaml

from analysis.analysis_types import FileAnalysis
from analysis.complexity import file_complexity_score


def build_frontmatter(analysis: FileAnalysis) -> str:
    """Build a YAML front-matter block from an analysis result.

    Returns
    -------
    str
        A ``---`` fenced YAML block ready to be prepended to a markdown
        document body.  Example::

            ---
            file: src/utils.py
            language: python
            lines: 142
            complexity: 3.4
            last_analyzed: 2025-01-15T14:32:00
            tags: [python, utils, projectmind]
            ---
    """
    complexity = file_complexity_score(analysis)
    analyzed_dt = datetime.fromtimestamp(analysis.analyzed_at, tz=timezone.utc)

    data: dict[str, Any] = {
        "file": analysis.path,
        "language": analysis.language,
        "lines": analysis.lines_of_code,
        "complexity": round(complexity, 1),
        "last_analyzed": analyzed_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "tags": _derive_tags(analysis),
    }

    yaml_text = yaml.safe_dump(
        data, sort_keys=False, allow_unicode=True, default_flow_style=False,
    ).strip()

    return f"---\n{yaml_text}\n---\n"


def _derive_tags(analysis: FileAnalysis) -> list[str]:
    """Derive tags from the analysis language and file path."""
    tags: list[str] = []

    # Language tag.
    if analysis.language:
        tags.append(analysis.language)

    # Path-component tags: use the parent directory names and the stem
    # of the filename (e.g. "src/utils.py" → ["src", "utils"]).
    parts = PurePosixPath(analysis.path).parts
    for part in parts[:-1]:
        slug = part.lower().replace(" ", "-")
        if slug and slug not in tags:
            tags.append(slug)
    stem = PurePosixPath(analysis.path).stem.lower().replace(" ", "-")
    if stem and stem not in tags:
        tags.append(stem)

    # Always include projectmind.
    if "projectmind" not in tags:
        tags.append("projectmind")

    return tags
