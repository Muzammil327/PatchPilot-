# PatchPilot Architecture

PatchPilot is an autonomous coding agent. It takes a GitHub issue, investigates the
repository, patches the code, runs it in a sandbox, repairs its own failures, and reports
success only when a verification contract and an independent reviewer agent both approve.

The phase-by-phase build plan lives in [`phases.md`](phases.md).

## System diagram

```mermaid
flowchart LR
    UI[Next.js Dashboard] -- REST + live events --> API[FastAPI Backend]
    API --> ORCH[Agent Orchestrator]
    ORCH --> LLM[Nebius Token Factory<br/>NVIDIA Nemotron]
    ORCH --> RI[Repo Intelligence<br/>scanner + Tree-sitter map]
    ORCH --> TOOLS[Agent Tools<br/>read/search/write/git]
    ORCH --> SBX[Sandbox Runner<br/>Nebius infrastructure]
    ORCH --> VER[Verification Engine]
    ORCH --> REV[Reviewer Agent]
    RI --> WS[(Isolated Workspace<br/>cloned repo)]
    TOOLS --> WS
    SBX --> WS
    API --> DB[(Run store<br/>runs, attempts, events)]
    API --> GH[GitHub API<br/>clone + PR]
```

## Request lifecycle

1. User connects a repository and describes an issue in the dashboard.
2. Backend clones the repo into an isolated workspace and builds a repo map.
3. Orchestrator derives a **Verification Contract** from the issue.
4. Coding agent plans, selects files, and edits code through tools.
5. Sandbox runs install / test / lint / build; failures feed the **self-repair loop**.
6. Verification engine checks the contract; the **reviewer agent** challenges the patch.
7. On approval, the user views the diff and opens a pull request.
8. Every step is emitted as an event and streamed to the dashboard timeline.

```mermaid
sequenceDiagram
    participant U as User
    participant F as Frontend
    participant B as Backend
    participant A as Coding Agent
    participant S as Sandbox
    participant R as Reviewer
    U->>F: Repo URL + issue
    F->>B: POST /api/runs
    B->>B: Clone, scan, build repo map
    B->>B: Create verification contract
    loop Self-repair (bounded attempts)
        B->>A: Plan + edit with tools
        A->>S: Run tests / lint / build
        S-->>A: Results
    end
    B->>R: Issue + contract + diff + results
    R-->>B: Approved / changes requested
    B-->>F: Events stream + final verdict
    U->>F: Create pull request
```

## Components

| Component | Location | Responsibility |
| --------- | -------- | -------------- |
| Dashboard | `frontend/app/` | Repo explorer, agent timeline, terminal logs, verification panel |
| API client | `frontend/lib/api.ts` | Typed calls to the backend |
| API routes | `backend/app/api/` | Thin handlers: validate, delegate, shape the response |
| Config | `backend/app/config.py` | Single settings object loaded from the root `.env` |
| LLM client | `backend/app/llm/` | Nebius Token Factory calls, model routing, retries, error mapping |
| Repo intelligence | `backend/app/repo/` | Clone, scan, stack detection, repo map, retrieval |
| Agent | `backend/app/agent/` | Orchestrator loop, tools, prompts |
| Sandbox | `backend/app/sandbox/` | Allow-listed command execution with resource limits |
| Verification | `backend/app/verify/` | Contract generation and checking |
| Reviewer | `backend/app/review/` | Independent patch review |
| Run store | `backend/app/store/` | Runs, attempts, events |

## Model routing

| Role | Used for | Setting |
| ---- | -------- | ------- |
| `planner` | Planning, verification contract, review | `MODEL_PLANNER` (Nemotron Ultra) |
| `worker` | Edits, summaries, simple prompts | `MODEL_WORKER` (smaller Nemotron) |

## Error handling

- Provider failures raise a typed `LLMError` inside the backend.
- Handlers map them to `503` (provider not configured) or `502` (provider request failed)
  with a generic message. Raw provider responses, stack traces, and keys never reach the client.
- Retryable statuses (`429`, `5xx`) and transport errors are retried with exponential backoff.

## Security boundaries

- Secrets come only from the root `.env`; `.env.example` holds placeholders.
- Agent file tools are confined to the run's workspace (path-traversal guard).
- The sandbox runs allow-listed commands only, with CPU, memory, time, and network limits.
- The reviewer agent receives the issue, contract, diff, and results — not the coder's reasoning.

## Repository layout

```
PatchPilot/
├── frontend/          # Next.js (TypeScript, App Router, Tailwind)
├── backend/           # FastAPI (Python)
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/
│   │   └── llm/
│   └── tests/
├── architecture.md
├── phases.md
├── .env.example
└── README.md
```
