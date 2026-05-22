"""
ai/ollama_client.py
===================
Low-level HTTP client for the Ollama REST API.

This module knows *how* to talk to Ollama (URLs, JSON bodies, status
codes).  Retry logic lives in :mod:`ai.request_manager`; orchestration
lives in :mod:`ai.ai_manager`.
"""

from __future__ import annotations

from typing import Any

import requests

from core.config import AISettings
from core.exceptions import AIError
from core.logger import get_logger

log = get_logger(__name__)


class OllamaClient:
    """
    Thin wrapper around Ollama's HTTP API.

    Parameters
    ----------
    settings:
        AI configuration from :class:`~core.config.Settings`.
    session:
        Optional :class:`requests.Session` for connection pooling / tests.
    """

    def __init__(
        self,
        settings: AISettings,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self._settings = settings
        self._host = settings.ollama_host.rstrip("/")
        self._session = session or requests.Session()

    @property
    def host(self) -> str:
        """Configured Ollama base URL."""
        return self._host

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """
        Call ``POST /api/generate`` and return the decoded JSON body.

        Parameters
        ----------
        prompt:
            Full prompt text (see :class:`~ai.prompts.PromptBundle`).
        model:
            Override the configured default model.
        timeout:
            Per-request timeout in seconds (defaults to ``settings.timeout``).

        Raises
        ------
        AIError
            On HTTP errors or non-JSON responses.
        requests.exceptions.Timeout
            Passed through for :class:`~ai.request_manager.RequestManager`.
        requests.exceptions.RequestException
            Passed through for retry handling.
        """
        model_name = model or self._settings.default_model
        timeout_sec = timeout if timeout is not None else self._settings.timeout

        url = f"{self._host}/api/generate"
        body = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self._settings.temperature,
                "num_predict": self._settings.max_tokens,
            },
        }

        log.debug(
            "Ollama generate request model=%s prompt_len=%d",
            model_name,
            len(prompt),
        )

        try:
            response = self._session.post(
                url,
                json=body,
                timeout=timeout_sec,
            )
        except requests.exceptions.Timeout:
            log.warning("Ollama request timed out after %ss", timeout_sec)
            raise
        except requests.exceptions.RequestException as exc:
            log.warning("Ollama request failed: %s", exc)
            raise

        return self._decode_response(response)

    def list_models(self, *, timeout: int = 10) -> dict[str, Any]:
        """
        Call ``GET /api/tags`` to list locally available models.

        Used for startup health checks.
        """
        url = f"{self._host}/api/tags"
        try:
            response = self._session.get(url, timeout=timeout)
        except requests.exceptions.RequestException as exc:
            raise AIError(f"Cannot reach Ollama at {self._host}: {exc}") from exc

        return self._decode_response(response)

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_response(response: requests.Response) -> dict[str, Any]:
        """Raise :class:`AIError` on bad status codes; return JSON dict."""
        if response.status_code >= 400:
            detail = response.text[:500] if response.text else "(empty body)"
            raise AIError(
                f"Ollama HTTP {response.status_code}: {detail}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise AIError(
                f"Ollama returned non-JSON body (status {response.status_code})"
            ) from exc

        if not isinstance(data, dict):
            raise AIError(
                f"Ollama JSON root must be an object, got {type(data).__name__}"
            )

        return data
