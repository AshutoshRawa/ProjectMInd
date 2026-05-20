"""
tests/conftest.py
=================
Shared pytest fixtures for the ProjectMind suite.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pytest

# Make the project root importable when tests are invoked from anywhere.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Hygiene fixtures (autouse) — keep tests independent of each other.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_logger_state() -> None:
    """
    Reset the global logger state between tests so each test that calls
    ``logger.bootstrap`` gets a fresh set of handlers attached to its
    own (temp) logs directory instead of leaking handlers from the
    previous test's tmp_path.
    """
    yield
    from core import logger as _logger_module
    _logger_module._configured = False
    root = logging.getLogger("projectmind")
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture(autouse=True)
def _clear_projectmind_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Strip any ``PROJECTMIND_*`` environment variables the developer may
    have set in their shell so config tests are deterministic.
    """
    for key in list(os.environ):
        if key.startswith("PROJECTMIND_"):
            monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """
    A throw-away directory tree that mirrors the real project layout
    (config/, logs/, vault/) so tests can bootstrap an isolated
    Application without touching the developer's actual files.
    """
    (tmp_path / "config").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "vault").mkdir()
    return tmp_path
