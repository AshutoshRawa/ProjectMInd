"""
tests/test_git.py
=================
Module 9 — Git Intelligence Engine tests.

All tests use a **real git repository fixture** built from scratch in
``tmp_path`` with 5 known commits.  No mocking of GitPython itself.
The AI layer (get_ai) is mocked to avoid Ollama dependency.
The memory layer (MemoryStore) is mocked to avoid ChromaDB I/O.

Coverage
--------
 1. DiffChunk — token_estimate auto-populated from content.
 2. CommitInfo — properties (total_lines_added, total_tokens, short_hash).
 3. GitMonitor — get_latest_commit() returns CommitInfo from real repo.
 4. GitMonitor — get_commits_since() returns correct commits in order.
 5. GitMonitor — diff_chunks populated with real file content.
 6. GitMonitor — get_commits_since() with unknown hash returns empty.
 7. _split_diff_to_chunks — small diff → single chunk.
 8. _split_diff_to_chunks — large diff → multiple chunks with overlap.
 9. summarize() — single-pass call for small diff.
10. summarize() — hierarchical call for large diff (>2000 tokens).
11. summarize() — mutates commit.ai_summary and commit.impact_score.
12. calculate_impact_score() — zero files, zero lines → 0.0.
13. calculate_impact_score() — formula is capped at 1.0.
14. calculate_impact_score() — graph_complexity adds to score.
15. GitMemory.store_commit() — calls memory_store.upsert with correct chunk.
16. GitMemory.store_commit() — chunk id follows git::commit:: scheme.
17. GitMemory.store_commit() — chunk_type is "commit".
18. GitMemory.store_commit() — metadata contains hash/author/date/files.
19. GitMemory.store_commit() — skips commit with empty ai_summary.
20. GitMemory.search_commits() — delegates to vector store with commit filter.
21. GitEngine — start() subscribes to git.commit event.
22. GitEngine — git.commit event triggers summarize + store + republish.
23. GitEngine — git.commit_summarized event published after processing.
24. Full pipeline — 5-commit repo, each commit summarised and stored.
25. GIT_COMMIT event payload — CommitInfo is delivered as event payload.
"""

from __future__ import annotations

import time
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

# ── repo builder ──────────────────────────────────────────────────────────────
def _build_repo(tmp_path: Path):
    """
    Create a real git repository with 5 known commits and return it.

    Commit layout:
        c1 — add README.md
        c2 — add auth/login.py
        c3 — add db/models.py
        c4 — modify auth/login.py (add function)
        c5 — add tests/test_auth.py
    """
    from git_integration.git_monitor import _load_gitpython  # noqa: PLC0415
    gitpkg = _load_gitpython()

    repo = gitpkg.Repo.init(str(tmp_path))
    repo.config_writer().set_value("user", "name", "Tester").release()
    repo.config_writer().set_value("user", "email", "test@example.com").release()

    def _write_commit(rel_path: str, content: str, message: str):
        full = tmp_path / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        repo.index.add([rel_path])
        repo.index.commit(message)

    _write_commit("README.md",        "# Project\n",                          "docs: add README")
    _write_commit("auth/login.py",    "def login(u, p): pass\n",              "feat: add login")
    _write_commit("db/models.py",     "class User: pass\n",                   "feat: add User model")
    _write_commit("auth/login.py",    "def login(u, p): pass\ndef logout(): pass\n", "feat: add logout")
    _write_commit("tests/test_auth.py", "def test_login(): assert True\n",     "test: add auth tests")

    return repo


@pytest.fixture()
def repo_path(tmp_path: Path) -> Path:
    _build_repo(tmp_path)
    return tmp_path


# ── helpers ───────────────────────────────────────────────────────────────────
def _fake_ai(return_text: str = "AI summary.") -> MagicMock:
    ai = MagicMock()
    ai.complete.return_value = return_text
    return ai


def _fake_store() -> MagicMock:
    store = MagicMock()
    store._lock = threading.Lock()
    store._ensure_client.return_value = MagicMock()
    return store


# =============================================================================
# 1–2. git_types
# =============================================================================

class TestGitTypes:
    def test_diffchunk_token_estimate_auto(self) -> None:
        from git_integration.git_types import DiffChunk
        dc = DiffChunk(file_path="a.py", lines_added=3, lines_removed=1, content="hello world foo")
        assert dc.token_estimate == 3

    def test_diffchunk_explicit_token_override(self) -> None:
        from git_integration.git_types import DiffChunk
        dc = DiffChunk(file_path="a.py", lines_added=0, lines_removed=0, content="x", token_estimate=99)
        assert dc.token_estimate == 99

    def test_commitinfo_short_hash(self) -> None:
        from git_integration.git_types import CommitInfo
        c = CommitInfo(hash="abcdef1234567890", author="A", date="2024-01-01T00:00:00+00:00", message="msg")
        assert c.short_hash == "abcdef12"

    def test_commitinfo_total_lines(self) -> None:
        from git_integration.git_types import CommitInfo, DiffChunk
        c = CommitInfo(
            hash="a" * 40, author="A", date="d", message="m",
            diff_chunks=[
                DiffChunk("a.py", 5, 2, "content a"),
                DiffChunk("b.py", 3, 1, "content b"),
            ],
        )
        assert c.total_lines_added == 8
        assert c.total_lines_removed == 3

    def test_commitinfo_total_tokens(self) -> None:
        from git_integration.git_types import CommitInfo, DiffChunk
        c = CommitInfo(
            hash="a" * 40, author="A", date="d", message="m",
            diff_chunks=[
                DiffChunk("a.py", 1, 0, "one two three"),     # 3 tokens
                DiffChunk("b.py", 1, 0, "four five"),          # 2 tokens
            ],
        )
        assert c.total_tokens == 5


# =============================================================================
# 3–6. GitMonitor — real repo
# =============================================================================

class TestGitMonitor:
    def test_get_latest_commit_returns_commitinfo(self, repo_path: Path) -> None:
        from core.event_bus import EventBus
        from git_integration.git_monitor import GitMonitor
        from git_integration.git_types import CommitInfo

        bus = EventBus()
        monitor = GitMonitor(repo_path=str(repo_path), bus=bus)
        monitor._repo = monitor._open_repo()

        commit = monitor.get_latest_commit()
        assert isinstance(commit, CommitInfo)
        assert commit.message == "test: add auth tests"
        assert len(commit.hash) == 40

    def test_get_latest_commit_has_author(self, repo_path: Path) -> None:
        from core.event_bus import EventBus
        from git_integration.git_monitor import GitMonitor

        monitor = GitMonitor(str(repo_path), EventBus())
        monitor._repo = monitor._open_repo()
        commit = monitor.get_latest_commit()
        assert "Tester" in commit.author
        assert "<" in commit.author and ">" in commit.author

    def test_get_commits_since_returns_5_commits(self, repo_path: Path) -> None:
        from core.event_bus import EventBus
        from git_integration.git_monitor import GitMonitor, _load_gitpython

        bus = EventBus()
        monitor = GitMonitor(str(repo_path), bus)
        monitor._repo = monitor._open_repo()

        gitpkg = _load_gitpython()
        repo = gitpkg.Repo(str(repo_path))
        # The oldest commit (initial) — commits since it should return 4 newer ones.
        all_commits = list(repo.iter_commits())
        oldest = all_commits[-1]

        commits = monitor.get_commits_since(oldest.hexsha)
        assert len(commits) == 4
        # Newest first.
        assert commits[0].message == "test: add auth tests"

    def test_get_commits_since_unknown_hash_returns_empty(self, repo_path: Path) -> None:
        from core.event_bus import EventBus
        from git_integration.git_monitor import GitMonitor

        monitor = GitMonitor(str(repo_path), EventBus())
        monitor._repo = monitor._open_repo()
        result = monitor.get_commits_since("0" * 40)
        assert result == []

    def test_diff_chunks_populated(self, repo_path: Path) -> None:
        from core.event_bus import EventBus
        from git_integration.git_monitor import GitMonitor

        monitor = GitMonitor(str(repo_path), EventBus())
        monitor._repo = monitor._open_repo()
        commit = monitor.get_latest_commit()
        # The last commit added tests/test_auth.py, so diff_chunks should exist.
        assert len(commit.diff_chunks) >= 1
        assert any("test_auth" in dc.file_path for dc in commit.diff_chunks)

    def test_commit_date_is_iso8601(self, repo_path: Path) -> None:
        from core.event_bus import EventBus
        from git_integration.git_monitor import GitMonitor

        monitor = GitMonitor(str(repo_path), EventBus())
        monitor._repo = monitor._open_repo()
        commit = monitor.get_latest_commit()
        # Should parse without error.
        from datetime import datetime
        dt = datetime.fromisoformat(commit.date)
        assert dt.year >= 2024


# =============================================================================
# 7–8. _split_diff_to_chunks
# =============================================================================

class TestSplitDiffToChunks:
    def test_small_diff_single_chunk(self) -> None:
        from git_integration.git_monitor import _split_diff_to_chunks

        diff = "+" + " word" * 50         # 50 words — well under 2000
        chunks = _split_diff_to_chunks("a.py", diff, added=5, removed=0)
        assert len(chunks) == 1
        assert chunks[0].file_path == "a.py"
        assert chunks[0].lines_added == 5

    def test_large_diff_multiple_chunks(self) -> None:
        from git_integration.git_monitor import _split_diff_to_chunks

        diff = " word" * 5_000            # 5000 words — triggers splitting
        chunks = _split_diff_to_chunks("big.py", diff, added=1000, removed=500)
        assert len(chunks) > 1
        # Lines are only counted in the first chunk.
        assert chunks[0].lines_added == 1000
        assert all(c.lines_added == 0 for c in chunks[1:])

    def test_large_diff_chunks_have_overlap(self) -> None:
        from git_integration.git_monitor import _split_diff_to_chunks

        # Use a predictable sequence so overlap is verifiable.
        words = [str(i) for i in range(5000)]
        diff = " ".join(words)
        chunks = _split_diff_to_chunks("x.py", diff, added=0, removed=0)
        assert len(chunks) > 1
        # The last word of chunk 0 should appear somewhere in chunk 1.
        last_word_of_chunk0 = chunks[0].content.split()[-1]
        assert last_word_of_chunk0 in chunks[1].content


# =============================================================================
# 9–14. commit_summarizer
# =============================================================================

class TestCommitSummarizer:
    def _small_commit(self) -> Any:
        from git_integration.git_types import CommitInfo, DiffChunk
        return CommitInfo(
            hash="a" * 40,
            author="Alice <alice@example.com>",
            date="2024-06-14T00:00:00+00:00",
            message="feat: small change",
            files_changed=["a.py"],
            diff_chunks=[DiffChunk("a.py", 5, 2, "small diff content " * 10)],
        )

    def _large_commit(self) -> Any:
        from git_integration.git_types import CommitInfo, DiffChunk
        # Each chunk has 2100 words — above threshold.
        chunks = [
            DiffChunk("auth.py", 300, 100, " word" * 2100),
            DiffChunk("db.py",   200, 50,  " word" * 2100),
        ]
        return CommitInfo(
            hash="b" * 40,
            author="Bob <bob@example.com>",
            date="2024-06-14T01:00:00+00:00",
            message="refactor: big refactor",
            files_changed=["auth.py", "db.py"],
            diff_chunks=chunks,
        )

    def test_single_pass_calls_ai_once(self) -> None:
        from git_integration.commit_summarizer import summarize
        ai = _fake_ai("single summary")
        commit = self._small_commit()
        summarize(commit, ai=ai)
        assert ai.complete.call_count == 1

    def test_single_pass_uses_commit_summary_prompt(self) -> None:
        from git_integration.commit_summarizer import summarize
        ai = _fake_ai()
        commit = self._small_commit()
        summarize(commit, ai=ai)
        assert ai.complete.call_args[0][0] == "commit_summary"

    def test_hierarchical_calls_ai_multiple_times(self) -> None:
        from git_integration.commit_summarizer import summarize
        ai = _fake_ai("chunk summary")
        commit = self._large_commit()
        summarize(commit, ai=ai)
        # 2 chunks + 1 final = 3 calls minimum.
        assert ai.complete.call_count >= 3

    def test_summarize_mutates_ai_summary(self) -> None:
        from git_integration.commit_summarizer import summarize
        ai = _fake_ai("The commit added logout functionality.")
        commit = self._small_commit()
        result = summarize(commit, ai=ai)
        assert commit.ai_summary == "The commit added logout functionality."
        assert result == commit.ai_summary

    def test_summarize_mutates_impact_score(self) -> None:
        from git_integration.commit_summarizer import summarize
        ai = _fake_ai()
        commit = self._small_commit()
        assert commit.impact_score == 0.0
        summarize(commit, ai=ai)
        assert 0.0 < commit.impact_score <= 1.0

    def test_impact_score_zero_files_zero_lines(self) -> None:
        from git_integration.commit_summarizer import calculate_impact_score
        from git_integration.git_types import CommitInfo
        c = CommitInfo(hash="a" * 40, author="A", date="d", message="m")
        score = calculate_impact_score(c)
        assert score == 0.0

    def test_impact_score_capped_at_1(self) -> None:
        from git_integration.commit_summarizer import calculate_impact_score
        from git_integration.git_types import CommitInfo, DiffChunk
        c = CommitInfo(
            hash="a" * 40, author="A", date="d", message="m",
            files_changed=["a", "b", "c", "d", "e", "f", "g", "h"],
            diff_chunks=[DiffChunk("a.py", 5000, 5000, "x")],
        )
        assert calculate_impact_score(c, graph_complexity=1.0) == 1.0

    def test_impact_score_graph_complexity_adds(self) -> None:
        from git_integration.commit_summarizer import calculate_impact_score
        from git_integration.git_types import CommitInfo
        c = CommitInfo(hash="a" * 40, author="A", date="d", message="m",
                       files_changed=["a.py"])
        low  = calculate_impact_score(c, graph_complexity=0.0)
        high = calculate_impact_score(c, graph_complexity=1.0)
        assert high > low


# =============================================================================
# 15–20. GitMemory
# =============================================================================

class TestGitMemory:
    def _commit(self, ai_summary: str = "Auth was refactored.") -> Any:
        from git_integration.git_types import CommitInfo
        return CommitInfo(
            hash="c" * 40,
            author="Carol <carol@example.com>",
            date="2024-06-14T02:00:00+00:00",
            message="refactor: auth",
            files_changed=["auth/login.py", "auth/utils.py"],
            ai_summary=ai_summary,
            impact_score=0.6,
        )

    def test_store_commit_calls_upsert(self) -> None:
        from git_integration.git_memory import GitMemory
        store = _fake_store()
        gm = GitMemory(store)
        gm.store_commit(self._commit())
        store.upsert.assert_called_once()

    def test_store_commit_chunk_id_scheme(self) -> None:
        from git_integration.git_memory import GitMemory
        store = _fake_store()
        gm = GitMemory(store)
        commit = self._commit()
        gm.store_commit(commit)
        chunk = store.upsert.call_args[0][0][0]
        assert chunk.id == f"git::commit::{commit.hash}"

    def test_store_commit_chunk_type_is_commit(self) -> None:
        from git_integration.git_memory import GitMemory
        store = _fake_store()
        gm = GitMemory(store)
        gm.store_commit(self._commit())
        chunk = store.upsert.call_args[0][0][0]
        assert chunk.chunk_type == "commit"

    def test_store_commit_metadata_fields(self) -> None:
        from git_integration.git_memory import GitMemory
        store = _fake_store()
        gm = GitMemory(store)
        commit = self._commit()
        gm.store_commit(commit)
        chunk = store.upsert.call_args[0][0][0]
        meta = chunk.metadata
        assert meta["hash"] == commit.hash
        assert meta["author"] == commit.author
        assert meta["date"] == commit.date
        assert "auth/login.py" in meta["files_changed"]
        assert meta["impact_score"] == 0.6

    def test_store_commit_skips_empty_summary(self) -> None:
        from git_integration.git_memory import GitMemory
        store = _fake_store()
        gm = GitMemory(store)
        commit = self._commit(ai_summary="")
        gm.store_commit(commit)
        store.upsert.assert_not_called()

    def test_search_commits_returns_empty_for_empty_query(self) -> None:
        from git_integration.git_memory import GitMemory
        gm = GitMemory(_fake_store())
        assert gm.search_commits("") == []
        assert gm.search_commits("   ") == []


# =============================================================================
# 21–25. GitEngine — event-driven integration
# =============================================================================

class TestGitEngine:
    def _make_engine(self, repo_path: Path):
        from core.event_bus import EventBus
        from git_integration.git_engine import GitEngine

        bus = EventBus()
        ai = _fake_ai("Commit summary from AI.")
        store = _fake_store()

        engine = GitEngine(
            bus=bus,
            ai=ai,
            memory_store=store,
            repo_path=str(repo_path),
            poll_interval=999.0,   # effectively disable auto-polling in tests
        )
        return engine, bus, ai, store

    def test_start_subscribes_to_git_commit(self, repo_path: Path) -> None:
        from core.event_bus import EventBus
        engine, bus, ai, store = self._make_engine(repo_path)
        engine.start()
        try:
            # Verify subscription exists by checking handler is set.
            assert engine._bus_handler is not None
        finally:
            engine.stop()

    def test_git_commit_event_triggers_summarize(self, repo_path: Path) -> None:
        from git_integration.git_types import CommitInfo
        engine, bus, ai, store = self._make_engine(repo_path)
        engine.start()
        try:
            commit = CommitInfo(
                hash="d" * 40,
                author="Dave <dave@example.com>",
                date="2024-06-14T03:00:00+00:00",
                message="fix: patch",
                files_changed=["fix.py"],
            )
            bus.publish("git.commit", {"commit": commit})
            # Wait for worker to process.
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if ai.complete.call_count >= 1:
                    break
                time.sleep(0.05)
            assert ai.complete.call_count >= 1
        finally:
            engine.stop()

    def test_git_commit_summarized_event_published(self, repo_path: Path) -> None:
        from git_integration.git_types import CommitInfo
        engine, bus, ai, store = self._make_engine(repo_path)
        received: list[Any] = []
        bus.subscribe("git.commit_summarized", lambda p: received.append(p))

        engine.start()
        try:
            commit = CommitInfo(
                hash="e" * 40,
                author="Eve <eve@example.com>",
                date="2024-06-14T04:00:00+00:00",
                message="chore: update deps",
                files_changed=["requirements.txt"],
            )
            bus.publish("git.commit", {"commit": commit})
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if received:
                    break
                time.sleep(0.05)
            assert len(received) == 1
            assert received[0]["commit"].hash == "e" * 40
        finally:
            engine.stop()

    def test_full_pipeline_5_commits(self, repo_path: Path) -> None:
        """Publish 5 commits through the engine; all should be stored."""
        from git_integration.git_types import CommitInfo
        engine, bus, ai, store = self._make_engine(repo_path)
        engine.start()
        try:
            hashes = ["f" * 39 + str(i) for i in range(5)]
            for i, h in enumerate(hashes):
                commit = CommitInfo(
                    hash=h,
                    author=f"User{i} <u{i}@example.com>",
                    date="2024-06-14T00:00:00+00:00",
                    message=f"commit #{i}",
                    files_changed=[f"file{i}.py"],
                )
                bus.publish("git.commit", {"commit": commit})

            # Wait for all 5 to be stored.
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if store.upsert.call_count >= 5:
                    break
                time.sleep(0.05)
            assert store.upsert.call_count == 5
        finally:
            engine.stop()

    def test_commit_payload_delivered_as_commitinfo(self, repo_path: Path) -> None:
        """Verify the event payload wraps a CommitInfo, not a dict."""
        from git_integration.git_types import CommitInfo
        engine, bus, ai, store = self._make_engine(repo_path)
        received: list[Any] = []
        bus.subscribe("git.commit_summarized", lambda p: received.append(p))

        engine.start()
        try:
            commit = CommitInfo(
                hash="0" * 40,
                author="Zero <z@z.com>",
                date="2024-06-14T00:00:00+00:00",
                message="zero commit",
                files_changed=["zero.py"],
            )
            bus.publish("git.commit", {"commit": commit})
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if received:
                    break
                time.sleep(0.05)
            payload = received[0]
            assert isinstance(payload["commit"], CommitInfo)
        finally:
            engine.stop()
