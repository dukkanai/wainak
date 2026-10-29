"""Transactional repository seam; independent from HTTP and database drivers."""

import copy
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import ContextManager, Protocol


@dataclass
class State:
    accounts: dict = field(default_factory=dict)
    sessions: dict = field(default_factory=dict)
    relationships: dict = field(default_factory=dict)
    blocks: set = field(default_factory=set)
    reports: dict = field(default_factory=dict)
    idempotency: dict = field(default_factory=dict)


class Repository(Protocol):
    durable: bool

    def transaction(self) -> ContextManager[State]:
        """Yield one consistent state; commit on success, roll back on failure."""
        ...


class MemoryRepository:
    """Copy-on-write transactions support independent services sharing one store."""

    durable = False

    def __init__(self):
        self._state = State()
        self._lock = threading.RLock()

    @contextmanager
    def transaction(self):
        with self._lock:
            working = copy.deepcopy(self._state)
            yield working
            self._state = copy.deepcopy(working)
