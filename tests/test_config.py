"""
Tests for :mod:`core.config`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.config import ConfigLoader


def test_load_defaults_returns_populated_settings() -> None:
    settings = ConfigLoader().load()
    assert settings.app.name == "ProjectMind"
    assert settings.logging.level in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    assert "Architecture" in settings.vault.sections


def test_user_config_deep_merge(tmp_path: Path) -> None:
    user_cfg = tmp_path / "config.yaml"
    user_cfg.write_text(
        "logging:\n  level: DEBUG\nai:\n  timeout: 999\n",
        encoding="utf-8",
    )
    settings = ConfigLoader(user_config_path=user_cfg).load()
    assert settings.logging.level == "DEBUG"
    assert settings.ai.timeout == 999
    # Untouched defaults survive the merge.
    assert settings.app.name == "ProjectMind"


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROJECTMIND_LOGGING__LEVEL", "WARNING")
    monkeypatch.setenv("PROJECTMIND_AI__TIMEOUT", "42")
    settings = ConfigLoader().load()
    assert settings.logging.level == "WARNING"
    assert settings.ai.timeout == 42


def test_invalid_log_level_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_cfg = tmp_path / "config.yaml"
    user_cfg.write_text("logging:\n  level: NOPE\n", encoding="utf-8")
    # Make sure no env override masks the bad value.
    for k in list(os.environ):
        if k.startswith("PROJECTMIND_"):
            monkeypatch.delenv(k, raising=False)
    with pytest.raises(ValueError, match="logging.level"):
        ConfigLoader(user_config_path=user_cfg).load()


def test_invalid_ollama_host_raises(tmp_path: Path) -> None:
    user_cfg = tmp_path / "config.yaml"
    user_cfg.write_text("ai:\n  ollama_host: not-a-url\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ollama_host"):
        ConfigLoader(user_config_path=user_cfg).load()
