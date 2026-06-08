"""Persistence layer with two interchangeable backends.

`InMemoryStore`  -- zero-dependency dict store for mock/degraded mode.
`MongoStore`     -- real MongoDB Atlas via pymongo, used when MONGODB_URI is set.

Both expose the same small interface so the agent code never branches on mode.
The agent's MongoDB *partner-MCP* story is layered on top via mcp_client.py; the
store here is the durable system of record.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Protocol

from .models import RuleEntry, now_utc


class RuleStore(Protocol):
    def upsert(self, entry: RuleEntry) -> None: ...
    def get(self, entry_id: str) -> RuleEntry | None: ...
    def all(self) -> list[RuleEntry]: ...
    def find(self, *, entry_type: str | None = None, label: str | None = None) -> list[RuleEntry]: ...
    def count(self) -> int: ...
    def backend(self) -> str: ...


class InMemoryStore:
    """Dict-backed store. Survives only for the process lifetime."""

    def __init__(self) -> None:
        self._data: dict[str, RuleEntry] = {}

    def upsert(self, entry: RuleEntry) -> None:
        self._data[entry.entry_id] = entry

    def get(self, entry_id: str) -> RuleEntry | None:
        return self._data.get(entry_id)

    def all(self) -> list[RuleEntry]:
        return list(self._data.values())

    def find(self, *, entry_type: str | None = None, label: str | None = None) -> list[RuleEntry]:
        out: list[RuleEntry] = []
        for e in self._data.values():
            if entry_type and e.entry_type != entry_type:
                continue
            if label and label not in e.labels:
                continue
            out.append(e)
        return out

    def count(self) -> int:
        return len(self._data)

    def backend(self) -> str:
        return "in-memory (mock)"


class MongoStore:
    """MongoDB Atlas store. Imported lazily so mock mode needs no pymongo."""

    def __init__(self, uri: str, db_name: str, collection: str) -> None:
        from pymongo import MongoClient  # local import keeps mock mode dep-free

        self._client = MongoClient(uri, appname="rulememory-cloud")
        self._col = self._client[db_name][collection]
        self._col.create_index("entry_id", unique=True)
        self._col.create_index("entry_type")
        self._col.create_index("expires_at_utc")

    @staticmethod
    def _to_doc(entry: RuleEntry) -> dict:
        doc = entry.model_dump(mode="json")
        doc["_id"] = entry.entry_id
        return doc

    @staticmethod
    def _to_entry(doc: dict) -> RuleEntry:
        doc = {k: v for k, v in doc.items() if k != "_id"}
        return RuleEntry.model_validate(doc)

    def upsert(self, entry: RuleEntry) -> None:
        self._col.replace_one({"_id": entry.entry_id}, self._to_doc(entry), upsert=True)

    def get(self, entry_id: str) -> RuleEntry | None:
        doc = self._col.find_one({"_id": entry_id})
        return self._to_entry(doc) if doc else None

    def all(self) -> list[RuleEntry]:
        return [self._to_entry(d) for d in self._col.find({})]

    def find(self, *, entry_type: str | None = None, label: str | None = None) -> list[RuleEntry]:
        query: dict = {}
        if entry_type:
            query["entry_type"] = entry_type
        if label:
            query["labels"] = label
        return [self._to_entry(d) for d in self._col.find(query)]

    def count(self) -> int:
        return self._col.count_documents({})

    def backend(self) -> str:
        return "MongoDB Atlas (live)"


def deadlines_expiring_within(
    store: RuleStore, hours: float, at: datetime | None = None
) -> list[RuleEntry]:
    at = at or now_utc()
    out = [e for e in store.all() if e.entry_type == "deadline" and e.expires_within(hours, at)]
    out.sort(key=lambda e: e.expires_at_utc or at)
    return out


def stale_entries(store: RuleStore, at: datetime | None = None) -> list[RuleEntry]:
    at = at or now_utc()
    return [e for e in store.all() if e.is_stale(at)]


def seed_store(store: RuleStore, entries: Iterable[RuleEntry]) -> int:
    n = 0
    for e in entries:
        store.upsert(e)
        n += 1
    return n
