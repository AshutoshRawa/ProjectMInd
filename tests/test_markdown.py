"""
Tests for :mod:`obsidian.markdown`.
"""

from __future__ import annotations

import pytest

from core.exceptions import VaultError
from obsidian.markdown import (
    build_frontmatter,
    compose_note,
    parse_frontmatter,
)


def test_build_frontmatter_empty_returns_empty_string() -> None:
    assert build_frontmatter({}) == ""


def test_build_frontmatter_round_trip() -> None:
    data = {"title": "Hello", "tags": ["a", "b"], "status": "draft"}
    block = build_frontmatter(data)
    assert block.startswith("---\n") and block.rstrip().endswith("---")
    note = compose_note(data, "# body\n\ntext")
    fm, body = parse_frontmatter(note)
    assert fm == data
    assert "# body" in body


def test_parse_frontmatter_missing_block() -> None:
    fm, body = parse_frontmatter("# Just a body\n")
    assert fm == {}
    assert body == "# Just a body\n"


def test_parse_frontmatter_malformed_yaml_raises() -> None:
    bad = "---\nkey: : :\n---\nbody\n"
    with pytest.raises(VaultError):
        parse_frontmatter(bad)


def test_compose_note_without_frontmatter() -> None:
    note = compose_note({}, "hello\n")
    assert note == "hello\n"
