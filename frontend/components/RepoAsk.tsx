"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";

import { ApiError, askRepo, isRepoMissingError, type AskResponse } from "@/lib/api";
import { handleSubmitShortcut, SUBMIT_SHORTCUT_LABEL } from "@/lib/form-shortcuts";

const MAX_QUESTION_LENGTH = 1000;
// Matches the backend's issue limit for runs.
const MAX_ISSUE_LENGTH = 4000;

/** The Fix issue text: the confirmed bug first, then the evidence Ask found. */
function buildIssue(question: string, result: AskResponse): string {
  const heading = result.issueSummary ?? question;
  return `${heading}\n\nFindings from Ask:\n${result.answer}`.slice(0, MAX_ISSUE_LENGTH);
}

type AskState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "success"; question: string; result: AskResponse };

interface RepoAskProps {
  repoId: string;
  onSelectFile: (path: string) => void;
  onRepoMissing: () => void;
  /** Hands an issue over to the Fix tab. */
  onFixIssue: (issue: string) => void;
}

export function RepoAsk({ repoId, onSelectFile, onRepoMissing, onFixIssue }: RepoAskProps) {
  const [question, setQuestion] = useState("");
  const [state, setState] = useState<AskState>({ status: "idle" });
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const isLoading = state.status === "loading";
  const isEmpty = question.trim().length === 0;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isLoading || isEmpty) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ status: "loading" });

    try {
      const asked = question.trim();
      const result = await askRepo(repoId, asked, controller.signal);
      setState({ status: "success", question: asked, result });
      if (result.isIssueConfirmed) onFixIssue(buildIssue(asked, result));
    } catch (error) {
      if (controller.signal.aborted) return;
      if (isRepoMissingError(error)) {
        onRepoMissing();
        return;
      }
      const message =
        error instanceof ApiError ? error.message : "Something went wrong. Please try again.";
      setState({ status: "error", message });
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <form onSubmit={handleSubmit} className="flex flex-col gap-2">
        <label htmlFor="repo-question" className="text-sm font-medium">
          Ask about this repo
        </label>
        <textarea
          id="repo-question"
          value={question}
          maxLength={MAX_QUESTION_LENGTH}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={handleSubmitShortcut}
          rows={3}
          placeholder="e.g. The cart total is wrong when an item has quantity 2"
          className="w-full resize-y rounded-xl border border-border bg-background p-3 text-sm leading-relaxed outline-none transition-colors placeholder:text-muted focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent-soft"
        />
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={isLoading || isEmpty}
            className="rounded-lg bg-accent px-5 py-2 text-sm font-semibold text-accent-foreground transition-opacity hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isLoading ? "Asking Nemotron…" : "Ask"}
          </button>
          {isEmpty && !isLoading ? (
            <span className="text-sm text-muted">Enter a question to ask.</span>
          ) : (
            <span className="text-xs text-muted">
              <kbd className="rounded border border-border px-1 font-mono">{SUBMIT_SHORTCUT_LABEL}</kbd>{" "}
              to ask
            </span>
          )}
          <span className="ml-auto font-mono text-xs text-muted">
            {question.length}/{MAX_QUESTION_LENGTH}
          </span>
        </div>
      </form>

      <section aria-live="polite" aria-busy={isLoading}>
        <AskResult
          state={state}
          onSelectFile={onSelectFile}
          onFixAnyway={(asked, result) => onFixIssue(buildIssue(asked, result))}
        />
      </section>
    </div>
  );
}

function AskResult({
  state,
  onSelectFile,
  onFixAnyway,
}: {
  state: AskState;
  onSelectFile: (path: string) => void;
  onFixAnyway: (question: string, result: AskResponse) => void;
}) {
  switch (state.status) {
    case "idle":
      return (
        <p className="text-sm text-muted">
          Describe a bug here first. When the answer confirms it, PatchPilot moves to Fix an
          issue and prepares a success checklist.
        </p>
      );
    case "loading":
      return (
        <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-4">
          <p className="text-sm text-muted">Finding relevant files and asking the model…</p>
          <div aria-hidden="true" className="flex flex-col gap-2 motion-safe:animate-pulse">
            <span className="h-2.5 w-11/12 rounded bg-surface-raised" />
            <span className="h-2.5 w-4/5 rounded bg-surface-raised" />
            <span className="h-2.5 w-2/3 rounded bg-surface-raised" />
          </div>
        </div>
      );
    case "error":
      return (
        <p
          role="alert"
          className="rounded-lg border border-danger bg-danger-surface p-3 text-sm text-danger"
        >
          {state.message}
        </p>
      );
    case "success": {
      const { result } = state;
      return (
        <div className="flex flex-col gap-2">
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-xl border border-border bg-surface p-4 font-sans text-sm leading-relaxed">
            {result.answer || "(The model returned an empty answer.)"}
          </pre>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted">Files used:</span>
            {result.files.length === 0 ? (
              <span className="text-muted">none matched</span>
            ) : (
              result.files.map((file) => (
                <button
                  key={file.path}
                  type="button"
                  onClick={() => onSelectFile(file.path)}
                  className="rounded-full border border-border px-2 py-0.5 font-mono hover:bg-surface focus-visible:outline-2 focus-visible:outline-accent"
                >
                  {file.path}
                </button>
              ))
            )}
            <span className="text-muted">
              · {result.model} · {result.latencyMs} ms
            </span>
          </div>
          {result.isIssueConfirmed ? (
            <p className="rounded-lg border border-accent bg-accent-soft px-3 py-2 text-sm text-accent">
              ✓ Bug confirmed. Moved to Fix an issue to prepare the fix.
            </p>
          ) : (
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span className="text-muted">No bug confirmed in the code that was checked.</span>
              <button
                type="button"
                onClick={() => onFixAnyway(state.question, result)}
                className="rounded-md border border-border px-2 py-1 text-xs hover:bg-surface focus-visible:outline-2 focus-visible:outline-accent"
              >
                Fix anyway
              </button>
            </div>
          )}
        </div>
      );
    }
  }
}
