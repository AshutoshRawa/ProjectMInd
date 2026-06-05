"""
Tests for Module 5 — Documentation Engine.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

from analysis.analysis_types import FileAnalysis, FunctionInfo
from core import EventBus
from docs import (
    Module5DocEngine,
    build_frontmatter,
    generate,
    render_doc_template,
)
from docs.changelog import (
    AI_SUMMARY_CHANGED,
    COMPLEXITY_CHANGED,
    FUNCTION_ADDED,
    FUNCTION_REMOVED,
    IMPORTS_CHANGED,
    ChangelogEntry,
    diff_analyses,
    format_changelog,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_analysis(**overrides: Any) -> FileAnalysis:
    """Build a FileAnalysis with sensible defaults, overridable per-field."""
    defaults: dict[str, Any] = {
        "path": "src/utils.py",
        "language": "python",
        "lines_of_code": 142,
        "functions": [
            FunctionInfo(
                name="parse",
                line_start=10,
                line_end=30,
                params=["data", "strict"],
                complexity=4,
                has_docstring=True,
                calls=["validate", "json.loads"],
            ),
            FunctionInfo(
                name="dump",
                line_start=35,
                line_end=40,
                params=["obj"],
                complexity=1,
                has_docstring=False,
                calls=["json.dumps"],
            ),
        ],
        "classes": ["Parser"],
        "imports": ["json", "pathlib.Path"],
        "ai_summary": "Utility module for JSON parsing and serialization.",
        "anti_patterns": ["Missing type annotations on dump()"],
        "analyzed_at": 1736950320.0,  # 2025-01-15T14:32:00 UTC
    }
    defaults.update(overrides)
    return FileAnalysis(**defaults)


def _wait_for_result(results: list[dict[str, object]], timeout: float = 3.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if results:
            return results[0]
        time.sleep(0.05)
    raise AssertionError("expected docs.doc_updated event")


# ---------------------------------------------------------------------------
# frontmatter.py
# ---------------------------------------------------------------------------

def test_build_frontmatter_format() -> None:
    """Verify exact YAML format with --- fences."""
    analysis = _make_analysis()
    fm = build_frontmatter(analysis)

    assert fm.startswith("---\n")
    assert fm.endswith("---\n")

    # Check key fields are present.
    assert "file: src/utils.py" in fm
    assert "language: python" in fm
    assert "lines: 142" in fm
    assert "complexity:" in fm
    assert "last_analyzed:" in fm
    assert "tags:" in fm


def test_build_frontmatter_tags_derived() -> None:
    """Verify tags are derived from language, path components, and always include projectmind."""
    analysis = _make_analysis(path="backend/api/handlers.py", language="python")
    fm = build_frontmatter(analysis)

    assert "python" in fm
    assert "backend" in fm
    assert "api" in fm
    assert "handlers" in fm
    assert "projectmind" in fm


# ---------------------------------------------------------------------------
# doc_generator.py
# ---------------------------------------------------------------------------

def test_generate_produces_all_sections(monkeypatch) -> None:
    """Verify H1, blockquote, Functions table, Anti-Patterns, Dependencies, Changelog."""
    # Stub out AI.
    monkeypatch.setattr("docs.doc_generator.get_ai", lambda: SimpleNamespace(
        complete=lambda *a, **kw: ""
    ), raising=False)

    analysis = _make_analysis()
    changelog = [
        ChangelogEntry(
            timestamp=analysis.analyzed_at,
            change_type=FUNCTION_ADDED,
            description="Function `parse` added",
        ),
    ]
    md = generate(analysis, changelog_entries=changelog)

    # H1 filename.
    assert "# utils.py" in md
    # Blockquote summary.
    assert "> Utility module for JSON parsing" in md
    # Functions table.
    assert "## Functions" in md
    assert "| `parse`" in md
    assert "| `dump`" in md
    assert "✓" in md   # parse has docstring
    assert "✗" in md   # dump doesn't
    # Anti-Patterns section.
    assert "## Anti-Patterns" in md
    assert "Missing type annotations" in md
    # Dependencies.
    assert "## Dependencies" in md
    assert "`json`" in md
    assert "`pathlib.Path`" in md
    # Changelog.
    assert "## Changelog" in md
    assert "FUNCTION_ADDED" in md


def test_generate_omits_anti_patterns_when_empty(monkeypatch) -> None:
    """Verify Anti-Patterns section is skipped when list is empty."""
    monkeypatch.setattr("docs.doc_generator.get_ai", lambda: SimpleNamespace(
        complete=lambda *a, **kw: ""
    ), raising=False)

    analysis = _make_analysis(anti_patterns=[])
    md = generate(analysis)

    assert "## Anti-Patterns" not in md


# ---------------------------------------------------------------------------
# changelog.py
# ---------------------------------------------------------------------------

def test_diff_analyses_detects_function_added() -> None:
    """Add a function between old and new."""
    old = _make_analysis(functions=[
        FunctionInfo("parse", 10, 30, ["data"], 4, True, []),
    ])
    new = _make_analysis(functions=[
        FunctionInfo("parse", 10, 30, ["data"], 4, True, []),
        FunctionInfo("serialize", 35, 50, ["obj"], 2, False, []),
    ])

    entries = diff_analyses(old, new)
    types = [e.change_type for e in entries]
    assert FUNCTION_ADDED in types
    added = [e for e in entries if e.change_type == FUNCTION_ADDED]
    assert any("serialize" in e.description for e in added)


def test_diff_analyses_detects_function_removed() -> None:
    """Remove a function between old and new."""
    old = _make_analysis(functions=[
        FunctionInfo("parse", 10, 30, ["data"], 4, True, []),
        FunctionInfo("old_fn", 35, 40, [], 1, False, []),
    ])
    new = _make_analysis(functions=[
        FunctionInfo("parse", 10, 30, ["data"], 4, True, []),
    ])

    entries = diff_analyses(old, new)
    types = [e.change_type for e in entries]
    assert FUNCTION_REMOVED in types
    removed = [e for e in entries if e.change_type == FUNCTION_REMOVED]
    assert any("old_fn" in e.description for e in removed)


def test_diff_analyses_detects_complexity_changed() -> None:
    """Change complexity between old and new."""
    old = _make_analysis(functions=[
        FunctionInfo("parse", 10, 30, ["data"], 2, True, []),
    ])
    new = _make_analysis(functions=[
        FunctionInfo("parse", 10, 30, ["data"], 8, True, []),
    ])

    entries = diff_analyses(old, new)
    types = [e.change_type for e in entries]
    assert COMPLEXITY_CHANGED in types


def test_diff_analyses_detects_imports_changed() -> None:
    """Modify imports between old and new."""
    old = _make_analysis(imports=["json", "os"])
    new = _make_analysis(imports=["json", "sys"])

    entries = diff_analyses(old, new)
    types = [e.change_type for e in entries]
    assert IMPORTS_CHANGED in types
    imp_entry = next(e for e in entries if e.change_type == IMPORTS_CHANGED)
    assert "sys" in imp_entry.description  # added
    assert "os" in imp_entry.description   # removed


def test_diff_analyses_detects_ai_summary_changed() -> None:
    """Modify AI summary between old and new."""
    old = _make_analysis(ai_summary="Old summary.")
    new = _make_analysis(ai_summary="New improved summary.")

    entries = diff_analyses(old, new)
    types = [e.change_type for e in entries]
    assert AI_SUMMARY_CHANGED in types


def test_format_changelog_respects_max() -> None:
    """Verify capping at max_entries."""
    ts = time.time()
    entries = [
        ChangelogEntry(ts + i, FUNCTION_ADDED, f"Function `fn{i}` added")
        for i in range(10)
    ]

    result = format_changelog(entries, max_entries=3)
    lines = [ln for ln in result.strip().splitlines() if ln.startswith("-")]
    assert len(lines) == 3

    # Most recent first (highest timestamp).
    assert "fn9" in lines[0]


# ---------------------------------------------------------------------------
# template_engine.py
# ---------------------------------------------------------------------------

def test_render_doc_template_unknown_raises() -> None:
    """Verify error on unknown template name."""
    import pytest
    from jinja2 import TemplateNotFound

    with pytest.raises(TemplateNotFound):
        render_doc_template("nonexistent_template", {})


# ---------------------------------------------------------------------------
# doc_engine.py — EventBus integration
# ---------------------------------------------------------------------------

def test_doc_engine_subscribes_and_publishes(monkeypatch) -> None:
    """End-to-end: analysis event → doc engine → docs.doc_updated event."""
    # Stub AI so doc_generator doesn't reach out.
    monkeypatch.setattr("docs.doc_generator.get_ai", lambda: SimpleNamespace(
        complete=lambda *a, **kw: ""
    ), raising=False)

    bus = EventBus()
    results: list[dict[str, object]] = []
    bus.subscribe("docs.doc_updated", lambda payload: results.append(payload))

    engine = Module5DocEngine(bus=bus)
    engine.start()
    try:
        analysis = _make_analysis()
        bus.publish(
            "analysis.file_analyzed",
            {
                "file_path": analysis.path,
                "analysis": analysis.to_dict(),
            },
        )
        payload = _wait_for_result(results)
    finally:
        engine.stop()

    assert payload["path"] == "src/utils.py"
    assert isinstance(payload["markdown_content"], str)
    assert "# utils.py" in payload["markdown_content"]
    assert isinstance(payload["frontmatter"], str)
    assert "---" in payload["frontmatter"]
