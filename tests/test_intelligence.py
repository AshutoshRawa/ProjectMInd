"""
tests/test_intelligence.py
===========================
Test suite for Module 10 — Autonomous Intelligence Engine.

Mock project
------------
The tests build a 20-file synthetic codebase entirely in memory:
- 20 :class:`~analysis.analysis_types.FileAnalysis` objects
- A corresponding :class:`networkx.DiGraph`
- No real disk I/O except for the :class:`~intelligence.suggestion_store.SuggestionStore`
  JSON file (which uses ``tmp_path`` from pytest).

Tests are grouped by component:
1. pattern_detector (5 tests)
2. refactor_suggester (2 tests)
3. suggestion_store (6 tests)
4. intelligence_engine (2 tests — mocked AI + bus)
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import networkx as nx
import pytest

from analysis.analysis_types import FileAnalysis, FunctionInfo
from intelligence.intelligence_types import Pattern, Suggestion
from intelligence.pattern_detector import (
    COMPLEXITY_THRESHOLD,
    GOD_FILE_THRESHOLD,
    HUB_IN_DEGREE_THRESHOLD,
    detect_anti_patterns,
)
from intelligence.suggestion_store import SuggestionStore


# ---------------------------------------------------------------------------
# Fixtures — 20-file mock project
# ---------------------------------------------------------------------------

def _make_fn(name: str, complexity: int = 1) -> FunctionInfo:
    """Create a minimal FunctionInfo for testing."""
    return FunctionInfo(
        name=name,
        line_start=1,
        line_end=10,
        params=[],
        complexity=complexity,
        has_docstring=True,
        calls=[],
    )


def _make_analysis(
    path: str,
    functions: list[FunctionInfo] | None = None,
    imports: list[str] | None = None,
) -> FileAnalysis:
    """Create a minimal FileAnalysis for testing."""
    return FileAnalysis(
        path=path,
        language="python",
        lines_of_code=100,
        functions=functions or [_make_fn("main")],
        classes=[],
        imports=imports or [],
        ai_summary="",
        anti_patterns=[],
        analyzed_at=time.time(),
    )


@pytest.fixture()
def mock_project() -> tuple[nx.DiGraph, list[FileAnalysis]]:
    """A 20-file synthetic project with no anti-patterns by default.

    Layout
    ------
    - Files: module_00.py … module_19.py
    - Each file imports the next one in sequence (linear chain, no cycles).
    - All files have exactly 2 functions with complexity 2.
    """
    files = [f"module_{i:02d}.py" for i in range(20)]
    analyses: list[FileAnalysis] = []
    graph = nx.DiGraph()

    for i, path in enumerate(files):
        fns = [_make_fn(f"func_{j}", complexity=2) for j in range(2)]
        imports = [files[i + 1]] if i < len(files) - 1 else []
        fa = _make_analysis(path, functions=fns, imports=imports)
        analyses.append(fa)

        graph.add_node(
            path,
            language="python",
            complexity=2.0,
            function_count=2,
            last_analyzed=fa.analyzed_at,
        )

    # Wire edges.
    for i in range(len(files) - 1):
        graph.add_edge(files[i], files[i + 1])

    return graph, analyses


@pytest.fixture()
def store(tmp_path: Path) -> SuggestionStore:
    """A fresh SuggestionStore backed by a temp file (no MemoryStore)."""
    return SuggestionStore(store_path=tmp_path / "suggestions.json")


# ---------------------------------------------------------------------------
# 1. pattern_detector — GOD_FILE
# ---------------------------------------------------------------------------

class TestGodFileDetection:
    def test_god_file_detected(self, mock_project):
        """A file with >20 functions must trigger GOD_FILE."""
        graph, analyses = mock_project
        # Make module_00 a god file.
        god_path = "module_00.py"
        many_fns = [_make_fn(f"fn_{i}") for i in range(GOD_FILE_THRESHOLD + 1)]
        analyses[0] = _make_analysis(god_path, functions=many_fns)
        graph.nodes[god_path]["function_count"] = len(many_fns)

        patterns = detect_anti_patterns(graph, analyses)

        god_patterns = [p for p in patterns if p.pattern_type == "GOD_FILE"]
        assert len(god_patterns) == 1
        assert god_patterns[0].affected_files == [god_path]
        assert god_patterns[0].severity == "high"
        assert len(god_patterns[0].evidence) == GOD_FILE_THRESHOLD + 1

    def test_god_file_not_detected_at_threshold(self, mock_project):
        """Exactly GOD_FILE_THRESHOLD functions must NOT trigger GOD_FILE."""
        graph, analyses = mock_project
        exactly_threshold_fns = [_make_fn(f"fn_{i}") for i in range(GOD_FILE_THRESHOLD)]
        analyses[0] = _make_analysis("module_00.py", functions=exactly_threshold_fns)

        patterns = detect_anti_patterns(graph, analyses)
        assert not any(p.pattern_type == "GOD_FILE" for p in patterns)


# ---------------------------------------------------------------------------
# 2. pattern_detector — CIRCULAR_DEPENDENCY
# ---------------------------------------------------------------------------

class TestCircularDependencyDetection:
    def test_circular_dependency_detected(self, mock_project):
        """A→B→C→A cycle must trigger CIRCULAR_DEPENDENCY."""
        graph, analyses = mock_project
        # Introduce A→B→C→A cycle between modules 5, 6, 7.
        graph.add_edge("module_07.py", "module_05.py")

        patterns = detect_anti_patterns(graph, analyses)

        circ = [p for p in patterns if p.pattern_type == "CIRCULAR_DEPENDENCY"]
        assert len(circ) >= 1
        # The affected files must include our three modules.
        all_affected = {f for p in circ for f in p.affected_files}
        assert {"module_05.py", "module_06.py", "module_07.py"}.issubset(all_affected)

    def test_no_circular_dependency_in_clean_chain(self, mock_project):
        """A clean linear chain must NOT trigger CIRCULAR_DEPENDENCY."""
        graph, analyses = mock_project
        patterns = detect_anti_patterns(graph, analyses)
        assert not any(p.pattern_type == "CIRCULAR_DEPENDENCY" for p in patterns)


# ---------------------------------------------------------------------------
# 3. pattern_detector — COMPLEXITY_HOTSPOT
# ---------------------------------------------------------------------------

class TestComplexityHotspotDetection:
    def test_complexity_hotspot_detected(self, mock_project):
        """A file with complexity > 8 imported by 5+ files triggers COMPLEXITY_HOTSPOT."""
        graph, analyses = mock_project

        hotspot = "module_10.py"
        graph.nodes[hotspot]["complexity"] = COMPLEXITY_THRESHOLD + 1

        # Add 5 extra importer edges (they don't need to be in analyses).
        for i in range(5):
            importer = f"importer_{i}.py"
            if not graph.has_node(importer):
                graph.add_node(importer, language="python", complexity=1.0,
                               function_count=1, last_analyzed=0.0)
            graph.add_edge(importer, hotspot)

        patterns = detect_anti_patterns(graph, analyses)
        hot = [p for p in patterns if p.pattern_type == "COMPLEXITY_HOTSPOT"]
        assert len(hot) >= 1
        assert hot[0].affected_files == [hotspot]
        assert hot[0].severity == "high"

    def test_complexity_hotspot_not_detected_below_in_degree(self, mock_project):
        """High complexity alone (in_degree < 5) must NOT trigger COMPLEXITY_HOTSPOT."""
        graph, analyses = mock_project
        target = "module_10.py"
        graph.nodes[target]["complexity"] = COMPLEXITY_THRESHOLD + 5
        # module_10 already has exactly 1 importer (module_09) in the chain.

        patterns = detect_anti_patterns(graph, analyses)
        assert not any(p.pattern_type == "COMPLEXITY_HOTSPOT" for p in patterns)


# ---------------------------------------------------------------------------
# 4. pattern_detector — ORPHAN_MODULE
# ---------------------------------------------------------------------------

class TestOrphanModuleDetection:
    def test_orphan_detected(self, mock_project):
        """An isolated real file triggers ORPHAN_MODULE."""
        graph, analyses = mock_project

        orphan = "orphan.py"
        fa = _make_analysis(orphan, functions=[_make_fn("do_stuff")], imports=[])
        analyses.append(fa)
        graph.add_node(orphan, language="python", complexity=1.0,
                       function_count=1, last_analyzed=fa.analyzed_at)
        # No edges added — it's completely isolated.

        patterns = detect_anti_patterns(graph, analyses)
        orphans = [p for p in patterns if p.pattern_type == "ORPHAN_MODULE"]
        assert len(orphans) == 1
        assert orphans[0].affected_files == [orphan]

    def test_orphan_not_detected_for_stub_nodes(self, mock_project):
        """External library stub nodes (not in analyses) must not be flagged."""
        graph, analyses = mock_project
        # Add a stub that is NOT in analyses.
        graph.add_node("external_lib", language="unknown", complexity=0.0,
                       function_count=0, last_analyzed=0.0, stub=True)

        patterns = detect_anti_patterns(graph, analyses)
        # The external_lib node has no real FileAnalysis, so it's excluded.
        orphans = [p for p in patterns if p.pattern_type == "ORPHAN_MODULE"]
        orphan_files = {f for p in orphans for f in p.affected_files}
        assert "external_lib" not in orphan_files

    def test_no_false_positives_clean_project(self, mock_project):
        """Clean 20-file chain must produce no patterns (except none)."""
        graph, analyses = mock_project
        patterns = detect_anti_patterns(graph, analyses)
        # The chain has no orphans (all connected), no cycles, no god files,
        # no hotspots (complexity=2, in_degree=1).
        assert patterns == []


# ---------------------------------------------------------------------------
# 5. refactor_suggester — mocked AI
# ---------------------------------------------------------------------------

class TestRefactorSuggester:
    def test_suggest_returns_suggestion(self, store):
        """suggest() must return a PENDING Suggestion with all fields set."""
        from intelligence.refactor_suggester import suggest

        pattern = Pattern(
            pattern_type="GOD_FILE",
            severity="high",
            affected_files=["big_module.py"],
            description="big_module.py has 25 functions.",
            evidence=["big_module.py::func_1"],
        )

        fake_text = "Split big_module.py into auth.py and data.py."

        with patch("intelligence.refactor_suggester.get_ai") as mock_get_ai:
            mock_ai = MagicMock()
            mock_ai.complete.return_value = fake_text
            mock_get_ai.return_value = mock_ai

            suggestion = suggest(pattern, store)

        assert isinstance(suggestion, Suggestion)
        assert suggestion.state == "PENDING"
        assert suggestion.pattern_type == "GOD_FILE"
        assert suggestion.suggestion_text == fake_text
        assert suggestion.priority == 2  # high → 2
        assert suggestion.affected_files == ["big_module.py"]
        assert suggestion.id  # uuid4 string

    def test_suggest_uses_correct_prompt_name(self, store):
        """suggest() must call get_ai().complete with 'refactor_suggestion_v2'."""
        from intelligence.refactor_suggester import suggest, _PROMPT_NAME

        pattern = Pattern(
            pattern_type="ORPHAN_MODULE",
            severity="medium",
            affected_files=["unused.py"],
            description="unused.py is disconnected.",
        )

        with patch("intelligence.refactor_suggester.get_ai") as mock_get_ai:
            mock_ai = MagicMock()
            mock_ai.complete.return_value = "Remove unused.py."
            mock_get_ai.return_value = mock_ai

            suggest(pattern, store)

            call_args = mock_ai.complete.call_args
            assert call_args[0][0] == _PROMPT_NAME

    def test_suggest_never_writes_files(self):
        """The _WRITES_FILES sentinel in refactor_suggester must be False."""
        import intelligence.refactor_suggester as rs
        assert rs._WRITES_FILES is False


# ---------------------------------------------------------------------------
# 6. suggestion_store — persistence
# ---------------------------------------------------------------------------

class TestSuggestionStorePersist:
    def test_persist_and_get_pending(self, store):
        """A persisted PENDING suggestion must appear in get_pending()."""
        s = Suggestion(
            id=str(uuid.uuid4()),
            pattern_type="GOD_FILE",
            affected_files=["a.py"],
            suggestion_text="Split a.py",
            priority=2,
            state="PENDING",
        )
        store.persist(s)

        pending = store.get_pending()
        assert len(pending) == 1
        assert pending[0].id == s.id

    def test_persist_upserts_on_same_id(self, store):
        """Persisting twice with the same id must replace, not duplicate."""
        s = Suggestion(
            id="fixed-id-001",
            pattern_type="GOD_FILE",
            affected_files=["a.py"],
            suggestion_text="v1",
            priority=2,
            state="PENDING",
        )
        store.persist(s)

        s2 = Suggestion(
            id="fixed-id-001",
            pattern_type="GOD_FILE",
            affected_files=["a.py"],
            suggestion_text="v2",
            priority=2,
            state="PENDING",
        )
        store.persist(s2)

        all_suggestions = store.get_all()
        assert len(all_suggestions) == 1
        assert all_suggestions[0].suggestion_text == "v2"


class TestSuggestionStoreStateTransitions:
    def test_update_state_accepted(self, store):
        """Transitioning to ACCEPTED must update state in the store."""
        s = Suggestion(
            id=str(uuid.uuid4()),
            pattern_type="ORPHAN_MODULE",
            affected_files=["orphan.py"],
            suggestion_text="Remove orphan.py",
            priority=3,
            state="PENDING",
        )
        store.persist(s)

        updated = store.update_state(s.id, "ACCEPTED")
        assert updated is not None
        assert updated.state == "ACCEPTED"

        # Verify it no longer appears in get_pending().
        pending = store.get_pending()
        assert not any(p.id == s.id for p in pending)

    def test_update_state_rejected_with_reason(self, store):
        """Transitioning to REJECTED must store the rejection reason."""
        s = Suggestion(
            id=str(uuid.uuid4()),
            pattern_type="GOD_FILE",
            affected_files=["huge.py"],
            suggestion_text="Split huge.py",
            priority=2,
            state="PENDING",
        )
        store.persist(s)

        reason = "The file is intentionally large for performance reasons."
        updated = store.update_state(s.id, "REJECTED", reason=reason)
        assert updated is not None
        assert updated.state == "REJECTED"
        assert updated.rejection_reason == reason

    def test_update_state_invalid_raises(self, store):
        """An invalid state string must raise ValueError."""
        s = Suggestion(
            id=str(uuid.uuid4()),
            pattern_type="GOD_FILE",
            affected_files=["x.py"],
            suggestion_text="Fix x",
            priority=2,
            state="PENDING",
        )
        store.persist(s)

        with pytest.raises(ValueError, match="Invalid state"):
            store.update_state(s.id, "INVALID_STATE")  # type: ignore[arg-type]

    def test_update_state_unknown_id_returns_none(self, store):
        """Updating a non-existent id must return None without error."""
        result = store.update_state("does-not-exist", "ACCEPTED")
        assert result is None


class TestSuggestionStoreDeferral:
    def test_deferred_resurfaces_after_elapsed(self, store):
        """A DEFERRED suggestion whose period has elapsed must become PENDING."""
        s = Suggestion(
            id=str(uuid.uuid4()),
            pattern_type="COMPLEXITY_HOTSPOT",
            affected_files=["complex.py"],
            suggestion_text="Reduce complexity",
            priority=2,
            state="PENDING",
        )
        store.persist(s)

        # Defer it.
        store.update_state(s.id, "DEFERRED")

        # Manually force deferred_until into the past.
        all_s = store.get_all()
        idx = next(i for i, x in enumerate(all_s) if x.id == s.id)
        all_s[idx] = Suggestion(
            id=s.id,
            pattern_type=s.pattern_type,
            affected_files=list(s.affected_files),
            suggestion_text=s.suggestion_text,
            priority=s.priority,
            state="DEFERRED",
            deferred_until=time.time() - 1,  # already elapsed
        )
        store._save_all(all_s)  # noqa: SLF001

        # get_pending() should re-surface it.
        pending = store.get_pending()
        assert any(p.id == s.id for p in pending)


class TestSuggestionStoreFewShotExamples:
    def _seed_n(self, store: SuggestionStore, n: int, state: str, *, reason: str = "") -> list[Suggestion]:
        suggestions: list[Suggestion] = []
        for i in range(n):
            s = Suggestion(
                id=str(uuid.uuid4()),
                pattern_type="GOD_FILE",
                affected_files=[f"file_{i}.py"],
                suggestion_text=f"suggestion text {i}",
                priority=2,
                state="PENDING",
                created_at=time.time() + i,  # ensure order
            )
            store.persist(s)
            store.update_state(s.id, state, reason=reason)
            suggestions.append(s)
        return suggestions

    def test_accepted_examples_for_few_shot(self, store):
        """get_accepted_examples(n=3) must return at most 3 ACCEPTED dicts."""
        self._seed_n(store, 5, "ACCEPTED")
        examples = store.get_accepted_examples(n=3)
        assert len(examples) == 3
        for ex in examples:
            assert ex["state"] == "ACCEPTED"

    def test_rejected_examples_include_reason(self, store):
        """get_rejected_examples must include rejection_reason in each dict."""
        self._seed_n(store, 2, "REJECTED", reason="not applicable")
        examples = store.get_rejected_examples(n=3)
        assert len(examples) == 2
        for ex in examples:
            assert ex["state"] == "REJECTED"
            assert ex["rejection_reason"] == "not applicable"


# ---------------------------------------------------------------------------
# 7. intelligence_engine — integration
# ---------------------------------------------------------------------------

class TestIntelligenceEngine:
    def test_engine_cycle_publishes_event(self, mock_project, store, tmp_path):
        """A full cycle must publish intelligence.suggestions_ready on the bus."""
        from core.event_bus import EventBus
        from intelligence.intelligence_engine import IntelligenceEngine, _OUTPUT_EVENT

        graph, analyses = mock_project

        # Make module_00 a god file so a pattern is detected.
        many_fns = [_make_fn(f"fn_{i}") for i in range(GOD_FILE_THRESHOLD + 1)]
        analyses[0] = _make_analysis("module_00.py", functions=many_fns)
        graph.nodes["module_00.py"]["function_count"] = len(many_fns)

        bus = EventBus()
        received: list[dict] = []
        bus.subscribe(_OUTPUT_EVENT, received.append)

        engine = IntelligenceEngine(
            bus=bus,
            graph=graph,
            analyses=analyses,
            store=store,
            cycle_interval=9999,  # disable automatic timer
        )

        fake_text = "Split module_00.py into sub-modules."
        with patch("intelligence.refactor_suggester.get_ai") as mock_get_ai:
            mock_ai = MagicMock()
            mock_ai.complete.return_value = fake_text
            mock_get_ai.return_value = mock_ai

            engine._run_cycle()  # noqa: SLF001 — trigger manually

        assert len(received) == 1
        payload = received[0]
        assert "suggestions" in payload
        assert len(payload["suggestions"]) >= 1
        assert payload["suggestions"][0]["pattern_type"] == "GOD_FILE"

    def test_engine_skips_already_pending_pattern(self, mock_project, store):
        """A pattern already in PENDING must NOT generate a second suggestion."""
        from core.event_bus import EventBus
        from intelligence.intelligence_engine import IntelligenceEngine, _OUTPUT_EVENT

        graph, analyses = mock_project

        many_fns = [_make_fn(f"fn_{i}") for i in range(GOD_FILE_THRESHOLD + 1)]
        analyses[0] = _make_analysis("module_00.py", functions=many_fns)
        graph.nodes["module_00.py"]["function_count"] = len(many_fns)

        bus = EventBus()
        received: list[dict] = []
        bus.subscribe(_OUTPUT_EVENT, received.append)

        engine = IntelligenceEngine(
            bus=bus, graph=graph, analyses=analyses, store=store, cycle_interval=9999
        )

        fake_text = "Split module_00.py."
        with patch("intelligence.refactor_suggester.get_ai") as mock_get_ai:
            mock_ai = MagicMock()
            mock_ai.complete.return_value = fake_text
            mock_get_ai.return_value = mock_ai

            # First cycle — creates a suggestion.
            engine._run_cycle()  # noqa: SLF001
            first_count = len(store.get_pending())

            # Second cycle — same pattern, already PENDING → skip.
            engine._run_cycle()  # noqa: SLF001
            second_count = len(store.get_pending())

        assert first_count == second_count  # no duplicates
        # Only one event published (second cycle produced nothing new).
        assert len(received) == 1
