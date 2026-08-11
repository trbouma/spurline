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
            if event.kind == 5:
                self._record_deletions(event)
            self.connection.commit()
            return cursor.rowcount > 0

    def query(self, filters: list[dict[str, Any]]) -> list[StoredEvent]:
        limit = filter_limit(filters)
        with self.lock:
            rows = self.connection.execute(
                """
                SELECT events.raw_json
                FROM events
                LEFT JOIN deletions
                  ON deletions.event_id = events.id
                 AND deletions.deleted_by = events.pubkey
                WHERE deletions.event_id IS NULL
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

                CREATE TABLE IF NOT EXISTS deletions (
                  event_id TEXT NOT NULL,
                  deleted_by TEXT NOT NULL,
                  deletion_event_id TEXT NOT NULL,
                  deleted_at INTEGER NOT NULL,
                  PRIMARY KEY (event_id, deleted_by)
                );

                CREATE INDEX IF NOT EXISTS idx_deletions_deleted_by
                  ON deletions (deleted_by);
                """
            )
            self.connection.commit()

    def _record_deletions(self, event: StoredEvent) -> None:
        for tag in event.tags:
            if len(tag) < 2 or tag[0] != "e":
                continue
            target_id = tag[1]
            if not _is_lower_hex(target_id, 64) or target_id == event.id:
                continue
            self.connection.execute(
                """
                INSERT OR REPLACE INTO deletions
                  (event_id, deleted_by, deletion_event_id, deleted_at)
                VALUES (?, ?, ?, ?)
                """,
                (target_id, event.pubkey, event.id, event.created_at),
            )


def _is_lower_hex(value: str, length: int) -> bool:
    return len(value) == length and all(char in "0123456789abcdef" for char in value)
