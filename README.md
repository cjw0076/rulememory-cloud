# RuleMemory Cloud

> **▶ Live:** https://rulememory-cloud-516399822756.us-central1.run.app  ·  **▶ 60-second demo video:** [https://github.com/cjw0076/rulememory-cloud/releases/download/demo-v1/rulememory_cloud_demo.mp4](https://github.com/cjw0076/rulememory-cloud/releases/download/demo-v1/rulememory_cloud_demo.mp4)


A Gemini-powered, MongoDB-backed agent that turns contest/launch **rules pages**
into auditable, queryable memory — and runs a **multi-step task under user
oversight**, not just chat.

Built for the **Google Cloud Rapid Agent Hackathon** on the **MongoDB partner
track**. Reasoning by **Gemini** (Google Gen AI SDK); persistence + partner MCP
integration by **MongoDB** (Atlas + the official MongoDB MCP server). Hosted on
**Cloud Run**.

## What it does (the multi-step task)

```
ingest a rules page
  -> Gemini extracts structured facts (deadlines, rules, eligibility)
  -> facts written to MongoDB via the MongoDB MCP server (partner integration)
  -> facts persisted to the durable MongoDB store
answer "which deadlines expire in the next 24 hours?"
flag stale assumptions (facts past their stale-after window)
answer a grounded natural-language question over remembered facts
```

Every step emits a typed transcript record, so a human can inspect exactly what
the agent extracted, stored, and decided (user oversight).

## Run the demo NOW (no credentials)

The app runs end-to-end in **mock mode** with zero credentials: a deterministic
local stub stands in for Gemini, and an in-memory store + mock MCP client stand
in for MongoDB. The exact same code switches to live mode when env vars are set.

```bash
cd app
python demo.py            # full multi-step transcript, mock mode
python tests/test_agent.py   # mock-mode end-to-end tests
```

Serve the HTTP surface locally:

```bash
cd app
PYTHONPATH=src uvicorn rulememory.app:app --port 8080
# then:
curl localhost:8080/health
curl -X POST localhost:8080/run -H 'content-type: application/json' \
  -d '{"source_text":"Submission deadline: 2026-06-11 14:00 PDT.","source_id":"s","question":"what expires soon?","deadline_hours":9000}'
```

## Live mode (env-gated)

Each axis flips to live independently when its env vars are present (see
`.env.example`). No secret values live in the repo — only env var names.

| Axis        | Mock (default)        | Live (env set)                                   |
|-------------|-----------------------|--------------------------------------------------|
| Reasoning   | deterministic stub    | Gemini via `GEMINI_API_KEY` or Vertex AI         |
| Persistence | in-memory dict        | MongoDB Atlas via `MONGODB_URI`                  |
| Partner MCP | mock tool results     | MongoDB MCP server via `MONGODB_MCP_URL` (HTTP)  |

Default model id is `gemini-2.5-flash`; set `GEMINI_MODEL` to a Gemini 3 id once
your project has access.

## HTTP endpoints

| Method | Path         | Purpose                                          |
|--------|--------------|--------------------------------------------------|
| GET    | `/`          | landing page (renders so the hosted URL is live) |
| GET    | `/health`    | liveness + live/mock status per backend          |
| POST   | `/ingest`    | extract facts from a rules page, remember them    |
| POST   | `/run`       | full multi-step task, returns the transcript      |
| GET    | `/deadlines` | deadlines expiring within `?hours=24`             |
| GET    | `/stale`     | flag stale assumptions                            |
| POST   | `/ask`       | grounded NL answer over remembered facts          |
| GET    | `/entries`   | dump remembered facts                             |

## Deploy

See [`DEPLOY_STEPS.md`](DEPLOY_STEPS.md) for exact copy-paste founder steps
(gcloud auth, APIs, Atlas cluster, `gcloud run deploy`, video shot list).

## Partner integration: MongoDB MCP server

`src/rulememory/mcp_client.py` speaks MCP `tools/call` to the official
[MongoDB MCP server](https://github.com/mongodb-js/mongodb-mcp-server) over HTTP
transport, using the real tool names (`find`, `insert-many`, `aggregate`,
`count`, `list-collections`). The server reads the cluster string from
`MDB_MCP_CONNECTION_STRING`; this agent points at it via `MONGODB_MCP_URL`.

## License

MIT — see [`LICENSE`](LICENSE).
