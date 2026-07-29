# ProjectMind

> **Autonomous AI-powered developer memory and documentation engine.**
>
> Local-first software intelligence — watches your codebase, analyzes architecture, generates docs, and builds an Obsidian-compatible knowledge graph you own.

---

## Table of Contents

- [What Is ProjectMind?](#what-is-projectmind)
- [The Problem It Solves](#the-problem-it-solves)
- [Features](#features)
- [Architecture Overview](#architecture-overview)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Environment Variables](#environment-variables)
- [Running ProjectMind](#running-projectmind)
- [Usage](#usage)
- [Module Reference](#module-reference)
- [Project Layout](#project-layout)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## What Is ProjectMind?

ProjectMind is a fully local, privacy-first tool that sits alongside your codebase and continuously learns about it. It uses a local LLM (Ollama + Qwen) to perform static analysis, generate documentation, track architectural changes, build a dependency graph, maintain a semantic memory store, summarize git commits, and surface refactoring suggestions — all written to an Obsidian-compatible markdown vault that you own and control.

No data ever leaves your machine.

---

## The Problem It Solves

- **Institutional knowledge loss** — Engineers leave, and with them goes the understanding of *why* code looks the way it does. ProjectMind continuously captures that context.
- **Stale or missing documentation** — Docs go out of date the moment they're written. ProjectMind regenerates documentation automatically whenever files change.
- **Invisible architectural drift** — Circular dependencies, orphan modules, and complexity hotspots accumulate silently. ProjectMind detects them and suggests fixes.
- **Fragmented understanding** — Onboarding a new team member means reading thousands of lines. ProjectMind provides semantic search and natural-language Q&A over the entire codebase.

---

## Features

| # | Module | Description |
|---|--------|-------------|
| 1 | **Foundation Engine** | Config (3-layer merge), logging (rotating + colored console), service registry (DI), EventBus (pub/sub), vault abstraction |
| 2 | **Watcher Engine** | Recursive filesystem monitoring via `watchdog` with debounce, extension filtering, and ignore patterns |
| 3 | **AI Communication** | Local Ollama/Qwen client with versioned prompt templates, JSON response parsing, async support, and automatic model fallback |
| 4 | **Code Analysis** | Python AST extraction (functions, classes, imports, call graphs), cyclomatic complexity scoring, dependency mapping, AI-enriched summaries |
| 5 | **Documentation Engine** | Markdown generation with YAML frontmatter, function tables, anti-pattern sections, dependency lists, and changelogs |
| 6 | **Graph Engine** | Incremental directed dependency graph (NetworkX) — orphan detection, hub analysis, cycle detection, complexity hotspots |
| 7 | **Memory Engine** | Semantic long-term memory via ChromaDB + `sentence-transformers` — chunking, embedding, similarity search |
| 8 | **Obsidian Engine** | Async vault writer — `[[wikilinks]]`, note builder, index, link resolver, rich Obsidian-compatible notes |
| 9 | **Git Integration** | Commit monitor, AI-powered diff summarizer, commit memory store for semantic retrieval |
| 10 | **Intelligence Engine** | Autonomous anti-pattern detection, AI-generated refactoring suggestions, natural-language codebase Q&A |

All modules communicate through a decoupled **EventBus** and can be enabled or disabled independently.

---

## Architecture Overview

```
main.py → core.bootstrap
              │
    ┌─────────┼──────────────────────────┐
    ▼         ▼                          ▼
 config    logger                vault (Obsidian)
              │
         ServiceRegistry
              ▲
    ┌────┬────┼────┬─────┬────┬────┬────┐
    │    │    │    │     │    │    │    │
   M2   M3   M4   M5   M6   M7   M8  M9/M10
watcher ai analysis docs graph mem obsidian intel
```

### EventBus Event Flow

```
watcher.file_change
    └─► analysis.file_analyzed
            ├─► docs.doc_updated
            │       └─► obsidian.note_written
            ├─► graph.graph_updated
            │       └─► intelligence.suggestions_ready
            └─► (memory chunks upserted)

git.commit
    └─► git.commit_summarized
            └─► (commit stored in memory)
```

**Design rules:**
- All inter-module communication goes through the `EventBus` — no direct cross-module calls.
- Every module imports only from another module's `__init__.py`.
- All AI calls route through `get_ai().complete("prompt_name", variables)`.

---

## Prerequisites

| Requirement | Version | Purpose |
|-------------|---------|---------|
| **Python** | ≥ 3.12 | Runtime |
| **Ollama** | Latest | Local LLM inference server |
| **Qwen model** | `qwen2.5-coder:14b` (recommended) | Code analysis, doc generation, commit summaries, refactoring suggestions |
| **Git** | Any recent version | Required if you enable the Git Integration module (M9) |

### Installing Ollama

Follow the instructions at [ollama.com](https://ollama.com) to install Ollama for your OS. Once installed:

```bash
# Start the Ollama server (if not running as a system service)
ollama serve

# Pull the recommended model
ollama pull qwen2.5-coder:14b
```

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/ProjectMind.git
cd ProjectMind

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

# 3. Install runtime dependencies
pip install -r requirements.txt

# 4. (Optional) Install dev/test dependencies
pip install -r requirements-dev.txt

# 5. Create your local config file
cp config/config.example.yaml config/config.yaml
```

> **Note:** `config/config.yaml` is git-ignored, so your local settings are never committed.

---

## Configuration

ProjectMind uses a **3-layer configuration merge**:

1. `config/default_config.yaml` — built-in defaults (do not edit)
2. `config/config.yaml` — your local overrides (copy from `config.example.yaml`)
3. `PROJECTMIND_*` environment variables — highest priority, override everything

### Key Configuration Sections

Edit `config/config.yaml` to enable modules and customize behavior:

```yaml
# --- Application identity ---
app:
  instance_id: "my-laptop"       # Useful for multi-project setups

# --- Paths ---
paths:
  project_root: "."              # The codebase ProjectMind will learn about
  vault_dir: "vault"             # Obsidian-compatible output vault
  logs_dir: "logs"               # Rotating log files

# --- Logging ---
logging:
  level: "INFO"                  # DEBUG | INFO | WARNING | ERROR | CRITICAL
  console_color: true
  max_bytes: 5242880             # 5 MB per log file
  backup_count: 5

# --- AI (Ollama) ---
ai:
  ollama_host: "http://localhost:11434"
  default_model: "qwen2.5-coder:14b"
  fallback_model: "qwen2.5-coder:14b"
  timeout: 120
  max_tokens: 4096
  temperature: 0.2

# --- Enable modules individually ---
watcher:      { enabled: true }
analysis:     { enabled: true }
docs:         { enabled: true }
graph:        { enabled: true }
memory:       { enabled: true }
obsidian:     { enabled: true }
git:          { enabled: true }
intelligence: { enabled: true }
```

### Module-specific Configuration

<details>
<summary><strong>Watcher (Module 2)</strong></summary>

```yaml
watcher:
  enabled: true
  watch_dirs: ["backend", "frontend", "src", "app"]
  debounce_seconds: 2.0
  watch_extensions: [".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".json"]
  ignore_patterns:
    - "**/__pycache__/**"
    - "**/.git/**"
    - "**/node_modules/**"
    - "**/dist/**"
    - "**/build/**"
    - "**/venv/**"
```
</details>

<details>
<summary><strong>Analysis (Module 4)</strong></summary>

```yaml
analysis:
  enabled: true
  batch_size: 20                 # Max files per analysis batch
  max_file_size: 524288          # Skip files > 512 KB
```
</details>

<details>
<summary><strong>Memory (Module 7)</strong></summary>

```yaml
memory:
  enabled: true
  chroma_db_path: ".chroma"
  embedding_model: "all-MiniLM-L6-v2"
  retention_days: 90
```
</details>

<details>
<summary><strong>Git (Module 9)</strong></summary>

```yaml
git:
  enabled: true
  repo_path: "."
  poll_interval_seconds: 60.0
```
</details>

<details>
<summary><strong>Intelligence (Module 10)</strong></summary>

```yaml
intelligence:
  enabled: true
  cycle_interval_seconds: 3600   # Background analysis every 60 minutes
  min_severity: "medium"         # low | medium | high
  store_path: ".suggestions"
```
</details>

---

## Environment Variables

Any configuration value can be overridden via an environment variable prefixed with `PROJECTMIND_`. Nested keys use double underscores (`__`) as separators.

| Variable | Config equivalent | Example |
|----------|-------------------|---------|
| `PROJECTMIND_LOGGING__LEVEL` | `logging.level` | `DEBUG` |
| `PROJECTMIND_WATCHER__ENABLED` | `watcher.enabled` | `true` |
| `PROJECTMIND_AI__OLLAMA_HOST` | `ai.ollama_host` | `http://192.168.1.50:11434` |
| `PROJECTMIND_AI__DEFAULT_MODEL` | `ai.default_model` | `qwen2.5-coder:7b` |
| `PROJECTMIND_AI__TIMEOUT` | `ai.timeout` | `180` |
| `PROJECTMIND_AI__TEMPERATURE` | `ai.temperature` | `0.1` |
| `PROJECTMIND_MEMORY__ENABLED` | `memory.enabled` | `true` |
| `PROJECTMIND_GIT__ENABLED` | `git.enabled` | `true` |
| `PROJECTMIND_GIT__POLL_INTERVAL_SECONDS` | `git.poll_interval_seconds` | `120` |
| `PROJECTMIND_INTELLIGENCE__ENABLED` | `intelligence.enabled` | `true` |
| `PROJECTMIND_INTELLIGENCE__MIN_SEVERITY` | `intelligence.min_severity` | `low` |
| `PROJECTMIND_PATHS__PROJECT_ROOT` | `paths.project_root` | `/home/user/myproject` |

Example — run with debug logging and the watcher enabled:

```bash
PROJECTMIND_LOGGING__LEVEL=DEBUG PROJECTMIND_WATCHER__ENABLED=true python main.py
```

---

## Running ProjectMind

```bash
# Make sure Ollama is running
ollama serve  # or it may already be running as a system service

# Activate your virtual environment
source .venv/bin/activate

# Run ProjectMind
python main.py
```

On startup, `main.py` will:

1. Bootstrap the foundation engine (config → logger → vault → service registry)
2. Connect to Ollama and verify the AI model is available
3. Start each enabled module in dependency order (Analysis → Docs → Graph → Memory → Obsidian → Git → Intelligence → Watcher)
4. If the watcher is enabled, block and monitor the filesystem until you press `Ctrl+C`
5. On shutdown, all services are stopped gracefully and pending state is persisted

### Common Run Patterns

```bash
# Minimal — just test the foundation + AI connection
python main.py

# Watch a codebase and generate docs
PROJECTMIND_WATCHER__ENABLED=true \
PROJECTMIND_ANALYSIS__ENABLED=true \
PROJECTMIND_DOCS__ENABLED=true \
PROJECTMIND_OBSIDIAN__ENABLED=true \
python main.py

# Full pipeline — everything enabled
PROJECTMIND_WATCHER__ENABLED=true \
PROJECTMIND_ANALYSIS__ENABLED=true \
PROJECTMIND_DOCS__ENABLED=true \
PROJECTMIND_GRAPH__ENABLED=true \
PROJECTMIND_MEMORY__ENABLED=true \
PROJECTMIND_OBSIDIAN__ENABLED=true \
PROJECTMIND_GIT__ENABLED=true \
PROJECTMIND_INTELLIGENCE__ENABLED=true \
python main.py
```

> **Tip:** It's simpler to set `enabled: true` in `config/config.yaml` for the modules you want, rather than passing many environment variables.

---

## Usage

### Watching a Codebase

Point `paths.project_root` at your target project and enable the watcher:

```yaml
paths:
  project_root: "/path/to/your/project"

watcher:
  enabled: true
  watch_dirs: ["src", "lib"]     # Subdirectories to monitor
```

ProjectMind will detect file changes and propagate them through the pipeline:

**File change** → **AST analysis** → **Doc generation** → **Graph update** → **Memory upsert** → **Obsidian note** → **Intelligence scan**

### Opening the Vault in Obsidian

1. Open [Obsidian](https://obsidian.md/)
2. Choose **Open folder as vault**
3. Select the `vault/` directory inside your ProjectMind installation
4. Browse generated notes, explore `[[wikilinks]]` between files, and use Obsidian's graph view to visualize your codebase

### Codebase Q&A (Module 10)

When the Intelligence Engine is enabled, you can use `query_codebase()` programmatically for natural-language questions about your code — it combines semantic memory search with AI reasoning.

---

## Module Reference

### Module 1 — Foundation Engine (`core/`)

Core infrastructure shared by all modules:

- **Config** — 3-layer merge: `default_config.yaml` → `config.yaml` → `PROJECTMIND_*` env vars
- **Logger** — rotating file + colored console output under the `projectmind` namespace
- **ServiceRegistry** — thread-safe dependency injection container (singleton + factory patterns)
- **Bootstrap** — wires config → logger → vault → services → signal handlers
- **Vault** — Obsidian-compatible markdown store with atomic writes and YAML frontmatter
- **Interfaces** — abstract contracts (`FileWatcher`, `AIClient`, `Analyzer`, `MemoryEngine`, `GraphBuilder`)
- **EventBus** — synchronous pub/sub for decoupled inter-module communication

### Module 2 — Watcher Engine (`watcher/`)

Recursive filesystem monitoring via `watchdog`:

- **Watches:** configurable directories (default: `backend/`, `frontend/`, `src/`, `app/`)
- **Tracks:** `.py`, `.js`, `.ts`, `.tsx`, `.jsx`, `.md`, `.json`
- **Ignores:** `node_modules`, `.git`, `__pycache__`, `dist`, `build`, `venv`, `.next`
- **Events:** `CREATED`, `MODIFIED`, `DELETED`, `MOVED` → debounced → published as `watcher.file_change`

### Module 3 — AI Communication Engine (`ai/`)

Single interface to local Ollama (Qwen models):

- **`get_ai().complete("prompt_name", variables)`** — templated prompt rendering + model call
- **Fallback** — auto-switches to `fallback_model` when the primary is unavailable
- **Prompts** — `code_analysis`, `doc_generation`, `commit_summary`, `refactor_suggestion`
- **Parsing** — extracts JSON from fenced/prose-wrapped responses, validates schemas
- **Async** — `acomplete()` / `acomplete_raw()` via `ollama.AsyncClient`

### Module 4 — Code Analysis Engine (`analysis/`)

Static analysis + AI enrichment for Python files:

- AST extraction — functions, classes, imports, call graphs, docstring detection
- Cyclomatic complexity — per-function and weighted file-level scoring
- Dependency mapping — project-local import graph construction
- AI enrichment — summaries and anti-pattern detection via the `code_analysis` prompt

### Module 5 — Documentation Engine (`docs/`)

Converts analysis results into structured markdown (never writes to disk directly):

- YAML frontmatter (file, language, lines, complexity, tags, timestamps)
- Function tables, anti-pattern sections, dependency lists
- Changelog with diff detection (`FUNCTION_ADDED`, `FUNCTION_REMOVED`, `COMPLEXITY_CHANGED`, `IMPORTS_CHANGED`, `AI_SUMMARY_CHANGED`)

### Module 6 — Graph Engine (`graph/`)

Incremental directed dependency graph backed by NetworkX:

- **Mutations:** `update_node`, `update_edges`, `remove_node` — only touches affected nodes
- **Queries:** `get_neighbors`, `get_related_files` (BFS within N hops)
- **Analysis:** orphan detection, hub analysis (high in-degree), cycle detection (Johnson's algorithm), complexity hotspots
- **Persistence:** auto-saves to `graph_state.json` every 10 updates

### Module 7 — Memory Engine (`memory/`)

Semantic long-term memory backed by ChromaDB:

- Chunker splits analysis results into overlapping text chunks with metadata
- Embedder uses `all-MiniLM-L6-v2` via `sentence-transformers`
- Similarity search returns ranked `MemoryChunk` results
- 90-day configurable retention window

### Module 8 — Obsidian Engine (`obsidian/`)

Writes analysis results as rich Obsidian-compatible notes:

- Async write queue with atomic file operations
- In-memory vault index (stem → path lookups)
- `[[wikilink]]` resolution with path disambiguation
- Note builder assembles: frontmatter + doc body + graph links + semantic neighbors

### Module 9 — Git Integration (`git_integration/`)

Monitors commits and stores AI-generated summaries:

- Polls `git log` for new commits at a configurable interval
- Sends diffs to AI for structured `CommitSummary` generation
- Stores summaries in ChromaDB for semantic retrieval

### Module 10 — Intelligence Engine (`intelligence/`)

Autonomous analysis that synthesizes across all modules:

- Pattern detection: high complexity, orphans, hubs, circular dependencies
- AI-generated refactoring suggestions with rationale
- Deduplication by pattern fingerprint
- 60-minute background analysis cycle + triggered by graph updates
- `query_codebase()` for natural-language Q&A over the codebase

---

## Project Layout

```
ProjectMind/
├── main.py                 # Entry point
├── pyproject.toml          # Project metadata + pytest config
├── requirements.txt        # Runtime dependencies
├── requirements-dev.txt    # Dev/test dependencies (includes runtime)
│
├── core/                   # M1 — Config, logging, registry, bootstrap, EventBus
├── watcher/                # M2 — Filesystem monitoring
├── ai/                     # M3 — Ollama/Qwen AI client
├── analysis/               # M4 — Code analysis engine
├── docs/                   # M5 — Documentation engine
├── graph/                  # M6 — Dependency graph engine
├── memory/                 # M7 — ChromaDB semantic memory
├── obsidian/               # M8 — Obsidian vault writer
├── git_integration/        # M9 — Git commit monitor + summarizer
├── intelligence/           # M10 — Autonomous pattern detection + Q&A
│
├── config/                 # Configuration files
│   ├── default_config.yaml # Built-in defaults (do not edit)
│   └── config.example.yaml # Copy to config.yaml for local overrides
│
├── templates/              # Markdown note templates (Jinja2)
├── vault/                  # Obsidian knowledge vault (git-ignored)
├── logs/                   # Rotating log files (git-ignored)
└── tests/                  # Pytest test suite
```

---

## Testing

```bash
# Install dev dependencies (if not already installed)
pip install -r requirements-dev.txt

# Run the full test suite
python3 -m pytest -q

# Run tests with verbose output
python3 -m pytest -v

# Run a specific test file
python3 -m pytest tests/test_analysis.py -v
```

The test suite includes **260 tests** covering: config loading, service registry, vault operations, markdown helpers, watcher events/filtering/debounce, AI prompts/parsing/fallback, AST extraction, complexity scoring, dependency mapping, EventBus flows, doc generation, changelog diffing, template rendering, graph node/edge/persistence/analysis, memory chunking/embedding/store/search, Obsidian vault/index/writer/link-resolver/note-builder/engine, git monitor/summarizer/memory/engine, and intelligence pattern-detection/refactor-suggester/suggestion-store/engine.

---

## Troubleshooting

### Ollama connection fails on startup

```
AI engine could not start — is Ollama running at http://localhost:11434?
```

**Fix:** Make sure the Ollama server is running:

```bash
ollama serve
```

If Ollama is on a different host or port, update `ai.ollama_host` in your config or set:

```bash
export PROJECTMIND_AI__OLLAMA_HOST="http://<host>:<port>"
```

### Model not found / fallback error

**Fix:** Pull the required model:

```bash
ollama pull qwen2.5-coder:14b
```

To use a smaller model (e.g., on machines with limited VRAM), pull a smaller variant and update config:

```bash
ollama pull qwen2.5-coder:7b
```

```yaml
ai:
  default_model: "qwen2.5-coder:7b"
  fallback_model: "qwen2.5-coder:7b"
```

### Watcher says "disabled" and exits immediately

**Fix:** Enable the watcher in your config:

```yaml
watcher:
  enabled: true
```

Or via environment variable:

```bash
PROJECTMIND_WATCHER__ENABLED=true python main.py
```

### No files are being detected by the watcher

**Possible causes:**
- Your source code is not in one of the watched directories (`backend/`, `frontend/`, `src/`, `app/` by default). Update `watcher.watch_dirs` to match your project structure.
- The file extension is not in `watcher.watch_extensions`. Add your file types if needed.
- The file path matches an ignore pattern. Check `watcher.ignore_patterns`.

### ChromaDB or sentence-transformers errors

**Fix:** Make sure all runtime dependencies are installed:

```bash
pip install -r requirements.txt
```

The `sentence-transformers` package will download the `all-MiniLM-L6-v2` model on first use (~80 MB). Ensure you have an internet connection for the initial download.

### `[FATAL] ...` error on startup

A `ProjectMindError` during bootstrap means the configuration could not be loaded. Check:

- `config/config.yaml` exists and is valid YAML
- No syntax errors in your YAML overrides
- Environment variables use the correct `PROJECTMIND_` prefix and `__` separator

### Vault not appearing in Obsidian

**Fix:** The vault is written to the `vault/` directory (configurable via `paths.vault_dir`). Make sure at least the Obsidian module (M8) and one upstream module (Analysis + Docs) are enabled for notes to be generated.

### Python version error

ProjectMind requires **Python ≥ 3.12**. Check your version:

```bash
python3 --version
```

---

## License

TBD.
