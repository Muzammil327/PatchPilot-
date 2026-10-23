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

## How it works

1. **Sign in** — continue with GitHub. Every API call except `/health` requires a signed-in
   session.
2. **Connect a repository** — paste a public GitHub URL. PatchPilot clones it, scans it, and
   builds a repo map (stack, routes, tests, files).
3. **Ask** — ask questions about the code or describe a suspected bug. Ask answers from the
   repository and ends with a verdict: bug confirmed (with a one-line summary) or no bug.
4. **Fix** — a confirmed bug is handed over to Fix with the summary and Ask's findings, and a
   success checklist (verification contract) is drafted for review. Fix stays locked until Ask
   confirms a bug or you choose **Fix anyway**. The agent then plans, edits, runs
   install/test/lint/build in a Docker sandbox, repairs failures, and is checked by an
   independent reviewer. Progress, diff, and verdict show live in the run view.
5. **Pull request** — open a PR from a finished run as the signed-in user. Repos you can push to
   get a branch directly; any other public repo is forked into your account first.

Full roadmap: [`phases.md`](phases.md) · Architecture: [`architecture.md`](architecture.md)

## Platform

| Part | Host | Role |
| ---- | ---- | ---- |
| Frontend | Vercel | Next.js app; forwards `/api/*` to the backend |
| Backend | Railway | FastAPI API + agent; `railway.json` sets the start command and `/health` check |
| Models | Nebius Token Factory | NVIDIA Nemotron |
| Code host | GitHub | OAuth sign-in, cloning, pull requests |

The browser only talks to the Vercel site. Next.js rewrites `/api/*` to the Railway backend,
so the session cookie is first-party and no cross-site cookie is needed.

```
Browser ──> Vercel (Next.js) ──/api/*──> Railway (FastAPI) ──> Nebius / GitHub
```

### Deployment settings

Set these in each host's dashboard (values are never committed):

| Where | Variable | Value |
| ----- | -------- | ----- |
| Vercel | `BACKEND_URL` | The Railway backend URL |
| Vercel | `NEXT_PUBLIC_API_BASE_URL` | The Vercel frontend's own URL |
| Railway | `NEBIUS_API_KEY`, `NEBIUS_BASE_URL`, `MODEL_PLANNER`, `MODEL_WORKER` | Model provider settings |
| Railway | `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | From the GitHub OAuth App |
| Railway | `GITHUB_CALLBACK_URL` | `<frontend URL>/api/auth/github/callback` (must match the OAuth App) |
| Railway | `FRONTEND_ORIGIN` | The Vercel frontend URL |
| Railway | `SESSION_COOKIE_CROSS_SITE` | `false` (the `/api` rewrite keeps the cookie first-party) |

Sessions, connected repositories, and runs are held in memory, so a backend redeploy signs
everyone out and clears them. If Docker is not available on the backend host, a run still
finishes but is marked **unverified** instead of verified.

## Tech stack

- **Frontend:** Next.js (TypeScript, App Router), Tailwind CSS
- **Backend:** FastAPI (Python 3.11+), httpx, pydantic-settings
- **Models:** NVIDIA Nemotron via Nebius Token Factory
- **Execution:** allow-listed install/test/lint/build commands in Docker containers

## Project structure

```
PatchPilot/
├── frontend/          # Next.js dashboard
├── backend/           # FastAPI API + agent (Railway config: railway.json, railpack.json)
├── architecture.md    # Architecture
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
| `MODEL_REVIEWER` | No | Optional separate model for independent patch review; defaults to `MODEL_PLANNER` |
| `AGENT_MAX_REVIEW_ROUNDS` | No | Maximum verification/reviewer repair rounds (default `2`) |
| `LLM_TIMEOUT_SECONDS` | No | Request timeout (default `60`) |
| `LLM_MAX_RETRIES` | No | Retries for 429/5xx (default `2`) |
| `FRONTEND_ORIGIN` | No | Allowed CORS origin (default `http://localhost:3000`) |
| `LOG_LEVEL` | No | Backend log level (default `INFO`) |
| `GITHUB_CLIENT_ID` | Yes | GitHub OAuth App client ID for sign-in |
| `GITHUB_CLIENT_SECRET` | Yes | GitHub OAuth App client secret |
| `GITHUB_CALLBACK_URL` | Yes | Must match the OAuth App's callback URL exactly |
| `SESSION_COOKIE_CROSS_SITE` | No | `true` only when frontend and backend are on different sites without the `/api` rewrite (default `false`) |
| `GITHUB_TOKEN` | No | GitHub access for cloning |
| `NEXT_PUBLIC_API_BASE_URL` | No | Backend URL for the frontend (`frontend/.env.local`) |
| `BACKEND_URL` | No | Frontend host only: forwards `/api/*` to this backend so the session cookie is first-party |

## API

All `/api/*` routes except `/api/auth/*` require a signed-in session.

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/health` | Liveness check |
| `GET` | `/api/auth/github/login` | Start GitHub sign-in |
| `GET` | `/api/auth/github/callback` | OAuth callback; sets the session cookie |
| `GET` | `/api/auth/me` | Signed-in user |
| `POST` | `/api/auth/logout` | Sign out |
| `POST` | `/api/repos` | Connect a repository by URL |
| `GET` | `/api/repos/{repoId}` | Repository summary |
| `GET` | `/api/repos/{repoId}/map` | Repo map |
| `GET` | `/api/repos/{repoId}/search` | Code search |
| `POST` | `/api/repos/{repoId}/ask` | Ask; returns the answer plus `isIssueConfirmed` / `issueSummary` |
| `POST` | `/api/repos/{repoId}/runs/contract` | Draft the success checklist for an issue |
| `POST` | `/api/repos/{repoId}/runs` | Start a Fix run |
| `GET` | `/api/repos/{repoId}/runs/active` | Active run for the repository |
| `GET` | `/api/repos/{repoId}/runs/{runId}` | Run progress, diff, and verdict (poll) |
| `POST` | `/api/repos/{repoId}/runs/{runId}/cancel` | Cancel a run |
| `POST` | `/api/repos/{repoId}/runs/{runId}/pull-request` | Open a pull request from a finished run |
| `POST` | `/api/repos/{repoId}/commands` | Run an allow-listed command in the sandbox |
| `POST` | `/api/prompt` | `{ "prompt": string }` → `{ "output", "model", "latencyMs" }` |

## Development commands

| Task | Backend (`backend/`) | Frontend (`frontend/`) |
| ---- | -------------------- | ---------------------- |
| Dev server | `uvicorn app.main:app --reload` | `npm run dev` |
| Test | `pytest` | — |
| Lint | `ruff check .` | `npm run lint` |
| Format | `ruff format .` | — |
| Build | — | `npm run build` |

## Planned

- Faster code search with ripgrep
- Private repositories
- Persistent storage for sessions, repositories, and runs (survives redeploys)
- LLM re-ranking of retrieved files
- Python route and test mapping in the repo map

## License

TBD
