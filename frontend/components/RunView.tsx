"use client";

import { useEffect, useState } from "react";

import { DiffView } from "@/components/DiffView";
import {
  ApiError,
  fetchRun,
  isRepoMissingError,
  isRunMissingError,
  type AgentPlan,
  type AgentRun,
  type RunEvent,
  type RunStatus,
} from "@/lib/api";

const POLL_INTERVAL_MS = 1500;
const MS_PER_SECOND = 1000;
const ARGUMENT_PREVIEW_CHARS = 90;

type RunViewState =
  | { status: "loading" }
  | { status: "error"; message: string; isRepoMissing: boolean }
  | { status: "loaded"; run: AgentRun; elapsedSeconds: number };

const STATUS_LABEL: Record<RunStatus, string> = {
  running: "Running",
  succeeded: "Succeeded",
  no_changes: "No changes",
  failed: "Failed",
};

const STATUS_CLASS: Record<RunStatus, string> = {
  running: "border-border bg-surface text-foreground motion-safe:animate-pulse",
  succeeded: "border-accent bg-accent text-accent-foreground",
  no_changes: "border-border bg-surface text-muted",
  failed: "border-danger bg-danger-surface text-danger",
};

const EVENT_ICON: Record<RunEvent["type"], string> = {
  started: "▶",
  plan: "🧭",
  model_message: "💬",
  tool_call: "→",
  tool_result: "✓",
  finished: "■",
  failed: "✕",
};

interface RunViewProps {
  repoId: string;
  runId: string;
  onSelectFile: (path: string) => void;
  onRepoMissing: () => void;
  onClose: () => void;
}

export function RunView({ repoId, runId, onSelectFile, onRepoMissing, onClose }: RunViewProps) {
  const [state, setState] = useState<RunViewState>({ status: "loading" });
  const isRepoMissing = state.status === "error" && state.isRepoMissing;

  useEffect(() => {
    if (isRepoMissing) onRepoMissing();
  }, [isRepoMissing, onRepoMissing]);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function poll() {
      try {
        const run = await fetchRun(repoId, runId, controller.signal);
        const end = run.finishedAt ? Date.parse(run.finishedAt) : Date.now();
        const elapsedSeconds = Math.max(0, Math.round((end - Date.parse(run.createdAt)) / MS_PER_SECOND));
        setState({ status: "loaded", run, elapsedSeconds });
        if (run.status === "running") timer = setTimeout(poll, POLL_INTERVAL_MS);
      } catch (error) {
        if (controller.signal.aborted) return;
        const message = isRunMissingError(error)
          ? "This run is no longer available. The backend restarted; start the run again."
          : error instanceof ApiError
            ? error.message
            : "Could not load the run.";
        setState({ status: "error", message, isRepoMissing: isRepoMissingError(error) });
      }
    }

    void poll();
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [repoId, runId]);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-sm font-semibold">Agent run</h2>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded-md border border-border px-2 py-1 text-xs hover:bg-surface focus-visible:outline-2 focus-visible:outline-accent"
        >
          Overview
        </button>
      </div>
      <div aria-live="polite">
        <RunBody state={state} onSelectFile={onSelectFile} />
      </div>
    </div>
  );
}

function RunBody({
  state,
  onSelectFile,
}: {
  state: RunViewState;
  onSelectFile: (path: string) => void;
}) {
  switch (state.status) {
    case "loading":
      return (
        <p className="animate-pulse text-sm text-muted motion-reduce:animate-none">
          Starting the agent…
        </p>
      );
    case "error":
      return (
        <p role="alert" className="rounded-lg border border-danger bg-danger-surface p-3 text-sm text-danger">
          {state.message}
        </p>
      );
    case "loaded": {
      const { run, elapsedSeconds } = state;
      return (
        <div className="flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-3 text-xs">
              <span className={`rounded-full border px-3 py-1 font-semibold ${STATUS_CLASS[run.status]}`}>
                {STATUS_LABEL[run.status]}
              </span>
              <span className="text-muted">
                {run.steps} {run.steps === 1 ? "step" : "steps"} · {elapsedSeconds}s
              </span>
            </div>
            <p className="text-sm">{run.issue}</p>
          </div>

          {run.plan && <PlanCard plan={run.plan} onSelectFile={onSelectFile} />}

          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-medium">Timeline</h3>
            <ol className="flex flex-col gap-1">
              {run.events.map((event) => (
                <TimelineItem key={event.seq} event={event} />
              ))}
            </ol>
          </section>

          {run.status === "failed" && run.error && (
            <p role="alert" className="rounded-lg border border-danger bg-danger-surface p-3 text-sm text-danger">
              {run.error}
            </p>
          )}

          {run.summary && (
            <section className="flex flex-col gap-2">
              <h3 className="text-sm font-medium">Summary</h3>
              <p className="whitespace-pre-wrap rounded-lg border border-border bg-surface p-3 text-sm">
                {run.summary}
              </p>
            </section>
          )}

          {run.status === "succeeded" && (
            <section className="flex flex-col gap-2">
              <h3 className="text-sm font-medium">Changes</h3>
              <DiffView diff={run.diff} onSelectFile={onSelectFile} />
              <p className="text-xs text-muted">
                Applied to PatchPilot&apos;s working copy only; the GitHub repository is unchanged.
              </p>
            </section>
          )}
          {run.status === "no_changes" && (
            <p className="text-sm text-muted">The agent finished without changing any files.</p>
          )}
        </div>
      );
    }
  }
}

function PlanCard({
  plan,
  onSelectFile,
}: {
  plan: AgentPlan;
  onSelectFile: (path: string) => void;
}) {
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4">
      <h3 className="text-sm font-medium">Plan</h3>
      <p className="text-sm">
        <span className="text-muted">Likely root cause: </span>
        {plan.rootCause}
      </p>
      {plan.filesToInspect.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted">Files:</span>
          {plan.filesToInspect.map((path) => (
            <button
              key={path}
              type="button"
              onClick={() => onSelectFile(path)}
              className="rounded-full border border-border px-2 py-0.5 font-mono hover:bg-background focus-visible:outline-2 focus-visible:outline-accent"
            >
              {path}
            </button>
          ))}
        </div>
      )}
      <ol className="flex list-decimal flex-col gap-1 pl-5 text-sm">
        {plan.steps.map((step, index) => (
          <li key={`${index}:${step}`}>{step}</li>
        ))}
      </ol>
      {plan.testsToAdd.length > 0 && (
        <div className="text-sm">
          <p className="text-muted">Tests to add:</p>
          <ul className="flex list-disc flex-col gap-1 pl-5">
            {plan.testsToAdd.map((test, index) => (
              <li key={`${index}:${test}`}>{test}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function argumentPreview(event: RunEvent): string {
  if (event.type !== "tool_call" || !event.detail) return "";
  const compact = event.detail.replace(/\s+/g, " ");
  return compact.length > ARGUMENT_PREVIEW_CHARS
    ? `${compact.slice(0, ARGUMENT_PREVIEW_CHARS)}…`
    : compact;
}

function TimelineItem({ event }: { event: RunEvent }) {
  const isFailure = event.type === "failed" || event.message.includes(" failed ");
  const preview = argumentPreview(event);
  const line = (
    <span className="flex min-w-0 gap-2">
      <span aria-hidden="true" className="w-4 shrink-0 text-center">
        {EVENT_ICON[event.type]}
      </span>
      <span className={`shrink-0 ${isFailure ? "text-danger" : ""}`}>{event.message}</span>
      {preview && <span className="truncate text-muted">{preview}</span>}
    </span>
  );

  if (!event.detail) {
    return <li className="px-2 py-1 font-mono text-xs">{line}</li>;
  }
  return (
    <li className="font-mono text-xs">
      <details className="rounded px-2 py-1 open:bg-surface">
        <summary className="cursor-pointer list-none hover:underline focus-visible:outline-2 focus-visible:outline-accent">
          {line}
        </summary>
        <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap border-t border-border pt-2 text-muted">
          {event.detail}
        </pre>
      </details>
    </li>
  );
}
