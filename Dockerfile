# RuleMemory Cloud -- Cloud Run container.
# Runs the FastAPI app (uvicorn on $PORT) PLUS, as an in-container sidecar, the
# official MongoDB MCP server on localhost:3000. The app's MCP client talks to it
# over loopback, so the partner-track MongoDB MCP integration is live over the
# wire without exposing any extra port to the internet.

# --- Node stage: provides node + npm for the MongoDB MCP server ---
FROM node:20-slim AS node

# --- Final image: Python app + Node runtime + MongoDB MCP server ---
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Bring Node.js over from the node stage and wire up npm/npx.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && npm install -g mongodb-mcp-server@latest \
 && npm cache clean --force

# Python deps first for layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App source.
COPY src ./src
COPY seed ./seed
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

ENV PYTHONPATH=/app/src

EXPOSE 8080

# entrypoint launches the MCP sidecar (if MONGODB_URI is set) then uvicorn.
CMD ["./entrypoint.sh"]
