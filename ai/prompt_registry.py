"""
ai/prompt_registry.py
=====================
Versioned prompt template registry for ProjectMind.

Every AI prompt used by ProjectMind is registered here as a
:class:`PromptTemplate`.  :class:`PromptRegistry` stores templates by
name and version, renders variable placeholders, and raises
:class:`~core.exceptions.PromptNotFoundError` for unknown names.

This module is an **internal** implementation detail of the ``ai``
package.  Other packages interact with prompts exclusively through
:meth:`ai.ai_manager.AIManager.complete`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from core import PromptNotFoundError


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PromptTemplate:
    """
    Immutable prompt definition.

    Attributes
    ----------
    name:
        Unique identifier used by callers of ``get_ai().complete(name, …)``.
    version:
        Semantic version string (e.g. ``"1.0"``).  Multiple versions of
        the same prompt can coexist; ``'latest'`` always resolves to the
        highest registered version.
    system_prompt:
        System-level instructions (role, constraints, output format).
    user_template:
        User-message template with ``{variable}`` placeholders that are
        filled at render time via :meth:`PromptRegistry.render`.
    description:
        Human-readable explanation shown in logs and admin views.
    """

    name: str
    version: str
    system_prompt: str
    user_template: str
    description: str = ""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class PromptRegistry:
    """
    Thread-safe, versioned store for :class:`PromptTemplate` objects.

    Usage::

        registry = PromptRegistry()
        registry.register(PromptTemplate(name="greet", version="1.0", ...))
        system, user = registry.render("greet", {"user": "Alice"})
    """

    def __init__(self) -> None:
        # name → {version → template}
        self._templates: dict[str, dict[str, PromptTemplate]] = defaultdict(dict)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, template: PromptTemplate) -> None:
        """
        Add or replace a template in the registry.

        If a template with the same ``(name, version)`` already exists
        it is silently overwritten.
        """
        self._templates[template.name][template.version] = template

    def get(self, name: str, version: str = "latest") -> PromptTemplate:
        """
        Retrieve a template by *name* and *version*.

        When *version* is ``'latest'`` the highest registered version
        (sorted lexicographically) is returned.

        Raises
        ------
        PromptNotFoundError
            If *name* is not registered or the requested version does
            not exist.
        """
        versions = self._templates.get(name)
        if not versions:
            available = sorted(self._templates.keys()) or ["(none)"]
            raise PromptNotFoundError(
                f"Prompt '{name}' not found. "
                f"Available prompts: {', '.join(available)}"
            )

        if version == "latest":
            # Highest version string (lexicographic)
            latest_ver = sorted(versions.keys())[-1]
            return versions[latest_ver]

        if version not in versions:
            available_versions = sorted(versions.keys())
            raise PromptNotFoundError(
                f"Prompt '{name}' version '{version}' not found. "
                f"Available versions: {', '.join(available_versions)}"
            )

        return versions[version]

    def render(
        self,
        name: str,
        variables: dict[str, Any],
        version: str = "latest",
    ) -> tuple[str, str]:
        """
        Look up a template and render its placeholders.

        Parameters
        ----------
        name:
            Template name.
        variables:
            Mapping of ``{placeholder}`` → value.
        version:
            Template version (default ``'latest'``).

        Returns
        -------
        tuple[str, str]
            ``(system_prompt, rendered_user_prompt)``

        Raises
        ------
        PromptNotFoundError
            If the template does not exist.
        KeyError
            If a required placeholder is missing from *variables*.
        """
        template = self.get(name, version)
        rendered_user = template.user_template.format_map(variables)
        return template.system_prompt, rendered_user

    def list_templates(self) -> list[str]:
        """Return sorted list of registered template names."""
        return sorted(self._templates.keys())

    def has(self, name: str) -> bool:
        """Return True if *name* is registered."""
        return name in self._templates


# ---------------------------------------------------------------------------
# Default templates
# ---------------------------------------------------------------------------

_SYSTEM_BASE = (
    "You are ProjectMind, an autonomous developer intelligence assistant.\n"
    "You help engineers understand software architecture, relationships between\n"
    "components, and how projects evolve over time.  Be precise, concise, and\n"
    "ground answers in the context provided.  Do not invent files or APIs that\n"
    "were not mentioned in the prompt."
)


def _register_defaults(registry: PromptRegistry) -> None:
    """Pre-register the four core prompt templates."""

    registry.register(PromptTemplate(
        name="code_analysis",
        version="1.0",
        system_prompt=_SYSTEM_BASE,
        user_template=(
            "Analyze the following code file.\n\n"
            "**File path:** {file_path}\n"
            "**Language:** {language}\n\n"
            "```\n{code}\n```\n\n"
            "Provide a JSON response with these fields:\n"
            "- purpose: one-sentence summary of what this file does\n"
            "- complexity: low | medium | high\n"
            "- key_functions: list of important function/method names\n"
            "- dependencies: list of imports or external dependencies\n"
            "- suggestions: list of potential improvements"
        ),
        description="Analyze a code file for purpose, complexity, and structure.",
    ))

    registry.register(PromptTemplate(
        name="doc_generation",
        version="1.0",
        system_prompt=(
            f"{_SYSTEM_BASE}\n\n"
            "You are generating Markdown documentation.  Use clear headings,\n"
            "bullet points, and code blocks where appropriate.  Output ONLY\n"
            "the Markdown document — no commentary."
        ),
        user_template=(
            "Generate comprehensive Markdown documentation for the following "
            "code analysis.\n\n"
            "**Module:** {module_name}\n"
            "**File path:** {file_path}\n\n"
            "Analysis data:\n```json\n{analysis_json}\n```\n\n"
            "Include sections for: Overview, API Reference, Dependencies, "
            "and Usage Examples."
        ),
        description="Generate Markdown documentation from a code analysis result.",
    ))

    registry.register(PromptTemplate(
        name="commit_summary",
        version="1.0",
        system_prompt=(
            f"{_SYSTEM_BASE}\n\n"
            "Summarize git diffs in clear, plain English.  Focus on *what*\n"
            "changed and *why* it matters.  Be concise — one paragraph for\n"
            "small diffs, a short bulleted list for larger ones."
        ),
        user_template=(
            "Summarize this git diff in plain English.\n\n"
            "**Commit:** {commit_hash}\n"
            "**Author:** {author}\n"
            "**Files changed:** {files_changed}\n\n"
            "```diff\n{diff}\n```"
        ),
        description="Summarize a git diff in plain English.",
    ))

    registry.register(PromptTemplate(
        name="refactor_suggestion",
        version="1.0",
        system_prompt=(
            f"{_SYSTEM_BASE}\n\n"
            "You are a senior code reviewer.  Suggest concrete improvements\n"
            "without applying them.  For each suggestion give:\n"
            "1. What to change\n"
            "2. Why it improves the code\n"
            "3. A brief code sketch (if helpful)\n\n"
            "Do NOT rewrite the entire file — focus on the highest-impact changes."
        ),
        user_template=(
            "Review the following code and suggest improvements.\n\n"
            "**File path:** {file_path}\n"
            "**Language:** {language}\n\n"
            "```\n{code}\n```\n\n"
            "Focus on: readability, maintainability, performance, and "
            "adherence to best practices."
        ),
        description="Suggest code improvements without applying them.",
    ))
