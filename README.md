# ProjectMind

> **Autonomous AI-powered developer memory and documentation engine.**
>
> Local-first software intelligence — *not* a chatbot, *not* an agent
> framework, *not* an AI wrapper.

ProjectMind watches AI-assisted software projects and incrementally builds
long-term **project intelligence**: architecture maps, feature histories,
bug timelines, API catalogues, and an Obsidian-compatible knowledge graph
you actually own.

This repository ships **Module 1: Foundation Engine**, **Module 2: Watcher Engine**, **Module 3: AI Communication Engine**, and **Module 4: Code & Architecture Analysis**. Higher modules (memory engine, graph builder, git intelligence, etc.) are stubbed as interfaces and filled in over time — see [Roadmap](#roadmap).

---

## Table of contents

1. [What's in Module 1](#whats-in-module-1)
2. [Module 2 Documentation](#module-2-documentation)
3. [Module 3 Documentation](#module-3-documentation)
4. [Module 4 Documentation](#module-4-documentation)
5. [Quick start](#quick-start)
6. [Project layout](#project-layout)
7. [Architecture](#architecture)
8. [Startup flow](#startup-flow)
9. [Configuration](#configuration)
10. [Logging](#logging)
11. [The vault](#the-vault)
12. [Testing](#testing)
13. [Roadmap](#roadmap)
14. [Future scalability notes](#future-scalability-notes)

---

## What's in Module 1

Module 1 is the **foundation engine** — everything required for later
modules to plug in cleanly.  It contains:

- ✅ Foundational architecture & scalable folder layout
- ✅ Application bootstrapper (`core/bootstrap.py`)
- ✅ YAML configuration system with env-var overrides (`core/config.py`)
- ✅ Centralised rotating + colour logger (`core/logger.py`)
- ✅ Service registry (`core/registry.py`)
- ✅ Abstract interfaces for future modules (`core/interfaces.py`)
- ✅ Shared utilities (`core/utils.py`)
- ✅ Obsidian-compatible vault manager (`obsidian/vault.py`)
- ✅ Markdown + YAML front-matter helpers (`obsidian/markdown.py`)
- ✅ Custom exception hierarchy (`core/exceptions.py`)
- ✅ Graceful shutdown via SIGINT/SIGTERM
- ✅ Pytest suite for the foundation

**Module 2 (Watcher Engine)** adds recursive filesystem monitoring with ignore rules, extension filters, and debounced event logging.

**Module 3 (AI Communication Engine)** connects the system to a local Ollama server running Qwen models, enabling secure prompt-response generation, automated error retries, exponential backoffs, and strict response structural validation.

**Module 4 (Code & Architecture Analysis)** consumes watcher events through `EventBus`, extracts Python structure with AST analysis, enriches file summaries through the registered `code_analysis` AI prompt, and publishes structured analysis results.

**Not implemented yet** (intentionally): embeddings, vector DBs, graph generation, git parsing, memory synthesis. Those land in later modules.

---

## Module 2 Documentation

Module 2 is the **Watcher Engine**. It extends the foundation engine with
recursive filesystem monitoring while deliberately avoiding AI,
summarisation, markdown generation, graph generation, or code analysis.

The watcher integrates with Module 1 by reusing:

- `core.config.Settings` for watcher configuration
- `core.logger.get_logger()` for event logging
- `core.bootstrap.bootstrap()` for service registration
- `core.interfaces.FileWatcher` as the service contract
- `core.exceptions.WatcherError` for startup/runtime failures

### What Module 2 does

When enabled, ProjectMind monitors these directories under
`paths.project_root`:

- `backend/`
- `frontend/`
- `src/`
- `app/`

It detects:

- file creation
- file modification
- file deletion
- file moves/renames

It tracks only these file extensions:

- `.py`
- `.js`
- `.ts`
- `.tsx`
- `.jsx`
- `.md`
- `.json`

It ignores noisy/generated folders:

- `node_modules`
- `.git`
- `__pycache__`
- `pycache`
- `dist`
- `build`
- `venv`
- `.venv`
- `.next`
- `coverage`

### Watcher package layout

```
watcher/
├── __init__.py           # lightweight public event exports
├── events.py             # normalized FileChangeEvent model
├── file_tracker.py       # debounce + duplicate event collapse
├── filters.py            # extension and ignored-path filtering
├── watcher.py            # watchdog event handler
└── watcher_manager.py    # FileWatcher service implementation
```

### Runtime flow

1. `ConfigLoader` loads the `watcher` section from YAML/env vars.
2. `bootstrap()` registers `WatcherManager` when `watcher.enabled=true`.
3. `main.py` starts the watcher and keeps the process alive.
4. Watchdog emits raw filesystem events.
5. `ProjectMindEventHandler` filters unsupported paths and extensions.
6. `FileTracker` debounces bursts and minimizes duplicate events.
7. Stable `FileChangeEvent` records are logged at `INFO`.
8. On shutdown, pending events are flushed and the observer stops cleanly.

### Example log output

```text
[watcher] modified: /path/to/project/src/app.py
[watcher] created: /path/to/project/backend/routes.py
[watcher] deleted: /path/to/project/frontend/old-widget.tsx
```

### Module 2 boundaries

Module 2 only builds watcher infrastructure. It does not call AI models,
generate documentation, write markdown notes, create embeddings, parse git,
or perform semantic code analysis. Those responsibilities belong to later
modules that will consume watcher events.

---

## Module 3 Documentation

Module 3 is the **AI Communication Engine**. It provides the single ProjectMind interface for communicating with a local [Ollama](https://ollama.com) instance running a Qwen model, using the official `ollama` Python package and registered prompt templates for all model calls.

The AI engine integrates seamlessly with Module 1 & Module 2 by reusing:
- `core.Settings` / `core.AISettings` (loading configuration under the `ai` section)
- `core.get_logger()` for all debug, trace, warning, and error activity
- `core.bootstrap.bootstrap()` for global bootstrap service registration as `AIClient`
- `watcher.watcher_manager.WatcherManager` event hooks (subscribing `AIManager.on_file_change` to events for future downstream analysis triggers)

### What Module 3 does
- **Connection Diagnostics**: Performs an Ollama model-list availability check on start.
- **Smart Model Fallback**: Falls back to the configured `fallback_model` when Ollama reports the default model is missing.
- **Registered Prompt Templates**: Routes all templated calls through `AIManager.complete(prompt_name, variables)` and the internal prompt registry.
- **Async Support**: Provides async completion methods backed by `ollama.AsyncClient`.
- **Strict Response Parsing**: Parses JSON from fenced or prose-wrapped model responses and validates simple structured schemas.
- **Call Logging**: Logs every AI call with prompt name, model, latency, and token count.

### AI Engine package layout
```text
ai/
├── __init__.py           # public exports (AIManager, get_ai, init_ai)
├── ai_manager.py         # public AI interface and Ollama coordination
├── prompt_registry.py    # internal registered prompt templates
└── response_parser.py    # internal JSON parsing and schema validation
```

### Config properties
Configuration is declared under the `ai` block in your settings:
```yaml
ai:
  # Ollama server REST endpoint
  ollama_host: "http://localhost:11434"
  # Target Qwen model (must be pulled: ollama pull qwen2.5-coder:14b)
  default_model: "qwen2.5-coder:14b"
  # Fallback model to try when the default model is missing
  fallback_model: "qwen2.5-coder:14b"
  # Connection and inference timeout limit (seconds)
  timeout: 120
  # Maximum prediction token length
  max_tokens: 4096
  # Generative temperature (0.0 = deterministic, 1.0 = creative)
  temperature: 0.2
  # Reserved for future retry policy
  max_retries: 3
  # Reserved for future retry policy
  retry_backoff_seconds: 1.0
```

### Runtime Flow & Lifecycle
1. `bootstrap()` parses settings, initializes `AIManager`, and registers it as `AIClient`.
2. `main.py` invokes `ai.start()`.
3. `AIManager` verifies Ollama connectivity through the official package's model-list call.
4. Downstream modules call `get_ai().complete("prompt_name", variables)` for templated prompts or `complete_raw()` for health checks and diagnostics.
5. When the system shuts down, `Application.shutdown` invokes `AIManager.stop()`.

---

## Module 4 Documentation

Module 4 is the **Code & Architecture Analysis** engine. It subscribes to watcher file-change events through `core.EventBus`, performs lightweight static analysis, optionally enriches the result with the Module 3 AI client, and emits structured analysis payloads back onto the event bus.

The analyzer integrates with earlier modules by reusing:
- `core.AnalysisSettings` for analysis configuration
- `core.EventBus` for all module-to-module communication
- `core.Analyzer` as the service contract
- `core.get_logger()` for lifecycle and error logging
- `ai.get_ai().complete("code_analysis", variables)` for AI enrichment
- `watcher.FileChangeEvent` from the public watcher package surface

### What Module 4 does

For supported file-change events, Module 4:

- handles deleted, missing, oversized, and empty files without calling AI
- detects the file language from extension
- extracts Python functions, classes, imports, line counts, call names, docstring presence, and approximate cyclomatic complexity
- sends code to the registered `code_analysis` prompt for AI summary and improvement signals
- parses plain JSON, fenced JSON, and lightly malformed JSON with trailing commas
- publishes `analysis.file_analyzed` events containing structured analysis data

### Analysis package layout

```text
analysis/
├── __init__.py             # public exports
├── analysis_types.py       # FileAnalysis and FunctionInfo data models
├── analyzer_engine.py      # Analyzer service and EventBus wiring
├── ast_analyzer.py         # Python AST extraction
├── complexity.py           # cyclomatic complexity helper
└── dependency_mapper.py    # local dependency graph helper
```

### Runtime flow

1. `bootstrap()` creates the shared `EventBus`.
2. When `analysis.enabled=true`, `bootstrap()` registers `Module4AnalyzerEngine` as `Analyzer`.
3. `main.py` starts the analyzer service.
4. The watcher publishes `watcher.file_change` events through `EventBus`.
5. Module 4 queues accepted `FileChangeEvent` payloads on a worker thread.
6. The worker performs static analysis and AI enrichment.
7. Module 4 publishes an `analysis.file_analyzed` payload for downstream memory, graph, or documentation modules.

### Example output payload

```python
{
    "file_path": "/path/to/project/src/calculator.py",
    "language": "python",
    "change_kind": "modified",
    "analysis": {
        "path": "/path/to/project/src/calculator.py",
        "language": "python",
        "lines_of_code": 42,
        "functions": [
            {
                "name": "add",
                "line_start": 10,
                "line_end": 12,
                "params": ["a", "b"],
                "complexity": 1,
                "has_docstring": true,
                "calls": [],
            }
        ],
        "classes": ["Calculator"],
        "imports": ["math"],
        "ai_summary": "Provides calculator helpers.",
        "anti_patterns": ["Add error handling for invalid input."],
        "analyzed_at": 1779863479.117874,
    },
}
```

### Module 4 boundaries

Module 4 analyzes and emits file intelligence only. It does not write Obsidian notes, create long-term memory, update graph files, parse git history, or directly call Ollama. AI access stays behind `get_ai().complete("code_analysis", variables)`.

---

## Quick start

### Requirements

- Python **3.12+**
- (Future modules) [Ollama](https://ollama.com) with a Qwen model pulled

### Install

```bash
git clone <your-fork> ProjectMind
cd ProjectMind

python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
# For development / running tests:
pip install -r requirements-dev.txt
```

### First run

```bash
python main.py
```

You should see colourised log output indicating that:

1. Configuration loaded from `config/default_config.yaml`
2. Logger initialised (file + console)
3. Vault directory and section folders created
4. Core services registered
5. Bootstrap complete, clean exit

Log files are written to `logs/projectmind.log` (rotating, 5 MB × 5).

### Module 2 — enable the watcher

1. Ensure the directories you want monitored exist under your
   `paths.project_root` (e.g. `backend/`, `frontend/`, `src/`, `app/`).
2. Enable the watcher in config or via environment variable:

```yaml
# config/config.yaml
watcher:
  enabled: true
```

```bash
export PROJECTMIND_WATCHER__ENABLED=true
python main.py
```

ProjectMind will stay running, log debounced file events at `INFO`, and
exit cleanly on Ctrl+C.  Ignored paths include `node_modules`, `.git`,
`__pycache__`, `dist`, `build`, `venv`, `.next`, and `coverage`.

### Module 4 — enable analysis

Module 4 needs the watcher and AI engine because file changes arrive through
`EventBus` and AI enrichment uses the registered `code_analysis` prompt.

```yaml
# config/config.yaml
watcher:
  enabled: true
analysis:
  enabled: true
```

```bash
ollama pull qwen2.5-coder:14b
python main.py
```

Create or edit a supported file under one of the watched directories
(`backend/`, `frontend/`, `src/`, or `app/`) and Module 4 will publish an
`analysis.file_analyzed` event.

### Customising

Copy the example config and edit:

```bash
cp config/config.example.yaml config/config.yaml
```

Or override any value via environment variable using the
`PROJECTMIND_<SECTION>__<KEY>` convention:

```bash
export PROJECTMIND_LOGGING__LEVEL=DEBUG
export PROJECTMIND_AI__OLLAMA_HOST="http://192.168.1.10:11434"
python main.py
```

---

## Project layout

```
ProjectMind/
├── core/                  # foundation engine — config, logging, registry, bootstrap
│   ├── bootstrap.py
│   ├── config.py
│   ├── exceptions.py
│   ├── interfaces.py
│   ├── logger.py
│   ├── registry.py
│   └── utils.py
├── obsidian/              # Obsidian-compatible vault + markdown helpers
│   ├── markdown.py
│   └── vault.py
├── watcher/               # Module 2 — file change detection
├── ai/                    # Module 3 — Ollama / Qwen integration
├── analysis/              # Module 4 — code & architecture analysis
├── memory/                # 🔜 Module 5 — long-term project memory
├── graph/                 # 🔜 Module 6 — Obsidian graph generation
├── git/                   # 🔜 git history parsing
├── intelligence/          # 🔜 cross-module synthesis layer
├── docs/                  # 🔜 documentation generators
├── config/
│   ├── default_config.yaml      # shipped defaults — do not edit
│   └── config.example.yaml      # template for user overrides
├── templates/             # markdown templates used when generating notes
├── vault/                 # Obsidian-compatible knowledge store (gitignored content)
├── logs/                  # rotating log files (gitignored)
├── tests/                 # pytest suite
├── main.py
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

---

## Architecture

ProjectMind follows clean-architecture principles tuned for a long-lived,
plugin-ready local system:

```
             ┌──────────────────────────────────────────┐
             │              main.py                     │
             │  (entry point — drives Application)      │
             └──────────────────────────────────────────┘
                              │
                              ▼
             ┌──────────────────────────────────────────┐
             │         core.bootstrap                   │
             │   builds Settings, Logger, Vault,        │
             │   ServiceRegistry — wires everything     │
             └──────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────────┐
        ▼                     ▼                         ▼
 ┌───────────────┐   ┌────────────────┐       ┌──────────────────┐
 │ core.config   │   │  core.logger   │       │  obsidian.vault  │
 │  (Settings)   │   │ (rotating+TTY) │       │  (NoteStore)     │
 └───────────────┘   └────────────────┘       └──────────────────┘
                              │
                              ▼
             ┌──────────────────────────────────────────┐
             │       core.registry.ServiceRegistry      │
             │  ←  future modules look up collaborators │
             └──────────────────────────────────────────┘
                              ▲
     ┌────────────┬───────────┴───────────┬────────────┐
     │            │                       │            │
  watcher/      ai/                  analysis/    memory/   …
  (M2)         (M3)                    (M4)        (M5)
```

**Key principles**

- **Infrastructure ↔ Domain split** — `core/` and `obsidian/` are
  infrastructure; future `analysis/`, `intelligence/`, `memory/` are
  domain.  Domain packages may depend on infrastructure but never the
  reverse.
- **No circular imports** — every module touches `core` directly and
  reaches sibling services through public package surfaces, service
  interfaces, and EventBus messages.
- **Interfaces over implementations** — `core/interfaces.py` defines the
  contracts; concrete classes are wired only inside `bootstrap.py`.
- **Plugin-ready** — registering a new service is a one-liner in
  bootstrap, paving the way for a future plugin auto-loader.
- **Async-ready** — nothing in the foundation pins us to a sync model;
  services can later expose `async start/stop` overloads.

---

## Startup flow

1. **`main.py`** calls `core.bootstrap.bootstrap()`.
2. **`ConfigLoader`** reads `config/default_config.yaml`, deep-merges
   `config/config.yaml` (if present), then applies any
   `PROJECTMIND_*` env-vars and validates the result.
3. **Directories** — `logs/` and `vault/` (with all configured sections)
   are created if missing.
4. **`logger.bootstrap()`** wires a rotating file handler and a
   colourised console handler under the `projectmind` namespace.
5. **`VaultManager.initialize()`** creates the section folders
   (`Architecture`, `Features`, `APIs`, …) and an `.obsidian/` marker.
6. **`ServiceRegistry`** is created and the canonical services are
   registered: `Settings`, `ServiceRegistry` itself, `VaultManager`,
   `project_root`, `logs_dir`.
7. **Signal handlers** for `SIGINT` / `SIGTERM` are bound so Ctrl-C
   triggers graceful shutdown hooks instead of an ugly traceback.
8. **AI**, **Watcher**, and **Analysis** services are registered according
   to config flags and wired through the shared `EventBus`.
9. The fully-built **`Application`** handle is returned to `main`.

Shutdown runs every registered hook in LIFO order, swallowing
individual failures so one misbehaving module cannot block the rest.

---

## Configuration

Merge order (later overrides earlier):

1. `config/default_config.yaml`  — shipped defaults
2. `config/config.yaml`           — your overrides (gitignored)
3. `PROJECTMIND_<SECTION>__<KEY>` — environment variables

Double-underscore separates nesting:

| Env var                              | Maps to                  |
|--------------------------------------|--------------------------|
| `PROJECTMIND_LOGGING__LEVEL=DEBUG`   | `logging.level`          |
| `PROJECTMIND_AI__TIMEOUT=300`        | `ai.timeout`             |
| `PROJECTMIND_PATHS__VAULT_DIR=/data` | `paths.vault_dir`        |

Values are coerced to `bool`/`int`/`float`/`str` automatically.

To generate a starter user config from the bundled example:

```bash
python -c "from core.config import ConfigLoader; ConfigLoader().generate_default_config()"
```

---

## Logging

- Single namespace: `projectmind` (children: `projectmind.core.config`, …)
- Two handlers wired in `bootstrap()`:
  - **File** → `logs/projectmind.log`, rotating at 5 MB × 5 backups,
    plain UTF-8 format
  - **Console** → ANSI-coloured if the terminal supports it, plain
    otherwise
- Get a logger anywhere with:

```python
from core.logger import get_logger
log = get_logger(__name__)
log.info("hello")
```

---

## The vault

The vault is just a directory tree that **doubles as an Obsidian vault**.
ProjectMind owns *write* access; you (or Obsidian) own *read* access.

```
vault/
├── .obsidian/         # auto-created marker so Obsidian recognises the folder
├── Architecture/      # high-level system design notes
├── Features/          # per-feature lifecycle
├── APIs/              # endpoint catalogues
├── Bugs/              # incident & fix history
├── Daily/             # day-by-day project logs
├── Generated/         # AI-generated raw output (Module 3+)
├── Graphs/            # graph data exported by Module 6
├── AI-Prompts/        # prompt templates and traces
└── Memory/            # long-term project memory snapshots
```

Writing a note from code:

```python
from core.bootstrap import bootstrap
from obsidian.vault import VaultManager

app = bootstrap()
vault: VaultManager = app.registry.get(VaultManager)

vault.write_note(
    section="Architecture",
    name="Service Layout",
    body="# Service layout\n\nThe foundation engine wires …",
    frontmatter_extras={"tags": ["architecture", "module-1"]},
)
```

---

## Testing

```bash
pip install -r requirements-dev.txt
pytest -q
```

The test suite covers:

- Config loading, deep-merge, env override, validation
- Service registry register/get/has/replace semantics
- Vault initialisation, write/read round-trip, missing sections
- Markdown front-matter parse + compose round-trip
- Watcher filters, debounce tracker, and live observer smoke test
- AI prompt rendering, response parsing, fallback handling, and async calls
- Module 4 AST extraction, EventBus analysis flow, delete handling, and AI enrichment parsing

---

## Roadmap

| Module | Status | Description                                          |
|--------|--------|------------------------------------------------------|
| 1      | ✅     | Foundation engine (this repo)                        |
| 2      | ✅     | File watcher with debounced event pipeline           |
| 3      | ✅     | Ollama / Qwen client + AI service abstraction        |
| 4      | ✅     | Code & architecture analysis                          |
| 5      | 🔜     | Long-term memory engine                               |
| 6      | 🔜     | Obsidian graph builder                                |
| 7+     | 🔜     | Git history parsing, intelligence synthesis, plugins |

---

## Future scalability notes

The foundation was deliberately built for the long haul:

- **Plugin loader** — `ServiceRegistry` is the natural drop-in point.
  A future `core/plugins.py` can scan an `entry_points` group and call
  `registry.register(...)` for each discovered service.
- **Async pipelines** — the `Service` base class can grow `async_start`
  / `async_stop` overloads without breaking existing callers; the
  registry is already thread-safe.
- **Multi-project indexing** — `paths.project_root` is settable per
  bootstrap call, so a future supervisor can spin up one
  `Application` per indexed project, each with its own vault.
- **Event bus** — watchers, AI, and analysis communicate through the
  in-process `EventBus`, keeping higher modules decoupled as memory,
  graph, and documentation pipelines are added.
- **No DB lock-in** — Module 1 is markdown-only.  When a vector DB is
  needed (Module 5+) it will hide behind a `MemoryEngine` interface
  and stay swappable.
- **Local-first forever** — every external integration goes through an
  interface in `core/interfaces.py`, so cloud variants can be added
  without touching the foundation.

---

## License

TBD.
