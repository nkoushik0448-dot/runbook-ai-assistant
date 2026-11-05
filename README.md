# Runbook AI Assistant

A working demo that answers production-support questions from a library of
**SAMPLE** Guidewire ClaimCenter-style runbooks, and triages pasted log
snippets to the right runbook.

## Problem

During a production incident, support engineers lose time searching
runbooks and logs to find the right fix. This assistant retrieves the
most relevant runbook for a question, explains why it matched, and
logs every query so the team can see what was asked and what was found.

## What it does

- **Ask a question** — `POST /ask` returns ranked runbook matches with a
  relevance score (0–100), the matched terms, and the full runbook:
  symptoms, checks, steps, and escalation.
- **Triage a log** — `POST /triage` extracts error signals from a pasted
  log snippet, suggests the matching runbook, and explains why.
- **Browse runbooks** — `GET /runbooks` lists all 8 SAMPLE runbooks.
- **History / observability** — `GET /history` lists every ask and triage
  with a timestamp, matched runbook ids, and top score. History is stored
  in a local SQLite file (`history.db`, gitignored).
- **Validation and honest empty matches** — empty or too-short questions
  return a clear 422 error. A question that matches no runbook returns
  an empty match list, not an invented answer.

## How retrieval works — honestly

There is **no LLM API and no API key** in this version. Retrieval is
**deterministic keyword scoring** (see `app/retrieval.py`):

1. The input is normalised to lower case.
2. Each runbook has a keyword list. A keyword that appears in the input
   scores points: 10 for a single word, 20 for a multi-word phrase.
3. Scores are capped at 100. Runbooks are ranked by score, then by id.

That is deliberately simple and explainable. It is enough to rank the
verified examples correctly:

- "ClaimCenter login fails after deployment" → **RB-101** top
- "integration timeout on payment" → **RB-103** top
- A database-pool log with "Cannot get a connection" /
  "Connection pool exhausted" → **RB-105** top

## Sample data

All data in `data/` is **SAMPLE** data, labelled as such. It is not
production data and does not come from any employer:

- `data/runbooks.json` — 8 SAMPLE runbooks: RB-101 Login & Authentication
  Failure After Deployment, RB-102 Slow Claim Intake, RB-103 Integration
  Timeout — Payment, RB-104 Batch Job Failure, RB-105 Database Connection
  Errors & Pool Exhaustion, RB-106 Deployment Rollback, RB-107 Log Triage,
  RB-108 Message Queue Backlog.
- `data/sample_logs/` — 3 SAMPLE log snippets: `db_pool.txt`,
  `login_auth.txt`, `integration_timeout.txt`.

## How to run locally

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API is then at `http://127.0.0.1:8000`. Interactive docs are at
`http://127.0.0.1:8000/docs`.

## API examples (curl)

```bash
# Health
curl http://127.0.0.1:8000/health

# List runbooks
curl http://127.0.0.1:8000/runbooks

# Ask a question
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "ClaimCenter login fails after deployment"}'

# Triage a log (use a file to avoid shell-quoting the log)
curl -X POST http://127.0.0.1:8000/triage \
  -H "Content-Type: application/json" \
  --data @<(python3 -c "import json; print(json.dumps({'log': open('data/sample_logs/db_pool.txt').read()}))")

# History
curl http://127.0.0.1:8000/history
```

## Tests

```bash
pytest -v
```

Tests cover: ask RB-101, ask RB-103, off-topic ask returns an empty
match, too-short ask returns 422, triage of a DB-pool log returns
RB-105, and history logging for asks and triages.

## Project structure

```
runbook-ai-assistant/
├── app/
│   ├── __init__.py
│   ├── main.py        # FastAPI app: /health, /runbooks, /ask, /triage, /history
│   ├── retrieval.py   # Deterministic keyword scoring (no LLM)
│   └── history.py     # SQLite history logging
├── data/
│   ├── runbooks.json          # 8 SAMPLE runbooks (RB-101–RB-108)
│   └── sample_logs/           # 3 SAMPLE log snippets
├── tests/
│   ├── conftest.py
│   ├── test_ask.py
│   ├── test_triage.py
│   └── test_history.py
├── requirements.txt
├── README.md
├── LICENSE            # MIT
└── .gitignore         # venv, __pycache__, history.db, .env
```

## How to add a real LLM API later

This version intentionally has no LLM, so the next step is a clean
extension, not a rewrite:

1. Keep retrieval as the first step — retrieve the top 1–3 runbooks
   exactly as now, and pass **only those runbooks** to the model.
2. Add an LLM call (e.g. OpenAI API) that answers *from the retrieved
   runbooks only*, with citations to the runbook id and step numbers.
   Keep the API key in a `.env` file (gitignored), never in code.
3. Add an evaluation set: a list of questions with the expected
   runbook id, and a script that reports how often the top match is
   correct. That turns "it worked on 3 examples" into a measured result.
4. Consider embeddings / a vector store only after step 3 shows
   keyword scoring is missing real queries — measure first, then upgrade.

## License

MIT — see `LICENSE`.
