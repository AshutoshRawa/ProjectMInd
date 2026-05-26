"""
Module 3: AI Communication Engine.

Only the manager entry points are public.  Prompt templates, response parsing,
and Ollama wiring stay behind ``AIManager``.
"""

from ai.ai_manager import AIManager, get_ai, init_ai

__all__ = ["AIManager", "get_ai", "init_ai"]
