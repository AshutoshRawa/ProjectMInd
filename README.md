# ProjectMind

> **Autonomous AI-powered developer memory and documentation engine.**
>
> Local-first software intelligence — watches your codebase, analyzes architecture, generates docs, and builds an Obsidian-compatible knowledge graph you own.

---

## Modules

| # | Module | Status | Description |
|---|--------|--------|-------------|
| 1 | Foundation Engine | ✅ | Config, logging, registry, bootstrap, vault, EventBus |
| 2 | Watcher Engine | ✅ | Recursive filesystem monitoring with debounce |
| 3 | AI Communication | ✅ | Ollama/Qwen client with prompt templates |
| 4 | Code Analysis | ✅ | AST extraction, complexity, dependency mapping |
| 5 | Documentation Engine | ✅ | Markdown generation with frontmatter & changelogs |
| 6 | Graph Builder | 🔜 | Obsidian knowledge graph generation |
| 7+ | Memory, Git, Intelligence | 🔜 | Long-term memory, git parsing, synthesis |

---

## Quick Start

```bash
git clone <your-fork> ProjectMind && cd ProjectMind
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Optional: enable watcher + analysis
cp config/config.example.yaml config/config.yaml
# Edit config.yaml: set watcher.enabled: true, analysis.enabled: true

ollama pull qwen2.5-coder:7b   # required for AI features
python main.py
```

Override any config via environment variables:

```bash
PROJECTMIND_LOGGING__LEVEL=DEBUG PROJECTMIND_WATCHER__ENABLED=true python main.py
```

---

## Architecture

```
main.py → core.bootstrap
              │
    ┌─────────┼──────────┐
    ▼         ▼          ▼
 config    logger    vault (Obsidian)
              │
         ServiceRegistry
              ▲
    ┌────┬────┼────┬─────┐
    │    │    │    │     │
  M2   M3   M4   M5   M6+
watcher  ai  analysis docs  ...
```

**Rules:** All inter-module communication through `EventBus` only. Every module imports only from another module's `__init__.py`. All AI calls go through `get_ai().complete('prompt_name', variables)`.

---

## Module 1 — Foundation Engine

Core infrastructure for all modules:

- **Config** — 3-layer merge: `default_config.yaml` → `config.yaml` → `PROJECTMIND_*` env vars
- **Logger** — rotating file + colored console under `projectmind` namespace
- **ServiceRegistry** — thread-safe DI container with singleton + factory support
- **Bootstrap** — wires config → logger → vault → services → signal handlers
- **Vault** — Obsidian-compatible markdown store with atomic writes and YAML frontmatter
- **Interfaces** — abstract contracts (`FileWatcher`, `AIClient`, `Analyzer`, `MemoryEngine`, `GraphBuilder`)
- **EventBus** — synchronous pub/sub for decoupled module communication

---

## Module 2 — Watcher Engine

Recursive filesystem monitoring via `watchdog`:

- **Watches:** `backend/`, `frontend/`, `src/`, `app/` (configurable)
- **Tracks:** `.py`, `.js`, `.ts`, `.tsx`, `.jsx`, `.md`, `.json`
- **Ignores:** `node_modules`, `.git`, `__pycache__`, `dist`, `build`, `venv`, `.next`
- **Events:** `CREATED`, `MODIFIED`, `DELETED`, `MOVED` → debounced → published as `watcher.file_change`

```
watcher/
├── events.py           # FileChangeEvent, ChangeKind
├── filters.py          # extension + path filtering
├── file_tracker.py     # debounce + deduplication
├── watcher.py          # watchdog handler
└── watcher_manager.py  # FileWatcher service
```

---

## Module 3 — AI Communication Engine

Single interface to local Ollama (Qwen models):

- **`get_ai().complete("prompt_name", variables)`** — templated prompt rendering + model call
- **Fallback** — auto-switches to `fallback_model` when primary is missing
- **Prompts** — `code_analysis`, `doc_generation`, `commit_summary`, `refactor_suggestion`
- **Parsing** — extracts JSON from fenced/prose-wrapped responses, validates schemas
- **Async** — `acomplete()` / `acomplete_raw()` via `ollama.AsyncClient`

```yaml
# config/config.yaml
ai:
  ollama_host: "http://localhost:11434"
  default_model: "qwen2.5-coder:7b"
  fallback_model: "qwen2.5:7b"
  timeout: 120
  max_tokens: 4096
  temperature: 0.2
```

```
ai/
├── ai_manager.py       # AIManager service + get_ai() singleton
├── prompt_registry.py  # versioned prompt template store
└── response_parser.py  # JSON extraction + schema validation
```

---

## Module 4 — Code Analysis Engine

Static analysis + AI enrichment for Python files:

- **AST extraction** — functions, classes, imports, call graphs, docstring detection
- **Cyclomatic complexity** — per-function and weighted file-level score
- **Dependency mapping** — `build_dependency_graph()` for project-local imports
- **AI enrichment** — `code_analysis` prompt for summaries and anti-pattern detection
- **JSON serialization** — `FileAnalysis.to_dict()` / `.from_dict()` / `.to_json()` / `.from_json()`
- **EventBus** — subscribes to `watcher.file_change`, publishes `analysis.file_analyzed`

```
analysis/
├── analysis_types.py    # FileAnalysis, FunctionInfo dataclasses
├── analyzer_engine.py   # Module4AnalyzerEngine (EventBus service)
├── ast_analyzer.py      # Python AST extraction + analyze_python_file()
├── complexity.py        # cyclomatic_complexity() + file_complexity_score()
└── dependency_mapper.py # build_dependency_graph() + resolve_local_import()
```

### Key types

```python
@dataclass(frozen=True)
class FunctionInfo:
    name: str
    line_start: int
    line_end: int
    params: list[str]
    complexity: int       # cyclomatic
    has_docstring: bool
    calls: list[str]

@dataclass(frozen=True)
class FileAnalysis:
    path: str
    language: str
    lines_of_code: int
    functions: list[FunctionInfo]
    classes: list[str]
    imports: list[str]
    ai_summary: str
    anti_patterns: list[str]
    analyzed_at: float
```

---

## Module 5 — Documentation Engine

Generates structured markdown from analysis results. **Produces strings only — never writes to vault** (that's Module 8).

- **Frontmatter** — YAML block with file path, language, lines, complexity, tags
- **Doc generator** — deterministic markdown: H1 → blockquote summary → Functions table → Anti-Patterns → Dependencies → Changelog
- **Changelog** — diffs two `FileAnalysis` snapshots, detects `FUNCTION_ADDED`, `FUNCTION_REMOVED`, `COMPLEXITY_CHANGED`, `IMPORTS_CHANGED`, `AI_SUMMARY_CHANGED`
- **Templates** — Jinja2 templates stored as string constants (no external files)
- **AI usage** — only for optional extended description; structure is never AI-generated
- **EventBus** — subscribes to `analysis.file_analyzed`, publishes `docs.doc_updated`

```
docs/
├── frontmatter.py      # build_frontmatter(analysis) → YAML
├── doc_generator.py    # generate(analysis) → complete markdown
├── changelog.py        # ChangelogEntry, diff_analyses(), format_changelog()
├── template_engine.py  # Jinja2 templates + render_doc_template()
└── doc_engine.py       # Module5DocEngine (EventBus service)
```

### Example output

```markdown
---
file: src/utils.py
language: python
lines: 142
complexity: 3.4
last_analyzed: 2025-01-15T14:32:00
tags: [python, src, utils, projectmind]
---

# utils.py

> Utility module for JSON parsing and serialization.

## Functions

| Name | Params | Complexity | Docstring? |
|------|--------|------------|------------|
| `parse` | data, strict | 4 | ✓ |
| `dump` | obj | 1 | ✗ |

## Anti-Patterns

- Missing type annotations on dump()

## Dependencies

- `json`
- `pathlib.Path`

## Changelog

- **[FUNCTION_ADDED]** Function `parse` added _2025-01-15 14:32_
```

---

## Project Layout

```
ProjectMind/
├── core/               # M1 — config, logging, registry, bootstrap, EventBus
├── obsidian/           # M1 — vault manager + markdown helpers
├── watcher/            # M2 — filesystem monitoring
├── ai/                 # M3 — Ollama/Qwen AI client
├── analysis/           # M4 — code analysis engine
├── docs/               # M5 — documentation engine
├── memory/             # 🔜 M6 — long-term memory
├── graph/              # 🔜 M7 — Obsidian graph builder
├── git/                # 🔜 git history parsing
├── intelligence/       # 🔜 cross-module synthesis
├── config/             # YAML configuration files
├── templates/          # markdown note templates
├── vault/              # Obsidian knowledge store (gitignored)
├── logs/               # rotating logs (gitignored)
├── tests/              # pytest suite
├── main.py             # entry point
├── requirements.txt    # runtime deps: PyYAML, watchdog, ollama, Jinja2
└── pyproject.toml      # project metadata + pytest config
```

---

## Testing

```bash
pip install -r requirements-dev.txt
python3 -m pytest -q
```

**83 tests** covering: config, registry, vault, markdown, watcher, AI prompts/parsing/fallback, AST extraction, complexity, dependency mapping, EventBus flows, doc generation, changelog diffing, template rendering, and end-to-end service integration.

---

## License

TBD.
