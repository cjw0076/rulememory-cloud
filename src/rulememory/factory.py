"""Wiring: build a fully-configured agent from Settings, choosing live vs mock
backends per axis. Used by both the HTTP app and the CLI demo so they share one
construction path.
"""

from __future__ import annotations

from .agent import RuleMemoryAgent
from .config import Settings, load_settings
from .mcp_client import MongoMcpClient
from .reasoner import GeminiReasoner, MockReasoner, Reasoner
from .store import InMemoryStore, MongoStore, RuleStore


def build_reasoner(settings: Settings) -> Reasoner:
    if settings.gemini_live:
        try:
            return GeminiReasoner(
                settings.gemini_model,
                api_key=settings.gemini_api_key,
                use_vertexai=settings.use_vertexai,
                project=settings.gcp_project,
                location=settings.gcp_location,
            )
        except Exception:  # missing SDK / bad creds -> degrade, never crash boot
            return MockReasoner()
    return MockReasoner()


def build_store(settings: Settings) -> RuleStore:
    if settings.mongo_live:
        try:
            return MongoStore(
                settings.mongodb_uri,  # type: ignore[arg-type]
                settings.mongodb_db,
                settings.mongodb_collection,
            )
        except Exception as e:  # surface why we degraded (no secrets logged)
            import sys, traceback
            print(f"[store] MongoStore init failed -> in-memory fallback: "
                  f"{type(e).__name__}: {str(e)[:300]}", file=sys.stderr, flush=True)
            traceback.print_exc()
            return InMemoryStore()
    return InMemoryStore()


def build_mcp(settings: Settings) -> MongoMcpClient:
    return MongoMcpClient(
        settings.mongodb_mcp_url,
        database=settings.mongodb_db,
        collection=settings.mongodb_collection,
    )


def build_agent(settings: Settings | None = None) -> RuleMemoryAgent:
    settings = settings or load_settings()
    return RuleMemoryAgent(
        settings=settings,
        store=build_store(settings),
        reasoner=build_reasoner(settings),
        mcp=build_mcp(settings),
    )
