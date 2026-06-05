"""
docs/changelog.py
=================
Diff two :class:`~analysis.analysis_types.FileAnalysis` snapshots and
produce a structured changelog.

Change types
------------
- ``FUNCTION_ADDED``     — a new function appeared
- ``FUNCTION_REMOVED``   — a function was deleted
- ``COMPLEXITY_CHANGED`` — overall complexity score shifted
- ``IMPORTS_CHANGED``    — the import list changed
- ``AI_SUMMARY_CHANGED`` — the AI summary text changed
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from analysis.analysis_types import FileAnalysis
from analysis.complexity import file_complexity_score


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChangelogEntry:
    """A single detected change between two analysis snapshots."""

    timestamp: float          # unix epoch seconds
    change_type: str          # one of the constants below
    description: str          # human-readable explanation

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "change_type": self.change_type,
            "description": self.description,
        }


# Change-type constants.
FUNCTION_ADDED = "FUNCTION_ADDED"
FUNCTION_REMOVED = "FUNCTION_REMOVED"
COMPLEXITY_CHANGED = "COMPLEXITY_CHANGED"
IMPORTS_CHANGED = "IMPORTS_CHANGED"
AI_SUMMARY_CHANGED = "AI_SUMMARY_CHANGED"


# ---------------------------------------------------------------------------
# Diffing
# ---------------------------------------------------------------------------

def diff_analyses(
    old: FileAnalysis,
    new: FileAnalysis,
) -> list[ChangelogEntry]:
    """Compare *old* and *new* analyses and return detected changes.

    The timestamp on each entry is taken from ``new.analyzed_at``.
    """
    ts = new.analyzed_at
    entries: list[ChangelogEntry] = []

    # --- Function additions / removals ---
    old_funcs = {f.name for f in old.functions}
    new_funcs = {f.name for f in new.functions}

    for name in sorted(new_funcs - old_funcs):
        entries.append(ChangelogEntry(
            timestamp=ts,
            change_type=FUNCTION_ADDED,
            description=f"Function `{name}` added",
        ))

    for name in sorted(old_funcs - new_funcs):
        entries.append(ChangelogEntry(
            timestamp=ts,
            change_type=FUNCTION_REMOVED,
            description=f"Function `{name}` removed",
        ))

    # --- Complexity change ---
    old_score = round(file_complexity_score(old), 1)
    new_score = round(file_complexity_score(new), 1)
    if old_score != new_score:
        entries.append(ChangelogEntry(
            timestamp=ts,
            change_type=COMPLEXITY_CHANGED,
            description=f"Complexity changed from {old_score} to {new_score}",
        ))

    # --- Imports change ---
    if sorted(old.imports) != sorted(new.imports):
        added = sorted(set(new.imports) - set(old.imports))
        removed = sorted(set(old.imports) - set(new.imports))
        parts: list[str] = []
        if added:
            parts.append(f"added: {', '.join(added)}")
        if removed:
            parts.append(f"removed: {', '.join(removed)}")
        entries.append(ChangelogEntry(
            timestamp=ts,
            change_type=IMPORTS_CHANGED,
            description=f"Imports changed ({'; '.join(parts)})",
        ))

    # --- AI summary change ---
    if old.ai_summary.strip() != new.ai_summary.strip():
        entries.append(ChangelogEntry(
            timestamp=ts,
            change_type=AI_SUMMARY_CHANGED,
            description="AI summary updated",
        ))

    return entries


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_changelog(
    entries: list[ChangelogEntry],
    max_entries: int = 5,
) -> str:
    """Render changelog entries as a markdown bullet list.

    Entries are sorted most-recent-first and capped at *max_entries*.
    Returns an empty string if *entries* is empty.
    """
    if not entries:
        return ""

    # Most recent first.
    sorted_entries = sorted(entries, key=lambda e: e.timestamp, reverse=True)
    capped = sorted_entries[:max_entries]

    lines: list[str] = []
    for entry in capped:
        dt = datetime.fromtimestamp(entry.timestamp, tz=timezone.utc)
        ts_str = dt.strftime("%Y-%m-%d %H:%M")
        lines.append(f"- **[{entry.change_type}]** {entry.description} _{ts_str}_")

    return "\n".join(lines) + "\n"
