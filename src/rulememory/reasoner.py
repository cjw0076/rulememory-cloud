"""Reasoning layer: Gemini (live) or a deterministic stub (mock).

Two responsibilities:
  1. extract_facts(text) -> structured RuleEntry candidates from a rules page.
  2. summarize(question, entries) -> a grounded natural-language answer.

Live mode uses the Google Gen AI SDK (`google-genai`) targeting either the
Gemini Developer API (GEMINI_API_KEY) or Vertex AI (GOOGLE_GENAI_USE_VERTEXAI).
The default model id is gemini-2.5-flash; set GEMINI_MODEL to a Gemini 3 id once
your project has access (the hackathon references "Gemini 3").

Mock mode runs a small rule-based extractor so the whole multi-step pipeline is
testable with no credentials. The mock is intentionally simple but real enough
to demonstrate extract -> store -> query -> flag.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .models import RuleEntry, SourceRef, now_utc

_EXTRACTION_INSTRUCTIONS = (
    "You extract contest/launch FACTS from the provided source text. "
    "Return STRICT JSON: a list of objects with keys "
    "entry_type (one of rule|deadline|eligibility|preference|decision|evidence), "
    "title, summary, confidence (0..1), and for deadlines an ISO-8601 "
    "expires_at_utc. Only facts present in the text. No commentary."
)


class Reasoner:
    """Abstract reasoner. Implementations: GeminiReasoner, MockReasoner."""

    name = "base"

    def extract_facts(self, text: str, source_id: str) -> list[RuleEntry]:
        raise NotImplementedError

    def summarize(self, question: str, context: str) -> str:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Live: Gemini via google-genai
# --------------------------------------------------------------------------- #
class GeminiReasoner(Reasoner):
    name = "gemini"

    def __init__(self, model: str, *, api_key: str | None, use_vertexai: bool,
                 project: str | None, location: str) -> None:
        from google import genai  # local import; only needed in live mode

        self.model = model
        if use_vertexai:
            self._client = genai.Client(vertexai=True, project=project, location=location)
        else:
            self._client = genai.Client(api_key=api_key)

    def _generate(self, prompt: str) -> str:
        resp = self._client.models.generate_content(model=self.model, contents=prompt)
        return (resp.text or "").strip()

    def extract_facts(self, text: str, source_id: str) -> list[RuleEntry]:
        prompt = f"{_EXTRACTION_INSTRUCTIONS}\n\n--- SOURCE TEXT ---\n{text}\n--- END ---"
        raw = self._generate(prompt)
        return _entries_from_json(raw, source_id)

    def summarize(self, question: str, context: str) -> str:
        prompt = (
            "You are RuleMemory, a contest-facts assistant. Answer the question "
            "using ONLY the remembered facts below. Be concise and cite entry_ids.\n\n"
            f"QUESTION: {question}\n\nREMEMBERED FACTS:\n{context}\n\nANSWER:"
        )
        return self._generate(prompt)


# --------------------------------------------------------------------------- #
# Mock: deterministic local extractor
# --------------------------------------------------------------------------- #
class MockReasoner(Reasoner):
    name = "mock"

    _DEADLINE_RE = re.compile(
        r"(?P<label>[A-Za-z][\w \-/]{2,40}?)\s*(?:deadline|due|closes?|by)\s*[:\-]?\s*"
        r"(?P<date>\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2})?)",
        re.IGNORECASE,
    )
    _ISO_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2})?\b")

    def extract_facts(self, text: str, source_id: str) -> list[RuleEntry]:
        entries: list[RuleEntry] = []
        seq = 0

        def mk_id() -> str:
            nonlocal seq
            seq += 1
            return f"{source_id}-{seq:03d}"

        ref = SourceRef(source_id=source_id, section_hint="auto-extracted")

        # Deadlines: "X deadline: YYYY-MM-DD HH:MM"
        for m in self._DEADLINE_RE.finditer(text):
            dt = _parse_iso(m.group("date"))
            if dt is None:
                continue
            label = m.group("label").strip().rstrip(":-").strip()
            entries.append(
                RuleEntry(
                    entry_id=mk_id(),
                    entry_type="deadline",
                    title=f"{label} deadline",
                    summary=f"{label} is due at {dt.isoformat()}.",
                    confidence=0.9,
                    expires_at_utc=dt,
                    source_refs=[ref],
                    labels=["deadline"],
                )
            )

        # Eligibility / rule cues, line-based.
        for line in (ln.strip() for ln in text.splitlines()):
            if not line or len(line) < 12:
                continue
            low = line.lower()
            if any(k in low for k in ("eligib", "must be", "residents of", "age of majority")):
                entries.append(
                    RuleEntry(
                        entry_id=mk_id(),
                        entry_type="eligibility",
                        title="Eligibility constraint",
                        summary=line[:240],
                        confidence=0.7,
                        source_refs=[ref],
                        labels=["eligibility"],
                    )
                )
            elif any(k in low for k in ("must use", "required to", "powered by", "integrate")):
                entries.append(
                    RuleEntry(
                        entry_id=mk_id(),
                        entry_type="rule",
                        title="Build requirement",
                        summary=line[:240],
                        confidence=0.75,
                        source_refs=[ref],
                        labels=["rule"],
                    )
                )
        return entries

    def summarize(self, question: str, context: str) -> str:
        return (
            f"[mock-reasoner] Based on remembered facts, here is the answer to "
            f'"{question}":\n{context if context.strip() else "(no matching facts)"}'
        )


def _parse_iso(s: str) -> datetime | None:
    s = s.strip().replace(" ", "T")
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _entries_from_json(raw: str, source_id: str) -> list[RuleEntry]:
    """Parse a Gemini JSON response into RuleEntry objects, tolerantly."""
    raw = raw.strip()
    # Strip markdown code fences if the model wrapped its JSON.
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = data.get("entries") or data.get("facts") or [data]
    out: list[RuleEntry] = []
    ref = SourceRef(source_id=source_id, section_hint="gemini-extracted")
    for i, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            continue
        et = item.get("entry_type", "rule")
        if et not in {"rule", "deadline", "eligibility", "preference", "decision", "evidence"}:
            et = "rule"
        expires = _parse_iso(str(item["expires_at_utc"])) if item.get("expires_at_utc") else None
        out.append(
            RuleEntry(
                entry_id=f"{source_id}-{i:03d}",
                entry_type=et,
                title=str(item.get("title", "fact"))[:120],
                summary=str(item.get("summary", ""))[:300],
                confidence=float(item.get("confidence", 0.7)),
                expires_at_utc=expires,
                source_refs=[ref],
                labels=[et],
            )
        )
    return out


def stale_after_default(hours: int = 24, at: datetime | None = None) -> datetime:
    return (at or now_utc()) + timedelta(hours=hours)
