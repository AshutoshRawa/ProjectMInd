"""
analysis/_json_utils.py
========================
Shared JSON-from-AI-response parsing utilities used across the analysis package.

Extracted from ``analyzer_engine.py`` to eliminate the duplicate
implementation that previously existed in ``ast_analyzer.py``.

Public API
----------
- :func:`parse_json_object` — strip markdown fence, extract first JSON object.
- :func:`remove_trailing_commas` — sanitise JSON with trailing commas.
"""

from __future__ import annotations

import json
import re
from typing import Any


def remove_trailing_commas(text: str) -> str:
    """Remove trailing commas before ``}`` or ``]`` so :func:`json.loads` succeeds."""
    return re.sub(r",\s*([}\]])", r"\1", text)


def parse_json_object(text: str) -> dict[str, Any] | None:
    """Extract the first valid JSON object from *text*.

    Handles:
    - Bare JSON (``{…}``)
    - Markdown code fences (``` json … ```)
    - Trailing commas (common in AI output)

    Returns ``None`` when no valid JSON object can be extracted.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return None

    # Strip markdown code fence if present.
    fence_match = re.search(
        r"```(?:json|JSON)?\s*([\s\S]*?)\s*```",
        cleaned,
    )
    if fence_match:
        cleaned = fence_match.group(1).strip()

    # Try the full cleaned string first, then the first {...} sub-match.
    candidates = [cleaned]
    object_match = re.search(r"\{[\s\S]*\}", cleaned)
    if object_match:
        candidates.append(object_match.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(remove_trailing_commas(candidate))
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None
