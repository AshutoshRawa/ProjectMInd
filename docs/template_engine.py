"""
docs/template_engine.py
=======================
Jinja2-based template renderer for documentation generation.

All templates are stored as string constants in this module — no
external template files.  This keeps deployment trivial and makes
templates easy to version alongside the code.
"""

from __future__ import annotations

from typing import Any

from jinja2 import BaseLoader, Environment, TemplateNotFound


# ---------------------------------------------------------------------------
# Template definitions
# ---------------------------------------------------------------------------

_TEMPLATES: dict[str, str] = {
    # ----- Main document layout -----
    "file_doc": """\
# {{ filename }}

> {{ ai_summary if ai_summary else "_No AI summary available._" }}

{% if extended_description %}
{{ extended_description }}

{% endif %}
## Functions

{% if functions %}
| Name | Params | Complexity | Docstring? |
|------|--------|------------|------------|
{% for fn in functions %}
| `{{ fn.name }}` | {{ fn.params | join(', ') if fn.params else '—' }} | {{ fn.complexity }} | {{ '✓' if fn.has_docstring else '✗' }} |
{% endfor %}
{% else %}
_No functions found._
{% endif %}

{% if anti_patterns %}
## Anti-Patterns

{% for ap in anti_patterns %}
- {{ ap }}
{% endfor %}

{% endif %}
## Dependencies

{% if imports %}
{% for imp in imports %}
- `{{ imp }}`
{% endfor %}
{% else %}
_No dependencies._
{% endif %}

{% if changelog %}
## Changelog

{{ changelog }}
{% endif %}
""",

    # ----- Standalone function table -----
    "function_table": """\
| Name | Params | Complexity | Docstring? |
|------|--------|------------|------------|
{% for fn in functions %}
| `{{ fn.name }}` | {{ fn.params | join(', ') if fn.params else '—' }} | {{ fn.complexity }} | {{ '✓' if fn.has_docstring else '✗' }} |
{% endfor %}
""",

    # ----- Standalone anti-patterns list -----
    "anti_patterns": """\
{% for ap in anti_patterns %}
- {{ ap }}
{% endfor %}
""",

    # ----- Standalone dependencies list -----
    "dependencies": """\
{% for imp in imports %}
- `{{ imp }}`
{% endfor %}
""",

    # ----- Standalone changelog block -----
    "changelog": """\
{% for entry in entries %}
- **[{{ entry.change_type }}]** {{ entry.description }} _{{ entry.timestamp | datetime_iso }}_
{% endfor %}
""",
}


# ---------------------------------------------------------------------------
# Custom Jinja2 loader (loads from the in-memory dict)
# ---------------------------------------------------------------------------

class _DictLoader(BaseLoader):
    """Load templates from the module-level ``_TEMPLATES`` dict."""

    def get_source(
        self, environment: Environment, template: str,
    ) -> tuple[str, str | None, bool]:
        if template not in _TEMPLATES:
            raise TemplateNotFound(template)
        source = _TEMPLATES[template]
        return source, template, lambda: True


# ---------------------------------------------------------------------------
# Jinja2 environment & filters
# ---------------------------------------------------------------------------

def _datetime_iso(value: float) -> str:
    """Jinja2 filter: unix timestamp → ``YYYY-MM-DD HH:MM``."""
    from datetime import datetime, timezone

    dt = datetime.fromtimestamp(value, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M")


def _yes_no(value: bool) -> str:
    """Jinja2 filter: boolean → ``✓`` / ``✗``."""
    return "✓" if value else "✗"


_env = Environment(
    loader=_DictLoader(),
    autoescape=False,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["datetime_iso"] = _datetime_iso
_env.filters["yes_no"] = _yes_no


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_doc_template(template_name: str, context: dict[str, Any]) -> str:
    """Render a named template with the given context.

    Parameters
    ----------
    template_name:
        One of the registered template names (``file_doc``,
        ``function_table``, ``anti_patterns``, ``dependencies``,
        ``changelog``).
    context:
        Variables to inject into the template.

    Returns
    -------
    str
        Rendered markdown string.

    Raises
    ------
    jinja2.TemplateNotFound
        If *template_name* is not registered.
    """
    template = _env.get_template(template_name)
    return template.render(**context)


def list_templates() -> list[str]:
    """Return sorted list of available template names."""
    return sorted(_TEMPLATES.keys())
