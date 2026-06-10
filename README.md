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

Serve the HTTP surface + web UI locally:

```bash
cd app
PYTHONPATH=src uvicorn rulememory.app:app --port 8080
# then open the console UI in a browser:
open http://localhost:8080/
# or hit the JSON endpoints directly:
curl localhost:8080/health
curl localhost:8080/memory
curl 'localhost:8080/memory/deadlines?hours=24'
curl -X POST localhost:8080/ask -H 'content-type: application/json' \
  -d '{"question":"what build requirements are remembered?"}'
curl -X POST localhost:8080/run -H 'content-type: application/json' \
  -d '{"source_text":"Submission deadline: 2026-06-11 14:00 PDT.","source_id":"s","question":"what expires soon?","deadline_hours":9000}'
```

## Web UI (judge-facing console)

`GET /` serves a single-page agent console (vanilla HTML/CSS/JS embedded in
`src/rulememory/ui.py` — no framework, no build step, shipped inside the same
Cloud Run image). From the browser a user can:

- **Paste/edit a rules document + a question** and set the deadline window, then
  click **Run agent** (it pre-fills a compelling example in one click).
- **Watch the multi-step plan animate** from the *real* `/run` transcript:
  `ingest → extract.facts (Gemini) → mcp.insert-many (MongoDB MCP, transport
  shown) → store.upsert (MongoDB) → flag.conflict → query.deadlines →
  flag.stale → answer.summarize`, with each step's detail and raw data.
- **See the grounded answer** with cited fact ids highlighted as chips.
- **Inspect persisted memory** as a table (id, type, fact, source, expires,
  status) via `GET /memory`, including a live **stale** flag.
- **Ask the existing memory** (no re-ingest) via `POST /ask`, proving
  persistence across sessions.
- See a **live status badge** from `/health` (mode, Gemini, MongoDB, MCP).

The pre-filled example is a Rapid Agent rules snapshot with a near-term
submission deadline **and** a `Python 3.12` build requirement that visibly
**supersedes** a stale `use Python 2` assumption already in memory (seeded at
startup, only when memory is empty). So a judge sees deadline-tracking, stale
decay, and conflict/supersede surfacing in a single click.

**Screenshot (what the page shows):** a dark, Google-branded console. Left
panel: editable *Rules document* + *Question* + *Deadline window* with a
**▶ Run agent** button. Top-right: status chips reading `mode: live`, green dots
for `Gemini`, `MongoDB`, `MCP`. Center-right: the animated **Agent plan** —
eight numbered cards lighting up in sequence, each green-checked when done,
the `mcp.insert-many` card showing `insert-many via http transport`. Below it
the **Grounded answer** card with `rapid-rules-002`-style fact ids as blue
cited chips. Bottom: the **Persisted memory** table with the superseded
`use Python 2` row tagged `superseded`/`stale` and the new active facts, plus an
**Ask the existing memory** box.

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

| Method | Path                 | Purpose                                          |
|--------|----------------------|--------------------------------------------------|
| GET    | `/`                  | **web UI** — single-page agent console           |
| GET    | `/health`            | liveness + live/mock status per backend          |
| POST   | `/ingest`            | extract facts from a rules page, remember them   |
| POST   | `/run`               | full multi-step task, returns the transcript     |
| GET    | `/deadlines`         | deadlines expiring within `?hours=24`            |
| GET    | `/stale`             | flag stale assumptions                           |
| POST   | `/ask`               | grounded NL answer over EXISTING remembered facts|
| GET    | `/entries`           | dump remembered facts (raw)                      |
| GET    | `/memory`            | persisted facts + provenance + live stale flags  |
| GET    | `/memory/deadlines`  | upcoming deadlines within `?hours=N`             |

`/memory`, `/memory/deadlines`, and `POST /ask` are what the web UI calls;
`/ask` answers over already-persisted memory (no re-ingest), demonstrating
persistence across sessions. Ingest now also surfaces **conflicts**: a new fact
that supersedes a prior one on the same topic (e.g. `Python 3.12` superseding
`use Python 2`) emits a `flag.conflict` transcript step and marks the old fact
`superseded`.

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
