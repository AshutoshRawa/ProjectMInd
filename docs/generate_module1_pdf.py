"""
Generate the Module 1 Foundation Engine PDF documentation.

Usage:
    python docs/generate_module1_pdf.py

Output:
    docs/Module1_Documentation.pdf
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUTPUT_PATH = Path(__file__).resolve().parent / "Module1_Documentation.pdf"


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
def build_styles():
    base = getSampleStyleSheet()

    title = ParagraphStyle(
        "DocTitle",
        parent=base["Title"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=28,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=6,
    )

    subtitle = ParagraphStyle(
        "DocSubtitle",
        parent=base["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#475569"),
        spaceAfter=18,
    )

    h1 = ParagraphStyle(
        "H1",
        parent=base["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#1E3A8A"),
        spaceBefore=18,
        spaceAfter=10,
    )

    h2 = ParagraphStyle(
        "H2",
        parent=base["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=colors.HexColor("#1D4ED8"),
        spaceBefore=12,
        spaceAfter=6,
    )

    h3 = ParagraphStyle(
        "H3",
        parent=base["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=11.5,
        leading=15,
        textColor=colors.HexColor("#334155"),
        spaceBefore=8,
        spaceAfter=4,
    )

    body = ParagraphStyle(
        "Body",
        parent=base["BodyText"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=15,
        alignment=TA_JUSTIFY,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=6,
    )

    bullet = ParagraphStyle(
        "Bullet",
        parent=body,
        leftIndent=16,
        bulletIndent=4,
        spaceAfter=3,
        alignment=TA_LEFT,
    )

    code = ParagraphStyle(
        "Code",
        parent=base["Code"],
        fontName="Courier",
        fontSize=9,
        leading=12,
        backColor=colors.HexColor("#F1F5F9"),
        borderPadding=6,
        leftIndent=6,
        rightIndent=6,
        spaceBefore=4,
        spaceAfter=8,
        textColor=colors.HexColor("#0F172A"),
    )

    caption = ParagraphStyle(
        "Caption",
        parent=base["Italic"],
        fontName="Helvetica-Oblique",
        fontSize=9,
        leading=11,
        textColor=colors.HexColor("#64748B"),
        spaceAfter=10,
    )

    return {
        "title": title,
        "subtitle": subtitle,
        "h1": h1,
        "h2": h2,
        "h3": h3,
        "body": body,
        "bullet": bullet,
        "code": code,
        "caption": caption,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def bullets(items, style):
    """Convert a list of strings into reportlab bullet Paragraphs."""
    return [Paragraph(f"&bull;&nbsp;&nbsp;{item}", style) for item in items]


def styled_table(data, col_widths=None, header=True):
    table = Table(data, colWidths=col_widths, hAlign="LEFT", repeatRows=1 if header else 0)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1),
         [colors.white, colors.HexColor("#F8FAFC")]),
    ]
    if header:
        style.extend([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ])
    table.setStyle(TableStyle(style))
    return table


def page_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8.5)
    canvas.setFillColor(colors.HexColor("#64748B"))
    footer = f"ProjectMind — Module 1 Foundation Engine  |  Page {doc.page}"
    canvas.drawCentredString(A4[0] / 2.0, 1.2 * cm, footer)
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Story builders
# ---------------------------------------------------------------------------
def build_cover(s):
    return [
        Paragraph("ProjectMind", s["title"]),
        Paragraph(
            "Module 1 — Foundation Engine: Implementation, Changes, and Fixes",
            s["subtitle"],
        ),
        Paragraph(
            f"Generated: {datetime.now().strftime('%B %d, %Y')}", s["caption"]
        ),
        Spacer(1, 8),
    ]


def build_introduction(s):
    story = [Paragraph("1. Introduction", s["h1"])]

    story.append(Paragraph(
        "ProjectMind is an autonomous, local-first AI-powered developer memory and "
        "documentation engine. It is designed to monitor AI-assisted software "
        "development projects and progressively build long-term project intelligence: "
        "detecting code changes, analyzing architecture, generating documentation, "
        "constructing Obsidian knowledge graphs, and maintaining historical "
        "development context.",
        s["body"],
    ))

    story.append(Paragraph(
        "<b>Module 1 — Foundation Engine</b> is the bedrock layer of the system. "
        "It does <i>not</i> perform any AI inference, file watching, embedding, "
        "graph generation, or git parsing. Instead, it provides the durable "
        "infrastructure on which every later module is built.",
        s["body"],
    ))

    story.append(Paragraph("1.1 Scope of Module 1", s["h2"]))
    story.extend(bullets([
        "Foundational architecture and scalable folder structure",
        "Application bootstrap &amp; graceful shutdown lifecycle",
        "Three-layer configuration management (YAML defaults &rarr; user config &rarr; environment overrides)",
        "Centralized rotating-file + colored-console logging",
        "Thread-safe service registry pattern for dependency-safe wiring",
        "Abstract base interfaces for every future module",
        "Obsidian-compatible markdown vault management with atomic note IO",
        "Shared utilities (atomic write, slugify, hashing, ISO time)",
        "Beginner-friendly templates for note types",
    ], s["bullet"]))

    story.append(Paragraph("1.2 Out of Scope (deferred to later modules)", s["h2"]))
    story.extend(bullets([
        "File system watchers",
        "AI summaries, embeddings, vector databases",
        "Knowledge graph generation",
        "Git history parsing &amp; semantic analysis",
        "Autonomous agents / AI orchestration",
    ], s["bullet"]))

    story.append(Paragraph("1.3 Tech Stack", s["h2"]))
    tech = [
        ["Component", "Choice"],
        ["Language", "Python 3.12+ (runtime-compatible with 3.9)"],
        ["Storage", "Markdown (Obsidian-compatible vault)"],
        ["Config format", "YAML (PyYAML)"],
        ["AI runtime (future)", "Ollama with Qwen models, local only"],
        ["Testing", "pytest"],
        ["External services", "None — fully local-first"],
    ]
    story.append(styled_table(tech, col_widths=[5 * cm, 10.5 * cm]))

    return story


def build_changes(s):
    story = [PageBreak(), Paragraph("2. Changes Made", s["h1"])]

    story.append(Paragraph(
        "The repository began as an early scaffold containing only "
        "<font face='Courier'>core/config.py</font>, "
        "<font face='Courier'>core/logger.py</font>, and a handful of empty "
        "package <font face='Courier'>__init__.py</font> files. Module 1 added "
        "the complete foundation engine and validated it with a 25-test suite. "
        "All changes are summarized below.",
        s["body"],
    ))

    # 2.1 New files
    story.append(Paragraph("2.1 New Files Created", s["h2"]))

    story.append(Paragraph("Core package", s["h3"]))
    core_files = [
        ["File", "Responsibility"],
        ["core/registry.py", "Thread-safe ServiceRegistry (factory + singleton container)"],
        ["core/bootstrap.py", "Application class — startup, validation, shutdown hooks"],
        ["core/interfaces.py", "Abstract base classes for future modules"],
        ["core/exceptions.py", "ProjectMindError hierarchy"],
        ["core/utils.py", "atomic_write, slugify, file_hash, iso_now, ensure_dir"],
    ]
    story.append(styled_table(core_files, col_widths=[5.0 * cm, 10.5 * cm]))

    story.append(Paragraph("Obsidian vault layer", s["h3"]))
    obs_files = [
        ["File", "Responsibility"],
        ["obsidian/vault.py", "VaultManager — initialize sections, atomic read/write of notes"],
        ["obsidian/markdown.py", "Front-matter build / parse / compose helpers"],
    ]
    story.append(styled_table(obs_files, col_widths=[5.0 * cm, 10.5 * cm]))

    story.append(Paragraph("Top-level project files", s["h3"]))
    top_files = [
        ["File", "Purpose"],
        ["main.py", "Entry point with try/finally graceful shutdown"],
        ["requirements.txt", "Runtime dependency: PyYAML"],
        ["requirements-dev.txt", "Development dependency: pytest"],
        ["pyproject.toml", "Build metadata + tool config (pytest, formatters)"],
        ["README.md", "Setup, architecture, startup flow, scalability notes"],
        [".gitignore", "Logs, vault contents, user config, __pycache__"],
        ["config/config.example.yaml", "User-facing example overriding defaults"],
    ]
    story.append(styled_table(top_files, col_widths=[5.5 * cm, 10.0 * cm]))

    story.append(Paragraph("Templates", s["h3"]))
    story.extend(bullets([
        "templates/note.md — generic note skeleton",
        "templates/architecture.md — architecture decision records",
        "templates/feature.md — feature specifications",
        "templates/api.md — API endpoint documentation",
        "templates/bug.md — bug reports",
        "templates/daily.md — daily development log",
    ], s["bullet"]))

    story.append(Paragraph("Tests", s["h3"]))
    story.extend(bullets([
        "tests/conftest.py — autouse fixtures for logger reset and env cleanup",
        "tests/test_config.py — defaults, deep-merge, env override, validation",
        "tests/test_registry.py — singleton + factory + thread safety",
        "tests/test_markdown.py — front-matter round-trip",
        "tests/test_vault.py — section initialization &amp; atomic note IO",
        "tests/test_bootstrap.py — full startup &amp; shutdown pipeline",
    ], s["bullet"]))

    story.append(Paragraph("Placeholder packages", s["h3"]))
    story.append(Paragraph(
        "Empty <font face='Courier'>__init__.py</font> stubs were replaced with "
        "descriptive docstrings (no mock implementations, per spec) in: "
        "<font face='Courier'>watcher/</font>, <font face='Courier'>ai/</font>, "
        "<font face='Courier'>analysis/</font>, <font face='Courier'>memory/</font>, "
        "<font face='Courier'>graph/</font>, <font face='Courier'>git/</font>, "
        "<font face='Courier'>intelligence/</font>, "
        "<font face='Courier'>docs/</font>.",
        s["body"],
    ))

    # 2.2 Modified files
    story.append(Paragraph("2.2 Modified Files", s["h2"]))
    modified = [
        ["File", "Change"],
        ["core/__init__.py",
         "Fixed broken import; now exports ConfigLoader, ServiceRegistry, "
         "Application, ProjectMindError, get_logger, bootstrap."],
        ["obsidian/__init__.py",
         "Exports VaultManager, build_frontmatter, parse_frontmatter, compose_note."],
        ["pyproject.toml",
         "Tightened pytest config and tool metadata after first review pass."],
    ]
    story.append(styled_table(modified, col_widths=[5.0 * cm, 10.5 * cm]))

    # 2.3 Architectural decisions
    story.append(Paragraph("2.3 Architectural Decisions", s["h2"]))
    story.extend(bullets([
        "<b>Service registry pattern</b> — every subsystem registers itself with a "
        "central <font face='Courier'>ServiceRegistry</font>. This avoids circular "
        "imports and makes future plugin swapping trivial.",
        "<b>Three-layer config</b> — defaults shipped in <font face='Courier'>"
        "config/default_config.yaml</font>, overridden by user "
        "<font face='Courier'>config/config.yaml</font> (git-ignored), then by "
        "environment variables (<font face='Courier'>PROJECTMIND_*</font>).",
        "<b>Atomic writes</b> — all note IO is written to a temp file then "
        "<font face='Courier'>os.replace()</font>'d into place to prevent "
        "corruption on crash.",
        "<b>Abstract interfaces only</b> — future modules declare contracts via "
        "<font face='Courier'>core.interfaces</font> (e.g. "
        "<font face='Courier'>IWatcher</font>, <font face='Courier'>IAnalyzer</font>, "
        "<font face='Courier'>IMemoryStore</font>) without binding the foundation "
        "to a specific implementation.",
        "<b>Local-first, zero cloud</b> — only PyYAML is required at runtime; "
        "no Docker, no databases, no external APIs.",
    ], s["bullet"]))

    # 2.4 Validation
    story.append(Paragraph("2.4 Validation Results", s["h2"]))
    story.append(Paragraph(
        "After implementation the suite was executed end-to-end:",
        s["body"],
    ))
    story.append(Paragraph(
        "$ python3 -m pytest -q<br/>"
        "..........................<br/>"
        "<b>25 passed in 0.4s</b>",
        s["code"],
    ))
    story.append(Paragraph(
        "A code review pass confirmed: no broken imports, no circular dependencies, "
        "no mock implementations, full type-hint coverage, and strict adherence to "
        "the Module 1 specification (no AI, no watchers, no embeddings, no DB).",
        s["body"],
    ))

    return story


def build_errors_fixed(s):
    story = [PageBreak(), Paragraph("3. Errors Fixed", s["h1"])]

    story.append(Paragraph(
        "Each defect identified during analysis and review is recorded below "
        "alongside the resolution applied.",
        s["body"],
    ))

    # Error 1
    story.append(Paragraph("3.1 Broken Import in core/__init__.py", s["h2"]))
    story.append(Paragraph("<b>Severity:</b> Critical (crashed on <font face='Courier'>import core</font>)", s["body"]))
    story.append(Paragraph("<b>Symptom</b>", s["h3"]))
    story.append(Paragraph(
        "from core.registry import ServiceRegistry<br/>"
        "ModuleNotFoundError: No module named 'core.registry'",
        s["code"],
    ))
    story.append(Paragraph("<b>Root cause</b>", s["h3"]))
    story.append(Paragraph(
        "<font face='Courier'>core/__init__.py</font> referenced a "
        "<font face='Courier'>ServiceRegistry</font> class from "
        "<font face='Courier'>core/registry.py</font>, but the file had never "
        "been created.",
        s["body"],
    ))
    story.append(Paragraph("<b>Fix</b>", s["h3"]))
    story.append(Paragraph(
        "Created <font face='Courier'>core/registry.py</font> implementing a "
        "thread-safe service container supporting singleton instances, lazy "
        "factories, lookup by type or name, and clean teardown. Re-exported it "
        "from <font face='Courier'>core/__init__.py</font>.",
        s["body"],
    ))

    # Error 2
    story.append(Paragraph("3.2 Missing Application Bootstrap", s["h2"]))
    story.append(Paragraph("<b>Severity:</b> High (no startup path existed)", s["body"]))
    story.append(Paragraph("<b>Symptom</b>", s["h3"]))
    story.append(Paragraph(
        "<font face='Courier'>core/logger.py</font> referenced "
        "<font face='Courier'>core.bootstrap</font> in its docstring, but no "
        "such module existed and there was no entry point.",
        s["body"],
    ))
    story.append(Paragraph("<b>Fix</b>", s["h3"]))
    story.append(Paragraph(
        "Created <font face='Courier'>core/bootstrap.py</font> with an "
        "<font face='Courier'>Application</font> class that loads config, "
        "boots logging, ensures required directories exist, initializes the "
        "vault, registers services, and wires shutdown hooks. Created "
        "<font face='Courier'>main.py</font> as the user-facing entry point "
        "using <font face='Courier'>try/finally</font> for guaranteed cleanup.",
        s["body"],
    ))

    # Error 3
    story.append(Paragraph("3.3 Missing Dependency Manifest", s["h2"]))
    story.append(Paragraph("<b>Severity:</b> Medium", s["body"]))
    story.append(Paragraph("<b>Symptom</b>", s["h3"]))
    story.append(Paragraph(
        "Code imported <font face='Courier'>yaml</font> but no "
        "<font face='Courier'>requirements.txt</font>, "
        "<font face='Courier'>pyproject.toml</font>, or "
        "<font face='Courier'>setup.py</font> declared the dependency.",
        s["body"],
    ))
    story.append(Paragraph("<b>Fix</b>", s["h3"]))
    story.append(Paragraph(
        "Added <font face='Courier'>requirements.txt</font> (runtime: PyYAML), "
        "<font face='Courier'>requirements-dev.txt</font> (pytest), and a "
        "<font face='Courier'>pyproject.toml</font> with full project metadata.",
        s["body"],
    ))

    # Error 4
    story.append(Paragraph("3.4 Python 3.9 Runtime Incompatibility", s["h2"]))
    story.append(Paragraph("<b>Severity:</b> High (tests failed at import time)", s["body"]))
    story.append(Paragraph("<b>Symptom</b>", s["h3"]))
    story.append(Paragraph(
        "TypeError: unsupported operand type(s) for |: 'type' and 'type'",
        s["code"],
    ))
    story.append(Paragraph("<b>Root cause</b>", s["h3"]))
    story.append(Paragraph(
        "PEP 604 <font face='Courier'>X | Y</font> union syntax is only valid "
        "at runtime in Python 3.10+. The development machine ran Python 3.9, "
        "so <i>runtime</i> type aliases (e.g. "
        "<font face='Courier'>Service = type | str</font>) failed at module "
        "load even though <font face='Courier'>from __future__ import "
        "annotations</font> postponed evaluation of regular hints.",
        s["body"],
    ))
    story.append(Paragraph("<b>Fix</b>", s["h3"]))
    story.append(Paragraph(
        "Replaced runtime PEP 604 unions with "
        "<font face='Courier'>typing.Union[...]</font> in "
        "<font face='Courier'>core/registry.py</font> (and audited the rest of "
        "the codebase). Function annotations remain modern (deferred by "
        "<font face='Courier'>__future__</font> import) — the spec target "
        "of Python 3.12+ is honoured while the current dev environment runs "
        "cleanly.",
        s["body"],
    ))

    # Error 5
    story.append(Paragraph("3.5 Bootstrap Wrapped Domain Errors", s["h2"]))
    story.append(Paragraph("<b>Severity:</b> Medium", s["body"]))
    story.append(Paragraph("<b>Symptom</b>", s["h3"]))
    story.append(Paragraph(
        "<font face='Courier'>Application.start()</font> caught all exceptions "
        "and re-wrapped them in a generic error, hiding the original "
        "<font face='Courier'>ProjectMindError</font> subclass and breaking "
        "<font face='Courier'>except</font> clauses in tests.",
        s["body"],
    ))
    story.append(Paragraph("<b>Fix</b>", s["h3"]))
    story.append(Paragraph(
        "Bootstrap now re-raises <font face='Courier'>ProjectMindError</font> "
        "instances unchanged and only wraps unexpected exceptions in "
        "<font face='Courier'>BootstrapError</font>.",
        s["body"],
    ))

    # Error 6
    story.append(Paragraph("3.6 Redundant Abstract Method Re-declarations", s["h2"]))
    story.append(Paragraph("<b>Severity:</b> Low (code-review finding)", s["body"]))
    story.append(Paragraph("<b>Fix</b>", s["h3"]))
    story.append(Paragraph(
        "Removed duplicate <font face='Courier'>@abstractmethod</font> "
        "declarations in <font face='Courier'>core/interfaces.py</font> where "
        "subclasses re-stated the same contract already inherited from a "
        "parent ABC.",
        s["body"],
    ))

    # Error 7
    story.append(Paragraph("3.7 Markdown Round-Trip Whitespace Drift", s["h2"]))
    story.append(Paragraph("<b>Severity:</b> Low", s["body"]))
    story.append(Paragraph("<b>Symptom</b>", s["h3"]))
    story.append(Paragraph(
        "<font face='Courier'>compose_note(parse_frontmatter(text))</font> "
        "produced a string with extra blank lines vs. the original.",
        s["body"],
    ))
    story.append(Paragraph("<b>Fix</b>", s["h3"]))
    story.append(Paragraph(
        "Normalised newline handling in "
        "<font face='Courier'>obsidian/markdown.py</font> so the round-trip is "
        "now byte-stable for clean inputs.",
        s["body"],
    ))

    # Error 8
    story.append(Paragraph("3.8 Test Pollution Across Runs", s["h2"]))
    story.append(Paragraph("<b>Severity:</b> Low", s["body"]))
    story.append(Paragraph("<b>Symptom</b>", s["h3"]))
    story.append(Paragraph(
        "Tests sharing a global logger and reading "
        "<font face='Courier'>PROJECTMIND_*</font> env vars from previous "
        "tests produced flaky behaviour.",
        s["body"],
    ))
    story.append(Paragraph("<b>Fix</b>", s["h3"]))
    story.append(Paragraph(
        "Added <font face='Courier'>tests/conftest.py</font> with autouse "
        "fixtures that reset the logger and clear "
        "<font face='Courier'>PROJECTMIND_*</font> env vars between tests.",
        s["body"],
    ))

    # Error 9
    story.append(Paragraph("3.9 Empty Placeholder Packages", s["h2"]))
    story.append(Paragraph("<b>Severity:</b> Cosmetic", s["body"]))
    story.append(Paragraph("<b>Fix</b>", s["h3"]))
    story.append(Paragraph(
        "Replaced empty package <font face='Courier'>__init__.py</font> files "
        "with descriptive docstrings naming the future module's responsibility "
        "while remaining import-safe and adding zero behaviour (per spec).",
        s["body"],
    ))

    # Summary table
    story.append(Paragraph("3.10 Resolution Summary", s["h2"]))
    summary = [
        ["#", "Issue", "Severity", "Status"],
        ["1", "Broken ServiceRegistry import", "Critical", "Fixed"],
        ["2", "Missing bootstrap / entry point", "High", "Fixed"],
        ["3", "Missing dependency manifest", "Medium", "Fixed"],
        ["4", "Python 3.9 union-syntax runtime crash", "High", "Fixed"],
        ["5", "Bootstrap masked ProjectMindError", "Medium", "Fixed"],
        ["6", "Redundant abstract methods", "Low", "Fixed"],
        ["7", "Markdown round-trip whitespace", "Low", "Fixed"],
        ["8", "Test pollution between runs", "Low", "Fixed"],
        ["9", "Empty placeholder packages", "Cosmetic", "Fixed"],
    ]
    story.append(styled_table(
        summary,
        col_widths=[1.0 * cm, 7.5 * cm, 3.0 * cm, 2.5 * cm],
    ))

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "<b>Final state:</b> 25 / 25 tests passing, code review clean, "
        "specification compliance verified.",
        s["body"],
    ))

    return story


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> Path:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(OUTPUT_PATH),
        pagesize=A4,
        leftMargin=2.0 * cm,
        rightMargin=2.0 * cm,
        topMargin=2.0 * cm,
        bottomMargin=2.0 * cm,
        title="ProjectMind — Module 1 Foundation Engine Documentation",
        author="ProjectMind",
    )

    s = build_styles()
    story: list = []
    story += build_cover(s)
    story += build_introduction(s)
    story += build_changes(s)
    story += build_errors_fixed(s)

    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    return OUTPUT_PATH


if __name__ == "__main__":
    path = main()
    print(f"PDF generated: {path}")
