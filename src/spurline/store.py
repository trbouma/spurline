from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .events import StoredEvent
from .filters import filter_limit, validate_filter_bounds


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
        with self.lock, self.connection:
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
            if cursor.rowcount > 0:
                self._index_tags(event.id, event.tags)
            if event.kind == 5:
                self._record_deletions(event)
            self.connection.commit()
            return cursor.rowcount > 0

    def query(self, filters: list[dict[str, Any]]) -> list[StoredEvent]:
        validate_filter_bounds(filters)
        limit = filter_limit(filters)
        matches: dict[str, StoredEvent] = {}
        with self.lock:
            for relay_filter in filters:
                clauses = ["NOT EXISTS (SELECT 1 FROM deletions d WHERE d.event_id = events.id AND d.deleted_by = events.pubkey)"]
                parameters: list[Any] = []
                for key, column in (("ids", "id"), ("authors", "pubkey")):
                    if key not in relay_filter:
                        continue
                    prefixes = relay_filter[key]
                    conditions = []
                    exact = [prefix for prefix in prefixes if len(prefix) == 64]
                    if exact:
                        conditions.append(f"{column} IN (" + ",".join("?" for _ in exact) + ")")
                        parameters.extend(exact)
                    for prefix in prefixes:
                        if len(prefix) == 64:
                            continue
                        else:
                            conditions.append(f"({column} >= ? AND {column} < ?)")
                            parameters.extend([prefix, prefix + "\U0010ffff"])
                    clauses.append("(" + " OR ".join(conditions) + ")" if conditions else "0")
                if "kinds" in relay_filter:
                    values = relay_filter["kinds"]
                    clauses.append("kind IN (" + ",".join("?" for _ in values) + ")")
                    parameters.extend(values)
                for key, operator in (("since", ">="), ("until", "<=")):
                    if key in relay_filter:
                        clauses.append(f"created_at {operator} ?")
                        parameters.append(relay_filter[key])
                for key, values in relay_filter.items():
                    if key.startswith("#"):
                        clauses.append("id IN (SELECT event_id FROM event_tags WHERE name = ? AND value IN (" + ",".join("?" for _ in values) + "))")
                        parameters.extend([key[1:], *values])
                rows = self.connection.execute(
                    "SELECT raw_json FROM events WHERE " + " AND ".join(clauses)
                    + " ORDER BY created_at DESC, id DESC LIMIT ?",
                    [*parameters, limit],
                )
                for row in rows:
                    event = StoredEvent.from_dict(json.loads(row["raw_json"]))
                    matches[event.id] = event
        return sorted(matches.values(), key=lambda event: (event.created_at, event.id), reverse=True)[:limit]

    def _index_tags(self, event_id: str, tags: list[list[str]]) -> None:
        self.connection.executemany(
            "INSERT OR IGNORE INTO event_tags (event_id, name, value) VALUES (?, ?, ?)",
            [(event_id, tag[0], tag[1]) for tag in tags if len(tag) >= 2],
        )

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
            # Backfill once, transactionally, so existing relay data is retained.
            # A failed migration rolls back the table and is retried next startup.
            with self.connection:
                self.connection.execute("BEGIN")
                exists = self.connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='event_tags'"
                ).fetchone()
                self.connection.execute(
                    "CREATE TABLE IF NOT EXISTS event_tags (event_id TEXT NOT NULL, name TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (name, value, event_id))"
                )
                if not exists:
                    for row in self.connection.execute("SELECT id, tags_json FROM events"):
                        self._index_tags(row["id"], json.loads(row["tags_json"]))
                self.connection.execute("CREATE INDEX IF NOT EXISTS idx_events_order ON events(created_at DESC, id DESC)")
                self.connection.execute("CREATE INDEX IF NOT EXISTS idx_events_kind_order ON events(kind, created_at DESC, id DESC)")
                self.connection.execute("CREATE INDEX IF NOT EXISTS idx_events_author_order ON events(pubkey, created_at DESC, id DESC)")
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
