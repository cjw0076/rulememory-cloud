"""Embedded single-page web UI for RuleMemory Cloud.

The HTML/CSS/JS is embedded as a Python string (not a static file) on purpose:
the Cloud Run image already `COPY src ./src`, so shipping the UI inside the
package means there is no extra Dockerfile COPY to remember and no static-path
resolution to get wrong in the container. The page is vanilla HTML + CSS + JS
(no framework, no build step) and talks to the existing JSON endpoints
(`/health`, `/run`, `/ask`, `/memory`, `/memory/deadlines`).

A judge can open `GET /` and, in one click, watch the multi-step agent plan
animate from the real `/run` transcript, see the grounded answer with cited
fact ids highlighted, and inspect persisted MongoDB-backed memory.
"""

from __future__ import annotations

import json

# A compelling, pre-filled example: a contest rules page with a deadline inside
# the 24h window AND a build requirement that supersedes a stale "use Python 2"
# assumption the agent already holds in memory (seeded at startup).
EXAMPLE_RULES = """\
Google Cloud Rapid Agent Hackathon -- rules snapshot

Submission deadline: 2026-06-11 14:00 PDT.
Internal freeze deadline: 2026-06-10 23:59 PDT.
Video upload deadline: 2026-06-11 13:00 PDT.

Build requirement: projects must use Python 3.12 for the agent runtime.
Build requirement: projects must use Gemini models and integrate at least one
participating partner's MCP server.
Build requirement: the agent must move beyond chat and complete multi-step
tasks under user oversight.

Eligibility: participants must be above the legal age of majority in their
place of residence. Residents of certain sanctioned jurisdictions are not
eligible.
"""

EXAMPLE_QUESTION = (
    "Which deadlines expire in the next 24 hours, and what must we use to "
    "build the agent?"
)

_INDEX_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>RuleMemory Cloud — agent console</title>
<style>
  :root {
    --bg: #0b1020;
    --panel: #121a30;
    --panel-2: #0e1526;
    --line: #243149;
    --ink: #e8edf7;
    --muted: #8ea0c0;
    --brand1: #4285f4;  /* Google blue */
    --brand2: #34a853;  /* Google green */
    --brand3: #fbbc05;  /* Google yellow */
    --brand4: #ea4335;  /* Google red */
    --accent: #5b9bff;
    --ok: #34a853;
    --warn: #fbbc05;
    --bad: #ea4335;
    --radius: 14px;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; }
  body {
    font-family: "Google Sans", system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
    background:
      radial-gradient(1200px 500px at 80% -10%, rgba(66,133,244,.18), transparent),
      radial-gradient(900px 500px at -10% 110%, rgba(52,168,83,.14), transparent),
      var(--bg);
    color: var(--ink);
    min-height: 100vh;
  }
  a { color: var(--accent); }
  header {
    display: flex; align-items: center; gap: 16px;
    padding: 20px 28px; border-bottom: 1px solid var(--line);
    position: sticky; top: 0; z-index: 5;
    background: rgba(11,16,32,.78); backdrop-filter: blur(8px);
  }
  .logo {
    width: 38px; height: 38px; border-radius: 10px; flex: none;
    background:
      conic-gradient(from 180deg, var(--brand1), var(--brand2), var(--brand3), var(--brand4), var(--brand1));
    box-shadow: 0 0 0 1px rgba(255,255,255,.08), 0 8px 24px rgba(66,133,244,.35);
  }
  .title h1 { font-size: 19px; margin: 0; letter-spacing: .2px; }
  .title p { margin: 2px 0 0; font-size: 12.5px; color: var(--muted); }
  .spacer { flex: 1; }
  .status {
    display: flex; gap: 8px; flex-wrap: wrap; align-items: center;
    font-size: 12px;
  }
  .chip {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 5px 10px; border-radius: 999px;
    border: 1px solid var(--line); background: var(--panel-2);
    color: var(--muted); white-space: nowrap;
  }
  .chip b { color: var(--ink); font-weight: 600; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
  .dot.on { background: var(--ok); box-shadow: 0 0 8px var(--ok); }
  .dot.off { background: var(--bad); }
  .chip.mode-live { border-color: rgba(52,168,83,.5); color: #bdf0cd; }
  .chip.mode-mock { border-color: rgba(251,188,5,.45); color: #ffe8a3; }

  main {
    display: grid; grid-template-columns: 380px 1fr; gap: 18px;
    padding: 22px 28px 60px; max-width: 1360px; margin: 0 auto;
  }
  @media (max-width: 980px) { main { grid-template-columns: 1fr; } }

  .panel {
    background: linear-gradient(180deg, var(--panel), var(--panel-2));
    border: 1px solid var(--line); border-radius: var(--radius);
    padding: 18px; box-shadow: 0 10px 30px rgba(0,0,0,.25);
  }
  .panel h2 {
    font-size: 13px; text-transform: uppercase; letter-spacing: .12em;
    color: var(--muted); margin: 0 0 12px;
  }
  label { display: block; font-size: 12.5px; color: var(--muted); margin: 12px 0 6px; }
  textarea, input[type=text], input[type=number] {
    width: 100%; background: #0a1122; color: var(--ink);
    border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px;
    font-size: 13px; font-family: inherit; resize: vertical;
  }
  textarea { line-height: 1.5; }
  textarea:focus, input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(91,155,255,.15); }
  .row { display: flex; gap: 12px; }
  .row > div { flex: 1; }
  button {
    cursor: pointer; border: none; border-radius: 10px;
    font-family: inherit; font-size: 13.5px; font-weight: 600;
    padding: 11px 16px; color: #fff;
    background: linear-gradient(120deg, var(--brand1), #2b6fe0);
    box-shadow: 0 6px 18px rgba(66,133,244,.35);
    transition: transform .06s ease, filter .15s ease;
  }
  button:hover { filter: brightness(1.07); }
  button:active { transform: translateY(1px); }
  button:disabled { filter: grayscale(.6) brightness(.8); cursor: progress; }
  button.ghost {
    background: transparent; color: var(--accent);
    border: 1px solid var(--line); box-shadow: none;
  }
  .btnrow { display: flex; gap: 10px; margin-top: 16px; }
  .btnrow button { flex: 1; }

  .col { display: flex; flex-direction: column; gap: 18px; }

  /* plan steps */
  ol.plan { list-style: none; margin: 0; padding: 0; }
  ol.plan li {
    border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px;
    margin-bottom: 10px; background: var(--panel-2);
    opacity: .35; transform: translateY(4px);
    transition: opacity .35s ease, transform .35s ease, border-color .35s ease;
  }
  ol.plan li.show { opacity: 1; transform: none; }
  ol.plan li.active { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(91,155,255,.12); }
  ol.plan li.done { border-color: rgba(52,168,83,.4); }
  .step-head { display: flex; align-items: center; gap: 10px; }
  .step-num {
    width: 24px; height: 24px; border-radius: 50%; flex: none;
    display: grid; place-items: center; font-size: 12px; font-weight: 700;
    background: #0a1122; border: 1px solid var(--line); color: var(--muted);
  }
  li.done .step-num { background: var(--ok); color: #042; border-color: var(--ok); }
  li.active .step-num { background: var(--accent); color: #021; border-color: var(--accent); }
  .step-name { font-weight: 600; font-size: 13.5px; }
  .step-badge {
    margin-left: auto; font-size: 11px; color: var(--muted);
    border: 1px solid var(--line); border-radius: 999px; padding: 2px 8px;
  }
  .step-detail { color: var(--muted); font-size: 12.5px; margin: 7px 0 0 34px; }
  .step-data {
    margin: 8px 0 0 34px; font-size: 11.5px; color: #b9c6e2;
    background: #0a1122; border: 1px solid var(--line); border-radius: 8px;
    padding: 8px 10px; overflow-x: auto; white-space: pre-wrap; word-break: break-word;
    max-height: 180px;
  }

  .answer {
    border: 1px solid rgba(52,168,83,.4); border-radius: 12px;
    background: linear-gradient(180deg, rgba(52,168,83,.10), transparent);
    padding: 14px 16px; font-size: 14px; line-height: 1.6; white-space: pre-wrap;
  }
  .answer .cite {
    display: inline-block; font-family: ui-monospace, Menlo, monospace;
    font-size: 12px; background: rgba(66,133,244,.18); color: #cfe0ff;
    border: 1px solid rgba(66,133,244,.5); border-radius: 6px;
    padding: 0 6px; margin: 0 1px;
  }
  .muted { color: var(--muted); }
  .placeholder { color: var(--muted); font-size: 13px; padding: 8px 2px; }

  table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
  th { color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
  td.id { font-family: ui-monospace, Menlo, monospace; color: #cfe0ff; white-space: nowrap; }
  .tag {
    display: inline-block; font-size: 10.5px; padding: 1px 7px; border-radius: 999px;
    border: 1px solid var(--line); color: var(--muted);
  }
  .tag.deadline { color: #ffd9a3; border-color: rgba(251,188,5,.5); }
  .tag.rule { color: #cfe0ff; border-color: rgba(66,133,244,.5); }
  .tag.eligibility { color: #d7c9ff; border-color: rgba(150,120,255,.5); }
  .pill-stale { color: #ffb4ac; border: 1px solid rgba(234,67,53,.55); border-radius: 999px; padding: 1px 8px; font-size: 11px; }
  .pill-active { color: #bdf0cd; border: 1px solid rgba(52,168,83,.5); border-radius: 999px; padding: 1px 8px; font-size: 11px; }
  .pill-superseded { color: #c8d2e6; border: 1px solid var(--line); border-radius: 999px; padding: 1px 8px; font-size: 11px; }

  .barhead { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
  .barhead .right { display: flex; gap: 8px; align-items: center; }
  .ask-row { display: flex; gap: 10px; margin-top: 8px; }
  .ask-row input { flex: 1; }
  .toast {
    position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
    background: var(--bad); color: #fff; padding: 10px 16px; border-radius: 10px;
    font-size: 13px; box-shadow: 0 8px 24px rgba(0,0,0,.4); display: none; z-index: 20;
  }
  footer { text-align: center; color: var(--muted); font-size: 12px; padding: 8px 0 30px; }
</style>
</head>
<body>
<header>
  <div class="logo" aria-hidden="true"></div>
  <div class="title">
    <h1>RuleMemory Cloud</h1>
    <p>Gemini × MongoDB MCP agent · turns rules pages into auditable, queryable memory</p>
  </div>
  <div class="spacer"></div>
  <div class="status" id="status"><span class="chip">connecting…</span></div>
</header>

<main>
  <!-- LEFT: input -->
  <section class="panel" id="inputPanel">
    <h2>1 · Rules &amp; question</h2>
    <label for="rules">Rules document</label>
    <textarea id="rules" rows="13"></textarea>
    <label for="question">Question</label>
    <textarea id="question" rows="2"></textarea>
    <div class="row">
      <div>
        <label for="hours">Deadline window (hours)</label>
        <input type="number" id="hours" value="24" min="1" step="1" />
      </div>
      <div>
        <label for="srcid">Source id</label>
        <input type="text" id="srcid" value="rapid-rules" />
      </div>
    </div>
    <div class="btnrow">
      <button id="runBtn">▶ Run agent</button>
      <button class="ghost" id="resetBtn" title="Restore the example">Reset example</button>
    </div>
    <p class="muted" style="font-size:12px;margin-top:14px">
      Runs the real multi-step task: ingest → Gemini extract → MongoDB&nbsp;MCP
      insert → store → deadlines → stale/conflict → grounded answer.
    </p>
  </section>

  <!-- RIGHT -->
  <div class="col">
    <section class="panel">
      <div class="barhead">
        <h2 style="margin:0">2 · Agent plan</h2>
        <span class="muted" id="planMeta"></span>
      </div>
      <ol class="plan" id="plan">
        <li class="placeholder-li"><span class="placeholder">Click “Run agent” to watch the plan execute step by step.</span></li>
      </ol>
    </section>

    <section class="panel">
      <h2>3 · Grounded answer</h2>
      <div id="answer"><span class="placeholder">The cited, grounded answer appears here.</span></div>
    </section>

    <section class="panel">
      <div class="barhead">
        <h2 style="margin:0">4 · Persisted memory</h2>
        <div class="right">
          <span class="muted" id="memMeta"></span>
          <button class="ghost" id="refreshMem">↻ Refresh</button>
        </div>
      </div>
      <div style="overflow-x:auto">
        <table id="memTable">
          <thead><tr>
            <th>ID</th><th>Type</th><th>Fact</th><th>Source</th><th>Expires</th><th>Status</th>
          </tr></thead>
          <tbody><tr><td colspan="6" class="placeholder">Loading memory…</td></tr></tbody>
        </table>
      </div>
      <h2 style="margin-top:18px">Ask the existing memory (no re-ingest)</h2>
      <div class="ask-row">
        <input type="text" id="askInput" placeholder="e.g. What build requirements are remembered?" />
        <button id="askBtn">Ask</button>
      </div>
      <div id="askAnswer" style="margin-top:10px"></div>
    </section>
  </div>
</main>

<div class="toast" id="toast"></div>
<footer>RuleMemory Cloud · Google Cloud Rapid Agent Hackathon · MongoDB partner track</footer>

<script>
const EXAMPLE_RULES = __EXAMPLE_RULES__;
const EXAMPLE_QUESTION = __EXAMPLE_QUESTION__;

const $ = (id) => document.getElementById(id);
const STEP_LABELS = {
  "ingest.start":     ["Ingest", "rules"],
  "extract.facts":    ["Extract facts", "Gemini"],
  "mcp.insert-many":  ["Insert via MongoDB MCP", "MCP tool"],
  "store.upsert":     ["Persist to store", "MongoDB"],
  "flag.conflict":    ["Flag conflicts", "supersede"],
  "query.deadlines":  ["Query deadlines", "window"],
  "flag.stale":       ["Flag stale", "decay"],
  "answer.summarize": ["Summarize answer", "Gemini"],
  "done":             ["Done", "final"],
};

function toast(msg) {
  const t = $("toast");
  t.textContent = msg; t.style.display = "block";
  setTimeout(() => { t.style.display = "none"; }, 4200);
}

function loadExample() {
  $("rules").value = EXAMPLE_RULES;
  $("question").value = EXAMPLE_QUESTION;
  $("hours").value = 24;
  $("srcid").value = "rapid-rules";
}

async function refreshStatus() {
  try {
    const h = await (await fetch("/health")).json();
    const live = (m) => `<span class="dot ${m ? "on" : "off"}"></span>`;
    const modeClass = h.mode === "live" ? "mode-live" : "mode-mock";
    $("status").innerHTML =
      `<span class="chip ${modeClass}"><b>mode:</b> ${h.mode}</span>` +
      `<span class="chip">${live(h.gemini_live)}<b>Gemini</b> ${h.gemini_model || ""}</span>` +
      `<span class="chip">${live(h.mongo_live)}<b>MongoDB</b> ${h.store_backend}</span>` +
      `<span class="chip">${live(h.mcp_live)}<b>MCP</b> ${h.mcp_transport}</span>` +
      `<span class="chip"><b>${h.entries}</b> facts</span>`;
  } catch (e) {
    $("status").innerHTML = `<span class="chip" style="border-color:var(--bad)">offline</span>`;
  }
}

function citeIds(text, ids) {
  if (!text) return "";
  let html = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  // Highlight every known fact id wherever it appears in the answer.
  const sorted = [...ids].sort((a, b) => b.length - a.length);
  for (const id of sorted) {
    if (!id) continue;
    const esc = id.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&");
    html = html.replace(new RegExp(esc, "g"), `<span class="cite">${id}</span>`);
  }
  return html;
}

function renderPlanSkeleton(steps) {
  const ol = $("plan");
  ol.innerHTML = "";
  steps.forEach((s, i) => {
    const lab = STEP_LABELS[s.step] || [s.step, ""];
    const li = document.createElement("li");
    li.innerHTML =
      `<div class="step-head">
         <span class="step-num">${i + 1}</span>
         <span class="step-name">${lab[0]}</span>
         <span class="step-badge">${lab[1]}</span>
       </div>
       <div class="step-detail"></div>
       <div class="step-data" style="display:none"></div>`;
    li.querySelector(".step-detail").textContent = s.detail || "";
    const data = s.data && Object.keys(s.data).length
      ? JSON.stringify(s.data, null, 2) : "";
    if (data) {
      const d = li.querySelector(".step-data");
      d.style.display = "block"; d.textContent = data;
    }
    ol.appendChild(li);
  });
  return ol;
}

async function animatePlan(steps) {
  const ol = renderPlanSkeleton(steps);
  const items = [...ol.children];
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  for (let i = 0; i < items.length; i++) {
    items[i].classList.add("show", "active");
    items[i].scrollIntoView({ behavior: "smooth", block: "nearest" });
    await sleep(520);
    items[i].classList.remove("active");
    items[i].classList.add("done");
  }
}

function allFactIds(transcript) {
  const ids = new Set();
  for (const s of transcript.steps) {
    const d = s.data || {};
    (d.entry_ids || []).forEach(x => ids.add(x));
    (d.supersessions || []).forEach(x => { ids.add(x.old); ids.add(x.new); });
  }
  return [...ids];
}

async function runAgent() {
  const btn = $("runBtn");
  btn.disabled = true; btn.textContent = "Running…";
  $("answer").innerHTML = `<span class="placeholder">Thinking…</span>`;
  $("planMeta").textContent = "";
  try {
    const body = {
      source_text: $("rules").value,
      source_id: $("srcid").value || "rapid-rules",
      question: $("question").value,
      deadline_hours: parseFloat($("hours").value) || 24,
    };
    const res = await fetch("/run", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const out = await res.json();
    const t = out.transcript;
    $("planMeta").textContent = `${t.steps.length} steps`;
    await animatePlan(t.steps);

    const doneStep = t.steps.find(s => s.step === "done");
    const ans = doneStep ? (doneStep.data.answer || "") : "";
    const ids = allFactIds(t);
    $("answer").innerHTML = ans
      ? `<div class="answer">${citeIds(ans, ids)}</div>`
      : `<span class="placeholder">No answer produced.</span>`;
    await refreshStatus();
    await refreshMemory();
  } catch (e) {
    toast("Run failed: " + e.message);
    $("answer").innerHTML = `<span class="placeholder">Run failed: ${e.message}</span>`;
  } finally {
    btn.disabled = false; btn.textContent = "▶ Run agent";
  }
}

function statusPill(row) {
  if (row.stale && row.status !== "superseded") return `<span class="pill-stale">stale</span>`;
  if (row.status === "superseded") return `<span class="pill-superseded">superseded</span>`;
  if (row.status === "stale") return `<span class="pill-stale">stale</span>`;
  return `<span class="pill-active">active</span>`;
}

async function refreshMemory() {
  try {
    const m = await (await fetch("/memory")).json();
    $("memMeta").textContent = `${m.count} entries · ${m.backend}`;
    const tbody = $("memTable").querySelector("tbody");
    if (!m.entries.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="placeholder">No facts remembered yet — run the agent.</td></tr>`;
      return;
    }
    tbody.innerHTML = m.entries.map(r => {
      const exp = r.expires_at ? r.expires_at.replace("T", " ").replace("+00:00", "") : "—";
      const txt = (r.text || r.title || "").replace(/</g, "&lt;");
      return `<tr>
        <td class="id">${r.id}</td>
        <td><span class="tag ${r.type}">${r.type}</span></td>
        <td>${txt}</td>
        <td class="muted">${r.source || "—"}</td>
        <td class="muted">${exp}</td>
        <td>${statusPill(r)}</td>
      </tr>`;
    }).join("");
  } catch (e) {
    $("memMeta").textContent = "memory unavailable";
  }
}

async function askMemory() {
  const q = $("askInput").value.trim();
  if (!q) return;
  const btn = $("askBtn");
  btn.disabled = true;
  $("askAnswer").innerHTML = `<span class="placeholder">Asking remembered facts…</span>`;
  try {
    const res = await fetch("/ask", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ question: q }),
    });
    const out = await res.json();
    const m = await (await fetch("/memory")).json();
    const ids = m.entries.map(e => e.id);
    $("askAnswer").innerHTML = `<div class="answer">${citeIds(out.answer || "", ids)}</div>`;
  } catch (e) {
    toast("Ask failed: " + e.message);
    $("askAnswer").innerHTML = `<span class="placeholder">Ask failed: ${e.message}</span>`;
  } finally {
    btn.disabled = false;
  }
}

$("runBtn").addEventListener("click", runAgent);
$("resetBtn").addEventListener("click", loadExample);
$("refreshMem").addEventListener("click", refreshMemory);
$("askBtn").addEventListener("click", askMemory);
$("askInput").addEventListener("keydown", (e) => { if (e.key === "Enter") askMemory(); });

loadExample();
refreshStatus();
refreshMemory();
setInterval(refreshStatus, 15000);
</script>
</body>
</html>
"""


INDEX_HTML = (
    _INDEX_TEMPLATE
    .replace("__EXAMPLE_RULES__", json.dumps(EXAMPLE_RULES))
    .replace("__EXAMPLE_QUESTION__", json.dumps(EXAMPLE_QUESTION))
)
