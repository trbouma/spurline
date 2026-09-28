"""Run this contract against each new backend before enabling it."""

import asyncio

import pytest

from spurline.events import StoredEvent
from spurline.storage import SQLiteStorage


@pytest.fixture(params=[SQLiteStorage], ids=["sqlite"])
def storage_factory(request, tmp_path):
    return lambda: request.param(tmp_path / "contract.sqlite3")


def test_storage_contract(storage_factory):
    async def run():
        store = storage_factory()
        event = StoredEvent(id="a" * 64, pubkey="b" * 64, kind=1,
                            created_at=10, tags=[["p", "recipient"]], content="test", sig="f" * 128)
        deletion = StoredEvent(id="c" * 64, pubkey=event.pubkey, kind=5,
                               created_at=11, tags=[["e", event.id]], content="", sig="f" * 128)
        try:
            assert await store.save(event)
            assert not await store.save(event)
            assert await store.query([{"#p": ["recipient"]}, {"authors": ["b"]}]) == [event]
            assert await store.query([{"ids": [f"{i:064x}" for i in range(1000)] + [event.id]}]) == [event]
            assert await store.save(deletion)
            assert await store.query([{"kinds": [1]}]) == []
        finally:
            await store.close()
        store = storage_factory()
        try:
            assert await store.query([{}]) == [deletion]
        finally:
            await store.close()
    asyncio.run(run())
