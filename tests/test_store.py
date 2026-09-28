from __future__ import annotations

from spurline.events import StoredEvent
from spurline.store import EventStore
from spurline.filters import matches_any_filter, filter_limit
import pytest


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


@pytest.mark.parametrize("filters", [
    [{}], [], [{"kinds": []}], [{"authors": []}], [{"#p": []}],
    [{"ids": ["000"]}], [{"ids": ["f" * 64]}],
    [{"authors": ["a"]}], [{"authors": ["A"]}],
    [{"authors": ["a" * 64], "kinds": [1059], "since": 4, "until": 16}],
    [{"#p": ["alice"], "#x": ["one"], "limit": 3}],
    [{"#p": ["' OR 1=1 --"]}],
    [{"kinds": [14], "limit": 2}, {"#p": ["alice"], "limit": 5}],
])
def test_sql_filters_match_existing_semantics(tmp_path, filters):
    store = EventStore(tmp_path / "relay.db")
    events = [_event(id=f"{i:064x}", pubkey=("a" if i % 2 else "b") * 64,
        kind=1059 if i % 3 else 14, created_at=i // 2,
        tags=[["p", "alice" if i % 2 else "bob"], ["x", "one"]]) for i in range(40)]
    for event in events:
        store.save(event)
    expected = sorted((e for e in events if matches_any_filter(e, filters)),
                      key=lambda e: (e.created_at, e.id), reverse=True)[:filter_limit(filters)]
    assert store.query(filters) == expected
    store.close()


def test_existing_database_backfills_tags_once(tmp_path):
    path = tmp_path / "relay.db"
    store = EventStore(path)
    event = _event(id="a" * 64, pubkey="b" * 64, kind=1059,
                   created_at=1, tags=[["p", "alice"], ["p", "alice"]])
    store.save(event)
    store.connection.execute("DROP TABLE event_tags")
    store.connection.commit()
    store.close()
    for _ in range(2):
        store = EventStore(path)
        assert store.query([{"#p": ["alice"]}]) == [event]
        assert store.connection.execute("SELECT count(*) FROM event_tags").fetchone()[0] == 1
        store.close()


def test_only_matching_bounded_results_are_deserialized(tmp_path, monkeypatch):
    store = EventStore(tmp_path / "relay.db")
    for i in range(1000):
        store.save(_event(id=f"{i:064x}", pubkey="a" * 64, kind=1059, created_at=i,
                         tags=[["p", "alice" if i < 10 else "bob"]]))
    original = StoredEvent.from_dict
    decoded = []
    def decode(value):
        decoded.append(value)
        return original(value)
    monkeypatch.setattr(StoredEvent, "from_dict", decode)
    result = store.query([{"kinds": [1059], "#p": ["alice"], "limit": 3}])
    assert len(result) == len(decoded) == 3
    assert [event.created_at for event in result] == [9, 8, 7]
    store.close()
