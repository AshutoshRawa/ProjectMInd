"""
Tests for Module 3 — AI Communication Engine.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from ai.ai_manager import AIManager
from ai.ollama_client import OllamaClient
from ai.prompts import PromptBuilder, PromptBundle
from ai.request_manager import RequestManager
from ai.response_parser import ResponseParser
from core.config import AISettings
from core.exceptions import AIError


@pytest.fixture()
def ai_settings() -> AISettings:
    return AISettings(
        ollama_host="http://localhost:11434",
        default_model="qwen2.5-coder:7b",
        fallback_model="qwen2.5:7b",
        timeout=30,
        max_retries=2,
        retry_backoff_seconds=0.01,
    )


def test_response_parser_extracts_text() -> None:
    text = ResponseParser.parse_generate({"response": "  hello  ", "done": True})
    assert text == "hello"


def test_response_parser_raises_on_error_field() -> None:
    with pytest.raises(AIError, match="Ollama returned an error"):
        ResponseParser.parse_generate({"error": "model not found"})


def test_response_parser_raises_on_missing_response() -> None:
    with pytest.raises(AIError, match="missing 'response'"):
        ResponseParser.parse_generate({"done": True})


def test_response_parser_parse_tags() -> None:
    names = ResponseParser.parse_tags(
        {"models": [{"name": "qwen2.5-coder:7b"}, {"name": "llama3"}]}
    )
    assert names == ["qwen2.5-coder:7b", "llama3"]


def test_prompt_bundle_flattens_sections() -> None:
    bundle = PromptBundle(system="SYS", user="USER")
    flat = bundle.as_single_prompt()
    assert "### System" in flat
    assert "SYS" in flat
    assert "### User" in flat
    assert "USER" in flat
    assert "### Assistant" in flat


def test_prompt_builder_user_message() -> None:
    bundle = PromptBuilder().user_message("What is ProjectMind?")
    assert bundle.user == "What is ProjectMind?"
    assert "ProjectMind" in bundle.system


def test_request_manager_retries_on_timeout(ai_settings: AISettings) -> None:
    manager = RequestManager(ai_settings)
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 2:
            raise requests.exceptions.Timeout("timed out")
        return "ok"

    assert manager.execute(flaky, label="test") == "ok"
    assert calls["n"] == 2


def test_request_manager_fails_after_exhausted_retries(
    ai_settings: AISettings,
) -> None:
    manager = RequestManager(ai_settings)

    def always_timeout() -> str:
        raise requests.exceptions.Timeout("timed out")

    with pytest.raises(AIError, match="failed after"):
        manager.execute(always_timeout, label="test")


def test_request_manager_does_not_retry_ai_error(ai_settings: AISettings) -> None:
    manager = RequestManager(ai_settings)

    def boom() -> str:
        raise AIError("permanent")

    with pytest.raises(AIError, match="permanent"):
        manager.execute(boom, label="test")


def test_ollama_client_generate_decodes_json(ai_settings: AISettings) -> None:
    session = MagicMock()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"response": "hi", "done": True}
    session.post.return_value = response

    client = OllamaClient(ai_settings, session=session)
    payload = client.generate("ping")

    assert payload["response"] == "hi"
    session.post.assert_called_once()
    call_kwargs = session.post.call_args
    assert call_kwargs[0][0] == "http://localhost:11434/api/generate"
    assert call_kwargs[1]["json"]["model"] == "qwen2.5-coder:7b"
    assert call_kwargs[1]["json"]["stream"] is False


def test_ollama_client_raises_on_http_error(ai_settings: AISettings) -> None:
    session = MagicMock()
    response = MagicMock()
    response.status_code = 500
    response.text = "internal error"
    session.post.return_value = response

    client = OllamaClient(ai_settings, session=session)
    with pytest.raises(AIError, match="HTTP 500"):
        client.generate("ping")


def test_ai_manager_generate_parses_response(ai_settings: AISettings) -> None:
    manager = AIManager(ai_settings)

    with patch.object(manager._client, "generate") as mock_gen:
        mock_gen.return_value = {"response": "answer", "done": True}
        text = manager.generate("test prompt")

    assert text == "answer"
    assert manager.active_model == "qwen2.5-coder:7b"


def test_ai_manager_falls_back_on_missing_model(ai_settings: AISettings) -> None:
    manager = AIManager(ai_settings)

    with patch.object(manager._client, "generate") as mock_gen:
        mock_gen.side_effect = [
            AIError("model qwen2.5-coder:7b not found"),
            {"response": "fallback ok", "done": True},
        ]
        text = manager.generate("test")

    assert text == "fallback ok"
    assert manager.active_model == "qwen2.5:7b"
    assert mock_gen.call_count == 2


def test_ai_manager_on_file_change_logs_only(
    ai_settings: AISettings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    manager = AIManager(ai_settings)
    with caplog.at_level(logging.DEBUG, logger="projectmind.ai.ai_manager"):
        manager.on_file_change("fake-event")
    assert any("watcher event received" in r.message for r in caplog.records)


@pytest.fixture()
def isolated_config(tmp_path: Path) -> Path:
    """Minimal user config pointing paths at a temp directory."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"paths:\n"
        f"  project_root: \"{tmp_path.as_posix()}\"\n"
        f"  logs_dir: \"logs\"\n"
        f"  vault_dir: \"vault\"\n",
        encoding="utf-8",
    )
    return cfg


def test_bootstrap_registers_ai_client(isolated_config: Path) -> None:
    from core.bootstrap import bootstrap
    from core.interfaces import AIClient
    from ai.ai_manager import AIManager

    app = bootstrap(
        user_config_path=isolated_config, install_signal_handlers=False
    )
    try:
        ai = app.registry.get(AIClient)
        assert isinstance(ai, AIManager)
    finally:
        app.shutdown()
