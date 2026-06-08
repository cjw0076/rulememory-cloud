"""Partner integration: the official MongoDB MCP server.

The MongoDB MCP server (https://github.com/mongodb-js/mongodb-mcp-server) exposes
database tools -- find, insert-many, aggregate, count, list-collections, ... --
over MCP. Launched with `--transport http` it serves streamable HTTP on
http://127.0.0.1:3000 by default and reads the cluster connection string from
the env var MDB_MCP_CONNECTION_STRING.

This client speaks the MCP JSON-RPC `tools/call` method to that server. The exact
tool names below are the real ones from the MongoDB MCP docs:
    find, insert-many, aggregate, count, list-collections, list-databases

In mock mode (no MONGODB_MCP_URL) the client returns deterministic mock tool
results so the agent's multi-step transcript still exercises the *same* code
path and tool schema -- proving the integration shape without credentials.

Sources:
  https://www.mongodb.com/docs/mcp-server/tools/
  https://github.com/mongodb-js/mongodb-mcp-server
"""

from __future__ import annotations

import json
from typing import Any

# Real MongoDB MCP server database tool names.
TOOL_FIND = "find"
TOOL_INSERT_MANY = "insert-many"
TOOL_AGGREGATE = "aggregate"
TOOL_COUNT = "count"
TOOL_LIST_COLLECTIONS = "list-collections"


class MongoMcpClient:
    """Thin MCP `tools/call` client for the MongoDB MCP server (HTTP transport).

    When `base_url` is None the client is in mock mode and never touches the
    network; it synthesizes results that mirror the MCP tool result envelope.
    """

    def __init__(self, base_url: str | None, *, database: str, collection: str) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self.database = database
        self.collection = collection
        self._id = 0

    @property
    def live(self) -> bool:
        return self.base_url is not None

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke an MCP tool. Returns a normalized dict:
        {"tool": name, "arguments": {...}, "transport": "...", "result": {...}}
        """
        if not self.live:
            return {
                "tool": name,
                "arguments": arguments,
                "transport": "mock",
                "result": self._mock_result(name, arguments),
            }

        import httpx  # local import; mock mode stays dependency-light

        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(f"{self.base_url}/mcp", json=payload, headers=headers)
            resp.raise_for_status()
            data = _parse_mcp_response(resp.text)
        return {
            "tool": name,
            "arguments": arguments,
            "transport": "http",
            "result": data,
        }

    # ---- convenience wrappers around the real tool names ----

    def insert_many(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
        return self.call_tool(
            TOOL_INSERT_MANY,
            {"database": self.database, "collection": self.collection, "documents": documents},
        )

    def find(self, filter_: dict[str, Any] | None = None, limit: int = 50) -> dict[str, Any]:
        return self.call_tool(
            TOOL_FIND,
            {
                "database": self.database,
                "collection": self.collection,
                "filter": filter_ or {},
                "limit": limit,
            },
        )

    def count(self, filter_: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.call_tool(
            TOOL_COUNT,
            {"database": self.database, "collection": self.collection, "query": filter_ or {}},
        )

    def _mock_result(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == TOOL_INSERT_MANY:
            docs = arguments.get("documents", [])
            return {"insertedCount": len(docs), "acknowledged": True}
        if name == TOOL_COUNT:
            return {"count": 0}
        if name == TOOL_FIND:
            return {"documents": []}
        if name == TOOL_LIST_COLLECTIONS:
            return {"collections": [self.collection]}
        return {"ok": True}


def _parse_mcp_response(text: str) -> dict[str, Any]:
    """Parse either a plain JSON-RPC response or an SSE-framed one."""
    text = text.strip()
    if text.startswith("event:") or "\ndata:" in text or text.startswith("data:"):
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                try:
                    obj = json.loads(line[len("data:"):].strip())
                except json.JSONDecodeError:
                    continue
                return obj.get("result", obj)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}
    return obj.get("result", obj)
