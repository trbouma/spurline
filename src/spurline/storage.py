"""Async storage boundary shared by relay backends."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Protocol

from .events import StoredEvent
from .store import EventStore


class StorageError(Exception):
    """A backend operation failed; publication may need reconciliation."""


class EventStorage(Protocol):
    async def save(self, event: StoredEvent) -> bool:
        """Commit an event and its tags/deletions atomically; False for duplicates."""
        ...

    async def query(self, filters: list[dict[str, Any]]) -> list[StoredEvent]:
        """Return unique, visible events ordered by descending timestamp and ID."""
        ...

    async def close(self) -> None:
        """Release backend resources after outstanding operations finish."""
        ...


class SQLiteStorage:
    """Keep synchronous SQLite work off the relay event loop."""

    def __init__(self, database_path: Path) -> None:
        self._store = EventStore(database_path)

    async def save(self, event: StoredEvent) -> bool:
        try:
            return await asyncio.to_thread(self._store.save, event)
        except (sqlite3.Error, OverflowError) as exc:
            raise StorageError("SQLite save failed") from exc

    async def query(self, filters: list[dict[str, Any]]) -> list[StoredEvent]:
        try:
            return await asyncio.to_thread(self._store.query, filters)
        except (sqlite3.Error, OverflowError) as exc:
            raise StorageError("SQLite query failed") from exc

    async def close(self) -> None:
        await asyncio.to_thread(self._store.close)
