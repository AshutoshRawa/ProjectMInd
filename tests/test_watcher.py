"""
Tests for Module 2 — Watcher Engine.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from core.config import WatcherSettings
from watcher.events import ChangeKind
from watcher.file_tracker import FileTracker
from watcher.filters import PathFilter
from watcher.watcher_manager import WatcherManager


@pytest.fixture()
def watcher_settings() -> WatcherSettings:
    return WatcherSettings(
        enabled=True,
        watch_dirs=["backend"],
        debounce_seconds=0.15,
        watch_extensions=[".py", ".md"],
    )


@pytest.fixture()
def watch_tree(tmp_path: Path) -> Path:
    """Minimal backend/ tree for watcher tests."""
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "api").mkdir()
    (backend / "api" / "routes.py").write_text("x = 1\n", encoding="utf-8")
    (backend / "node_modules").mkdir()
    (backend / "node_modules" / "pkg.js").write_text("", encoding="utf-8")
    return tmp_path


def test_path_filter_ignores_node_modules(
    watch_tree: Path,
    watcher_settings: WatcherSettings,
) -> None:
    filt = PathFilter(watcher_settings, watch_tree)
    ignored = watch_tree / "backend" / "node_modules" / "pkg.js"
    allowed = watch_tree / "backend" / "api" / "routes.py"
    assert not filt.is_allowed_file(ignored)
    assert filt.is_allowed_file(allowed)


def test_path_filter_ignores_all_default_build_and_cache_dirs(
    watch_tree: Path,
    watcher_settings: WatcherSettings,
) -> None:
    filt = PathFilter(watcher_settings, watch_tree)
    ignored_dirs = [
        "node_modules",
        ".git",
        "__pycache__",
        "pycache",
        "dist",
        "build",
        "venv",
        ".venv",
        ".next",
        "coverage",
    ]

    for dirname in ignored_dirs:
        path = watch_tree / "backend" / dirname / "ignored.py"
        assert not filt.is_allowed_file(path)


def test_path_filter_allows_extensions_and_blocks_others(
    watch_tree: Path,
    watcher_settings: WatcherSettings,
) -> None:
    filt = PathFilter(watcher_settings, watch_tree)
    assert filt.is_allowed_file(watch_tree / "backend" / "readme.md")
    assert not filt.is_allowed_file(watch_tree / "backend" / "image.png")


def test_path_filter_allows_deleted_paths(
    watch_tree: Path,
    watcher_settings: WatcherSettings,
) -> None:
    filt = PathFilter(watcher_settings, watch_tree)
    ghost = watch_tree / "backend" / "removed.py"
    assert filt.is_allowed_file(ghost)


def test_file_tracker_debounces_duplicate_events() -> None:
    emitted: list[tuple[Path, ChangeKind]] = []

    def _capture(event) -> None:  # noqa: ANN001
        emitted.append((event.path, event.kind))

    tracker = FileTracker(debounce_seconds=0.2, on_flush=_capture)
    path = Path("/tmp/example.py")
    tracker.record(path, ChangeKind.MODIFIED)
    tracker.record(path, ChangeKind.MODIFIED)
    tracker.record(path, ChangeKind.MODIFIED)
    assert tracker.pending_count() == 1
    time.sleep(0.35)
    assert len(emitted) == 1
    assert emitted[0][1] == ChangeKind.MODIFIED


def test_file_tracker_merge_prefers_delete_over_modify() -> None:
    emitted: list[ChangeKind] = []

    tracker = FileTracker(
        debounce_seconds=0.2,
        on_flush=lambda e: emitted.append(e.kind),
    )
    path = Path("/tmp/remove_me.py")
    tracker.record(path, ChangeKind.MODIFIED)
    tracker.record(path, ChangeKind.DELETED)
    tracker.flush_now()
    assert emitted == [ChangeKind.DELETED]


def _wait_for_event(events: list[str], expected: str, timeout: float = 4.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(expected in event for event in events):
            return
        time.sleep(0.05)
    raise AssertionError(f"expected watcher event containing {expected!r}: {events}")


def test_watcher_manager_logs_modified_file(
    watch_tree: Path,
    watcher_settings: WatcherSettings,
) -> None:
    events: list[str] = []

    manager = WatcherManager(
        project_root=watch_tree,
        settings=watcher_settings,
        on_event=lambda e: events.append(str(e)),
    )
    manager.start()
    try:
        target = watch_tree / "backend" / "api" / "routes.py"
        target.write_text("x = 2\n", encoding="utf-8")
        _wait_for_event(events, "modified")
    finally:
        manager.stop()


def test_watcher_manager_logs_created_and_deleted_files(
    watch_tree: Path,
    watcher_settings: WatcherSettings,
) -> None:
    events: list[str] = []

    manager = WatcherManager(
        project_root=watch_tree,
        settings=watcher_settings,
        on_event=lambda e: events.append(str(e)),
    )
    manager.start()
    try:
        target = watch_tree / "backend" / "api" / "new_route.py"
        target.write_text("x = 1\n", encoding="utf-8")
        _wait_for_event(events, "created")

        target.unlink()
        _wait_for_event(events, "deleted")
    finally:
        manager.stop()


def test_watcher_manager_skips_missing_watch_dirs(
    tmp_path: Path,
    watcher_settings: WatcherSettings,
) -> None:
    manager = WatcherManager(
        project_root=tmp_path,
        settings=watcher_settings,
    )
    # No backend/ directory — start should not raise.
    manager.start()
    assert not manager.healthy()
    manager.stop()
