"""
ai/prompts.py
===============
Prompt templates for the AI Communication Engine.

Module 3 only establishes *how* prompts are assembled — not what analysis
or documentation prompts contain.  Future modules (analysis, docs) will
add specialised builders on top of these primitives.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# System identity — reused whenever ProjectMind talks to the model
# ---------------------------------------------------------------------------

PROJECTMIND_SYSTEM_PROMPT = """\
You are ProjectMind, an autonomous developer intelligence assistant.

You help engineers understand software architecture, relationships between
components, and how projects evolve over time.  Be precise, concise, and
ground answers in the context provided.  Do not invent files or APIs that
were not mentioned in the prompt.
"""


@dataclass(frozen=True)
class PromptBundle:
    """
    A ready-to-send prompt with optional system context.

    Attributes
    ----------
    system:
        High-level instructions (role, tone, constraints).
    user:
        The task-specific user message.
    """

    system: str
    user: str

    def as_single_prompt(self) -> str:
        """
        Flatten system + user into one string for Ollama ``/api/generate``.

        Ollama's generate endpoint accepts a single ``prompt`` field.  We
        delimit sections clearly so Qwen can distinguish instructions from
        the task.
        """
        return (
            f"### System\n{self.system.strip()}\n\n"
            f"### User\n{self.user.strip()}\n\n"
            f"### Assistant\n"
        )


class PromptBuilder:
    """
    Factory for common ProjectMind prompt shapes.

    Usage::

        bundle = PromptBuilder().user_message("Explain this module.")
        text = bundle.as_single_prompt()
        ai_manager.generate(text)
    """

    def __init__(self, system: str = PROJECTMIND_SYSTEM_PROMPT) -> None:
        self._system = system

    def user_message(self, message: str) -> PromptBundle:
        """Wrap *message* with the default ProjectMind system prompt."""
        return PromptBundle(system=self._system, user=message)

    def custom(self, system: str, user: str) -> PromptBundle:
        """Build a prompt with explicit system and user sections."""
        return PromptBundle(system=system, user=user)

    @staticmethod
    def ping() -> str:
        """
        Minimal prompt for connectivity checks.

        Short and deterministic — used by :meth:`ai.ai_manager.AIManager.start`
        to verify Ollama responds without spending many tokens.
        """
        return "Reply with exactly: OK"
