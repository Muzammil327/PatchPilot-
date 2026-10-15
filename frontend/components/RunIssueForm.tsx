"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";

import { ApiError, createVerificationContract, isRepoMissingError, startRun, type VerificationCriterion } from "@/lib/api";

const MAX_ISSUE_LENGTH = 4000;

type FormState = { status: "idle" } | { status: "generating" } | { status: "review" } | { status: "starting" } | { status: "error"; message: string };

interface RunIssueFormProps {
  repoId: string;
  onRunStarted: (runId: string) => void;
  onRepoMissing: () => void;
}

export function RunIssueForm({ repoId, onRunStarted, onRepoMissing }: RunIssueFormProps) {
  const [issue, setIssue] = useState("");
  const [state, setState] = useState<FormState>({ status: "idle" });
  const [criteria, setCriteria] = useState<VerificationCriterion[] | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const isBusy = state.status === "starting" || state.status === "generating";
  const isEmpty = issue.trim().length === 0;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isBusy || isEmpty || (criteria && (!criteria.length || criteria.some((item) => !item.description.trim())))) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setState(criteria ? { status: "starting" } : { status: "generating" });

    try {
      if (!criteria) {
        const contract = await createVerificationContract(repoId, issue.trim(), controller.signal);
        setCriteria(contract.criteria);
        setState({ status: "review" });
        return;
      }
      const { runId } = await startRun(repoId, issue.trim(), { criteria }, controller.signal);
      setCriteria(null);
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
        onChange={(event) => { setIssue(event.target.value); setCriteria(null); setState({ status: "idle" }); }}
        rows={2}
        placeholder="e.g. The total() function in lib/cart.ts returns 0 instead of summing item prices."
        className="w-full resize-y rounded-lg border border-border bg-surface p-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-accent"
      />
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={isBusy || isEmpty}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground transition-opacity hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          {state.status === "generating" ? "Creating checklist…" : state.status === "starting" ? "Starting…" : criteria ? "Start with this checklist" : "Create success checklist"}
        </button>
        {isEmpty && !isBusy && (
          <span className="text-sm text-muted">Describe an issue to run the agent.</span>
        )}
      </div>
      {criteria && <section className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-3">
        <h3 className="text-sm font-medium">Review success checklist before the agent edits</h3>
        {criteria.map((criterion, index) => <div key={criterion.id} className="flex gap-2">
          <input aria-label={`Success criterion ${index + 1}`} value={criterion.description} maxLength={300}
            onChange={(event) => setCriteria((items) => items?.map((item, i) => i === index ? { ...item, description: event.target.value } : item) ?? null)}
            className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1 text-sm" />
          {criterion.kind !== "tests_pass" && <button type="button" aria-label={`Remove criterion ${index + 1}`} onClick={() => setCriteria((items) => items?.filter((_, i) => i !== index) ?? null)} className="rounded border border-border px-2 text-sm">Remove</button>}
        </div>)}
        {criteria.length < 12 && <button type="button" onClick={() => setCriteria((items) => [...(items ?? []), { id: `custom_${Date.now()}`, description: "", kind: "behavior", required: true }])} className="self-start text-xs text-accent underline">Add criterion</button>}
        <p className="text-xs text-muted">Every listed item is required for approval.</p>
      </section>}
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
