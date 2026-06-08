"""RuleMemory data model.

Mirrors docs/rule_memory_schema.json from the reused Qwen RuleMemory asset, kept
deliberately small so it round-trips cleanly into a single MongoDB collection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

EntryType = Literal[
    "rule",
    "deadline",
    "eligibility",
    "preference",
    "decision",
    "evidence",
]

EntryStatus = Literal["active", "stale", "invalidated", "superseded"]


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class SourceRef(BaseModel):
    source_id: str
    section_hint: str = ""
    captured_at_utc: datetime = Field(default_factory=now_utc)
    quote: str | None = None


class RuleEntry(BaseModel):
    entry_id: str
    entry_type: EntryType
    title: str
    summary: str
    confidence: float = 0.8
    status: EntryStatus = "active"
    created_at_utc: datetime = Field(default_factory=now_utc)
    # When present, the fact is considered stale after this instant. Deadlines
    # carry the actual deadline timestamp here so "expires in 24h" queries work.
    expires_at_utc: datetime | None = None
    # Independent of expiry: a fact derived from a source page that may drift.
    stale_after_utc: datetime | None = None
    source_refs: list[SourceRef] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)

    def is_stale(self, at: datetime | None = None) -> bool:
        at = at or now_utc()
        if self.status in {"invalidated", "superseded"}:
            return True
        if self.stale_after_utc is not None and at >= self.stale_after_utc:
            return True
        return False

    def expires_within(self, hours: float, at: datetime | None = None) -> bool:
        if self.expires_at_utc is None:
            return False
        at = at or now_utc()
        delta_hours = (self.expires_at_utc - at).total_seconds() / 3600.0
        return 0 <= delta_hours <= hours
