"""FastAPI HTTP surface for Cloud Run.

Endpoints:
  GET  /                 -> single-page web UI (judge-facing demo console)
  GET  /health           -> liveness + which backends are live vs mock (Cloud Run probe)
  POST /ingest           -> step 1: extract facts from a rules page and remember them
  POST /run              -> full multi-step task, returns the inspectable transcript
  GET  /deadlines        -> deadlines expiring within ?hours=24
  GET  /stale            -> flag stale assumptions
  POST /ask              -> grounded NL answer over EXISTING remembered facts
  GET  /entries          -> dump remembered facts (raw)
  GET  /memory           -> persisted entries with provenance + stale flags (UI)
  GET  /memory/deadlines -> upcoming deadlines within ?hours=N (UI)

The single Cloud Run container listens on $PORT (default 8080).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import __version__
from .config import load_settings
from .factory import build_agent
from .agent import Transcript
from .models import RuleEntry, now_utc
from .store import deadlines_expiring_within
from .ui import INDEX_HTML

settings = load_settings()
agent = build_agent(settings)


def _seed_demo_assumption() -> None:
    """Seed one PRIOR, already-stale assumption ("use Python 2") so a judge's
    very first ingest visibly SUPERSEDES it (the pre-filled example requires
    Python 3.12) and the stale-flag step has a real hit. Idempotent and only
    runs when memory is empty, so it never disturbs an already-populated live
    cluster.
    """
    try:
        if agent.store.count() != 0:
            return
        from datetime import datetime, timezone

        from .models import RuleEntry, SourceRef

        agent.store.upsert(
            RuleEntry(
                entry_id="seed-assumption-001",
                entry_type="rule",
                title="Build requirement: use Python 2",
                summary="Earlier assumption: build the agent runtime on Python 2. "
                "Revisit — likely outdated.",
                confidence=0.5,
                # Already past its stale window relative to the demo clock.
                stale_after_utc=datetime(2026, 6, 9, 0, 0, tzinfo=timezone.utc),
                source_refs=[SourceRef(source_id="prior-session-log")],
                labels=["assumption", "rule"],
            )
        )
    except Exception:  # never let seeding break boot
        pass


_seed_demo_assumption()

app = FastAPI(title="RuleMemory Cloud", version=__version__)


class IngestBody(BaseModel):
    source_text: str
    source_id: str = "src-adhoc"


class RunBody(BaseModel):
    source_text: str
    source_id: str = "src-adhoc"
    question: str = "Which deadlines expire in the next 24 hours?"
    deadline_hours: float = 24.0


class AskBody(BaseModel):
    question: str


def _status() -> dict[str, Any]:
    return {
        "version": __version__,
        "mode": settings.mode,
        "reasoner": agent.reasoner.name,
        "store_backend": agent.store.backend(),
        "mcp_transport": "http" if agent.mcp.live else "mock",
        "gemini_model": settings.gemini_model,
        "gemini_live": settings.gemini_live,
        "mongo_live": settings.mongo_live,
        "mcp_live": settings.mcp_live,
        "entries": agent.store.count(),
    }


def _entry_view(e: RuleEntry, at: datetime) -> dict[str, Any]:
    """Serialize a stored fact for the UI: provenance + computed stale flag."""
    src = e.source_refs[0].source_id if e.source_refs else ""
    return {
        "id": e.entry_id,
        "type": e.entry_type,
        "title": e.title,
        "text": e.summary,
        "status": e.status,
        "confidence": e.confidence,
        "source": src,
        "created_at": e.created_at_utc.isoformat() if e.created_at_utc else None,
        "expires_at": e.expires_at_utc.isoformat() if e.expires_at_utc else None,
        "stale_after": e.stale_after_utc.isoformat() if e.stale_after_utc else None,
        "stale": e.is_stale(at),
    }


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    return INDEX_HTML


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, **_status()}


@app.post("/ingest")
def ingest(body: IngestBody) -> dict[str, Any]:
    t = Transcript(task="ingest")
    entries = agent.ingest(body.source_text, body.source_id, t)
    return {"ingested": len(entries), "transcript": t.to_dict()}


@app.post("/run")
def run(body: RunBody) -> dict[str, Any]:
    t = agent.run_full_task(
        body.source_text, body.source_id, body.question, body.deadline_hours
    )
    return {"status": _status(), "transcript": t.to_dict()}


@app.get("/deadlines")
def deadlines(hours: float = 24.0) -> dict[str, Any]:
    t = Transcript(task="deadlines")
    hits = agent.answer_deadlines(hours, t)
    return {"hours": hours, "deadlines": [e.model_dump(mode="json") for e in hits]}


@app.get("/stale")
def stale() -> dict[str, Any]:
    t = Transcript(task="stale")
    hits = agent.flag_stale(t)
    return {"stale": [e.model_dump(mode="json") for e in hits]}


@app.post("/ask")
def ask(body: AskBody) -> dict[str, Any]:
    t = Transcript(task="ask")
    answer = agent.answer(body.question, t)
    return {"question": body.question, "answer": answer}


@app.get("/entries")
def entries() -> dict[str, Any]:
    return {"entries": [e.model_dump(mode="json") for e in agent.store.all()]}


@app.get("/memory")
def memory() -> dict[str, Any]:
    """Persisted memory for the UI: every stored fact with provenance and a
    freshly-computed stale flag. Demonstrates persistence across sessions."""
    at = now_utc()
    rows = [_entry_view(e, at) for e in agent.store.all()]
    # Stable, useful ordering: deadlines first (soonest first), then the rest.
    rows.sort(key=lambda r: (r["type"] != "deadline", r["expires_at"] or "", r["id"]))
    return {
        "count": len(rows),
        "backend": agent.store.backend(),
        "as_of": at.isoformat(),
        "entries": rows,
    }


@app.get("/memory/deadlines")
def memory_deadlines(hours: float = 24.0) -> dict[str, Any]:
    """Upcoming deadlines within N hours, computed over persisted memory."""
    at = now_utc()
    hits = deadlines_expiring_within(agent.store, hours, at)
    return {
        "hours": hours,
        "as_of": at.isoformat(),
        "count": len(hits),
        "deadlines": [_entry_view(e, at) for e in hits],
    }
