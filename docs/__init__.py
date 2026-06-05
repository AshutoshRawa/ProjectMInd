"""
docs/
=====
Module 5 — Documentation Engine.

Consumes :class:`~analysis.analysis_types.FileAnalysis` results and produces
structured markdown strings.  This module **never** writes to the vault —
that responsibility belongs to Module 8.
"""

from docs.changelog import ChangelogEntry, diff_analyses, format_changelog
from docs.doc_engine import Module5DocEngine
from docs.doc_generator import generate
from docs.frontmatter import build_frontmatter
from docs.template_engine import render_doc_template

__all__ = [
    "ChangelogEntry",
    "Module5DocEngine",
    "build_frontmatter",
    "diff_analyses",
    "format_changelog",
    "generate",
    "render_doc_template",
]
