"""
Tests for :mod:`core.logger`.
"""

from __future__ import annotations

from pathlib import Path

from core.config import LoggingSettings
from core.logger import bootstrap, get_logger


def test_logger_honors_include_timestamp_false(tmp_path: Path) -> None:
    bootstrap(
        tmp_path,
        LoggingSettings(
            level="INFO",
            console_color=False,
            include_timestamp=False,
            filename="projectmind.log",
        ),
    )

    log = get_logger("tests.logger")
    log.info("hello")

    content = (tmp_path / "projectmind.log").read_text(encoding="utf-8")
    assert "INFO" in content
    assert "hello" in content
    assert not content.startswith("20")
