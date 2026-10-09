"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";

import { ApiError, isRepoMissingError, startRun } from "@/lib/api";

const MAX_ISSUE_LENGTH = 4000;

type FormState = { status: "idle" } | { status: "starting" } | { status: "error"; message: string };

interface RunIssueFormProps {
  repoId: string;
  onRunStarted: (runId: string) => void;
  onRepoMissing: () => void;
}

export function RunIssueForm({ repoId, onRunStarted, onRepoMissing }: RunIssueFormProps) {
  const [issue, setIssue] = useState("");
  const [state, setState] = useState<FormState>({ status: "idle" });
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const isStarting = state.status === "starting";
  const isEmpty = issue.trim().length === 0;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isStarting || isEmpty) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ status: "starting" });

    try {
      const { runId } = await startRun(repoId, issue.trim(), controller.signal);
      setState({ status: "idle" });
      onRunStarted(runId);
    } catch (error) {
      if (controller.signal.aborted) return;
      if (isRepoMissingError(error)) {
        onRepoMissing();
        return;
      }
      const message =
        error instanceof ApiError ? error.message : "Could not start the agent. Please try again.";
      setState({ status: "error", message });
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2">
      <label htmlFor="run-issue" className="text-sm font-medium">
        Describe the bug or change
      </label>
      <textarea
        id="run-issue"
        value={issue}
        maxLength={MAX_ISSUE_LENGTH}
        onChange={(event) => setIssue(event.target.value)}
        rows={2}
        placeholder="e.g. The total() function in lib/cart.ts returns 0 instead of summing item prices."
        className="w-full resize-y rounded-lg border border-border bg-surface p-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-accent"
      />
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={isStarting || isEmpty}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground transition-opacity hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isStarting ? "Starting…" : "Run agent"}
        </button>
        {isEmpty && !isStarting && (
          <span className="text-sm text-muted">Describe an issue to run the agent.</span>
        )}
      </div>
      {state.status === "error" && (
        <p role="alert" className="rounded-lg border border-danger bg-danger-surface p-3 text-sm text-danger">
          {state.message}
        </p>
      )}
      <p className="text-xs text-muted">
        The agent edits a temporary copy of the repository. Your GitHub repository is never changed.
      </p>
    </form>
  );
}
