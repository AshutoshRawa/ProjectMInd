"""
core/utils.py
=============
Small, dependency-free helpers shared across the codebase.

Keep this module *tiny*.  When a helper grows to more than ~30 lines or
develops external dependencies, promote it to its own module.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Filesystem
# ---------------------------------------------------------------------------

def ensure_dir(path: Path) -> Path:
    """Create *path* (and parents) if missing and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """
    Write *content* to *path* atomically.

    The text is first written to a sibling temp file in the same
    directory, then ``os.replace``-d into place.  This prevents readers
    from observing a partially written file even if the process crashes
    mid-write — important for the vault which other tools (Obsidian)
    may be reading concurrently.
    """
    ensure_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(content)
        os.replace(tmp_path, path)
    finally:
        # Clean up the temp file if replace didn't happen.
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Strings
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_length: int = 80) -> str:
    """
    Convert *text* into a filesystem-safe slug.

    Examples::

        slugify("Hello, World!")      # → "hello-world"
        slugify("  Foo  Bar  ")       # → "foo-bar"
    """
    cleaned = _SLUG_RE.sub("-", text.lower()).strip("-")
    return cleaned[:max_length] or "untitled"


def short_hash(text: str, length: int = 12) -> str:
    """Return the first *length* hex chars of the SHA-256 of *text*."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string (seconds precision)."""
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


def today_iso() -> str:
    """Return today's UTC date as ``YYYY-MM-DD``."""
    return datetime.now(tz=timezone.utc).date().isoformat()
