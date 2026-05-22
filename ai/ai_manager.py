"""
ai/ai_manager.py
================
High-level AI Communication Engine for ProjectMind.

:class:`AIManager` is the concrete implementation of
:class:`~core.interfaces.AIClient`.  It wires together:

- :class:`~ai.ollama_client.OllamaClient` — HTTP transport
- :class:`~ai.request_manager.RequestManager` — retries and backoff
- :class:`~ai.response_parser.ResponseParser` — JSON → text
- :class:`~ai.prompts.PromptBuilder` — prompt assembly

Watcher integration (Module 2) is limited to receiving
:class:`~watcher.events.FileChangeEvent` notifications at DEBUG level.
Analysis and documentation are intentionally **not** implemented here.
"""

from __future__ import annotations

from core.config import AISettings
from core.exceptions import AIError
from core.interfaces import AIClient
from core.logger import get_logger
from ai.ollama_client import OllamaClient
from ai.prompts import PromptBuilder
from ai.request_manager import RequestManager
from ai.response_parser import ResponseParser

log = get_logger(__name__)


class AIManager(AIClient):
    """
    Ollama-backed AI service for ProjectMind.

    Parameters
    ----------
    settings:
        AI section from :class:`~core.config.Settings`.
    """

    name = "ai"

    def __init__(self, settings: AISettings) -> None:
        self._settings = settings
        self._client = OllamaClient(settings)
        self._requests = RequestManager(settings)
        self._parser = ResponseParser()
        self._prompts = PromptBuilder()
        self._started = False
        self._model_in_use: str = settings.default_model

    # ------------------------------------------------------------------
    # AIClient / Service lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Verify Ollama is reachable and the configured model is available.

        Does not pull models — the operator must run ``ollama pull`` first.
        """
        if self._started:
            return

        log.info(
            "Starting AI engine — host=%s model=%s",
            self._settings.ollama_host,
            self._settings.default_model,
        )

        try:
            self._ensure_model_available()
            # Lightweight generate to confirm end-to-end communication.
            reply = self.generate(PromptBuilder.ping())
            log.info("AI engine ready (ping response: %r)", reply[:80])
            self._started = True
        except AIError:
            log.exception("AI engine failed startup health check")
            raise

    def stop(self) -> None:
        """Release the HTTP session."""
        self._client.close()
        self._started = False
        log.info("AI engine stopped")

    def healthy(self) -> bool:
        """True after a successful :meth:`start`."""
        return self._started

    def generate(self, prompt: str, *, model: str | None = None) -> str:
        """
        Send *prompt* to Ollama and return the model's text response.

        Uses the default model from config unless *model* is provided.
        On model-not-found errors, automatically retries with
        ``fallback_model`` once.
        """
        primary = model or self._settings.default_model
        try:
            return self._generate_once(prompt, model=primary)
        except AIError as exc:
            fallback = self._settings.fallback_model
            if primary == fallback:
                raise
            if self._is_model_missing_error(exc):
                log.warning(
                    "Model %r unavailable — falling back to %r",
                    primary,
                    fallback,
                )
                return self._generate_once(prompt, model=fallback)
            raise

    # ------------------------------------------------------------------
    # Watcher integration (receive events only — no analysis yet)
    # ------------------------------------------------------------------

    def on_file_change(self, event: object) -> None:
        """
        Receive debounced watcher events.

        Module 3 only acknowledges events at DEBUG level.  Module 4+
        will enqueue analysis jobs from this hook.
        """
        log.debug("[ai] watcher event received (not processed yet): %s", event)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def active_model(self) -> str:
        """Model name used for the most recent successful call."""
        return self._model_in_use

    @property
    def prompt_builder(self) -> PromptBuilder:
        """Shared :class:`~ai.prompts.PromptBuilder` instance."""
        return self._prompts

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _generate_once(self, prompt: str, *, model: str) -> str:
        def _call() -> str:
            payload = self._client.generate(prompt, model=model)
            return self._parser.parse_generate(payload)

        text = self._requests.execute(_call, label="ollama generate")
        self._model_in_use = model
        return text

    def _ensure_model_available(self) -> None:
        def _list() -> list[str]:
            payload = self._client.list_models()
            return self._parser.parse_tags(payload)

        names = self._requests.execute(_list, label="ollama tags")
        target = self._settings.default_model

        if not any(self._model_matches(name, target) for name in names):
            log.warning(
                "Model %r not found in Ollama tags (%d models listed). "
                "Run: ollama pull %s",
                target,
                len(names),
                target,
            )

    @staticmethod
    def _model_matches(installed: str, requested: str) -> bool:
        """
        Ollama tag names may include variant suffixes.

        Treat ``qwen2.5-coder:7b`` as matching related tag names.
        """
        return (
            installed == requested
            or installed.startswith(requested + "-")
            or installed.startswith(requested + ":")
            or requested in installed
        )

    @staticmethod
    def _is_model_missing_error(exc: AIError) -> bool:
        message = str(exc).lower()
        return "model" in message and (
            "not found" in message
            or "does not exist" in message
            or "404" in message
        )
