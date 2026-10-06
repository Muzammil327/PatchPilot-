"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";

import { ApiError, fetchPromptCompletion, type PromptResponse } from "@/lib/api";

type RequestState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "success"; result: PromptResponse };

export function PromptForm() {
  const [prompt, setPrompt] = useState("");
  const [state, setState] = useState<RequestState>({ status: "idle" });
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const isLoading = state.status === "loading";
  const isPromptEmpty = prompt.trim().length === 0;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isLoading || isPromptEmpty) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ status: "loading" });

    try {
      const result = await fetchPromptCompletion(prompt.trim(), controller.signal);
      setState({ status: "success", result });
    } catch (error) {
      if (controller.signal.aborted) return;
      const message =
        error instanceof ApiError ? error.message : "Something went wrong. Please try again.";
      setState({ status: "error", message });
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <label htmlFor="prompt" className="text-sm font-medium">
          Coding prompt
        </label>
        <textarea
          id="prompt"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          rows={3}
          placeholder="e.g. Write a Python function that deduplicates Stripe webhook events by ID."
          className="w-full resize-y rounded-lg border border-border bg-surface p-3 font-mono text-sm outline-none focus-visible:ring-2 focus-visible:ring-accent"
        />
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={isLoading || isPromptEmpty}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground transition-opacity hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isLoading ? "Asking Nemotron…" : "Send"}
          </button>
          {isPromptEmpty && !isLoading && (
            <span className="text-sm text-muted">Enter a prompt to send.</span>
          )}
        </div>
      </form>

      <section aria-live="polite" aria-busy={isLoading} className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">Response</h2>
        <PromptResult state={state} />
      </section>
    </div>
  );
}

function PromptResult({ state }: { state: RequestState }) {
  switch (state.status) {
    case "idle":
      return (
        <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted">
          No response yet. Send a prompt to see the model output here.
        </p>
      );
    case "loading":
      return (
        <p className="animate-pulse rounded-lg border border-border bg-surface p-4 text-sm text-muted motion-reduce:animate-none">
          Waiting for the model…
        </p>
      );
    case "error":
      return (
        <p
          role="alert"
          className="rounded-lg border border-danger bg-danger-surface p-4 text-sm text-danger"
        >
          {state.message}
        </p>
      );
    case "success":
      return (
        <div className="flex flex-col gap-2">
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-surface p-4 font-mono text-sm">
            {state.result.output || "(The model returned an empty response.)"}
          </pre>
          <p className="text-xs text-muted">
            {state.result.model} · {state.result.latencyMs} ms
          </p>
        </div>
      );
  }
}
