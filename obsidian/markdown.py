"""
obsidian/markdown.py
====================
Markdown + YAML front-matter helpers used by the vault layer.

Obsidian notes follow the convention::

    ---
    key: value
    tags: [foo, bar]
    ---
    # Note title

    Body text…

This module gives the rest of ProjectMind a single, well-tested place
to build and parse that format so we never hand-roll YAML strings
elsewhere.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from core import VaultError

_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(?P<fm>.*?)\n---\s*\n?(?P<body>.*)\Z",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build_frontmatter(data: dict[str, Any]) -> str:
    """
    Serialise *data* into an Obsidian-compatible YAML front-matter block.

    The output always ends with a trailing newline so it can be
    concatenated directly with a body.

    Empty input yields an empty string (no fences) so callers can opt
    out of front-matter entirely.
    """
    if not data:
        return ""
    yaml_text = yaml.safe_dump(
        data, sort_keys=False, allow_unicode=True, default_flow_style=False
    ).strip()
    return f"---\n{yaml_text}\n---\n"


def compose_note(frontmatter: dict[str, Any], body: str) -> str:
    """
    Combine *frontmatter* and *body* into a complete markdown document.

    Always emits exactly one blank line between the YAML fence and the
    body for readability.
    """
    fm_block = build_frontmatter(frontmatter)
    body_clean = body.strip("\n")
    if fm_block:
        # Single blank line between fence and body, single trailing newline.
        return f"{fm_block}\n{body_clean}\n"
    return f"{body_clean}\n"


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """
    Split *text* into ``(frontmatter_dict, body)``.

    If the document has no front-matter, returns ``({}, text)`` so the
    caller can handle both shapes uniformly.

    Raises
    ------
    VaultError
        If a fence block exists but its YAML is malformed.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    raw = match.group("fm")
    body = match.group("body")
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise VaultError(f"Malformed YAML front-matter: {exc}") from exc

    if not isinstance(data, dict):
        raise VaultError(
            f"Front-matter must decode to a mapping, got {type(data).__name__}"
        )
    return data, body
