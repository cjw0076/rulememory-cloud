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


if __name__ == "__main__":
    test_full_task_mock_mode()
    test_stale_flagging()
    print("OK: all mock-mode tests passed")
