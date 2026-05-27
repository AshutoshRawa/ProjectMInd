from __future__ import annotations

import queue
import re
import threading
from dataclasses import asdict
from pathlib import Path
import json
import time
from typing import Any

from ai import get_ai
from analysis.ast_analyzer import analyze_python, empty_extract
from analysis.analysis_types import FileAnalysis
from core import AnalysisSettings, EventBus, Analyzer, get_logger
from watcher import ChangeKind, FileChangeEvent

log = get_logger(__name__)


class Module4AnalyzerEngine(Analyzer):
    """
    Module 4: consume watcher events, run lightweight static analysis
    (AST/complexity/import extraction), optionally enrich with AI summary,
    and emit structured results via EventBus.
    """

    name = "analysis"

    def __init__(
        self,
        *,
        bus: EventBus,
        settings: AnalysisSettings,
        event_name: str = "watcher.file_change",
        output_event_name: str = "analysis.file_analyzed",
    ) -> None:
        self._bus = bus
        self._settings = settings
        self._event_name = event_name
        self._output_event_name = output_event_name

        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._queue: "queue.Queue[FileChangeEvent]" = queue.Queue()
        self._bus_handler: Any | None = None
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True

        self._stop_event.clear()
        self._queue = queue.Queue()

        def _on_bus_event(payload: dict[str, Any]) -> None:
            event = payload.get("event")
            if isinstance(event, FileChangeEvent):
                self._queue.put(event)

        self._bus_handler = _on_bus_event
        self._bus.subscribe(self._event_name, _on_bus_event)

        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="projectmind.module4.analysis",
            daemon=True,
        )
        self._worker_thread.start()

        log.info("[analysis] subscribed to %s and started worker", self._event_name)

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False

        self._stop_event.set()

        if self._bus_handler is not None:
            self._bus.unsubscribe(self._event_name, self._bus_handler)
            self._bus_handler = None

        if self._worker_thread is not None:
            self._worker_thread.join(timeout=5.0)
            self._worker_thread = None

        log.info("[analysis] stopped")

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                event = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                self._analyze_event(event)
            except Exception as exc:  # noqa: BLE001
                log.exception("[analysis] failed to analyse event: %s", exc)

    def _analyze_event(self, event: FileChangeEvent) -> None:
        # Handle deletes first: no code to analyse.
        if event.kind == ChangeKind.DELETED:
            self._bus.publish(
                self._output_event_name,
                {
                    "file_path": str(event.path),
                    "analysis": None,
                    "analysis_error": "deleted",
                },
            )
            return

        path = event.path
        if not path.exists() or not path.is_file():
            self._bus.publish(
                self._output_event_name,
                {
                    "file_path": str(path),
                    "analysis": None,
                    "analysis_error": "file_missing",
                },
            )
            return

        try:
            if path.stat().st_size > self._settings.max_file_size:
                self._bus.publish(
                    self._output_event_name,
                    {
                        "file_path": str(path),
                        "analysis": None,
                        "analysis_error": "file_too_large",
                    },
                )
                return
        except OSError:
            # If we can't stat, just skip analysis.
            return

        code = path.read_text(encoding="utf-8", errors="ignore")
        if not code.strip():
            return

        language = _guess_language(path)

        extract = _static_extract(path, language=language, code=code)
        ai_summary, anti_patterns = _ai_enrich(
            file_path=str(path),
            language=extract.language,
            code=code,
        )

        analysis = FileAnalysis(
            path=str(path),
            language=extract.language,
            lines_of_code=extract.lines_of_code,
            functions=extract.functions,
            classes=extract.classes,
            imports=extract.imports,
            ai_summary=ai_summary,
            anti_patterns=anti_patterns,
            analyzed_at=time.time(),
        )

        self._bus.publish(
            self._output_event_name,
            {
                "file_path": str(path),
                "language": language,
                "change_kind": event.kind.value,
                "analysis": asdict(analysis),
            },
        )


def _guess_language(path: Path) -> str:
    ext = path.suffix.lower()
    mapping = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".jsx": "jsx",
        ".md": "markdown",
        ".json": "json",
    }
    return mapping.get(ext, ext.lstrip(".") or "unknown")

def _static_extract(path: Path, *, language: str, code: str):
    if language == "python":
        return analyze_python(path, code)
    return empty_extract(language=language, source=code)


def _ai_enrich(*, file_path: str, language: str, code: str) -> tuple[str, list[str]]:
    """
    Best-effort AI enrichment.
    - If the `code_analysis` prompt exists, prefer it.
    - Otherwise fall back to a raw prompt.

    This returns (summary, anti_patterns). If AI is unavailable or fails,
    returns ("", []).
    """
    try:
        text = get_ai().complete(
            "code_analysis",
            {"file_path": file_path, "language": language, "code": code},
        )
    except Exception:
        try:
            text = get_ai().complete_raw(
                "Summarize this file in 3-5 sentences and list any anti-patterns "
                "as bullet points.\n\n"
                f"File: {file_path}\nLanguage: {language}\n\n{code}"
            )
        except Exception:
            return "", []

    # If prompt returns JSON (default `code_analysis`), derive summary from fields.
    parsed = _parse_json_object(text)
    if parsed is not None:
        purpose = parsed.get("purpose")
        suggestions = parsed.get("suggestions")
        summary = purpose.strip() if isinstance(purpose, str) else ""
        if isinstance(suggestions, list):
            anti = [str(x).strip() for x in suggestions if str(x).strip()]
            return summary, anti
        return summary, []

    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    anti: list[str] = []
    summary_lines: list[str] = []
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith(("-", "*")) and len(stripped) > 2:
            anti.append(stripped[1:].strip())
        else:
            if stripped:
                summary_lines.append(stripped)

    summary = " ".join(summary_lines).strip()
    return summary, anti


def _parse_json_object(text: str) -> dict[str, Any] | None:
    cleaned = (text or "").strip()
    if not cleaned:
        return None

    fence_match = re.search(
        r"```(?:json|JSON)?\s*([\s\S]*?)\s*```",
        cleaned,
    )
    if fence_match:
        cleaned = fence_match.group(1).strip()

    candidates = [cleaned]
    object_match = re.search(r"\{[\s\S]*\}", cleaned)
    if object_match:
        candidates.append(object_match.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(_remove_trailing_commas(candidate))
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _remove_trailing_commas(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text)
