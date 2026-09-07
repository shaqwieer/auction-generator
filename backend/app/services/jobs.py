"""Long work runs off the request thread, behind an interface.

The in-process runner is deliberately simple: a fixed pool of worker threads,
one queue, and a cancel flag per job. It matches what the ops screen shows
("ENGINES 3/3 UP") and can be swapped for Celery without touching callers.
"""

from __future__ import annotations

import queue
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from app.core.config import get_settings


@dataclass
class JobHandle:
    job_id: uuid.UUID
    cancelled: threading.Event = field(default_factory=threading.Event)
    paused: threading.Event = field(default_factory=threading.Event)

    def wait_if_paused(self) -> None:
        while self.paused.is_set() and not self.cancelled.is_set():
            self.paused.wait(0.2)


class JobRunner(Protocol):
    def submit(self, job_id: uuid.UUID, work: Callable[[JobHandle], None]) -> None: ...
    def cancel(self, job_id: uuid.UUID) -> bool: ...
    def pause(self, job_id: uuid.UUID) -> bool: ...
    def resume(self, job_id: uuid.UUID) -> bool: ...
    def is_running(self, job_id: uuid.UUID) -> bool: ...


class InProcessRunner:
    def __init__(self, workers: int | None = None) -> None:
        self.workers = workers or get_settings().worker_count
        self._queue: queue.Queue[tuple[JobHandle, Callable[[JobHandle], None]]] = (
            queue.Queue()
        )
        self._handles: dict[uuid.UUID, JobHandle] = {}
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        for index in range(self.workers):
            thread = threading.Thread(
                target=self._loop, name=f"engine-{index + 1:02d}", daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def _loop(self) -> None:
        while True:
            handle, work = self._queue.get()
            try:
                if not handle.cancelled.is_set():
                    work(handle)
            except Exception:
                pass
            finally:
                with self._lock:
                    self._handles.pop(handle.job_id, None)
                self._queue.task_done()

    def submit(self, job_id: uuid.UUID, work: Callable[[JobHandle], None]) -> None:
        self.start()
        handle = JobHandle(job_id=job_id)
        with self._lock:
            self._handles[job_id] = handle
        self._queue.put((handle, work))

    def cancel(self, job_id: uuid.UUID) -> bool:
        with self._lock:
            handle = self._handles.get(job_id)
        if handle is None:
            return False
        handle.paused.clear()
        handle.cancelled.set()
        return True

    def pause(self, job_id: uuid.UUID) -> bool:
        with self._lock:
            handle = self._handles.get(job_id)
        if handle is None:
            return False
        handle.paused.set()
        return True

    def resume(self, job_id: uuid.UUID) -> bool:
        with self._lock:
            handle = self._handles.get(job_id)
        if handle is None:
            return False
        handle.paused.clear()
        return True

    def is_running(self, job_id: uuid.UUID) -> bool:
        with self._lock:
            return job_id in self._handles

    def join(self, timeout: float | None = None) -> None:
        """Block until the queue drains. Used by tests and the CLI."""
        self._queue.join()


_runner: InProcessRunner | None = None


def get_runner() -> InProcessRunner:
    global _runner
    if _runner is None:
        _runner = InProcessRunner()
    return _runner
