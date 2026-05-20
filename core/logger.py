"""
core/logger.py
==============
Centralised logging factory for ProjectMind.

Key design choices
------------------
- A single ``get_logger(name)`` entry point is used everywhere in the
  codebase — no module should configure its own handler.
- The root ``projectmind`` logger is configured **once** during
  ``bootstrap()``; subsequent calls to ``get_logger`` simply return a
  child logger and are therefore cheap.
- Rotating file handler + console handler are both wired in, with
  independent formatters so the console can optionally include ANSI colour
  while the file always stays plain text.
- Colour support degrades gracefully: if the terminal does not support
  ANSI escape codes the formatter falls back to plain output automatically.

Usage
-----
.. code-block:: python

    from core.logger import get_logger

    log = get_logger(__name__)
    log.info("System started")
    log.debug("Detailed diagnostic: %s", some_value)
    log.error("Something went wrong", exc_info=True)
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Avoid a hard import of Settings at module load time so that logger.py
    # can be safely imported before the config system is initialised.
    from core.config import LoggingSettings

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_ROOT_LOGGER_NAME = "projectmind"

# Tracks whether bootstrap() has already been called so we never add
# duplicate handlers.
_configured: bool = False


# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------

class _ANSIColour:
    """Minimal ANSI escape-code constants."""
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    GREY    = "\033[90m"
    CYAN    = "\033[36m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    RED     = "\033[31m"
    MAGENTA = "\033[35m"

    # Map Python logging levels to colours
    LEVEL_COLOURS: dict[int, str] = {
        logging.DEBUG:    GREY,
        logging.INFO:     GREEN,
        logging.WARNING:  YELLOW,
        logging.ERROR:    RED,
        logging.CRITICAL: MAGENTA,
    }


def _supports_colour() -> bool:
    """Return True if the current stdout appears to support ANSI colours."""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


# ---------------------------------------------------------------------------
# Custom formatters
# ---------------------------------------------------------------------------

class _PlainFormatter(logging.Formatter):
    """
    Plain-text formatter for file output.

    Example output::

        2024-01-15 12:30:45,123 | INFO     | core.config          | Settings loaded successfully
    """

    _FMT_WITH_TIME = (
        "%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s"
    )
    _FMT_NO_TIME = "%(levelname)-8s | %(name)-22s | %(message)s"
    _DATE_FMT = "%Y-%m-%d %H:%M:%S"

    def __init__(self, *, include_timestamp: bool = True) -> None:
        fmt = self._FMT_WITH_TIME if include_timestamp else self._FMT_NO_TIME
        super().__init__(fmt=fmt, datefmt=self._DATE_FMT)


class _ColourFormatter(logging.Formatter):
    """
    ANSI-coloured formatter for console output.

    The level name is coloured; the module name is dimmed; the message
    itself is left unstyled so embedded data is easy to read.
    """

    _DATE_FMT = "%H:%M:%S"

    def __init__(self, *, include_timestamp: bool = True) -> None:
        super().__init__()
        self._include_timestamp = include_timestamp

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        colour = _ANSIColour.LEVEL_COLOURS.get(record.levelno, _ANSIColour.RESET)
        level_str = f"{colour}{record.levelname:<8}{_ANSIColour.RESET}"
        name_str  = f"{_ANSIColour.CYAN}{record.name:<22}{_ANSIColour.RESET}"
        msg_str   = record.getMessage()

        # Append exception traceback if present
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            msg_str = f"{msg_str}\n{exc_text}"

        if self._include_timestamp:
            time_str = (
                f"{_ANSIColour.GREY}"
                f"{self.formatTime(record, self._DATE_FMT)}"
                f"{_ANSIColour.RESET}"
            )
            return f"{time_str} | {level_str} | {name_str} | {msg_str}"
        return f"{level_str} | {name_str} | {msg_str}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def bootstrap(
    logs_dir: Path,
    settings: "LoggingSettings",
) -> None:
    """
    Configure the root ``projectmind`` logger.

    This must be called **once**, early in the startup sequence (from
    ``core/bootstrap.py``).  It is idempotent — subsequent calls are
    no-ops so test suites can call it safely multiple times.

    Parameters
    ----------
    logs_dir:
        Directory where the rotating log file will be written.  Created
        if it does not exist.
    settings:
        The logging section of the application :class:`~core.config.Settings`.
    """
    global _configured
    if _configured:
        return

    logs_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger(_ROOT_LOGGER_NAME)
    root.setLevel(getattr(logging, settings.level, logging.INFO))

    # Prevent log records from propagating to the Python root logger,
    # which would cause duplicate output.
    root.propagate = False

    # ---- File handler ---------------------------------------------------
    log_file = logs_dir / settings.filename
    file_handler = RotatingFileHandler(
        filename=log_file,
        maxBytes=settings.max_bytes,
        backupCount=settings.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        _PlainFormatter(include_timestamp=settings.include_timestamp)
    )
    file_handler.setLevel(logging.DEBUG)  # Capture everything to file
    root.addHandler(file_handler)

    # ---- Console handler ------------------------------------------------
    console_handler = logging.StreamHandler(sys.stdout)
    use_colour = settings.console_color and _supports_colour()
    console_handler.setFormatter(
        _ColourFormatter(include_timestamp=settings.include_timestamp)
        if use_colour
        else _PlainFormatter(include_timestamp=settings.include_timestamp)
    )
    console_handler.setLevel(getattr(logging, settings.level, logging.INFO))
    root.addHandler(console_handler)

    _configured = True

    # Log the first line *after* both handlers are attached so it appears
    # in both the file and the console.
    root.info(
        "Logging initialised — level=%s  file=%s",
        settings.level,
        log_file,
    )


def get_logger(name: str) -> logging.Logger:
    """
    Return a child logger under the ``projectmind`` namespace.

    Parameters
    ----------
    name:
        Typically ``__name__`` of the calling module.  The logger name
        shown in output will be relative to ``projectmind``.

    Returns
    -------
    logging.Logger
        A configured child logger ready for use.

    Example
    -------
    .. code-block:: python

        from core.logger import get_logger
        log = get_logger(__name__)
        log.info("Module loaded")
    """
    # If the caller passes a fully qualified name (e.g. ``core.config``)
    # we prefix it with the root namespace so that all loggers form a
    # coherent tree.
    if name.startswith(_ROOT_LOGGER_NAME):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")


def set_level(level: str) -> None:
    """
    Dynamically adjust the minimum log level at runtime.

    Useful for temporarily enabling DEBUG output without restarting.

    Parameters
    ----------
    level:
        One of ``"DEBUG"``, ``"INFO"``, ``"WARNING"``, ``"ERROR"``,
        ``"CRITICAL"`` (case-insensitive).
    """
    numeric = getattr(logging, level.upper(), None)
    if numeric is None:
        raise ValueError(f"Unknown log level: {level!r}")
    root = logging.getLogger(_ROOT_LOGGER_NAME)
    root.setLevel(numeric)
    for handler in root.handlers:
        handler.setLevel(numeric)
