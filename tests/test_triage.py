"""Tests for POST /triage."""


DB_POOL_LOG = """2026-11-05 09:14:02,112 ERROR [ClaimCenter] Cannot get a connection, pool exhausted
2026-11-05 09:14:02,118 ERROR [ClaimCenter] java.sql.SQLException: Cannot get a connection, pool exhausted
2026-11-05 09:14:03,004 ERROR [ClaimCenter] Database connection failed: Connection pool exhausted
"""


def test_triage_db_pool_returns_rb105(client):
    r = client.post("/triage", json={"log": DB_POOL_LOG})
    assert r.status_code == 200
    data = r.json()
    assert data["top_runbook_id"] == "RB-105"
    assert data["suggested_runbook"]["id"] == "RB-105"
    assert data["top_score"] > 0
    assert data["reason"] is not None
    assert "RB-105" in data["reason"]


def test_triage_extracts_error_signals(client):
    r = client.post("/triage", json={"log": DB_POOL_LOG})
    assert r.status_code == 200
    signals = [f["signal"] for f in r.json()["findings"]]
    assert any("Cannot get a connection" in s for s in signals)
    assert any("Connection pool exhausted" in s for s in signals)


def test_triage_too_short_returns_validation_error(client):
    r = client.post("/triage", json={"log": "ok"})
    assert r.status_code == 422
