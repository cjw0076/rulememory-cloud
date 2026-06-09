"""RuleMemory agent orchestrator.

This is the "moves beyond chat" part required by the hackathon: a multi-step
task pipeline run under user oversight, not a single chat turn. Each step
produces an auditable record that lands in the transcript.

The canonical task:
    ingest(source_text)  -> Gemini extracts facts
                         -> facts written to MongoDB via the partner MCP server
                         -> facts also persisted to the durable store
    answer_deadlines(h)  -> query the store for deadlines expiring within h hours
    flag_stale()         -> surface assumptions past their stale-after window
    answer(question)     -> Gemini grounds an answer on remembered facts

Every method appends typed steps to a shared transcript so the HTTP layer can
return a full, inspectable trace (user oversight).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .config import Settings
from .mcp_client import MongoMcpClient
from .models import RuleEntry, now_utc
from .reasoner import Reasoner, stale_after_default
from .store import (
    RuleStore,
    deadlines_expiring_within,
    stale_entries,
)


@dataclass
class Step:
    step: str
    detail: str
    data: dict[str, Any] = field(default_factory=dict)
    at_utc: str = field(default_factory=lambda: now_utc().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {"step": self.step, "detail": self.detail, "data": self.data, "at_utc": self.at_utc}


@dataclass
class Transcript:
    task: str
    steps: list[Step] = field(default_factory=list)

    def add(self, step: str, detail: str, **data: Any) -> None:
        self.steps.append(Step(step=step, detail=detail, data=data))

    def to_dict(self) -> dict[str, Any]:
        return {"task": self.task, "steps": [s.to_dict() for s in self.steps]}

    def render(self) -> str:
        lines = [f"# Task: {self.task}", ""]
        for i, s in enumerate(self.steps, start=1):
            lines.append(f"[{i}] {s.step} :: {s.detail}")
            for k, v in s.data.items():
                lines.append(f"      {k} = {v}")
        return "\n".join(lines)


class RuleMemoryAgent:
    def __init__(self, settings: Settings, store: RuleStore, reasoner: Reasoner,
                 mcp: MongoMcpClient) -> None:
        self.settings = settings
        self.store = store
        self.reasoner = reasoner
        self.mcp = mcp

    # --- step 1: ingest a rules page and remember its facts ---
    def ingest(self, source_text: str, source_id: str, transcript: Transcript,
               at: datetime | None = None) -> list[RuleEntry]:
        at = at or now_utc()
        transcript.add(
            "ingest.start",
            f"reasoner={self.reasoner.name} source_id={source_id} chars={len(source_text)}",
        )
        entries = self.reasoner.extract_facts(source_text, source_id)
        transcript.add(
            "extract.facts",
            f"Gemini extracted {len(entries)} candidate fact(s)",
            entry_ids=[e.entry_id for e in entries],
            types=[e.entry_type for e in entries],
        )

        # Tag non-deadline facts with a stale-after window (relative to ingest
        # time) so assumptions decay but freshly-ingested facts are not stale yet.
        for e in entries:
            e.created_at_utc = at
            if e.stale_after_utc is None and e.entry_type != "deadline":
                e.stale_after_utc = stale_after_default(24, at)

        # Partner MCP: write the facts to MongoDB through the MongoDB MCP server.
        # Pin _id to entry_id so the authoritative store.upsert below REPLACES the
        # same document (idempotent) instead of creating a second doc that would
        # violate the unique entry_id index when the MCP transport is live.
        docs = []
        for e in entries:
            d = e.model_dump(mode="json")
            d["_id"] = e.entry_id
            docs.append(d)
        mcp_res = self.mcp.insert_many(docs)
        transcript.add(
            "mcp.insert-many",
            f"MongoDB MCP tool '{mcp_res['tool']}' via {mcp_res['transport']} transport",
            arguments_summary={
                "database": self.mcp.database,
                "collection": self.mcp.collection,
                "documents": len(docs),
            },
            result=mcp_res["result"],
        )

        # Durable system of record (pymongo direct or in-memory).
        for e in entries:
            self.store.upsert(e)
        transcript.add(
            "store.upsert",
            f"persisted to {self.store.backend()} (total={self.store.count()})",
        )
        return entries

    # --- step 2: answer "what deadlines expire within N hours" ---
    def answer_deadlines(self, hours: float, transcript: Transcript,
                         at: datetime | None = None) -> list[RuleEntry]:
        at = at or now_utc()
        hits = deadlines_expiring_within(self.store, hours, at)
        transcript.add(
            "query.deadlines",
            f"deadlines expiring within {hours}h of {at.isoformat()}",
            count=len(hits),
            entry_ids=[e.entry_id for e in hits],
        )
        return hits

    # --- step 3: flag stale assumptions ---
    def flag_stale(self, transcript: Transcript, at: datetime | None = None) -> list[RuleEntry]:
        at = at or now_utc()
        stale = stale_entries(self.store, at)
        # Auto-mark them stale in the record (under oversight; reversible).
        for e in stale:
            if e.status == "active":
                e.status = "stale"
                self.store.upsert(e)
        transcript.add(
            "flag.stale",
            f"{len(stale)} fact(s) past stale-after window",
            entry_ids=[e.entry_id for e in stale],
        )
        return stale

    # --- step 4: grounded natural-language answer ---
    def answer(self, question: str, transcript: Transcript) -> str:
        entries = self.store.all()
        context = "\n".join(
            f"- {e.entry_id} [{e.entry_type}/{e.status}] {e.title}: {e.summary}"
            + (f" (expires {e.expires_at_utc.isoformat()})" if e.expires_at_utc else "")
            for e in entries
        )
        answer = self.reasoner.summarize(question, context)
        transcript.add(
            "answer.summarize",
            f"grounded answer over {len(entries)} fact(s) via {self.reasoner.name}",
            question=question,
        )
        return answer

    # --- full canonical multi-step run, for the demo and the /run endpoint ---
    def run_full_task(self, source_text: str, source_id: str, question: str,
                      deadline_hours: float = 24.0,
                      at: datetime | None = None) -> Transcript:
        t = Transcript(task="ingest rules -> store via MongoDB MCP -> "
                            "query deadlines -> flag stale -> answer")
        self.ingest(source_text, source_id, t, at=at)
        self.answer_deadlines(deadline_hours, t, at=at)
        self.flag_stale(t, at=at)
        ans = self.answer(question, t)
        t.add("done", "final answer ready", answer=ans)
        return t
