"""
ai/response_parser.py
=======================
Parse and normalise Ollama HTTP JSON responses.

Ollama's ``/api/generate`` endpoint returns a JSON object whose primary
text field is ``response``.  This module extracts that text and surfaces
clear errors when the payload is malformed or reports failure.
"""

from __future__ import annotations

from typing import Any

from core.exceptions import AIError


class ResponseParser:
    """
    Stateless helper that turns raw Ollama JSON into plain text.

    Keeping parsing separate from transport (``ollama_client``) means
    tests can validate edge cases without mocking HTTP.
    """

    @staticmethod
    def parse_generate(payload: dict[str, Any]) -> str:
        """
        Extract the assistant text from an Ollama *generate* response.

        Parameters
        ----------
        payload:
            Decoded JSON body from ``POST /api/generate`` (non-streaming).

        Returns
        -------
        str
            Trimmed model output.

        Raises
        ------
        AIError
            If the payload is missing expected fields or reports an error.
        """
        if not isinstance(payload, dict):
            raise AIError(
                f"Expected JSON object from Ollama, got {type(payload).__name__}"
            )

        # Ollama may include an ``error`` field on partial failures.
        if error := payload.get("error"):
            raise AIError(f"Ollama returned an error: {error}")

        if "response" not in payload:
            raise AIError(
                "Ollama response missing 'response' field. "
                f"Keys present: {sorted(payload.keys())}"
            )

        text = payload["response"]
        if text is None:
            raise AIError("Ollama returned a null response")

        if not isinstance(text, str):
            raise AIError(
                f"Ollama 'response' must be a string, got {type(text).__name__}"
            )

        return text.strip()

    @staticmethod
    def parse_tags(payload: dict[str, Any]) -> list[str]:
        """
        Extract model names from ``GET /api/tags``.

        Used during health checks to confirm the configured model exists.
        """
        if not isinstance(payload, dict):
            raise AIError(
                f"Expected JSON object from Ollama tags, got {type(payload).__name__}"
            )

        models_raw = payload.get("models", [])
        if not isinstance(models_raw, list):
            raise AIError("Ollama tags response 'models' is not a list")

        names: list[str] = []
        for entry in models_raw:
            if isinstance(entry, dict) and "name" in entry:
                names.append(str(entry["name"]))
        return names
