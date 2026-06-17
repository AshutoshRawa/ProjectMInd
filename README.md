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
| 6 | Graph Engine | ✅ | Incremental dependency graph — orphans, hubs, cycles, hotspots |
| 7 | Memory Engine | ✅ | Semantic memory with ChromaDB — chunking, embedding, search |
| 8 | Obsidian Engine | ✅ | Vault writer — links, index, note builder, async queue |
| 9 | Git Integration | ✅ | Commit monitor, AI summariser, git memory store |
| 10 | Intelligence Engine | ✅ | Autonomous pattern detection, refactor suggestions, codebase Q&A |

---

## Quick Start

```bash
git clone <your-fork> ProjectMind && cd ProjectMind
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Copy and edit the example config (enable the modules you want)
cp config/config.example.yaml config/config.yaml

# Pull the required Ollama model
ollama pull qwen2.5-coder:14b

python main.py
```

Override any config via environment variables:

```bash
PROJECTMIND_LOGGING__LEVEL=DEBUG PROJECTMIND_WATCHER__ENABLED=true python main.py
```

Enable modules incrementally in `config/config.yaml`:

```yaml
watcher:    { enabled: true }
analysis:   { enabled: true }
docs:       { enabled: true }
graph:      { enabled: true }
memory:     { enabled: true }
obsidian:   { enabled: true }
git:        { enabled: true }
intelligence: { enabled: true }
```

---

## Architecture

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

**Rules:**
- All inter-module communication through `EventBus` only
- Every module imports only from another module's `__init__.py`
- All AI calls go through `get_ai().complete('prompt_name', variables)`

---

## EventBus Event Flow

```
watcher.file_change
    └─► M4: analysis.file_analyzed
            ├─► M5: docs.doc_updated
            │       └─► M8: obsidian.note_written
            ├─► M6: graph.graph_updated
            │       └─► M8: (graph links in notes)
            │       └─► M10: intelligence.suggestions_ready
            └─► M7: (memory chunks upserted)

git.commit
    └─► M9: git.commit_summarized
            └─► M7: (commit stored in memory)
```

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
  default_model: "qwen2.5-coder:14b"
  fallback_model: "qwen2.5-coder:14b"
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

Converts `FileAnalysis` results into structured markdown strings.  
**Boundary rule: produces strings only — never writes to the Obsidian vault** (that is Module 8's job).

### Files

```
docs/
├── frontmatter.py      # build_frontmatter(analysis) → YAML --- block
├── doc_generator.py    # generate(analysis, changelog_entries) → full markdown
├── changelog.py        # ChangelogEntry · diff_analyses() · format_changelog()
├── template_engine.py  # Jinja2 string-templates + render_doc_template()
└── doc_engine.py       # Module5DocEngine (EventBus service)
```

### Public API

| Symbol | Signature | Description |
|--------|-----------|-------------|
| `build_frontmatter` | `(analysis: FileAnalysis) -> str` | YAML `---` block: file, language, lines, complexity, last_analyzed, tags |
| `generate` | `(analysis, changelog_entries=None) -> str` | Full markdown: frontmatter + body sections |
| `diff_analyses` | `(old, new: FileAnalysis) -> list[ChangelogEntry]` | Detects changes between two analysis snapshots |
| `format_changelog` | `(entries, max=5) -> str` | Renders up to 5 changelog entries as a markdown bullet list |
| `render_doc_template` | `(template_name, context) -> str` | Renders a named Jinja2 template (stored as strings in-module) |
| `Module5DocEngine` | `(bus, ...) -> Service` | Long-lived EventBus service: start / stop |

### Document sections (in order)

```
# <filename>                     ← H1
> <ai_summary>                   ← blockquote

## Functions                     ← table: name | params | complexity | docstring?
## Anti-Patterns                 ← only rendered when list is non-empty
## Dependencies                  ← import list
## Changelog                     ← last 5 entries, most-recent first
```

### Changelog change types

| Constant | Trigger |
|----------|---------|
| `FUNCTION_ADDED` | New function appears in analysis |
| `FUNCTION_REMOVED` | Function deleted from analysis |
| `COMPLEXITY_CHANGED` | Weighted complexity score shifts |
| `IMPORTS_CHANGED` | Import list additions or removals |
| `AI_SUMMARY_CHANGED` | AI summary text differs |

### EventBus contract

| Direction | Event | Payload |
|-----------|-------|---------|
| Subscribe | `analysis.file_analyzed` | `{file_path, analysis}` |
| Publish | `docs.doc_updated` | `{path, markdown_content, frontmatter}` |

---

## Module 6 — Graph Engine

Builds and maintains an **incremental directed dependency graph** of the codebase.  
**Boundary rule: outputs graph data only — never writes to the Obsidian vault** (that is Module 8's job).

### Files

```
graph/
├── graph_builder.py    # GraphEngine — wraps networkx.DiGraph, incremental mutations
├── graph_state.py      # GraphStateManager · save_graph() · load_graph()
├── graph_analyzer.py   # find_orphans · find_hubs · find_circular_deps · complexity_hotspots
└── graph_engine.py     # Module6GraphEngine (EventBus service)
```

### Public API

#### `GraphEngine` — `graph/graph_builder.py`

| Method | Signature | Description |
|--------|-----------|-------------|
| `update_node` | `(analysis: FileAnalysis)` | Add or patch a file node (**incremental** — only touches that node) |
| `update_edges` | `(analysis: FileAnalysis) -> (added, removed)` | Sync import edges; returns lists of targets added/removed |
| `remove_node` | `(path: str)` | Remove a node and all its incident edges (safe on missing) |
| `get_neighbors` | `(path: str) -> list[str]` | Direct import successors of `path` |
| `get_related_files` | `(path: str, depth=2) -> list[str]` | BFS reachable files within `depth` hops |

#### `graph_analyzer.py` — pure, side-effect-free functions

| Function | Returns | Description |
|----------|---------|-------------|
| `find_orphans(graph)` | `list[str]` | Nodes with zero in-edges **and** zero out-edges |
| `find_hubs(graph, threshold=5)` | `list[str]` | Nodes imported by ≥ `threshold` others (high in-degree), sorted desc |
| `find_circular_deps(graph)` | `list[list[str]]` | All simple cycles via Johnson's algorithm |
| `complexity_hotspots(graph)` | `list[str]` | Nodes in top-quartile complexity **and** top-quartile in-degree |

### EventBus contract

| Direction | Event | Payload |
|-----------|-------|---------|
| Subscribe | `analysis.file_analyzed` | `{file_path, analysis}` |
| Publish | `graph.graph_updated` | `{updated_node, edges_added, edges_removed, stats}` |

### Persistence

Graph serialised to `graph_state.json` (networkx node-link format). Auto-save every **10 updates**; `stop()` forces a final save. Load failure starts a fresh empty graph — never crashes.

---

## Module 7 — Memory Engine

Semantic long-term memory backed by **ChromaDB** and `sentence-transformers`:

- **Chunker** — splits `FileAnalysis` into overlapping text chunks with rich metadata
- **Embedder** — `all-MiniLM-L6-v2` embeddings via `sentence-transformers`
- **MemoryStore** — ChromaDB collection wrapper with upsert, delete, and similarity search
- **MemoryUpdater** — EventBus service: subscribes to `analysis.file_analyzed`, upserts chunks
- **SemanticSearch** — `search(query, top_k)` returns ranked `MemoryChunk` results

```
memory/
├── chunker.py          # split FileAnalysis → list[MemoryChunk]
├── embedder.py         # Embedder — encode() + batch_encode()
├── memory_store.py     # MemoryStore — ChromaDB CRUD + search
├── memory_updater.py   # MemoryUpdater (EventBus service)
└── semantic_search.py  # SemanticSearch — query interface
```

### EventBus contract

| Direction | Event | Payload |
|-----------|-------|---------|
| Subscribe | `analysis.file_analyzed` | `{file_path, analysis}` |

```yaml
# config/config.yaml
memory:
  enabled: true
  chroma_db_path: ".chroma"
  embedding_model: "all-MiniLM-L6-v2"
  retention_days: 90
```

---

## Module 8 — Obsidian Engine

Writes analysis results as rich Obsidian-compatible markdown notes:

- **VaultWriter** — async write queue with `write`, `delete`, `mkdir` operations
- **VaultIndex** — in-memory index of all vault notes (stem → path lookups)
- **LinkResolver** — converts file paths to `[[wikilinks]]`, resolves duplicates with path disambiguation
- **NoteBuilder** — assembles the final note: frontmatter + doc body + graph links + semantic neighbours
- **ObsidianEngine** — EventBus service: subscribes to `docs.doc_updated` + `graph.graph_updated`

```
obsidian/
├── vault.py            # VaultManager — write_note / read_note / list_notes
├── vault_index.py      # VaultIndex — stem-based lookup, startup scan
├── vault_writer.py     # VaultWriter — async queue, atomic writes
├── link_resolver.py    # LinkResolver — path_to_wikilink / resolve_links
├── note_builder.py     # NoteBuilder — assemble final markdown
├── markdown.py         # markdown helpers
└── obsidian_engine.py  # Module8ObsidianEngine (EventBus service)
```

### EventBus contract

| Direction | Event | Payload |
|-----------|-------|---------|
| Subscribe | `docs.doc_updated` | `{path, markdown_content, frontmatter}` |
| Subscribe | `graph.graph_updated` | `{updated_node, edges_added, edges_removed, stats}` |
| Publish | `obsidian.note_written` | `{vault_path, source_path}` |

---

## Module 9 — Git Integration Engine

Monitors commits and stores AI-generated summaries in memory:

- **GitMonitor** — polls `git log` for new commits, publishes `git.commit` events
- **CommitSummarizer** — sends diff + metadata to AI, parses structured `CommitSummary`
- **GitMemory** — stores commit summaries in ChromaDB for semantic retrieval
- **GitEngine** — long-lived service wiring all of the above

```
git_integration/
├── git_types.py        # CommitInfo, CommitSummary dataclasses
├── git_monitor.py      # GitMonitor — poll + publish git.commit
├── commit_summarizer.py # CommitSummarizer — AI-based diff → summary
├── git_memory.py       # GitMemory — store/search commit summaries
└── git_engine.py       # GitEngine (EventBus service)
```

### EventBus contract

| Direction | Event | Payload |
|-----------|-------|---------|
| Publish | `git.commit` | `{commit: CommitInfo}` |
| Publish | `git.commit_summarized` | `{commit_hash, summary: CommitSummary}` |

```yaml
# config/config.yaml
git:
  enabled: true
  repo_path: "."
  poll_interval_seconds: 60.0
```

---

## Module 10 — Intelligence Engine

Autonomous analysis cycle that synthesises across all modules:

- **PatternDetector** — detects anti-patterns in the graph (high complexity, orphan files, hubs, cycles)
- **RefactorSuggester** — calls AI with pattern context → produces `Suggestion` with rationale
- **SuggestionStore** — persists suggestions to disk; deduplicates by pattern fingerprint
- **IntelligenceEngine** — runs on a 60-minute cycle + triggered by `graph.graph_updated`; also exposes `query_codebase()` for natural-language Q&A

```
intelligence/
├── intelligence_types.py  # Pattern, Suggestion dataclasses
├── pattern_detector.py    # detect_anti_patterns(graph, analyses)
├── refactor_suggester.py  # suggest(pattern, ai) → Suggestion
├── suggestion_store.py    # SuggestionStore — persist, deduplicate, query
└── intelligence_engine.py # IntelligenceEngine (EventBus service)
```

### EventBus contract

| Direction | Event | Payload |
|-----------|-------|---------|
| Subscribe | `graph.graph_updated` | triggers analysis cycle |
| Publish | `intelligence.suggestions_ready` | `{suggestions: list[Suggestion]}` |

```yaml
# config/config.yaml
intelligence:
  enabled: true
  cycle_interval_seconds: 3600
  min_severity: "medium"
  store_path: ".suggestions"
```

---

## Project Layout

```
ProjectMind/
├── core/               # M1 — config, logging, registry, bootstrap, EventBus
├── obsidian/           # M8 — vault manager + Obsidian note writer
├── watcher/            # M2 — filesystem monitoring
├── ai/                 # M3 — Ollama/Qwen AI client
├── analysis/           # M4 — code analysis engine
├── docs/               # M5 — documentation engine
├── graph/              # M6 — dependency graph engine
├── memory/             # M7 — ChromaDB semantic memory
├── git_integration/    # M9 — git commit monitor + summariser
├── intelligence/       # M10 — autonomous pattern detection + Q&A
├── config/             # YAML configuration files
├── templates/          # markdown note templates
├── vault/              # Obsidian knowledge store (gitignored)
├── logs/               # rotating logs (gitignored)
├── tests/              # pytest suite
├── main.py             # entry point
├── requirements.txt    # runtime deps
└── pyproject.toml      # project metadata + pytest config
```

---

## Testing

```bash
pip install -r requirements-dev.txt
python3 -m pytest -q
```

**259 tests** covering: config, registry, vault, markdown, watcher, AI prompts/parsing/fallback, AST extraction, complexity, dependency mapping, EventBus flows, doc generation, changelog diffing, template rendering, graph node/edge/persistence/analysis, memory chunking/embedding/store/search, Obsidian vault/index/writer/link-resolver/note-builder/engine, git monitor/summarizer/memory/engine, and intelligence pattern-detection/refactor-suggester/suggestion-store/engine.

---

## License

TBD.
