# PatchPilot

An autonomous coding agent for the **Coding & Agentic Engineering Track**, powered by
**NVIDIA Nemotron** models served through **Nebius Token Factory**.

Give PatchPilot a GitHub repository and a bug description. It investigates the codebase,
forms a hypothesis, patches the code, runs the tests in a sandbox, repairs its own failed
attempts, and only marks the patch as done when a verification contract and an independent
reviewer agent both approve. Then it opens a pull request.

```
PATCH VERIFIED ✓

Tests: 24/24
Lint: Passed
Build: Passed
Reviewer: Approved
```

## Features

| Feature | Phase | Status |
| ------- | ----- | ------ |
| Prompt → Nemotron → response | 1 | In progress |
| Repository scan, repo map, relevant-file retrieval | 2 | Planned |
| Autonomous plan → edit → diff agent loop | 3 | Planned |
| Sandbox execution with self-repair | 4 | Planned |
| Verification contract + reviewer agent | 5 | Planned |
| Dashboard, diff view, pull request creation | 6 | Planned |

Full roadmap: [`phases.md`](phases.md) · Architecture: [`docs/architecture.md`](docs/architecture.md)

## Tech stack

- **Frontend:** Next.js (TypeScript, App Router), Tailwind CSS
- **Backend:** FastAPI (Python 3.11+), httpx, pydantic-settings
- **Models:** NVIDIA Nemotron via Nebius Token Factory
- **Execution:** sandboxed runs on Nebius infrastructure *(Phase 4)*

## Project structure

```
PatchPilot/
├── frontend/          # Next.js dashboard
├── backend/           # FastAPI API + agent
├── docs/              # Architecture docs
├── phases.md          # Build plan
└── .env.example       # Environment variable template
```

## Getting started

### Prerequisites

- Node.js 20+ and npm
- Python 3.11+
- A Nebius Token Factory API key

### 1. Configure environment

```bash
cp .env.example .env
# edit .env: NEBIUS_API_KEY, NEBIUS_BASE_URL, MODEL_PLANNER, MODEL_WORKER
```

Optional, only if the backend is not on `http://localhost:8000`:

```bash
echo "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000" > frontend/.env.local
```

### 2. Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

API: <http://localhost:8000> · Interactive docs: <http://localhost:8000/docs>

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

App: <http://localhost:3000>

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `NEBIUS_API_KEY` | Yes | Nebius Token Factory API key |
| `NEBIUS_BASE_URL` | Yes | Token Factory OpenAI-compatible base URL |
| `MODEL_PLANNER` | Yes | Nemotron model for planning and review |
| `MODEL_WORKER` | Yes | Nemotron model for simpler tasks |
| `LLM_TIMEOUT_SECONDS` | No | Request timeout (default `60`) |
| `LLM_MAX_RETRIES` | No | Retries for 429/5xx (default `2`) |
| `FRONTEND_ORIGIN` | No | Allowed CORS origin (default `http://localhost:3000`) |
| `LOG_LEVEL` | No | Backend log level (default `INFO`) |
| `GITHUB_TOKEN` | Phase 2+ | GitHub access for cloning and PRs |
| `NEXT_PUBLIC_API_BASE_URL` | No | Backend URL for the frontend (`frontend/.env.local`) |

## API

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/health` | Liveness check |
| `POST` | `/api/prompt` | `{ "prompt": string }` → `{ "output", "model", "latencyMs" }` |

## Development commands

| Task | Backend (`backend/`) | Frontend (`frontend/`) |
| ---- | -------------------- | ---------------------- |
| Dev server | `uvicorn app.main:app --reload` | `npm run dev` |
| Test | `pytest` | — |
| Lint | `ruff check .` | `npm run lint` |
| Format | `ruff format .` | — |
| Build | — | `npm run build` |

## License

TBD
