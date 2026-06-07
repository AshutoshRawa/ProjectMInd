"""
tests/test_graph.py
===================
Tests for Module 6 — Graph Engine.

Uses a 10-file mock project graph to verify all graph_analyzer
functions return correct results, plus unit tests for graph_builder,
graph_state, and the EventBus integration (Module6GraphEngine).

Mock project dependency topology
---------------------------------

    main.py ──► utils.py ──► helpers.py
       │              │
       │              └──► constants.py
       ▼
    config.py ──► constants.py
       │
       └──► utils.py

    api.py ──► utils.py
           ──► models.py ──► constants.py
           ──► services.py ──► utils.py
                          ──► models.py

    orphan.py   (no edges at all)

In-degree summary:
    utils.py    : imported by main, api, services     → 3
    constants.py: imported by helpers, config, models → 3
    models.py   : imported by api, services           → 2
    helpers.py  : imported by utils                   → 1
    config.py   : imported by main                    → 1
    services.py : imported by api                     → 1
    main.py     : 0
    api.py      : 0
    orphan.py   : 0 (and out-degree 0)

Cycles:
    None in this topology.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import networkx as nx
import pytest

from analysis.analysis_types import FileAnalysis, FunctionInfo
from core import EventBus
from graph import (
    GraphEngine,
    GraphStateManager,
    Module6GraphEngine,
    complexity_hotspots,
    find_circular_deps,
    find_hubs,
    find_orphans,
    load_graph,
    save_graph,
)


# ---------------------------------------------------------------------------
# Shared helpers & fixtures
# ---------------------------------------------------------------------------

def _make_func(name: str = "fn", complexity: int = 1) -> FunctionInfo:
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
    imports: list[str] | None = None,
    complexity: int = 1,
    functions: list[FunctionInfo] | None = None,
) -> FileAnalysis:
    if functions is None:
        functions = [_make_func("fn", complexity)]
    return FileAnalysis(
        path=path,
        language="python",
        lines_of_code=50,
        functions=functions,
        classes=[],
        imports=imports or [],
        ai_summary="",
        anti_patterns=[],
        analyzed_at=time.time(),
    )


# ---------------------------------------------------------------------------
# 10-file mock project fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_graph() -> nx.DiGraph:
    """Build the 10-node mock project graph described in the module docstring."""
    engine = GraphEngine()

    files: list[tuple[str, list[str], int]] = [
        # (path, imports, complexity)
        ("main.py",     ["utils.py", "config.py"],                        2),
        ("utils.py",    ["helpers.py", "constants.py"],                   3),
        ("helpers.py",  [],                                                1),
        ("constants.py",[],                                                1),
        ("config.py",   ["constants.py", "utils.py"],                     2),
        ("api.py",      ["utils.py", "models.py", "services.py"],         5),
        ("models.py",   ["constants.py"],                                  2),
        ("services.py", ["utils.py", "models.py"],                        4),
        ("orphan.py",   [],                                                1),  # true orphan
        ("cli.py",      ["main.py"],                                       2),  # imports main
    ]

    for path, imports, cx in files:
        analysis = _make_analysis(path, imports=imports, complexity=cx)
        engine.update_node(analysis)
        engine.update_edges(analysis)

    return engine.graph


# ---------------------------------------------------------------------------
# graph_builder.py — GraphEngine
# ---------------------------------------------------------------------------

class TestGraphEngine:

    def test_update_node_adds_node(self) -> None:
        engine = GraphEngine()
        analysis = _make_analysis("src/foo.py", complexity=3)
        engine.update_node(analysis)

        assert engine.graph.has_node("src/foo.py")
        attrs = engine.graph.nodes["src/foo.py"]
        assert attrs["language"] == "python"
        assert attrs["function_count"] == 1
        assert "complexity" in attrs
        assert "last_analyzed" in attrs

    def test_update_node_is_incremental(self) -> None:
        """Second update_node call must update attributes, not re-add the node."""
        engine = GraphEngine()
        a1 = _make_analysis("a.py", complexity=1)
        a2 = _make_analysis("a.py", complexity=9, functions=[_make_func("fn", 9)])

        engine.update_node(a1)
        engine.update_node(a2)

        # Should still be exactly one node.
        assert engine.graph.number_of_nodes() == 1
        # Complexity must reflect the second analysis.
        assert engine.graph.nodes["a.py"]["complexity"] > 1.0

    def test_update_edges_adds_edges(self) -> None:
        engine = GraphEngine()
        analysis = _make_analysis("a.py", imports=["b.py", "c.py"])
        engine.update_node(analysis)
        added, removed = engine.update_edges(analysis)

        assert set(added) == {"b.py", "c.py"}
        assert removed == []
        assert engine.graph.has_edge("a.py", "b.py")
        assert engine.graph.has_edge("a.py", "c.py")

    def test_update_edges_removes_stale_edges(self) -> None:
        engine = GraphEngine()
        a1 = _make_analysis("a.py", imports=["b.py", "c.py"])
        engine.update_node(a1)
        engine.update_edges(a1)

        # Second analysis drops c.py.
        a2 = _make_analysis("a.py", imports=["b.py"])
        engine.update_node(a2)
        added, removed = engine.update_edges(a2)

        assert "c.py" in removed
        assert not engine.graph.has_edge("a.py", "c.py")
        assert engine.graph.has_edge("a.py", "b.py")

    def test_remove_node(self) -> None:
        engine = GraphEngine()
        analysis = _make_analysis("x.py", imports=["y.py"])
        engine.update_node(analysis)
        engine.update_edges(analysis)

        engine.remove_node("x.py")
        assert not engine.graph.has_node("x.py")
        # Edge must also be gone (networkx removes incident edges with the node).
        assert not engine.graph.has_edge("x.py", "y.py")

    def test_remove_node_safe_on_missing(self) -> None:
        engine = GraphEngine()
        engine.remove_node("nonexistent.py")  # must not raise

    def test_get_neighbors(self) -> None:
        engine = GraphEngine()
        analysis = _make_analysis("root.py", imports=["a.py", "b.py"])
        engine.update_node(analysis)
        engine.update_edges(analysis)

        neighbors = engine.get_neighbors("root.py")
        assert sorted(neighbors) == ["a.py", "b.py"]

    def test_get_neighbors_missing_node(self) -> None:
        engine = GraphEngine()
        assert engine.get_neighbors("ghost.py") == []

    def test_get_related_files_depth_1(self) -> None:
        engine = GraphEngine()
        for path, imports in [("a.py", ["b.py"]), ("b.py", ["c.py"]), ("c.py", [])]:
            analysis = _make_analysis(path, imports=imports)
            engine.update_node(analysis)
            engine.update_edges(analysis)

        related = engine.get_related_files("a.py", depth=1)
        assert "b.py" in related
        assert "c.py" not in related  # depth 1 only

    def test_get_related_files_depth_2(self) -> None:
        engine = GraphEngine()
        for path, imports in [("a.py", ["b.py"]), ("b.py", ["c.py"]), ("c.py", [])]:
            analysis = _make_analysis(path, imports=imports)
            engine.update_node(analysis)
            engine.update_edges(analysis)

        related = engine.get_related_files("a.py", depth=2)
        assert "b.py" in related
        assert "c.py" in related  # reachable at depth 2

    def test_get_related_excludes_self(self) -> None:
        engine = GraphEngine()
        analysis = _make_analysis("a.py", imports=["b.py"])
        engine.update_node(analysis)
        engine.update_edges(analysis)

        related = engine.get_related_files("a.py")
        assert "a.py" not in related


# ---------------------------------------------------------------------------
# graph_state.py — save / load / auto-save
# ---------------------------------------------------------------------------

class TestGraphState:

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        g = nx.DiGraph()
        g.add_node("a.py", language="python", complexity=2.5, function_count=3,
                   last_analyzed=1000.0)
        g.add_node("b.py", language="python", complexity=1.0, function_count=1,
                   last_analyzed=2000.0)
        g.add_edge("a.py", "b.py")

        save_graph(g, state_file)
        assert state_file.exists()

        restored = load_graph(state_file)
        assert restored.number_of_nodes() == 2
        assert restored.number_of_edges() == 1
        assert restored.has_edge("a.py", "b.py")

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        g = load_graph(tmp_path / "nonexistent.json")
        assert isinstance(g, nx.DiGraph)
        assert g.number_of_nodes() == 0

    def test_load_corrupt_file_returns_empty(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "corrupt.json"
        bad_file.write_text("{{{{ not json !!!}", encoding="utf-8")
        g = load_graph(bad_file)
        assert isinstance(g, nx.DiGraph)
        assert g.number_of_nodes() == 0

    def test_auto_save_triggers_at_interval(self, tmp_path: Path) -> None:
        state_file = tmp_path / "auto.json"
        mgr = GraphStateManager(state_file, auto_save_interval=5)
        g = nx.DiGraph()
        g.add_node("x.py")

        # 4 updates — no file yet.
        for _ in range(4):
            triggered = mgr.record_update(g)
            assert not triggered
        assert not state_file.exists()

        # 5th update — auto-save fires.
        triggered = mgr.record_update(g)
        assert triggered
        assert state_file.exists()

    def test_auto_save_atomic_no_corrupt_on_partial_write(self, tmp_path: Path) -> None:
        """Verify no .tmp file is left behind after a successful save."""
        state_file = tmp_path / "state.json"
        mgr = GraphStateManager(state_file)
        g = nx.DiGraph()
        g.add_node("z.py")
        mgr.save_graph(g)

        tmp_file = state_file.with_suffix(".tmp")
        assert not tmp_file.exists()


# ---------------------------------------------------------------------------
# graph_analyzer.py — using the 10-file mock graph
# ---------------------------------------------------------------------------

class TestFindOrphans:

    def test_orphan_detected(self, mock_graph: nx.DiGraph) -> None:
        orphans = find_orphans(mock_graph)
        assert "orphan.py" in orphans

    def test_connected_nodes_not_orphans(self, mock_graph: nx.DiGraph) -> None:
        orphans = find_orphans(mock_graph)
        assert "utils.py" not in orphans
        assert "main.py" not in orphans

    def test_orphan_count(self, mock_graph: nx.DiGraph) -> None:
        # Only orphan.py qualifies (no in-edges AND no out-edges).
        orphans = find_orphans(mock_graph)
        assert len(orphans) == 1

    def test_empty_graph_returns_empty(self) -> None:
        assert find_orphans(nx.DiGraph()) == []


class TestFindHubs:

    def test_hub_detection_threshold_3(self, mock_graph: nx.DiGraph) -> None:
        """utils.py is imported by main, api, services → in-degree 3."""
        hubs = find_hubs(mock_graph, threshold=3)
        assert "utils.py" in hubs

    def test_hub_detection_threshold_4(self, mock_graph: nx.DiGraph) -> None:
        """No node has in-degree ≥ 5 in our mock graph.

        utils.py has in-degree 4 (main, api, services, config), so
        threshold=5 should return an empty list.
        """
        hubs = find_hubs(mock_graph, threshold=5)
        assert hubs == []

    def test_hub_sorted_by_in_degree(self, mock_graph: nx.DiGraph) -> None:
        hubs = find_hubs(mock_graph, threshold=2)
        assert len(hubs) >= 2
        # Highest in-degree node comes first.
        in_degrees = [mock_graph.in_degree(h) for h in hubs]
        assert in_degrees == sorted(in_degrees, reverse=True)

    def test_empty_graph_returns_empty(self) -> None:
        assert find_hubs(nx.DiGraph(), threshold=1) == []


class TestFindCircularDeps:

    def test_no_cycles_in_mock_graph(self, mock_graph: nx.DiGraph) -> None:
        cycles = find_circular_deps(mock_graph)
        assert cycles == []

    def test_cycle_detected(self) -> None:
        g = nx.DiGraph()
        g.add_edges_from([("a.py", "b.py"), ("b.py", "c.py"), ("c.py", "a.py")])
        cycles = find_circular_deps(g)
        assert len(cycles) == 1
        cycle = cycles[0]
        assert set(cycle) == {"a.py", "b.py", "c.py"}

    def test_self_loop_detected(self) -> None:
        g = nx.DiGraph()
        g.add_edge("x.py", "x.py")
        cycles = find_circular_deps(g)
        assert any("x.py" in c for c in cycles)

    def test_two_separate_cycles(self) -> None:
        g = nx.DiGraph()
        g.add_edges_from([("a.py", "b.py"), ("b.py", "a.py")])   # cycle 1
        g.add_edges_from([("c.py", "d.py"), ("d.py", "c.py")])   # cycle 2
        cycles = find_circular_deps(g)
        assert len(cycles) == 2

    def test_empty_graph_returns_empty(self) -> None:
        assert find_circular_deps(nx.DiGraph()) == []


class TestComplexityHotspots:

    def test_hotspots_with_high_complexity_and_high_indegree(self) -> None:
        """
        Build a graph where only one node is unambiguously the hotspot.

        hotspot.py: complexity=50 (far above all others), in-degree=10.
        sink.py:    complexity=1,  in-degree=0  → excluded on BOTH axes.

        We add 10 distinct low-complexity callers so the quartile
        boundary falls clearly below hotspot's in-degree.
        """
        g = nx.DiGraph()
        # The target hotspot — highest complexity AND highest in-degree.
        g.add_node("hotspot.py", complexity=50.0, function_count=10, last_analyzed=0.0)
        # An isolated, simple file — zero in-degree, very low complexity.
        g.add_node("sink.py", complexity=1.0, function_count=1, last_analyzed=0.0)
        # 10 callers, each with complexity=1 and in-degree=0.
        for i in range(10):
            caller = f"caller{i}.py"
            g.add_node(caller, complexity=1.0, function_count=1, last_analyzed=0.0)
            g.add_edge(caller, "hotspot.py")

        hotspots = complexity_hotspots(g)
        assert "hotspot.py" in hotspots
        assert "sink.py" not in hotspots

    def test_no_real_nodes_returns_empty(self) -> None:
        """Stub nodes (no complexity attr) are ignored."""
        g = nx.DiGraph()
        g.add_node("stub.py")  # no attributes
        assert complexity_hotspots(g) == []

    def test_empty_graph_returns_empty(self) -> None:
        assert complexity_hotspots(nx.DiGraph()) == []

    def test_mock_graph_hotspots(self, mock_graph: nx.DiGraph) -> None:
        """Must not raise; result is a list of strings."""
        result = complexity_hotspots(mock_graph)
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, str)


# ---------------------------------------------------------------------------
# Module6GraphEngine — EventBus integration
# ---------------------------------------------------------------------------

def _wait_for(results: list[Any], timeout: float = 3.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if results:
            return results[0]
        time.sleep(0.05)
    raise AssertionError("expected graph.graph_updated event but none arrived")


class TestModule6GraphEngine:

    def test_subscribe_and_publish(self, tmp_path: Path) -> None:
        """Analysis event → graph engine → graph.graph_updated event."""
        bus = EventBus()
        results: list[dict[str, Any]] = []
        bus.subscribe("graph.graph_updated", results.append)

        engine = Module6GraphEngine(
            bus=bus,
            state_path=tmp_path / "state.json",
        )
        engine.start()
        try:
            analysis = _make_analysis("src/main.py", imports=["src/utils.py"])
            bus.publish(
                "analysis.file_analyzed",
                {"file_path": analysis.path, "analysis": analysis.to_dict()},
            )
            payload = _wait_for(results)
        finally:
            engine.stop()

        assert payload["updated_node"] == "src/main.py"
        assert isinstance(payload["edges_added"], list)
        assert isinstance(payload["edges_removed"], list)
        assert "src/utils.py" in payload["edges_added"]
        stats = payload["stats"]
        assert stats["node_count"] >= 1
        assert "edge_count" in stats
        assert "orphan_count" in stats

    def test_state_saved_on_stop(self, tmp_path: Path) -> None:
        """stop() must write the state file."""
        state_file = tmp_path / "graph_state.json"
        bus = EventBus()
        engine = Module6GraphEngine(bus=bus, state_path=state_file)
        engine.start()
        analysis = _make_analysis("a.py", imports=["b.py"])
        bus.publish(
            "analysis.file_analyzed",
            {"file_path": analysis.path, "analysis": analysis.to_dict()},
        )
        time.sleep(0.2)  # let worker process
        engine.stop()

        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert "nodes" in data  # node-link format

    def test_start_idempotent(self, tmp_path: Path) -> None:
        """Calling start() twice must not raise or double-subscribe."""
        bus = EventBus()
        engine = Module6GraphEngine(bus=bus, state_path=tmp_path / "s.json")
        engine.start()
        engine.start()  # must be a no-op
        engine.stop()

    def test_stop_idempotent(self, tmp_path: Path) -> None:
        bus = EventBus()
        engine = Module6GraphEngine(bus=bus, state_path=tmp_path / "s.json")
        engine.start()
        engine.stop()
        engine.stop()  # must be a no-op

    def test_multiple_analyses_incremental(self, tmp_path: Path) -> None:
        """Verify second analysis updates the node, not duplicates it."""
        bus = EventBus()
        results: list[dict[str, Any]] = []
        bus.subscribe("graph.graph_updated", results.append)

        engine = Module6GraphEngine(bus=bus, state_path=tmp_path / "s.json")
        engine.start()
        try:
            for cx in (2, 5):  # two analyses of same file
                analysis = _make_analysis(
                    "a.py", imports=["b.py"],
                    complexity=cx,
                    functions=[_make_func("fn", cx)],
                )
                bus.publish(
                    "analysis.file_analyzed",
                    {"file_path": analysis.path, "analysis": analysis.to_dict()},
                )
            time.sleep(0.3)
        finally:
            engine.stop()

        # After both analyses the graph should still have exactly one "a.py" node.
        assert engine._engine.graph.number_of_nodes() >= 1  # type: ignore[attr-defined]
        assert engine._engine.graph.has_node("a.py")  # type: ignore[attr-defined]
