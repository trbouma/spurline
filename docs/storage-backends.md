# Storage backends

Spurline uses SQLite for self-contained local deployments. The relay now calls
the asynchronous `EventStorage` interface (`save`, `query`, and `close`).
`SQLiteStorage` owns thread dispatch; the synchronous `EventStore` maintains the
existing database format, indexes, and migrations. No data conversion or new
configuration is required for this change.

Backend injection is available through `create_app(settings, store=backend)`.
The application owns the injected backend and closes it at lifespan shutdown.
Backend setup currently happens before requests are served.

## Query and failure contract

Queries preserve existing semantics: filters are ORed, results are deduplicated,
same-author deletions hide their targets, and results are ordered by descending
creation time and event ID. The largest requested limit applies to the merged
result, with a default of 500 and a ceiling of 5000.

Requests allow at most 16 filters, 2000 values per filter, 128 partial prefixes
per ID/author field, and 4096 characters per string. Integers must fit a signed
64-bit value. Complete IDs use SQL `IN` expressions. Invalid requests receive
`CLOSED` while their WebSocket remains usable. Backend failures raise
`StorageError`: queries receive `CLOSED`, and publications receive an unsuccessful
`OK` without claiming that a commit definitely did not happen. Connection cleanup
runs even when a handler fails unexpectedly.

SQLite inserts the event, tag entries, and deletion records in one transaction;
failed writes roll back. Its single connection and lock still serialize database
work. Moving that work to threads protects the event loop, but does not provide
parallel database access. Filter limits bound request complexity, not execution
time; query deadlines and bounded concurrency remain future work.

## PostgreSQL path

PostgreSQL is planned, not implemented. A backend should use an async connection
pool, its own schema migrations and indexes, atomic writes, and the same filter
and deletion semantics. Extend `tests/test_storage_contract.py` with a PostgreSQL
factory and run the shared contract against both backends. Production configuration,
pool lifecycle, SQLite data import, load tests, and execution deadlines must be
implemented before enabling it for deployments.

Multiple relay processes also need shared event notifications. The current
broadcast mechanism only reaches clients in the process that receives an event;
shared PostgreSQL storage alone does not provide cross-process delivery. Design
notification delivery, duplicate handling, and reconnect recovery alongside that
deployment model. Service identity binding also currently uses local SQLite state
and will need an explicit shared-state design before multi-instance deployment.
