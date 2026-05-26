"""
ai/response_parser.py
=====================
Parse and validate AI-generated text responses.

This module handles the messy reality of LLM output: models often wrap
JSON in markdown fences, include preamble text, or produce slightly
malformed structures.  The helpers here extract usable data and raise
:class:`~core.exceptions.ResponseParseError` with the raw response
attached for debugging.

This module is an **internal** implementation detail of the ``ai``
package.  Other packages should not import from here directly.
"""

from __future__ import annotations

import json
import re
from typing import Any

from core import ResponseParseError, get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_json_response(text: str) -> dict[str, Any]:
    """
    Extract a JSON object from an AI response string.

    Handles common LLM quirks:
    - Markdown fenced code blocks (````json ... ``` `` or ```` ... ``` ``)
    - Leading/trailing prose around the JSON
    - Trailing commas (basic cleanup)

    Parameters
    ----------
    text:
        Raw text returned by the model.

    Returns
    -------
    dict
        Parsed JSON object.

    Raises
    ------
    ResponseParseError
        If no valid JSON object can be extracted.
    """
    if not text or not text.strip():
        log.error("AI returned empty response")
        raise ResponseParseError("AI returned an empty response")

    cleaned = _strip_markdown_fences(text)

    # Try parsing the cleaned text directly
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
        raise ResponseParseError(
            f"Expected JSON object, got {type(result).__name__}"
        )
    except json.JSONDecodeError:
        pass

    # Try extracting a JSON object from surrounding prose
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        extracted = match.group()
        try:
            result = json.loads(extracted)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            try:
                result = json.loads(_remove_trailing_commas(extracted))
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

    # Try removing trailing commas and re-parsing
    sanitised = _remove_trailing_commas(cleaned)
    try:
        result = json.loads(sanitised)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    log.error("Failed to parse JSON from AI response: %.500s", text)
    raise ResponseParseError(
        f"Could not extract valid JSON from AI response. "
        f"Raw response (first 500 chars): {text[:500]}"
    )


def parse_structured(
    text: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    """
    Parse JSON from *text* and validate it against *schema*.

    The schema is a simple dictionary mapping field names to their
    expected Python types (e.g. ``{"name": str, "score": int}``).
    Nested validation is not performed — only top-level keys and
    types are checked.

    Parameters
    ----------
    text:
        Raw AI response text.
    schema:
        ``{field_name: expected_type}`` mapping.

    Returns
    -------
    dict
        Validated JSON object.

    Raises
    ------
    ResponseParseError
        If JSON extraction fails or the result does not match *schema*.
    """
    data = parse_json_response(text)

    errors: list[str] = []

    for field_name, expected_type in schema.items():
        if field_name not in data:
            errors.append(f"missing required field '{field_name}'")
            continue

        value = data[field_name]
        if not isinstance(value, expected_type):
            errors.append(
                f"field '{field_name}' expected {expected_type.__name__}, "
                f"got {type(value).__name__}"
            )

    if errors:
        log.error(
            "Schema validation failed: %s | raw: %.500s",
            "; ".join(errors),
            text,
        )
        raise ResponseParseError(
            f"Schema validation failed: {'; '.join(errors)}"
        )

    return data


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _strip_markdown_fences(text: str) -> str:
    """
    Remove markdown code fences wrapping a JSON block.

    Handles ````` ```json ... ``` ````` , ````` ``` ... ``` ````` , and
    triple-backtick-only blocks.
    """
    stripped = text.strip()

    # Match ```json\n...\n``` or ```\n...\n```
    fence_pattern = re.compile(
        r"^```(?:json|JSON)?\s*\n([\s\S]*?)\n\s*```\s*$",
        re.MULTILINE,
    )
    match = fence_pattern.search(stripped)
    if match:
        return match.group(1).strip()

    # Fallback: if text starts/ends with ```, strip them
    if stripped.startswith("```") and stripped.endswith("```"):
        inner = stripped[3:]
        if inner.startswith("json") or inner.startswith("JSON"):
            inner = inner[4:]
        inner = inner.rstrip("`")
        # Remove trailing ``` from end
        if inner.endswith("```"):
            inner = inner[:-3]
        return inner.strip()

    return stripped


def _remove_trailing_commas(text: str) -> str:
    """Remove trailing commas before closing braces/brackets."""
    return re.sub(r",\s*([}\]])", r"\1", text)
