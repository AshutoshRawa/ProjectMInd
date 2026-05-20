"""
core/config.py
==============
Centralised configuration loader for ProjectMind.

Responsibilities
----------------
- Load the bundled ``default_config.yaml`` as a baseline.
- Deep-merge any user-supplied ``config/config.yaml`` on top of it.
- Override individual leaf values with environment variables of the form
  ``PROJECTMIND_<SECTION>__<KEY>`` (double-underscore separates nesting).
  Example: ``PROJECTMIND_LOGGING__LEVEL=DEBUG``
- Expose a single ``Settings`` dataclass that the rest of the application
  reads — never import raw dicts from here.
- Validate required fields and surface clear error messages.

Design notes
------------
- No third-party config library (pydantic-settings, dynaconf, etc.) is used
  intentionally so that Module 1 has zero non-stdlib dependencies beyond PyYAML.
- ``ConfigLoader`` is a pure value object: it reads once at construction time
  and never mutates.  Thread-safe by design.
"""

from __future__ import annotations

import copy
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

# Root of the ProjectMind installation (two levels up from this file).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config" / "default_config.yaml"
_USER_CONFIG_PATH = _PROJECT_ROOT / "config" / "config.yaml"

# Environment-variable prefix used for overrides.
_ENV_PREFIX = "PROJECTMIND_"


# ---------------------------------------------------------------------------
# Settings dataclass hierarchy
# ---------------------------------------------------------------------------

@dataclass
class AppSettings:
    """Top-level application identity."""
    name: str = "ProjectMind"
    version: str = "0.1.0"
    description: str = ""
    instance_id: str = ""


@dataclass
class PathSettings:
    """Filesystem paths used by the system."""
    project_root: str = "."
    logs_dir: str = "logs"
    vault_dir: str = "vault"
    runtime_config: str = "config/runtime.yaml"


@dataclass
class LoggingSettings:
    """Logging configuration."""
    level: str = "INFO"
    max_bytes: int = 5_242_880   # 5 MB
    backup_count: int = 5
    console_color: bool = True
    include_timestamp: bool = True
    filename: str = "projectmind.log"


@dataclass
class VaultFrontmatterSettings:
    """Default front-matter injected into every generated note."""
    author: str = "ProjectMind"
    tags: list[str] = field(default_factory=list)
    status: str = "draft"


@dataclass
class VaultSettings:
    """Obsidian vault layout settings."""
    sections: list[str] = field(default_factory=lambda: [
        "Architecture", "Features", "APIs", "Bugs",
        "Daily", "Generated", "Graphs", "AI-Prompts", "Memory",
    ])
    frontmatter: VaultFrontmatterSettings = field(
        default_factory=VaultFrontmatterSettings
    )


@dataclass
class AISettings:
    """Ollama / model settings (placeholder for Module 2)."""
    ollama_host: str = "http://localhost:11434"
    default_model: str = "qwen2.5-coder:7b"
    fallback_model: str = "qwen2.5:7b"
    timeout: int = 120
    max_tokens: int = 4096
    temperature: float = 0.2


@dataclass
class WatcherSettings:
    """File-watcher settings (placeholder for Module 3)."""
    enabled: bool = False
    ignore_patterns: list[str] = field(default_factory=list)
    debounce_seconds: float = 2.0
    watch_extensions: list[str] = field(default_factory=lambda: [
        ".py", ".ts", ".js", ".go", ".rs", ".md"
    ])


@dataclass
class AnalysisSettings:
    """Code-analysis settings (placeholder for Module 4)."""
    enabled: bool = False
    batch_size: int = 20
    max_file_size: int = 524_288   # 512 KB


@dataclass
class MemorySettings:
    """Memory engine settings (placeholder for Module 5)."""
    enabled: bool = False
    retention_days: int = 90


@dataclass
class GraphSettings:
    """Graph generation settings (placeholder for Module 6)."""
    enabled: bool = False
    format: str = "markdown-links"


@dataclass
class Settings:
    """
    Root settings object.  Every module imports this and reads from it.

    Usage example::

        from core.config import ConfigLoader

        settings = ConfigLoader().load()
        print(settings.logging.level)
    """
    app: AppSettings = field(default_factory=AppSettings)
    paths: PathSettings = field(default_factory=PathSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    vault: VaultSettings = field(default_factory=VaultSettings)
    ai: AISettings = field(default_factory=AISettings)
    watcher: WatcherSettings = field(default_factory=WatcherSettings)
    analysis: AnalysisSettings = field(default_factory=AnalysisSettings)
    memory: MemorySettings = field(default_factory=MemorySettings)
    graph: GraphSettings = field(default_factory=GraphSettings)


# ---------------------------------------------------------------------------
# Loader implementation
# ---------------------------------------------------------------------------

class ConfigLoader:
    """
    Loads, merges, and validates ProjectMind configuration.

    Merge order (later wins):
        1. ``config/default_config.yaml``   — shipped with the repo
        2. ``config/config.yaml``           — user-created, git-ignored
        3. Environment variables             — highest priority

    Parameters
    ----------
    user_config_path:
        Override the path to the user config file.  Useful in tests.
    """

    def __init__(self, user_config_path: Path | None = None) -> None:
        self._default_path = _DEFAULT_CONFIG_PATH
        self._user_path = user_config_path or _USER_CONFIG_PATH

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> Settings:
        """
        Execute the full load-merge-validate pipeline and return a
        populated :class:`Settings` instance.

        Raises
        ------
        FileNotFoundError
            If ``default_config.yaml`` is missing (indicates a broken
            installation).
        ValueError
            If a required field fails validation.
        """
        raw = self._load_defaults()
        raw = self._merge_user_config(raw)
        raw = self._apply_env_overrides(raw)
        self._validate(raw)
        return self._build_settings(raw)

    def generate_default_config(
        self,
        destination: Path | None = None,
        *,
        overwrite: bool = False,
    ) -> Path:
        """
        Write a starter user configuration file and return its path.

        The generated file is copied from ``config/config.example.yaml``
        when available because that file is intentionally beginner-facing.
        If the example file is missing, the bundled default config is used
        as a safe fallback.
        """
        target = destination or self._user_path
        if target.exists() and not overwrite:
            raise FileExistsError(
                f"Config already exists at {target}. "
                "Pass overwrite=True to replace it."
            )

        source = _PROJECT_ROOT / "config" / "config.example.yaml"
        if not source.exists():
            source = self._default_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return target

    @classmethod
    def validate_raw(cls, raw: dict[str, Any]) -> None:
        """Validate a raw config dictionary without loading files."""
        cls._validate(copy.deepcopy(raw))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_defaults(self) -> dict[str, Any]:
        """Load the bundled default configuration."""
        if not self._default_path.exists():
            raise FileNotFoundError(
                f"Default config not found at {self._default_path}. "
                "Your ProjectMind installation may be incomplete."
            )
        with self._default_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data

    def _merge_user_config(self, base: dict[str, Any]) -> dict[str, Any]:
        """
        Deep-merge the user-supplied config on top of *base*.
        Missing user config is silently skipped — it is optional.
        """
        if not self._user_path.exists():
            return base
        with self._user_path.open("r", encoding="utf-8") as fh:
            user_data = yaml.safe_load(fh) or {}
        return _deep_merge(base, user_data)

    def _apply_env_overrides(self, raw: dict[str, Any]) -> dict[str, Any]:
        """
        Walk all environment variables and apply any that match the prefix.

        Variable name mapping::

            PROJECTMIND_LOGGING__LEVEL   → raw["logging"]["level"]
            PROJECTMIND_AI__TIMEOUT      → raw["ai"]["timeout"]
        """
        raw = copy.deepcopy(raw)
        for env_key, env_val in os.environ.items():
            if not env_key.startswith(_ENV_PREFIX):
                continue
            # Strip prefix and split on double-underscore
            stripped = env_key[len(_ENV_PREFIX):]
            parts = [p.lower() for p in stripped.split("__")]
            _set_nested(raw, parts, _coerce_value(env_val))
        return raw

    @staticmethod
    def _validate(raw: dict[str, Any]) -> None:
        """
        Lightweight sanity checks.  Raises :exc:`ValueError` with a
        human-readable message on the first violation found.
        """
        # Logging level must be a valid Python logging level name.
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        level = raw.get("logging", {}).get("level", "INFO").upper()
        if level not in valid_levels:
            raise ValueError(
                f"logging.level '{level}' is invalid. "
                f"Choose one of: {', '.join(sorted(valid_levels))}"
            )

        logging_raw = raw.get("logging", {})
        max_bytes = int(logging_raw.get("max_bytes", 5_242_880))
        backup_count = int(logging_raw.get("backup_count", 5))
        if max_bytes <= 0:
            raise ValueError("logging.max_bytes must be greater than 0")
        if backup_count < 0:
            raise ValueError("logging.backup_count cannot be negative")

        # Ollama host must look like a URL.
        ai_raw = raw.get("ai", {})
        host = ai_raw.get("ollama_host", "")
        if host and not re.match(r"https?://", host):
            raise ValueError(
                f"ai.ollama_host '{host}' must start with http:// or https://"
            )
        timeout = int(ai_raw.get("timeout", 120))
        max_tokens = int(ai_raw.get("max_tokens", 4096))
        temperature = float(ai_raw.get("temperature", 0.2))
        if timeout <= 0:
            raise ValueError("ai.timeout must be greater than 0")
        if max_tokens <= 0:
            raise ValueError("ai.max_tokens must be greater than 0")
        if not 0 <= temperature <= 1:
            raise ValueError("ai.temperature must be between 0 and 1")

        paths_raw = raw.get("paths", {})
        for key in ("project_root", "logs_dir", "vault_dir", "runtime_config"):
            value = paths_raw.get(key)
            if value is not None and not str(value).strip():
                raise ValueError(f"paths.{key} cannot be empty")

        vault_raw = raw.get("vault", {})
        sections = vault_raw.get("sections", VaultSettings().sections)
        if not isinstance(sections, list) or not sections:
            raise ValueError("vault.sections must be a non-empty list")
        if any(
            not isinstance(section, str) or not section.strip()
            for section in sections
        ):
            raise ValueError("vault.sections entries must be non-empty strings")
        if len(set(sections)) != len(sections):
            raise ValueError("vault.sections cannot contain duplicates")

    @staticmethod
    def _build_settings(raw: dict[str, Any]) -> Settings:
        """
        Translate the merged raw dict into a :class:`Settings` object.
        Unknown keys in the YAML are silently ignored so that older config
        files stay compatible with newer code.
        """
        def _get(section: str, default: dict) -> dict:
            return raw.get(section, default)

        # --- app ---------------------------------------------------------
        app_raw = _get("app", {})
        app = AppSettings(
            name=app_raw.get("name", "ProjectMind"),
            version=app_raw.get("version", "0.1.0"),
            description=app_raw.get("description", ""),
            instance_id=app_raw.get("instance_id", ""),
        )

        # --- paths -------------------------------------------------------
        paths_raw = _get("paths", {})
        paths = PathSettings(
            project_root=paths_raw.get("project_root", "."),
            logs_dir=paths_raw.get("logs_dir", "logs"),
            vault_dir=paths_raw.get("vault_dir", "vault"),
            runtime_config=paths_raw.get("runtime_config", "config/runtime.yaml"),
        )

        # --- logging -----------------------------------------------------
        log_raw = _get("logging", {})
        logging_settings = LoggingSettings(
            level=log_raw.get("level", "INFO").upper(),
            max_bytes=int(log_raw.get("max_bytes", 5_242_880)),
            backup_count=int(log_raw.get("backup_count", 5)),
            console_color=_as_bool(log_raw.get("console_color", True)),
            include_timestamp=_as_bool(log_raw.get("include_timestamp", True)),
            filename=log_raw.get("filename", "projectmind.log"),
        )

        # --- vault -------------------------------------------------------
        vault_raw = _get("vault", {})
        fm_raw = vault_raw.get("frontmatter", {})
        vault = VaultSettings(
            sections=vault_raw.get("sections", VaultSettings().sections),
            frontmatter=VaultFrontmatterSettings(
                author=fm_raw.get("author", "ProjectMind"),
                tags=fm_raw.get("tags", []),
                status=fm_raw.get("status", "draft"),
            ),
        )

        # --- ai ----------------------------------------------------------
        ai_raw = _get("ai", {})
        ai = AISettings(
            ollama_host=ai_raw.get("ollama_host", "http://localhost:11434"),
            default_model=ai_raw.get("default_model", "qwen2.5-coder:7b"),
            fallback_model=ai_raw.get("fallback_model", "qwen2.5:7b"),
            timeout=int(ai_raw.get("timeout", 120)),
            max_tokens=int(ai_raw.get("max_tokens", 4096)),
            temperature=float(ai_raw.get("temperature", 0.2)),
        )

        # --- watcher -----------------------------------------------------
        watch_raw = _get("watcher", {})
        watcher = WatcherSettings(
            enabled=_as_bool(watch_raw.get("enabled", False)),
            ignore_patterns=watch_raw.get("ignore_patterns", []),
            debounce_seconds=float(watch_raw.get("debounce_seconds", 2.0)),
            watch_extensions=watch_raw.get(
                "watch_extensions",
                WatcherSettings().watch_extensions,
            ),
        )

        # --- analysis ----------------------------------------------------
        ana_raw = _get("analysis", {})
        analysis = AnalysisSettings(
            enabled=_as_bool(ana_raw.get("enabled", False)),
            batch_size=int(ana_raw.get("batch_size", 20)),
            max_file_size=int(ana_raw.get("max_file_size", 524_288)),
        )

        # --- memory ------------------------------------------------------
        mem_raw = _get("memory", {})
        memory = MemorySettings(
            enabled=_as_bool(mem_raw.get("enabled", False)),
            retention_days=int(mem_raw.get("retention_days", 90)),
        )

        # --- graph -------------------------------------------------------
        graph_raw = _get("graph", {})
        graph = GraphSettings(
            enabled=_as_bool(graph_raw.get("enabled", False)),
            format=graph_raw.get("format", "markdown-links"),
        )

        return Settings(
            app=app,
            paths=paths,
            logging=logging_settings,
            vault=vault,
            ai=ai,
            watcher=watcher,
            analysis=analysis,
            memory=memory,
            graph=graph,
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """
    Recursively merge *override* into a deep copy of *base*.

    - Dicts are merged key-by-key (nested merge).
    - All other types (lists, scalars) are replaced wholesale.
    """
    result = copy.deepcopy(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


def _set_nested(data: dict[str, Any], keys: list[str], value: Any) -> None:
    """
    Set ``data[keys[0]][keys[1]]...[keys[-1]] = value``, creating
    intermediate dicts as needed.  Operates in-place.
    """
    for key in keys[:-1]:
        if key not in data or not isinstance(data[key], dict):
            data[key] = {}
        data = data[key]
    data[keys[-1]] = value


def _coerce_value(raw: str) -> Any:
    """
    Attempt to coerce a raw string env-var value to a Python scalar.

    - "true"/"false" → bool
    - Integer strings → int
    - Float strings   → float
    - Everything else → str
    """
    lower = raw.strip().lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _as_bool(value: Any) -> bool:
    """Coerce booleans from YAML/env-friendly scalar values."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower in {"true", "1", "yes", "on"}:
            return True
        if lower in {"false", "0", "no", "off"}:
            return False
    return bool(value)
