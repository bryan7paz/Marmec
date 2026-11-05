"""Global pipeline state tracker — shared between API and background tasks."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any


class PipelineState:
    """Singleton that holds the current pipeline execution state.

    Thread-safe: all mutations go through a lock.
    Observers (SSE) read via snapshots.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls) -> PipelineState:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._reset()
        return cls._instance

    def _reset(self) -> None:
        self.running = False
        self.step = ""  # "crawling" | "processing" | "persisting" | ""
        self.current = ""  # fonte ou documento atual
        self.processed = 0
        self.total = 0
        self.errors: list[str] = []
        self.last_run: datetime | None = None
        self.last_run_ok = False
        self.queue_size = 0
        self.docs_persisted = 0
        self.started_at: datetime | None = None
        self.crawl_stats: dict[str, int] | None = None
        self._listeners: list[threading.Event] = []

    # ── Mutation ────────────────────────────────────────────────────

    def start(self) -> None:
        with self._lock:
            self.running = True
            self.step = "starting"
            self.current = ""
            self.processed = 0
            self.total = 0
            self.errors = []
            self.started_at = datetime.now(UTC)
            self._notify()

    def update(self, **kwargs: Any) -> None:
        with self._lock:
            for k, v in kwargs.items():
                setattr(self, k, v)
            self._notify()

    def finish(self, ok: bool = True) -> None:
        with self._lock:
            self.running = False
            self.step = ""
            self.current = ""
            self.last_run = datetime.now(UTC)
            self.last_run_ok = ok
            self._notify()

    def add_error(self, msg: str) -> None:
        with self._lock:
            self.errors.append(msg)
            self._notify()

    # ── Observation (SSE) ──────────────────────────────────────────

    def subscribe(self) -> threading.Event:
        """Return a new Event that fires on every state change."""
        evt = threading.Event()
        with self._lock:
            self._listeners.append(evt)
        return evt

    def unsubscribe(self, evt: threading.Event) -> None:
        with self._lock:
            self._listeners = [e for e in self._listeners if e is not evt]

    def _notify(self) -> None:
        for evt in self._listeners:
            evt.set()

    # ── Snapshot ────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self.running,
                "step": self.step,
                "current": self.current,
                "processed": self.processed,
                "total": self.total,
                "errors": list(self.errors),
                "last_run": self.last_run.isoformat() if self.last_run else None,
                "last_run_ok": self.last_run_ok,
                "queue_size": self.queue_size,
                "docs_persisted": self.docs_persisted,
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "crawl_stats": self.crawl_stats,
            }


# Module-level singleton
pipeline_state = PipelineState()
