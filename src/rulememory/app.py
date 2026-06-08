"""FastAPI HTTP surface for Cloud Run.

Endpoints:
  GET  /            -> tiny human landing page (so the hosted URL renders)
  GET  /health      -> liveness + which backends are live vs mock (Cloud Run probe)
  POST /ingest      -> step 1: extract facts from a rules page and remember them
  POST /run         -> full multi-step task, returns the inspectable transcript
  GET  /deadlines   -> deadlines expiring within ?hours=24
  GET  /stale       -> flag stale assumptions
  POST /ask         -> grounded NL answer over remembered facts
  GET  /entries     -> dump remembered facts

The single Cloud Run container listens on $PORT (default 8080).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import __version__
from .config import load_settings
from .factory import build_agent
from .agent import Transcript

settings = load_settings()
agent = build_agent(settings)

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


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    s = _status()
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>RuleMemory Cloud</title></head><body style="font-family:system-ui;max-width:42rem;margin:3rem auto">
<h1>RuleMemory Cloud</h1>
<p>Gemini-powered, MongoDB-backed contest-facts agent (MongoDB partner track).</p>
<p><b>mode:</b> {s['mode']} &middot; <b>reasoner:</b> {s['reasoner']} &middot;
<b>store:</b> {s['store_backend']} &middot; <b>mcp:</b> {s['mcp_transport']}</p>
<p>Try <code>GET /health</code>, <code>POST /run</code>, <code>GET /deadlines?hours=24</code>.</p>
</body></html>"""


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
