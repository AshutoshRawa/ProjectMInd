"""
tests/test_memory.py
====================
Module 7 — Semantic Memory Engine tests.

Validates:
1. Chunker — Python file produces correct chunk structure and stable IDs.
2. Chunker — non-Python sliding window produces overlapping chunks.
3. Embedder — singleton pattern, embed() returns float list of correct length.
4. Embedder — embed_batch() returns correct count and consistent vectors.
5. MemoryStore — upsert / get_existing_ids / delete_by_file round-trip.
6. MemoryStore — upsert is idempotent (same chunk twice → count unchanged).
7. MemoryUpdater — on_file_changed stores chunks and publishes memory.updated.
8. MemoryUpdater — on_file_deleted removes chunks and publishes memory.deleted.
9. MemoryUpdater — EventBus integration (analysis.file_analyzed → worker queue).
10. SemanticSearch — embed 10 real code chunks, verify ranking correctness.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from analysis.analysis_types import FileAnalysis, FunctionInfo
from core.event_bus import EventBus
from memory.chunker import Chunk, chunk_python_file, _make_id, _sliding_window_chunks
from memory.embedder import embed, embed_batch, MODEL_NAME
from memory.memory_store import MemoryStore
from memory.memory_updater import MemoryUpdater
from memory.semantic_search import SearchResult, search, search_by_file


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_analysis(
    path: str = "/proj/sample.py",
    language: str = "python",
    functions: list[FunctionInfo] | None = None,
    classes: list[str] | None = None,
    imports: list[str] | None = None,
    ai_summary: str = "Utility module.",
    anti_patterns: list[str] | None = None,
) -> FileAnalysis:
    return FileAnalysis(
        path=path,
        language=language,
        lines_of_code=50,
        functions=functions or [],
        classes=classes or [],
        imports=imports or ["os", "pathlib"],
        ai_summary=ai_summary,
        anti_patterns=anti_patterns or [],
        analyzed_at=time.time(),
    )


def _make_fn(name: str, *, line_start: int = 1, line_end: int = 10) -> FunctionInfo:
    return FunctionInfo(
        name=name,
        line_start=line_start,
        line_end=line_end,
        params=["self", "value"],
        complexity=3,
        has_docstring=True,
        calls=["print", "validate"],
    )


@pytest.fixture()
def tmp_store(tmp_path: Path) -> MemoryStore:
    """A fresh MemoryStore backed by a temporary directory."""
    return MemoryStore(chroma_db_path=tmp_path / "chroma")


@pytest.fixture()
def bus() -> EventBus:
    return EventBus()


# ---------------------------------------------------------------------------
# 1. Chunker — Python file structure
# ---------------------------------------------------------------------------

class TestChunkerPython:
    def test_produces_function_chunk_per_function(self) -> None:
        fn1 = _make_fn("process", line_start=5, line_end=15)
        fn2 = _make_fn("validate", line_start=17, line_end=25)
        analysis = _make_analysis(functions=[fn1, fn2], classes=["Service"])

        chunks = chunk_python_file(analysis)

        function_chunks = [c for c in chunks if c.chunk_type == "function"]
        assert len(function_chunks) == 2
        names = {c.metadata["name"] for c in function_chunks}
        assert names == {"process", "validate"}

    def test_produces_class_chunk_per_class(self) -> None:
        analysis = _make_analysis(classes=["Loader", "Parser"])
        chunks = chunk_python_file(analysis)

        class_chunks = [c for c in chunks if c.chunk_type == "class"]
        assert len(class_chunks) == 2
        names = {c.metadata["name"] for c in class_chunks}
        assert names == {"Loader", "Parser"}

    def test_always_produces_module_chunk(self) -> None:
        analysis = _make_analysis()  # no functions or classes
        chunks = chunk_python_file(analysis)

        module_chunks = [c for c in chunks if c.chunk_type == "module"]
        assert len(module_chunks) == 1

    def test_module_chunk_contains_imports_and_summary(self) -> None:
        analysis = _make_analysis(
            imports=["os", "json"],
            ai_summary="Handles JSON serialization.",
        )
        chunks = chunk_python_file(analysis)
        module = next(c for c in chunks if c.chunk_type == "module")

        assert "os" in module.content
        assert "json" in module.content
        assert "Handles JSON serialization." in module.content

    def test_function_chunk_metadata_fields(self) -> None:
        fn = _make_fn("do_work", line_start=10, line_end=20)
        analysis = _make_analysis(functions=[fn])
        chunks = chunk_python_file(analysis)

        fn_chunk = next(c for c in chunks if c.chunk_type == "function")
        meta = fn_chunk.metadata

        assert meta["name"] == "do_work"
        assert meta["line_start"] == 10
        assert meta["line_end"] == 20
        assert meta["complexity"] == 3
        assert meta["has_docstring"] is True
        assert meta["language"] == "python"

    def test_chunk_id_stability(self) -> None:
        """Same file + function name → same ID always."""
        fn = _make_fn("compute")
        a1 = _make_analysis(path="/proj/math.py", functions=[fn])
        a2 = _make_analysis(path="/proj/math.py", functions=[fn])

        ids1 = {c.id for c in chunk_python_file(a1)}
        ids2 = {c.id for c in chunk_python_file(a2)}
        assert ids1 == ids2

    def test_chunk_id_format(self) -> None:
        fn = _make_fn("run")
        analysis = _make_analysis(path="/project/runner.py", functions=[fn])
        chunks = chunk_python_file(analysis)

        fn_chunk = next(c for c in chunks if c.chunk_type == "function")
        assert fn_chunk.id == "/project/runner.py::function::run"

    def test_make_id_stable_formula(self) -> None:
        assert _make_id("/a/b.py", "function", "foo") == "/a/b.py::function::foo"
        assert _make_id("/a/b.py", "class", "MyClass") == "/a/b.py::class::MyClass"
        assert _make_id("/a/b.py", "module", "b") == "/a/b.py::module::b"


# ---------------------------------------------------------------------------
# 2. Chunker — sliding window (non-Python)
# ---------------------------------------------------------------------------

class TestChunkerSlidingWindow:
    def test_short_text_produces_single_chunk(self) -> None:
        result = _sliding_window_chunks("hello world this is a test", window=50, overlap=10)
        assert len(result) == 1

    def test_long_text_produces_multiple_chunks(self) -> None:
        words = ["word"] * 600
        text = " ".join(words)
        result = _sliding_window_chunks(text, window=100, overlap=20)
        assert len(result) > 1

    def test_overlap_means_words_appear_in_consecutive_chunks(self) -> None:
        words = [f"w{i}" for i in range(200)]
        text = " ".join(words)
        chunks = _sliding_window_chunks(text, window=50, overlap=10)
        assert len(chunks) >= 2

        last_of_first = set(chunks[0].split())
        first_of_second = set(chunks[1].split())
        assert len(last_of_first & first_of_second) > 0, "Expected overlap between consecutive chunks"

    def test_generic_file_produces_text_chunks(self) -> None:
        analysis = _make_analysis(
            path="/proj/readme.md",
            language="markdown",
            ai_summary="Describes the project architecture.",
        )
        chunks = chunk_python_file(analysis)
        assert all(c.chunk_type == "text" for c in chunks)
        assert len(chunks) >= 1
        assert all(c.metadata["language"] == "markdown" for c in chunks)


# ---------------------------------------------------------------------------
# 3 & 4. Embedder — singleton and output shape
# ---------------------------------------------------------------------------

class TestEmbedder:
    def test_reset_for_testing_clears_singleton(self, monkeypatch) -> None:
        import memory.embedder as embedder

        sentinel = object()
        monkeypatch.setattr(embedder, "_model", sentinel)

        embedder._reset_for_testing()

        assert embedder._model is None

    def test_embed_returns_list_of_floats(self) -> None:
        vec = embed("def hello(): pass")
        assert isinstance(vec, list)
        assert len(vec) > 0
        assert all(isinstance(v, float) for v in vec)

    def test_embed_dim_is_384(self) -> None:
        # all-MiniLM-L6-v2 has 384 dimensions.
        vec = embed("sample text")
        assert len(vec) == 384

    def test_embed_batch_empty(self) -> None:
        result = embed_batch([])
        assert result == []

    def test_embed_batch_count_matches_input(self) -> None:
        texts = ["alpha", "beta", "gamma"]
        vecs = embed_batch(texts)
        assert len(vecs) == 3
        for v in vecs:
            assert len(v) == 384

    def test_singleton_same_object(self) -> None:
        from memory.embedder import _get_model
        m1 = _get_model()
        m2 = _get_model()
        assert m1 is m2

    def test_same_text_produces_same_vector(self) -> None:
        v1 = embed("class Config: pass")
        v2 = embed("class Config: pass")
        assert v1 == v2

    def test_model_name_constant(self) -> None:
        assert MODEL_NAME == "all-MiniLM-L6-v2"


# ---------------------------------------------------------------------------
# 5 & 6. MemoryStore — upsert / get / delete / idempotency
# ---------------------------------------------------------------------------

class TestMemoryStore:
    def _make_chunk(self, cid: str = "fp::function::foo", content: str = "def foo(): pass") -> Chunk:
        return Chunk(
            id=cid,
            content=content,
            chunk_type="function",
            metadata={"file_path": "/proj/a.py", "language": "python"},
        )

    def test_upsert_increases_count(self, tmp_store: MemoryStore) -> None:
        chunk = self._make_chunk()
        tmp_store.upsert([chunk])
        assert tmp_store.count() == 1

    def test_get_existing_ids_returns_stored_ids(self, tmp_store: MemoryStore) -> None:
        c1 = self._make_chunk("/proj/a.py::function::foo", "def foo(): pass")
        c2 = self._make_chunk("/proj/a.py::function::bar", "def bar(): pass")
        tmp_store.upsert([c1, c2])

        ids = tmp_store.get_existing_ids("/proj/a.py")
        assert ids == {c1.id, c2.id}

    def test_delete_by_file_removes_chunks(self, tmp_store: MemoryStore) -> None:
        c1 = self._make_chunk("/proj/a.py::function::foo", "def foo(): pass")
        c1_meta = Chunk(id=c1.id, content=c1.content, chunk_type="function",
                        metadata={"file_path": "/proj/a.py", "language": "python"})
        c2 = Chunk(
            id="/proj/b.py::function::run",
            content="def run(): pass",
            chunk_type="function",
            metadata={"file_path": "/proj/b.py", "language": "python"},
        )
        tmp_store.upsert([c1_meta, c2])
        tmp_store.delete_by_file("/proj/a.py")

        remaining = tmp_store.get_existing_ids("/proj/a.py")
        assert remaining == set()
        # b.py should still be there.
        assert tmp_store.count() == 1

    def test_upsert_is_idempotent(self, tmp_store: MemoryStore) -> None:
        chunk = self._make_chunk()
        tmp_store.upsert([chunk])
        tmp_store.upsert([chunk])  # same id → replace, not duplicate
        assert tmp_store.count() == 1

    def test_upsert_empty_list_is_noop(self, tmp_store: MemoryStore) -> None:
        tmp_store.upsert([])
        assert tmp_store.count() == 0

    def test_get_existing_ids_empty_for_unknown_file(self, tmp_store: MemoryStore) -> None:
        ids = tmp_store.get_existing_ids("/nonexistent/file.py")
        assert ids == set()


# ---------------------------------------------------------------------------
# 7 & 8. MemoryUpdater — on_file_changed / on_file_deleted
# ---------------------------------------------------------------------------

class TestMemoryUpdater:
    def _updater(self, bus: EventBus, tmp_store: MemoryStore) -> MemoryUpdater:
        return MemoryUpdater(bus=bus, store=tmp_store)

    def test_on_file_changed_stores_chunks(
        self, bus: EventBus, tmp_store: MemoryStore
    ) -> None:
        updater = self._updater(bus, tmp_store)
        fn = _make_fn("process")
        analysis = _make_analysis(path="/proj/svc.py", functions=[fn], classes=["Service"])

        updater.on_file_changed(analysis)
        assert tmp_store.count() > 0

    def test_on_file_changed_publishes_memory_updated(
        self, bus: EventBus, tmp_store: MemoryStore
    ) -> None:
        events: list[dict] = []
        bus.subscribe("memory.updated", lambda p: events.append(p))

        updater = self._updater(bus, tmp_store)
        analysis = _make_analysis(path="/proj/svc.py", functions=[_make_fn("run")])
        updater.on_file_changed(analysis)

        assert len(events) == 1
        assert events[0]["file_path"] == "/proj/svc.py"
        assert events[0]["chunk_count"] > 0

    def test_on_file_changed_replaces_stale_chunks(
        self, bus: EventBus, tmp_store: MemoryStore
    ) -> None:
        updater = self._updater(bus, tmp_store)
        fp = "/proj/module.py"

        # First version: two functions.
        a1 = _make_analysis(path=fp, functions=[_make_fn("alpha"), _make_fn("beta")])
        updater.on_file_changed(a1)
        count_after_first = tmp_store.count()

        # Second version: only one function → stale chunk removed.
        a2 = _make_analysis(path=fp, functions=[_make_fn("alpha")])
        updater.on_file_changed(a2)
        count_after_second = tmp_store.count()

        assert count_after_second < count_after_first

    def test_on_file_deleted_removes_chunks(
        self, bus: EventBus, tmp_store: MemoryStore
    ) -> None:
        updater = self._updater(bus, tmp_store)
        analysis = _make_analysis(path="/proj/gone.py", functions=[_make_fn("do")])
        updater.on_file_changed(analysis)
        assert tmp_store.count() > 0

        updater.on_file_deleted("/proj/gone.py")
        assert tmp_store.count() == 0

    def test_on_file_deleted_publishes_memory_deleted(
        self, bus: EventBus, tmp_store: MemoryStore
    ) -> None:
        events: list[dict] = []
        bus.subscribe("memory.deleted", lambda p: events.append(p))

        updater = self._updater(bus, tmp_store)
        updater.on_file_deleted("/proj/orphan.py")

        assert len(events) == 1
        assert events[0]["file_path"] == "/proj/orphan.py"


# ---------------------------------------------------------------------------
# 9. MemoryUpdater — EventBus integration
# ---------------------------------------------------------------------------

class TestMemoryUpdaterEventBus:
    def _wait(self, condition_fn, *, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition_fn():
                return
            time.sleep(0.05)
        raise AssertionError("Timed out waiting for condition")

    def test_analysis_done_event_triggers_upsert(
        self, bus: EventBus, tmp_store: MemoryStore
    ) -> None:
        updater = MemoryUpdater(bus=bus, store=tmp_store)
        updater.start()
        try:
            fn = _make_fn("handler")
            analysis = _make_analysis(path="/proj/handler.py", functions=[fn])

            bus.publish(
                "analysis.file_analyzed",
                {
                    "file_path": "/proj/handler.py",
                    "analysis": analysis.to_dict(),
                    "analysis_error": None,
                    "change_kind": "modified",
                },
            )
            self._wait(lambda: tmp_store.count() > 0)
            assert tmp_store.count() > 0
        finally:
            updater.stop()

    def test_delete_event_triggers_removal(
        self, bus: EventBus, tmp_store: MemoryStore
    ) -> None:
        updater = MemoryUpdater(bus=bus, store=tmp_store)
        updater.start()
        try:
            # First store a chunk.
            analysis = _make_analysis(path="/proj/old.py", functions=[_make_fn("run")])
            updater.on_file_changed(analysis)
            assert tmp_store.count() > 0

            # Publish delete event.
            deleted: list[dict] = []
            bus.subscribe("memory.deleted", lambda p: deleted.append(p))
            bus.publish(
                "analysis.file_analyzed",
                {
                    "file_path": "/proj/old.py",
                    "analysis": None,
                    "analysis_error": "deleted",
                    "change_kind": "deleted",
                },
            )
            self._wait(lambda: tmp_store.count() == 0)
            assert tmp_store.count() == 0
        finally:
            updater.stop()


# ---------------------------------------------------------------------------
# 10. SemanticSearch — 10 real code chunks, verify search ranking
# ---------------------------------------------------------------------------

class TestSemanticSearch:
    """
    Embed 10 real code-like chunks into a temp store and verify that
    semantic search returns sensible ranked results.
    """

    _CODE_CHUNKS = [
        # authentication-related
        ("auth.py::function::login",       "def login(username, password): verify credentials and return JWT token"),
        ("auth.py::function::logout",      "def logout(session_id): invalidate session and revoke JWT token"),
        ("auth.py::function::register",    "def register(email, password): create new user account with hashed password"),
        # database-related
        ("db.py::function::connect",       "def connect(host, port, db_name): open database connection pool with retry logic"),
        ("db.py::function::query",         "def query(sql, params): execute parameterised SQL statement and return rows"),
        ("db.py::function::close",         "def close(): gracefully close all database connections in the pool"),
        # HTTP / API related
        ("api.py::function::get_user",     "def get_user(user_id): fetch user record from database by primary key"),
        ("api.py::function::update_user",  "def update_user(user_id, data): validate and persist user profile changes"),
        # utility
        ("utils.py::function::hash_pw",    "def hash_password(plain): bcrypt hash a plaintext password string"),
        ("utils.py::function::parse_date", "def parse_date(date_str): parse ISO 8601 date string to datetime object"),
    ]

    def _populate(self, store: MemoryStore) -> None:
        chunks = [
            Chunk(
                id=cid,
                content=content,
                chunk_type="function",
                metadata={"file_path": cid.split("::")[0], "language": "python"},
            )
            for cid, content in self._CODE_CHUNKS
        ]
        store.upsert(chunks)

    def test_search_returns_results(self, tmp_store: MemoryStore) -> None:
        self._populate(tmp_store)
        results = search("user authentication and login", store=tmp_store, top_k=3)
        assert len(results) >= 1

    def test_search_results_are_search_result_instances(self, tmp_store: MemoryStore) -> None:
        self._populate(tmp_store)
        results = search("database query", store=tmp_store, top_k=3)
        for r in results:
            assert isinstance(r, SearchResult)

    def test_search_scores_are_in_unit_interval(self, tmp_store: MemoryStore) -> None:
        self._populate(tmp_store)
        results = search("connect to postgres", store=tmp_store, top_k=5)
        for r in results:
            assert 0.0 <= r.score <= 1.0, f"Score out of range: {r.score}"

    def test_search_is_ranked_by_score_descending(self, tmp_store: MemoryStore) -> None:
        self._populate(tmp_store)
        results = search("login password authentication", store=tmp_store, top_k=5)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_login_ranks_auth_chunks_first(self, tmp_store: MemoryStore) -> None:
        self._populate(tmp_store)
        results = search("user login with password JWT token", store=tmp_store, top_k=3)
        top_ids = {r.chunk_id for r in results[:2]}
        auth_ids = {"auth.py::function::login", "auth.py::function::logout",
                    "auth.py::function::register", "utils.py::function::hash_pw"}
        assert top_ids & auth_ids, (
            f"Expected auth-related chunks in top-2, got: {top_ids}"
        )

    def test_search_database_query_ranks_db_chunks_first(self, tmp_store: MemoryStore) -> None:
        self._populate(tmp_store)
        results = search("SQL query execute database rows", store=tmp_store, top_k=3)
        top_ids = {r.chunk_id for r in results[:2]}
        db_ids = {"db.py::function::connect", "db.py::function::query", "db.py::function::close"}
        assert top_ids & db_ids, (
            f"Expected db-related chunks in top-2, got: {top_ids}"
        )

    def test_search_language_filter(self, tmp_store: MemoryStore) -> None:
        """filter_language restricts results to matching metadata."""
        self._populate(tmp_store)
        results = search("user data", store=tmp_store, top_k=5, filter_language="python")
        for r in results:
            assert r.metadata.get("language") == "python"

    def test_search_by_file_excludes_source_file(self, tmp_store: MemoryStore) -> None:
        self._populate(tmp_store)
        results = search_by_file("auth.py", store=tmp_store, top_k=5)
        file_paths = {r.file_path for r in results}
        assert "auth.py" not in file_paths

    def test_search_empty_query_returns_empty(self, tmp_store: MemoryStore) -> None:
        self._populate(tmp_store)
        results = search("   ", store=tmp_store, top_k=5)
        assert results == []

    def test_all_ten_chunks_indexed(self, tmp_store: MemoryStore) -> None:
        self._populate(tmp_store)
        assert tmp_store.count() == 10
