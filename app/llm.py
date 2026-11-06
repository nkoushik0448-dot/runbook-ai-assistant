"""Optional LLM answers, grounded in retrieved runbooks (a real RAG pattern).

How it works:
  1. The caller first runs the existing deterministic retrieval
     (app/retrieval.py) to get the top matching runbooks.
  2. Those runbooks — and only those runbooks — are sent to a local
     Ollama model as context, with a system prompt that says: answer
     ONLY from the provided runbooks, cite their IDs, and say so
     plainly when they do not cover the question.
  3. The model's answer is returned together with the runbooks it
     was grounded in, so anyone can check the answer against them.

Ollama runs entirely on your own machine — there is no API key, no
account, and nothing leaves the machine. The model and host come
from the OLLAMA_MODEL and OLLAMA_HOST environment variables
(defaults: llama3.2:3b and http://localhost:11434, see .env.example).
No embeddings and no vector database are involved — retrieval stays
the deterministic keyword scoring from retrieval.py.

When Ollama is not running, ask_llm() raises LLMUnavailableError
and the /ask-ai endpoint answers 503 with instructions to start it,
instead of fabricating anything. When Ollama itself fails (model
not pulled, 4xx/5xx), ask_llm() raises LLMUpstreamError carrying
the upstream status, and the endpoint answers 502 — again, no
fabricated answer.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_MODEL = "llama3.2:3b"
DEFAULT_HOST = "http://localhost:11434"
TIMEOUT_SECONDS = 120.0

SYSTEM_PROMPT = (
    "You are a production-support assistant for Guidewire ClaimCenter. "
    "Answer the user's question using ONLY the runbooks provided below "
    "as context. Cite the runbook IDs (for example RB-101) for every "
    "claim you make. If the provided runbooks do not cover the question, "
    "say so plainly and do not invent an answer. Keep the answer short "
    "and practical: what to check and what to do, in order."
)


class LLMUnavailableError(Exception):
    """Raised when Ollama is not reachable (not running)."""


class LLMUpstreamError(Exception):
    """Raised when the Ollama API call fails.

    upstream_status is the HTTP status Ollama returned (e.g. 404 when
    the model has not been pulled, 500), or None when the request
    never reached Ollama (network error other than connection refused).
    """

    def __init__(self, upstream_status: int | None, message: str) -> None:
        super().__init__(message)
        self.upstream_status = upstream_status
        self.message = message


def model_name() -> str:
    """The Ollama model to use (OLLAMA_MODEL, default llama3.2:3b)."""
    return os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def host() -> str:
    """The Ollama server base URL (OLLAMA_HOST, default localhost)."""
    return os.environ.get("OLLAMA_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST


def chat_url() -> str:
    """The Ollama chat API endpoint."""
    return f"{host().rstrip('/')}/api/chat"


def _format_runbook(runbook: dict[str, Any]) -> str:
    """Render one retrieved runbook as context text for the model."""
    lines = [f"Runbook {runbook['id']}: {runbook['title']}"]
    if runbook.get("symptoms"):
        lines.append("Symptoms:")
        lines.extend(f"- {s}" for s in runbook["symptoms"])
    if runbook.get("checks"):
        lines.append("Checks:")
        lines.extend(f"- {c}" for c in runbook["checks"])
    if runbook.get("steps"):
        lines.append("Steps:")
        lines.extend(f"- {s}" for s in runbook["steps"])
    return "\n".join(lines)


def _build_messages(
    question: str, matches: list[dict[str, Any]]
) -> list[dict[str, str]]:
    """Build the chat messages: system prompt + runbook context + question."""
    if matches:
        context = "\n\n".join(_format_runbook(m) for m in matches)
    else:
        context = (
            "No runbooks matched this question. Say that the runbooks do "
            "not cover it and do not invent an answer."
        )
    user_content = (
        f"Runbooks:\n{context}\n\n"
        f"Question: {question}\n\n"
        "Answer using only the runbooks above, citing their IDs."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _extract_error_message(resp: httpx.Response) -> str:
    """Pull a human-readable message out of an Ollama error response."""
    try:
        data = resp.json()
        message = data.get("error")
        if message:
            return str(message)
    except (ValueError, AttributeError):
        pass
    text = resp.text.strip()
    if text:
        return text[:500]
    return f"Ollama API returned HTTP {resp.status_code} with no error detail."


def ask_llm(question: str, matches: list[dict[str, Any]]) -> str:
    """Ask the local Ollama model a question, grounded in the runbooks.

    Returns the model's answer text. Raises LLMUnavailableError when
    Ollama is not running, and LLMUpstreamError when the Ollama call
    fails (e.g. the model has not been pulled). Never returns a
    fabricated answer.
    """
    model = model_name()
    payload = {
        "model": model,
        "messages": _build_messages(question, matches),
        "stream": False,
    }
    try:
        # trust_env=False: Ollama is a local server, so no proxy is
        # ever needed — and proxy environment variables must not be
        # able to break this call (some environments have no_proxy
        # entries, e.g. bare IPv6 addresses, that httpx cannot parse
        # and that would raise InvalidURL before any request is made).
        with httpx.Client(timeout=TIMEOUT_SECONDS, trust_env=False) as client:
            resp = client.post(chat_url(), json=payload)
    except httpx.ConnectError as exc:
        raise LLMUnavailableError(
            "Ollama is not running: could not connect to "
            f"{host()}. Start it with `ollama serve` (in a separate "
            f"terminal), and make sure the model is pulled with "
            f"`ollama pull {model}`. The deterministic /ask endpoint "
            "needs no Ollama at all."
        ) from exc
    except httpx.RequestError as exc:
        raise LLMUpstreamError(
            None, f"Could not reach the Ollama API: {exc}"
        ) from exc
    if resp.status_code != 200:
        message = _extract_error_message(resp)
        if resp.status_code == 404 and "not found" in message.lower():
            message = (
                f"{message} Pull the model first with "
                f"`ollama pull {model}`."
            )
        raise LLMUpstreamError(resp.status_code, message)
    try:
        data = resp.json()
        content = data["message"]["content"]
    except (ValueError, KeyError, TypeError) as exc:
        raise LLMUpstreamError(
            resp.status_code,
            "Ollama returned an unexpected response shape.",
        ) from exc
    if not content or not content.strip():
        raise LLMUpstreamError(
            resp.status_code, "Ollama returned an empty answer."
        )
    return content.strip()
