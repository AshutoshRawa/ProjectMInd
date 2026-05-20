"""
Smoke tests for :mod:`core.bootstrap`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.bootstrap import bootstrap
from core.config import Settings
from core.registry import ServiceRegistry
from obsidian.vault import VaultManager


@pytest.fixture()
def isolated_config(tmp_path: Path) -> Path:
    """Write a minimal user config that points all paths at *tmp_path*."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"paths:\n"
        f"  project_root: \"{tmp_path.as_posix()}\"\n"
        f"  logs_dir: \"logs\"\n"
        f"  vault_dir: \"vault\"\n",
        encoding="utf-8",
    )
    return cfg


def test_bootstrap_builds_application(isolated_config: Path, tmp_path: Path) -> None:
    app = bootstrap(
        user_config_path=isolated_config, install_signal_handlers=False
    )
    try:
        # Settings + registry are wired.
        assert isinstance(app.settings, Settings)
        assert isinstance(app.registry, ServiceRegistry)
        assert app.registry.get(Settings) is app.settings

        # Vault registered and initialised on disk.
        vault = app.registry.get(VaultManager)
        assert (tmp_path / "vault").is_dir()
        for section in app.settings.vault.sections:
            assert (tmp_path / "vault" / section).is_dir()
        assert vault.root == (tmp_path / "vault").resolve()

        # Logs dir was created.
        assert (tmp_path / "logs").is_dir()
    finally:
        app.shutdown()


def test_shutdown_runs_hooks_in_lifo(
    isolated_config: Path,
) -> None:
    app = bootstrap(
        user_config_path=isolated_config, install_signal_handlers=False
    )
    order: list[str] = []
    app.on_shutdown(lambda: order.append("first"))
    app.on_shutdown(lambda: order.append("second"))
    app.on_shutdown(lambda: order.append("third"))
    app.shutdown()
    assert order == ["third", "second", "first"]


def test_shutdown_swallows_hook_exceptions(
    isolated_config: Path,
) -> None:
    app = bootstrap(
        user_config_path=isolated_config, install_signal_handlers=False
    )
    calls: list[str] = []
    app.on_shutdown(lambda: calls.append("clean"))
    app.on_shutdown(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    app.on_shutdown(lambda: calls.append("also-clean"))
    # Should not raise even though the middle hook explodes.
    app.shutdown()
    assert calls == ["also-clean", "clean"]
