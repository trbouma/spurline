from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .events import StoredEvent
from .filters import filter_limit, matches_any_filter


class EventStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def close(self) -> None:
        with self.lock:
            self.connection.close()

    def save(self, event: StoredEvent) -> bool:
        with self.lock:
            cursor = self.connection.execute(
                """
                INSERT OR IGNORE INTO events
                  (id, pubkey, created_at, kind, tags_json, content, sig, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.pubkey,
                    event.created_at,
                    event.kind,
                    json.dumps(event.tags, separators=(",", ":")),
                    event.content,
                    event.sig,
                    json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":")),
                ),
            )
            self.connection.commit()
            return cursor.rowcount > 0

    def query(self, filters: list[dict[str, Any]]) -> list[StoredEvent]:
        limit = filter_limit(filters)
        with self.lock:
            rows = self.connection.execute(
                """
                SELECT raw_json
                FROM events
                ORDER BY created_at DESC, id DESC
                """
            ).fetchall()
        matches = []
        for row in rows:
            event = StoredEvent.from_dict(json.loads(row["raw_json"]))
            if matches_any_filter(event, filters):
                matches.append(event)
            if len(matches) >= limit:
                break
        return matches

    def _migrate(self) -> None:
        with self.lock:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                  id TEXT PRIMARY KEY,
                  pubkey TEXT NOT NULL,
                  created_at INTEGER NOT NULL,
                  kind INTEGER NOT NULL,
                  tags_json TEXT NOT NULL,
                  content TEXT NOT NULL,
                  sig TEXT NOT NULL,
                  raw_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_events_created_at ON events (created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_pubkey ON events (pubkey);
                CREATE INDEX IF NOT EXISTS idx_events_kind ON events (kind);
                """
            )
            self.connection.commit()
