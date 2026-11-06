"""Tests for POST /ask-ai (real LLM call to local Ollama, mocked at
the httpx level).

Ollama is a local server, so in tests its HTTP call is mocked with
httpx.MockTransport — the tests exercise the real request-building,
response-parsing, and error-handling code in app/llm.py without
needing Ollama running. No new test dependencies are used.
"""

import json

import httpx
import pytest

from app import llm as llm_module

QUESTION = "ClaimCenter login fails after deployment"

MOCKED_ANSWER = (
    "Per RB-101, first reproduce the login failure with a test account "
    "and note the exact error and timestamp, then compare the deployed "
    "authentication configuration against the last known good one."
)


def _ollama_success(request: httpx.Request) -> httpx.Response:
    """Mock Ollama handler: checks the request, returns a canned answer."""
    assert str(request.url) == "http://localhost:11434/api/chat"
    payload = json.loads(request.content)
    assert payload["model"] == "llama3.2:3b"
    assert payload["stream"] is False
    # The request must be grounded: at least one runbook is in the
    # context sent to the model, the question is included, and the
    # system prompt restricts the model to the runbooks.
    user_content = payload["messages"][1]["content"]
    assert "Runbook RB-" in user_content
    assert "Question:" in user_content
    assert "ONLY" in payload["messages"][0]["content"]
    return httpx.Response(
        200,
        json={
            "model": "llama3.2:3b",
            "message": {"role": "assistant", "content": MOCKED_ANSWER},
            "done": True,
        },
    )


def _mock_httpx_client(monkeypatch, handler):
    """Patch httpx.Client so llm.py's real call goes through a mock.

    The factory returns a real httpx.Client bound to a MockTransport,
    so the request is built, sent, and parsed by the production code.
    """
    transport = httpx.MockTransport(handler)
    # Capture the real Client class first: after patching, httpx.Client
    # IS this factory, so the factory must not call itself.
    real_client = httpx.Client
    monkeypatch.setattr(
        llm_module.httpx,
        "Client",
        lambda *args, **kwargs: real_client(transport=transport),
    )


def test_ask_ai_returns_mocked_answer_with_grounding(client, monkeypatch):
    _mock_httpx_client(monkeypatch, _ollama_success)

    r = client.post("/ask-ai", json={"question": QUESTION})
    assert r.status_code == 200
    data = r.json()
    assert data["answer"] == MOCKED_ANSWER
    assert data["model"] == "llama3.2:3b"
    assert data["llm_used"] is True
    assert data["top_runbook_id"] == "RB-101"
    assert data["top_score"] > 0
    # The answer is grounded: the runbooks it cites are returned too.
    grounded_ids = [rb["id"] for rb in data["grounded_runbooks"]]
    assert "RB-101" in grounded_ids
    assert data["grounded_runbooks"][0]["id"] == "RB-101"
    assert data["grounded_runbooks"][0]["score"] > 0


def test_ask_ai_logs_to_history(client, monkeypatch):
    _mock_httpx_client(monkeypatch, _ollama_success)

    before = client.get("/history")
    count_before = len(before.json())

    r = client.post(
        "/ask-ai",
        json={"question": "integration timeout on payment for ask-ai history test"},
    )
    assert r.status_code == 200

    after = client.get("/history")
    entries = after.json()
    assert len(entries) == count_before + 1
    latest = entries[0]  # newest first
    assert latest["type"] == "ask-ai"
    assert latest["model"] == "llama3.2:3b"
    assert "RB-103" in latest["matched_runbook_ids"]


def test_ask_ai_ollama_not_running_returns_clear_error(client, monkeypatch):
    def _connection_refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    _mock_httpx_client(monkeypatch, _connection_refused)

    r = client.post("/ask-ai", json={"question": QUESTION})
    assert r.status_code == 503
    data = r.json()
    assert data["error"] == "llm_unavailable"
    assert "ollama serve" in data["message"]
    assert "ollama pull llama3.2:3b" in data["message"]
    # No fabricated answer is returned.
    assert "answer" not in data


def test_ask_ai_model_not_pulled_returns_upstream_error(client, monkeypatch):
    def _model_missing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": "model 'llama3.2:3b' not found, try pulling it first"},
        )

    _mock_httpx_client(monkeypatch, _model_missing)

    r = client.post("/ask-ai", json={"question": QUESTION})
    assert r.status_code == 502
    data = r.json()
    assert data["error"] == "llm_upstream_error"
    assert data["upstream_status"] == 404
    assert "ollama pull llama3.2:3b" in data["message"]
    # No fabricated answer is returned.
    assert "answer" not in data


def test_ask_ai_too_short_returns_validation_error(client, monkeypatch):
    r = client.post("/ask-ai", json={"question": "hi"})
    assert r.status_code == 422
    r = client.post("/ask-ai", json={"question": ""})
    assert r.status_code == 422


def test_ask_still_deterministic_without_ollama(client, monkeypatch):
    """The original /ask endpoint needs no Ollama and never calls the LLM."""
    r = client.post("/ask", json={"question": QUESTION})
    assert r.status_code == 200
    data = r.json()
    assert data["top_runbook_id"] == "RB-101"
    assert data["top_score"] > 0
    assert "answer" not in data  # /ask returns ranked runbooks, not prose


@pytest.mark.parametrize("bad_status", [429, 500])
def test_ask_ai_ollama_error_statuses_return_upstream_error(
    client, monkeypatch, bad_status
):
    def _error(request: httpx.Request, status=bad_status) -> httpx.Response:
        return httpx.Response(
            status,
            json={"error": f"Upstream failure ({status})."},
        )

    _mock_httpx_client(monkeypatch, _error)

    r = client.post("/ask-ai", json={"question": QUESTION})
    assert r.status_code == 502
    data = r.json()
    assert data["error"] == "llm_upstream_error"
    assert data["upstream_status"] == bad_status
    assert "answer" not in data
