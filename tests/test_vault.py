"""
Tests for :mod:`obsidian.vault`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import VaultFrontmatterSettings
from core.exceptions import VaultError
from core.interfaces import NoteStore
from obsidian.vault import VaultManager

SECTIONS = ["Architecture", "Features", "Daily"]


@pytest.fixture()
def vault(tmp_path: Path) -> VaultManager:
    v = VaultManager(
        root=tmp_path / "vault",
        sections=SECTIONS,
        frontmatter=VaultFrontmatterSettings(
            author="Tester", tags=["test"], status="draft"
        ),
    )
    v.initialize()
    return v


def test_initialize_creates_sections(vault: VaultManager) -> None:
    for section in SECTIONS:
        assert (vault.root / section).is_dir()
    assert (vault.root / ".obsidian").is_dir()


def test_write_and_read_round_trip(vault: VaultManager) -> None:
    path = vault.write_note(
        section="Architecture",
        name="My First Note!",
        body="# Hello\n\nWorld.",
        frontmatter_extras={"tags": ["architecture"]},
    )
    assert path.exists()
    assert path.name == "my-first-note.md"

    fm, body = vault.read_note("Architecture", "My First Note!")
    assert fm["author"] == "Tester"
    assert fm["tags"] == ["architecture"]    # extras override defaults
    assert "created" in fm and "updated" in fm
    assert "Hello" in body


def test_write_preserves_created_timestamp(vault: VaultManager) -> None:
    p1 = vault.write_note("Daily", "Day 1", "first")
    fm1, _ = vault.read_note("Daily", "Day 1")
    created_first = fm1["created"]

    vault.write_note("Daily", "Day 1", "second pass")
    fm2, body2 = vault.read_note("Daily", "Day 1")
    assert fm2["created"] == created_first
    assert "second pass" in body2
    assert p1.exists()


def test_unknown_section_raises(vault: VaultManager) -> None:
    with pytest.raises(VaultError, match="Unknown vault section"):
        vault.write_note("Nonexistent", "x", "body")


def test_list_notes(vault: VaultManager) -> None:
    vault.write_note("Features", "Alpha", "a")
    vault.write_note("Features", "Beta", "b")
    notes = vault.list_notes("Features")
    assert notes == ["alpha.md", "beta.md"]


def test_read_missing_note_raises(vault: VaultManager) -> None:
    with pytest.raises(VaultError, match="Note not found"):
        vault.read_note("Architecture", "never-written")


def test_vault_satisfies_note_store_protocol(vault: VaultManager) -> None:
    assert isinstance(vault, NoteStore)
