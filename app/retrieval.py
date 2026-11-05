"""Deterministic keyword retrieval over the SAMPLE runbook library.

No LLM API, no API keys, no embeddings. Scoring is deliberately simple
and explainable so an interviewer can follow it:

- Normalise the input text to lower case.
- For each runbook, find which of its keywords appear as substrings.
- A matched keyword scores points: 10 for a single word, 20 for a
  multi-word phrase (phrases are more specific, so they weigh more).
- Score is capped at 100 and rounded to an integer.
- Results are ranked by score (descending), then by runbook id.

This is the same scoring used by the web demo, so the rankings match:
  "ClaimCenter login fails after deployment" -> RB-101 top
  "integration timeout on payment"          -> RB-103 top
  a DB-pool log with "Cannot get a connection" /
  "Connection pool exhausted"              -> RB-105 top
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "runbooks.json"


def load_runbooks(path: Path | None = None) -> list[dict[str, Any]]:
    """Load the runbook library from JSON."""
    with open(path or DATA_PATH, encoding="utf-8") as f:
        runbooks = json.load(f)
    return runbooks


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def score_runbook(text: str, runbook: dict[str, Any]) -> tuple[int, list[str]]:
    """Score one runbook against the input text.

    Returns (score 0-100, matched keywords in library order).
    """
    haystack = _normalise(text)
    matched: list[str] = []
    points = 0
    for keyword in runbook.get("keywords", []):
        kw = _normalise(str(keyword))
        if not kw:
            continue
        # Word-boundary-ish substring match: require the keyword to
        # appear as a phrase. For single short words (e.g. "db",
        # "sql", "api") use a word-boundary regex to avoid matching
        # inside other words (e.g. "db" inside "debug").
        if " " in kw:
            hit = kw in haystack
        elif len(kw) <= 3:
            hit = re.search(rf"\b{re.escape(kw)}\b", haystack) is not None
        else:
            hit = kw in haystack
        if hit:
            matched.append(str(keyword))
            points += 20 if " " in kw else 10
    score = min(100, points)
    return score, matched


def rank_runbooks(
    text: str, runbooks: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Rank all runbooks with score > 0, highest first.

    Each result is the full runbook dict plus "score" and
    "matched_terms" keys. An empty list means no runbook matched —
    callers should report that honestly instead of inventing a match.
    """
    runbooks = runbooks if runbooks is not None else load_runbooks()
    ranked: list[dict[str, Any]] = []
    for runbook in runbooks:
        score, matched = score_runbook(text, runbook)
        if score > 0:
            result = dict(runbook)
            result["score"] = score
            result["matched_terms"] = matched
            ranked.append(result)
    ranked.sort(key=lambda r: (-r["score"], r["id"]))
    return ranked
