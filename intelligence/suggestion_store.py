"""
intelligence/suggestion_store.py
==================================
Module 10 — Suggestion persistence and feedback loop.

Responsibilities
----------------
1. **Persist** suggestions to a JSON file so they survive restarts.
2. **Track lifecycle state**: PENDING → ACCEPTED | REJECTED | DEFERRED.
3. **Re-surface DEFERRED suggestions** after 7 days if the pattern still
   exists (callers check :meth:`get_pending`; this module only re-opens
   suggestions whose deferral period has elapsed).
4. **Write Memory feedback chunks** after every state change so future AI
   prompts can learn from the history via semantic search.

The feedback loop is the most important quality mechanism in Module 10.
Every call to :meth:`update_state` writes a ``Chunk`` with
``chunk_type="suggestion_feedback"`` into the memory store.  The
:func:`~intelligence.refactor_suggester.suggest` function reads these back
via :meth:`get_accepted_examples` and :meth:`get_rejected_examples` to
provide few-shot context to the AI.

Thread safety
-------------
All public methods are protected by a ``threading.Lock``.  The JSON file is
written atomically via :func:`core.utils.atomic_write_text`.

Storage layout
--------------
``<store_path>`` (default ``<project_root>/suggestions.json``)::

    [
        { ...Suggestion.to_dict()... },
        ...
    ]
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from core.logger import get_logger
from core.utils import atomic_write_text
from intelligence.intelligence_types import Suggestion, SuggestionState

if TYPE_CHECKING:
    from memory.memory_store import MemoryStore

log = get_logger(__name__)


_DEFERRED_SECONDS: float = 7 * 24 * 3600  # 7 days
VALID_STATES: frozenset[str] = frozenset({"PENDING", "ACCEPTED", "REJECTED", "DEFERRED"})


# ---------------------------------------------------------------------------
# SuggestionStore
# ---------------------------------------------------------------------------

class SuggestionStore:
    """JSON-backed store for :class:`~intelligence.intelligence_types.Suggestion` objects.

    Parameters
    ----------
    store_path:
        Path to the JSON file where suggestions are persisted.
        Created on first write if it does not exist.
    memory_store:
        Optional :class:`~memory.memory_store.MemoryStore`.  When supplied,
        state changes are mirrored as ``suggestion_feedback`` chunks so that
        semantic search surfaces the project's refactoring history.
    """

    def __init__(
        self,
        store_path: str | Path,
        memory_store: "MemoryStore | None" = None,
    ) -> None:
        self._path = Path(store_path)
        self._memory_store = memory_store
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def persist(self, suggestion: Suggestion) -> None:
        """Add or update *suggestion* in the store.

        If a suggestion with the same ``id`` already exists it is replaced;
        otherwise it is appended.  The JSON file is written atomically.

        Parameters
        ----------
        suggestion:
            The :class:`~intelligence.intelligence_types.Suggestion` to store.
        """
        with self._lock:
            suggestions = self._load_all()
            # Upsert by id.
            idx = next(
                (i for i, s in enumerate(suggestions) if s.id == suggestion.id),
                None,
            )
            if idx is not None:
                suggestions[idx] = suggestion
            else:
                suggestions.append(suggestion)
            self._save_all(suggestions)

        log.debug("[suggestion_store] persisted suggestion id=%s state=%s",
                  suggestion.id, suggestion.state)

    def update_state(
        self,
        suggestion_id: str,
        state: SuggestionState,
        reason: str = "",
    ) -> Suggestion | None:
        """Transition *suggestion_id* to *state*.

        Valid transitions::

            PENDING → ACCEPTED | REJECTED | DEFERRED
            DEFERRED → PENDING | ACCEPTED | REJECTED

        After a successful transition the suggestion is persisted and a
        ``suggestion_feedback`` chunk is written to the memory store (if
        configured).

        Parameters
        ----------
        suggestion_id:
            UUID string matching :attr:`~Suggestion.id`.
        state:
            New state.  Must be one of ``PENDING``, ``ACCEPTED``,
            ``REJECTED``, ``DEFERRED``.
        reason:
            Free-text explanation (required for ``REJECTED``; recommended
            for ``DEFERRED``).

        Returns
        -------
        Suggestion | None
            The updated suggestion, or ``None`` if *suggestion_id* was not
            found.

        Raises
        ------
        ValueError
            If *state* is not a valid :data:`VALID_STATES` member.
        """
        if state not in VALID_STATES:
            raise ValueError(
                f"Invalid state {state!r}. Must be one of: "
                + ", ".join(sorted(VALID_STATES))
            )

        with self._lock:
            suggestions = self._load_all()
            match = next((s for s in suggestions if s.id == suggestion_id), None)
            if match is None:
                log.warning("[suggestion_store] update_state: id=%s not found", suggestion_id)
                return None

            # Mutate a fresh dataclass instance (Suggestion is not frozen).
            updated = Suggestion(
                id=match.id,
                pattern_type=match.pattern_type,
                affected_files=list(match.affected_files),
                suggestion_text=match.suggestion_text,
                priority=match.priority,
                state=state,
                created_at=match.created_at,
                deferred_until=(
                    time.time() + _DEFERRED_SECONDS if state == "DEFERRED" else 0.0
                ),
                rejection_reason=reason if state == "REJECTED" else match.rejection_reason,
            )

            idx = suggestions.index(match)
            suggestions[idx] = updated
            self._save_all(suggestions)

        log.info(
            "[suggestion_store] state change: id=%s %s → %s",
            suggestion_id, match.state, state,
        )

        # Write feedback chunk to memory so future prompts can learn.
        self._write_feedback_chunk(updated, reason=reason)
        return updated

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_pending(self) -> list[Suggestion]:
        """Return all suggestions currently in ``PENDING`` state.

        DEFERRED suggestions whose ``deferred_until`` timestamp has elapsed
        are automatically promoted back to ``PENDING`` before returning.

        Returns
        -------
        list[Suggestion]
            Sorted by priority ascending (1 = critical first), then by
            creation time ascending (oldest first).
        """
        with self._lock:
            suggestions = self._load_all()
            now = time.time()
            changed = False

            for i, s in enumerate(suggestions):
                if s.state == "DEFERRED" and s.deferred_until > 0 and now >= s.deferred_until:
                    suggestions[i] = Suggestion(
                        id=s.id,
                        pattern_type=s.pattern_type,
                        affected_files=list(s.affected_files),
                        suggestion_text=s.suggestion_text,
                        priority=s.priority,
                        state="PENDING",
                        created_at=s.created_at,
                        deferred_until=0.0,
                        rejection_reason=s.rejection_reason,
                    )
                    changed = True
                    log.info("[suggestion_store] DEFERRED→PENDING (elapsed): id=%s", s.id)

            if changed:
                self._save_all(suggestions)

            pending = [s for s in suggestions if s.state == "PENDING"]

        pending.sort(key=lambda s: (s.priority, s.created_at))
        return pending

    def get_accepted_examples(self, n: int = 3) -> list[dict]:
        """Return the *n* most-recently accepted suggestions as dicts.

        Used by :mod:`intelligence.refactor_suggester` to build few-shot
        context for the AI prompt.

        Parameters
        ----------
        n:
            Maximum number of examples to return.

        Returns
        -------
        list[dict]
            Each dict is ``Suggestion.to_dict()`` for an ``ACCEPTED``
            suggestion, ordered newest-first.
        """
        with self._lock:
            suggestions = self._load_all()

        accepted = [
            s for s in suggestions if s.state == "ACCEPTED"
        ]
        # Newest first.
        accepted.sort(key=lambda s: s.created_at, reverse=True)
        return [s.to_dict() for s in accepted[:n]]

    def get_rejected_examples(self, n: int = 3) -> list[dict]:
        """Return the *n* most-recently rejected suggestions as dicts.

        Used by :mod:`intelligence.refactor_suggester` to build few-shot
        context for the AI prompt.

        Parameters
        ----------
        n:
            Maximum number of examples to return.

        Returns
        -------
        list[dict]
            Each dict is ``Suggestion.to_dict()`` for a ``REJECTED``
            suggestion, ordered newest-first.  Includes ``rejection_reason``.
        """
        with self._lock:
            suggestions = self._load_all()

        rejected = [
            s for s in suggestions if s.state == "REJECTED"
        ]
        rejected.sort(key=lambda s: s.created_at, reverse=True)
        return [s.to_dict() for s in rejected[:n]]

    def get_all(self) -> list[Suggestion]:
        """Return every suggestion in the store."""
        with self._lock:
            return self._load_all()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_all(self) -> list[Suggestion]:
        """Load all suggestions from the JSON file.  Must be called under lock."""
        if not self._path.exists():
            return []
        try:
            raw: list[dict] = json.loads(self._path.read_text(encoding="utf-8"))
            return [Suggestion.from_dict(d) for d in raw if isinstance(d, dict)]
        except (json.JSONDecodeError, KeyError) as exc:
            log.error("[suggestion_store] corrupted store at %s: %s", self._path, exc)
            return []

    def _save_all(self, suggestions: list[Suggestion]) -> None:
        """Persist suggestions to the JSON file atomically.  Must be called under lock."""
        payload = json.dumps(
            [s.to_dict() for s in suggestions],
            indent=2,
            ensure_ascii=False,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self._path, payload)

    def _write_feedback_chunk(self, suggestion: Suggestion, *, reason: str) -> None:
        """Write a suggestion_feedback chunk to the memory store.

        This is the bridge that connects the feedback loop to future AI
        prompts.  The chunk text describes what was suggested, for which
        pattern, and what the outcome was.  Future calls to
        :meth:`get_accepted_examples` / :meth:`get_rejected_examples` read
        from the JSON store; this chunk makes the history queryable via
        semantic search for broader context queries.
        """
        if self._memory_store is None:
            return

        try:
            from memory.chunker import Chunk  # deferred to avoid circular imports

            chunk_text = (
                f"[suggestion_feedback] id={suggestion.id}\n"
                f"pattern_type: {suggestion.pattern_type}\n"
                f"affected_files: {', '.join(suggestion.affected_files)}\n"
                f"state: {suggestion.state}\n"
                f"priority: {suggestion.priority}\n"
            )
            if reason:
                chunk_text += f"reason: {reason}\n"
            chunk_text += f"suggestion_text:\n{suggestion.suggestion_text}"

            chunk = Chunk(
                id=f"suggestion_feedback::{suggestion.id}",
                content=chunk_text,
                chunk_type="text",  # type: ignore[arg-type]  # "suggestion_feedback" is stored in metadata
                metadata={
                    "suggestion_id": suggestion.id,
                    "pattern_type": suggestion.pattern_type,
                    "state": suggestion.state,
                    "priority": suggestion.priority,
                    "file_path": "intelligence/suggestion_store",
                    "language": "projectmind",
                    "chunk_type": "suggestion_feedback",
                },
            )
            self._memory_store.upsert([chunk])
            log.debug(
                "[suggestion_store] feedback chunk written for id=%s state=%s",
                suggestion.id, suggestion.state,
            )
        except Exception as exc:  # noqa: BLE001
            # Memory write failure must never crash the main flow.
            log.warning(
                "[suggestion_store] failed to write feedback chunk for id=%s: %s",
                suggestion.id, exc,
            )
