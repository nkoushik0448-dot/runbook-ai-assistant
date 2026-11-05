"""Tests for GET /health, GET /runbooks, and POST /ask."""


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["runbooks"] == 8


def test_list_runbooks(client):
    r = client.get("/runbooks")
    assert r.status_code == 200
    ids = [rb["id"] for rb in r.json()]
    assert ids == [f"RB-10{i}" for i in range(1, 9)]


def test_ask_login_after_deployment_returns_rb101(client):
    r = client.post("/ask", json={"question": "ClaimCenter login fails after deployment"})
    assert r.status_code == 200
    data = r.json()
    assert data["top_runbook_id"] == "RB-101"
    assert data["top_score"] > 0
    assert data["matches"][0]["id"] == "RB-101"
    assert "login" in data["matches"][0]["matched_terms"]


def test_ask_integration_timeout_returns_rb103(client):
    r = client.post("/ask", json={"question": "integration timeout on payment"})
    assert r.status_code == 200
    data = r.json()
    assert data["top_runbook_id"] == "RB-103"
    assert data["matches"][0]["id"] == "RB-103"


def test_ask_off_topic_returns_empty_match(client):
    r = client.post("/ask", json={"question": "what is the weather today"})
    assert r.status_code == 200
    data = r.json()
    assert data["matches"] == []
    assert data["top_runbook_id"] is None
    assert data["top_score"] == 0


def test_ask_too_short_returns_validation_error(client):
    r = client.post("/ask", json={"question": "hi"})
    assert r.status_code == 422


def test_ask_empty_returns_validation_error(client):
    r = client.post("/ask", json={"question": ""})
    assert r.status_code == 422
