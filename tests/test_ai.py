"""
Tests for Module 3: AI Communication Engine.
"""

from __future__ import annotations

import sys
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai.ai_manager import AIManager
from ai.prompt_registry import PromptNotFoundError, PromptRegistry, PromptTemplate
from ai.response_parser import (
    ResponseParseError,
    parse_json_response,
    parse_structured,
)
from core import AIError, AISettings


@pytest.fixture()
def ai_settings() -> AISettings:
    return AISettings(
        ollama_host="http://localhost:11434",
        default_model="qwen2.5-coder:7b",
        fallback_model="qwen2.5:7b",
        timeout=30,
        max_tokens=512,
        temperature=0.1,
    )


def make_manager(
    ai_settings: AISettings,
    client: MagicMock | None = None,
    async_client: MagicMock | None = None,
) -> AIManager:
    return AIManager(
        settings=ai_settings,
        client=client or MagicMock(),
        async_client=async_client or MagicMock(),
    )


def test_prompt_registry_renders_registered_template() -> None:
    registry = PromptRegistry()
    registry.register(
        PromptTemplate(
            name="hello",
            version="1.0",
            system_prompt="System",
            user_template="Hello {name}",
            description="Greeting",
        )
    )

    assert registry.render("hello", {"name": "Ada"}) == ("System", "Hello Ada")


def test_prompt_registry_raises_for_missing_template() -> None:
    with pytest.raises(PromptNotFoundError):
        PromptRegistry().get("missing")


def test_default_prompts_are_available(ai_settings: AISettings) -> None:
    manager = make_manager(ai_settings)
    system_prompt, user_prompt = manager._registry.render(
        "code_analysis",
        {"file_path": "app.py", "language": "python", "code": "print('x')"},
    )

    assert "ProjectMind" in system_prompt
    assert "app.py" in user_prompt


def test_parse_json_response_strips_markdown_fences() -> None:
    assert parse_json_response('```json\n{"ok": true}\n```') == {"ok": True}


def test_parse_json_response_extracts_json_from_prose() -> None:
    assert parse_json_response('Here:\n{"name": "ProjectMind",}\nDone') == {
        "name": "ProjectMind"
    }


def test_parse_json_response_raises_on_invalid_json() -> None:
    with pytest.raises(ResponseParseError):
        parse_json_response("not json")


def test_parse_structured_validates_schema() -> None:
    parsed = parse_structured('{"name": "ProjectMind", "score": 10}', {
        "name": str,
        "score": int,
    })
    assert parsed["score"] == 10


def test_parse_structured_raises_on_schema_mismatch() -> None:
    with pytest.raises(ResponseParseError, match="expected int"):
        parse_structured('{"score": "high"}', {"score": int})


def test_complete_calls_ollama_chat_with_rendered_prompt(
    ai_settings: AISettings,
) -> None:
    client = MagicMock()
    client.chat.return_value = {
        "model": "qwen2.5-coder:7b",
        "message": {"content": " analysis "},
        "eval_count": 7,
    }
    manager = make_manager(ai_settings, client=client)

    text = manager.complete(
        "commit_summary",
        {
            "commit_hash": "abc123",
            "author": "Ada",
            "files_changed": "1",
            "diff": "+print('x')",
        },
    )

    assert text == "analysis"
    call = client.chat.call_args.kwargs
    assert call["model"] == "qwen2.5-coder:7b"
    assert call["messages"][0]["role"] == "system"
    assert "abc123" in call["messages"][1]["content"]
    assert call["options"]["num_predict"] == 512


def test_complete_collects_streamed_chunks(ai_settings: AISettings) -> None:
    client = MagicMock()
    client.chat.return_value = iter([
        {"model": "qwen2.5-coder:7b", "message": {"content": "hel"}},
        {
            "model": "qwen2.5-coder:7b",
            "message": {"content": "lo"},
            "eval_count": 2,
        },
    ])
    manager = make_manager(ai_settings, client=client)

    assert manager.complete(
        "refactor_suggestion",
        {"file_path": "a.py", "language": "python", "code": "x=1"},
        stream=True,
    ) == "hello"


def test_complete_raw_calls_ollama_generate(ai_settings: AISettings) -> None:
    client = MagicMock()
    client.generate.return_value = {
        "model": "qwen2.5-coder:7b",
        "response": " raw answer ",
        "eval_count": 3,
    }
    manager = make_manager(ai_settings, client=client)

    assert manager.complete_raw("ping") == "raw answer"
    assert client.generate.call_args.kwargs["prompt"] == "ping"


def test_ai_manager_falls_back_when_model_is_missing(
    ai_settings: AISettings,
) -> None:
    client = MagicMock()
    client.chat.side_effect = [
        Exception("model qwen2.5-coder:7b not found"),
        {
            "model": "qwen2.5:7b",
            "message": {"content": "fallback ok"},
            "eval_count": 4,
        },
    ]
    manager = make_manager(ai_settings, client=client)

    text = manager.complete(
        "doc_generation",
        {
            "module_name": "AI",
            "file_path": "ai.py",
            "analysis_json": "{}",
        },
    )

    assert text == "fallback ok"
    assert manager.active_model == "qwen2.5:7b"
    assert client.chat.call_args_list[1].kwargs["model"] == "qwen2.5:7b"


def test_ai_manager_reports_connection_refused(ai_settings: AISettings) -> None:
    client = MagicMock()
    client.chat.side_effect = ConnectionRefusedError("connection refused")
    manager = make_manager(ai_settings, client=client)

    with pytest.raises(AIError, match="Cannot reach Ollama"):
        manager.complete(
            "commit_summary",
            {
                "commit_hash": "abc123",
                "author": "Ada",
                "files_changed": "1",
                "diff": "+x",
            },
        )


def test_ai_manager_reports_timeout(ai_settings: AISettings) -> None:
    client = MagicMock()
    client.generate.side_effect = TimeoutError("slow")
    manager = make_manager(ai_settings, client=client)

    with pytest.raises(AIError, match="timed out"):
        manager.complete_raw("ping")


def test_is_available_returns_false_on_connection_error(
    ai_settings: AISettings,
) -> None:
    client = MagicMock()
    client.list.side_effect = ConnectionRefusedError("connection refused")
    manager = make_manager(ai_settings, client=client)

    assert manager.is_available() is False


def test_acomplete_uses_async_client(ai_settings: AISettings) -> None:
    async_client = MagicMock()
    async_client.chat = AsyncMock(return_value={
        "model": "qwen2.5-coder:7b",
        "message": {"content": "async ok"},
        "eval_count": 5,
    })
    manager = make_manager(ai_settings, async_client=async_client)

    text = asyncio.run(
        manager.acomplete(
            "code_analysis",
            {"file_path": "a.py", "language": "python", "code": "print(1)"},
        )
    )

    assert text == "async ok"
    assert async_client.chat.call_args.kwargs["model"] == "qwen2.5-coder:7b"


def test_ai_manager_logs_prompt_model_latency_and_tokens(
    ai_settings: AISettings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = MagicMock()
    client.generate.return_value = {
        "model": "qwen2.5-coder:7b",
        "response": "ok",
        "eval_count": 11,
    }
    manager = make_manager(ai_settings, client=client)

    with caplog.at_level("INFO", logger="projectmind.ai.ai_manager"):
        manager.complete_raw("ping")

    assert any(
        "prompt_name=<raw>" in record.message
        and "model=qwen2.5-coder:7b" in record.message
        and "latency_ms=" in record.message
        and "token_count=11" in record.message
        for record in caplog.records
    )


@pytest.fixture()
def isolated_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"paths:\n"
        f"  project_root: \"{tmp_path.as_posix()}\"\n"
        f"  logs_dir: \"logs\"\n"
        f"  vault_dir: \"vault\"\n",
        encoding="utf-8",
    )
    return cfg


def test_bootstrap_registers_ai_client(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_ollama = SimpleNamespace(
        ResponseError=RuntimeError,
        Client=MagicMock(return_value=MagicMock()),
        AsyncClient=MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setitem(sys.modules, "ollama", fake_ollama)

    from ai import AIManager
    from core import AIClient
    from core.bootstrap import bootstrap

    app = bootstrap(
        user_config_path=isolated_config,
        install_signal_handlers=False,
    )
    try:
        ai = app.registry.get(AIClient)
        assert isinstance(ai, AIManager)
    finally:
        app.shutdown()
