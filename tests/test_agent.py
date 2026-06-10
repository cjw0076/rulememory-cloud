"""Mock-mode end-to-end test for the RuleMemory agent.

Run from app/:  python -m pytest tests/   (or: python tests/test_agent.py)
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rulememory.config import Settings  # noqa: E402
from rulememory.factory import build_agent  # noqa: E402

RULES = """\
Submission deadline: 2026-06-11 14:00 PDT.
Build requirement: projects must use Gemini and integrate a partner MCP server.
Eligibility: participants must be above the legal age of majority.
"""


def _mock_settings() -> Settings:
    # All credential fields None/empty -> mock mode on every axis.
    return Settings(
        gemini_api_key=None, gemini_model="gemini-2.5-flash", use_vertexai=False,
        gcp_project=None, gcp_location="us-central1",
        mongodb_uri=None, mongodb_db="rulememory", mongodb_collection="entries",
        mongodb_mcp_url=None, port=8080,
    )


def test_full_task_mock_mode():
    settings = _mock_settings()
    assert settings.mode == "mock"
    agent = build_agent(settings)

    fixed_now = datetime(2026, 6, 11, 5, 0, tzinfo=timezone.utc)  # ~24h before deadline
    t = agent.run_full_task(RULES, "test-src", "what expires?", deadline_hours=30.0, at=fixed_now)

    steps = {s.step for s in t.steps}
    # Multi-step proof: all stages present.
    for expected in {"ingest.start", "extract.facts", "mcp.insert-many",
                     "store.upsert", "query.deadlines", "flag.stale",
                     "answer.summarize", "done"}:
        assert expected in steps, f"missing step {expected}"

    # Facts were extracted and stored.
    assert agent.store.count() >= 2
    # A deadline was found within the window.
    dl = [s for s in t.steps if s.step == "query.deadlines"][0]
    assert dl.data["count"] >= 1
    # MCP insert-many was exercised with the right tool name.
    mcp = [s for s in t.steps if s.step == "mcp.insert-many"][0]
    assert mcp.data["result"]["insertedCount"] >= 2


def test_stale_flagging():
    agent = build_agent(_mock_settings())
    # Ingest at T0; non-deadline facts get a 24h stale window from T0.
    t0 = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    from rulememory.agent import Transcript
    tr = Transcript(task="x")
    agent.ingest(RULES, "s", tr, at=t0)
    for e in agent.store.all():
        if e.entry_type != "deadline":
            assert e.stale_after_utc is not None
    # Two days later everything non-deadline is stale.
    later = datetime(2026, 6, 5, 0, 0, tzinfo=timezone.utc)
    stale = agent.flag_stale(Transcript(task="y"), at=later)
    assert len(stale) >= 1


def test_conflict_supersede():
    """A later ingest whose fact shares a topic-key with an existing active
    fact marks the older one superseded and records it in the transcript."""
    from rulememory.agent import Transcript
    from rulememory.models import RuleEntry, SourceRef

    agent = build_agent(_mock_settings())
    # Prior assumption: "use Python 2".
    agent.store.upsert(RuleEntry(
        entry_id="old-001", entry_type="rule",
        title="Build requirement: use Python 2",
        summary="Earlier assumption: build the runtime on Python 2.",
        source_refs=[SourceRef(source_id="prior")],
    ))
    new_rules = "Build requirement: projects must use Python 3.12 for the runtime."
    tr = Transcript(task="x")
    agent.ingest(new_rules, "newsrc", tr)

    # The prior fact is now superseded.
    old = agent.store.get("old-001")
    assert old is not None and old.status == "superseded"
    # The conflict step recorded the supersession.
    conf = [s for s in tr.steps if s.step == "flag.conflict"][0]
    assert len(conf.data["supersessions"]) >= 1
    rec = conf.data["supersessions"][0]
    assert rec["old"] == "old-001"


def _client():
    # Import here so the app-level startup seed runs in mock mode (no creds).
    from fastapi.testclient import TestClient
    from rulememory import app as app_module
    return TestClient(app_module.app), app_module.agent


def test_http_endpoints_mock_mode():
    client, agent = _client()

    # UI is served at / and is a full HTML page.
    r = client.get("/")
    assert r.status_code == 200
    assert "RuleMemory Cloud" in r.text
    assert "Run agent" in r.text

    # Health reports mock mode and backend status.
    h = client.get("/health").json()
    assert h["ok"] is True
    assert h["mode"] == "mock"

    # Startup seeded the prior "use Python 2" assumption.
    mem = client.get("/memory").json()
    assert mem["count"] >= 1
    assert any("python 2" in e["text"].lower() or "python 2" in e["title"].lower()
               for e in mem["entries"])
    # Every memory row carries provenance + a computed stale flag.
    for e in mem["entries"]:
        assert "stale" in e and "source" in e and "id" in e

    # Run the full task; the seeded Python 2 assumption gets superseded.
    run = client.post("/run", json={
        "source_text": "Submission deadline: 2099-01-01 00:00.\n"
                       "Build requirement: projects must use Python 3.12.",
        "source_id": "ui-src",
        "question": "what must we use?",
        "deadline_hours": 1000000,
    }).json()
    steps = {s["step"] for s in run["transcript"]["steps"]}
    assert "flag.conflict" in steps

    # /memory/deadlines surfaces the far-future deadline within a huge window.
    dl = client.get("/memory/deadlines", params={"hours": 10_000_000}).json()
    assert dl["count"] >= 1

    # /ask answers over EXISTING memory without re-ingesting.
    before = client.get("/health").json()["entries"]
    ask = client.post("/ask", json={"question": "what is remembered?"}).json()
    after = client.get("/health").json()["entries"]
    assert before == after  # no new facts created by /ask
    assert isinstance(ask["answer"], str) and ask["answer"]


if __name__ == "__main__":
    test_full_task_mock_mode()
    test_stale_flagging()
    test_conflict_supersede()
    test_http_endpoints_mock_mode()
    print("OK: all mock-mode tests passed")
