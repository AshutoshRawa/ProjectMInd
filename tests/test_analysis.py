"""
Tests for Module 4 — Code & Architecture Analysis.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

from analysis import Module4AnalyzerEngine
from analysis.analysis_types import FileAnalysis, FunctionInfo
from analysis.ast_analyzer import analyze_python
from analysis.complexity import file_complexity_score
from analysis.dependency_mapper import build_dependency_graph, resolve_local_import
from core import AnalysisSettings, EventBus
from watcher import ChangeKind, FileChangeEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_for_result(results: list[dict[str, object]], timeout: float = 3.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if results:
            return results[0]
        time.sleep(0.05)
    raise AssertionError("expected analysis.file_analyzed event")


# ---------------------------------------------------------------------------
# Existing tests (preserved)
# ---------------------------------------------------------------------------

def test_analyze_python_extracts_structure(tmp_path: Path) -> None:
    source = (
        "import os\n"
        "from pathlib import Path\n\n"
        "class Runner:\n"
        "    pass\n\n"
        "def build(name: str, *, verbose: bool = False) -> Path:\n"
        "    if verbose and name:\n"
        "        print(name)\n"
        "    return Path(name)\n"
    )

    extract = analyze_python(tmp_path / "sample.py", source)

    assert extract.language == "python"
    assert extract.lines_of_code == 8
    assert extract.classes == ["Runner"]
    assert extract.imports == ["os", "pathlib.Path"]
    assert len(extract.functions) == 1
    func = extract.functions[0]
    assert func.name == "build"
    assert func.params == ["name", "verbose"]
    assert func.calls == ["Path", "print"]
    assert func.complexity >= 3


def test_module4_consumes_watcher_event_and_publishes_analysis(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "sample.py"
    target.write_text(
        "import json\n\n"
        "class Tool:\n"
        "    pass\n\n"
        "def run(value):\n"
        "    return json.dumps(value)\n",
        encoding="utf-8",
    )
    fake_ai = SimpleNamespace(
        complete=lambda _name, _variables: (
            '{"purpose": "Serialize a value.", '
            '"suggestions": ["Add a return type annotation."]}'
        )
    )
    monkeypatch.setattr("analysis.analyzer_engine.get_ai", lambda: fake_ai)

    bus = EventBus()
    results: list[dict[str, object]] = []
    bus.subscribe("analysis.file_analyzed", lambda payload: results.append(payload))
    engine = Module4AnalyzerEngine(
        bus=bus,
        settings=AnalysisSettings(enabled=True, max_file_size=524_288),
    )

    engine.start()
    try:
        bus.publish(
            "watcher.file_change",
            {
                "event": FileChangeEvent(
                    path=target,
                    kind=ChangeKind.MODIFIED,
                    timestamp="2026-05-27T00:00:00Z",
                )
            },
        )
        payload = _wait_for_result(results)
    finally:
        engine.stop()

    assert payload["file_path"] == str(target)
    assert payload["language"] == "python"
    assert payload["change_kind"] == "modified"
    analysis = payload["analysis"]
    assert isinstance(analysis, dict)
    assert analysis["path"] == str(target)
    assert analysis["language"] == "python"
    assert analysis["classes"] == ["Tool"]
    assert analysis["imports"] == ["json"]
    assert analysis["ai_summary"] == "Serialize a value."
    assert analysis["anti_patterns"] == ["Add a return type annotation."]
    assert [item["name"] for item in analysis["functions"]] == ["run"]


def test_module4_publishes_deleted_event_without_ai(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def _fail_get_ai():
        raise AssertionError("delete events should not call AI")

    monkeypatch.setattr("analysis.analyzer_engine.get_ai", _fail_get_ai)
    bus = EventBus()
    results: list[dict[str, object]] = []
    bus.subscribe("analysis.file_analyzed", lambda payload: results.append(payload))
    engine = Module4AnalyzerEngine(
        bus=bus,
        settings=AnalysisSettings(enabled=True, max_file_size=524_288),
    )

    engine.start()
    try:
        bus.publish(
            "watcher.file_change",
            {
                "event": FileChangeEvent(
                    path=tmp_path / "removed.py",
                    kind=ChangeKind.DELETED,
                    timestamp="2026-05-27T00:00:00Z",
                )
            },
        )
        payload = _wait_for_result(results)
    finally:
        engine.stop()

    assert payload["analysis"] is None
    assert payload["analysis_error"] == "deleted"


def test_module4_falls_back_to_raw_ai_prompt(monkeypatch) -> None:
    calls: list[str] = []

    class FakeAI:
        def complete(self, _name, _variables):  # noqa: ANN001
            calls.append("complete")
            raise RuntimeError("missing prompt")

        def complete_raw(self, _prompt):  # noqa: ANN001
            calls.append("complete_raw")
            return "Summary line\n- Avoid global state"

    monkeypatch.setattr("analysis.analyzer_engine.get_ai", lambda: FakeAI())

    from analysis.analyzer_engine import _ai_enrich

    summary, anti_patterns = _ai_enrich(
        file_path="sample.py",
        language="python",
        code="x = 1",
    )

    assert calls == ["complete", "complete_raw"]
    assert summary == "Summary line"
    assert anti_patterns == ["Avoid global state"]


def test_module4_extracts_fenced_json_ai_response(monkeypatch) -> None:
    fake_ai = SimpleNamespace(
        complete=lambda _name, _variables: (
            "```json\n"
            "{\n"
            '  "purpose": "Provide calculator helpers.",\n'
            '  "suggestions": ["Add division support.",],\n'
            "}\n"
            "```"
        )
    )
    monkeypatch.setattr("analysis.analyzer_engine.get_ai", lambda: fake_ai)

    from analysis.analyzer_engine import _ai_enrich

    summary, anti_patterns = _ai_enrich(
        file_path="sample.py",
        language="python",
        code="x = 1",
    )

    assert summary == "Provide calculator helpers."
    assert anti_patterns == ["Add division support."]


# ---------------------------------------------------------------------------
# New tests — real .py fixture files
# ---------------------------------------------------------------------------


def test_file_complexity_score_weighted_average(tmp_path: Path) -> None:
    """Create a fixture with functions of varying complexity and verify
    the weighted-average score."""
    fixture = tmp_path / "mixed_complexity.py"
    fixture.write_text(
        # simple_fn: lines 1-2, complexity 1
        "def simple_fn():\n"
        "    return 42\n"
        "\n"
        # complex_fn: lines 4-13, complexity >= 5
        "def complex_fn(x, y, z):\n"
        "    if x > 0:\n"
        "        for i in range(y):\n"
        "            if i % 2 == 0:\n"
        "                while z > 0:\n"
        "                    z -= 1\n"
        "            elif i > 10:\n"
        "                pass\n"
        "        return x\n"
        "    return 0\n",
        encoding="utf-8",
    )

    extract = analyze_python(fixture, fixture.read_text())
    analysis = FileAnalysis(
        path=str(fixture),
        language=extract.language,
        lines_of_code=extract.lines_of_code,
        functions=extract.functions,
        classes=extract.classes,
        imports=extract.imports,
        ai_summary="",
        anti_patterns=[],
        analyzed_at=time.time(),
    )

    score = file_complexity_score(analysis)
    # Score must be between the minimum (1) and max complexity.
    assert score > 1.0, f"Weighted score {score} should exceed 1 (simple baseline)"
    # The complex function spans more lines, so it dominates.
    complexities = [f.complexity for f in analysis.functions]
    assert score <= max(complexities), "Score must not exceed the max individual complexity"


def test_file_complexity_score_no_functions() -> None:
    """Verify file_complexity_score returns 0.0 for a file with no functions."""
    analysis = FileAnalysis(
        path="empty.py",
        language="python",
        lines_of_code=5,
        functions=[],
        classes=["Config"],
        imports=["os"],
        ai_summary="",
        anti_patterns=[],
        analyzed_at=time.time(),
    )
    assert file_complexity_score(analysis) == 0.0


def test_resolve_local_import_finds_module(tmp_path: Path) -> None:
    """Create a mini project tree and verify import resolution."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")

    result = resolve_local_import("mypkg.utils", tmp_path)
    assert result is not None
    assert result.endswith("utils.py")

    # Also resolve a package itself.
    result_pkg = resolve_local_import("mypkg", tmp_path)
    assert result_pkg is not None
    assert result_pkg.endswith("__init__.py")


def test_resolve_local_import_returns_none_for_stdlib() -> None:
    """Standard-library imports like 'os' and 'sys' should return None."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        assert resolve_local_import("os", td) is None
        assert resolve_local_import("sys", td) is None
        assert resolve_local_import("json.decoder", td) is None


def test_analysis_types_json_roundtrip() -> None:
    """Serialize FileAnalysis to JSON, deserialize back, and verify equality."""
    func = FunctionInfo(
        name="process",
        line_start=10,
        line_end=25,
        params=["data", "verbose"],
        complexity=4,
        has_docstring=True,
        calls=["print", "validate"],
    )
    original = FileAnalysis(
        path="/tmp/sample.py",
        language="python",
        lines_of_code=100,
        functions=[func],
        classes=["Processor"],
        imports=["os", "json"],
        ai_summary="Processes incoming data.",
        anti_patterns=["God function"],
        analyzed_at=1717600000.0,
    )

    # Round-trip via dict.
    d = original.to_dict()
    assert isinstance(d, dict)
    restored_from_dict = FileAnalysis.from_dict(d)
    assert restored_from_dict == original

    # Round-trip via JSON string.
    j = original.to_json()
    assert isinstance(j, str)
    parsed = json.loads(j)
    assert parsed["path"] == "/tmp/sample.py"
    restored_from_json = FileAnalysis.from_json(j)
    assert restored_from_json == original

    # FunctionInfo round-trip.
    fj = func.to_json()
    assert FunctionInfo.from_json(fj) == func


def test_analyze_python_syntax_error_graceful(tmp_path: Path) -> None:
    """Verify partial result on broken Python (SyntaxError)."""
    broken = tmp_path / "broken.py"
    broken.write_text(
        "import os\n"
        "def oops(:\n"  # deliberate syntax error
        "    pass\n",
        encoding="utf-8",
    )

    extract = analyze_python(broken, broken.read_text())
    assert extract.language == "python"
    assert extract.lines_of_code == 3
    # AST failed, so structures are empty.
    assert extract.functions == []
    assert extract.classes == []
    assert extract.imports == []


def test_analyze_python_extracts_methods_inside_classes(tmp_path: Path) -> None:
    """Verify that methods defined inside a class body are discovered."""
    fixture = tmp_path / "with_class.py"
    fixture.write_text(
        "class MyService:\n"
        "    def __init__(self, name):\n"
        '        """Constructor."""\n'
        "        self.name = name\n"
        "\n"
        "    def run(self):\n"
        "        print(self.name)\n"
        "\n"
        "    async def fetch(self, url):\n"
        "        return await self._get(url)\n"
        "\n"
        "def standalone():\n"
        "    pass\n",
        encoding="utf-8",
    )

    extract = analyze_python(fixture, fixture.read_text())
    func_names = sorted(f.name for f in extract.functions)
    assert "standalone" in func_names
    assert "__init__" in func_names
    assert "run" in func_names
    assert "fetch" in func_names

    # __init__ should have a docstring.
    init_fn = next(f for f in extract.functions if f.name == "__init__")
    assert init_fn.has_docstring is True

    # fetch is async — verify it was captured.
    fetch_fn = next(f for f in extract.functions if f.name == "fetch")
    assert "_get" in fetch_fn.calls


def test_build_dependency_graph_local_imports(tmp_path: Path) -> None:
    """Multi-file fixture project — verify the dependency graph is correct."""
    # Create a mini project: pkga/mod.py imports pkgb.helper
    pkga = tmp_path / "pkga"
    pkga.mkdir()
    (pkga / "__init__.py").write_text("", encoding="utf-8")
    (pkga / "mod.py").write_text(
        "from pkgb import helper\n\ndef work():\n    helper.do()\n",
        encoding="utf-8",
    )

    pkgb = tmp_path / "pkgb"
    pkgb.mkdir()
    (pkgb / "__init__.py").write_text("", encoding="utf-8")
    (pkgb / "helper.py").write_text(
        "def do():\n    print('done')\n",
        encoding="utf-8",
    )

    analyses = [
        FileAnalysis(
            path=str(pkga / "mod.py"),
            language="python",
            lines_of_code=4,
            functions=[],
            classes=[],
            imports=["pkgb.helper"],
            ai_summary="",
            anti_patterns=[],
            analyzed_at=time.time(),
        ),
        FileAnalysis(
            path=str(pkgb / "helper.py"),
            language="python",
            lines_of_code=2,
            functions=[],
            classes=[],
            imports=[],
            ai_summary="",
            anti_patterns=[],
            analyzed_at=time.time(),
        ),
    ]

    graph = build_dependency_graph(analyses, project_root=tmp_path)
    mod_deps = graph[str(pkga / "mod.py")]
    assert len(mod_deps) == 1
    assert mod_deps[0].endswith("helper.py")
    # helper.py has no local deps.
    assert graph[str(pkgb / "helper.py")] == []
