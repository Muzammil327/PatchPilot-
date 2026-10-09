"use client";

import { useEffect, useState } from "react";

import {
  ApiError,
  fetchRelevantFiles,
  fetchRepoSearch,
  isRepoMissingError,
  type RankedFile,
  type SearchResult,
} from "@/lib/api";

type ResultsState =
  | { status: "loading" }
  | { status: "error"; message: string; isRepoMissing: boolean }
  | { status: "success"; ranked: RankedFile[]; search: SearchResult };

interface SearchResultsProps {
  repoId: string;
  query: string;
  onSelectFile: (path: string) => void;
  onClose: () => void;
  onRepoMissing: () => void;
}

export function SearchResults({
  repoId,
  query,
  onSelectFile,
  onClose,
  onRepoMissing,
}: SearchResultsProps) {
  const [state, setState] = useState<ResultsState>({ status: "loading" });
  const isRepoMissing = state.status === "error" && state.isRepoMissing;

  useEffect(() => {
    if (isRepoMissing) onRepoMissing();
  }, [isRepoMissing, onRepoMissing]);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      fetchRelevantFiles(repoId, query, controller.signal),
      fetchRepoSearch(repoId, query, controller.signal),
    ])
      .then(([ranked, search]) => setState({ status: "success", ranked, search }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const message = error instanceof ApiError ? error.message : "Search failed.";
        setState({ status: "error", message, isRepoMissing: isRepoMissingError(error) });
      });
    return () => controller.abort();
  }, [repoId, query]);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-sm font-semibold">
          Results for <span className="font-mono">“{query}”</span>
        </h2>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded-md border border-border px-2 py-1 text-xs hover:bg-surface focus-visible:outline-2 focus-visible:outline-accent"
        >
          Overview
        </button>
      </div>
      <div aria-live="polite">
        <ResultsBody state={state} onSelectFile={onSelectFile} />
      </div>
    </div>
  );
}

function ResultsBody({
  state,
  onSelectFile,
}: {
  state: ResultsState;
  onSelectFile: (path: string) => void;
}) {
  switch (state.status) {
    case "loading":
      return (
        <p className="animate-pulse text-sm text-muted motion-reduce:animate-none">Searching…</p>
      );
    case "error":
      return (
        <p role="alert" className="text-sm text-danger">
          {state.message}
        </p>
      );
    case "success":
      return (
        <div className="flex flex-col gap-5">
          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-medium">Relevant files</h3>
            {state.ranked.length === 0 ? (
              <p className="text-sm text-muted">No relevant files found.</p>
            ) : (
              <ol className="flex flex-col gap-1">
                {state.ranked.map((file) => (
                  <li key={file.path}>
                    <button
                      type="button"
                      onClick={() => onSelectFile(file.path)}
                      className="flex w-full flex-col gap-0.5 rounded-md border border-border px-3 py-2 text-left hover:bg-surface focus-visible:outline-2 focus-visible:outline-accent"
                    >
                      <span className="flex justify-between gap-3 font-mono text-xs">
                        <span className="truncate font-semibold">{file.path}</span>
                        <span className="shrink-0 text-muted">{file.score}</span>
                      </span>
                      <span className="truncate text-xs text-muted">{file.reasons.join(" · ")}</span>
                    </button>
                  </li>
                ))}
              </ol>
            )}
          </section>

          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-medium">
              Matching lines
              {state.search.isTruncated && (
                <span className="font-normal text-muted"> (first {state.search.matches.length})</span>
              )}
            </h3>
            {state.search.matches.length === 0 ? (
              <p className="text-sm text-muted">No lines contain this exact text.</p>
            ) : (
              <ul className="flex flex-col gap-0.5 font-mono text-xs">
                {state.search.matches.map((match) => (
                  <li key={`${match.path}:${match.line}`}>
                    <button
                      type="button"
                      onClick={() => onSelectFile(match.path)}
                      className="flex w-full gap-2 rounded px-1 py-0.5 text-left hover:bg-surface focus-visible:outline-2 focus-visible:outline-accent"
                    >
                      <span className="shrink-0 text-muted">
                        {match.path}:{match.line}
                      </span>
                      <span className="truncate">{match.text}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      );
  }
}
