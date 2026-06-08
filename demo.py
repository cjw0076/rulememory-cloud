#!/usr/bin/env python3
"""RuleMemory Cloud -- local mock-mode demo.

Runs the full multi-step task with zero credentials and prints the transcript,
proving: ingest rules -> Gemini extract -> store via MongoDB MCP ->
query deadlines -> flag stale -> grounded answer.

Usage:
    python app/demo.py                 # uses the bundled rules snapshot
    python app/demo.py path/to/file    # ingest your own source text

With creds present (GEMINI_API_KEY + MONGODB_URI, optionally MONGODB_MCP_URL)
the SAME script runs in live mode automatically.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# Make `rulememory` importable whether run from repo root or app/.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from rulememory.config import load_settings  # noqa: E402
from rulememory.factory import build_agent  # noqa: E402

SEED = Path(__file__).resolve().parent / "seed" / "rapid_rules_snapshot.txt"


def main() -> int:
    settings = load_settings()
    agent = build_agent(settings)

    src_path = Path(sys.argv[1]) if len(sys.argv) > 1 else SEED
    source_text = src_path.read_text(encoding="utf-8")
    source_id = src_path.stem

    print("=" * 70)
    print(f"RuleMemory Cloud demo  |  mode={settings.mode}  "
          f"reasoner={agent.reasoner.name}  store={agent.store.backend()}  "
          f"mcp={'http' if agent.mcp.live else 'mock'}")
    print("=" * 70)

    # Fix "now" so the deadline/stale logic is deterministic for the demo.
    # 2026-06-10 18:00 UTC == 11:00 PDT on 2026-06-10, i.e. ~20h before the
    # 2026-06-11 14:00 PDT submission deadline -> it shows up in the 24h window.
    fixed_now = datetime(2026, 6, 10, 18, 0, tzinfo=timezone.utc)

    # Seed one PRIOR assumption whose stale-after window has already passed, so
    # the flag-stale step has a realistic non-trivial hit (an old fact decays
    # while freshly-ingested facts stay fresh).
    from rulememory.models import RuleEntry, SourceRef
    agent.store.upsert(RuleEntry(
        entry_id="prior-001",
        entry_type="preference",
        title="Assumed partner track = GitLab",
        summary="Earlier session assumed the GitLab track; revisit before submit.",
        confidence=0.6,
        stale_after_utc=datetime(2026, 6, 9, 0, 0, tzinfo=timezone.utc),  # already past
        source_refs=[SourceRef(source_id="operator-log")],
        labels=["assumption"],
    ))

    transcript = agent.run_full_task(
        source_text=source_text,
        source_id=source_id,
        question="Which deadlines expire in the next 24 hours, and what must we "
                 "use to build the agent?",
        deadline_hours=24.0,
        at=fixed_now,
    )

    print(transcript.render())
    print("=" * 70)
    print(f"demo evaluated as-of (fixed): {fixed_now.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
