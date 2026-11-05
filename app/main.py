"""Runbook AI Assistant — FastAPI app.

Endpoints:
  GET  /health    service + runbook-count check
  GET  /runbooks  the SAMPLE runbook library
  POST /ask       ask a production-support question, get ranked runbooks
  POST /triage    paste a log snippet, get error signals + a runbook
  GET  /history   logged asks / triages, newest first

Retrieval is deterministic keyword scoring only (see retrieval.py).
There is no LLM API and no API key. When nothing matches, the API
says so honestly instead of inventing an answer.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.history import list_entries, log_entry
from app.retrieval import load_runbooks, rank_runbooks

app = FastAPI(
    title="Runbook AI Assistant",
    description=(
        "A working demo that answers production-support questions from "
        "a library of SAMPLE Guidewire ClaimCenter-style runbooks, "
        "using deterministic keyword retrieval — no LLM API."
    ),
    version="1.0.0",
)

RUNBOOKS = load_runbooks()

# Words / phrases that count as an error signal in a log line.
_ERROR_SIGNALS = [
    "ERROR",
    "FATAL",
    "Exception",
    "Cannot get a connection",
    "Connection pool exhausted",
    "Connection refused",
    "Read timed out",
    "Connection timed out",
    "access denied",
    "authentication",
    "LDAP",
    "timeout",
    "failed",
]


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, description="A production-support question")


class TriageRequest(BaseModel):
    log: str = Field(..., min_length=3, description="A pasted log snippet")


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "runbooks": len(RUNBOOKS)}


@app.get("/runbooks")
def get_runbooks() -> list[dict[str, Any]]:
    return RUNBOOKS


@app.post("/ask")
def ask(req: AskRequest) -> dict[str, Any]:
    matches = rank_runbooks(req.question, RUNBOOKS)
    matched_ids = [m["id"] for m in matches]
    top_score = matches[0]["score"] if matches else 0
    log_entry(
        entry_type="ask",
        input_text=req.question,
        matched_runbook_ids=matched_ids,
        top_score=top_score,
    )
    return {
        "question": req.question,
        "matches": matches,
        "top_runbook_id": matched_ids[0] if matched_ids else None,
        "top_score": top_score,
    }


def _extract_error_signals(log_text: str) -> list[dict[str, str]]:
    """Find log lines containing known error signals, with a reason."""
    findings: list[dict[str, str]] = []
    # Longest signals first, so a specific phrase like
    # "Cannot get a connection" wins over the generic "ERROR".
    signals_sorted = sorted(_ERROR_SIGNALS, key=len, reverse=True)
    for line in log_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for signal in signals_sorted:
            if signal.lower() in stripped.lower():
                findings.append(
                    {
                        "line": stripped,
                        "signal": signal,
                        "explanation": (
                            f"Log line contains '{signal}', which points to "
                            "a failure rather than normal activity."
                        ),
                    }
                )
                break
    return findings


@app.post("/triage")
def triage(req: TriageRequest) -> dict[str, Any]:
    findings = _extract_error_signals(req.log)
    matches = rank_runbooks(req.log, RUNBOOKS)
    matched_ids = [m["id"] for m in matches]
    top = matches[0] if matches else None
    top_score = top["score"] if top else 0
    log_entry(
        entry_type="triage",
        input_text=req.log,
        matched_runbook_ids=matched_ids,
        top_score=top_score,
    )
    reason = None
    if top:
        reason = (
            f"Matched {top['id']} ({top['title']}) on: "
            + ", ".join(top["matched_terms"])
            + ". "
            + top["symptoms"][0]
            if top.get("symptoms")
            else f"Matched {top['id']} on: " + ", ".join(top["matched_terms"])
        )
    return {
        "findings": findings,
        "suggested_runbook": top,
        "reason": reason,
        "top_runbook_id": top["id"] if top else None,
        "top_score": top_score,
    }


@app.get("/history")
def history(limit: int = 100) -> list[dict[str, Any]]:
    return list_entries(limit=limit)


# Allow running directly: python -m app.main
if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
