"""
ai/request_manager.py
=====================
Retry and backoff wrapper for Ollama HTTP calls.

Transient failures (timeouts, connection resets, 5xx responses) are
retried with exponential backoff.  Permanent failures (4xx except 429,
malformed responses) fail fast so callers get a clear error.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, TypeVar

import requests

from core.config import AISettings
from core.exceptions import AIError
from core.logger import get_logger

log = get_logger(__name__)

T = TypeVar("T")

# HTTP status codes that warrant a retry.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class RequestManager:
    """
    Execute callables with configurable retry and exponential backoff.

    Parameters
    ----------
    settings:
        Supplies ``max_retries``, ``retry_backoff_seconds``, and ``timeout``.
    """

    def __init__(self, settings: AISettings) -> None:
        self._max_retries = settings.max_retries
        self._backoff = settings.retry_backoff_seconds

    def execute(self, operation: Callable[[], T], *, label: str = "request") -> T:
        """
        Run *operation* up to ``max_retries + 1`` times.

        Parameters
        ----------
        operation:
            Zero-argument callable that performs one HTTP attempt.
        label:
            Short name for log messages (e.g. ``"generate"``).

        Returns
        -------
        T
            Whatever *operation* returns on success.

        Raises
        ------
        AIError
            After all attempts are exhausted.
        """
        attempts = self._max_retries + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                return operation()
            except AIError:
                # Domain errors from our client are not transient — do not retry.
                raise
            except requests.exceptions.Timeout as exc:
                last_error = exc
                log.warning(
                    "%s timed out (attempt %d/%d)",
                    label,
                    attempt,
                    attempts,
                )
            except requests.exceptions.ConnectionError as exc:
                last_error = exc
                log.warning(
                    "%s connection failed (attempt %d/%d): %s",
                    label,
                    attempt,
                    attempts,
                    exc,
                )
            except requests.exceptions.HTTPError as exc:
                last_error = exc
                status = exc.response.status_code if exc.response is not None else 0
                if status not in _RETRYABLE_STATUS:
                    raise AIError(f"{label} failed with HTTP {status}") from exc
                log.warning(
                    "%s HTTP %s (attempt %d/%d)",
                    label,
                    status,
                    attempt,
                    attempts,
                )
            except requests.exceptions.RequestException as exc:
                last_error = exc
                log.warning(
                    "%s request error (attempt %d/%d): %s",
                    label,
                    attempt,
                    attempts,
                    exc,
                )

            if attempt < attempts:
                delay = self._backoff * (2 ** (attempt - 1))
                log.debug("Retrying %s in %.1fs …", label, delay)
                time.sleep(delay)

        raise AIError(
            f"{label} failed after {attempts} attempt(s): {last_error}"
        ) from last_error
