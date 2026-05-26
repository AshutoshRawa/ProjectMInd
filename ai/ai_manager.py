"""
AI Communication Engine for ProjectMind.

This is the only public interface for AI access.  Callers use
``get_ai().complete("prompt_name", variables)`` and never import Ollama or
prompt internals directly.
"""

from __future__ import annotations

import asyncio
import importlib
import time
from collections.abc import Iterable
from typing import Any

from core import AIClient, AIError, AISettings, get_logger

from ai.prompt_registry import PromptRegistry, _register_defaults

log = get_logger(__name__)

_instance: AIManager | None = None


def get_ai() -> AIManager:
    """Return the process-wide AI manager singleton."""
    if _instance is None:
        raise RuntimeError("AI engine is not initialised; call init_ai() first")
    return _instance


def init_ai(settings: AISettings | None = None) -> AIManager:
    """Initialise and return the process-wide AI manager singleton."""
    global _instance
    _instance = AIManager(settings=settings)
    return _instance


class AIManager(AIClient):
    """Ollama-backed AI client used by all ProjectMind modules."""

    name = "ai"

    def __init__(
        self,
        settings: AISettings | None = None,
        *,
        client: Any | None = None,
        async_client: Any | None = None,
    ) -> None:
        self._settings = settings or AISettings()
        self._host = self._settings.ollama_host
        self._model = self._settings.default_model
        self._fallback_model = self._settings.fallback_model
        self.active_model = self._model
        self._started = False

        self._ollama = None if client and async_client else _load_ollama()
        self._client = client or self._make_client("Client")
        self._async_client = async_client or self._make_client("AsyncClient")

        self._registry = PromptRegistry()
        _register_defaults(self._registry)

    def start(self) -> None:
        """Mark the AI service started after a lightweight availability check."""
        if not self.is_available():
            raise AIError(f"Ollama server unreachable at {self._host}")
        self._started = True

    def stop(self) -> None:
        """Stop the AI service."""
        self._started = False

    def healthy(self) -> bool:
        """Return True once the service has started successfully."""
        return self._started

    def complete(
        self,
        prompt_name: str,
        variables: dict[str, Any],
        stream: bool = False,
    ) -> str:
        """Render a registered prompt and return the model response text."""
        system_prompt, user_prompt = self._registry.render(prompt_name, variables)
        started_at = time.perf_counter()
        model = self._model

        response = self._chat_with_fallback(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            stream=stream,
        )
        text = _response_text(response, chat=True).strip()
        self._log_call(
            prompt_name=prompt_name,
            response=response,
            default_model=model,
            started_at=started_at,
        )
        return text

    def complete_raw(self, prompt_text: str) -> str:
        """Send a raw prompt to Ollama without using a prompt template."""
        started_at = time.perf_counter()
        model = self._model

        response = self._generate_with_fallback(prompt_text, model=model)
        text = _response_text(response, chat=False).strip()
        self._log_call(
            prompt_name="<raw>",
            response=response,
            default_model=model,
            started_at=started_at,
        )
        return text

    def is_available(self) -> bool:
        """Return True when the Ollama server can be reached."""
        try:
            self._client.list()
            return True
        except Exception as exc:  # noqa: BLE001
            log.debug("Ollama availability check failed: %s", exc)
            return False

    async def acomplete(
        self,
        prompt_name: str,
        variables: dict[str, Any],
        stream: bool = False,
    ) -> str:
        """Async version of :meth:`complete` using ``ollama.AsyncClient``."""
        system_prompt, user_prompt = self._registry.render(prompt_name, variables)
        started_at = time.perf_counter()
        model = self._model

        response = await self._achat_with_fallback(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            stream=stream,
        )
        text = _response_text(response, chat=True).strip()
        self._log_call(
            prompt_name=prompt_name,
            response=response,
            default_model=model,
            started_at=started_at,
        )
        return text

    async def acomplete_raw(self, prompt_text: str) -> str:
        """Async raw completion using ``ollama.AsyncClient``."""
        started_at = time.perf_counter()
        model = self._model

        response = await self._agenerate_with_fallback(prompt_text, model=model)
        text = _response_text(response, chat=False).strip()
        self._log_call(
            prompt_name="<raw>",
            response=response,
            default_model=model,
            started_at=started_at,
        )
        return text

    def on_file_change(self, event: object) -> None:
        """Receive EventBus/file watcher events for future AI workflows."""
        log.debug("[ai] watcher event received: %s", event)

    def _make_client(self, class_name: str) -> Any:
        client_cls = getattr(self._ollama, class_name)
        try:
            return client_cls(host=self._host, timeout=self._settings.timeout)
        except TypeError:
            return client_cls(host=self._host)

    def _chat_with_fallback(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        stream: bool,
    ) -> Any:
        try:
            return self._chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                stream=stream,
            )
        except AIError as exc:
            if self._should_fallback(exc, model):
                return self._chat(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model=self._fallback_model,
                    stream=stream,
                )
            raise

    def _chat(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        stream: bool,
    ) -> Any:
        try:
            response = self._client.chat(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=stream,
                options=self._options(),
            )
            self.active_model = model
            return _collect_stream(response) if stream else response
        except Exception as exc:  # noqa: BLE001
            raise self._to_ai_error(exc) from exc

    def _generate_with_fallback(self, prompt_text: str, *, model: str) -> Any:
        try:
            return self._generate(prompt_text, model=model)
        except AIError as exc:
            if self._should_fallback(exc, model):
                return self._generate(prompt_text, model=self._fallback_model)
            raise

    def _generate(self, prompt_text: str, *, model: str) -> Any:
        try:
            response = self._client.generate(
                model=model,
                prompt=prompt_text,
                stream=False,
                options=self._options(),
            )
            self.active_model = model
            return response
        except Exception as exc:  # noqa: BLE001
            raise self._to_ai_error(exc) from exc

    async def _achat_with_fallback(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        stream: bool,
    ) -> Any:
        try:
            return await self._achat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                stream=stream,
            )
        except AIError as exc:
            if self._should_fallback(exc, model):
                return await self._achat(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model=self._fallback_model,
                    stream=stream,
                )
            raise

    async def _achat(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        stream: bool,
    ) -> Any:
        try:
            response = await self._async_client.chat(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=stream,
                options=self._options(),
            )
            self.active_model = model
            return await _acollect_stream(response) if stream else response
        except Exception as exc:  # noqa: BLE001
            raise self._to_ai_error(exc) from exc

    async def _agenerate_with_fallback(self, prompt_text: str, *, model: str) -> Any:
        try:
            return await self._agenerate(prompt_text, model=model)
        except AIError as exc:
            if self._should_fallback(exc, model):
                return await self._agenerate(prompt_text, model=self._fallback_model)
            raise

    async def _agenerate(self, prompt_text: str, *, model: str) -> Any:
        try:
            response = await self._async_client.generate(
                model=model,
                prompt=prompt_text,
                stream=False,
                options=self._options(),
            )
            self.active_model = model
            return response
        except Exception as exc:  # noqa: BLE001
            raise self._to_ai_error(exc) from exc

    def _options(self) -> dict[str, Any]:
        return {
            "temperature": self._settings.temperature,
            "num_predict": self._settings.max_tokens,
        }

    def _should_fallback(self, exc: AIError, model: str) -> bool:
        return model != self._fallback_model and _is_model_missing(exc)

    def _to_ai_error(self, exc: Exception) -> AIError:
        response_error = getattr(self._ollama, "ResponseError", None)
        if response_error is not None and isinstance(exc, response_error):
            message = str(exc)
            if _looks_like_model_missing(message):
                return AIError(f"Ollama model not found: {message}")
            return AIError(f"Ollama error: {message}")

        message = str(exc)
        lowered = message.lower()
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) or "timeout" in lowered:
            return AIError(f"Ollama request timed out: {message}")
        if isinstance(exc, OSError) or "connection refused" in lowered:
            return AIError(f"Cannot reach Ollama at {self._host}: {message}")
        if _looks_like_model_missing(message):
            return AIError(f"Ollama model not found: {message}")
        return AIError(f"Ollama request failed: {message}")

    def _log_call(
        self,
        *,
        prompt_name: str,
        response: Any,
        default_model: str,
        started_at: float,
    ) -> None:
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        model = _get(response, "model", default_model)
        token_count = int(_get(response, "eval_count", 0) or 0)
        log.info(
            "AI call prompt_name=%s model=%s latency_ms=%d token_count=%d",
            prompt_name,
            model,
            latency_ms,
            token_count,
        )


def _load_ollama() -> Any:
    try:
        return importlib.import_module("ollama")
    except ModuleNotFoundError as exc:
        raise AIError(
            "The official 'ollama' package is required. Install it with "
            "`pip install ollama`."
        ) from exc


def _get(response: Any, key: str, default: Any = None) -> Any:
    if isinstance(response, dict):
        return response.get(key, default)
    return getattr(response, key, default)


def _response_text(response: Any, *, chat: bool) -> str:
    if chat:
        message = _get(response, "message", {})
        if isinstance(message, dict):
            return str(message.get("content", ""))
        return str(getattr(message, "content", ""))
    return str(_get(response, "response", ""))


def _collect_stream(response: Iterable[Any]) -> dict[str, Any]:
    content: list[str] = []
    final: Any = {}
    for chunk in response:
        final = chunk
        content.append(_response_text(chunk, chat=True))
    result = dict(final) if isinstance(final, dict) else {"model": _get(final, "model")}
    result["message"] = {"content": "".join(content)}
    result.setdefault("eval_count", _get(final, "eval_count", 0))
    return result


async def _acollect_stream(response: Any) -> dict[str, Any]:
    content: list[str] = []
    final: Any = {}
    async for chunk in response:
        final = chunk
        content.append(_response_text(chunk, chat=True))
    result = dict(final) if isinstance(final, dict) else {"model": _get(final, "model")}
    result["message"] = {"content": "".join(content)}
    result.setdefault("eval_count", _get(final, "eval_count", 0))
    return result


def _is_model_missing(exc: AIError) -> bool:
    return _looks_like_model_missing(str(exc))


def _looks_like_model_missing(message: str) -> bool:
    lowered = message.lower()
    return "model" in lowered and (
        "not found" in lowered or "does not exist" in lowered or "404" in lowered
    )
