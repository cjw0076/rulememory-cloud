# DEPLOY_STEPS — RuleMemory Cloud (founder, copy-paste, in order)

Everything below the line **requires founder credentials** (the agent could not
do these). Do them in order. Total time ~30–45 min if accounts are new.

> The app already runs in mock mode with no credentials. These steps switch it
> to live (real Gemini + real MongoDB Atlas) and host it on Cloud Run.

---

## 0. Prereqs (install once)

- Install the gcloud CLI: https://cloud.google.com/sdk/docs/install
- Have a Google account that can create a Google Cloud project + enable billing.
- Have (or create) a MongoDB Atlas account: https://www.mongodb.com/cloud/atlas/register

---

## 1. Authenticate Google Cloud

```bash
gcloud auth login
gcloud auth application-default login   # ADC, used by Vertex AI path
```

## 2. Create / select a project and set it

```bash
# Create new (skip if you already have one):
gcloud projects create rulememory-cloud-$RANDOM --name="RuleMemory Cloud"
# List to find the exact PROJECT_ID:
gcloud projects list

export PROJECT_ID=<paste-your-project-id>
gcloud config set project "$PROJECT_ID"
```

## 3. Enable billing (required for Cloud Run + Gemini)

```bash
gcloud billing accounts list                       # copy the ACCOUNT_ID
gcloud billing projects link "$PROJECT_ID" \
  --billing-account=<ACCOUNT_ID>
```
(If no billing account exists, create one in the console:
https://console.cloud.google.com/billing — new accounts get free credits.)

## 4. Enable the required APIs

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com \
  generativelanguage.googleapis.com
```

## 5. Get a Gemini credential (pick ONE path)

**Path A — Gemini API key (simplest):**
1. Open https://aistudio.google.com/app/apikey
2. Create an API key in your project, copy it.
```bash
export GEMINI_API_KEY=<paste-key>
```

**Path B — Vertex AI (no key; uses the Cloud Run service account):**
- Skip the key. The deploy script auto-sets `GOOGLE_GENAI_USE_VERTEXAI=true`
  with your project + region. Ensure the Cloud Run service account has the
  `roles/aiplatform.user` role (default Compute SA usually does on a billing
  project).

> The hackathon references **Gemini 3**. Default model id is `gemini-2.5-flash`.
> If your project has Gemini 3 access, set:
> `export GEMINI_MODEL=<gemini-3 model id>` before deploying.

## 6. Create a free MongoDB Atlas cluster + connection string

1. https://cloud.mongodb.com → **Build a Database** → **M0 (Free)** → pick a
   cloud/region close to your Cloud Run region → Create.
2. **Database Access** → Add New Database User → username + password (save them).
3. **Network Access** → Add IP Address → **Allow access from anywhere**
   `0.0.0.0/0` (simplest for Cloud Run; tighten later).
4. **Database → Connect → Drivers** → copy the SRV string. It looks like:
   `mongodb+srv://USER:PASS@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority`
```bash
export MONGODB_URI='mongodb+srv://USER:PASS@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority'
```
   (URL-encode special characters in the password.)

## 7. (Optional but recommended for the partner-track story) Run the MongoDB MCP server

The agent already counts as MongoDB-integrated via Atlas, and emits MCP-shaped
tool calls. To make the partner-MCP integration **live over the wire**, run the
official MongoDB MCP server and point the agent at it. Easiest: a second tiny
Cloud Run service or a sidecar.

```bash
# Locally, to verify it works:
export MDB_MCP_CONNECTION_STRING="$MONGODB_URI"
npx -y mongodb-mcp-server@latest --transport http --httpPort 3000
# Then for the agent:
export MONGODB_MCP_URL=http://<mcp-host>:3000
```
If you skip this, leave `MONGODB_MCP_URL` unset — the agent still persists to
MongoDB Atlas directly; only the MCP transport stays mocked.

## 8. Deploy to Cloud Run (one command)

From the `app/` directory:

```bash
cd app
PROJECT_ID="$PROJECT_ID" REGION=us-central1 \
MONGODB_URI="$MONGODB_URI" \
GEMINI_API_KEY="${GEMINI_API_KEY:-}" \
GEMINI_MODEL="${GEMINI_MODEL:-gemini-2.5-flash}" \
MONGODB_MCP_URL="${MONGODB_MCP_URL:-}" \
./deploy.sh
```

`deploy.sh` runs `gcloud run deploy --source .` (Cloud Build builds the
Dockerfile), wires the env vars, and prints the hosted URL.

## 9. Get the hosted URL and verify live mode

```bash
gcloud run services describe rulememory-cloud \
  --region us-central1 --format='value(status.url)'

URL=$(gcloud run services describe rulememory-cloud --region us-central1 --format='value(status.url)')
curl "$URL/health"     # expect "mode":"live", reasoner":"gemini", store backend MongoDB
curl -X POST "$URL/run" -H 'content-type: application/json' \
  -d '{"source_text":"Submission deadline: 2026-06-11 14:00 PDT. Build requirement: must use Gemini and a partner MCP server.","source_id":"rules","question":"what expires in 24h and what must we use?","deadline_hours":24}'
```

This `$URL` is the **hosted project URL** for the Devpost submission.

## 10. Public repo + license (Devpost requires open source)

```bash
# From the app/ directory (or wrap it in its own repo root):
git init && git add . && git commit -m "RuleMemory Cloud"
gh repo create rulememory-cloud --public --source=. --push
```
The MIT `LICENSE` is already at the repo top. On GitHub, the About box should
show the license — set it via repo Settings if not auto-detected.

## 11. Record the ~3-minute demo video (shot list)

1. **0:00–0:20 Problem.** "Contest teams lose facts and miss deadlines because
   rules live in chat." Show the rules page you'll ingest.
2. **0:20–0:50 Architecture.** One slide: Gemini (reasoning) → MongoDB MCP
   server → MongoDB Atlas (memory) → Cloud Run. Say the partner track: MongoDB.
3. **0:50–2:10 Live multi-step run.** In a terminal, hit the hosted `$URL/run`.
   Walk the transcript on screen: `extract.facts` (Gemini), `mcp.insert-many`
   (MongoDB MCP), `store.upsert`, `query.deadlines` (the 24h hits),
   `flag.stale` (an old assumption flagged), `answer.summarize`. Emphasize this
   is multi-step **under user oversight**, not chat.
4. **2:10–2:40 Proof it's live.** Show `$URL/health` reading `"mode":"live"`,
   then the Atlas UI showing the inserted documents in the `entries` collection.
5. **2:40–3:00 Close.** Public repo URL + hosted URL on screen. Done.

Upload to YouTube (unlisted is fine), English or subtitled.

## 12. Submit on Devpost

Form fields: project name, **partner track = MongoDB**, hosted URL (step 9),
public repo URL (step 10), video URL (step 11), text description (reuse README).
**Deadline: 2026-06-11 14:00 PDT — submit with margin.**

---

## Teardown (avoid charges after judging)

```bash
gcloud run services delete rulememory-cloud --region us-central1
# Atlas: pause or delete the M0 cluster in the console (M0 is free anyway).
```
