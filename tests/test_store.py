from __future__ import annotations

from spurline.events import StoredEvent
from spurline.store import EventStore


def test_same_author_deletion_hides_target_event(tmp_path) -> None:
    store = EventStore(tmp_path / "spurline.sqlite3")
    event = _event(id="1" * 64, pubkey="a" * 64, kind=37375, created_at=100)
    deletion = _event(
        id="2" * 64,
        pubkey=event.pubkey,
        kind=5,
        created_at=101,
        tags=[["e", event.id]],
        content="delete record",
    )

    assert store.save(event)
    assert store.query([{"kinds": [37375]}]) == [event]

    assert store.save(deletion)
    assert store.query([{"kinds": [37375]}]) == []
    assert store.query([{"kinds": [5]}]) == [deletion]

    store.close()


def test_other_author_deletion_does_not_hide_target_event(tmp_path) -> None:
    store = EventStore(tmp_path / "spurline.sqlite3")
    event = _event(id="3" * 64, pubkey="a" * 64, kind=37375, created_at=100)
    deletion = _event(
        id="4" * 64,
        pubkey="b" * 64,
        kind=5,
        created_at=101,
        tags=[["e", event.id]],
        content="delete record",
    )

    store.save(event)
    store.save(deletion)

    assert store.query([{"kinds": [37375]}]) == [event]

    store.close()


def _event(
    *,
    id: str,
    pubkey: str,
    kind: int,
    created_at: int,
    tags: list[list[str]] | None = None,
    content: str = "",
) -> StoredEvent:
    return StoredEvent(
        id=id,
        pubkey=pubkey,
        created_at=created_at,
        kind=kind,
        tags=tags or [["d", "record"]],
        content=content,
        sig="f" * 128,
    )
