"""
Tests for Module 4 — Code & Architecture Analysis.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

from analysis import Module4AnalyzerEngine
from analysis.ast_analyzer import analyze_python
from core import AnalysisSettings, EventBus
from watcher import ChangeKind, FileChangeEvent


def _wait_for_result(results: list[dict[str, object]], timeout: float = 3.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if results:
            return results[0]
        time.sleep(0.05)
    raise AssertionError("expected analysis.file_analyzed event")


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
