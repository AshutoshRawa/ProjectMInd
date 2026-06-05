"""
docs/doc_generator.py
=====================
Generate complete markdown documentation from a :class:`FileAnalysis`.

The produced string contains YAML front-matter followed by deterministic
structure (function tables, anti-patterns, dependencies, changelog).
AI is used **only** for an optional extended description — the document
skeleton is never AI-generated.
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any

from analysis.analysis_types import FileAnalysis
from docs.changelog import ChangelogEntry, format_changelog
from docs.frontmatter import build_frontmatter
from docs.template_engine import render_doc_template


def generate(
    analysis: FileAnalysis,
    changelog_entries: list[ChangelogEntry] | None = None,
) -> str:
    """Produce a complete markdown document for *analysis*.

    Parameters
    ----------
    analysis:
        The :class:`FileAnalysis` to document.
    changelog_entries:
        Optional list of :class:`ChangelogEntry` items to render in the
        Changelog section.  If ``None`` the section is omitted.

    Returns
    -------
    str
        Complete markdown string: YAML front-matter + structured body.
    """
    frontmatter = build_frontmatter(analysis)

    # --- AI extended description (best-effort, non-critical) ---
    extended_description = _ai_extended_description(analysis)

    # --- Changelog ---
    changelog_md = ""
    if changelog_entries:
        changelog_md = format_changelog(changelog_entries, max_entries=5)

    # --- Build context for the Jinja2 template ---
    filename = PurePosixPath(analysis.path).name
    context: dict[str, Any] = {
        "filename": filename,
        "ai_summary": analysis.ai_summary,
        "extended_description": extended_description,
        "functions": [
            {
                "name": f.name,
                "params": f.params,
                "complexity": f.complexity,
                "has_docstring": f.has_docstring,
            }
            for f in analysis.functions
        ],
        "anti_patterns": analysis.anti_patterns,
        "imports": analysis.imports,
        "changelog": changelog_md,
    }

    body = render_doc_template("file_doc", context)

    return frontmatter + "\n" + body


def _ai_extended_description(analysis: FileAnalysis) -> str:
    """Call AI for an extended description paragraph.

    Returns an empty string if AI is unavailable or fails.  Structure
    is always deterministic — this is a non-essential enrichment.
    """
    try:
        from ai import get_ai  # noqa: PLC0415 — deferred import

        analysis_json = json.dumps(analysis.to_dict(), indent=2)
        module_name = PurePosixPath(analysis.path).stem
        text = get_ai().complete(
            "doc_generation",
            {
                "module_name": module_name,
                "file_path": analysis.path,
                "analysis_json": analysis_json,
            },
        )
        # Take only the first paragraph to keep it brief.
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if paragraphs:
            # Skip if the AI returned a heading (starts with #).
            first = paragraphs[0]
            if not first.startswith("#"):
                return first
    except Exception:  # noqa: BLE001 — AI failure must never break doc generation
        pass

    return ""
