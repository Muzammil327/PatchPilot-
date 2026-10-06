"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";

import { ApiError, createRepo, type RepoSummary } from "@/lib/api";

type RequestState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string };

interface RepoConnectProps {
  onConnected: (repo: RepoSummary) => void;
}

export function RepoConnect({ onConnected }: RepoConnectProps) {
  const [url, setUrl] = useState("");
  const [state, setState] = useState<RequestState>({ status: "idle" });
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const isLoading = state.status === "loading";
  const isUrlEmpty = url.trim().length === 0;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isLoading || isUrlEmpty) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ status: "loading" });

    try {
      const repo = await createRepo(url.trim(), controller.signal);
      onConnected(repo);
    } catch (error) {
      if (controller.signal.aborted) return;
      const message =
        error instanceof ApiError ? error.message : "Something went wrong. Please try again.";
      setState({ status: "error", message });
    }
  }

  return (
    <section className="flex flex-col gap-4 rounded-xl border border-border p-4 sm:p-6">
      <h2 className="text-lg font-semibold">Connect repository</h2>
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <label htmlFor="repo-url" className="text-sm font-medium">
          Public GitHub URL
        </label>
        <div className="flex flex-col gap-3 sm:flex-row">
          <input
            id="repo-url"
            type="url"
            inputMode="url"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://github.com/owner/repo"
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-sm outline-none focus-visible:ring-2 focus-visible:ring-accent"
          />
          <button
            type="submit"
            disabled={isLoading || isUrlEmpty}
            className="shrink-0 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground transition-opacity hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isLoading ? "Cloning…" : "Connect"}
          </button>
        </div>
        {isUrlEmpty && !isLoading && (
          <span className="text-sm text-muted">Enter a repository URL to connect.</span>
        )}
      </form>

      <div aria-live="polite" aria-busy={isLoading}>
        {state.status === "loading" && (
          <p className="animate-pulse rounded-lg border border-border bg-surface p-4 text-sm text-muted motion-reduce:animate-none">
            Cloning and scanning the repository…
          </p>
        )}
        {state.status === "error" && (
          <p
            role="alert"
            className="rounded-lg border border-danger bg-danger-surface p-4 text-sm text-danger"
          >
            {state.message}
          </p>
        )}
      </div>
    </section>
  );
}
