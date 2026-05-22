"""
ai/
===
**Module 3 — AI Communication Engine**

Connects ProjectMind to a local Ollama server and Qwen models via HTTP.
Provides prompt assembly, retries, timeouts, and response parsing.

Public API
----------
- :class:`~ai.ai_manager.AIManager` — implements :class:`~core.interfaces.AIClient`
- :class:`~ai.prompts.PromptBuilder` — prompt templates
- :class:`~ai.ollama_client.OllamaClient` — low-level HTTP client
"""

from ai.ai_manager import AIManager
from ai.prompts import PromptBuilder, PromptBundle, PROJECTMIND_SYSTEM_PROMPT

__all__ = [
    "AIManager",
    "PromptBuilder",
    "PromptBundle",
    "PROJECTMIND_SYSTEM_PROMPT",
]
