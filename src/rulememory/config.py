"""Runtime configuration, fully env-var driven.

Two axes of "live vs mock":
  * Reasoning  -> Gemini (live) or a deterministic local stub (mock)
  * Persistence -> MongoDB Atlas (live) or an in-memory store (mock)

Each axis flips to LIVE only when its credential env vars are present, so the
app boots and runs end-to-end with zero credentials (degraded/mock mode) and
upgrades automatically once the founder injects secrets via Cloud Run env vars.

No secret VALUES live in this file -- only the NAMES of the env vars to read.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- Gemini (reasoning) ---
    # google-genai supports two backends. We default to the Gemini Developer
    # API via GEMINI_API_KEY; set GOOGLE_GENAI_USE_VERTEXAI=true to route
    # through Vertex AI (needs GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_LOCATION
    # and ADC, i.e. the Cloud Run service account).
    gemini_api_key: str | None
    gemini_model: str
    use_vertexai: bool
    gcp_project: str | None
    gcp_location: str

    # --- MongoDB (persistence) ---
    # MONGODB_URI is the standard SRV connection string from Atlas.
    mongodb_uri: str | None
    mongodb_db: str
    mongodb_collection: str

    # --- MongoDB MCP server (partner integration) ---
    # The official MongoDB MCP server is reachable over HTTP when launched with
    # `--transport http`. We point at it via MONGODB_MCP_URL. When unset, the
    # agent uses the direct pymongo store but still emits MCP-shaped tool calls
    # in its transcript so the partner-integration story stays faithful.
    mongodb_mcp_url: str | None

    # --- HTTP surface ---
    port: int

    @property
    def gemini_live(self) -> bool:
        if self.use_vertexai:
            return bool(self.gcp_project)
        return bool(self.gemini_api_key)

    @property
    def mongo_live(self) -> bool:
        return bool(self.mongodb_uri)

    @property
    def mcp_live(self) -> bool:
        return bool(self.mongodb_mcp_url)

    @property
    def mode(self) -> str:
        return "live" if (self.gemini_live and self.mongo_live) else "mock"


def load_settings() -> Settings:
    return Settings(
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        use_vertexai=_truthy(os.environ.get("GOOGLE_GENAI_USE_VERTEXAI")),
        gcp_project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        gcp_location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        mongodb_uri=os.environ.get("MONGODB_URI"),
        mongodb_db=os.environ.get("MONGODB_DB", "rulememory"),
        mongodb_collection=os.environ.get("MONGODB_COLLECTION", "entries"),
        mongodb_mcp_url=os.environ.get("MONGODB_MCP_URL"),
        port=int(os.environ.get("PORT", "8080")),
    )
