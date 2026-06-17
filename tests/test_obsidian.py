"""
tests/test_obsidian.py
======================
Module 8 — Obsidian Integration Engine tests.

Coverage
--------
1.  WriteTask — priority ordering, timestamp tiebreaking (FIFO).
2.  WriteQueue — enqueue / dequeue order respects priority.
3.  WriteQueue — write executes atomically, file appears on disk.
4.  WriteQueue — retries on PermissionError (up to 3 attempts).
5.  WriteQueue — write_log.json is written for every completed task.
6.  WriteQueue — delete operation removes the target file.
7.  WriteQueue — mkdir operation creates the directory.
8.  WriteQueue — stop(drain=True) flushes pending tasks before exit.
9.  WriteQueue — stop(drain=False) discards pending tasks.
10. link_resolver — path_to_wikilink shortest-path format.
11. link_resolver — resolve_links disambiguates duplicate stems.
12. note_builder — build_note preserves frontmatter verbatim.
13. note_builder — build_note appends ## Related Files section.
14. note_builder — build_note appends ## Semantic Neighbors with score%.
15. note_builder — build_note with no graph_links omits that section.
16. note_builder — build_note with no related_chunks omits neighbors.
17. VaultIndex   — startup scan finds existing .md files.
18. VaultIndex   — update("write") adds entry; exists() returns True.
19. VaultIndex   — update("delete") removes entry; exists() returns False.
20. VaultIndex   — find_note via source_file_path mapping.
21. VaultIndex   — find_note via stem fallback.
22. VaultIndex   — non-md paths ignored by update().
23. ObsidianEngine — doc_updated event triggers note write on disk.
24. ObsidianEngine — note_written event is published after write.
25. ObsidianEngine — graph_updated event populates graph edge cache.
"""

from __future__ import annotations

import json
import time
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.event_bus import EventBus
from obsidian.link_resolver import path_to_wikilink, resolve_links
from obsidian.note_builder import build_note
from obsidian.obsidian_engine import ObsidianEngine
from obsidian.vault_index import VaultIndex
from obsidian.vault_writer import Priority, WriteQueue, WriteTask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait(condition_fn, *, timeout: float = 5.0, interval: float = 0.05) -> None:
    """Poll *condition_fn* until True or timeout, then assert."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition_fn():
            return
        time.sleep(interval)
    raise AssertionError(f"Timed out after {timeout}s waiting for condition")


def _make_search_result(file_path: str = "/proj/a.py", score: float = 0.87):
    """Build a minimal SearchResult-like object without importing memory."""
    result = MagicMock()
    result.file_path = file_path
    result.score = score
    result.chunk_id = f"{file_path}::function::foo"
    result.content = "def foo(): pass"
    result.metadata = {"language": "python"}
    return result


# ---------------------------------------------------------------------------
# 1–2. WriteTask — priority ordering
# ---------------------------------------------------------------------------

class TestWriteTaskOrdering:
    def test_lower_priority_int_sorts_first(self) -> None:
        high = WriteTask(path="/a.md", priority=Priority.HIGH, content="h")
        low  = WriteTask(path="/b.md", priority=Priority.LOW,  content="l")
        # high < low because 0 < 20
        assert high < low

    def test_same_priority_fifo_by_timestamp(self) -> None:
        t1 = WriteTask(path="/a.md", priority=Priority.NORMAL, content="a")
        time.sleep(0.01)  # ensure distinct timestamps
        t2 = WriteTask(path="/b.md", priority=Priority.NORMAL, content="b")
        assert t1 < t2

    def test_heap_pops_highest_priority_first(self) -> None:
        import heapq
        heap: list[WriteTask] = []
        heapq.heappush(heap, WriteTask(path="/low.md",  priority=Priority.LOW,    content="l"))
        heapq.heappush(heap, WriteTask(path="/high.md", priority=Priority.HIGH,   content="h"))
        heapq.heappush(heap, WriteTask(path="/norm.md", priority=Priority.NORMAL, content="n"))

        order = [heapq.heappop(heap).priority for _ in range(3)]
        assert order == [Priority.HIGH, Priority.NORMAL, Priority.LOW]


# ---------------------------------------------------------------------------
# 3. WriteQueue — file written to disk
# ---------------------------------------------------------------------------

class TestWriteQueueWrite:
    def test_write_creates_file(self, tmp_path: Path) -> None:
        wq = WriteQueue(vault_root=tmp_path)
        wq.start()
        try:
            target = tmp_path / "note.md"
            task = WriteTask(path=str(target), content="# Hello\n", operation="write")
            wq.enqueue(task)
            _wait(lambda: target.exists())
            assert target.read_text() == "# Hello\n"
        finally:
            wq.stop()

    def test_write_creates_parent_directories(self, tmp_path: Path) -> None:
        wq = WriteQueue(vault_root=tmp_path)
        wq.start()
        try:
            target = tmp_path / "deep" / "nested" / "note.md"
            task = WriteTask(path=str(target), content="deep note", operation="write")
            wq.enqueue(task)
            _wait(lambda: target.exists())
            assert target.read_text() == "deep note"
        finally:
            wq.stop()


# ---------------------------------------------------------------------------
# 4. WriteQueue — PermissionError retry behavior
# ---------------------------------------------------------------------------

class TestWriteQueueRetry:
    def test_retries_up_to_3_times_on_permission_error(self, tmp_path: Path) -> None:
        wq = WriteQueue(vault_root=tmp_path)

        call_counts: list[int] = [0]
        original_do = wq._do_operation

        def flaky_do(task: WriteTask) -> None:
            call_counts[0] += 1
            if call_counts[0] < 3:
                raise PermissionError("locked")
            original_do(task)

        wq._do_operation = flaky_do  # type: ignore[method-assign]
        wq.start()
        try:
            target = tmp_path / "retry.md"
            task = WriteTask(path=str(target), content="retry content", operation="write")
            wq.enqueue(task)
            _wait(lambda: call_counts[0] >= 3, timeout=5.0)
            # After 3 calls (2 failures + 1 success) the file should exist.
            _wait(lambda: target.exists(), timeout=3.0)
        finally:
            wq.stop()

        assert call_counts[0] == 3

    def test_permanent_permission_error_gives_up_after_3_attempts(self, tmp_path: Path) -> None:
        wq = WriteQueue(vault_root=tmp_path)
        call_counts: list[int] = [0]

        def always_fail(task: WriteTask) -> None:
            call_counts[0] += 1
            raise PermissionError("always locked")

        wq._do_operation = always_fail  # type: ignore[method-assign]
        wq.start()
        try:
            task = WriteTask(path=str(tmp_path / "fail.md"), content="x", operation="write")
            wq.enqueue(task)
            # Wait for all 3 attempts + backoff (200ms × 2 = 400ms) + margin.
            _wait(lambda: call_counts[0] >= 3, timeout=5.0)
        finally:
            wq.stop()

        assert call_counts[0] == 3


# ---------------------------------------------------------------------------
# 5. WriteQueue — write_log.json
# ---------------------------------------------------------------------------

class TestWriteQueueLog:
    def test_successful_write_appends_log_entry(self, tmp_path: Path) -> None:
        wq = WriteQueue(vault_root=tmp_path)
        wq.start()
        try:
            target = tmp_path / "logged.md"
            task = WriteTask(path=str(target), content="content", operation="write")
            wq.enqueue(task)
            _wait(lambda: (tmp_path / "write_log.json").exists())
        finally:
            wq.stop()

        log_path = tmp_path / "write_log.json"
        entries = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
        assert len(entries) >= 1
        entry = entries[-1]
        assert entry["path"] == str(target)
        assert entry["operation"] == "write"
        assert entry["success"] is True
        assert "ms" in entry

    def test_failed_write_logs_error_field(self, tmp_path: Path) -> None:
        wq = WriteQueue(vault_root=tmp_path)

        def always_fail(task: WriteTask) -> None:
            raise PermissionError("locked")

        wq._do_operation = always_fail  # type: ignore[method-assign]
        wq.start()
        try:
            task = WriteTask(path=str(tmp_path / "fail.md"), content="x", operation="write")
            wq.enqueue(task)
            _wait(lambda: (tmp_path / "write_log.json").exists(), timeout=5.0)
            # Wait for retry cycle to complete.
            time.sleep(0.8)
        finally:
            wq.stop()

        log_path = tmp_path / "write_log.json"
        entries = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
        failed = [e for e in entries if not e["success"]]
        assert failed, "Expected at least one failed log entry"
        assert "error" in failed[-1]


# ---------------------------------------------------------------------------
# 6–7. WriteQueue — delete and mkdir operations
# ---------------------------------------------------------------------------

class TestWriteQueueOperations:
    def test_delete_removes_file(self, tmp_path: Path) -> None:
        target = tmp_path / "to_delete.md"
        target.write_text("bye")

        wq = WriteQueue(vault_root=tmp_path)
        wq.start()
        try:
            task = WriteTask(path=str(target), operation="delete")
            wq.enqueue(task)
            _wait(lambda: not target.exists())
        finally:
            wq.stop()

    def test_mkdir_creates_directory(self, tmp_path: Path) -> None:
        new_dir = tmp_path / "new_section"
        wq = WriteQueue(vault_root=tmp_path)
        wq.start()
        try:
            task = WriteTask(path=str(new_dir), operation="mkdir")
            wq.enqueue(task)
            _wait(lambda: new_dir.is_dir())
        finally:
            wq.stop()


# ---------------------------------------------------------------------------
# 8–9. WriteQueue — drain / no-drain stop
# ---------------------------------------------------------------------------

class TestWriteQueueStop:
    def test_stop_drain_true_flushes_queue(self, tmp_path: Path) -> None:
        wq = WriteQueue(vault_root=tmp_path)
        wq.start()

        targets = [tmp_path / f"note_{i}.md" for i in range(5)]
        for t in targets:
            wq.enqueue(WriteTask(path=str(t), content=f"# {t.name}", operation="write"))

        wq.stop(drain=True, timeout=10.0)

        # All files should exist after drain.
        assert all(t.exists() for t in targets)

    def test_stop_drain_false_may_discard_tasks(self, tmp_path: Path) -> None:
        """
        With drain=False the queue is cleared before the worker exits.
        We can't guarantee zero files (some may have already been written),
        but the stop should return quickly without hanging.
        """
        wq = WriteQueue(vault_root=tmp_path)
        wq.start()

        # Enqueue many heavy tasks without letting the worker pick them up.
        # We do this by pausing the worker briefly via a lock.
        lock = threading.Event()

        original_do = wq._do_operation

        def slow_do(task: WriteTask) -> None:
            lock.wait(timeout=1.0)
            original_do(task)

        wq._do_operation = slow_do  # type: ignore[method-assign]

        for i in range(20):
            wq.enqueue(WriteTask(path=str(tmp_path / f"n{i}.md"), content="x", operation="write"))

        # Stop immediately without draining.
        lock.set()
        t0 = time.monotonic()
        wq.stop(drain=False, timeout=3.0)
        elapsed = time.monotonic() - t0

        # Should complete well within timeout.
        assert elapsed < 4.0


# ---------------------------------------------------------------------------
# 10–11. link_resolver
# ---------------------------------------------------------------------------

class TestLinkResolver:
    def test_path_to_wikilink_inside_vault(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        note = vault / "Architecture" / "config.md"
        result = path_to_wikilink(str(note), str(vault))
        assert result == "[[config]]"

    def test_path_to_wikilink_outside_vault(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        source = tmp_path / "src" / "core" / "config.py"
        result = path_to_wikilink(str(source), str(vault))
        assert result == "[[config]]"

    def test_resolve_links_unique_stems(self, tmp_path: Path) -> None:
        vault = str(tmp_path / "vault")
        paths = ["/vault/A/alpha.md", "/vault/B/beta.md"]
        result = resolve_links(paths, vault_root=vault)
        assert result == ["[[alpha]]", "[[beta]]"]

    def test_resolve_links_duplicate_stems_disambiguated(self, tmp_path: Path) -> None:
        vault = str(tmp_path / "vault")
        paths = [
            str(tmp_path / "vault" / "A" / "utils.md"),
            str(tmp_path / "vault" / "B" / "utils.md"),
        ]
        result = resolve_links(paths, vault_root=vault)
        # Both should contain "utils" but be distinct.
        assert result[0] != result[1]
        assert all("utils" in r for r in result)

    def test_resolve_links_empty_list(self) -> None:
        assert resolve_links([], vault_root="/vault") == []


# ---------------------------------------------------------------------------
# 12–16. note_builder
# ---------------------------------------------------------------------------

class TestNoteBuilder:
    _DOC = "---\ntitle: config\nauthor: ProjectMind\n---\n\n# config\n\nDoes things.\n"

    def test_preserves_frontmatter_verbatim(self) -> None:
        note = build_note(self._DOC, [], [])
        assert note.startswith("---\ntitle: config\nauthor: ProjectMind\n---")

    def test_appends_related_files_section(self) -> None:
        note = build_note(self._DOC, ["/vault/A/utils.md"], [], vault_root="/vault")
        assert "## Related Files" in note
        assert "[[utils]]" in note

    def test_appends_semantic_neighbors_section(self) -> None:
        sr = _make_search_result(file_path="/proj/database.py", score=0.91)
        note = build_note(self._DOC, [], [sr])
        assert "## Semantic Neighbors" in note
        assert "[[database]]" in note
        assert "91%" in note

    def test_no_graph_links_omits_related_section(self) -> None:
        note = build_note(self._DOC, [], [])
        assert "## Related Files" not in note

    def test_no_search_results_omits_neighbors_section(self) -> None:
        note = build_note(self._DOC, [], [])
        assert "## Semantic Neighbors" not in note

    def test_top_3_neighbors_limit(self) -> None:
        results = [_make_search_result(f"/proj/f{i}.py", 0.9 - i * 0.1) for i in range(6)]
        note = build_note(self._DOC, [], results)
        # Only 3 neighbors should appear (f0, f1, f2).
        assert note.count("[[f") == 3

    def test_related_files_multiple_links(self) -> None:
        note = build_note(self._DOC, ["/v/A.md", "/v/B.md", "/v/C.md"], [], vault_root="/v")
        for name in ["[[A]]", "[[B]]", "[[C]]"]:
            assert name in note

    def test_note_ends_with_newline(self) -> None:
        note = build_note(self._DOC, [], [])
        assert note.endswith("\n")


# ---------------------------------------------------------------------------
# 17–22. VaultIndex
# ---------------------------------------------------------------------------

class TestVaultIndex:
    def test_startup_scan_finds_existing_notes(self, tmp_path: Path) -> None:
        (tmp_path / "notes").mkdir()
        (tmp_path / "notes" / "config.md").write_text("# config")
        (tmp_path / "notes" / "vault.md").write_text("# vault")

        idx = VaultIndex(vault_root=tmp_path)
        assert idx.note_count() == 2

    def test_update_write_adds_entry(self, tmp_path: Path) -> None:
        idx = VaultIndex(vault_root=tmp_path)
        note = tmp_path / "new_note.md"
        note.write_text("# New")
        idx.update(note, "write")
        assert idx.exists(str(note))

    def test_update_delete_removes_entry(self, tmp_path: Path) -> None:
        note = tmp_path / "gone.md"
        note.write_text("bye")
        idx = VaultIndex(vault_root=tmp_path)
        assert idx.exists(str(note))

        note.unlink()
        idx.update(note, "delete")
        assert not idx.exists(str(note))

    def test_find_note_via_source_path(self, tmp_path: Path) -> None:
        idx = VaultIndex(vault_root=tmp_path)
        note = tmp_path / "Generated" / "config.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text("# config")
        idx.update(note, "write", source_file_path="/src/core/config.py")

        found = idx.find_note("/src/core/config.py")
        assert found == str(note)

    def test_find_note_via_stem_fallback(self, tmp_path: Path) -> None:
        note = tmp_path / "utils.md"
        note.write_text("# utils")
        idx = VaultIndex(vault_root=tmp_path)

        found = idx.find_note("/any/path/to/utils.py")
        assert found is not None
        assert "utils.md" in found

    def test_non_md_update_is_ignored(self, tmp_path: Path) -> None:
        idx = VaultIndex(vault_root=tmp_path)
        before = idx.note_count()
        idx.update(tmp_path / "image.png", "write")
        assert idx.note_count() == before

    def test_exists_false_for_missing_entry(self, tmp_path: Path) -> None:
        idx = VaultIndex(vault_root=tmp_path)
        assert not idx.exists("/no/such/file.md")


# ---------------------------------------------------------------------------
# 23–25. ObsidianEngine — event-driven integration
# ---------------------------------------------------------------------------

class TestObsidianEngine:
    @pytest.fixture()
    def vault(self, tmp_path: Path) -> Path:
        v = tmp_path / "vault"
        (v / "Generated").mkdir(parents=True)
        return v

    @pytest.fixture()
    def bus(self) -> EventBus:
        return EventBus()

    def _start_engine(self, bus: EventBus, vault: Path) -> ObsidianEngine:
        engine = ObsidianEngine(bus=bus, vault_root=vault, memory_store=None)
        engine.start()
        return engine

    def test_doc_updated_event_writes_note(self, bus: EventBus, vault: Path) -> None:
        engine = self._start_engine(bus, vault)
        try:
            bus.publish("docs.doc_updated", {
                "path": "/src/core/config.py",
                "markdown_content": "# config\n\nCore configuration module.\n",
                "frontmatter": "---\ntitle: config\n---",
            })
            _wait(lambda: any((vault / "Generated").glob("*.md")))
            notes = list((vault / "Generated").glob("*.md"))
            assert len(notes) == 1
            content = notes[0].read_text()
            assert "config" in content
        finally:
            engine.stop()

    def test_note_written_event_published(self, bus: EventBus, vault: Path) -> None:
        events: list[dict] = []
        bus.subscribe("obsidian.note_written", lambda p: events.append(p))

        engine = self._start_engine(bus, vault)
        try:
            bus.publish("docs.doc_updated", {
                "path": "/src/utils.py",
                "markdown_content": "# utils\n\nHelper functions.\n",
                "frontmatter": "",
            })
            _wait(lambda: len(events) > 0)
            assert events[0]["source_path"] == "/src/utils.py"
            assert "note_path" in events[0]
        finally:
            engine.stop()

    def test_graph_updated_caches_edges(self, bus: EventBus, vault: Path) -> None:
        engine = self._start_engine(bus, vault)
        try:
            bus.publish("graph.graph_updated", {
                "updated_node": "/src/api.py",
                "edges_added": ["/src/db.py", "/src/auth.py"],
                "edges_removed": [],
                "stats": {"node_count": 3, "edge_count": 2, "orphan_count": 0},
            })
            time.sleep(0.2)  # let worker process event
            assert "/src/db.py" in engine._graph_edges.get("/src/api.py", [])
            assert "/src/auth.py" in engine._graph_edges.get("/src/api.py", [])
        finally:
            engine.stop()

    def test_graph_links_appear_in_note(self, bus: EventBus, vault: Path) -> None:
        events: list[dict] = []
        bus.subscribe("obsidian.note_written", lambda p: events.append(p))

        engine = self._start_engine(bus, vault)
        try:
            # First publish graph edges for the file.
            bus.publish("graph.graph_updated", {
                "updated_node": "/src/app.py",
                "edges_added": ["/src/config.py"],
                "edges_removed": [],
                "stats": {},
            })
            time.sleep(0.15)

            # Then publish the doc event.
            bus.publish("docs.doc_updated", {
                "path": "/src/app.py",
                "markdown_content": "# app\n\nMain application.\n",
                "frontmatter": "",
            })
            _wait(lambda: len(events) > 0)

            note_path = Path(events[0]["note_path"])
            _wait(lambda: note_path.exists())
            content = note_path.read_text()
            assert "## Related Files" in content
            assert "[[config]]" in content
        finally:
            engine.stop()
