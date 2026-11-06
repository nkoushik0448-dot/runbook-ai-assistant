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
- **Ask the LLM** — `POST /ask-ai` (optional, needs Ollama running
  locally) returns a short answer written by the local `llama3.2:3b`
  model, grounded in the retrieved runbooks only, with citations to
  runbook IDs. No API key, no account. If Ollama is not running it
  answers 503 instead of fabricating anything.
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

`POST /ask` has **no LLM API and no API key**. Retrieval is
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

## LLM answers with Ollama (optional, local) — POST /ask-ai

`POST /ask-ai` adds a real LLM call on top of the same retrieval
(see `app/llm.py`). It is a retrieval-grounded (RAG-style) answer,
without embeddings or a vector database. The model runs entirely on
your own machine via [Ollama](https://ollama.com) — no API key, no
account, and nothing leaves the machine:

1. The question is run through the same deterministic retrieval, and
   the top matching runbooks are taken as context.
2. Only those runbooks — id, title, symptoms, checks, steps — are
   sent to the local Ollama model (`llama3.2:3b` by default), with a
   system prompt that says: answer **only** from the provided
   runbooks, cite their IDs, and say so plainly when they do not
   cover the question.
3. The response returns the model's answer plus the runbooks it was
   grounded in (with relevance scores), the model name, and
   `llm_used: true`, so the answer can be checked against its sources.
   The call is logged to history as type `ask-ai` with the model name.

### Setup

```bash
# Install Ollama (Linux): https://ollama.com/download
curl -fsSL https://ollama.com/install.sh | sh

ollama pull llama3.2:3b   # download the model (about 2 GB, once)
ollama serve              # start the local server, if not already running
```

The model and server address come from the `OLLAMA_MODEL` and
`OLLAMA_HOST` environment variables (defaults `llama3.2:3b` and
`http://localhost:11434`, see `.env.example`).

### When the LLM is not available

- Ollama not running → `POST /ask-ai` returns **503** with
  `error: "llm_unavailable"` and instructions to start it
  (`ollama serve`, `ollama pull llama3.2:3b`). No answer is fabricated.
- Ollama returns an error (e.g. 404 because the model has not been
  pulled, or a 5xx) or is unreachable → `POST /ask-ai` returns **502**
  with `error: "llm_upstream_error"`, the upstream status, and the
  upstream message. No answer is fabricated.
- `POST /ask` keeps working exactly as before with no Ollama at all.

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
`http://127.0.0.1:8000/docs`. To use `POST /ask-ai`, Ollama must be
running locally — see "LLM answers with Ollama" above.

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

# Ask the LLM (needs Ollama running locally)
curl -X POST http://127.0.0.1:8000/ask-ai \
  -H "Content-Type: application/json" \
  -d '{"question": "ClaimCenter login fails after deployment"}'

# History
curl http://127.0.0.1:8000/history
```

## Tests

```bash
pytest -v
```

Tests cover: ask RB-101, ask RB-103, off-topic ask returns an empty
match, too-short ask returns 422, triage of a DB-pool log returns
RB-105, history logging for asks and triages, and /ask-ai with a
mocked Ollama (grounded answer, Ollama-not-running 503, model-not-
pulled 502, /ask still deterministic with no Ollama).

## Project structure

```
runbook-ai-assistant/
├── app/
│   ├── __init__.py
│   ├── main.py        # FastAPI app: /health, /runbooks, /ask, /ask-ai, /triage, /history
│   ├── retrieval.py   # Deterministic keyword scoring (no LLM)
│   ├── llm.py         # Ollama LLM call, grounded in retrieved runbooks
│   └── history.py     # SQLite history logging
├── data/
│   ├── runbooks.json          # 8 SAMPLE runbooks (RB-101–RB-108)
│   └── sample_logs/           # 3 SAMPLE log snippets
├── tests/
│   ├── conftest.py
│   ├── test_ask.py
│   ├── test_llm.py
│   ├── test_triage.py
│   └── test_history.py
├── requirements.txt
├── README.md
├── LICENSE            # MIT
└── .gitignore         # venv, __pycache__, history.db, .env
```

## What is still deliberately simple

- Retrieval is deterministic keyword scoring, and the LLM answers
  only from the retrieved runbooks. The next step is a measured one:
  build an evaluation set — a list of questions with the expected
  runbook id — and a script that reports how often the top match is
  correct. That turns "it worked on 3 examples" into a measured result.
- Consider embeddings / a vector store only after that evaluation
  shows keyword scoring is missing real queries — measure first,
  then upgrade.
- A cloud LLM API can be added the same way later:
  keep retrieval as the first step, pass only the retrieved runbooks
  as context, and keep the API key in a `.env` file (gitignored),
  never in code.

## License

MIT — see `LICENSE`.
