"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";

import { ApiError, askRepo, isRepoMissingError, type AskResponse } from "@/lib/api";

const MAX_QUESTION_LENGTH = 1000;

type AskState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "success"; result: AskResponse };

interface RepoAskProps {
  repoId: string;
  onSelectFile: (path: string) => void;
  onRepoMissing: () => void;
}

export function RepoAsk({ repoId, onSelectFile, onRepoMissing }: RepoAskProps) {
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
      const result = await askRepo(repoId, question.trim(), controller.signal);
      setState({ status: "success", result });
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
          rows={2}
          placeholder="e.g. Which files are related to authentication?"
          className="w-full resize-y rounded-lg border border-border bg-surface p-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-accent"
        />
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={isLoading || isEmpty}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground transition-opacity hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isLoading ? "Asking Nemotron…" : "Ask"}
          </button>
          {isEmpty && !isLoading && (
            <span className="text-sm text-muted">Enter a question to ask.</span>
          )}
        </div>
      </form>

      <section aria-live="polite" aria-busy={isLoading}>
        <AskResult state={state} onSelectFile={onSelectFile} />
      </section>
    </div>
  );
}

function AskResult({
  state,
  onSelectFile,
}: {
  state: AskState;
  onSelectFile: (path: string) => void;
}) {
  switch (state.status) {
    case "idle":
      return (
        <p className="text-sm text-muted">
          Answers use only the most relevant files from this repo.
        </p>
      );
    case "loading":
      return (
        <p className="animate-pulse text-sm text-muted motion-reduce:animate-none">
          Finding relevant files and asking the model…
        </p>
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
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-surface p-3 text-sm">
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
        </div>
      );
    }
  }
}
