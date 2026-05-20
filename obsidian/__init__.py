"""
obsidian/
=========
Obsidian-compatible vault layer.

The submodules here own:
- :mod:`obsidian.markdown`  — YAML front-matter + body composition
- :mod:`obsidian.vault`     — directory structure and note IO

Nothing in this package depends on AI, watchers, or any other future
module, so it can be imported safely from anywhere.
"""

from obsidian.markdown import build_frontmatter, compose_note, parse_frontmatter
from obsidian.vault import VaultManager

__all__ = [
    "VaultManager",
    "build_frontmatter",
    "compose_note",
    "parse_frontmatter",
]
