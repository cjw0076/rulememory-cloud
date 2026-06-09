#!/bin/sh
# Start the MongoDB MCP server sidecar on loopback (only when a cluster URI is
# present), then exec the FastAPI app. The MCP server is NOT exposed publicly --
# only the app's $PORT is. The app reaches it at MONGODB_MCP_URL (localhost:3000).
set -e

if [ -n "${MONGODB_URI}" ]; then
  echo ">> starting MongoDB MCP sidecar on 127.0.0.1:3000"
  MDB_MCP_CONNECTION_STRING="${MONGODB_URI}" \
    mongodb-mcp-server --transport http --httpPort 3000 --httpHost 127.0.0.1 \
    >/tmp/mcp_sidecar.log 2>&1 &
fi

exec uvicorn rulememory.app:app --host 0.0.0.0 --port "${PORT}"
