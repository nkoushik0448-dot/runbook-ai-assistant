"""Tests for GET /history logging."""


def test_history_logs_ask(client):
    before = client.get("/history")
    assert before.status_code == 200
    count_before = len(before.json())

    r = client.post(
        "/ask", json={"question": "integration timeout on payment for history test"}
    )
    assert r.status_code == 200

    after = client.get("/history")
    assert after.status_code == 200
    entries = after.json()
    assert len(entries) == count_before + 1
    latest = entries[0]  # newest first
    assert latest["type"] == "ask"
    assert "integration timeout on payment" in latest["input"]
    assert "RB-103" in latest["matched_runbook_ids"]
    assert latest["top_score"] > 0
    assert latest["timestamp"]


def test_history_logs_triage(client):
    before = client.get("/history")
    count_before = len(before.json())

    r = client.post(
        "/triage",
        json={"log": "ERROR Cannot get a connection, pool exhausted"},
    )
    assert r.status_code == 200

    after = client.get("/history")
    entries = after.json()
    assert len(entries) == count_before + 1
    assert entries[0]["type"] == "triage"
    assert "RB-105" in entries[0]["matched_runbook_ids"]
